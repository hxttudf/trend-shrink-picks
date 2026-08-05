#!/bin/bash
# 资金流向收盘 — 发送两条消息
set -e

if ! /home/ubuntu/Sequoia-X-a/.venv-host/bin/python3 /home/ubuntu/Sequoia-X-a/is_trading_day.py > /dev/null 2>&1; then
    exit 0
fi

OUTPUT=$(/home/ubuntu/Sequoia-X-a/.venv-host/bin/python3 /home/ubuntu/.hermes/scripts/fund_flow_daily.py close 2>&1 | grep -v "^ 0%\|^100%\|^[0-9]*%")

MSG1=$(echo "$OUTPUT" | sed -n '/===MSG1===/,/===MSG2===/p' | grep -v '===MSG')
MSG2=$(echo "$OUTPUT" | sed -n '/===MSG2===/,$ p' | grep -v '===MSG')

echo "$MSG1"
echo ""
echo "---SPLIT---"
echo ""
echo "$MSG2"
