#!/usr/bin/env python3
"""二买/三买 新旧打分公式对比回测(真当时信号, 回放窗口内无偏差)
旧公式=当前calc_score; 新公式=因子分析修正版(二买: pos60/dist_lo方向修正; 三买: 去掉t2)
对比: 各分层(≥60/≥70/≥80)胜率与样本 — 验证修正是否有效
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

def score_new_2b(closes, highs, lows, vols, i):
    ma20 = sum(closes[i-20:i+1]) / 21
    L60 = min(lows[i-60:i+1]); H60 = max(highs[i-60:i+1]); H40 = max(highs[i-40:i+1])
    c0 = closes[i]
    b5 = (c0/ma20 - 1) * 100 if ma20 > 0 else 0
    t1 = (c0 - H40)/H40 * 100 if H40 > 0 else 0
    pos60 = (c0 - L60)/(H60-L60) * 100 if H60 > L60 else 50
    dist_lo = (c0/L60 - 1) * 100 if L60 > 0 else 0
    s = 50.0 + _lin(-t1, 0, 35, -10, 12)          # 深回调(有效保留)
    s += _lin(100 - pos60, 0, 60, 0, 10)           # 修正: 位置越低越好(原适中+8)
    s += _lin(b5, -4, 7, -8, 8)                    # 站上均线(有效保留)
    if b5 > 10: s -= (b5 - 10) * 0.6
    s += _lin(dist_lo, 0, 40, 8, -6)               # 修正: 越贴近低点加分越多(原中等距离最高)
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

def score_new_3b(closes, highs, lows, i):
    H40 = max(highs[i-40:i+1])
    L60 = min(lows[i-60:i+1]); c0 = closes[i]
    t5 = (H40 - L60)/L60 * 100 if L60 > 0 else 0
    t1 = (c0 - H40)/H40 * 100 if H40 > 0 else 0
    s = 50.0 + _lin(t5, 24.49, 68.88, 0, 15)      # 箱体高度(有效保留)
    if t5 > 70: s -= (t5 - 70) * 0.2               # 极端高惩罚(妖股)
    s += _lin(-t1, 9.97, 77.37, -8, 8)             # 回踩深(有效保留)
    return max(0.0, min(100.0, s))                 # 去掉t2(突破力度无效)

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
    data = defaultdict(lambda: {'old': {5: [], 20: []}, 'new': {5: [], 20: []}, 'old_h': {5: [], 20: []}, 'new_h': {5: [], 20: []}})
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
            sn = score_new_2b(closes, highs, lows, vols, i)
        else:
            so = score_old_3b(closes, highs, lows, i)
            sn = score_new_3b(closes, highs, lows, i)
        d = data[typ]
        for tag, sc in (('old', so), ('new', sn)):
            d[tag][5].append((sc, ret5)); d[tag][20].append((sc, ret20))
        for tag, sc in (('old_h', so), ('new_h', sn)):
            if sc >= 70:
                d[tag][5].append((sc, ret5)); d[tag][20].append((sc, ret20))
    picks.close(); seq.close()
    for typ in ('二买', '三买'):
        d = data[typ]
        print(f"═══ {typ}: 旧公式 vs 新公式 (20日) ═══")
        for tag, name in (('old', '旧公式'), ('new', '新公式')):
            pairs = d[tag][20]
            n = len(pairs)
            win = sum(1 for _, r in pairs if r > 0) / n * 100
            avg = sum(r for _, r in pairs) / n * 100
            g70 = [(s, r) for s, r in pairs if s >= 70]
            g80 = [(s, r) for s, r in pairs if s >= 80]
            def stat(g):
                if not g: return (0, 0, 0)
                w = sum(1 for _, r in g if r > 0) / len(g) * 100
                a = sum(r for _, r in g) / len(g) * 100
                return (len(g), w, a)
            n70, w70, a70 = stat(g70); n80, w80, a80 = stat(g80)
            print(f"  {name}: 全量{n} 胜率{win:.1f}% 收益{avg:+.2f}% | ≥70分: {n70}个 胜率{w70:.1f}% 收益{a70:+.2f}% | ≥80分: {n80}个 胜率{w80:.1f}% 收益{a80:+.2f}%")
        print()

if __name__ == "__main__":
    main()
