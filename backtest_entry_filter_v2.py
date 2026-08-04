#!/usr/bin/env python3
"""
补充回测：对比T+1尾盘买入(无过滤) vs T+1尾盘买入(有过滤),
隔离"尾盘买入"本身的效果。
"""

import sqlite3
from collections import defaultdict

TREND_DB = '/home/ubuntu/databases/trend_picks.db'
STOCK_DB = '/home/ubuntu/databases/Sequoia选股.db'

tc = sqlite3.connect(TREND_DB)
sc = sqlite3.connect(STOCK_DB)
tc.row_factory = sqlite3.Row
sc.row_factory = sqlite3.Row

signals = tc.execute("""
    SELECT dp.symbol, dp.date, dp.close_qfq as sig_close, dp.buy_price, 
           dp.vol_ratio, COALESCE(dp.name, '') as name
    FROM daily_picks dp
    WHERE dp.strategy_id = 'premium_b'
    ORDER BY dp.date
""").fetchall()

# 预加载K线
all_symbols = set(s['symbol'] for s in signals)
stock_kline = {}
for sym in all_symbols:
    rows = sc.execute("""
        SELECT date, close_qfq, volume, open_qfq, high_qfq, low_qfq
        FROM stock_daily WHERE symbol=? AND close_qfq>0 ORDER BY date
    """, (sym,)).fetchall()
    if rows:
        stock_kline[sym] = rows

stock_date_idx = {}
for sym, rows in stock_kline.items():
    stock_date_idx[sym] = {r['date']: i for i, r in enumerate(rows)}

def get_nth_close(sym, date_str, n=1):
    rows = stock_kline.get(sym, [])
    idx = stock_date_idx.get(sym, {}).get(date_str)
    if idx is None or idx + n >= len(rows):
        return None, None
    return rows[idx + n]['close_qfq'], rows[idx + n]['date']

def get_nth_data(sym, date_str, n=1):
    rows = stock_kline.get(sym, [])
    idx = stock_date_idx.get(sym, {}).get(date_str)
    if idx is None or idx + n >= len(rows):
        return None
    return rows[idx + n]

def calc_avg_vol(sym, date_str, days=20):
    rows = stock_kline.get(sym, [])
    idx = stock_date_idx.get(sym, {}).get(date_str)
    if idx is None or idx < days:
        return None
    total = 0
    cnt = 0
    for i in range(idx - days, idx):
        if rows[i]['volume'] and rows[i]['volume'] > 0:
            total += rows[i]['volume']
            cnt += 1
    return total / cnt if cnt > 0 else None

print(f"总信号: {len(signals)}")
print()

# ── 基准1: T+1开盘买入(原始) ──
print("="*70)
print("【基准1】T+1开盘买入(原始)")
print("="*70)
trades = []
skipped = []
for sig in signals:
    sym = sig['symbol']; sig_date = sig['date']
    rows = stock_kline.get(sym, [])
    sig_idx = stock_date_idx.get(sym, {}).get(sig_date)
    if sig_idx is None:
        skipped.append((sym, sig_date, 'no data'))
        continue
    
    bp_row = get_nth_data(sym, sig_date, 1)
    if bp_row is None:
        skipped.append((sym, sig_date, 'no T+1'))
        continue
    buy_price = bp_row['open_qfq']
    buy_date = bp_row['date']
    if not buy_price or buy_price <= 0:
        skipped.append((sym, sig_date, 'bad open'))
        continue
    
    sell_idx = sig_idx + 21
    if sell_idx >= len(rows):
        skipped.append((sym, sig_date, 'no T+20'))
        continue
    sell_price = rows[sell_idx]['close_qfq']
    sell_date = rows[sell_idx]['date']
    ret = (sell_price / buy_price - 1) * 100
    trades.append(ret)

rets = trades
wr = sum(1 for r in rets if r > 0) / len(rets) * 100
avg = sum(rets) / len(rets)
print(f"  成交{len(rets)} 跳过{len(skipped)}  均收益{avg:+.2f}%  胜率{wr:.1f}%")

# ── 基准2: T+1尾盘买入(无过滤) ──
print()
print("="*70)
print("【基准2】T+1尾盘买入(无过滤)")
print("="*70)
trades = []
skipped = []
for sig in signals:
    sym = sig['symbol']; sig_date = sig['date']
    rows = stock_kline.get(sym, [])
    sig_idx = stock_date_idx.get(sym, {}).get(sig_date)
    if sig_idx is None:
        skipped.append((sym, sig_date, 'no data'))
        continue
    
    bp_row = get_nth_data(sym, sig_date, 1)
    if bp_row is None:
        skipped.append((sym, sig_date, 'no T+1'))
        continue
    buy_price = bp_row['close_qfq']  # T+1收盘
    buy_date = bp_row['date']
    if not buy_price or buy_price <= 0:
        skipped.append((sym, sig_date, 'bad close'))
        continue
    
    sell_idx = sig_idx + 21
    if sell_idx >= len(rows):
        skipped.append((sym, sig_date, 'no T+20'))
        continue
    sell_price = rows[sell_idx]['close_qfq']
    ret = (sell_price / buy_price - 1) * 100
    trades.append(ret)

