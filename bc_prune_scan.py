#!/usr/bin/env python3
"""V3精简扫描: 条件收紧 × 每日TopN × 市场过滤
目标: 每天<=3个信号(年<=750) + 胜率尽量高"""
import sqlite3
from collections import defaultdict

SCORES_DB = "/home/ubuntu/trend-shrink-picks/bc_scores2.db"
DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"

conn = sqlite3.connect(SCORES_DB)
rows = conn.execute(
    "SELECT bt_date, symbol, score, s65, drop_pct, bottom_days FROM scores "
    "WHERE score BETWEEN 75 AND 88 AND s65>=4 AND bottom_days>=60 "
    "AND abs(drop_pct) BETWEEN 20 AND 65 AND is_st=0"
).fetchall()
conn.close()

# 上证指数 MA60 (市场过滤)
db = sqlite3.connect(DB)
idx = [r[0] for r in db.execute(
    "SELECT date FROM stock_daily WHERE symbol='000001.SH' AND close_qfq>0 ORDER BY date")]
idx_close = [r[0] for r in db.execute(
    "SELECT close_qfq FROM stock_daily WHERE symbol='000001.SH' AND close_qfq>0 ORDER BY date")]
idx_ma60 = {}
for i in range(59, len(idx_close)):
    idx_ma60[int(idx[i].replace('-', ''))] = sum(idx_close[i-59:i+1]) / 60

def rets(bd, sym):
    bd_str = f"{bd//10000}-{bd%10000//100:02d}-{bd%100:02d}"
    fut = db.execute(
        "SELECT close_qfq FROM stock_daily WHERE symbol=? AND close_qfq>0 AND date>? ORDER BY date LIMIT 10",
        (sym, bd_str)).fetchall()
    cur = db.execute(
        "SELECT close_qfq FROM stock_daily WHERE symbol=? AND date=? AND close_qfq>0",
        (sym, bd_str)).fetchone()
    if not cur or len(fut) < 10:
        return None
    return (fut[9][0]/cur[0]-1)*100

# 每回测日的上证收盘
idx_close_by_date = {}
for i, d in enumerate(idx):
    idx_close_by_date[int(d.replace('-', ''))] = idx_close[i]

def run(score_lo, score_hi, need_streak, bottom_min, topn, mkt_filter):
    sigs = [r for r in rows if score_lo <= r[2] <= score_hi and r[3] >= need_streak
            and r[5] >= bottom_min]
    if topn:
        # 每回测日按分数取前N
        by_bd = defaultdict(list)
        for r in sigs:
            by_bd[r[0]].append(r)
        sigs = []
        for bd, lst in by_bd.items():
            lst.sort(key=lambda r: -r[2])
            sigs.extend(lst[:topn])
    out = {}
    for yr in ['2023', '2024', '2025', '2026']:
        gg = [r for r in sigs if str(r[0]).startswith(yr)]
        if mkt_filter:
            gg = [r for r in gg if idx_close_by_date.get(r[0], 0) > idx_ma60.get(r[0], 0)]
        vals = []
        for r in gg:
            v = rets(r[0], r[1])
            if v is not None:
                vals.append(v)
        n = len(vals)
        if n:
            w = sum(1 for v in vals if v > 0)
            out[yr] = (n, w/n*100, sum(vals)/n)
    return out

combos = [
    # (分数下限, 期数, 底部, TopN, 市场过滤)
    ("V3原版",               75, 4, 60, 0, False),
    ("分数80+",              80, 4, 60, 0, False),
    ("期数5",                75, 5, 60, 0, False),
    ("底部90",               75, 4, 90, 0, False),
    ("Top5",                 75, 4, 60, 5, False),
    ("Top3",                 75, 4, 60, 3, False),
    ("Top5+市场过滤",        75, 4, 60, 5, True),
    ("Top3+市场过滤",        75, 4, 60, 3, True),
    ("分数80+Top5",          80, 4, 60, 5, False),
    ("分数80+Top3",          80, 4, 60, 3, False),
    ("分数80+期数5+Top3",    80, 5, 60, 3, False),
    ("分数80+期数5+Top3+市场", 80, 5, 60, 3, True),
    ("分数80+底部90+Top3",   80, 4, 90, 3, False),
    ("分数80+底部90+Top3+市场", 80, 4, 90, 3, True),
]
print(f"{'组合':<22}{'2023':>24}{'2024':>24}{'2025':>24}{'2026':>24}")
print("-"*120)
for name, sl, ns, bm, topn, mf in combos:
    res = run(sl, 88, ns, bm, topn, mf)
    parts = []
    for yr in ['2023', '2024', '2025', '2026']:
        if yr in res:
            n, w, avg = res[yr]
            parts.append(f"{yr}:{n}个/{w:.0f}%/{avg:+.1f}%")
        else:
            parts.append(f"{yr}:--")
    print(f"{name:<22}" + " | ".join(parts))
db.close()
