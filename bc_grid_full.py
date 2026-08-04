#!/usr/bin/env python3
"""
底部确认策略 — 全参数网格扫描(无未来函数)
维度: 确认阈值{50,55,60,65,70} × 确认期数{1,2,3,4,5} × 分数{70,75,78,80}
      × 底部{0,30,60} × 跌幅{不限,20-65,25-55,30-60} × MA60{Y,N}
目标: 信号量适中(每年100~500) + T+10胜率最高 + 2026年不亏
"""
import sqlite3, time
from itertools import product

SCORES_DB = "/home/ubuntu/trend-shrink-picks/bc_scores2.db"
DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"
# 列: 0bd 1sym 2score 3streak60 4s50 5s55 6s60 7s65 8s70 9drop 10bottom 11vs 12cur 13ma20 14ma60 15is_st

t0 = time.time()
conn = sqlite3.connect(SCORES_DB)
rows = conn.execute("SELECT * FROM scores").fetchall()
conn.close()
print(f"记录: {len(rows)} ({time.time()-t0:.0f}s)", flush=True)

# 收益缓存(所有非ST评分记录)
db = sqlite3.connect(DB)
ret_cache = {}
for i, r in enumerate(rows):
    if r[15]:
        continue
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

def evaluate(th, need, minscore, bottom_min, drop_range, ma60f, year=None):
    """th: 确认阈值(对应列4-8: 50/55/60/65/70); need: 连续期数; 其他过滤"""
    col = {50: 4, 55: 5, 60: 6, 65: 7, 70: 8}[th]
    out = []
    for r in rows:
        if r[15]:
            continue
        if r[2] < minscore:
            continue
        if r[col] < need:
            continue
        if bottom_min and r[10] < bottom_min:
            continue
        if drop_range and not (drop_range[0] <= abs(r[9]) <= drop_range[1]):
            continue
        if ma60f and not (r[12] > r[14]):
            continue
        rets = ret_cache.get((r[0], r[1]))
        if not rets:
            continue
        if year and not str(r[0]).startswith(year):
            continue
        out.append((r[0], r[2], rets))
    return out

def stat(group):
    if not group:
        return (0, None)
    parts = {}
    for h in [5, 10, 20]:
        vals = [g[2][h] for g in group if g[2].get(h) is not None]
        if not vals:
            continue
        wins = sum(1 for v in vals if v > 0)
        parts[h] = (wins/len(vals)*100, sum(vals)/len(vals))
    return (len(group), parts)

def fmt(s):
    if s[0] == 0:
        return "无"
    p = s[1]
    return f"n={s[0]} | " + " | ".join(f"T+{h}:{p[h][0]:.0f}%/{p[h][1]:+.1f}%" for h in [5,10,20] if h in p)

# ═══ 第一步: 阈值×期数×分数 (不加底部/跌幅/MA60) ═══
print("\n" + "="*100)
print("第一步: 确认阈值 × 期数 × 分数 (无其他过滤)")
print("="*100)
results1 = []
for th, need, ms in product([50, 55, 60, 65, 70], [1, 2, 3, 4, 5], [70, 75, 78, 80]):
    g = evaluate(th, need, ms, 0, None, False)
    s = stat(g)
    if s[0] < 300:  # 信号太少跳过(2年<300≈每年<150)
        continue
    y26 = stat(evaluate(th, need, ms, 0, None, False, '2026'))
    y26s = f"26:{y26[0]}/" + (f"T10:{y26[1][10][0]:.0f}%/{y26[1][10][1]:+.1f}%" if y26[1] and 10 in y26[1] else "--")
    results1.append((th, need, ms, s[0], s[1], y26[0], y26s))
    print(f"  阈值{th} 期数{need} 分数{ms}: {fmt(s)} | {y26s}")
print(f"\n第一步完成 ({time.time()-t0:.0f}s)")

# ═══ 第二步: 代表组合 × 底部 × 跌幅 × MA60 ═══
print("\n" + "="*100)
print("第二步: 核心组合 × 底部时长 × 跌幅范围 × MA60")
print("="*100)
base_combos = [(65, 3, 78), (70, 3, 78), (70, 4, 80), (60, 3, 75), (65, 4, 75)]
bottoms = [0, 30, 60]
drops = [None, (20, 65), (25, 55), (30, 60)]
ma60s = [False, True]
for th, need, ms in base_combos:
    print(f"\n── 阈值{th} 期数{need} 分数{ms} ──")
    for bm, dr, mf in product(bottoms, drops, ma60s):
        g = evaluate(th, need, ms, bm, dr, mf)
        s = stat(g)
        if s[0] < 200:
            continue
        y26 = stat(evaluate(th, need, ms, bm, dr, mf, '2026'))
        y26s = f"26:{y26[0]}/" + (f"T10:{y26[1][10][0]:.0f}%/{y26[1][10][1]:+.1f}%" if y26[1] and 10 in y26[1] else "--")
        bm_s = str(bm) if bm else "无"
        dr_s = f"{dr[0]}-{dr[1]}" if dr else "不限"
        mf_s = "Y" if mf else "N"
        print(f"  底{bm_s:>3} 跌{dr_s:>6} MA60{mf_s}: {fmt(s)} | {y26s}")
print(f"\n总用时 {time.time()-t0:.0f}s")
