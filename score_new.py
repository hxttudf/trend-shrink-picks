#!/usr/bin/env python3
"""新打分机制 (2026-08-06) — 缩量温和回踩 + 超跌动力
综合分(strength_score) = 新分×0.6 + 旧分×0.4
强度(strength): strong = 新≥65 且 旧≥65 (双达标, C组合)
                weak = 综合分<50, 其余 neutral
回测(2020-2026, T+2买T+5卖, 含被推翻): 双达标样本2068条 +3.46%/74.3%
  2026年(当前): +2.17%/67.9% 有效 (旧打分2026年已失效+0.16%)

新分(缩量温和回踩): 50 + 缩量加分((1-量比)×15,±20)
  + 回踩温和分(前5日-10~-3%:+20; -15~-10%:+8; <-15%:-8; >-3%追高:-12)
  + 振幅分(<8%:+5, >15%:-5) + 均线分(距20日线-15~-5%:+5, <-20%:-5)
旧分(超跌动力): 50 + 量能((量比-1)×15,±20)
  + 形态(一买/二买:前10日跌幅×0.8超跌加分; 三买:前10日涨幅×1.5)
特征全部取信号日及之前数据 — 无未来函数"""


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def new_score(vr, d5, amp, dev20):
    """缩量温和回踩分 (0-100)"""
    s = 50.0
    s += _clamp((1 - vr) * 15, -20, 20)          # 缩量加分, 放量减分
    if -10 <= d5 <= -3:
        s += 20                                    # 温和回踩(最佳)
    elif -15 <= d5 < -10:
        s += 8
    elif d5 < -15:
        s -= 8                                     # 深跌减分
    else:
        s -= 12                                    # 追高/未回踩减分
    if amp < 8:
        s += 5
    elif amp > 15:
        s -= 5
    if -15 <= dev20 <= -5:
        s += 5
    elif dev20 < -20:
        s -= 5
    return round(_clamp(s, 0, 100), 1)


def old_score(typ, vr, d10, w2=0.8):
    """超跌动力分 (0-100), 超跌权重w2=0.8"""
    s = 50.0
    s += _clamp((vr - 1) * 15, -20, 20)
    if typ == '三买':
        s += _clamp(d10 * 1.5, -25, 25)
    else:
        s += _clamp(-d10 * w2, -25, 25)
    return round(_clamp(s, 0, 100), 1)


def calc_score(typ, zd, zg, closes, vols, highs, lows, i):
    """综合分 = 新分×0.6 + 旧分×0.4 (strength_score)"""
    if i < 20 or i >= len(closes):
        return 50.0
    c0 = closes[i]
    avg = sum(vols[i - 20:i]) / 20 if i >= 20 else 1
    vr = vols[i] / avg if avg else 0
    d5 = (c0 / closes[i - 5] - 1) * 100 if closes[i - 5] else 0
    d10 = (c0 / closes[i - 10] - 1) * 100 if closes[i - 10] else 0
    amp = (highs[i] - lows[i]) / lows[i] * 100 if lows[i] else 0
    ma20 = sum(closes[i - 20:i]) / 20
    dev20 = (c0 / ma20 - 1) * 100 if ma20 else 0
    ns = new_score(vr, d5, amp, dev20)
    os_ = old_score(typ, vr, d10)
    return round(ns * 0.6 + os_ * 0.4, 1)


def calc_strength(typ, zd, zg, closes, vols, highs, lows, i):
    """强度: strong=新≥65且旧≥65(双达标); weak=综合分<50; 其余neutral"""
    if i < 20 or i >= len(closes):
        return 'neutral'
    c0 = closes[i]
    avg = sum(vols[i - 20:i]) / 20 if i >= 20 else 1
    vr = vols[i] / avg if avg else 0
    d5 = (c0 / closes[i - 5] - 1) * 100 if closes[i - 5] else 0
    d10 = (c0 / closes[i - 10] - 1) * 100 if closes[i - 10] else 0
    amp = (highs[i] - lows[i]) / lows[i] * 100 if lows[i] else 0
    ma20 = sum(closes[i - 20:i]) / 20
    dev20 = (c0 / ma20 - 1) * 100 if ma20 else 0
    ns = new_score(vr, d5, amp, dev20)
    os_ = old_score(typ, vr, d10)
    if ns >= 65 and os_ >= 65:
        return 'strong'
    comb = ns * 0.6 + os_ * 0.4
    if comb < 50:
        return 'weak'
    return 'neutral'
