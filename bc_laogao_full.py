#!/usr/bin/env python3
"""全期验证: 2023-2026 worth候选 × 老高确认(7条件, ≥5确认)
无未来函数: 所有判定条件只用信号日及之前数据
"""
import sqlite3
from collections import defaultdict

SCORES_DB = "/home/ubuntu/trend-shrink-picks/bc_scores2.db"
DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"

conn = sqlite3.connect(SCORES_DB)
rows = conn.execute(
    "SELECT bt_date, symbol, score, s65, drop_pct, bottom_days FROM scores "
    "WHERE score BETWEEN 80 AND 88 AND s65>=4 AND bottom_days>=90 "
    "AND abs(drop_pct) BETWEEN 20 AND 65 AND is_st=0"
).fetchall()
conn.close()
print(f"全期worth候选: {len(rows)}")

db = sqlite3.connect(DB)
sym_all = set(r[1] for r in rows)
print(f"涉及股票: {len(sym_all)}")
series = {}
for sym in sym_all:
    c = db.execute(
        "SELECT date, close_qfq, volume FROM stock_daily WHERE symbol=? AND close_qfq>0 ORDER BY date",
        (sym,)).fetchall()
    series[sym] = c

def laogao_check(sym, bd, bottom_days):
    bd_str = f"{bd//10000}-{bd%10000//100:02d}-{bd%100:02d}"
    c = series.get(sym, [])
    idx_sig = next((i for i, r in enumerate(c) if r[0] == bd_str), None)
    if idx_sig is None or idx_sig < 60:
        return None
    def ma(n, at):
        if at - n + 1 < 0:
            return None
        return sum(r[1] for r in c[at-n+1:at+1]) / n
    ma20 = ma(20, idx_sig)
    ma60 = ma(60, idx_sig)
    ma20_5 = ma(20, idx_sig - 5)
    if ma20 is None or ma60 is None or ma20_5 is None:
        return None
    cur = c[idx_sig][1]
    vols = [r[2] for r in c[idx_sig-20:idx_sig]]
    avg_vol = sum(vols) / len(vols) if vols else 0
    vr = c[idx_sig][2] / avg_vol if avg_vol else 0
    r1 = cur > ma20 > ma60
    dist = (cur - ma20) / ma20 * 100
    r2 = 2 <= dist <= 15
    r3 = vr > 0.8
    r4 = bottom_days >= 120
    r5 = ma20 > ma20_5
    r6 = True
    for k in range(1, 6):
        if idx_sig - k < 1:
            break
        prev_c = c[idx_sig-k-1][1]
        chg = (c[idx_sig-k][1] / prev_c - 1) * 100
        vk = c[idx_sig-k][2]
        av = sum(r[2] for r in c[idx_sig-k-20:idx_sig-k]) / 20 if idx_sig-k >= 20 else avg_vol
        if chg < -3 and (vk / av if av else 0) > 1.2:
            r6 = False
            break
    r7 = False
    for k in range(1, 11):
        if idx_sig - k < 1:
            break
        prev_c = c[idx_sig-k-1][1]
        chg = (c[idx_sig-k][1] / prev_c - 1) * 100
        vk = c[idx_sig-k][2]
        av = sum(r[2] for r in c[idx_sig-k-20:idx_sig-k]) / 20 if idx_sig-k >= 20 else avg_vol
        if chg >= 3 and (vk / av if av else 0) >= 1.5:
            r7 = True
            break
    return (r1, r2, r3, r4, r5, r6, r7, dist, vr)

def rets(sym, bd):
    bd_str = f"{bd//10000}-{bd%10000//100:02d}-{bd%100:02d}"
    c = series.get(sym, [])
    idx_sig = next((i for i, r in enumerate(c) if r[0] == bd_str), None)
    if idx_sig is None:
        return None
    base = c[idx_sig][1]
    out = {}
    for h in [5, 10, 20]:
        if idx_sig + h < len(c):
            out[h] = (c[idx_sig+h][1] / base - 1) * 100
    return out

def stat(group, label, hkey=10):
    ra = [rets(r[1], r[0]) for r in group]
    ra = [x for x in ra if x]
    if not ra:
        print(f"  {label}: 无数据")
        return
    parts = []
    for h in [5, 10, 20]:
        vals = [x[h] for x in ra if h in x]
        if not vals:
            continue
        w = sum(1 for v in vals if v > 0)
        parts.append(f"T+{h} {w/len(vals)*100:.0f}%/{sum(vals)/len(vals):+.1f}%")
    print(f"  {label} (n={len(ra)}): " + " | ".join(parts))

# 全量老高确认
print("\n计算老高确认 (全期)...", flush=True)
res_all = []
for r in rows:
    lc = laogao_check(r[1], r[0], r[5])
    if lc is None:
        continue
    ok = sum(lc[:7])
    res_all.append((r, ok, ok >= 5))

print(f"可评估: {len(res_all)}")
print("\n=== 全期汇总 (2023-2026) ===")
stat([x[0] for x in res_all], "worth全部(基准)")
stat([x[0] for x in res_all if x[2]], "老高确认(>=5)")
stat([x[0] for x in res_all if not x[2]], "老高不确认")
stat([x[0] for x in res_all if x[1] >= 6], "老高6+分")
stat([x[0] for x in res_all if x[1] >= 7], "老高7/7严格")

print("\n=== 分年度 ===")
for yr in ['2023', '2024', '2025', '2026']:
    gg = [x for x in res_all if str(x[0][0]).startswith(yr)]
    print(f"\n-- {yr} (n={len(gg)}) --")
    stat([x[0] for x in gg], "全部")
    stat([x[0] for x in gg if x[2]], "老高确认(>=5)")
    stat([x[0] for x in gg if not x[2]], "老高不确认")
    if len([x for x in gg if x[1] >= 7]) >= 5:
        stat([x[0] for x in gg if x[1] >= 7], "7/7严格")

db.close()
