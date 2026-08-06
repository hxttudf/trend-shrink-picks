#!/usr/bin/env python3
"""旧打分机制备份 (2026-08-06 被新公式 score_new.py 替换)
如需恢复: 把本模块两个函数复制回 bc_flag_d3w30.py 并改回 import 即可。

旧公式: 50基准 + 量能±20((量比-1)×15, 放量加分) + 形态±25
  一买/二买: 形态 = 前10日跌幅×0.8 (超跌加分)
  三买/三卖: 形态 = 远离中枢幅度×1.5 (zd/zg为真值时)
  一卖/二卖: 形态 = 前10日涨幅×0.8
历史表现(2020-2026, ≥75分, T+2买T+5卖): 2024年+6.50%/82.5%大幅有效;
  2021/2023/2025中性; 2026年+0.16%/52.1%失效 → 被新公式替换"""


def calc_strength(typ, zd, zg, closes, vols, i):
    """旧强度: strong/neutral/weak"""
    if i < 20 or i >= len(closes):
        return 'neutral'
    c0 = closes[i]
    avg = sum(vols[i - 20:i]) / 20 if i >= 20 else 1
    vr = vols[i] / avg if avg else 0
    if typ == '三买' and zg and zg > 0:
        brk = (c0 - zg) / zg * 100
        if brk > 5 and vr > 1.5:
            return 'strong'
        if brk < 3:
            return 'weak'
        return 'neutral'
    if typ in ('一买', '二买'):
        c10 = closes[i - 10]
        drop10 = (c0 - c10) / c10 * 100 if c10 else 0
        if drop10 < -20:
            return 'strong'
        if vr < 0.6 and drop10 > -20:
            return 'weak'
        return 'neutral'
    return 'neutral'


def calc_score(typ, zd, zg, closes, vols, i):
    """旧分数: 0-100"""
    if i < 20 or i >= len(closes):
        return 50.0
    c0 = closes[i]
    avg = sum(vols[i - 20:i]) / 20 if i >= 20 else 1
    vr = vols[i] / avg if avg else 0
    s = 50.0
    s += max(-20.0, min(20.0, (vr - 1) * 15))
    if typ == '三买':
        c10 = closes[i - 10]
        rise10 = (c0 - c10) / c10 * 100 if c10 else 0
        brk = (c0 - zg) / zg * 100 if (zg and zg > 0) else rise10
        s += max(-25.0, min(25.0, brk * 1.5))
    else:
        c10 = closes[i - 10]
        chg = (c0 - c10) / c10 * 100 if c10 else 0
        s += max(-25.0, min(25.0, -chg * 0.8))
    return round(max(0.0, min(100.0, s)), 1)
