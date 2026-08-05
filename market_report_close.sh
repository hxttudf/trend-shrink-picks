#!/bin/bash
# 市场收盘复盘 — 输出为图片，避免微信文本切段限流
trap 'bash /home/ubuntu/.hermes/scripts/kuma_ping.sh "市场收盘复盘" done' EXIT
/home/ubuntu/Sequoia-X-a/.venv-host/bin/python3 /home/ubuntu/Sequoia-X-a/is_trading_day.py > /dev/null 2>&1 || exit 0

# 生成报告文本并转换为图片
/home/ubuntu/Sequoia-X-a/.venv-host/bin/python3 /home/ubuntu/nav/market_report.py close 2>/dev/null | \
  /home/ubuntu/Sequoia-X-a/.venv-host/bin/python3 /home/ubuntu/scripts/text_to_image.py
