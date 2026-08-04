#!/usr/bin/env python3
"""
回测: 极品B信号 + T+1/T+2放量大跌过滤 + 尾盘买入
对比基准: T+1开盘买入(原始方案)
"""

import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta
import sys

TREND_DB = '/home/ubuntu/databases/trend_picks.db'
STOCK_DB = '/home/ubuntu/databases/Sequoia选股.db'

tc = sqlite3.connect(TREND_DB)
sc = sqlite3.connect(STOCK_DB)
tc.row_factory = sqlite3.Row
sc.row_factory = sqlite3.Row

# ── 1. 获取所有极品B信号 ──
signals = tc.execute("""
    SELECT dp.symbol, dp.date, dp.close_qfq as sig_close, dp.buy_price, 
           dp.vol_ratio, COALESCE(dp.name, '') as name
    FROM daily_picks dp
    WHERE dp.strategy_id = 'premium_b'
    ORDER BY dp.date
""").fetchall()

print(f"总信号: {len(signals)}")

# ── 2. 获取每只股票的日K线数据 ──
# 预加载所有涉及股票的日K线
all_symbols = set(s['symbol'] for s in signals)
print(f"涉及股票: {len(all_symbols)} 只")

stock_kline = {}
for sym in all_symbols:
    rows = sc.execute("""
        SELECT date, close_qfq, volume, open_qfq, high_qfq, low_qfq
        FROM stock_daily WHERE symbol=? AND close_qfq>0
        ORDER BY date
    """, (sym,)).fetchall()
    if rows:
        stock_kline[sym] = rows

# ── 3. 构建日期→索引映射 ──
stock_date_idx = {}
for sym, rows in stock_kline.items():
    stock_date_idx[sym] = {r['date']: i for i, r in enumerate(rows)}

def get_prev_close(sym, date_str, rows):
    """获取前一日收盘价（前复权）"""
    idx = stock_date_idx.get(sym, {}).get(date_str)
    if idx is None or idx < 1:
        return None
    return rows[idx - 1]['close_qfq']

def get_nth_open(sym, date_str, n=1):
    """获取T+n日的开盘价"""
    rows = stock_kline.get(sym, [])
    idx = stock_date_idx.get(sym, {}).get(date_str)
    if idx is None or idx + n >= len(rows):
        return None
    return rows[idx + n]['open_qfq']

def get_nth_close(sym, date_str, n=1):
    """获取T+n日的收盘价"""
    rows = stock_kline.get(sym, [])
    idx = stock_date_idx.get(sym, {}).get(date_str)
    if idx is None or idx + n >= len(rows):
        return None
    return rows[idx + n]['close_qfq']

def get_nth_data(sym, date_str, n=1):
    """获取T+n日的完整数据"""
    rows = stock_kline.get(sym, [])
    idx = stock_date_idx.get(sym, {}).get(date_str)
    if idx is None or idx + n >= len(rows):
        return None
    return rows[idx + n]

def calc_avg_vol(sym, date_str, days=20):
    """计算T日之前days天的日均成交量"""
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

def is_limit_up(prev_close, cur_row):
    """判断是否涨停/一字板"""
    if prev_close is None or prev_close <= 0:
        return False, False
    cur_close = cur_row['close_qfq']
    daily_ret = (cur_close / prev_close - 1) * 100
    # 涨停: 接近10% (普通股9.5%, ST股4.5%+)
    is_up = daily_ret >= 9.5 or daily_ret >= 4.5  # 宽松判断
    # 一字板: 开盘=收盘=最高=最低 (基本没成交量或极低)
    if cur_row['open_qfq'] and cur_row['high_qfq'] and cur_row['low_qfq']:
        is_yizi = (
            abs(cur_row['open_qfq'] - cur_row['close_qfq']) / cur_row['close_qfq'] < 0.005
            and abs(cur_row['high_qfq'] - cur_row['low_qfq']) / cur_row['close_qfq'] < 0.005
            and is_up
        )
    else:
        is_yizi = False
    return is_up, is_yizi

# ── 4. 回测函数 ──
# 尝试多种"放量大跌"阈值
thresholds = [
    # (跌%, 量比倍数, 描述)
    (-3.0, 1.5, "跌≥-3%+量≥1.5x"),
    (-3.0, 1.8, "跌≥-3%+量≥1.8x"),
    (-3.0, 2.0, "跌≥-3%+量≥2.0x"),
    (-4.0, 1.5, "跌≥-4%+量≥1.5x"),
    (-5.0, 1.5, "跌≥-5%+量≥1.5x"),
    (-5.0, 2.0, "跌≥-5%+量≥2.0x"),
    (-2.0, 1.5, "跌≥-2%+量≥1.5x"),
    (-2.0, 2.0, "跌≥-2%+量≥2.0x"),
]

