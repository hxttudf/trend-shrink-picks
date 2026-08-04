#!/usr/bin/env python3
"""推荐组合分年度验证"""
import sqlite3
from collections import defaultdict

SCORES_DB = "/home/ubuntu/trend-shrink-picks/bc_scores2.db"
DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"

conn = sqlite3.connect(SCORES_DB)
all_rows = conn.execute(
    "SELECT bt_date, symbol, score, streak, drop_pct, bottom_days, vol_shrink, cur, ma20, ma60, is_st FROM scores"
).fetchall()
conn.close()

B_sigs = [r for r in all_rows if r[2] >= 75 and r[3] >= 4 and r[10] == 0]

db = sqlite3.connect(DB)
ret_cache = {}
for r in B_sigs:
    bd, sym = r[0], r[1]
    bd_str = f"{bd//10000}-{bd%10000//100:02d}-{bd%100:02d}"
    fut = db.execute(
        "SELECT close_qfq FROM stock_daily WHERE symbol=? AND close_qfq>0 AND date>? ORDER BY date LIMIT 20",
        (sym, bd_str)).fetchall()
    cur = db.execute(
        "SELECT close_qfq FROM stock_daily WHERE symbol=? AND date=? AND close_qfq>0",
        (sym, bd_str)).fetchone()
    if not cur:
        continue
    base = cur[0]
    rets = {}
    for h in [5, 10, 20]:
        rets[h] = (fut[h-1][0]/base - 1)*100 if len(fut) >= h else None
    ret_cache[(bd, sym)] = rets
db.close()

def evaluate(flt, year=None):
    out = []
    for r in B_sigs:
        ok = True
        for idx, op, val in flt:
            v = r[idx]
            if op == '>=' and not (v >= val): ok = False; break
            if op == 'range' and not (val[0] <= v <= val[1]): ok = False; break
            if op == '>ma60' and not (r[7] > r[9]): ok = False; break
        if not ok:
            continue
        rets = ret_cache.get((r[0], r[1]))
        if not rets:
            continue
        if year and not str(r[0]).startswith(year):
            continue
        out.append((r[0], r[1], r[2], rets))
    return out

def stat(group, label):
    if not group:
        print(f"  {label}: 无"); return
    parts = []
    for h in [5, 10, 20]:
        vals = [g[3][h] for g in group if g[3].get(h) is not None]
        if not vals: continue
        wins = sum(1 for v in vals if v > 0)
        parts.append(f"T+{h} {wins/len(vals)*100:.0f}%/{sum(vals)/len(vals):+.1f}%")
    print(f"  {label} (n={len(group)}): {' | '.join(parts)}")

combos = {
    "方案A 均衡(78/5/底60/跌25-55/MA60)": [(2,'>=',78),(3,'>=',5),(5,'>=',60),(4,'range',(-55,-25)),(7,'>ma60',0)],
    "方案B 精简(75/5/底60/跌30-60)": [(2,'>=',75),(3,'>=',5),(5,'>=',60),(4,'range',(-60,-30))],
    "方案C 多信号(75/4/底60/跌20-65)": [(2,'>=',75),(3,'>=',4),(5,'>=',60),(4,'range',(-65,-20))],
    "方案D 原B口径(75/4)": [(2,'>=',75),(3,'>=',4)],
}
for name, flt in combos.items():
    print(f"\n{'='*70}\n{name}\n{'='*70}")
    g = evaluate(flt)
    stat(g, "全部")
    for yr in ['2024', '2025', '2026']:
        stat(evaluate(flt, yr), yr)
