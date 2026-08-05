#!/usr/bin/env python3
"""
Claude-Mem Hermes Integration — full AI pipeline via DeepSeek.

Worker qu eues observations → DeepSeek analyzes → stores structured memories.

Usage:
    python3 cmem_hermes.py init       — start worker + seed context
    python3 cmem_hermes.py search "q" — search memories  
    python3 cmem_hermes.py add "观察内容"  — add an observation
"""

import subprocess, json, time, sys, os, urllib.request
from datetime import datetime
from pathlib import Path

BUN = "/home/ubuntu/.bun/bin/bun"
WORKER_SCRIPT = "/home/ubuntu/.hermes/node/lib/node_modules/claude-mem/plugin/scripts/worker-service.cjs"
MCP_SERVER = "/home/ubuntu/.hermes/node/lib/node_modules/claude-mem/plugin/scripts/mcp-server.cjs"
DATA_DIR = "/home/ubuntu/.claude-mem"
WORKER_PORT = 37777
WORKER_URL = f"http://127.0.0.1:{WORKER_PORT}"


def _log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] cmem: {msg}", flush=True)


# ─── Worker ──────────────────────────────────────────────────────────────

def check_worker():
    """Verify worker is running (wat chdog keeps it alive)."""
    try:
        req = urllib.request.Request(f"{WORKER_URL}/health")
        with urllib.request.urlopen(req, timeout=3) as resp:
            if json.loads(resp.read()).get("status") == "ok":
                return True
    except:
        pass
    _log("Worker not reachable — watchdog should restart it")
    sys.exit(1)


def api_post(path, data):
    req = urllib.request.Request(
        f"{WORKER_URL}{path}",
        data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def api_get(path):
    with urllib.request.urlopen(f"{WORKER_URL}{path}", timeout=10) as resp:
        return json.loads(resp.read())


# ─── Operations ──────────────────────────────────────────────────────────

def add_observation(session_id, tool_name, tool_input, tool_response, 
                    user_prompt="Hermes task", platform="hermes", cwd="/home/ubuntu"):
    """Queue an observation for DeepSeek analysis."""
    # Init session
    r = api_post("/api/sessions/init", {
        "contentSessionId": session_id,
        "cwd": cwd,
        "platformSource": platform,
    })
    _log(f"Session: {r.get('status')} (id={r.get('sessionDbId')})")
    
    # Queue observation
    r = api_post("/api/sessions/observations", {
        "contentSessionId": session_id,
        "tool_name": tool_name,
        "tool_input": tool_input,
        "tool_response": tool_response,
        "cwd": cwd,
        "platformSource": platform,
        "agentType": platform,
    })
    _log(f"Observation: {r.get('status')}")
    return r


def search_observations(query, limit=10):
    """Get observations from worker API."""
    data = api_get(f"/api/observations?limit={limit}")
    items = data.get("items", [])
    # Filter by query
    if query:
        q = query.lower()
        items = [i for i in items 
                 if q in (i.get("title","")+i.get("narrative","")).lower()]
    return items


def search_mcp(query, limit=5):
    """Full semantic search via MCP tools."""
    requests = (
        '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"h","version":"1"}}}\n'
        '{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
        f'{{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{{"name":"search","arguments":{{"query":"{query}","limit":{limit}}}}}}}\n'
    )
    
    proc = subprocess.Popen(
        [BUN, MCP_SERVER],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, env={**os.environ, "CLAUDE_MEM_DATA_DIR": DATA_DIR}
    )
    proc.stdin.write(requests); proc.stdin.flush()
    
    output = []
    for _ in range(50):
        line = proc.stdout.readline()
        if not line: break
        output.append(line.strip())
        if len([l for l in output if '"id":2' in l]) > 0: break
    
    proc.stdin.close(); proc.terminate()
    
    for line in output:
        try:
            msg = json.loads(line)
            if msg.get("id") == 2:
                content = msg.get("result",{}).get("content",[])
                return content[0].get("text","") if content else ""
        except: pass
    return ""


# ─── CLI ─────────────────────────────────────────────────────────────────

def cmd_init():
    if not check_worker():
        return
    
    # Seed ETF strategy context
    add_observation("hermes-etf-strategy", "ETF策略配置",
        {"query": "价纳创黄组合参数", "action": "setup"},
        {"result": "组合：512040/513100/159952/159937, MA=55, ROC=20, σ=2.6"},
        user_prompt="配置ETF轮动策略的价纳创黄组合参数"
    )
    
    # Seed trading pattern
    add_observation("hermes-lhb-pattern", "龙虎榜分析",
        {"query": "沃格光电 603773 龙虎榜", "action": "analyze"},
        {"finding": "章盟主买入，作手新一买入，判断诱多出货，不买入"},
        user_prompt="分析沃格光电603773的龙虎榜数据和游资动向"
    )
    
    # Seed output preferences
    add_observation("hermes-output-prefs", "输出格式",
        {"action": "set_preferences"},
        {"format": "markdown表格，持仓加粗，✓/✗标记，3位小数精度，无多余段落"},
        user_prompt="设置ETF信号推送的输出格式偏好"
    )
    
    _log("Waiting for DeepSeek to process...")
    time.sleep(15)
    
    items = api_get("/api/observations?limit=10").get("items", [])
    _log(f"Total observations: {len(items)}")
    for item in items[-6:]:
        print(f"  #{item['id']} [{item['type']}] {item['title']}")


def cmd_search(query):
    check_worker()
    
    # Try MCP semantic search first
    result = search_mcp(query)
    if result and "Error" not in result:
        print(result[:2000])
        return
    
    # Fallback to API filter
    items = search_observations(query)
    for item in items:
        print(f"\n#{item['id']} [{item['type']}] {item['title']}")
        print(f"  {item.get('narrative','')[:200]}")


def cmd_add(text):
    check_worker()
    ts = int(time.time())
    r = add_observation(f"hermes-manual-{ts}", "手动记录",
        {"action": "manual_add"},
        {"content": text},
        user_prompt=text[:200]
    )
    _log(f"Queued: {r.get('status')}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        # 默认: 检查worker健康, 退出0 (cron用)
        try:
            check_worker()
            print("[cmem] Worker healthy, cron skip")
        except SystemExit:
            print("[cmem] Worker unreachable — watchdog handles it")
        sys.exit(0)
    
    cmd = sys.argv[1]
    if cmd == "init":
        cmd_init()
    elif cmd == "search":
        cmd_search(sys.argv[2] if len(sys.argv) > 2 else "")
    elif cmd == "add":
        cmd_add(sys.argv[2] if len(sys.argv) > 2 else "")
    else:
        print(f"Unknown: {cmd}")
# Kuma heartbeat
import subprocess
subprocess.run(["bash", "/home/ubuntu/.hermes/scripts/kuma_ping.sh", "Claude-Mem Seed"], capture_output=True)
