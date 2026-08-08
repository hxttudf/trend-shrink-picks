#!/usr/bin/env python3
"""打分拆分 — 胜率/收益率报告（用户口径: 高分率不重要, 要胜率和收益率）"""
import pickle, numpy as np

d = pickle.load(open('/tmp/score_bt_rows.pkl', 'rb'))

def _lin(v, p20, p80, lo, hi):
    if p80 <= p20:
        return 0.0
    x = (v - p20) / (p80 - p20)
    return max(lo, min(hi, lo + x * (hi - lo)))

def new_score2(r):
    f = r['feats']
    return 50.0 + _lin(f['b5'], -1.62, 5.66, -15, 15) + _lin(f['b1'], -65.53, 9.73, -12, 12)

def new_score3(r):
    f = r['feats']
    return 50.0 + _lin(f['t2'], -0.98, 29.25, 0, 15) + _lin(f['t5'], 24.49, 68.88, 0, 15) + _lin(-f['t1'], 9.97, 77.37, -8, 8)

def line(label, rows, rkey):
    rets = np.array([r['rets'][rkey] for r in rows])
    win = (rets > 0).mean() * 100
    wins, loss = rets[rets > 0], rets[rets <= 0]
    pl = abs(wins.mean() / loss.mean()) if len(loss) else 99.0
    return f"{label}: n={len(rows)} 胜率={win:.1f}% 均收益={rets.mean():.2f}% 中位={np.median(rets):.2f}% 盈亏比={pl:.2f}"

for typ, rows, sc_fn in [('二买', d['二买'], new_score2), ('三买', d['三买'], new_score3)]:
    scores = np.array([sc_fn(r) for r in rows])
    print(f"========== {typ} ==========")
    for rk, rn in [('r10', '10日'), ('r20', '20日')]:
        print(f"  [{rn}持有] 基准(全部{len(rows)}): {line('', rows, rk)}")
    # 阈值分组(模拟T+2开盘≥X买入纪律)
    for th in (75, 70, 65, 60):
        idx = np.where(scores >= th)[0]
        sub = [rows[i] for i in idx]
        if len(sub) < 30:
            print(f"  ≥{th}分: n={len(sub)} (样本不足)")
            continue
        print(f"  ≥{th}分 10日: {line('', sub, 'r10')}")
        print(f"  ≥{th}分 20日: {line('', sub, 'r20')}")
    # 5分位
    print("  5分组(按新分数, 10日收益):")
    idx = np.argsort(scores)
    n = len(idx)
    q = n // 5
    for g in range(5):
        seg = idx[g * q:(g + 1) * q if g < 4 else n]
        rets = np.array([rows[i]['rets']['r10'] for i in seg])
        win = (rets > 0).mean() * 100
        tag = '高' if g == 4 else ('低' if g == 0 else '中')
        print(f"    组{g+1}{tag}: n={len(seg)} 胜率={win:.1f}% 均收益={rets.mean():.2f}% 中位={np.median(rets):.2f}%")
    # 样本外验证组(2025-2026)的胜率收益
    dates = np.array([r['date'] for r in rows])
    te_mask = dates >= '2025-01-01'
    te_idx = np.where(te_mask)[0]
    if len(te_idx) > 100:
        te_scores = scores[te_idx]
        top20 = np.argsort(-te_scores)[:len(te_idx) // 5]
        sub_te = [rows[te_idx[i]] for i in top20]
        print(f"  样本外(2025+){len(te_idx)}个 top20% 10日: {line('', sub_te, 'r10')}")
        print(f"  样本外(2025+)top20% 20日: {line('', sub_te, 'r20')}")
    print()
