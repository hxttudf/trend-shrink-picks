#!/usr/bin/env python3
"""卖点打分v2: 一卖=位置适度(避免最后一冲); 三卖=弱势破位(还在跌加分); 二卖=反弹弱
目标: 卖对率↑ 且 卖飞率不翻倍"""
import pickle, numpy as np

d = pickle.load(open('/tmp/score_bt_sell.pkl', 'rb'))

def lin(v, p20, p80, lo, hi):
    if p80 <= p20:
        return 0.0
    x = (v - p20) / (p80 - p20)
    return max(lo, min(hi, lo + x * (hi - lo)))

def clip(s):
    return max(0.0, min(100.0, s))

def sell_score2(r, typ):
    f = r['f']
    if typ == '一卖':
        s = 50.0
        s += lin(f['dist_lo'], 10, 50, -8, 10)
        if f['dist_lo'] > 60:
            s -= (f['dist_lo'] - 60) * 0.3
        s += lin(f['t5'], 20, 60, -5, 6)
        s += lin(f['pos60'], 35, 75, -4, 5)
        s += lin(f['atr'], 1.5, 6, -3, 5)
        s -= f['limit20'] * 1.2
        if f['chg10'] > 15:
            s -= (f['chg10'] - 15) * 0.4
        return clip(s)
    if typ == '二卖':
        s = 50.0
        s += lin(-f['chg10'], -8, 8, -6, 8)
        s += lin(f['dist_lo'], 8, 40, -6, 8)
        if f['dist_lo'] > 50:
            s -= (f['dist_lo'] - 50) * 0.25
        s += lin(f['vtrend'], -25, 25, -5, 6)
        s += lin(f['t5'], 20, 60, -4, 5)
        s -= f['limit20'] * 1.0
        return clip(s)
    else:
        s = 50.0
        s += lin(-f['chg10'], -10, 5, -8, 12)
        s += lin(-f['dist_lo'], 0, 15, -6, 8)
        s += lin(-f['pos60'], 10, 35, -5, 7)
        s += lin(f['vtrend'], -30, 20, -5, 8)
        s += lin(-f['rsi'], 25, 50, -4, 5)
        s -= f['limit20'] * 1.5
        return clip(s)

print("========== 卖点组合v2 ==========")
for typ, rows in d.items():
    print(f"\n-- {typ} --")
    sc = np.array([sell_score2(r, typ) for r in rows])
    r10 = np.array([r['r10'] for r in rows])
    r20 = np.array([r['r20'] for r in rows])
    print(f"  基准: 卖对率10={(r10<0).mean()*100:.1f}% 均收益={r10.mean():.2f}% 卖飞率={(r10>12).mean()*100:.1f}% | 20日卖对率={(r20<0).mean()*100:.1f}%")
    qs = np.quantile(sc, [0.2, 0.4, 0.6, 0.8])
    for name, scx, rx in [("全样本", sc, rows)]:
        pass
    # 5分组
    for g in range(5):
        lo = -np.inf if g == 0 else qs[g-1]
        hi = np.inf if g == 4 else qs[g]
        m = (sc >= lo) & (sc < hi)
        print(f"    组{g+1}: n={m.sum()} 卖对率={(r10[m]<0).mean()*100:.1f}% 均收益={r10[m].mean():.2f}% 卖飞率={(r10[m]>12).mean()*100:.1f}%")
    k = len(rows) // 5
    top = np.argsort(-sc)[:k]
    bot = np.argsort(sc)[:k]
    print(f"  top20%: 卖对率10={(r10[top]<0).mean()*100:.1f}% 均收益={r10[top].mean():.2f}% 卖飞率={(r10[top]>12).mean()*100:.1f}% | 20日卖对率={(r20[top]<0).mean()*100:.1f}%")
    print(f"  bot20%: 卖对率10={(r10[bot]<0).mean()*100:.1f}% 均收益={r10[bot].mean():.2f}% 卖飞率={(r10[bot]>12).mean()*100:.1f}%")

# 样本外(时间切片)
print("\n========== 样本外(训练75%→验证25%) top20% ==========")
for typ, rows in d.items():
    dates = np.array([r['date'] for r in rows])
    order = np.argsort(dates)
    rows_s = [rows[i] for i in order]
    n = len(rows_s)
    cut = int(n * 0.75)
    tr, te = rows_s[:cut], rows_s[cut:]
    sc_tr = np.array([sell_score2(r, typ) for r in tr])
    sc_te = np.array([sell_score2(r, typ) for r in te])
    qs = np.quantile(sc_tr, [0.2, 0.4, 0.6, 0.8])
    print(f"\n{typ} 训练{len(tr)}→验证{len(te)}:")
    for name, sc, rx in [("训练", sc_tr, tr), ("验证", sc_te, te)]:
        r10 = np.array([r['r10'] for r in rx])
        r20 = np.array([r['r20'] for r in rx])
        k = len(sc) // 5
        top = np.argsort(-sc)[:k]
        print(f"  {name}: top20%卖对率={(r10[top]<0).mean()*100:.1f}%(基准{(r10<0).mean()*100:.1f}%) 均收益={r10[top].mean():.2f}% 卖飞率={(r10[top]>12).mean()*100:.1f}% | 20日top卖对率={(r20[top]<0).mean()*100:.1f}%")
