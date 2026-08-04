#!/usr/bin/env python3
"""缠论分析: K线包含合并→分型→笔→中枢→背驰 (德赛西威600089)"""
import sqlite3

DB = '/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db'
conn = sqlite3.connect(DB)
rows = conn.execute(
    "SELECT date, open, high, low, close, close_qfq, volume FROM stock_daily "
    "WHERE symbol='600089' AND close_qfq>0 ORDER BY date").fetchall()
conn.close()
print(f"德赛西威 日线 {len(rows)}根 ({rows[0][0]}~{rows[-1][0]})")

# ── 1. K线包含处理 ──
def merge_inclusion(k):
    """k: [(date, h, l, ...)] 返回合并后的 [(date, h, l)]"""
    merged = []
    for r in k:
        h, l = r[2], r[3]
        if not merged:
            merged.append([r[0], h, l])
            continue
        # 包含关系: 前一根完全包含当前 或 当前完全包含前一根
        ph, pl = merged[-1][1], merged[-1][2]
        if (h >= ph and l <= pl) or (h <= ph and l >= pl):
            # 方向: 用合并序列最后两根比较
            if len(merged) >= 2:
                dir_up = merged[-1][1] > merged[-2][1]
            else:
                dir_up = h >= ph
            if dir_up:
                merged[-1][1] = max(ph, h)
                merged[-1][2] = max(pl, l)
            else:
                merged[-1][1] = min(ph, h)
                merged[-1][2] = min(pl, l)
        else:
            merged.append([r[0], h, l])
    return merged

merged = merge_inclusion(rows)
print(f"包含处理后: {len(merged)}根")

# ── 2. 分型识别 ──
fractals = []  # (idx, type, price) type: 'top'/'bottom'
for i in range(1, len(merged) - 1):
    h0, l0 = merged[i-1][1], merged[i-1][2]
    h1, l1 = merged[i][1], merged[i][2]
    h2, l2 = merged[i+1][1], merged[i+1][2]
    if h1 > h0 and h1 > h2 and l1 > l0 and l1 > l2:
        fractals.append((i, 'top', h1))
    elif l1 < l0 and l1 < l2 and h1 < h0 and h1 < h2:
        fractals.append((i, 'bottom', l1))

# ── 3. 笔划分 (顶底交替, 间隔>=4根合并K线) ──
bi = []  # [(idx, type, price)]
for f in fractals:
    if not bi:
        bi.append(f)
        continue
    if f[1] == bi[-1][1]:
        # 同类型: 保留更极端的
        if (f[1] == 'top' and f[2] > bi[-1][2]) or (f[1] == 'bottom' and f[2] < bi[-1][2]):
            bi[-1] = f
    else:
        if f[0] - bi[-1][0] >= 4:
            bi.append(f)
        else:
            # 间隔不够, 保留力度更大的
            if (f[1] == 'top' and f[2] > bi[-1][2]) or (f[1] == 'bottom' and f[2] < bi[-1][2]):
                bi[-1] = f

print(f"\n分型总数: {len(fractals)} | 笔数: {len(bi)}")
print("\n=== 最近10笔 ===")
for b in bi[-10:]:
    print(f"  {merged[b[0]][0]} {b[1]:6s} {b[2]:8.2f}")

# ── 4. 中枢识别 (最近三笔重叠) ──
def find_zhongshu(bis):
    """连续3笔的重叠区间"""
    zs_list = []
    for i in range(len(bis) - 2):
        a, b, c = bis[i], bis[i+1], bis[i+2]
        # 三笔的区间
        segs = []
        for x, y in [(a, b), (b, c)]:
            lo, hi = min(x[2], y[2]), max(x[2], y[2])
            segs.append((lo, hi))
        zs_hi = min(s[1] for s in segs)
        zs_lo = max(s[0] for s in segs)
        if zs_hi > zs_lo:
            zs_list.append((i, zs_lo, zs_hi, a[0], c[0]))
    return zs_list

zs_list = find_zhongshu(bi)
print(f"\n中枢数: {len(zs_list)}")
for zs in zs_list[-4:]:
    print(f"  中枢[{zs[3]}~{zs[4]}]: {zs[1]:.2f}~{zs[2]:.2f}")

# ── 5. 当前笔 + 背驰判断 ──
cur_price = rows[-1][5]
cur_date = rows[-1][0]
last_bi = bi[-1] if bi else None
print(f"\n当前价格: {cur_price:.2f} ({cur_date})")
print(f"最后一笔: {merged[last_bi[0]][0]} {last_bi[1]} @ {last_bi[2]:.2f}" if last_bi else "无")

# 背驰: 比较最近两段同向走势的幅度
def seg_force(b1, b2):
    """一段笔的力度 = 价格变化% """
    return abs(b2[2] / b1[2] - 1) * 100

if len(bi) >= 4:
    d1 = seg_force(bi[-4], bi[-3])
    d2 = seg_force(bi[-2], bi[-1])
    print(f"\n最近两段下跌笔: {d1:.1f}% → {d2:.1f}% (第二段更小=底背驰)")
    if bi[-1][1] == 'bottom':
        print(f"背驰判断: {'⚠️ 底背驰迹象(第二段力度<第一段)' if d2 < d1 else '无背驰(力度增强, 趋势延续)'}")

# ── 6. 阶段判定 ──
print("\n" + "="*50)
# 找最近的中枢和当前笔的关系
if zs_list:
    last_zs = zs_list[-1]
    zlo, zhi = last_zs[1], last_zs[2]
    print(f"最近中枢: {zlo:.2f} ~ {zhi:.2f}")
    if cur_price > zhi:
        stage = "突破中枢上方"
    elif cur_price < zlo:
        stage = "中枢下方"
    else:
        stage = "中枢内震荡"
    print(f"当前价格{cur_price:.2f} → {stage}")
print("="*50)
