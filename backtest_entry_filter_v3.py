#!/usr/bin/env python3
"""
三策略全面回测：T+1尾盘买入 + 放量大跌过滤(跌≥-2%+量≥1.5x)
对比无过滤的T+1尾盘买入，统计误杀/有效过滤/胜率/收益率变化
"""
import sqlite3

TREND_DB = '/home/ubuntu/databases/trend_picks.db'
STOCK_DB = '/home/ubuntu/databases/Sequoia选股.db'

tc = sqlite3.connect(TREND_DB)
sc = sqlite3.connect(STOCK_DB)
tc.row_factory = sqlite3.Row
sc.row_factory = sqlite3.Row

STRATEGIES = ['premium_a', 'premium_b', 'ultra_shrink']
STRAT_NAMES = {'premium_a': '极品A', 'premium_b': '极品B', 'ultra_shrink': '超缩量'}

# ── 预加载数据 ──
all_data = {}
for sid in STRATEGIES:
    signals = tc.execute("""
        SELECT dp.symbol, dp.date, dp.close_qfq as sig_close, dp.buy_price,
               COALESCE(dp.name, '') as name
        FROM daily_picks dp
        WHERE dp.strategy_id = ?
        ORDER BY dp.date
    """, (sid,)).fetchall()
    
    syms = set(s['symbol'] for s in signals)
    klines = {}
    for sym in syms:
        rows = sc.execute("""
            SELECT date, close_qfq, volume, open_qfq, high_qfq, low_qfq
            FROM stock_daily WHERE symbol=? AND close_qfq>0 ORDER BY date
        """, (sym,)).fetchall()
        if rows:
            klines[sym] = rows
    
    date_idx = {}
    for sym, rows in klines.items():
        date_idx[sym] = {r['date']: i for i, r in enumerate(rows)}
    
    all_data[sid] = {'signals': signals, 'klines': klines, 'date_idx': date_idx}

def get_nth(sym, date_str, n, klines, date_idx):
    rows = klines.get(sym, [])
    idx = date_idx.get(sym, {}).get(date_str)
    if idx is None or idx + n >= len(rows):
        return None
    return rows[idx + n]

def calc_avg_vol(sym, date_str, klines, date_idx, days=20):
    rows = klines.get(sym, [])
    idx = date_idx.get(sym, {}).get(date_str)
    if idx is None or idx < days:
        return None
    vols = [rows[i]['volume'] for i in range(idx-days, idx) if rows[i]['volume'] and rows[i]['volume'] > 0]
    return sum(vols) / len(vols) if vols else None

def get_prev_close(sym, date_str, klines, date_idx):
    idx = date_idx.get(sym, {}).get(date_str)
    rows = klines.get(sym, [])
    if idx is None or idx < 1:
        return None
    return rows[idx - 1]['close_qfq']

# ── 回测参数 ──
# 多个阈值
THRESHOLDS = [
    (-2.0, 1.5, "跌≥-2%+量≥1.5x"),
    (-3.0, 1.5, "跌≥-3%+量≥1.5x"),
    (-5.0, 1.5, "跌≥-5%+量≥1.5x"),
]

