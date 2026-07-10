#!/usr/bin/env python3
"""查询最新选股结果"""
import sqlite3, sys
from pathlib import Path

DB = Path(__file__).parent / "data" / "trend_picks.db"
if not DB.exists():
    print("DB不存在，还没跑过")
    sys.exit(0)

conn = sqlite3.connect(str(DB))
c = conn.cursor()
c.execute("SELECT date, pick_count, symbols FROM daily_summary ORDER BY date DESC LIMIT 1")
r = c.fetchone()
if not r:
    print("无记录")
    sys.exit(0)

print(f"日期: {r[0]}")
print(f"信号: {r[1]}只")
if r[2]:
    print(f"标的: {r[2]}")
print()

c.execute("SELECT symbol, name, dist_ma20, vol_ratio, pct_20d, close FROM daily_picks WHERE date=? ORDER BY dist_ma20", (r[0],))
rows = c.fetchall()
for row in rows:
    print(f"  {row[0]} {row[1]:>6}  距MA20:{row[2]:>5.1f}%  量比:{row[3]:>.2f}  20日涨:{row[4]:>5.1f}%  收盘:{row[5]}")
conn.close()
