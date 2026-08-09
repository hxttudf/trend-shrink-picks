#!/usr/bin/env python3
"""二买/三买 打分机制v3(案例证据驱动) vs 旧公式 对比回测
v3: 位置低+回调到位+回踩深+站均 → 加分; 箱体过大/突破过猛(妖股) → 惩罚
口径: 真当时信号(confirmed_later=0), T+2买入→T+2+5/20卖出, 复权
"""
import sqlite3
from collections import defaultdict

PICKS_DB = "/home/ubuntu/databases/trend_picks.db"
SEQ_DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"

def _lin(v, p20, p80, lo, hi):
    if p80 <= p20:
        return 0.0
    x = (v - p20) / (p80 - p20)
    return max(lo, min(hi, lo + x * (hi - lo)))

def score_old_2b(closes, highs, lows, vols, i):
    ma20 = sum(closes[i-20:i+1]) / 21
    L60 = min(lows[i-60:i+1]); H60 = max(highs[i-60:i+1]); H40 = max(highs[i-40:i+1])
    c0 = closes[i]
    b5 = (c0/ma20 - 1) * 100 if ma20 > 0 else 0
    t1 = (c0 - H40)/H40 * 100 if H40 > 0 else 0
    pos60 = (c0 - L60)/(H60-L60) * 100 if H60 > L60 else 50
    dist_lo = (c0/L60 - 1) * 100 if L60 > 0 else 0
    limit20 = int(sum(1 for k in range(i-20, i+1) if k > 0 and closes[k] and closes[k-1] and highs[k] > closes[k-1]*1.09))
    s = 50.0 + _lin(-t1, 0, 35, -10, 12)
    if pos60 < 30: s += (pos60 - 30) * 0.3
    elif pos60 <= 65: s += 8.0
    else: s += 8.0 - (pos60 - 65) * 0.45
    s += _lin(b5, -4, 7, -8, 8)
    if b5 > 10: s -= (b5 - 10) * 0.6
    if dist_lo < 10: s += dist_lo * 0.2
    elif dist_lo <= 35: s += 5.0
    else: s += 5.0 - (dist_lo - 35) * 0.3
    s -= limit20 * 2.0
    return max(0.0, min(100.0, s + 15.0))

def score_old_3b(closes, highs, lows, i):
    H40 = max(highs[i-40:i+1])
    H40p = max(highs[i-80:i-40]) if i >= 80 else H40
    L60 = min(lows[i-60:i+1]); c0 = closes[i]
    t2 = (H40/H40p - 1) * 100 if H40p > 0 else 0
    t5 = (H40 - L60)/L60 * 100 if L60 > 0 else 0
    t1 = (c0 - H40)/H40 * 100 if H40 > 0 else 0
    s = 50.0 + _lin(t2, -0.98, 29.25, 0, 15) + _lin(t5, 24.49, 68.88, 0, 15) + _lin(-t1, 9.97, 77.37, -8, 8)
    return max(0.0, min(100.0, s))

def score_v3_2b(closes, highs, lows, i):
    """v3(案例证据): 位置低+回调到位+回踩深+站均加分; 箱体大/突破猛惩罚"""
    ma20 = sum(closes[i-20:i+1]) / 21
    L60 = min(lows[i-60:i+1]); H60 = max(highs[i-60:i+1]); H40 = max(highs[i-40:i+1])
    H40p = max(highs[i-80:i-40]) if i >= 80 else H40
    c0 = closes[i]
    b5 = (c0/ma20 - 1) * 100 if ma20 > 0 else 0
    t1 = (c0 - H40)/H40 * 100 if H40 > 0 else 0
    pos60 = (c0 - L60)/(H60-L60) * 100 if H60 > L60 else 50
    dist_lo = (c0/L60 - 1) * 100 if L60 > 0 else 0
    t2 = (H40/H40p - 1) * 100 if H40p > 0 else 0
    t5 = (H40 - L60)/L60 * 100 if L60 > 0 else 0
    s = 50.0
    s += _lin(max(0.0, 100 - max(pos60, 0)), 0, 60, 0, 20)   # 位置越低分越高(核心)
    s += _lin(max(0.0, -dist_lo), 0, 30, 0, 10)              # 贴近60日低点加分
    s += _lin(-t1, 0, 40, -5, 8)                              # 回踩深(距40日高远)加分
    s += _lin(b5, -3, 5, -3, 4)                               # 站上MA20小加分
    if t5 > 100: s -= (t5 - 100) * 0.15                       # 箱体过大(妖股)惩罚
    if t2 > 50: s -= (t2 - 50) * 0.15                         # 突破过猛(暴涨后接盘)惩罚
    return max(0.0, min(100.0, s))