def backtest(sid, drop_thresh, vol_mult):
    """返回 (trades, filtered) 其中trades=[收益], filtered=[(sym, date, reason, 基准收益)]"""
    d = all_data[sid]
    signals = d['signals']
    klines = d['klines']
    date_idx = d['date_idx']
    
    trades = []    # [(ret, sym, sig_date)]
    filtered = []  # [(sym, sig_date, t1_ret, t1_vr, baseline_ret)]
    
    for sig in signals:
        sym = sig['symbol']; sig_date = sig['date']
        rows = klines.get(sym, [])
        sig_idx = date_idx.get(sym, {}).get(sig_date)
        if sig_idx is None: continue
        
        t1 = get_nth(sym, sig_date, 1, klines, date_idx)
        if t1 is None: continue
        
        prev_close = get_prev_close(sym, t1['date'], klines, date_idx)
        t1_ret = (t1['close_qfq'] / prev_close - 1) * 100 if prev_close and prev_close > 0 else 0
        avg_vol = calc_avg_vol(sym, t1['date'], klines, date_idx)
        t1_vr = t1['volume'] / avg_vol if avg_vol and avg_vol > 0 else 0
        
        # 基准收益(T+1尾盘买入, 持20d)
        sell_idx = sig_idx + 21
        if sell_idx >= len(rows): continue
        buy_price_t1 = t1['close_qfq']
        sell_price = rows[sell_idx]['close_qfq']
        baseline_ret = (sell_price / buy_price_t1 - 1) * 100
        
        # 过滤条件
        if t1_ret <= drop_thresh and t1_vr >= vol_mult:
            filtered.append((sym, sig_date, t1_ret, t1_vr, baseline_ret))
        else:
            trades.append((baseline_ret, sym, sig_date))
    
    return trades, filtered

# ── 运行回测 ──
print(f"{'策略':6s} {'阈值':20s} {'成交':>4s} {'过滤':>4s} {'均收益':>9s} {'胜率':>5s} {'过滤输家':>8s} {'过滤赢家':>8s} {'误杀':>6s} {'收益Δ':>7s} {'胜率Δ':>6s}")
print("-"*90)

for sid in STRATEGIES:
    name = STRAT_NAMES[sid]
    d = all_data[sid]
    
    # 基准: T+1尾盘无过滤
    base_trades, _ = backtest(sid, -999, 999)  # 无过滤
    base_rets = [t[0] for t in base_trades]
    base_avg = sum(base_rets) / len(base_rets) if base_rets else 0
    base_wr = sum(1 for r in base_rets if r > 0) / len(base_rets) * 100 if base_rets else 0
    base_n = len(base_trades)
    
    print(f"\n{name} (基准: {base_n}笔, 均收益{base_avg:+.2f}%, 胜率{base_wr:.1f}%)")
    
    for drop, mult, desc in THRESHOLDS:
        trades, filtered = backtest(sid, drop, mult)
        rets = [t[0] for t in trades]
        
        if not rets:
            print(f"  {desc:20s}: 全部跳过")
            continue
        
        avg = sum(rets) / len(rets)
        wr = sum(1 for r in rets if r > 0) / len(rets) * 100
        
        # 有效过滤(过滤掉的基准输家) vs 误杀(过滤掉的基准赢家)
        filtered_losers = sum(1 for f in filtered if f[4] < 0)
        filtered_winners = sum(1 for f in filtered if f[4] > 0)
        
        delta_avg = avg - base_avg
        delta_wr = wr - base_wr
        
        print(f"  {desc:20s}: {len(trades):4d} {len(filtered):4d} {avg:+9.2f}% {wr:5.1f}% {filtered_losers:8d} {filtered_winners:8d} {filtered_winners:6d} {delta_avg:+7.2f}% {delta_wr:+6.1f}%")
        
        # 详细：误杀名单
        if filtered_winners > 0:
            winners_filtered = sorted([f for f in filtered if f[4] > 0], key=lambda x: x[4], reverse=True)
            for f in winners_filtered[:5]:
                print(f"    ⚠ 误杀 {f[0]} {f[1]} T+1回撤{f[2]:.1f}% 量比{f[3]:.2f}x  基准收益{f[4]:+.2f}%")
        
        # 详细：有效过滤名单(大输家)
        losers_filtered = sorted([f for f in filtered if f[4] < 0], key=lambda x: x[4])
        for f in losers_filtered[:5]:
            print(f"    ✓ 躲过 {f[0]} {f[1]} T+1回撤{f[2]:.1f}% 量比{f[3]:.2f}x  基准收益{f[4]:+.2f}%")