def run_backtest(signals, entry_rule="baseline", drop_thresh=-3.0, vol_mult=1.5):
    """
    回测一个信号集
    entry_rule:
      'baseline'    - T+1开盘买入(原始)
      'close_t1'    - T+1尾盘买入, 如果T+1放量大跌则跳过
      'close_t1_t2' - T+1尾盘买入, 放量大跌/一字板则看T+2
    """
    trades = []
    skipped = []
    
    for sig in signals:
        sym = sig['symbol']
        sig_date = sig['date']
        rows = stock_kline.get(sym, [])
        sig_idx = stock_date_idx.get(sym, {}).get(sig_date)
        
        if sig_idx is None:
            skipped.append((sym, sig_date, '无日K线数据'))
            continue
        
        if entry_rule == 'baseline':
            # T+1开盘买入
            bp_row = get_nth_data(sym, sig_date, 1)  # T+1
            if bp_row is None:
                skipped.append((sym, sig_date, '无T+1数据'))
                continue
            buy_price = bp_row['open_qfq']
            buy_date = bp_row['date']
            if not buy_price or buy_price <= 0:
                skipped.append((sym, sig_date, 'T+1开盘价无效'))
                continue
            
            # 持有20个交易日 → 从T+1到T+20收盘
            sell_idx = sig_idx + 21  # T+1到T+21收盘(T+20持有)
            if sell_idx >= len(rows):
                skipped.append((sym, sig_date, f'无T+20数据(T+{sell_idx-sig_idx})'))
                continue
            sell_price = rows[sell_idx]['close_qfq']
            sell_date = rows[sell_idx]['date']
            
            ret = (sell_price / buy_price - 1) * 100
            trades.append({
                'symbol': sym, 'name': sig['name'], 'sig_date': sig_date,
                'buy_date': buy_date, 'buy_price': buy_price,
                'sell_date': sell_date, 'sell_price': sell_price,
                'return_pct': round(ret, 2), 'entry_rule': 'T+1开盘'
            })
            
        elif entry_rule == 'close_t1':
            # T+1尾盘买入, 放量大跌则跳过
            t1 = get_nth_data(sym, sig_date, 1)
            if t1 is None:
                skipped.append((sym, sig_date, '无T+1数据'))
                continue
            
            # 检查T+1放量大跌
            prev_close = get_prev_close(sym, t1['date'], rows)
            if prev_close and prev_close > 0:
                t1_ret = (t1['close_qfq'] / prev_close - 1) * 100
            else:
                t1_ret = 0
            
            avg_vol = calc_avg_vol(sym, t1['date'])
            t1_vr = t1['volume'] / avg_vol if avg_vol and avg_vol > 0 else 0
            
            is_big_drop = t1_ret <= drop_thresh and t1_vr >= vol_mult
            
            if is_big_drop:
                skipped.append((sym, sig_date, f'T+1放量大跌({t1_ret:.1f}%,量比{t1_vr:.2f})'))
                continue
            
            buy_price = t1['close_qfq']  # 尾盘买入=T+1收盘价
            buy_date = t1['date']
            
            # 持有20个交易日 → 从T+1到T+20收盘
            sell_idx = sig_idx + 21
            if sell_idx >= len(rows):
                skipped.append((sym, sig_date, f'无T+20数据'))
                continue
            sell_price = rows[sell_idx]['close_qfq']
            sell_date = rows[sell_idx]['date']
            
            ret = (sell_price / buy_price - 1) * 100
            trades.append({
                'symbol': sym, 'name': sig['name'], 'sig_date': sig_date,
                'buy_date': buy_date, 'buy_price': buy_price,
                'sell_date': sell_date, 'sell_price': sell_price,
                'return_pct': round(ret, 2), 'entry_rule': 'T+1尾盘'
            })
            
        elif entry_rule == 'close_t1_t2':
            # T+1: 检查放量大跌→跳过; 一字板→看T+2; 否则尾盘买入
            t1 = get_nth_data(sym, sig_date, 1)
            if t1 is None:
                skipped.append((sym, sig_date, '无T+1数据'))
                continue
            
            prev_close_t1 = get_prev_close(sym, t1['date'], rows)
            if prev_close_t1 and prev_close_t1 > 0:
                t1_ret = (t1['close_qfq'] / prev_close_t1 - 1) * 100
            else:
                t1_ret = 0
            
            avg_vol_t1 = calc_avg_vol(sym, t1['date'])
            t1_vr = t1['volume'] / avg_vol_t1 if avg_vol_t1 and avg_vol_t1 > 0 else 0
            t1_limit_up, t1_yizi = is_limit_up(prev_close_t1, t1)
            
            t1_big_drop = t1_ret <= drop_thresh and t1_vr >= vol_mult
            
            if not t1_big_drop and not t1_yizi:
                # T+1正常, 尾盘买入
                buy_price = t1['close_qfq']
                buy_date = t1['date']
                sell_idx = sig_idx + 21
                if sell_idx >= len(rows):
                    skipped.append((sym, sig_date, '无T+20数据'))
                    continue
                sell_price = rows[sell_idx]['close_qfq']
                sell_date = rows[sell_idx]['date']
                ret = (sell_price / buy_price - 1) * 100
                trades.append({
                    'symbol': sym, 'name': sig['name'], 'sig_date': sig_date,
                    'buy_date': buy_date, 'buy_price': buy_price,
                    'sell_date': sell_date, 'sell_price': sell_price,
                    'return_pct': round(ret, 2), 'entry_rule': 'T+1尾盘'
                })
            else:
                # T+1放量大跌 或 一字板 → 看T+2
                t2 = get_nth_data(sym, sig_date, 2)
                if t2 is None:
                    skipped.append((sym, sig_date, f'无T+2数据(t1_big_drop={t1_big_drop},t1_yizi={t1_yizi})'))
                    continue
                
                prev_close_t2 = get_prev_close(sym, t2['date'], rows)
                if prev_close_t2 and prev_close_t2 > 0:
                    t2_ret = (t2['close_qfq'] / prev_close_t2 - 1) * 100
                else:
                    t2_ret = 0
                
                avg_vol_t2 = calc_avg_vol(sym, t2['date'])
                t2_vr = t2['volume'] / avg_vol_t2 if avg_vol_t2 and avg_vol_t2 > 0 else 0
                t2_big_drop = t2_ret <= drop_thresh and t2_vr >= vol_mult
                
                if t2_big_drop:
                    skipped.append((sym, sig_date, f'T+2放量大跌({t2_ret:.1f}%,量比{t2_vr:.2f})'))
                    continue
                
                buy_price = t2['close_qfq']  # T+2尾盘买入
                buy_date = t2['date']
                sell_idx = sig_idx + 22  # 从T+2到T+21收盘(T+20持有日)
                if sell_idx >= len(rows):
                    skipped.append((sym, sig_date, '无T+21数据'))
                    continue
                sell_price = rows[sell_idx]['close_qfq']
                sell_date = rows[sell_idx]['date']
                ret = (sell_price / buy_price - 1) * 100
                trades.append({
                    'symbol': sym, 'name': sig['name'], 'sig_date': sig_date,
                    'buy_date': buy_date, 'buy_price': buy_price,
                    'sell_date': sell_date, 'sell_price': sell_price,
                    'return_pct': round(ret, 2), 'entry_rule': 'T+2尾盘(因T+1一字板/放量大跌)'
                })
    
    return trades, skipped


