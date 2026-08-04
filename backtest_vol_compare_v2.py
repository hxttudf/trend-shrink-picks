#!/usr/bin/env python3
"""
对比5日均量 vs 20日均量对放量大跌过滤的影响
"""
import sqlite3

TREND_DB = '/home/ubuntu/databases/trend_picks.db'
STOCK_DB = '/home/ubuntu/databases/Sequoia选股.db'

tc = sqlite3.connect(TREND_DB)
sc = sqlite3.connect(STOCK_DB)
tc.row_factory = sqlite3.Row
sc.row_factory = sqlite3.Row

# 获取所有策略信号
signals = tc.execute("""
    SELECT dp.symbol, dp.date, COALESCE(dp.name,'') as name, dp.strategy_id
    FROM daily_picks dp
    WHERE dp.strategy_id IN ('premium_a', 'premium_b', 'ultra_shrink')
    ORDER BY dp.date
""").fetchall()

print(f"总信号: {len(signals)}")

# 预加载K线
syms = set(s['symbol'] for s in signals)
klines = {}
for sym in syms:
    rows = sc.execute("""
        SELECT date, close_qfq, volume
        FROM stock_daily WHERE symbol=? AND close_qfq>0 ORDER BY date
    """, (sym,)).fetchall()
    if rows:
        klines[sym] = rows

di = {}
for sym, rows in klines.items():
    di[sym] = {r['date']: i for i, r in enumerate(rows)}

def get_nth(sym, ds, n):
    rows = klines.get(sym, [])
    idx = di.get(sym, {}).get(ds)
    if idx is None or idx+n >= len(rows): return None
    return rows[idx+n]

def avg_vol(sym, ds, days):
    rows = klines.get(sym, [])
    idx = di.get(sym, {}).get(ds)
    if idx is None or idx < days: return None
    vs = [rows[i]['volume'] for i in range(idx-days, idx) if rows[i]['volume'] and rows[i]['volume'] > 0]
    return sum(vs)/len(vs) if vs else None

# 对每个信号计算T+1的5日和20日量比
results = []
for sig in signals:
    sym, ds = sig['symbol'], sig['date']
    rows = klines.get(sym, [])
    si = di.get(sym, {}).get(ds)
    if si is None: continue
    
    t1 = get_nth(sym, ds, 1)
    if t1 is None: continue
    if si < 1: continue
    
    t1_ret = (t1['close_qfq'] / rows[si-1]['close_qfq'] - 1) * 100
    if rows[si-1]['close_qfq'] <= 0: continue
    
    avg5 = avg_vol(sym, t1['date'], 5)
    avg20 = avg_vol(sym, t1['date'], 20)
    vr5 = t1['volume'] / avg5 if avg5 and avg5 > 0 else 0
    vr20 = t1['volume'] / avg20 if avg20 and avg20 > 0 else 0
    
    # T+20收益
    sell_idx = si + 21
    if sell_idx >= len(rows): continue
    ret20 = (rows[sell_idx]['close_qfq'] / t1['close_qfq'] - 1) * 100
    
    results.append({
        'symbol': sym, 'name': sig['name'],
        'sig_date': ds, 'strategy': sig['strategy_id'],
        't1_ret': round(t1_ret, 1),
        'vr5': round(vr5, 2),
        'vr20': round(vr20, 2),
        'ret20': round(ret20, 2)
    })

print(f"有效信号: {len(results)}")

# 筛选条件: 跌≥-2%
drop_signals = [r for r in results if r['t1_ret'] <= -2.0]
print(f"\nT+1跌≥-2%的信号: {len(drop_signals)}")

# 分别用5日量比和20日量比过滤
print("\n=== 对比: 跌≥-2% + 量≥1.5x ===")

# 5日
filtered_5 = [r for r in drop_signals if r['vr5'] >= 1.5]
# 20日
filtered_20 = [r for r in drop_signals if r['vr20'] >= 1.5]

