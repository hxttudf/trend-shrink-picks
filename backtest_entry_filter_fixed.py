#!/usr/bin/env python3
"""
三策略+T+1放量大跌过滤 — 修正版（修复T+1涨跌幅计算bug）
"""
import sqlite3

TREND_DB = '/home/ubuntu/databases/trend_picks.db'
STOCK_DB = '/home/ubuntu/databases/Sequoia选股.db'

tc = sqlite3.connect(TREND_DB)
sc = sqlite3.connect(STOCK_DB)
tc.row_factory = sqlite3.Row
sc.row_factory = sqlite3.Row

signals = tc.execute("""
    SELECT dp.symbol, dp.date, COALESCE(dp.name,'') as name, dp.strategy_id
    FROM daily_picks dp
    WHERE dp.strategy_id IN ('premium_a', 'premium_b', 'ultra_shrink')
    ORDER BY dp.date
""").fetchall()

syms = set(s['symbol'] for s in signals)
klines = {}
for sym in syms:
    rows = sc.execute(
        "SELECT date, close_qfq, volume FROM stock_daily WHERE symbol=? AND close_qfq>0 ORDER BY date",
        (sym,)
    ).fetchall()
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
    """ds日期前days天的日均成交量"""
    rows = klines.get(sym, [])
    idx = di.get(sym, {}).get(ds)
    if idx is None or idx < days: return None
    vs = [rows[i]['volume'] for i in range(idx-days, idx)
          if rows[i]['volume'] and rows[i]['volume'] > 0]
    return sum(vs)/len(vs) if vs else None

results = []
for sig in signals:
    sym, ds = sig['symbol'], sig['date']
    rows = klines.get(sym, [])
    si = di.get(sym, {}).get(ds)
    if si is None: continue

    t1 = get_nth(sym, ds, 1)
    if t1 is None: continue

    # T+1日涨跌幅 = T+1收盘 / T+1日前一日收盘 - 1
    # 正确: t1_date的前一日 = rows[idx(t1_date) - 1]
    t1_date = t1['date']
    t1_idx = di.get(sym, {}).get(t1_date)
    if t1_idx is None or t1_idx < 1: continue
    prev_of_t1 = rows[t1_idx - 1]['close_qfq']
    if prev_of_t1 <= 0: continue
    t1_ret = (t1['close_qfq'] / prev_of_t1 - 1) * 100

    # 量比(5日 vs 20日)
    avg5 = avg_vol(sym, t1_date, 5)
    avg20 = avg_vol(sym, t1_date, 20)
    vr5 = t1['volume'] / avg5 if avg5 and avg5 > 0 else 0
    vr20 = t1['volume'] / avg20 if avg20 and avg20 > 0 else 0

    # T+20收益 (从T+1尾盘买入持有20交易日)
    sell_idx = si + 21
    if sell_idx >= len(rows): continue
    ret20 = (rows[sell_idx]['close_qfq'] / t1['close_qfq'] - 1) * 100

    results.append({
        'symbol': sym, 'name': sig['name'], 'sig_date': ds,
        'strategy': sig['strategy_id'],
        't1_ret': round(t1_ret, 1),
        'vr5': round(vr5, 2), 'vr20': round(vr20, 2),
        'ret20': round(ret20, 2)
    })

print(f"有效信号: {len(results)}")

# 所有T+1跌≥-2%的信号
drops = [r for r in results if r['t1_ret'] <= -2.0]
print(f"\nT+1跌≥-2%: {len(drops)}个")
print(f"{'符号':8s} {'名称':12s} {'日期':12s} {'策略':12s} {'T+1涨跌':>8s} {'量比5日':>8s} {'量比20日':>9s} {'T+20':>8s}")
for r in sorted(drops, key=lambda x: x['t1_ret']):
    print(f"{r['symbol']:8s} {r['name']:12s} {r['sig_date']:12s} {r['strategy']:12s} {r['t1_ret']:+8.1f}% {r['vr5']:8.2f} {r['vr20']:9.2f} {r['ret20']:+8.2f}%")

