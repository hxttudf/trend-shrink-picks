#!/usr/bin/env python3
"""
MemOS Bridge Controller v2 — with reverse RPC support for host LLM calls.

The MemOS bridge sends reverse JSON-RPC requests (IDs like "srv-N")
to ask the client to perform LLM completions. This controller handles
those by calling the DeepSeek API.
"""

import subprocess, json, time, os, threading, queue, urllib.request
from pathlib import Path

MEMOS_DIR = Path.home() / ".hermes" / "memos-plugin"

# ─── DeepSeek API ─────────────────────────────────────────────────────────

def _get_deepseek_key():
    """Read DeepSeek API key from Hermes config."""
    env_file = Path.home() / ".hermes" / ".env"
    config_file = Path.home() / ".hermes" / "config.yaml"
    # Try env first
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "DEEPSEEK" in line.upper() and "=" in line:
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    # Try memos config
    memos_config = MEMOS_DIR / "config.yaml"
    if memos_config.exists():
        for line in memos_config.read_text().splitlines():
            if "apiKey" in line and ":" in line:
                val = line.split(":", 1)[1].strip().strip('"').strip("'")
                if val and not val.startswith("sk-"):
                    continue
                if val:
                    return val
    return os.environ.get("DEEPSEEK_API_KEY", "")

DEEPSEEK_KEY = _get_deepseek_key()

def _log(msg: str):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] memos: {msg}", flush=True)

def call_deepseek(messages, max_tokens=1024, temperature=0):
    """Call DeepSeek chat completions API."""
    if not DEEPSEEK_KEY:
        raise RuntimeError("No DeepSeek API key found")
    
    data = json.dumps({
        "model": "deepseek-chat",
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }).encode()
    
    req = urllib.request.Request(
        "https://api.deepseek.com/v1/chat/completions",
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {DEEPSEEK_KEY}",
        },
    )
    
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            body = json.loads(resp.read())
            return body["choices"][0]["message"]["content"]
    except Exception as e:
        _log(f"DeepSeek API error: {e}")
        raise


# ─── Controller ───────────────────────────────────────────────────────────

