#!/usr/bin/env python3
"""二买/三买打分因子回测 — 单因子有效性 + 分组收益单调性
防未来函数: 所有因子只用信号日 i 及之前数据; 收益用 T+1 开盘买入(信号收盘后生成, T+1可执行)
防过拟合: 因子少而可解释, 先单因子看单调性, 组合后样本外(时间切片)验证
"""
import sqlite3, numpy as np, sys, time

SEQ_DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"
PICKS_DB = "/home/ubuntu/databases/trend_picks.db"

t0 = time.time()
seq = sqlite3.connect(SEQ_DB)
picks = sqlite3.connect(PICKS_DB)

# 1. 历史信号(2021起, status ok, 有price)
all_sigs = {}
for typ in ('二买', '三买'):
    all_sigs[typ] = picks.execute(
        "SELECT symbol, signal_date, price FROM chanlun_signals "
        "WHERE signal_type=? AND status='ok' AND price>0 AND signal_date>='2021-01-01'", (typ,)).fetchall()
    print(f"{typ} 信号数: {len(all_sigs[typ])}", flush=True)

# 2. 逐股票流式处理(机器仅3GB内存, 不能全市场驻留)
def open_qfq(r):
    return r[2] * r[6] / r[5] if r[5] else r[2]

# 3. 对每个信号计算因子 + 未来收益
# 因子(信号日i, 用<=i数据):
#   二买: b1回调深度(c0-前20日最低low), b2回调缩量(前5日均量/前20日均量), b3企稳量(v0/前20均量)
#         b4前低不破(c0>前低), b5距MA20, b6回调天数(前低到信号日天数)
#   三买: t1回踩深度(c0-前40日最高high), t2突破力度(前40日最高/更早高点), t3回踩缩量, t4企稳量
# 收益: T+1 open买入 → T+5/10/20 close卖出(对数收益)
def build(sym_rows):
    dates = [r[1] for r in sym_rows]
    close = np.array([r[6] for r in sym_rows], dtype=float)          # close_qfq 前复权
    # 修复: high/low 用当日ratio复权(与close_qfq同基准) — 之前用未复权导致混合基准bug
    high = np.array([r[3] * (r[6] / r[5]) if r[5] else r[3] for r in sym_rows], dtype=float)
    low = np.array([r[4] * (r[6] / r[5]) if r[5] else r[4] for r in sym_rows], dtype=float)
    vol = np.array([r[7] for r in sym_rows], dtype=float)
    oq = np.array([open_qfq(r) for r in sym_rows], dtype=float)
    return dates, close, high, low, vol, oq

# 逐股票流式处理, 无全量数组

def calc_features_and_ret(sym, date, typ, arr):
    """因子用≤T+1数据(信号T+1确认出), 收益T+2开盘买入→T+2+n收盘卖出
    (用户口径: 信号本身需要T+1出, K线可用到T+1, 买入在T+2开盘)"""
    if sym not in arr:
        return None
    dates, close, high, low, vol, oq = arr[sym]
    try:
        i = dates.index(date)
    except ValueError:
        return None
    j = i + 1  # T+1 确认点
    if j < 60 or j + 2 + 20 >= len(dates):
        return None
    c0 = close[j]                 # T+1收盘(确认价)
    if c0 <= 0:
        return None
    L20 = low[j-20:j+1].min()     # 前20日最低(含T+1)
    L60 = low[j-60:j+1].min()
    H40 = high[j-40:j+1].max()    # 前40日最高(含T+1)
    H40p = high[j-80:j-40].max() if j >= 80 else H40
    v5 = vol[j-5:j].mean()
    v20 = vol[j-20:j].mean()
    v0 = vol[j]
    c5 = close[j-5]
    ma20 = close[j-20:j+1].mean()
    li = j - 20 + int(np.argmin(low[j-20:j+1]))
    days_since_low = j - li
    feats = {
        'b1': (c0 - L20) / L20 * 100,
        'b2': (v5 / v20 - 1) * 100,
        'b3': (v0 / v20 - 1) * 100,
        'b4': 1.0 if c0 > L20 else 0.0,
        'b5': (c0 / ma20 - 1) * 100,
        'b6': float(days_since_low),
        'b7': (c5 - L20) / L20 * 100,
        't1': (c0 - H40) / H40 * 100,
        't2': (H40 / H40p - 1) * 100 if H40p > 0 else 0,
        't3': (v5 / v20 - 1) * 100,
        't4': (v0 / v20 - 1) * 100,
        't5': (H40 - L60) / L60 * 100,
        't6': (c0 / H40 - 1) * 100,
    }
    # 收益: T+2开盘买入 → T+2+n收盘卖出
    p0 = oq[i+2]
    if p0 <= 0:
        return None
    rets = {}
    for n in (5, 10, 20):
        pn = close[i+2+n]
        rets[f'r{n}'] = (pn / p0 - 1) * 100
    out = {'typ': typ, 'date': date, 'feats': feats, 'rets': rets}
    return out

