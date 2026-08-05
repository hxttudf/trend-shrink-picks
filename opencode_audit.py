#!/usr/bin/env python3
"""Audit opencode usage in recent sessions. If self-written code ratio > 70%, alert."""
import sqlite3, json, sys, os
from datetime import datetime, timedelta

SESSION_DB = os.path.expanduser("~/.hermes/state.db")
HOURS = 12
THRESHOLD = 0.70  # opencode ratio must be >= 70%

def audit():
    conn = sqlite3.connect(SESSION_DB)
    cutoff = (datetime.now() - timedelta(hours=HOURS)).timestamp()

    rows = conn.execute("""
        SELECT m.content, m.tool_calls
        FROM messages m
        JOIN sessions s ON m.session_id = s.id
        WHERE m.role = 'assistant'
          AND m.timestamp > ?
    """, (cutoff,)).fetchall()
    conn.close()

    self_code = 0
    opencode_use = 0

    for content, tool_calls_json in rows:
        if content and 'opencode' in content.lower():
            opencode_use += 1

        if not tool_calls_json:
            continue

        try:
            calls = json.loads(tool_calls_json)
        except json.JSONDecodeError:
            continue

        for tc in calls:
            fn = tc.get("function", {})
            name = fn.get("name", "")
            args = fn.get("arguments", "{}")
            try:
                if isinstance(args, str):
                    args_dict = json.loads(args)
                else:
                    args_dict = args
            except json.JSONDecodeError:
                continue

            if name == "terminal":
                command = args_dict.get("command", "") or args_dict.get("description", "") or ""
                if "<<" in command or "PYEOF" in command or len(command) > 500:
                    self_code += 1
            elif name == "execute_code":
                code = args_dict.get("code", "")
                if code.count("\n") > 5:
                    self_code += 1

    total = self_code + opencode_use
    if total == 0:
        print(f"SKIP: no code tasks found in past {HOURS}h")
        return

    ratio = opencode_use / total
    if ratio < THRESHOLD:
        print(f"⚠️ opencode 使用率不达标: {ratio:.0%} (阈值 {THRESHOLD:.0%})")
        print(f"   opencode={opencode_use}  self={self_code}")
    # Silent when OK — only alert on violation

if __name__ == "__main__":
    audit()
# Kuma heartbeat
import subprocess
subprocess.run(["bash", "/home/ubuntu/.hermes/scripts/kuma_ping.sh", "opencode-usage-audit"], capture_output=True)
