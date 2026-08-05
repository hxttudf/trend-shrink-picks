#!/usr/bin/env python3
"""Twitter full scrape + analyze → WeChat-formatted summary."""

import json, subprocess, sys, os
from datetime import datetime

PY = "/home/ubuntu/Sequoia-X-a/.venv-host/bin/python3"
SCRAPER = "/home/ubuntu/scripts/twitter_scraper.py"
ANALYZER = "/home/ubuntu/scripts/twitter_analyze.py"

env = {**os.environ, "HTTP_PROXY": "", "HTTPS_PROXY": ""}

def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300, env=env)
    return r.returncode, r.stdout.strip(), r.stderr.strip()

# ── Scrape ──
for mode in ["accounts", "keywords", "cashtags"]:
    run([PY, SCRAPER, "--mode", mode])

# ── Analyze ──
rc, out, err = run([PY, ANALYZER])
if rc != 0:
    print(f"Twitter 情报分析失败: {err[:200]}")
    sys.exit(1)

try:
    r = json.loads(out)
except json.JSONDecodeError:
    sys.exit(0)

if r.get("status") == "no_new_tweets":
    sys.exit(0)

now = r.get("run_time", "")
sentiment = r.get("sentiment", "neutral")
new_tweets = r.get("new_tweets", 0)
new_signals = r.get("new_signals", 0)
signal_types = r.get("signal_types", [])
companies = r.get("company_list", "无")
findings = r.get("findings", [])

emoji = {"bullish": "🐂", "bearish": "🐻", "neutral": "➖"}.get(sentiment, "")
sent_zh = {"bullish": "偏多", "bearish": "偏空", "neutral": "中性"}.get(sentiment, "")

lines = []
lines.append(f"{emoji} Twitter 供应链情报 {now}")
lines.append(f"新增 {new_tweets} 条推文，{new_signals} 个信号")
if signal_types:
    lines.append(f"信号类型：{' / '.join(signal_types)}")
if companies and companies != "none detected":
    lines.append(f"涉及公司：{companies}")
lines.append(f"情绪：{sent_zh}")

if findings:
    lines.append("```")
    for f in findings:
        lines.append(f)
    lines.append("```")

print("\n".join(lines))
