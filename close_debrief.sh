#!/bin/bash
# 尾盘复盘 — 生成post-market-debrief完整报告 → 直接输出文本
/home/ubuntu/Sequoia-X-a/.venv-host/bin/python3 /home/ubuntu/Sequoia-X-a/is_trading_day.py > /dev/null 2>&1 || exit 0
/home/ubuntu/Sequoia-X-a/.venv-host/bin/python3 /home/ubuntu/.hermes/scripts/close_debrief.py 2>/dev/null