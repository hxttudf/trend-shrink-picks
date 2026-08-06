#!/bin/bash
# 缠论盘中预信号: 14:35 拉盘中K线 → 跑预览缠论信号 → 输出强信号摘要
# 非交易日跳过; 拉数据前清代理(腾讯行情)
trap 'bash /home/ubuntu/.hermes/scripts/kuma_ping.sh "缠论盘中预信号" done' EXIT
set -e

if ! /home/ubuntu/Sequoia-X-a/.venv-host/bin/python3 /home/ubuntu/Sequoia-X-a/is_trading_day.py > /dev/null 2>&1; then
    echo "非交易日，跳过"
    exit 0
fi

cd /home/ubuntu/trend-shrink-picks
unset HTTP_PROXY HTTPS_PROXY

echo "📡 拉盘中K线(约6分钟)..."
/home/ubuntu/Sequoia-X-a/.venv-host/bin/python3 bc_preview_data.py 2>&1 | tail -1

echo ""
echo "📐 跑预览缠论信号..."
/home/ubuntu/Sequoia-X-a/.venv-host/bin/python3 bc_preview_chanlun.py 2>&1 | tail -1

echo ""
echo "===== 今日强信号(盘中预览) ====="
sqlite3 /home/ubuntu/databases/trend_picks.db \
  "SELECT symbol, name, signal_type, printf('%.1f分', strength_score), printf('%.2f', price) FROM preview_signals \
   WHERE signal_date=(SELECT MAX(signal_date) FROM preview_signals) AND strength='strong' \
   ORDER BY strength_score DESC LIMIT 12"

echo ""
echo "===== 信号分布 ====="
sqlite3 /home/ubuntu/databases/trend_picks.db \
  "SELECT signal_date, signal_type, strength, COUNT(*) FROM preview_signals \
   WHERE signal_date=(SELECT MAX(signal_date) FROM preview_signals) \
   GROUP BY signal_type, strength ORDER BY signal_type, strength"
echo "✅ 盘中预信号完成(未确认, 15:20正式确认)"
