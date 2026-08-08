#!/usr/bin/env python3
"""卖点(一卖/二卖/三卖)四分类剖析 + 单因子胜率 — 胜率=卖出后10日下跌占比(卖对)
因子复用买点框架(≤T+1数据), 2024+样本
"""
import sqlite3, numpy as np, pickle, time

t0 = time.time()
seq = sqlite3.connect("/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db")
picks = sqlite3.connect("/home/ubuntu/databases/trend_picks.db")

all_sigs = {}
for typ in ('一卖', '二卖', '三卖'):
    all_sigs[typ] = picks.execute(
        "SELECT symbol, signal_date, price FROM chanlun_signals "
        "WHERE signal_type=? AND status='ok' AND price>0 AND signal_date>='2024-01-01'", (typ,)).fetchall()
    print(f"{typ} 信号: {len(all_sigs[typ])}", flush=True)

sigs_by_sym = {}
for typ, rows in all_sigs.items():
    for sym, date, price in rows:
        sigs_by_sym.setdefault(sym, []).append((typ, date, price))

def open_qfq(r):
    return r[2] * r[6] / r[5] if r[5] else r[2]

def calc(sym, date):
    rows = seq.execute(
        "SELECT symbol, date, open, high, low, close, close_qfq, volume FROM stock_daily "
        "WHERE symbol=? AND close_qfq>0 ORDER BY date", (sym,)).fetchall()
    if not rows:
        return None
    dates = [r[1] for r in rows]
    try:
        i = dates.index(date)
    except ValueError:
        return None
    j = i + 1
    if j < 90 or j + 22 >= len(rows):
        return None
    close = np.array([r[6] for r in rows], float)
    high = np.array([r[3] * (r[6] / r[5]) if r[5] else r[3] for r in rows], float)
    low = np.array([r[4] * (r[6] / r[5]) if r[5] else r[4] for r in rows], float)
    vol = np.array([r[7] for r in rows], float)
    oq = np.array([open_qfq(r) for r in rows], float)
    c0 = close[j]
    if c0 <= 0:
        return None
    f = {}
    ma20 = close[j-20:j+1].mean()
    ma60 = close[j-60:j+1].mean()
    L20 = low[j-20:j+1].min()
    L60 = low[j-60:j+1].min()
    H40 = high[j-40:j+1].max()
    H60 = high[j-60:j+1].max()
    f['b5'] = (c0 / ma20 - 1) * 100
    f['b1'] = (c0 - L20) / L20 * 100
    f['t1'] = (c0 - H40) / H40 * 100
    f['t5'] = (H40 - L60) / L60 * 100
    f['b6'] = float(j - (j - 20 + int(np.argmin(low[j-20:j+1]))))
    f['chg10'] = (c0 / close[j-10] - 1) * 100           # 10日涨幅(顶部特征)
    f['chg20'] = (c0 / close[j-20] - 1) * 100
    tr = np.maximum(high[1:] - low[1:], 1e-9)
    f['atr'] = tr[j-13:j+1].mean() / c0 * 100
    diff = np.diff(close[j-14:j+1])
    up = diff[diff > 0].sum()
    dn = -diff[diff < 0].sum()
    f['rsi'] = 100 * up / (up + dn) if (up + dn) > 0 else 50
    y = close[j-20:j]
    x = np.arange(20)
    f['slope'] = np.polyfit(x, y, 1)[0] / c0 * 100
    f['m_align'] = 1.0 if ma20 > ma60 else 0.0
    f['pos60'] = (c0 - L60) / (H60 - L60) * 100 if H60 > L60 else 50
    f['vtrend'] = (vol[j-5:j].mean() / max(vol[j-60:j].mean(), 1) - 1) * 100
    f['gap'] = (oq[j] / close[j-1] - 1) * 100
    f['dist_hi'] = (c0 / H60 - 1) * 100
    f['dist_lo'] = (c0 / L60 - 1) * 100
    f['limit20'] = (high[j-20:j+1] > close[j-21:j] * 1.09).sum()
    # 卖点特有: 距前高/前低(二卖=反弹不创新高; 三卖=破位)
    f['to_hi'] = (H40 / max(H60, 1e-9) - 1) * 100        # 40日高 vs 60日高(创新高程度)
    f['under_ma'] = 1.0 if c0 < ma20 else 0.0            # 跌破MA20
    p0 = oq[i+2]
    if p0 <= 0:
        return None
    r10 = (close[i+2+10] / p0 - 1) * 100
    r20 = (close[i+2+20] / p0 - 1) * 100
    return {'f': f, 'r10': r10, 'r20': r20, 'date': date}

out = {'一卖': [], '二卖': [], '三卖': []}
n_done = 0
for sym, sig_list in sigs_by_sym.items():
    for typ, date, price in sig_list:
        r = calc(sym, date)
        if r:
            out[typ].append(r)
    n_done += 1
    if n_done % 800 == 0:
        print(f"  处理{n_done}只 {time.time()-t0:.0f}s", flush=True)

pickle.dump(out, open('/tmp/score_bt_sell.pkl', 'wb'))
print(f"完成 {time.time()-t0:.0f}s")

# 四分类剖析(卖点后10日收益): 大跌<-12 / 小跌-12~0 / 小涨0~12 / 大涨>12
for typ in ('一卖', '二卖', '三卖'):
    rows = out[typ]
    r10s = np.array([r['r10'] for r in rows])
    print(f"\n{'='*66}\n{typ}(n={len(rows)}) 四分类: 卖对率(下跌占比)={(r10s<0).mean()*100:.1f}%")
    groups = {'大跌': r10s < -12, '小跌': (r10s < 0) & (r10s >= -12), '小涨': (r10s > 0) & (r10s <= 12), '大涨': r10s > 12}
    print(f"  分布: " + '  '.join(f"{k} {(m).mean()*100:.0f}%" for k, m in groups.items()))
    feat_keys = list(rows[0]['f'].keys())
    print(f"  {'因子':<10}" + ''.join(f"{k:>9}" for k in groups))
    for fk in feat_keys:
        line = f"  {fk:<8}"
        for k in groups:
            vals = [r['f'][fk] for r, m in zip(rows, groups[k]) if m]
            line += f"{np.mean(vals):>9.1f}" if vals else f"{'-':>9}"
        print(line)
