#!/usr/bin/env python3
"""补充验证: 连续期数确认的分年度稳健性"""
import sqlite3
from collections import defaultdict

SCORES_DB = "/home/ubuntu/trend-shrink-picks/bt_scores.db"
DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"
TOP_N = 10
MIN_SCORE = 70

btdb = sqlite3.connect(SCORES_DB)
conn = sqlite3.connect(DB)

btdates = [r[0] for r in btdb.execute("SELECT DISTINCT bt_date FROM scores ORDER BY bt_date")]
top_by_date = {bd: btdb.execute(
    "SELECT symbol, score, is_oneword FROM scores WHERE bt_date=? ORDER BY score DESC LIMIT ?",
    (bd, TOP_N)).fetchall() for bd in btdates}

all_scores = btdb.execute("SELECT bt_date, symbol, score FROM scores").fetchall()
sym_dates = defaultdict(set)
for bd, sym, sc in all_scores:
    if sc >= MIN_SCORE:
        sym_dates[sym].add(bd)

consec = {}
for sym, date_set in sym_dates.items():
    streak = 0
    for bd in reversed(btdates):
        if bd in date_set:
            streak += 1
            consec[(bd, sym)] = streak
        else:
            streak = 0

# 构建信号(带streak)
signals = []
for bd in btdates:
    bd_str = f"{bd//10000}-{bd%10000//100:02d}-{bd%100:02d}"
    for sym, score, is_ow in top_by_date[bd]:
        streak = consec.get((bd, sym), 0)
        fut = conn.execute("SELECT close_qfq FROM stock_daily WHERE symbol=? AND close_qfq>0 AND date>? ORDER BY date LIMIT 20", (sym, bd_str)).fetchall()
        cur = conn.execute("SELECT close_qfq FROM stock_daily WHERE symbol=? AND date=? AND close_qfq>0", (sym, bd_str)).fetchone()
        if not cur: continue
        base = cur[0]
        rets = {}
        for h in [1, 5, 10, 20]:
            rets[h] = (fut[h-1][0]/base - 1)*100 if len(fut) >= h else None
        signals.append((bd_str, sym, streak, rets))

def stat(group, label):
    if not group:
        print(f"  {label}: 无信号"); return
    parts = []
    for h in [1, 5, 10, 20]:
        vals = [s[3][h] for s in group if s[3].get(h) is not None]
        if not vals: continue
        wins = sum(1 for v in vals if v > 0)
        avg = sum(vals)/len(vals)
        parts.append(f"T+{h} {wins/len(vals)*100:.0f}%/{avg:+.1f}%")
    print(f"  {label} (n={len(group)}): {' | '.join(parts)}")

# 年度 × 连续期数
print("="*70)
print("年度稳健性: 连续期数确认在各年份的表现 (胜率/均收)")
print("="*70)
for yr in ['2024', '2025', '2026']:
    g = [s for s in signals if s[0].startswith(yr)]
    print(f"\n  --- {yr}年 ---")
    stat([s for s in g if s[2] >= 1], "  连续>=1期(基线)")
    stat([s for s in g if s[2] >= 2], "  连续>=2期")
    stat([s for s in g if s[2] >= 3], "  连续>=3期")

btdb.close(); conn.close()