class MemOSController:
    def __init__(self, debug=False):
        self.proc = None
        self._id = 0
        self._pending = {}
        self._lock = threading.Lock()
        self._msg_queue = queue.Queue()
        self._reader_thread = None
        self._running = False
        self._debug = debug
    
    def start(self):
        _log("Starting bridge...")
        self.proc = subprocess.Popen(
            ["npx", "tsx", "bridge.cts", "--agent=hermes", "--no-viewer"],
            cwd=str(MEMOS_DIR),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        self._running = True
        self._reader_thread = threading.Thread(target=self._reader, daemon=True)
        self._reader_thread.start()
        time.sleep(3)
        _log(f"Bridge started (pid={self.proc.pid})")
    
    def _reader(self):
        """Read JSON-RPC messages, dispatch responses and handle reverse RPC."""
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
                
                rid = msg.get("id")
                
                # ── Server-initiated request (reverse RPC) ──
                if isinstance(rid, str) and rid.startswith("srv-"):
                    self._handle_server_request(rid, msg)
                    continue
                
                # ── Notification ──
                if rid is None:
                    continue
                
                # ── Client response ──
                with self._lock:
                    if rid in self._pending:
                        entry = self._pending.pop(rid)
                        entry["result"] = msg
                        entry["event"].set()
                        if self._debug:
                            ok = "✓" if "result" in msg else "✗"
                            _log(f"  ← resp[{rid}]: {ok}")
                
            except Exception as e:
                if self._running:
                    _log(f"Reader error: {e}")
                break
    
    def _handle_server_request(self, rid, msg):
        """Handle a reverse RPC request from the bridge (server → client)."""
        method = msg.get("method", "")
        params = msg.get("params", {})
        
        if self._debug:
            _log(f"  ← srv[{rid}]: {method}")
        
        try:
            if method == "host.llm.complete":
                response = self._handle_llm_complete(params)
            else:
                response = {"error": {"code": -32601, "message": f"Unknown method: {method}"}}
        except Exception as e:
            response = {"error": {"code": -32000, "message": str(e)}}
        
        # Send response back
        resp_msg = json.dumps({"jsonrpc": "2.0", "id": rid, "result": response})
        try:
            self.proc.stdin.write(resp_msg + "\n")
            self.proc.stdin.flush()
            if self._debug:
                _log(f"  → srv[{rid}]: done")
        except Exception as e:
            _log(f"Failed to send srv response: {e}")
    
    def _handle_llm_complete(self, params):
        """Handle host.llm.complete — call DeepSeek and return result."""
        messages = params.get("messages", [])
        max_tokens = params.get("max_tokens", 1024)
        temperature = params.get("temperature", 0)
        
        content = call_deepseek(messages, max_tokens, temperature)
        return {"content": content}
    
    def _next_id(self):
        with self._lock:
            self._id += 1
            return self._id
    
    def _call(self, method, params=None, timeout=120):
        rid = self._next_id()
        entry = {"event": threading.Event(), "result": None}
        
        with self._lock:
            self._pending[rid] = entry
        
        msg = json.dumps({"jsonrpc": "2.0", "method": method, "params": params or {}, "id": rid})
        
        try:
            self.proc.stdin.write(msg + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            with self._lock:
                self._pending.pop(rid, None)
            raise RuntimeError(f"Bridge dead: {e}")
        
        if self._debug:
            _log(f"  → {method}[{rid}]")
        
        if not entry["event"].wait(timeout):
            with self._lock:
                self._pending.pop(rid, None)
            raise TimeoutError(f"RPC timeout: {method}")
        
        msg = entry["result"]
        if "error" in msg:
            err = msg["error"]
            raise RuntimeError(f"RPC error [{method}]: {err.get('message', str(err))}")
        
        return msg.get("result", {})
    
    # ── Public API ──
    
    def init(self):
        return self._call("core.init", {"agent": "hermes"})
    
    def open_session(self, session_id=None):
        params = {"agent": "hermes"}
        if session_id:
            params["sessionId"] = session_id
        return self._call("session.open", params).get("sessionId", "")
    
    def close_session(self, session_id):
        self._call("session.close", {"sessionId": session_id})
    
    def open_episode(self, session_id, episode_id=None, user_message=None):
        params = {"sessionId": session_id}
        if episode_id:
            params["episodeId"] = episode_id
        if user_message:
            params["userMessage"] = user_message
        return self._call("episode.open", params).get("episodeId", "")
    
    def close_episode(self, episode_id):
        self._call("episode.close", {"episodeId": episode_id})
    
    def turn_start(self, session_id, episode_id, user_input):
        return self._call("turn.start", {
            "agent": "hermes",
            "sessionId": session_id,
            "episodeId": episode_id,
            "userText": user_input,
            "ts": int(time.time() * 1000),
        })
    
    def turn_end(self, session_id, episode_id, assistant_output, tool_calls=None):
        params = {
            "agent": "hermes",
            "sessionId": session_id,
            "episodeId": episode_id,
            "agentText": assistant_output,
            "toolCalls": tool_calls or [],
            "ts": int(time.time() * 1000),
        }
        return self._call("turn.end", params)
    
    def submit_feedback(self, episode_id, polarity="positive", magnitude=1.0):
        return self._call("feedback.submit", {
            "episodeId": episode_id,
            "channel": "implicit",
            "polarity": polarity,
            "magnitude": magnitude,
            "ts": int(time.time() * 1000),
        })
    
    def search_memory(self, query, top_k=5):
        return self._call("memory.search", {
            "agent": "hermes",
            "query": query,
            "topK": top_k,
        })
    
    def shutdown(self):
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
        _log("Bridge stopped")


# ─── Test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ctrl = MemOSController(debug=True)
    try:
        ctrl.start()
        _log(f"DeepSeek key: {'found' if DEEPSEEK_KEY else 'MISSING'}")
        ctrl.init()
        
        sid = ctrl.open_session("test_v3")
        eid = ctrl.open_episode(sid, "ep_test_v3", "Testing MemOS v3 with LLM")
        
        ctrl.turn_start(sid, eid, "Who are you?")
        ctrl.turn_end(sid, eid, "I am Hermes Agent.", [])
        
        ctrl.submit_feedback(eid, "positive")
        
        ctrl.close_episode(eid)
        ctrl.close_session(sid)
        
        time.sleep(10)  # Wait for async memory processing
        
        _log("Done!")
        
    except Exception as e:
        _log(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        ctrl.shutdown()
