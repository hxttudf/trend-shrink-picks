#!/bin/bash
# Sequoia-X 日线拉取+回填 — 非交易日跳过

trap 'bash /home/ubuntu/.hermes/scripts/kuma_ping.sh "Sequoia-X 日线数据拉取" done' EXIT
if ! /home/ubuntu/Sequoia-X-a/.venv-host/bin/python3 /home/ubuntu/Sequoia-X-a/is_trading_day.py > /dev/null 2>&1; then
    exit 0
fi

cd /home/ubuntu/Sequoia-X-a
HTTP_PROXY="" HTTPS_PROXY="" http_proxy="" https_proxy="" .venv-host/bin/python3 update_daily.py

# 拉取全市场基本面数据（含更新股票名称）
HTTP_PROXY="" HTTPS_PROXY="" .venv-host/bin/python3 fetch_basics.py 2>&1 | tail -1

HTTP_PROXY="" HTTPS_PROXY="" http_proxy="" https_proxy="" .venv-host/bin/python3 -c "
import sys; sys.path.insert(0,'.')
from daily_picks import backfill_top10_returns
backfill_top10_returns()
" 2>&1 | tail -1