# ── 综合统计(三策略合并) ──
print("\n" + "="*90)
print("三策略合并统计")
print("="*90)
print(f"{'阈值':20s} {'总信号':>6s} {'总成交':>6s} {'总过滤':>6s} {'均收益':>9s} {'胜率':>5s} {'过滤输家':>8s} {'过滤赢家':>8s} {'收益Δ':>7s} {'胜率Δ':>6s}")
print("-"*90)

for drop, mult, desc in THRESHOLDS:
    all_trades = []
    all_filtered = []
    base_all = []
    
    for sid in STRATEGIES:
        trades, filtered = backtest(sid, drop, mult)
        all_trades.extend(trades)
        all_filtered.extend(filtered)
        
        bt, _ = backtest(sid, -999, 999)
        base_all.extend(bt)
    
    base_rets = [t[0] for t in base_all]
    base_avg = sum(base_rets) / len(base_rets) if base_rets else 0
    base_wr = sum(1 for r in base_rets if r > 0) / len(base_rets) * 100 if base_rets else 0
    
    rets = [t[0] for t in all_trades]
    avg = sum(rets) / len(rets) if rets else 0
    wr = sum(1 for r in rets if r > 0) / len(rets) * 100 if rets else 0
    
    f_losers = sum(1 for f in all_filtered if f[4] < 0)
    f_winners = sum(1 for f in all_filtered if f[4] > 0)
    
    total = len(base_all)
    total_filter = len(all_filtered)
    total_trades = len(all_trades)
    
    delta_avg = avg - base_avg
    delta_wr = wr - base_wr
    
    print(f"{desc:20s} {total:6d} {total_trades:6d} {total_filter:6d} {avg:+9.2f}% {wr:5.1f}% {f_losers:8d} {f_winners:8d} {delta_avg:+7.2f}% {delta_wr:+6.1f}%")
    
    if f_winners > 0:
        print(f"  {'误杀名单':30s}", end="")
        for f in sorted(all_filtered, key=lambda x: x[4], reverse=True)[:5]:
            if f[4] > 0:
                print(f" {f[0]}({f[4]:+.1f}%)", end="")
        print()
    if f_losers > 0:
        print(f"  {'有效躲过':30s}", end="")
        for f in sorted(all_filtered, key=lambda x: x[4])[:5]:
            if f[4] < 0:
                print(f" {f[0]}({f[4]:+.1f}%)", end="")
        print()

# ── 误杀分析 ──
print()
print("="*90)
print("误杀分析：查看被过滤掉的赢家明细")
print("="*90)

# 用最佳阈值(-2%, 1.5x)
for sid in STRATEGIES:
    name = STRAT_NAMES[sid]
    trades, filtered = backtest(sid, -2.0, 1.5)
    winners_filtered = sorted([f for f in filtered if f[4] > 0], key=lambda x: x[4], reverse=True)
    losers_filtered = sorted([f for f in filtered if f[4] < 0], key=lambda x: x[4])
    
    if winners_filtered:
        print(f"\n{name} 误杀({len(winners_filtered)}笔):")
        for f in winners_filtered:
            print(f"  {f[0]} {f[1]} T+1回撤{f[2]:.1f}% 量比{f[3]:.2f}x  基准收益{f[4]:+.2f}%")

# ── 极端误杀分析(被过滤掉的>+30%赢家) - 如果有 ──
print()
big_mistakes = []
for drop, mult, desc in THRESHOLDS:
    if desc == "跌≥-2%+量≥1.5x":
        for sid in STRATEGIES:
            _, filtered = backtest(sid, drop, mult)
            for f in filtered:
                if f[4] > 20:
                    big_mistakes.append((STRAT_NAMES[sid], f[0], f[1], f[2], f[3], f[4]))

if big_mistakes:
    print("误杀中>+20%的赢家:")
    for s_name, sym, dt, t1r, vr, ret in sorted(big_mistakes, key=lambda x: x[5], reverse=True):
        print(f"  {s_name} {sym} {dt} T+1回撤{t1r:.1f}% 量比{vr:.2f}x 基准+{ret:.2f}%")

tc.close()
sc.close()