print(f"\n5日均量(同花顺)过滤: {len(filtered_5)}个信号")
print(f"20日均量(DB)过滤:    {len(filtered_20)}个信号")
print(f"两个都过滤的:         {len([r for r in drop_signals if r['vr5'] >= 1.5 and r['vr20'] >= 1.5])}个")
print(f"仅5日过滤的:          {len([r for r in drop_signals if r['vr5'] >= 1.5 and r['vr20'] < 1.5])}个")
print(f"仅20日过滤的:         {len([r for r in drop_signals if r['vr5'] < 1.5 and r['vr20'] >= 1.5])}个")

print("\n=== 详情 ===")
print(f"{'符号':8s} {'日期':12s} {'策略':12s} {'T+1涨跌':>8s} {'量比5日':>8s} {'量比20日':>9s} {'T+20收益':>9s} {'5日筛':>5s} {'20日筛':>6s}")
print("-"*75)

# 按T+1涨跌幅排序
for r in sorted(drop_signals, key=lambda x: x['t1_ret']):
    f5 = '✓' if r['vr5'] >= 1.5 else ''
    f20 = '✓' if r['vr20'] >= 1.5 else ''
    print(f"{r['symbol']:8s} {r['sig_date']:12s} {r['strategy']:12s} {r['t1_ret']:+8.1f}% {r['vr5']:8.2f} {r['vr20']:9.2f} {r['ret20']:+9.2f}% {f5:5s} {f20:6s}")

# 筛选结果汇总
print("\n\n=== 最终对比 ===")

def filter_stats(use_days):
    """返回(总信号数, 成交数, 过滤数, 过滤输家, 过滤赢家, 过滤ret_list)"""
    all_trades = []
    all_filtered = []
    for r in results:
        drop = r['t1_ret'] <= -2.0
        vr = r['vr5'] if use_days == 5 else r['vr20']
        over = vr >= 1.5
        
        if drop and over:
            all_filtered.append(r)
        else:
            all_trades.append(r)
    return len(results), len(all_trades), len(all_filtered), \
           sum(1 for f in all_filtered if f['ret20'] < 0), \
           sum(1 for f in all_filtered if f['ret20'] > 0), \
           all_filtered

for days, label in [(5, "5日均量(同花顺)"), (20, "20日均量(DB)")]:
    total, traded, fcount, fl, fw, f_list = filter_stats(days)
    base_avg = sum(r['ret20'] for r in results) / len(results)
    base_wr = sum(1 for r in results if r['ret20'] > 0) / len(results) * 100
    
    traded_rets = [r['ret20'] for r in results if not (r['t1_ret'] <= -2.0 and (r['vr5'] if days==5 else r['vr20']) >= 1.5)]
    if traded_rets:
        new_avg = sum(traded_rets) / len(traded_rets)
        new_wr = sum(1 for r in traded_rets if r > 0) / len(traded_rets) * 100
    else:
        new_avg, new_wr = 0, 0
    
    print(f"\n{label}:")
    print(f"  总{total}, 成交{traded}, 过滤{fcount}")
    print(f"  过滤输家{fl}, 过滤赢家{fw}")
    print(f"  基准均收益{base_avg:+.2f}% → {new_avg:+.2f}% (Δ{new_avg-base_avg:+.2f}%)")
    print(f"  基准胜率{base_wr:.1f}% → {new_wr:.1f}% (Δ{new_wr-base_wr:+.1f}%)")
    
    if fw > 0:
        print(f"  误杀:")
        for f in sorted(f_list, key=lambda x: x['ret20'], reverse=True):
            if f['ret20'] > 0:
                print(f"    {f['symbol']} {f['sig_date']} {f['strategy']} T+1涨{f['t1_ret']:+.1f}% vr={f['vr5'] if days==5 else f['vr20']:.2f} 收益{f['ret20']:+.2f}%")
    if fl > 0:
        print(f"  有效过滤:")
        for f in sorted(f_list, key=lambda x: x['ret20']):
            if f['ret20'] < 0:
                print(f"    {f['symbol']} {f['sig_date']} {f['strategy']} T+1涨{f['t1_ret']:+.1f}% vr={f['vr5'] if days==5 else f['vr20']:.2f} 收益{f['ret20']:+.2f}%")

tc.close()
sc.close()
