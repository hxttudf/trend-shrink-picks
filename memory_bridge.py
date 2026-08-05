#!/usr/bin/env python3
"""
Hermes Memory Bridge — feeds session data to MemOS and claude-mem.

Architecture:
  1. Spawns MemOS bridge as child process (stdio JSON-RPC)
  2. Sends session/episode/turn lifecycle events
  3. Reads Hermes session data and converts to MemOS format
  
Usage (background):
  nohup python3 ~/.hermes/scripts/memory_bridge.py > /tmp/memory_bridge.log 2>&1 &

Protocol: Line-delimited JSON-RPC 2.0 over stdin/stdout
"""

import subprocess
import json
import sys
import time
import os
import signal
import threading
import queue
from datetime import datetime
from pathlib import Path

# ─── Config ───────────────────────────────────────────────────────────────
MEMOS_PLUGIN_DIR = Path.home() / ".hermes" / "memos-plugin"
MEMOS_BRIDGE = "bridge.cts"
HERMES_SESSIONS_DIR = Path.home() / ".hermes" / "sessions"
HERMES_SESSIONS_JSON = HERMES_SESSIONS_DIR / "sessions.json"

# ─── Helpers ──────────────────────────────────────────────────────────────

def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", file=sys.stderr, flush=True)

def make_jsonrpc(method: str, params: dict = None, id_: int = None) -> dict:
    msg = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        msg["params"] = params
    if id_ is not None:
        msg["id"] = id_
    return msg

# ─── MemOS Bridge Controller ──────────────────────────────────────────────

