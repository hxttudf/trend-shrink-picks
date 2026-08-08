#!/usr/bin/env python3
"""二买组合变体样本外对比 — 找验证集不衰减的组合"""
import pickle, numpy as np

d = pickle.load(open('/tmp/score_bt_rows.pkl', 'rb'))
rows2 = d['二买']
for r in rows2:
    r['feats'] = dict(r['feats'])
    r['feats']['b6o'] = -abs(r['feats']['b6'] - 6)

def pct_rank(vals):
    s = np.argsort(np.argsort(vals))
    return s / max(len(vals) - 1, 1)

def combo_score(rows, feats_w):
    names = [f for f, w in feats_w]
    m = np.array([[r['feats'].get(f, 0) for f in names] for r in rows], dtype=float)
    m = np.nan_to_num(m, nan=0.0)
    pr = np.column_stack([pct_rank(m[:, k]) for k in range(m.shape[1])])
    w = np.array([w for f, w in feats_w])
    return pr @ w

def oos(rows, feats_w, label, rkey='r10'):
    dates = np.array([r['date'] for r in rows])
    order = np.argsort(dates)
    rows_s = [rows[i] for i in order]
    n = len(rows_s)
    cut = int(n * 0.7)
    train, test = rows_s[:cut], rows_s[cut:]
    sc_tr = combo_score(train, feats_w)
    sc_te = combo_score(test, feats_w)
    qs = np.quantile(sc_tr, [0.2, 0.4, 0.6, 0.8])
    line = [label]
    for name, sc, rows_x in [("tr", sc_tr, train), ("te", sc_te, test)]:
        rets = np.array([r['rets'][rkey] for r in rows_x])
        gs = []
        for g in range(5):
            lo = -np.inf if g == 0 else qs[g-1]
            hi = np.inf if g == 4 else qs[g]
            mask = (sc >= lo) & (sc < hi)
            gs.append(round(rets[mask].mean(), 2) if mask.sum() else float('nan'))
        line.append(f"{name}:[{'/'.join(map(str,gs))}] 极差{round(gs[4]-gs[0],2)}")
    print('  '.join(line))

print("=== 二买变体样本外(10日收益) ===")
oos(rows2, [('b5', 1.0)], 'b5单独')
oos(rows2, [('b6o', 1.0)], 'b6单独')
oos(rows2, [('b5', 1.0), ('b6o', 0.8)], 'b5+b6o')
oos(rows2, [('b5', 1.0), ('b2', 0.8)], 'b5+b2')
oos(rows2, [('b5', 1.0), ('b2', 0.8), ('b6o', 0.6)], 'b5+b2+b6o(原)')
oos(rows2, [('b5', 1.0), ('b6o', 0.8), ('b1', -0.5)], 'b5+b6o-b1(深回调反向)')
# 二买反向逻辑: 深回调(低价) + 企稳 —— 试 b1 正向(回调深=买低, 同三买逻辑)
oos(rows2, [('b5', 1.0), ('b1', 0.8), ('b6o', 0.6)], 'b5+b1+b6o(深回调正)')
# 量能细看: b3信号日量能
oos(rows2, [('b5', 1.0), ('b3', 0.8)], 'b5+b3')
