#!/usr/bin/env python3
"""卖点打分: 单因子胜率单调性(卖对率) + 分类型组合 + 样本外验证"""
import pickle, numpy as np

d = pickle.load(open('/tmp/score_bt_sell.pkl', 'rb'))

def wr(rows, fkey, label):
    vals = np.array([r['f'][fkey] for r in rows])
    rets = np.array([r['r10'] for r in rows])
    order = np.argsort(vals)
    n = len(order)
    q = n // 5
    line = [f"{label:<9}"]
    wins = []
    for g in range(5):
        seg = order[g*q:(g+1)*q if g < 4 else n]
        w = (rets[seg] < 0).mean() * 100   # 卖对率
        m = rets[seg].mean()
        wins.append(w)
        line.append(f"{w:.0f}%/{m:.1f}")
    print('  '.join(line))
    return wins

for typ, rows in d.items():
    print(f"\n========== {typ}(n={len(rows)}) 单因子卖对率(10日, 5分组低→高) ==========")
    for f in ['chg10', 'chg20', 'vtrend', 'dist_lo', 'dist_hi', 'limit20', 't5', 't1',
              'pos60', 'rsi', 'atr', 'slope', 'to_hi', 'b1', 'b5', 'under_ma']:
        wr(rows, f, f)

# 组合设计(分类型)
def lin(v, p20, p80, lo, hi):
    if p80 <= p20:
        return 0.0
    x = (v - p20) / (p80 - p20)
    return max(lo, min(hi, lo + x * (hi - lo)))

def sell_score(r, typ):
    f = r['f']
    if typ == '一卖':   # 顶部: 涨得猛+量热+位置高+涨停多
        s = 50.0
        s += lin(f['chg10'], 0, 20, -8, 10)
        s += lin(f['vtrend'], 0, 80, -5, 15)
        s += lin(f['dist_lo'], 10, 60, -8, 10)
        s += f['limit20'] * 2.5
        s += lin(f['t5'], 20, 70, -5, 6)
        s += lin(f['pos60'], 40, 80, -4, 5)
        return max(0.0, min(100.0, s))
    if typ == '二卖':   # 反弹出货: 反弹放量+位置高+涨停多
        s = 50.0
        s += lin(f['vtrend'], -30, 30, -8, 14)
        s += lin(f['dist_lo'], 5, 40, -8, 10)
        s += f['limit20'] * 2.0
        s += lin(f['t5'], 20, 65, -5, 6)
        s += lin(f['chg10'], -5, 8, -4, 6)
        return max(0.0, min(100.0, s))
    else:               # 三卖: 破位放量+破位深+弱反抽
        s = 50.0
        s += lin(f['vtrend'], -40, 20, -8, 14)
        s += lin(-f['t1'], 5, 35, -6, 10)
        s += lin(-f['chg10'], -8, 6, -6, 8)
        s += lin(f['dist_lo'], 0, 20, -6, 6)
        s += lin(f['atr'], 1, 6, -4, 6)
        return max(0.0, min(100.0, s))

print("\n========== 卖点组合: 分数档位卖对率 ==========")
for typ, rows in d.items():
    print(f"\n-- {typ} --")
    sc = np.array([sell_score(r, typ) for r in rows])
    r10 = np.array([r['r10'] for r in rows])
    r20 = np.array([r['r20'] for r in rows])
    print(f"  基准: 卖对率10={(r10<0).mean()*100:.1f}% 均跌={(r10[r10<0].mean()):.2f}%(亏) 卖飞率={(r10>12).mean()*100:.1f}% | 20日卖对率={(r20<0).mean()*100:.1f}%")
    for lo in range(40, 90, 5):
        idx = np.where((sc >= lo) & (sc < lo + 5))[0]
        if len(idx) < 100:
            continue
        print(f"  {lo}-{lo+4}分: n={len(idx)} 卖对率10={(r10[idx]<0).mean()*100:.1f}% 均跌={r10[idx].mean():.2f}% 卖飞率={(r10[idx]>12).mean()*100:.1f}% | 20日={(r20[idx]<0).mean()*100:.1f}%")
    k = len(rows) // 5
    top = np.argsort(-sc)[:k]
    bot = np.argsort(sc)[:k]
    print(f"  top20%: 卖对率10={(r10[top]<0).mean()*100:.1f}% 均收益={r10[top].mean():.2f}% 卖飞率={(r10[top]>12).mean()*100:.1f}%")
    print(f"  bot20%: 卖对率10={(r10[bot]<0).mean()*100:.1f}% 均收益={r10[bot].mean():.2f}% 卖飞率={(r10[bot]>12).mean()*100:.1f}%")
    print(f"  20日 top20%: 卖对率={(r20[top]<0).mean()*100:.1f}% 均收益={r20[top].mean():.2f}%")