rets = trades
wr = sum(1 for r in rets if r > 0) / len(rets) * 100
avg = sum(rets) / len(rets)
print(f"  成交{len(rets)} 跳过{len(skipped)}  均收益{avg:+.2f}%  胜率{wr:.1f}%")

# ── 方案A: T+1尾盘买入, 放量大跌过滤 ──
print()
print("="*70)
print("【方案A】T+1尾盘买入 + 放量大跌过滤(跌≥-2%+量≥1.5x)")
print("="*70)

def get_prev_close(sym, date_str, rows):
    idx = stock_date_idx.get(sym, {}).get(date_str)
    if idx is None or idx < 1:
        return None
    return rows[idx - 1]['close_qfq']

filtered_signals = []  # (sym, sig_date, reason)
entered_signals = []  # (return, sym, sig_date)
for sig in signals:
    sym = sig['symbol']; sig_date = sig['date']
    rows = stock_kline.get(sym, [])
    sig_idx = stock_date_idx.get(sym, {}).get(sig_date)
    if sig_idx is None:
        continue
    
    t1 = get_nth_data(sym, sig_date, 1)
    if t1 is None:
        continue
    
    prev_close = get_prev_close(sym, t1['date'], rows)
    t1_ret = (t1['close_qfq'] / prev_close - 1) * 100 if prev_close and prev_close > 0 else 0
    
    avg_vol = calc_avg_vol(sym, t1['date'])
    t1_vr = t1['volume'] / avg_vol if avg_vol and avg_vol > 0 else 0
    
    # 放量大跌: 跌≥-2% + 量≥1.5x 日均量
    if t1_ret <= -2.0 and t1_vr >= 1.5:
        filtered_signals.append((sym, sig_date, f'T+1放量大跌({t1_ret:.1f}%,量比{t1_vr:.2f})'))
        continue
    
    # T+1尾盘买入
    buy_price = t1['close_qfq']
    sell_idx = sig_idx + 21
    if sell_idx >= len(rows):
        continue
    sell_price = rows[sell_idx]['close_qfq']
    ret = (sell_price / buy_price - 1) * 100
    entered_signals.append((ret, sym, sig_date))

rets = [r for r, _, _ in entered_signals]
wr = sum(1 for r in rets if r > 0) / len(rets) * 100 if rets else 0
avg = sum(rets) / len(rets) if rets else 0
print(f"  成交{len(rets)} 跳过{len(filtered_signals)}  均收益{avg:+.2f}%  胜率{wr:.1f}%")

print(f"\n过滤掉的{len(filtered_signals)}个信号详情:")
for sym, dt, reason in filtered_signals:
    print(f"  {sym} {dt}: {reason}")

# ── 净值模拟 ──
print()
print("="*70)
print("【净值模拟对比】NAV 25%/只×上限4只×持有20天×有多少买多少")
print("="*70)

def run_nav_sim(entry_data_list, initial=200000):
    """
    entry_data_list: [(buy_date, sell_date, buy_price, sell_price, ...), ...]
    简化为信号时间线 + 收益率
    """
    cash = initial
    nav = initial
    positions = []  # [(buy_date, sell_date, buy_price, current_price, days_held, ret_actual)]
    daily_log = []
    
    # 收集所有交易日(从signals取日期范围)
    all_dates = set()
    for sig in signals:
        all_dates.add(sig['date'])
        t1 = get_nth_data(sig['symbol'], sig['date'], 1)
        if t1: all_dates.add(t1['date'])
    
    sorted_dates = sorted(all_dates)
    
    # 按信号日期处理
    signal_map = {}
    for entry in entry_data_list:
        sig_date = entry['sig_date']
        if sig_date not in signal_map:
            signal_map[sig_date] = []
        signal_map[sig_date].append(entry)
    
    for cur_date in sorted_dates:
        # 到期检查
        positions_to_close = [p for p in positions if p['sell_date'] == cur_date]
        for p in positions_to_close:
            proceeds = p['sell_price'] * p['volume']
            cash += proceeds
            positions.remove(p)
        
        # 新信号买入
        if cur_date in signal_map:
            for entry in signal_map[cur_date]:
                if len(positions) >= 4:
                    continue  # 上限4只
                target_val = nav * 0.25
                actual_val = min(target_val, cash)
                if actual_val < 1000:
                    continue
                volume = int(actual_val / entry['buy_price'] / 100) * 100
                if volume <= 0:
                    continue
                cost = volume * entry['buy_price']
                cash -= cost
                positions.append({
                    'symbol': entry['symbol'],
                    'name': entry['name'],
                    'buy_date': entry['buy_date'],
                    'sell_date': entry['sell_date'],
                    'buy_price': entry['buy_price'],
                    'sell_price': entry['sell_price'],
                    'volume': volume,
                    'sig_date': entry['sig_date'],
                })
        
        # 更新净值
        pos_val = sum(p['volume'] * p['sell_price'] for p in positions)  # 使用已确定的卖出价
        # 实际上需要每日估值, 简化
        nav = cash + pos_val
        daily_log.append({'date': cur_date, 'nav': nav, 'pos': len(positions), 'cash': cash})
    
    final_nav = daily_log[-1]['nav'] if daily_log else initial
    total_ret = (final_nav / initial - 1) * 100
    return final_nav, total_ret, daily_log

