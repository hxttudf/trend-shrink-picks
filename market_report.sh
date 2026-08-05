#!/bin/bash
# 市场复盘脚本包装 — 供 Hermes cron 调用
SLOT="${1:-close}"

# 检查是否为交易日
/home/ubuntu/Sequoia-X-a/.venv-host/bin/python3 /home/ubuntu/Sequoia-X-a/is_trading_day.py > /dev/null 2>&1 || exit 0

exec /home/ubuntu/Sequoia-X-a/.venv-host/bin/python3 /home/ubuntu/nav/market_report.py "$SLOT"