# ── 5. 运行回测 ──

# 基准: T+1开盘买入
print("\n" + "="*80)
print("基准: T+1开盘买入")
print("="*80)
trades_baseline, skipped_baseline = run_backtest(signals, 'baseline')
rets = [t['return_pct'] for t in trades_baseline]
win_rate = sum(1 for r in rets if r > 0) / len(rets) * 100 if rets else 0
avg_ret = sum(rets) / len(rets) if rets else 0
print(f"  成交: {len(trades_baseline)}  跳过: {len(skipped_baseline)}")
print(f"  平均T+20收益: {avg_ret:+.2f}%  胜率: {win_rate:.1f}%")
# 展示输家
losers = sorted(trades_baseline, key=lambda x: x['return_pct'])[:5]
loser_str = ', '.join(f"{t['symbol']}({t['name']}) {t['return_pct']:+.1f}%" for t in losers)
print(f"  最大输家: {loser_str}")
winners = sorted(trades_baseline, key=lambda x: x['return_pct'], reverse=True)[:5]
winner_str = ', '.join(f"{t['symbol']}({t['name']}) {t['return_pct']:+.1f}%" for t in winners)
print(f"  最大赢家: {winner_str}")

# 所有阈值方案
print("\n" + "="*80)
print("方案A: T+1尾盘买入, 放量大跌则跳过")
print("="*80)
for drop, mult, desc in thresholds:
    trades, skipped = run_backtest(signals, 'close_t1', drop, mult)
    if not trades:
        print(f"  {desc:20s}: 全部跳过(0成交)")
        continue
    rets = [t['return_pct'] for t in trades]
    win_rate = sum(1 for r in rets if r > 0) / len(rets) * 100
    avg_ret = sum(rets) / len(rets)
    print(f"  {desc:20s}: 成交{len(trades):2d} 跳过{len(skipped):2d} 均收益{avg_ret:+.2f}% 胜率{win_rate:.1f}%")

