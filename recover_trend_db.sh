#!/bin/bash
# trend_picks.db 完整重建(须在stockscope停止时执行, 避免并发写损坏)
set -e
DB=/home/ubuntu/databases/trend_picks.db
echo "[1/6] 停 stockscope..."
sudo systemctl stop stockscope
sleep 1
echo "[2/6] 删除损坏DB..."
rm -f ${DB}*
echo "[3/6] 缠论历史扫描(重建chanlun_signals)..."
cd /home/ubuntu/trend-shrink-picks
/home/ubuntu/Sequoia-X-a/.venv-host/bin/python3 bc_chanlun_history.py --recreate
echo "[4/6] 恢复daily_picks(从stockscope.db)..."
/home/ubuntu/trend-stockscope/venv/bin/python - <<'EOF'
import sqlite3
src = sqlite3.connect('/home/ubuntu/trend-stockscope/stockscope.db')
dst = sqlite3.connect('/home/ubuntu/databases/trend_picks.db')
dst.execute('''CREATE TABLE IF NOT EXISTS daily_picks (
    id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL, strategy_id TEXT NOT NULL,
    symbol TEXT NOT NULL, name TEXT DEFAULT '', close_qfq REAL, ma20 REAL, ma60 REAL,
    dist_ma20 REAL, vol_ratio REAL, pct_20d REAL, volume REAL, avg_vol_20d REAL,
    buy_price REAL, created_at TEXT DEFAULT (datetime('now','+8 hours')),
    UNIQUE(date, strategy_id, symbol))''')
rows = src.execute('SELECT date, strategy_id, symbol, name, close_qfq, ma20, ma60, dist_ma20, vol_ratio, pct_20d, volume, avg_vol_20d, buy_price FROM daily_picks').fetchall()
dst.executemany('INSERT OR REPLACE INTO daily_picks (date, strategy_id, symbol, name, close_qfq, ma20, ma60, dist_ma20, vol_ratio, pct_20d, volume, avg_vol_20d, buy_price) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)', rows)
dst.commit()
print(f'daily_picks: {len(rows)}条')
dst.close(); src.close()
EOF
echo "[5/6] 底部确认恢复(建表+3脚本)..."
/home/ubuntu/Sequoia-X-a/.venv-host/bin/python3 - <<'EOF'
import sqlite3
conn = sqlite3.connect('/home/ubuntu/databases/trend_picks.db')
conn.execute('''CREATE TABLE IF NOT EXISTS bottom_confirm_picks(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date TEXT, symbol TEXT, name TEXT, status TEXT, score REAL, stage TEXT,
  drop_pct REAL, bottom_days INTEGER, vol_shrink REAL, streak INTEGER,
  close_qfq REAL, ma20 REAL, ma60 REAL,
  created_at TEXT DEFAULT (datetime('now','localtime')))''')
conn.commit()
print('bottom_confirm_picks表已建')
conn.close()
EOF
/home/ubuntu/Sequoia-X-a/.venv-host/bin/python3 bc_load_history.py
/home/ubuntu/Sequoia-X-a/.venv-host/bin/python3 bc_load_history_v4.py
/home/ubuntu/Sequoia-X-a/.venv-host/bin/python3 bc_load_watch2026.py
echo "[6/6] 启动 stockscope..."
sudo systemctl start stockscope
sleep 3
echo "=== 验证 ==="
sqlite3 $DB "SELECT 'daily_picks',COUNT(*) FROM daily_picks UNION ALL SELECT 'bottom_confirm',COUNT(*) FROM bottom_confirm_picks UNION ALL SELECT 'chanlun_signals',COUNT(*) FROM chanlun_signals"
for ep in "api/kline/000977" "api/chanlun/dates" "api/picks/dates" "api/laogao/dates"; do
  code=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:8004/$ep")
  echo "$code  $ep"
done
echo "=== 完成 ==="
