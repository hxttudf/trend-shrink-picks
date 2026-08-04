#!/usr/bin/env python3
"""分析: 年度分布 + 分数段胜率 + 满分案例"""
import sqlite3
from collections import defaultdict

SCORES_DB = "/home/ubuntu/trend-shrink-picks/bc_scores2.db"
DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"

conn = sqlite3.connect(SCORES_DB)
rows = conn.execute(
    "SELECT bt_date, symbol, score, s65, drop_pct, bottom_days, cur, ma20, ma60 "
    "FROM scores WHERE score>=75 AND s65>=4 AND bottom_days>=60 "
    "AND abs(drop_pct) BETWEEN 20 AND 65 AND is_st=0"
).fetchall()
conn.close()

db = sqlite3.connect(DB)
def rets_of(bd, sym):
    bd_str = f"{bd//10000}-{bd%10000//100:02d}-{bd%100:02d}"
    fut = db.execute(
        "SELECT close_qfq FROM stock_daily WHERE symbol=? AND close_qfq>0 AND date>? ORDER BY date LIMIT 20",
        (sym, bd_str)).fetchall()
    cur = db.execute(
        "SELECT close_qfq FROM stock_daily WHERE symbol=? AND date=? AND close_qfq>0",
        (sym, bd_str)).fetchone()
    if not cur: return None
    base = cur[0]
    return {h: (fut[h-1][0]/base-1)*100 if len(fut) >= h else None for h in [5, 10, 20]}

# 1) 年度分布
by_year = defaultdict(int)
for r in rows: by_year[str(r[0])[:4]] += 1
print("=== 年度信号分布 ===")
for y in sorted(by_year): print(f"  {y}: {by_year[y]}个")

# 2) 分数段胜率
print("\n=== 分数段表现 (V2信号) ===")
bands = [(75, 80), (80, 85), (85, 90), (90, 95), (95, 101)]
for lo, hi in bands:
    g = [r for r in rows if lo <= r[2] < hi]
    rets_all = []
    for r in g:
        rets = rets_of(r[0], r[1])
        if rets: rets_all.append(rets)
    if not rets_all: continue
    parts = []
    for h in [5, 10, 20]:
        vals = [x[h] for x in rets_all if x[h] is not None]
        if not vals: continue
        w = sum(1 for v in vals if v > 0)
        parts.append(f"T+{h} {w/len(vals)*100:.0f}%/{sum(vals)/len(vals):+.1f}%")
    print(f"  {lo}~{hi}分 (n={len(rets_all)}): " + " | ".join(parts))

# 3) 高分(>=95) vs 中分(75-85) 分年度
print("\n=== 95+分 vs 75-85分 分年度 T+10 ===")
for yr in ['2024', '2025', '2026']:
    for label, lo, hi in [("75-85分", 75, 85), ("95+分", 95, 101)]:
        g = [r for r in rows if str(r[0]).startswith(yr) and lo <= r[2] < hi]
        vals = []
        for r in g:
            rets = rets_of(r[0], r[1])
            if rets and rets[10] is not None: vals.append(rets[10])
        if vals:
            w = sum(1 for v in vals if v > 0)
            print(f"  {yr} {label} (n={len(vals)}): T+10 胜率{w/len(vals)*100:.0f}% 均收{sum(vals)/len(vals):+.1f}%")

# 4) 满分案例
print("\n=== 满分(>=98)信号案例 ===")
top = sorted([r for r in rows if r[2] >= 98], key=lambda r: -r[2])
for r in top[:6]:
    rets = rets_of(r[0], r[1])
    print(f"  {r[0]} {r[1]} {r[2]:.0f}分 跌幅{r[4]:.1f}% 底部{r[5]}天 现价{r[6]:.2f} MA60={r[8]:.2f}")
    if rets:
        print(f"    → T+5 {rets[5]:+.1f}% | T+10 {rets[10]:+.1f}% | T+20 {rets[20]:+.1f}%")

# 5) 高分信号的构成分析: 100分的票有什么特征
print("\n=== 98+分信号特征 vs 全部V2信号 ===")
hi = [r for r in rows if r[2] >= 98]
lo = rows
for label, g in [("98+分", hi), ("全部", lo)]:
    if not g: continue
    drops = [abs(r[4]) for r in g]
    bottoms = [r[5] for r in g]
    print(f"  {label} (n={len(g)}): 跌幅均值{drops and sum(drops)/len(drops):.1f}% 底部均值{bottoms and sum(bottoms)/len(bottoms):.0f}天")

db.close()
