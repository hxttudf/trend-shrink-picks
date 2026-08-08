#!/usr/bin/env python3
"""胜率组合v2 — 严格样本外验证: 2024训练定分位边界, 2025-2026验证(含胜率+收益)"""
import pickle, numpy as np

d = pickle.load(open('/tmp/score_bt5.pkl', 'rb'))

def lin(v, p20, p80, lo, hi):
    if p80 <= p20:
        return 0.0
    x = (v - p20) / (p80 - p20)
    return max(lo, min(hi, lo + x * (hi - lo)))

def score_win2(r, typ):
    f = r['f']
    if typ == '二买':
        s = 50.0
        s += lin(-f['t1'], 0, 35, -10, 12)
        if f['pos60'] < 30:
            s += (f['pos60'] - 30) * 0.3
        elif f['pos60'] <= 65:
            s += 8.0
        else:
            s += 8.0 - (f['pos60'] - 65) * 0.45
        s += lin(f['b5'], -4, 7, -8, 8)
        if f['b5'] > 10:
            s -= (f['b5'] - 10) * 0.6
        if f['dist_lo'] < 10:
            s += f['dist_lo'] * 0.2
        elif f['dist_lo'] <= 35:
            s += 5.0
        else:
            s += 5.0 - (f['dist_lo'] - 35) * 0.3
        s -= f['limit20'] * 2.0
        return max(0.0, min(100.0, s))
    else:
        s = 50.0
        s += lin(-f['t1'], 0, 35, -10, 12)
        s += lin(f['pos60'], 30, 75, 8, -10)
        s += lin(f['dist_lo'], 10, 60, 8, -8)
        s -= f['limit20'] * 2.5
        s += lin(f['t2'], 0, 35, 0, 6)
        if f['t2'] > 45:
            s -= (f['t2'] - 45) * 0.4
        return max(0.0, min(100.0, s))

for typ, rows in d.items():
    dates = np.array([r['date'] for r in rows])
    order = np.argsort(dates)
    rows_s = [rows[i] for i in order]
    n = len(rows_s)
    cut = int(n * 0.75)  # 2024~2025初为训练, 后25%为验证
    tr, te = rows_s[:cut], rows_s[cut:]
    sc_tr = np.array([score_win2(r, typ) for r in tr])
    sc_te = np.array([score_win2(r, typ) for r in te])
    qs = np.quantile(sc_tr, [0.2, 0.4, 0.6, 0.8])
    print(f"\n===== {typ} 样本外验证(训练{len(tr)}→验证{len(te)}, 边界{np.round(qs,1)}) =====")
    for name, sc, rx in [("训练", sc_tr, tr), ("验证", sc_te, te)]:
        r10 = np.array([r['r10'] for r in rx])
        r20 = np.array([r['r20'] for r in rx])
        line = [f"{name}: "]
        for g in range(5):
            lo = -np.inf if g == 0 else qs[g-1]
            hi = np.inf if g == 4 else qs[g]
            m = (sc >= lo) & (sc < hi)
            if m.sum() < 50:
                line.append(f"组{g+1}(n={m.sum()}) -")
            else:
                line.append(f"组{g+1}:胜{(r10[m]>0).mean()*100:.0f}%/收{r10[m].mean():.1f}")
        print('  '.join(line))
        # top20%
        k = len(sc) // 5
        top = np.argsort(-sc)[:k]
        print(f"    {name} top20%: 胜率10={(r10[top]>0).mean()*100:.1f}% 收益10={r10[top].mean():.2f}% | 胜率20={(r20[top]>0).mean()*100:.1f}% 收益20={r20[top].mean():.2f}%")
        print(f"    {name} 基准:   胜率10={(r10>0).mean()*100:.1f}% 收益10={r10.mean():.2f}% | 胜率20={(r20>0).mean()*100:.1f}% 收益20={r20.mean():.2f}%")
