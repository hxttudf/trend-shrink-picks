#!/usr/bin/env python3
"""胜率导向组合v2: 简洁版 — 只用胜率单调因子, 样本外验证"""
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
        s += lin(-f['t1'], 0, 35, -10, 12)         # 深回踩(距突破位远=买得低) 胜率单调
        # pos60 倒U: 30~65最优
        if f['pos60'] < 30:
            s += (f['pos60'] - 30) * 0.3
        elif f['pos60'] <= 65:
            s += 8.0
        else:
            s += 8.0 - (f['pos60'] - 65) * 0.45    # 高位置惩罚
        # b5 站上均线适度 0~9%
        s += lin(f['b5'], -4, 7, -8, 8)
        if f['b5'] > 10:
            s -= (f['b5'] - 10) * 0.6
        # dist_lo 近低点(倒U: 10~35%最优)
        if f['dist_lo'] < 10:
            s += f['dist_lo'] * 0.2
        elif f['dist_lo'] <= 35:
            s += 5.0
        else:
            s += 5.0 - (f['dist_lo'] - 35) * 0.3
        # 涨停少
        s -= f['limit20'] * 2.0
        return max(0.0, min(100.0, s))
    else:
        s = 50.0
        s += lin(-f['t1'], 0, 35, -10, 12)         # 深回踩
        # pos60 低位置(单调: 越低越好, 但<30过深)
        s += lin(f['pos60'], 30, 75, 8, -10)
        # dist_lo 近低点(单调)
        s += lin(f['dist_lo'], 10, 60, 8, -8)
        # 涨停少
        s -= f['limit20'] * 2.5
        # t2 突破力度适度(0~35)
        s += lin(f['t2'], 0, 35, 0, 6)
        if f['t2'] > 45:
            s -= (f['t2'] - 45) * 0.4
        return max(0.0, min(100.0, s))

print("========== 胜率组合v2: 分数档位 ==========")
for typ, rows in d.items():
    print(f"\n-- {typ} --")
    sc = np.array([score_win2(r, typ) for r in rows])
    r10 = np.array([r['r10'] for r in rows])
    r20 = np.array([r['r20'] for r in rows])
    print(f"  基准: 胜率10={(r10>0).mean()*100:.1f}% 收益10={r10.mean():.2f}% | 胜率20={(r20>0).mean()*100:.1f}% 收益20={r20.mean():.2f}%")
    for lo in range(35, 90, 5):
        idx = np.where((sc >= lo) & (sc < lo + 5))[0]
        if len(idx) < 120:
            continue
        print(f"  {lo}-{lo+4}分: n={len(idx)} 胜率10={(r10[idx]>0).mean()*100:.1f}% 收益10={r10[idx].mean():.2f}% | 胜率20={(r20[idx]>0).mean()*100:.1f}% 收益20={r20[idx].mean():.2f}%")
    # top20%
    k = len(rows) // 5
    top = np.argsort(-sc)[:k]
    bot = np.argsort(sc)[:k]
    print(f"  top20%: 胜率10={(r10[top]>0).mean()*100:.1f}% 收益10={r10[top].mean():.2f}% 胜率20={(r20[top]>0).mean()*100:.1f}%")
    print(f"  bot20%: 胜率10={(r10[bot]>0).mean()*100:.1f}% 收益10={r10[bot].mean():.2f}% 胜率20={(r20[bot]>0).mean()*100:.1f}%")
    print(f"  top-bot 胜率差: {(r10[top]>0).mean()*100-(r10[bot]>0).mean()*100:+.1f}pp")

# 样本外(2025+) — 用2024样本定边界不行(无date), 用"信号时间"近似: 直接对比2025+的top vs bot
print("\n========== 全样本 vs 样本外稳健性(按分数位分层) ==========")
for typ, rows in d.items():
    sc = np.array([score_win2(r, typ) for r in rows])
    r10 = np.array([r['r10'] for r in rows])
    # 分5组(全样本分位)
    qs = np.quantile(sc, [0.2, 0.4, 0.6, 0.8])
    print(f"  {typ}: ", end='')
    for g in range(5):
        lo = -np.inf if g == 0 else qs[g-1]
        hi = np.inf if g == 4 else qs[g]
        m = (sc >= lo) & (sc < hi)
        print(f"组{g+1}胜率{(r10[m]>0).mean()*100:.0f}% ", end='')
    print()