print("\n" + "="*80)
print("方案B: T+1尾盘(放量大跌跳过/一字板看T+2), T+2尾盘(放量大跌跳过)")
print("="*80)
for drop, mult, desc in thresholds:
    trades, skipped = run_backtest(signals, 'close_t1_t2', drop, mult)
    if not trades:
        print(f"  {desc:20s}: 全部跳过(0成交)")
        continue
    rets = [t['return_pct'] for t in trades]
    win_rate = sum(1 for r in rets if r > 0) / len(rets) * 100
    avg_ret = sum(rets) / len(rets)
    t1_entries = sum(1 for t in trades if 'T+1' in t['entry_rule'])
    t2_entries = sum(1 for t in trades if 'T+2' in t['entry_rule'])
    t2_skipped = sum(1 for s in skipped if 'T+2' in s[2])
    t1_skipped_bigdrop = sum(1 for s in skipped if '一字板' in s[2] or '放量大跌' in s[2])
    print(f"  {desc:20s}: 成交{len(trades):2d}(T+1:{t1_entries} T+2:{t2_entries}) 跳过{len(skipped):2d}(T+1放量大跌/一字板) 均收益{avg_ret:+.2f}% 胜率{win_rate:.1f}%")

# ── 6. 详细分析最佳阈值 ──
print("\n" + "="*80)
print("详细分析: 跌≥-3%+量≥1.5x 方案 (方案B)")
print("="*80)
trades_detail, skipped_detail = run_backtest(signals, 'close_t1_t2', -3.0, 1.5)
rets = [t['return_pct'] for t in trades_detail]
win_rate = sum(1 for r in rets if r > 0) / len(rets) * 100 if rets else 0
avg_ret = sum(rets) / len(rets) if rets else 0

print(f"总信号: {len(signals)}")
print(f"成交: {len(trades_detail)}, 跳过: {len(skipped_detail)}")
print(f"平均T+20收益: {avg_ret:+.2f}%  胜率: {win_rate:.1f}%")

print("\n跳过的信号详情:")
for sym, dt, reason in skipped_detail:
    print(f"  {sym} {dt}: {reason}")

print("\n成交信号详情(输家):")
for t in sorted(trades_detail, key=lambda x: x['return_pct'])[:8]:
    print(f"  {t['symbol']}({t['name']}) 信号{t['sig_date']} {t['entry_rule']} {t['buy_date']} 收益{t['return_pct']:+.2f}%")

print("\n成交信号详情(赢家Top8):")
for t in sorted(trades_detail, key=lambda x: x['return_pct'], reverse=True)[:8]:
    print(f"  {t['symbol']}({t['name']}) 信号{t['sig_date']} {t['entry_rule']} {t['buy_date']} 收益{t['return_pct']:+.2f}%")

# ── 7. 对比基准被跳过的信号在方案B中表现 ──
print("\n" + "="*80)
print("基准中亏损的信号, 在方案B中被过滤掉的:")
print("="*80)
baseline_losers = [t for t in trades_baseline if t['return_pct'] < 0]
baseline_loser_symbols = {(t['symbol'], t['sig_date']) for t in baseline_losers}

filtered_out = []
for sym, dt, reason in skipped_detail:
    if (sym, dt) in baseline_loser_symbols:
        baselines = [t for t in trades_baseline if t['symbol'] == sym and t['sig_date'] == dt]
        if baselines:
            filtered_out.append((sym, dt, reason, baselines[0]['return_pct']))

print(f"基准亏损信号数: {len(baseline_losers)}")
print(f"方案B成功过滤掉的亏损信号: {len(filtered_out)}")
for sym, dt, reason, ret in filtered_out:
    print(f"  {sym} {dt}: 基准{ret:+.2f}% → {reason}")

# 误杀的赢家
print("\n基准中赚钱的信号, 在方案B中被误杀的:")
filtered_winners = []
for sym, dt, reason in skipped_detail:
    if (sym, dt) in {(t['symbol'], t['sig_date']) for t in trades_baseline if t['return_pct'] > 0}:
        baselines = [t for t in trades_baseline if t['symbol'] == sym and t['sig_date'] == dt]
        if baselines:
            filtered_winners.append((sym, dt, reason, baselines[0]['return_pct']))

print(f"方案B误杀的盈利信号: {len(filtered_winners)}")
for sym, dt, reason, ret in sorted(filtered_winners, key=lambda x: x[3], reverse=True)[:10]:
    print(f"  {sym} {dt}: 基准{ret:+.2f}% → {reason}")

tc.close()
sc.close()
