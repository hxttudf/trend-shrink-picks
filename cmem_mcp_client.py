#!/usr/bin/env python3
"""
Claude-Mem MCP Bridge — feeds Hermes session data to claude-mem via MCP protocol.

Protocol: JSON-RPC 2.0 over stdio (line-delimited), same as MemOS.
"""

import subprocess, json, time, os, threading
from pathlib import Path

MCP_SERVER = "/home/ubuntu/.hermes/node/lib/node_modules/claude-mem/plugin/scripts/mcp-server.cjs"
BUN = "/home/ubuntu/.bun/bin/bun"
DATA_DIR = "/home/ubuntu/.claude-mem"

def _log(msg: str):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] cmem: {msg}", flush=True)


class ClaudeMemClient:
    """MCP client for claude-mem."""
    
    def __init__(self, debug=False):
        self.proc = None
        self._id = 0
        self._pending = {}
        self._lock = threading.Lock()
        self._reader_thread = None
        self._running = False
        self._debug = debug
    
    def start(self):
        _log("Starting MCP server...")
        env = {**os.environ, "CLAUDE_MEM_DATA_DIR": DATA_DIR}
        self.proc = subprocess.Popen(
            [BUN, MCP_SERVER],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True, bufsize=1,
            env=env,
        )
        self._running = True
        self._reader_thread = threading.Thread(target=self._reader, daemon=True)
        self._reader_thread.start()
        time.sleep(1)
        _log(f"MCP server started (pid={self.proc.pid})")
    
    def _reader(self):
        while self._running and self.proc and self.proc.stdout:
            try:
                line = self.proc.stdout.readline()
                if not line:
                    _log("MCP stdout closed")
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                
                rid = msg.get("id")
                if rid is None:
                    continue
                
                with self._lock:
                    if rid in self._pending:
                        entry = self._pending.pop(rid)
                        entry["result"] = msg
                        entry["event"].set()
                        if self._debug:
                            ok = "✓" if "result" in msg else "✗"
                            _log(f"  ← mcp[{rid}]: {ok}")
            except Exception as e:
                if self._running:
                    _log(f"Reader error: {e}")
                break
    
    def _next_id(self):
        with self._lock:
            self._id += 1
            return self._id
    
    def _call(self, method, params=None, timeout=30):
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
            raise RuntimeError(f"MCP server dead: {e}")
        
        if not entry["event"].wait(timeout):
            with self._lock:
                self._pending.pop(rid, None)
            raise TimeoutError(f"MCP timeout: {method}")
        
        msg = entry["result"]
        if "error" in msg:
            err = msg["error"]
            raise RuntimeError(f"MCP error: {err.get('message', str(err))}")
        return msg.get("result", {})
    
    def _notify(self, method, params=None):
        """Send a notification (no response expected)."""
        msg = json.dumps({"jsonrpc": "2.0", "method": method, "params": params or {}})
        self.proc.stdin.write(msg + "\n")
        self.proc.stdin.flush()
    
    def initialize(self):
        result = self._call("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "hermes-bridge", "version": "1.0"},
        })
        _log(f"Initialized: {result.get('serverInfo', {}).get('name')} v{result.get('serverInfo', {}).get('version')}")
        self._notify("notifications/initialized")
        return result
    
    def call_tool(self, name, arguments):
        return self._call("tools/call", {
            "name": name,
            "arguments": arguments,
        })
    
    def add_observation(self, content, project_id=None, kind="manual", metadata=None):
        """Add a manual observation (memory entry)."""
        args = {"content": content}
        if project_id:
            args["projectId"] = project_id
        if kind:
            args["kind"] = kind
        if metadata:
            args["metadata"] = metadata
        return self.call_tool("observation_add", args)
    
    def record_event(self, event_type, payload, project_id=None):
        """Record an event and trigger generation."""
        args = {
            "eventType": event_type,
            "payload": payload,
            "sourceType": "hook",
        }
        if project_id:
            args["projectId"] = project_id
        return self.call_tool("observation_record_event", args)
    
    def search(self, query, limit=10):
        return self.call_tool("observation_search", {
            "query": query,
            "limit": limit,
        })
    
    def get_context(self, query, limit=10):
        """Get observations for context injection."""
        return self.call_tool("observation_context", {
            "query": query,
            "limit": limit,
        })
    
    def shutdown(self):
        self._running = False
        if self.proc:
            try:
                self.proc.stdin.close()
                self.proc.terminate()
                self.proc.wait(timeout=5)
            except Exception:
                self.proc.kill()
        _log("MCP server stopped")


# ─── Test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    client = ClaudeMemClient(debug=True)
    try:
        client.start()
        client.initialize()
        
        # Add a test memory
        result = client.add_observation(
            content="User正在使用Hermes Agent做ETF轮动策略。持仓组合：512040价值ETF、513100纳指ETF、159952创业板ETF、159937黄金ETF。策略参数：MA=55, ROC=20, 暴跌过滤σ=2.6。",
            project_id="hermes"
        )
        _log(f"Add observation: {json.dumps(result, ensure_ascii=False)[:200]}")
        
        result = client.add_observation(
            content="6月12日分析沃格光电(603773)：龙虎榜显示章盟主买入、作手新一买入。分时图显示早盘拉高后持续回落，判断为诱多出货。用户决定不买入。",
            project_id="hermes"
        )
        _log(f"Add observation 2: {json.dumps(result, ensure_ascii=False)[:200]}")
        
        # Search
        results = client.search("沃格光电", limit=3)
        _log(f"Search: {json.dumps(results, ensure_ascii=False)[:300]}")
        
        # Get context
        ctx = client.get_context("ETF 策略 持仓", limit=3)
        _log(f"Context: {json.dumps(ctx, ensure_ascii=False)[:300]}")
        
        _log("Done!")
    except Exception as e:
        _log(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        client.shutdown()
