#!/usr/bin/env python3
"""2026年观察(watch)标的回测 — 与daily脚本口径一致
watch判定(daily): analyze确认>=4期(阈值65) 且 score>=65 且 不满足worth硬条件
worth硬条件: 80<=score<=88 AND bottom>=90 AND 20<=drop<=65
注意: 市场过滤+Top3只作用于worth, 不影响watch名单本身
"""
import sqlite3
from collections import defaultdict

SCORES_DB = "/home/ubuntu/trend-shrink-picks/bc_scores2.db"
DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"

conn = sqlite3.connect(SCORES_DB)
rows = conn.execute(
    "SELECT bt_date, symbol, score, s65, drop_pct, bottom_days FROM scores "
    "WHERE s65>=4 AND score>=65 AND bt_date LIKE '2026%' AND is_st=0"
).fetchall()
conn.close()
print(f"2026候选(确认>=4期+分数>=65): {len(rows)}")

# 分类: worth vs watch (按daily脚本逻辑)
worth = []
watch = []
for r in rows:
    score = r[2]
    is_worth = (80 <= score <= 88 and r[5] >= 90 and 20 <= abs(r[4]) <= 65)
    if is_worth:
        worth.append(r)
    else:
        watch.append(r)
print(f"worth候选: {len(worth)} | watch: {len(watch)}")

db = sqlite3.connect(DB)
def rets(bd, sym):
    bd_str = f"{bd//10000}-{bd%10000//100:02d}-{bd%100:02d}"
    fut = db.execute(
        "SELECT close_qfq FROM stock_daily WHERE symbol=? AND close_qfq>0 AND date>? ORDER BY date LIMIT 20",
        (sym, bd_str)).fetchall()
    cur = db.execute(
        "SELECT close_qfq FROM stock_daily WHERE symbol=? AND date=? AND close_qfq>0",
        (sym, bd_str)).fetchone()
    if not cur:
        return None
    base = cur[0]
    return {h: (fut[h-1][0]/base-1)*100 if len(fut) >= h else None for h in [5, 10, 20]}

def stat(group, label):
    ra = [rets(r[0], r[1]) for r in group]
    ra = [x for x in ra if x]
    if not ra:
        print(f"  {label}: 无收益数据")
        return
    parts = []
    for h in [5, 10, 20]:
        vals = [x[h] for x in ra if x[h] is not None]
        if not vals:
            continue
        w = sum(1 for v in vals if v > 0)
        avg_w = sum(v for v in vals if v > 0) / max(1, sum(1 for v in vals if v > 0))
        avg_l = sum(v for v in vals if v <= 0) / max(1, sum(1 for v in vals if v <= 0))
        parts.append(f"T+{h} {w/len(vals)*100:.0f}%/{sum(vals)/len(vals):+.1f}% (盈{avg_w:+.1f}/亏{avg_l:+.1f})")
    print(f"  {label} (n={len(ra)}): " + " | ".join(parts))

print("\n=== 2026 全量对比 ===")
stat(watch, "watch观察名单(全部)")
stat(worth, "worth候选(未过滤)")

# watch按分数段
print("\n=== watch 分数段 ===")
for lo, hi in [(65, 70), (70, 75), (75, 80), (80, 100)]:
    g = [r for r in watch if lo <= r[2] < hi]
    stat(g, f"{lo}-{hi}分")

# watch按底部
print("\n=== watch 底部时长段 ===")
for lo, hi in [(0, 30), (30, 60), (60, 90), (90, 1000)]:
    g = [r for r in watch if lo <= r[5] < hi]
    stat(g, f"底{lo}-{hi}天")

# watch按季度
print("\n=== watch 分季度 ===")
for q, (a, b) in {"Q1": ("20260101", "20260331"), "Q2": ("20260401", "20260630"),
                   "Q3": ("20260701", "20260930")}.items():
    g = [r for r in watch if a <= str(r[0]) <= b]
    stat(g, q)

# 未来函数检查: streak/评分只含历史信息(库构建时已验证), 这里抽查s65分布
print("\n=== watch 确认期数分布 ===")
cnt = defaultdict(int)
for r in watch:
    cnt[r[3]] += 1
for k in sorted(cnt):
    print(f"  {k}期: {cnt[k]}个")

db.close()
