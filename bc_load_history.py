#!/usr/bin/env python3
"""
把V2参数的历史回测信号刷入 bottom_confirm_picks 表
V2: 阈值65 + 期数4 + 分数75 + 底部>=60天 + 跌幅20~65% + 非ST
stockscope 底部确认tab 即可按日期浏览历史信号
"""
import sqlite3

SCORES_DB = "/home/ubuntu/trend-shrink-picks/bc_scores2.db"
DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"
TREND_DB = "/home/ubuntu/databases/trend_picks.db"

# 读取V2历史信号
conn = sqlite3.connect(SCORES_DB)
rows = conn.execute(
    "SELECT bt_date, symbol, score, s65, drop_pct, bottom_days, vol_shrink, cur, ma20, ma60, is_st "
    "FROM scores WHERE score >= 75 AND s65 >= 4 AND bottom_days >= 60 "
    "AND abs(drop_pct) BETWEEN 20 AND 65 AND is_st = 0"
).fetchall()
conn.close()
print(f"V2历史信号: {len(rows)} 条")

# 名称
db = sqlite3.connect(DB)
names = dict(db.execute(
    "SELECT symbol, name FROM stock_basics WHERE date=(SELECT MAX(date) FROM stock_basics)"
).fetchall())
db.close()

# 写入
tdb = sqlite3.connect(TREND_DB)
n = 0
for bt_date, sym, score, streak, drop, bd, vs, cur, ma20, ma60, _ in rows:
    date_str = f"{bt_date//10000}-{bt_date%10000//100:02d}-{bt_date%100:02d}"
    name = names.get(sym, sym)
    # stage: 站上MA60=D趋势, 否则=C回调确认(已站上MA20)
    stage = "D趋势运行" if cur > ma60 else "C回调确认"
    tdb.execute(
        "INSERT OR REPLACE INTO bottom_confirm_picks "
        "(date, symbol, name, status, score, stage, drop_pct, bottom_days, vol_shrink, streak, close_qfq, ma20, ma60) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (date_str, sym, name, "worth", score, stage, round(drop, 2), bd, vs, streak, cur, ma20, ma60)
    )
    n += 1
tdb.commit()

# 统计
dates = tdb.execute("SELECT date, status, COUNT(*) FROM bottom_confirm_picks GROUP BY date, status ORDER BY date DESC LIMIT 15").fetchall()
tdb.close()
print(f"写入 {n} 条")
print("最近日期分布:")
for d, st, c in dates:
    print(f"  {d} {st}: {c}")
