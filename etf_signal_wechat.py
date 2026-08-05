#!/usr/bin/env python3
"""ETF双动量信号 - 微信推送（调用Docker内的完整版脚本）"""
import subprocess, sys, os

GROUP = sys.argv[1] if len(sys.argv) > 1 else "价纳创黄C3"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOCAL_SCRIPT = os.path.join(SCRIPT_DIR, "etf_signal_full.py")

# Ensure script is in container (persist to /data volume)
subprocess.run(
    ["sudo", "docker", "cp", LOCAL_SCRIPT, "etf-backtrader:/data/etf_signal_full.py"],
    capture_output=True, timeout=10
)

result = subprocess.run(
    ["sudo", "docker", "exec", "etf-backtrader",
     "python3", "/data/etf_signal_full.py", GROUP],
    capture_output=True, text=True, timeout=120
)
print(result.stdout)
if result.returncode != 0:
    print(result.stderr, file=sys.stderr)
    sys.exit(result.returncode)
