#!/usr/bin/env python3
"""胜率导向: 单因子胜率单调性测试 + 组合设计(避开过热) + 样本外胜率验证"""
import pickle, numpy as np

d = pickle.load(open('/tmp/score_bt5.pkl', 'rb'))

def win_rate_group(rows, fkey, label, rkey='r10', ngrp=5):
    """按因子5分组看胜率(收益>0占比)"""
    vals = np.array([r['f'][fkey] for r in rows])
    rets = np.array([r[rkey] for r in rows])
    order = np.argsort(vals)
    n = len(order)
    q = n // ngrp
    line = [f"{label:<12}"]
    wins = []
    for g in range(ngrp):
        seg = order[g*q:(g+1)*q if g < ngrp-1 else n]
        w = (rets[seg] > 0).mean() * 100
        m = rets[seg].mean()
        wins.append(w)
        line.append(f"{w:.0f}%/{m:.1f}")
    print('  '.join(line))
    return wins

for typ, rows in d.items():
    print(f"\n========== {typ} 单因子胜率(10日, 5分组低→高) ==========")
    feats = ['b5', 'b1', 't2', 't5', 't1', 'atr', 'rsi', 'slope', 'pos60',
             'vtrend', 'gap', 'dist_hi', 'dist_lo', 'limit20', 'm_align']
    for f in feats:
        win_rate_group(rows, f, f)

# 胜率导向组合: 避开过热(倒U/分段惩罚)
def score_win(r, typ):
    f = r['f']
    def lin(v, p20, p80, lo, hi):
        if p80 <= p20:
            return 0.0
        x = (v - p20) / (p80 - p20)
        return max(lo, min(hi, lo + x * (hi - lo)))
    if typ == '二买':
        s = 50.0
        # 基础: 站上均线适度(0~9%最优, 过高惩罚)
        s += lin(f['b5'], -5, 8, -12, 10)          # 正, 但>8%后封顶
        if f['b5'] > 12:
            s -= (f['b5'] - 12) * 0.8              # 追高惩罚
        # 位置: pos60 30-65最优(启动期), 过高惩罚
        s += lin(f['pos60'], 20, 60, -10, 12)
        if f['pos60'] > 70:
            s -= (f['pos60'] - 70) * 0.5
        # 量能: 温和放量最优, 过热惩罚
        if f['vtrend'] < 0:
            s += f['vtrend'] * 0.3                  # 缩量小扣
        elif f['vtrend'] < 25:
            s += f['vtrend'] * 0.4                  # 温和放量加分
        else:
            s += 10 - (f['vtrend'] - 25) * 0.4      # 过热惩罚
        # 距低点: 15-40%最优
        s += lin(f['dist_lo'], 5, 40, -10, 8)
        if f['dist_lo'] > 50:
            s -= (f['dist_lo'] - 50) * 0.3
        # 涨停少
        if f['limit20'] >= 3:
            s -= (f['limit20'] - 2) * 4
        return max(0.0, min(100.0, s))
    else:
        s = 50.0
        s += lin(f['t2'], 0, 30, 0, 8)              # 突破力度适度
        if f['t2'] > 40:
            s -= (f['t2'] - 40) * 0.4
        s += lin(f['t5'], 20, 55, -8, 8)            # 箱体适中
        if f['t5'] > 70:
            s -= (f['t5'] - 70) * 0.3
        s += lin(f['pos60'], 40, 72, -8, 8)
        if f['pos60'] > 80:
            s -= (f['pos60'] - 80) * 0.5
        if f['vtrend'] < 0:
            s += f['vtrend'] * 0.2
        elif f['vtrend'] < 30:
            s += f['vtrend'] * 0.3
        else:
            s += 9 - (f['vtrend'] - 30) * 0.35
        s += lin(f['dist_lo'], 15, 55, -8, 8)
        if f['dist_lo'] > 65:
            s -= (f['dist_lo'] - 65) * 0.3
        if f['limit20'] >= 3:
            s -= (f['limit20'] - 2) * 4
        return max(0.0, min(100.0, s))

print("\n========== 胜率导向组合: 分数档位 胜率/收益 ==========")
for typ, rows in d.items():
    print(f"\n-- {typ} --")
    sc = np.array([score_win(r, typ) for r in rows])
    rets10 = np.array([r['r10'] for r in rows])
    rets20 = np.array([r['r20'] for r in rows])
    print(f"  基准: 胜率10={(rets10>0).mean()*100:.1f}% 收益10={rets10.mean():.2f}% 胜率20={(rets20>0).mean()*100:.1f}% 收益20={rets20.mean():.2f}%")
    for lo in range(40, 90, 5):
        idx = np.where((sc >= lo) & (sc < lo + 5))[0]
        if len(idx) < 150:
            continue
        w10 = (rets10[idx] > 0).mean() * 100
        w20 = (rets20[idx] > 0).mean() * 100
        print(f"  {lo}-{lo+4}分: n={len(idx)} 胜率10={w10:.1f}% 收益10={rets10[idx].mean():.2f}% | 胜率20={w20:.1f}% 收益20={rets20[idx].mean():.2f}%")

# 样本外验证(2025+)
print("\n========== 样本外(2025+) top20% vs 基准 ==========")
for typ, rows in d.items():
    dates = np.array([r.get('date', '') for r in rows]) if 'date' in rows[0] else None
    sc = np.array([score_win(r, typ) for r in rows])
    rets10 = np.array([r['r10'] for r in rows])
    rets20 = np.array([r['r20'] for r in rows])
    # 全样本top20%
    k = len(rows) // 5
    top = np.argsort(-sc)[:k]
    print(f"  {typ} 全样本top20%: 胜率10={(rets10[top]>0).mean()*100:.1f}% 收益10={rets10[top].mean():.2f}% 胜率20={(rets20[top]>0).mean()*100:.1f}% 收益20={rets20[top].mean():.2f}%")
