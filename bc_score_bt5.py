#!/usr/bin/env python3
"""二买/三买信号后表现四分类(大涨/小涨/小跌/大跌)特征剖析 + 胜率导向因子挖掘
只重算2024-2026信号(近两年, 与当前市场结构更接近), 因子只用≤T+1数据
"""
import sqlite3, numpy as np, pickle, time

t0 = time.time()
SEQ_DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"
PICKS_DB = "/home/ubuntu/databases/trend_picks.db"
seq = sqlite3.connect(SEQ_DB)
picks = sqlite3.connect(PICKS_DB)

all_sigs = {}
for typ in ('二买', '三买'):
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
    """扩展因子 + 10日收益"""
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
    if j < 90 or j + 2 + 20 >= len(rows):
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
    # 基础因子
    ma20 = close[j-20:j+1].mean()
    ma60 = close[j-60:j+1].mean()
    L20 = low[j-20:j+1].min()
    L60 = low[j-60:j+1].min()
    H40 = high[j-40:j+1].max()
    H60 = high[j-60:j+1].max()
    f['b5'] = (c0 / ma20 - 1) * 100
    f['b1'] = (c0 - L20) / L20 * 100
    f['t2'] = (H40 / max(high[j-80:j-40].max(), 1e-9) - 1) * 100 if j >= 80 else 0
    f['t5'] = (H40 - L60) / L60 * 100
    f['t1'] = (c0 - H40) / H40 * 100
    f['b6'] = float(j - (j - 20 + int(np.argmin(low[j-20:j+1]))))
    # 胜率导向新因子
    tr = np.maximum(high[1:] - low[1:], 1e-9)
    atr14 = tr[j-13:j+1].mean()
    f['atr'] = atr14 / c0 * 100                          # 波动率
    # RSI14
    diff = np.diff(close[j-14:j+1])
    up = diff[diff > 0].sum()
    dn = -diff[diff < 0].sum()
    f['rsi'] = 100 * up / (up + dn) if (up + dn) > 0 else 50
    # 20日斜率(线性回归归一化)
    y = close[j-20:j]
    x = np.arange(20)
    slope = np.polyfit(x, y, 1)[0]
    f['slope'] = slope / c0 * 100                         # 20日趋势斜率%
    f['m_align'] = 1.0 if ma20 > ma60 else 0.0            # 多头排列
    f['pos60'] = (c0 - L60) / (H60 - L60) * 100 if H60 > L60 else 50  # 60日位置
    f['vtrend'] = (vol[j-5:j].mean() / max(vol[j-60:j].mean(), 1) - 1) * 100  # 量能趋势
    f['gap'] = (oq[j] / close[j-1] - 1) * 100             # T+1开盘跳空
    f['dist_hi'] = (c0 / H60 - 1) * 100                   # 距60日高点
    f['dist_lo'] = (c0 / L60 - 1) * 100                   # 距60日低点
    f['limit20'] = (high[j-20:j+1] > close[j-21:j] * 1.09).sum()  # 近20日涨停次数
    # 收益
    p0 = oq[i+2]
    if p0 <= 0:
        return None
    r10 = (close[i+2+10] / p0 - 1) * 100
    r20 = (close[i+2+20] / p0 - 1) * 100
    return {'f': f, 'r10': r10, 'r20': r20, 'date': date}

# 分批处理
out = {'二买': [], '三买': []}
n_done = 0
for sym, sig_list in sigs_by_sym.items():
    for typ, date, price in sig_list:
        r = calc(sym, date)
        if r:
            out[typ].append(r)
    n_done += 1
    if n_done % 800 == 0:
        print(f"  处理{n_done}只 {time.time()-t0:.0f}s", flush=True)

pickle.dump(out, open('/tmp/score_bt5.pkl', 'wb'))
print(f"完成: 二买{len(out['二买'])} 三买{len(out['三买'])} {time.time()-t0:.0f}s", flush=True)

# 四分类剖析
for typ in ('二买', '三买'):
    rows = out[typ]
    print(f"\n{'='*60}\n{typ} 四分类(按10日收益): 大涨>12% / 小涨0~12% / 小跌-12~0 / 大跌<-12%")
    r10s = np.array([r['r10'] for r in rows])
    groups = {'大涨': r10s > 12, '小涨': (r10s > 0) & (r10s <= 12), '小跌': (r10s > -12) & (r10s <= 0), '大跌': r10s <= -12}
    names = list(groups.keys())
    feat_keys = list(rows[0]['f'].keys())
    print(f"{'因子':<10}" + ''.join(f"{n:>10}" for n in names))
    for fk in feat_keys:
        line = f"{fk:<10}"
        for n in names:
            vals = [r['f'][fk] for r, m in zip(rows, groups[n]) if m]
            if vals:
                line += f"{np.mean(vals):>10.1f}"
            else:
                line += f"{'-':>10}"
        print(line)
    # 大涨 vs 大跌 区分度(diff/波动)
    print("\n  大涨vs大跌 因子区分度(均值差, 越大越能区分):")
    diffs = []
    for fk in feat_keys:
        big = np.mean([r['f'][fk] for r, m in zip(rows, groups['大涨']) if m]) if groups['大涨'].any() else 0
        bad = np.mean([r['f'][fk] for r, m in zip(rows, groups['大跌']) if m]) if groups['大跌'].any() else 0
        diffs.append((fk, big - bad))
    diffs.sort(key=lambda x: -abs(x[1]))
    for fk, d in diffs[:10]:
        print(f"    {fk}: {d:+.2f}")
