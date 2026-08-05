#!/bin/bash
# Sequoia-X 选股+回测 — 非交易日跳过
# 直接输出纯文本（跳过图片转换以节省时间，避免600s超时）

trap 'bash /home/ubuntu/.hermes/scripts/kuma_ping.sh "Sequoia-X 每日选股+回测" done' EXIT
if ! /home/ubuntu/Sequoia-X-a/.venv-host/bin/python3 /home/ubuntu/Sequoia-X-a/is_trading_day.py > /dev/null 2>&1; then
    exit 0
fi

cd /home/ubuntu/Sequoia-X-a
HTTP_PROXY="" HTTPS_PROXY="" http_proxy="" https_proxy="" \
  .venv-host/bin/python3 daily_picks.py 2>/dev/null | \
  awk 'BEGIN{print "```"} {print} END{print "```"}'
