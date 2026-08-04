#!/usr/bin/env python3
"""
底部确认策略 — 参数扫描(基于bc_scores2.db, 无未来函数)
在B口径(score>=75 & streak>=4 & 非ST)基础上收紧:
  分数门槛 / 确认期数 / 站上MA60 / 底部时长 / 缩量程度
目标: 信号量适中(每年100~400个) + 胜率最高
"""
import sqlite3, time
from itertools import product

SCORES_DB = "/home/ubuntu/trend-shrink-picks/bc_scores2.db"
DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"

t0 = time.time()
conn = sqlite3.connect(SCORES_DB)
all_rows = conn.execute(
    "SELECT bt_date, symbol, score, streak, drop_pct, bottom_days, vol_shrink, cur, ma20, ma60, is_st FROM scores"
).fetchall()
conn.close()
print(f"评分记录: {len(all_rows)} ({time.time()-t0:.0f}s)", flush=True)

# B信号集(收益缓存)
B_sigs = [r for r in all_rows if r[2] >= 75 and r[3] >= 4 and r[10] == 0]
print(f"B信号集: {len(B_sigs)}", flush=True)

# 收益缓存
db = sqlite3.connect(DB)
ret_cache = {}
for i, r in enumerate(B_sigs):
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
print(f"收益缓存: {len(ret_cache)} ({time.time()-t0:.0f}s)", flush=True)

def stat(group, label=""):
    n = len(group)
    if n == 0:
        return None
    parts = []
    for h in [5, 10, 20]:
        vals = [g[3][h] for g in group if g[3].get(h) is not None]
        if not vals:
            continue
        wins = sum(1 for v in vals if v > 0)
        parts.append(f"T+{h}:{wins/len(vals)*100:.0f}%/{sum(vals)/len(vals):+.1f}%")
    return n, " | ".join(parts)

def evaluate(filters, year=None):
    """filters: dict of (col_idx, op, val). 支持 '>ma60' 列间比较. 返回组"""
    out = []
    for r in B_sigs:
        ok = True
        for idx, op, val in filters:
            v = r[idx]
            if op == '>=' and not (v >= val): ok = False; break
            if op == '<=' and not (v <= val): ok = False; break
            if op == '<' and not (v < val): ok = False; break
            if op == 'range' and not (val[0] <= v <= val[1]): ok = False; break
            if op == '>ma60' and not (r[7] > r[9]): ok = False; break
            if op == '>ma20' and not (r[7] > r[8]): ok = False; break
        if not ok:
            continue
        rets = ret_cache.get((r[0], r[1]))
        if not rets:
            continue
        if year and not str(r[0]).startswith(year):
            continue
        out.append((r[0], r[1], r[2], rets))
    return out

# ═══ 单维度扫描 ═══
def scan_single():
    print("\n" + "="*90)
    print("单维度收紧 (在B基础上)")
    print("="*90)
    # 分数门槛
    print("\n-- 分数门槛 --")
    for s in [75, 78, 80, 82, 85]:
        r = stat(evaluate([(2, '>=', s)]), f"score>={s}")
        print(f"  score>={s}: {r}")
    # 确认期数
    print("\n-- 确认期数 --")
    for st in [4, 5, 6, 7]:
        r = stat(evaluate([(3, '>=', st)]), f"streak>={st}")
        print(f"  streak>={st}: {r}")
    # 站上MA60
    print("\n-- 站上MA60 (cur > ma60) --")
    r = stat(evaluate([(7, '>', 8)]), "cur>ma60")
    print(f"  cur>ma60: {r}")
    # 底部时长
    print("\n-- 底部时长 --")
    for bd_days in [30, 60, 90, 120]:
        r = stat(evaluate([(5, '>=', bd_days)]), f"bottom>={bd_days}")
        print(f"  bottom>={bd_days}天: {r}")
    # 缩量
    print("\n-- 缩量程度 --")
    for vs in [0.7, 0.5, 0.4]:
        r = stat(evaluate([(6, '<', vs)]), f"vs<{vs}")
        print(f"  vol_shrink<{vs}: {r}")
    # 跌幅范围
    print("\n-- 跌幅范围 --")
    for lo, hi in [(20, 50), (25, 55), (30, 60)]:
        r = stat(evaluate([(4, 'range', (-hi, -lo))]), f"drop{lo}-{hi}")
        print(f"  drop {lo}~{hi}%: {r}")

scan_single()

# ═══ 组合扫描 ═══
print("\n" + "="*90)
print("组合扫描2 (跌幅范围 × 底部时长 × MA60 × 分数)")
print("="*90)
print(f"{'分数':>4}{'期数':>4}{'MA60':>5}{'底60':>5}{'跌幅':>8} | {'n':>5} | T+5 | T+10 | T+20 | 2026 T+10")
print("-"*100)
combos = []
for score, streak, ma60f, bottom60, droprange in product(
        [75, 78, 80], [4, 5], [False, True], [False, True],
        [(20, 65), (30, 60), (25, 55)]):
    flt = [(2, '>=', score), (3, '>=', streak), (4, 'range', (-droprange[1], -droprange[0]))]
    if ma60f:
        flt.append((7, '>ma60', 0))
    if bottom60:
        flt.append((5, '>=', 60))
    g = evaluate(flt)
    n = len(g)
    if n < 150:
        continue
    y26g = evaluate(flt, '2026')
    y26 = stat(y26g)
    s5 = stat(g)
    if s5 is None:
        continue
    y26_str = f"{y26[0]}/{y26[1].split('|')[1].strip()}" if y26 and '|' in y26[1] else "0"
    print(f"{score:>4}{streak:>4}{'Y' if ma60f else 'N':>5}{'Y' if bottom60 else 'N':>5}{str(droprange):>8} | {s5[0]:>5} | {s5[1]} | {y26_str}")

print(f"\n总用时 {time.time()-t0:.0f}s")
