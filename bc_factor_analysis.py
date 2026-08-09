#!/usr/bin/env python3
"""二买/三买打分因子分析: 每个因子与20日收益的相关性(分箱对比)
用回放窗口内"真当时"信号(confirmed_later=0, 无快照偏差)
结论驱动: 因子分箱收益单调正相关=有效; 反向=公式设计错
"""
import sqlite3
from collections import defaultdict

PICKS_DB = "/home/ubuntu/databases/trend_picks.db"
SEQ_DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"

def factors_2b(closes, highs, lows, vols, i):
    ma20 = sum(closes[i-20:i+1]) / 21
    L60 = min(lows[i-60:i+1]); H60 = max(highs[i-60:i+1]); H40 = max(highs[i-40:i+1])
    c0 = closes[i]
    b5 = (c0/ma20 - 1) * 100 if ma20 > 0 else 0
    t1 = (c0 - H40)/H40 * 100 if H40 > 0 else 0
    pos60 = (c0 - L60)/(H60-L60) * 100 if H60 > L60 else 50
    dist_lo = (c0/L60 - 1) * 100 if L60 > 0 else 0
    limit20 = int(sum(1 for k in range(i-20, i+1) if k > 0 and closes[k] and closes[k-1] and highs[k] > closes[k-1]*1.09))
    return {'b5_站上MA20': b5, 't1_距40日高(负=好)': -t1, 'pos60_60日位置': pos60,
            'dist_lo_距60日低': dist_lo, 'limit20_涨停数': limit20}

def factors_3b(closes, highs, lows, i):
    H40 = max(highs[i-40:i+1])
    H40p = max(highs[i-80:i-40]) if i >= 80 else H40
    L60 = min(lows[i-60:i+1])
    c0 = closes[i]
    t2 = (H40/H40p - 1) * 100 if H40p > 0 else 0
    t5 = (H40 - L60)/L60 * 100 if L60 > 0 else 0
    t1 = (c0 - H40)/H40 * 100 if H40 > 0 else 0
    return {'t2_突破力度': t2, 't5_箱体高度': t5, 't1_距40日高(负=回踩深)': -t1}

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
    # 每个因子: 值列表 -> 对应20日收益
    fac = {'二买': defaultdict(list), '三买': defaultdict(list)}
    n = 0
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
        ret20 = closes[i+22] / closes[i+2] - 1
        f = factors_2b(closes, highs, lows, vols, i) if typ == '二买' else factors_3b(closes, highs, lows, i)
        for k, v in f.items():
            fac[typ][k].append((v, ret20))
        n += 1
    picks.close(); seq.close()
    print(f"样本: {n} (二买/三买真当时, 回放窗口内)\n")
    for typ in ('二买', '三买'):
        print(f"═══ {typ} 因子分箱分析 (值低→高, 每箱20日平均收益) ═══")
        for k, pairs in fac[typ].items():
            pairs.sort()
            m = len(pairs) // 5
            if m < 50:
                print(f"  {k}: 样本不足({len(pairs)})")
                continue
            box = []
            for b in range(5):
                seg = pairs[b*m:(b+1)*m if b < 4 else len(pairs)]
                avg = sum(r for _, r in seg) / len(seg) * 100
                lo = seg[0][0]; hi = seg[-1][0]
                box.append(f"[{lo:.1f}~{hi:.1f}]:{avg:+.2f}%")
            # 低箱 vs 高箱
            lo_avg = sum(r for _, r in pairs[:m]) / m * 100
            hi_avg = sum(r for _, r in pairs[-m:]) / m * 100
            print(f"  {k}: {' | '.join(box)}")
            print(f"      低箱{lo_avg:+.2f}% vs 高箱{hi_avg:+.2f}% → {'✓有效' if hi_avg > lo_avg + 0.5 else ('✗反向' if hi_avg < lo_avg - 0.5 else '≈无效')}")
        print()

if __name__ == "__main__":
    main()
