#!/usr/bin/env python3
"""V4历史信号刷入 bottom_confirm_picks (替换旧的V2口径数据)
V4: 分数80-88 + 期数4 + 底部>=90天 + 跌幅20~65% + 每日Top3 + 上证>MA60市场过滤
"""
import sqlite3
from collections import defaultdict

SCORES_DB = "/home/ubuntu/trend-shrink-picks/bc_scores2.db"
DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"
TREND_DB = "/home/ubuntu/databases/trend_picks.db"

# 1) V4条件信号
conn = sqlite3.connect(SCORES_DB)
rows = conn.execute(
    "SELECT bt_date, symbol, score, s65, drop_pct, bottom_days, vol_shrink, cur, ma20, ma60 "
    "FROM scores WHERE score BETWEEN 80 AND 88 AND s65>=4 AND bottom_days>=90 "
    "AND abs(drop_pct) BETWEEN 20 AND 65 AND is_st=0"
).fetchall()
conn.close()
print(f"V4条件信号: {len(rows)} 条")

# 2) 上证指数 MA60 (市场过滤)
db = sqlite3.connect(DB)
idx = [r[0] for r in db.execute(
    "SELECT date FROM stock_daily WHERE symbol='000001.SH' AND close_qfq>0 ORDER BY date")]
idx_close = [r[0] for r in db.execute(
    "SELECT close_qfq FROM stock_daily WHERE symbol='000001.SH' AND close_qfq>0 ORDER BY date")]
idx_ma60 = {}
for i in range(59, len(idx_close)):
    idx_ma60[int(idx[i].replace('-', ''))] = sum(idx_close[i-59:i+1]) / 60
idx_close_by_date = {}
for i, d in enumerate(idx):
    idx_close_by_date[int(d.replace('-', ''))] = idx_close[i]

# 3) 每日Top3 + 市场过滤
by_bd = defaultdict(list)
for r in rows:
    by_bd[r[0]].append(r)
sigs = []
for bd, lst in by_bd.items():
    lst.sort(key=lambda r: -r[2])
    for r in lst[:3]:
        if idx_close_by_date.get(bd, 0) > idx_ma60.get(bd, 0):
            sigs.append(r)
print(f"V4最终信号(Top3+市场过滤): {len(sigs)} 条")

# 4) 名称
names = dict(db.execute(
    "SELECT symbol, name FROM stock_basics WHERE date=(SELECT MAX(date) FROM stock_basics)").fetchall())
db.close()

# 5) 删除旧历史(保留今天daily跑的), 写入V4历史
tdb = sqlite3.connect(TREND_DB)
today = tdb.execute("SELECT MAX(date) FROM bottom_confirm_picks").fetchone()[0]
deleted = tdb.execute("DELETE FROM bottom_confirm_picks WHERE date != ?", (today,)).rowcount
print(f"删除旧历史 {deleted} 条 (保留 {today})")

n = 0
for bt_date, sym, score, streak, drop, bd, vs, cur, ma20, ma60 in sigs:
    date_str = f"{bt_date//10000}-{bt_date%10000//100:02d}-{bt_date%100:02d}"
    if date_str == today:
        continue  # 今天的由daily脚本管理
    name = names.get(sym, sym)
    stage = "D趋势运行" if cur > ma60 else "C回调确认"
    tdb.execute(
        "INSERT OR REPLACE INTO bottom_confirm_picks "
        "(date, symbol, name, status, score, stage, drop_pct, bottom_days, vol_shrink, streak, close_qfq, ma20, ma60) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (date_str, sym, name, "worth", score, stage, round(drop, 2), bd, vs, streak, cur, ma20, ma60))
    n += 1
tdb.commit()

# 6) 统计
stats = tdb.execute(
    "SELECT substr(date,1,4) y, status, COUNT(*) FROM bottom_confirm_picks GROUP BY y, status ORDER BY y").fetchall()
tdb.close()
print(f"写入V4历史 {n} 条")
for y, st, c in stats:
    print(f"  {y} {st}: {c}")
