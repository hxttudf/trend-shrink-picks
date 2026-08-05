#!/bin/bash
# ETF 尾盘信号 — 非交易日跳过
trap 'bash /home/ubuntu/.hermes/scripts/kuma_ping.sh "ETF信号-尾盘" done' EXIT
set -e

if ! /home/ubuntu/Sequoia-X-a/.venv-host/bin/python3 /home/ubuntu/Sequoia-X-a/is_trading_day.py > /dev/null 2>&1; then
    exit 0
fi

sudo docker exec etf-backtrader python3 /data/etf_signal_full.py --image > /dev/null
sudo docker cp etf-backtrader:/data/etf_signal.png /tmp/etf_signal_pm.png
echo "MEDIA:/tmp/etf_signal_pm.png"