# 4. 批量计算: 按股票分组, 逐股读K线算完即弃(内存安全)
sigs_by_sym = {}
for typ in ('二买', '三买'):
    for sym, date, price in all_sigs[typ]:
        sigs_by_sym.setdefault(sym, []).append((typ, date, price))
print(f"有信号的股票数: {len(sigs_by_sym)}", flush=True)
rows2, rows3 = [], []
n_done = 0
for sym, sig_list in sigs_by_sym.items():
    rows = seq.execute(
        "SELECT symbol, date, open, high, low, close, close_qfq, volume FROM stock_daily "
        "WHERE symbol=? AND close_qfq>0 ORDER BY date", (sym,)).fetchall()
    if not rows:
        continue
    arr1 = {sym: build(rows)}
    for typ, date, price in sig_list:
        r = calc_features_and_ret(sym, date, typ, arr1)
        if not r:
            continue
        if typ == '二买':
            rows2.append(r)
        else:
            rows3.append(r)
    n_done += 1
    if n_done % 500 == 0:
        print(f"  已处理{n_done}只, 二买{len(rows2)}/三买{len(rows3)} {time.time()-t0:.0f}s", flush=True)
print(f"二买有效样本: {len(rows2)}, 三买: {len(rows3)} {time.time()-t0:.0f}s", flush=True)

# 5. 单因子分组测试: 每因子5分组(按分位数), 看未来10日收益单调性
def group_test(rows, fname, label):
    vals = [(r['rets']['r10'], r['feats'][fname]) for r in rows]
    vals = [v for v in vals if v[1] is not None and np.isfinite(v[1])]
    if len(vals) < 200:
        return None
    vals.sort(key=lambda x: x[1])
    n = len(vals)
    q = n // 5
    groups = []
    for g in range(5):
        seg = vals[g*q:(g+1)*q if g < 4 else n]
        rets = [x[0] for x in seg]
        groups.append((np.mean(rets), np.median(rets), len(seg)))
    # 单调性: 组均收益随因子值升序的变化
    means = [g[0] for g in groups]
    return groups, means

def report(rows, fname, label):
    res = group_test(rows, fname, label)
    if not res:
        return
    groups, means = res
    mono = (means[4] > means[0]) and (means[4] > max(means[1:4]) or means[0] < min(means[1:4]))
    trend = "↑高因子高分" if means[4] > means[0] else "↓低因子高分"
    print(f"  {fname} {label}: 组10日收益 {[round(m,2) for m in means]} ({trend}) 极差={round(means[4]-means[0],2)}")

print("\n=== 二买因子(未来10日收益, 5分组) ===")
for f in ['b1','b2','b3','b4','b5','b6','b7']:
    report(rows2, f, '二买')
print("\n=== 三买因子 ===")
print(f"三买有效样本: {len(rows3)} {time.time()-t0:.0f}s")
for f in ['t1','t2','t3','t4','t5','t6']:
    report(rows3, f, '三买')

# 保存中间结果供组合阶段使用
import pickle
with open('/tmp/score_bt_rows.pkl', 'wb') as f:
    pickle.dump({'二买': rows2, '三买': rows3}, f)
print(f"\n总耗时 {time.time()-t0:.0f}s, 中间结果已存 /tmp/score_bt_rows.pkl")