def score_v3_3b(closes, highs, lows, i):
    """v3(案例证据): 位置低+回调到位+回踩深加分; 箱体大惩罚; 突破力度中性"""
    L60 = min(lows[i-60:i+1]); H60 = max(highs[i-60:i+1]); H40 = max(highs[i-40:i+1])
    c0 = closes[i]
    t1 = (c0 - H40)/H40 * 100 if H40 > 0 else 0
    pos60 = (c0 - L60)/(H60-L60) * 100 if H60 > L60 else 50
    dist_lo = (c0/L60 - 1) * 100 if L60 > 0 else 0
    t5 = (H40 - L60)/L60 * 100 if L60 > 0 else 0
    s = 50.0
    s += _lin(max(0.0, 100 - max(pos60, 0)), 0, 60, 0, 20)   # 位置越低分越高(核心)
    s += _lin(max(0.0, -dist_lo), 0, 30, 0, 10)              # 贴近60日低点加分
    s += _lin(-t1, 0, 40, -5, 8)                              # 回踩深加分
    if t5 > 100: s -= (t5 - 100) * 0.15                       # 箱体过大惩罚
    return max(0.0, min(100.0, s))

def main():
    picks = sqlite3.connect(PICKS_DB)
    seq = sqlite3.connect(SEQ_DB)
    rows = picks.execute(
        "SELECT symbol, signal_type, signal_date FROM chanlun_signals "
        "WHERE signal_type IN ('二买','三买') AND confirmed_later=0").fetchall()
    px_cache = {}
    for sym in set(r[0] for r in rows):
        px = seq.execute(
            "SELECT date, open, high, low, close, close_qfq, volume FROM stock_daily WHERE symbol=? AND close_qfq>0 ORDER BY date",
            (sym,)).fetchall()
        if len(px) > 80:
            px_cache[sym] = px
    data = defaultdict(lambda: {'old': [], 'v3': []})
    for sym, typ, sd in rows:
        if sym not in px_cache:
            continue
        px = px_cache[sym]
        dates = [r[0] for r in px]; closes = [r[5] for r in px]
        highs = [r[2] for r in px]; lows = [r[3] for r in px]; vols = [r[6] for r in px]
        try:
            i = dates.index(sd)
        except ValueError:
            continue
        if i < 80 or i + 22 >= len(closes) or closes[i+2] <= 0:
            continue
        ret5 = closes[i+7] / closes[i+2] - 1
        ret20 = closes[i+22] / closes[i+2] - 1
        if typ == '二买':
            so = score_old_2b(closes, highs, lows, vols, i)
            sn = score_v3_2b(closes, highs, lows, i)
        else:
            so = score_old_3b(closes, highs, lows, i)
            sn = score_v3_3b(closes, highs, lows, i)
        data[typ]['old'].append((so, ret5, ret20))
        data[typ]['v3'].append((sn, ret5, ret20))
    picks.close(); seq.close()
    for typ in ('二买', '三买'):
        print(f"══════ {typ}: 旧公式 vs v3 (真当时 {len(data[typ]['old'])}样本) ══════")
        for tag, name in (('old', '旧公式'), ('v3', 'v3(案例证据)')):
            pairs = data[typ][tag]
            n = len(pairs)
            win5 = sum(1 for _, r5, _ in pairs if r5 > 0) / n * 100
            win20 = sum(1 for _, _, r20 in pairs if r20 > 0) / n * 100
            avg20 = sum(r20 for _, _, r20 in pairs) / n * 100
            def stat(g):
                if not g:
                    return (0, 0, 0)
                w = sum(1 for _, _, r in g if r > 0) / len(g) * 100
                a = sum(r for _, _, r in g) / len(g) * 100
                return (len(g), w, a)
            print(f"  {name}: 全量{n} 胜率5{win5:.1f}% 胜率20{win20:.1f}% 收益20{avg20:+.2f}%")
            for th in (60, 70, 80):
                g = [(s, r5, r20) for s, r5, r20 in pairs if s >= th]
                nn, ww, aa = stat(g)
                print(f"      ≥{th}分: {nn}个 胜率20{ww:.1f}% 收益20{aa:+.2f}%")
        print()

if __name__ == "__main__":
    main()
