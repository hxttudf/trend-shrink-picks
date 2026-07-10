#!/bin/bash
# 趋势缩量选股 cron wrapper
# 每日15:22执行
set -e
cd "$(dirname "$0")"

VENV="/home/ubuntu/Sequoia-X-a/.venv-host"

# 交易日检查
python3 /home/ubuntu/Sequoia-X-a/is_trading_day.py || { echo "非交易日，跳过"; exit 0; }

# 运行选股
$VENV/bin/python3 run_picks.py 2>&1