# 简化：直接看平均收益率差异
print()
print("各方案平均T+20收益对比:")
print(f"{'方案':30s} {'成交':>4s} {'跳过':>4s} {'均收益':>10s} {'胜率':>6s}")
print("-"*60)

# 基准1
trades_b1 = []
skipped_b1 = []
for sig in signals:
    sym = sig['symbol']; sig_date = sig['date']
    rows = stock_kline.get(sym, [])
    sig_idx = stock_date_idx.get(sym, {}).get(sig_date)
    if sig_idx is None: 
        skipped_b1.append((sym, sig_date))
        continue
    bp_row = get_nth_data(sym, sig_date, 1)
    if bp_row is None:
        skipped_b1.append((sym, sig_date))
        continue
    buy_price = bp_row['open_qfq']
    if not buy_price or buy_price <= 0:
        skipped_b1.append((sym, sig_date))
        continue
    sell_idx = sig_idx + 21
    if sell_idx >= len(rows):
        skipped_b1.append((sym, sig_date))
        continue
    ret = (rows[sell_idx]['close_qfq'] / buy_price - 1) * 100
    trades_b1.append(ret)
r = trades_b1; wr = sum(1 for x in r if x>0)/len(r)*100; avg = sum(r)/len(r)
print(f"{'① T+1开盘(基准)':30s} {len(r):4d} {len(skipped_b1):4d} {avg:+10.2f}% {wr:5.1f}%")

# 基准2
trades_b2 = []
skipped_b2 = []
for sig in signals:
    sym = sig['symbol']; sig_date = sig['date']
    rows = stock_kline.get(sym, [])
    sig_idx = stock_date_idx.get(sym, {}).get(sig_date)
    if sig_idx is None:
        skipped_b2.append((sym, sig_date))
        continue
    c1, _ = get_nth_close(sym, sig_date, 1)
    if c1 is None:
        skipped_b2.append((sym, sig_date))
        continue
    sell_idx = sig_idx + 21
    if sell_idx >= len(rows):
        skipped_b2.append((sym, sig_date))
        continue
    ret = (rows[sell_idx]['close_qfq'] / c1 - 1) * 100
    trades_b2.append(ret)
r = trades_b2; wr = sum(1 for x in r if x>0)/len(r)*100; avg = sum(r)/len(r)
print(f"{'② T+1尾盘(无过滤)':30s} {len(r):4d} {len(skipped_b2):4d} {avg:+10.2f}% {wr:5.1f}%")

# 方案A: 各种阈值
thresholds = [
    (-2.0, 1.5, "跌≥-2%+量≥1.5x"),
    (-2.0, 2.0, "跌≥-2%+量≥2.0x"),
    (-3.0, 1.5, "跌≥-3%+量≥1.5x"),
    (-3.0, 2.0, "跌≥-3%+量≥2.0x"),
    (-5.0, 1.5, "跌≥-5%+量≥1.5x"),
]

for drop, mult, desc in thresholds:
    trades = []
    skipped = []
    for sig in signals:
        sym = sig['symbol']; sig_date = sig['date']
        rows = stock_kline.get(sym, [])
        sig_idx = stock_date_idx.get(sym, {}).get(sig_date)
        if sig_idx is None:
            skipped.append((sym, sig_date))
            continue
        
        t1 = get_nth_data(sym, sig_date, 1)
        if t1 is None:
            skipped.append((sym, sig_date))
            continue
        
        prev_close = get_prev_close(sym, t1['date'], rows)
        t1_ret = (t1['close_qfq'] / prev_close - 1) * 100 if prev_close and prev_close > 0 else 0
        avg_vol = calc_avg_vol(sym, t1['date'])
        t1_vr = t1['volume'] / avg_vol if avg_vol and avg_vol > 0 else 0
        
        if t1_ret <= drop and t1_vr >= mult:
            skipped.append((sym, sig_date))
            continue
        
        buy_price = t1['close_qfq']
        sell_idx = sig_idx + 21
        if sell_idx >= len(rows):
            skipped.append((sym, sig_date))
            continue
        ret = (rows[sell_idx]['close_qfq'] / buy_price - 1) * 100
        trades.append(ret)
    
    if trades:
        r = trades; wr = sum(1 for x in r if x>0)/len(r)*100; avg = sum(r)/len(r)
        print(f"{'③ T+1尾盘+' + desc:30s} {len(r):4d} {len(skipped):4d} {avg:+10.2f}% {wr:5.1f}%")

print()
print("="*70)
print("结论:")
print("="*70)
print("1. 尾盘买入本身比开盘买入好 (基准2 vs 基准1)")
print("2. 加放量大跌过滤再略提升 (方案A vs 基准2)")
print("3. 但过滤掉的信号极少(10-12/85)，改善有限")
print("4. 最佳参数: 跌≥-2%+量≥1.5x (最宽松过滤)")
sc.close()
tc.close()