# 分别用5日和20日量比过滤
def run_compare(avg_days, label):
    total = len(results)
    base_rets = [r['ret20'] for r in results]
    base_avg = sum(base_rets)/len(base_rets)
    base_wr = sum(1 for r in base_rets if r>0)/len(base_rets)*100

    all_filtered = []
    all_traded = []
    for r in results:
        is_drop = r['t1_ret'] <= -2.0
        vr = r['vr5'] if avg_days == 5 else r['vr20']
        is_big_vol = vr >= 1.5
        if is_drop and is_big_vol:
            all_filtered.append(r)
        else:
            all_traded.append(r)

    traded_rets = [r['ret20'] for r in all_traded]
    new_avg = sum(traded_rets)/len(traded_rets)
    new_wr = sum(1 for r in traded_rets if r>0)/len(traded_rets)*100

    f_losers = sum(1 for r in all_filtered if r['ret20'] < 0)
    f_winners = sum(1 for r in all_filtered if r['ret20'] > 0)

    print(f"\n{'='*70}")
    print(f"【{label}】跌≥-2%+量≥{1.5}x")
    print(f"{'='*70}")
    print(f"总{total} → 成交{len(all_traded)} 过滤{len(all_filtered)}")
    print(f"均收益: {base_avg:+.2f}% → {new_avg:+.2f}% (Δ{new_avg-base_avg:+.2f}%)")
    print(f"胜率:   {base_wr:.1f}% → {new_wr:.1f}% (Δ{new_wr-base_wr:+.1f}%)")
    print(f"过滤输家{f_losers} 过滤赢家{f_winners}")

    if f_winners > 0:
        print(f"\n  误杀:")
        for f in sorted(all_filtered, key=lambda x: x['ret20'], reverse=True):
            if f['ret20'] > 0:
                vr = f['vr5'] if avg_days==5 else f['vr20']
                print(f"    {f['symbol']}({f['name']}) {f['sig_date']} {f['strategy']} T+1{f['t1_ret']:+.1f}% vr={vr:.2f} 基准+{f['ret20']:.2f}%")
    if f_losers > 0:
        print(f"\n  有效过滤:")
        for f in sorted(all_filtered, key=lambda x: x['ret20']):
            if f['ret20'] < 0:
                vr = f['vr5'] if avg_days==5 else f['vr20']
                print(f"    {f['symbol']}({f['name']}) {f['sig_date']} {f['strategy']} T+1{f['t1_ret']:+.1f}% vr={vr:.2f} 基准{f['ret20']:.2f}%")

run_compare(5, "5日均量(同花顺)")
run_compare(20, "20日均量(DB)")

# 按策略细分
print("\n" + "="*70)
print("按策略细分 (跌≥-2%+量≥1.5x, 同花顺5日量比)")
print("="*70)
for sid, sname in [('premium_a','极品A'), ('premium_b','极品B'), ('ultra_shrink','超缩量')]:
    strat_results = [r for r in results if r['strategy'] == sid]
    base_rets = [r['ret20'] for r in strat_results]
    base_avg = sum(base_rets)/len(base_rets)
    base_wr = sum(1 for r in base_rets if r>0)/len(base_rets)*100 if base_rets else 0

    filtered = [r for r in strat_results if r['t1_ret'] <= -2.0 and r['vr5'] >= 1.5]
    traded = [r for r in strat_results if r not in filtered]
    traded_rets = [r['ret20'] for r in traded]
    new_avg = sum(traded_rets)/len(traded_rets)
    new_wr = sum(1 for r in traded_rets if r>0)/len(traded_rets)*100

    f_l = sum(1 for r in filtered if r['ret20'] < 0)
    f_w = sum(1 for r in filtered if r['ret20'] > 0)

    print(f"\n{sname} (总{len(strat_results)}): 成交{len(traded)} 过滤{len(filtered)}")
    print(f"  均收益{base_avg:+.2f}% → {new_avg:+.2f}% (Δ{new_avg-base_avg:+.2f}%)")
    print(f"  胜率{base_wr:.1f}% → {new_wr:.1f}% (Δ{new_wr-base_wr:+.1f}%)")
    print(f"  过滤输家{f_l} 过滤赢家{f_w}")
    for f in filtered:
        print(f"    {'✓躲过' if f['ret20']<0 else '⚠误杀'} {f['symbol']}({f['name']}) {f['sig_date']} T+1{f['t1_ret']:+.1f}% vr5={f['vr5']:.2f} 基准{f['ret20']:+.2f}%")

tc.close()
sc.close()
