#!/usr/bin/env python3
"""2026年watch信号 × 老高确认 → 回测 (与bc_laogao_confirm.py同逻辑, watch池)
watch: s65>=4 AND score>=65 AND 非worth硬条件(80-88分/底90/跌20-65)
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
print(f"2026候选: {len(rows)}")

# 分worth/watch
worth = []
watch = []
for r in rows:
    if 80 <= r[2] <= 88 and r[5] >= 90 and 20 <= abs(r[4]) <= 65:
        worth.append(r)
    else:
        watch.append(r)
print(f"worth: {len(worth)} | watch: {len(watch)}")

db = sqlite3.connect(DB)
sym_all = set(r[1] for r in watch) | set(r[1] for r in worth)
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

def stat(group, label):
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
        avg_w = sum(v for v in vals if v > 0) / max(1, sum(1 for v in vals if v > 0))
        avg_l = sum(v for v in vals if v <= 0) / max(1, sum(1 for v in vals if v <= 0))
        parts.append(f"T+{h} {w/len(vals)*100:.0f}%/{sum(vals)/len(vals):+.1f}% (盈{avg_w:+.1f}/亏{avg_l:+.1f})")
    print(f"  {label} (n={len(ra)}): " + " | ".join(parts))

# 老高确认应用到watch
print("\n计算老高确认...", flush=True)
watch_lg = []
n_none = 0
for r in watch:
    lc = laogao_check(r[1], r[0], r[5])
    if lc is None:
        n_none += 1
        continue
    ok_cnt = sum(lc[:7])
    watch_lg.append((r, ok_cnt, ok_cnt >= 5))

print(f"watch可评估: {len(watch_lg)} (跳过{n_none})")
print("\n=== 2026 watch × 老高确认 ===")
stat(watch, "watch全部(基准)")
stat([x[0] for x in watch_lg if x[2]], "watch+老高确认(>=5)")
stat([x[0] for x in watch_lg if not x[2]], "watch+老高不确认")
print("\n=== 与worth对比 ===")
worth_lg = []
for r in worth:
    lc = laogao_check(r[1], r[0], r[5])
    if lc is None:
        continue
    ok_cnt = sum(lc[:7])
    worth_lg.append((r, ok_cnt, ok_cnt >= 5))
stat(worth, "worth全部")
stat([x[0] for x in worth_lg if x[2]], "worth+老高确认(>=5)")
stat([x[0] for x in worth_lg if not x[2]], "worth+老高不确认")

print("\n=== 老高确认条件满足率 (watch池) ===")
if watch_lg:
    for i, name in [(0,'R1多头'), (1,'R2距MA20'), (2,'R3量比'), (3,'R4长底'), (4,'R5 MA20上'), (5,'R6无出货'), (6,'R7启动')]:
        print(f"  {name}: {sum(1 for x in watch_lg if x[0] and False)}")

# 按ok_cnt分档
print("\n=== watch 按老高分数分档 (T+10) ===")
for lo, hi in [(0, 3), (3, 5), (5, 7), (7, 8)]:
    g = [x[0] for x in watch_lg if lo <= x[1] < hi]
    stat(g, f"{lo}-{hi}分")

db.close()