class MemOSController:
    """Manages the MemOS bridge child process via stdio JSON-RPC."""
    
    def __init__(self):
        self.proc = None
        self._id = 0
        self._pending = {}
        self._lock = threading.Lock()
        self._reader_thread = None
        self._running = False
        
    def start(self):
        """Spawn the MemOS bridge."""
        log("Starting MemOS bridge...")
        self.proc = subprocess.Popen(
            ["npx", "tsx", MEMOS_BRIDGE, "--agent=hermes", "--no-viewer"],
            cwd=str(MEMOS_PLUGIN_DIR),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._running = True
        self._reader_thread = threading.Thread(target=self._read_responses, daemon=True)
        self._reader_thread.start()
        
        # Give it a moment to initialize
        time.sleep(2)
        log(f"MemOS bridge started (pid={self.proc.pid})")
        
    def _next_id(self) -> int:
        with self._lock:
            self._id += 1
            return self._id
    
    def _read_responses(self):
        """Read JSON-RPC responses from bridge stdout."""
        while self._running and self.proc and self.proc.stdout:
            try:
                line = self.proc.stdout.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                
                # Handle notifications (no id)
                if "id" not in msg:
                    method = msg.get("method", "")
                    if method in ("logs.forward", "events.notify"):
                        pass  # Ignore log/event notifications
                    continue
                
                # Handle responses
                rid = msg.get("id")
                with self._lock:
                    if rid in self._pending:
                        future = self._pending.pop(rid)
                        if "result" in msg:
                            future["result"] = msg["result"]
                        elif "error" in msg:
                            future["error"] = msg["error"]
                        future["done"] = True
            except Exception as e:
                if self._running:
                    log(f"Reader error: {e}")
                break
    
    def _call(self, method: str, params: dict = None, timeout: float = 30) -> dict:
        """Send a JSON-RPC request and wait for response."""
        rid = self._next_id()
        msg = make_jsonrpc(method, params, rid)
        
        future = {"done": False, "result": None, "error": None}
        with self._lock:
            self._pending[rid] = future
        
        try:
            self.proc.stdin.write(json.dumps(msg) + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            with self._lock:
                self._pending.pop(rid, None)
            raise RuntimeError(f"Bridge process dead: {e}")
        
        # Wait for response
        deadline = time.time() + timeout
        while time.time() < deadline:
            if future["done"]:
                if future["error"]:
                    raise RuntimeError(f"RPC error: {future['error']}")
                return future["result"]
            time.sleep(0.05)
        
        with self._lock:
            self._pending.pop(rid, None)
        raise TimeoutError(f"RPC timeout: {method}")
    
    def init(self):
        """Initialize the core."""
        result = self._call("core.init", {"agent": "hermes"})
        log("MemOS core initialized")
        return result
    
    def open_session(self, session_id: str = None):
        """Open a memory session."""
        params = {"agent": "hermes"}
        if session_id:
            params["sessionId"] = session_id
        result = self._call("session.open", params)
        log(f"Session opened: {result.get('sessionId', '?')}")
        return result.get("sessionId")
    
    def close_session(self, session_id: str):
        self._call("session.close", {"sessionId": session_id})
        log(f"Session closed: {session_id}")
    
    def open_episode(self, session_id: str, episode_id: str = None, user_message: str = None):
        params = {"sessionId": session_id}
        if episode_id:
            params["episodeId"] = episode_id
        if user_message:
            params["userMessage"] = user_message
        result = self._call("episode.open", params)
        eid = result.get("episodeId", episode_id)
        log(f"Episode opened: {eid}")
        return eid
    
    def close_episode(self, episode_id: str):
        self._call("episode.close", {"episodeId": episode_id})
        log(f"Episode closed: {episode_id}")
    
    def turn_start(self, episode_id: str, user_input: str):
        params = {
            "episodeId": episode_id,
            "userInput": user_input,
            "ts": int(time.time() * 1000),
        }
        return self._call("turn.start", params)
    
    def turn_end(self, episode_id: str, assistant_output: str, tool_calls: list = None):
        params = {
            "episodeId": episode_id,
            "assistantOutput": assistant_output,
            "ts": int(time.time() * 1000),
        }
        if tool_calls:
            params["toolCalls"] = tool_calls
        return self._call("turn.end", params)
    
    def submit_feedback(self, episode_id: str, polarity: str, magnitude: float = 1.0):
        params = {
            "episodeId": episode_id,
            "channel": "implicit",
            "polarity": polarity,
            "magnitude": magnitude,
            "ts": int(time.time() * 1000),
        }
        return self._call("feedback.submit", params)
    
    def search_memory(self, query: str, top_k: int = 5):
        return self._call("memory.search", {"query": query, "topK": top_k})
    
    def shutdown(self):
        """Gracefully shut down the bridge."""
        try:
            self._call("core.shutdown", timeout=5)
        except Exception:
            pass
        self._running = False
        if self.proc:
            try:
                self.proc.stdin.close()
                self.proc.terminate()
                self.proc.wait(timeout=5)
            except Exception:
                self.proc.kill()
        log("MemOS bridge stopped")

# ─── Hermes Session Reader ────────────────────────────────────────────────

def read_hermes_session() -> dict:
    """Read the current Hermes session metadata."""
    if not HERMES_SESSIONS_JSON.exists():
        return {}
    try:
        with open(HERMES_SESSIONS_JSON) as f:
            return json.load(f)
    except Exception as e:
        log(f"Failed to read sessions: {e}")
        return {}

def find_session_transcript_dir(session_id: str) -> Path:
    """Find the transcript directory for a session."""
    # Hermes stores session transcripts in ~/.hermes/sessions/
    # Session ID format: 20260612_172805_a363bd4f
    parts = session_id.split("_")
    if len(parts) >= 1:
        date_str = parts[0]  # 20260612
        dir_path = HERMES_SESSIONS_DIR / date_str
        if dir_path.exists():
            return dir_path
    return None

# ─── Main Bridge Logic ────────────────────────────────────────────────────

def process_current_session(controller: MemOSController):
    """Feed current Hermes session data to MemOS."""
    sessions = read_hermes_session()
    if not sessions:
        log("No active sessions found")
        return
    
    for key, sess in sessions.items():
        session_id = sess.get("session_id", "")
        if not session_id:
            continue
        
        # Open memory session
        mem_session_id = controller.open_session(session_id)
        
        # Open episode for this conversation
        display_name = sess.get("display_name") or "Hermes Chat"
        episode_id = controller.open_episode(
            mem_session_id,
            episode_id=session_id,
            user_message=display_name
        )
        
        # Try to read the transcript directory
        transcript_dir = find_session_transcript_dir(session_id)
        if transcript_dir:
            log(f"Transcript dir: {transcript_dir}")
            # We'll add transcript parsing in a future iteration
        
        # Submit positive feedback (session is active)
        controller.submit_feedback(episode_id, "positive", magnitude=0.5)
        
        # Close episode and session (MemOS processes asynchronously)
        controller.close_episode(episode_id)
        controller.close_session(mem_session_id)
        
        log(f"Processed session: {session_id}")

def run_standalone():
    """Run once: process current session and exit."""
    controller = MemOSController()
    try:
        controller.start()
        controller.init()
        process_current_session(controller)
    except Exception as e:
        log(f"Error: {e}")
    finally:
        controller.shutdown()

def run_daemon():
    """Run continuously, watching for new sessions."""
    controller = MemOSController()
    controller.start()
    
    try:
        controller.init()
        last_session_id = None
        
        while True:
            try:
                sessions = read_hermes_session()
                if sessions:
                    # Get the first active session
                    for key, sess in sessions.items():
                        session_id = sess.get("session_id", "")
                        if session_id and session_id != last_session_id:
                            last_session_id = session_id
                            
                            mem_session_id = controller.open_session(session_id)
                            episode_id = controller.open_episode(
                                mem_session_id,
                                episode_id=session_id,
                                user_message=sess.get("display_name") or "Hermes Chat"
                            )
                            controller.submit_feedback(episode_id, "positive")
                            controller.close_episode(episode_id)
                            controller.close_session(mem_session_id)
                            
                            log(f"Recorded session: {session_id}")
                        break
            except Exception as e:
                log(f"Watch loop error: {e}")
            
            time.sleep(60)  # Check every minute
    except KeyboardInterrupt:
        log("Shutting down...")
    finally:
        controller.shutdown()

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--daemon":
        run_daemon()
    else:
        run_standalone()
