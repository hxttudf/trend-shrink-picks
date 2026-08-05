#!/bin/bash
# 趋势缩量选股 cron wrapper
set -e

# 交易日检查
python3 /home/ubuntu/Sequoia-X-a/is_trading_day.py || { echo "非交易日，跳过"; exit 0; }

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# 运行选股脚本
cd /home/ubuntu/trend-shrink-picks
/home/ubuntu/Sequoia-X-a/.venv-host/bin/python3 run_picks.py 2>&1

echo ""

# 查询选股明细
python3 /home/ubuntu/trend-shrink-picks/query_picks.py today 2>&1

# 同步到stockscope
python3 /home/ubuntu/trend-stockscope/scripts/sync_picks.py 2>&1 | grep -v DeprecationWarning
echo ""

# 极品B模拟盘
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# 老高多重确认策略选股入库
cd /home/ubuntu/trend-shrink-picks
/home/ubuntu/Sequoia-X-a/.venv-host/bin/python3 bottom_confirm_daily.py 2>&1 | tail -25
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
cd /home/ubuntu/trend-shrink-picks
python3 sim_trade.py 2>&1
