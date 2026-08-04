#!/usr/bin/env python3
"""2026年观察(watch)历史信号写入 bottom_confirm_picks
watch判定(daily口径): 确认>=4期(阈值65) 且 score>=65 且 不满足worth硬条件
worth硬条件: 80<=score<=88 AND bottom>=90 AND 20<=drop<=65
"""
import sqlite3

SCORES_DB = "/home/ubuntu/trend-shrink-picks/bc_scores2.db"
DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"
TREND_DB = "/home/ubuntu/databases/trend_picks.db"

conn = sqlite3.connect(SCORES_DB)
rows = conn.execute(
    "SELECT bt_date, symbol, score, s65, drop_pct, bottom_days, vol_shrink, cur, ma20, ma60 "
    "FROM scores WHERE s65>=4 AND score>=65 AND bt_date LIKE '2026%' AND is_st=0"
).fetchall()
conn.close()

# 分类: worth硬条件 vs watch
watch = []
for r in rows:
    score = r[2]
    is_worth = (80 <= score <= 88 and r[5] >= 90 and 20 <= abs(r[4]) <= 65)
    if not is_worth:
        watch.append(r)
print(f"2026 watch: {len(watch)} 条")

db = sqlite3.connect(DB)
names = dict(db.execute(
    "SELECT symbol, name FROM stock_basics WHERE date=(SELECT MAX(date) FROM stock_basics)").fetchall())
db.close()

tdb = sqlite3.connect(TREND_DB)
# 先删掉已有的2026年watch历史(保留今天的daily数据), 避免新旧口径混杂
today = tdb.execute("SELECT MAX(date) FROM bottom_confirm_picks").fetchone()[0]
deleted = tdb.execute(
    "DELETE FROM bottom_confirm_picks WHERE date LIKE '2026%' AND status='watch' AND date != ?",
    (today,)).rowcount
print(f"清理旧watch历史 {deleted} 条 (保留今天 {today})")

n = 0
for bt_date, sym, score, streak, drop, bd, vs, cur, ma20, ma60 in watch:
    date_str = f"{bt_date//10000}-{bt_date%10000//100:02d}-{bt_date%100:02d}"
    if date_str == today:
        continue
    name = names.get(sym, sym)
    stage = "D趋势运行" if cur > ma60 else ("B启动" if cur > ma20 else "A洗盘")
    tdb.execute(
        "INSERT OR REPLACE INTO bottom_confirm_picks "
        "(date, symbol, name, status, score, stage, drop_pct, bottom_days, vol_shrink, streak, close_qfq, ma20, ma60) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (date_str, sym, name, "watch", score, stage, round(drop, 2), bd, vs, streak, cur, ma20, ma60))
    n += 1
tdb.commit()

stats = tdb.execute(
    "SELECT substr(date,1,4) y, status, COUNT(*) FROM bottom_confirm_picks GROUP BY y, status ORDER BY y").fetchall()
tdb.close()
print(f"写入2026 watch历史 {n} 条")
for y, st, c in stats:
    print(f"  {y} {st}: {c}")
