#!/usr/bin/env python3
"""
波段启动策略 — 全量回测 (按股迭代版)
基于抖音"明月夜"视频的三个必要条件 + 两个加分条件
"""
import sqlite3, time
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

DB = '/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db'
START = '2025-01-01'  # 缩到1年
END = '2026-07-16'
MIN_PRICE = 5.0
MAX_PRICE = 500.0

# 参数
WASH_MIN_DROP, WASH_MAX_DROP = 5.0, 25.0
WASH_VR_MAX = 0.85       # 洗盘期量比上限
BREAK_VR_MIN = 1.5       # 放量阳线量比下限
CALLBACK_MAX_DROP = 10.0  # 回调最大跌幅
CALLBACK_VR_MAX = 1.0     # 回调缩量上限

HOLD_DAYS = [5, 10, 20]
STOP_LOSS = 0.07
TAKE_PROFIT = 0.15

conn = sqlite3.connect(DB)
t0 = time.time()

print(f"波段启动策略回测: {START} ~ {END}")
print("=" * 50)

# 获取所有非ST股票
symbols = conn.execute("""
    SELECT DISTINCT d.symbol FROM stock_daily d
    JOIN stock_basics b ON d.symbol=b.symbol
    WHERE d.date = (SELECT MAX(d2.date) FROM stock_daily d2 WHERE d2.symbol=d.symbol)
      AND d.date >= date('now', '-5 days')
      AND b.name NOT LIKE '%ST%' AND b.name NOT LIKE '%退%'
      AND b.close > 0
    ORDER BY d.symbol
""").fetchall()
symbols = [r[0] for r in symbols]
print(f"股票数: {len(symbols)}")

# ── 主循环：按股处理 ──
all_signals = []
stock_count = 0
signal_count = 0

for sym in symbols:
    stock_count += 1
    if stock_count % 500 == 0:
        print(f"  进度: {stock_count}/{len(symbols)} 信号: {signal_count} 耗时: {time.time()-t0:.0f}s")
    
    # 加载单只股票数据
    grp = pd.read_sql(
        "SELECT date, close_qfq as close, volume, open_qfq as open "
        "FROM stock_daily WHERE symbol=? AND date>=? AND date<=? AND close_qfq>0 AND volume>0 "
        "ORDER BY date",
        conn, params=(sym, START, END)
    )
    if len(grp) < 60:
        continue
    
    # ── 计算特征 ──
    grp['avgv_20'] = grp['volume'].rolling(20, min_periods=10).mean()
    grp['vr'] = grp['volume'] / grp['avgv_20']
    grp['pct'] = grp['close'].pct_change(1) * 100
    grp['is_yang'] = (grp['close'] > grp['open']).astype(int)
    grp['yang_r10'] = grp['is_yang'].rolling(10, min_periods=5).mean()
    grp['vr_20avg'] = grp['vr'].rolling(20, min_periods=10).mean()
    grp['body_pct'] = abs(grp['close'] - grp['open']) / grp['open'] * 100
    
    # 连续阳线
    grp['consec_yang'] = 0
    for i in range(len(grp)):
        if grp.iloc[i]['is_yang'] == 1:
            grp.at[grp.index[i], 'consec_yang'] = (grp.iloc[i-1]['consec_yang'] + 1) if i > 0 else 1
        else:
            grp.at[grp.index[i], 'consec_yang'] = 0
    
    # 各周期跌幅
    grp['drop_20'] = grp['close'].pct_change(20) * 100
    grp['drop_30'] = grp['close'].pct_change(30) * 100
    
    # ── 扫描信号 ──
    for i in range(35, len(grp)):
        row = grp.iloc[i]
        if row['close'] < MIN_PRICE or row['close'] > MAX_PRICE:
            continue
        
        # 条件①: 洗盘吸筹
        drop_20 = row['drop_20'] if pd.notna(row['drop_20']) else 0
        drop_30 = row['drop_30'] if pd.notna(row['drop_30']) else 0
        vr_20avg = row['vr_20avg'] if pd.notna(row['vr_20avg']) else 99
        
        wash_ok = False
        wash_type = ''
        # 20天跌5-25% + 量比低
        if WASH_MIN_DROP <= -drop_20 <= WASH_MAX_DROP and vr_20avg < WASH_VR_MAX:
            wash_ok = True
            wash_type = '20d'
        # 30天跌8-25% + 量比低
        elif WASH_MIN_DROP <= -drop_30 <= WASH_MAX_DROP and vr_20avg < WASH_VR_MAX:
            wash_ok = True
            wash_type = '30d'
        if not wash_ok:
            continue
        
        # 条件②: 放量阳线（前5天内）
        yang_found = False
        yang_idx = -1
        yang_vr = 0
        for j in range(max(35, i-5), i):
            r2 = grp.iloc[j]
            if r2['is_yang'] == 1 and pd.notna(r2['vr']) and r2['vr'] >= BREAK_VR_MIN:
                yang_found = True
                yang_idx = j
                yang_vr = r2['vr']
                break
        if not yang_found:
            continue
        
        # 条件③: 回调缩量（放量阳线后回调<10%且缩量）
        cb_window = grp.iloc[yang_idx:i+1]
        if len(cb_window) < 2:
            continue
        cb_high = cb_window['close'].max()
        cb_drop = (cb_high - row['close']) / cb_high * 100
        if cb_drop > CALLBACK_MAX_DROP or cb_drop < 0:
            continue
        if pd.notna(row['vr']) and row['vr'] > CALLBACK_VR_MAX:
            continue
        
        # 加分条件
        yang_r10 = row['yang_r10'] if pd.notna(row['yang_r10']) else 0
        bonus_yang = yang_r10 >= 0.5
        bonus_consec = 3 <= row['consec_yang'] <= 7 and row['body_pct'] < 3.0
        
        all_signals.append({
            'sym': sym, 'date': row['date'], 'price': row['close'],
            'vr': round(row['vr'], 2), 'wash': wash_type,
            'drop20': round(drop_20, 1),
            'yang_vr': round(yang_vr, 1), 'cb_drop': round(cb_drop, 1),
            'yang_r10': round(yang_r10, 3), 'consec_yang': int(row['consec_yang']),
            'bonus': (1 if bonus_yang else 0) + (1 if bonus_consec else 0),
        })
        signal_count += 1

print(f"\n信号扫描完成: {signal_count} 个信号, 耗时 {time.time()-t0:.0f}s")

if signal_count == 0:
    conn.close()
    exit()

sig_df = pd.DataFrame(all_signals)

# ── 回测 ──
print("\n回测中...")
# 对每个信号，加载其后的K线数据
results = []
for _, sig in sig_df.iterrows():
    sym = sig['sym']
    entry_date = sig['date']
    entry_price = sig['price']
    bonus = sig['bonus']
    
    fdf = pd.read_sql(
        "SELECT date, close_qfq as close FROM stock_daily WHERE symbol=? AND date>? AND close_qfq>0 ORDER BY date LIMIT 30",
        conn, params=(sym, entry_date)
    )
    future = fdf.sort_values('date')
    if len(future) == 0:
        continue
    
    for hold in HOLD_DAYS:
        exit_price = None
        exit_date = None
        exit_reason = 'hold_end'
        
        for j in range(min(hold, len(future))):
            frow = future.iloc[j]
            cp = frow['close']
            if cp < entry_price * (1 - STOP_LOSS):
                exit_price = cp; exit_date = frow['date']; exit_reason = 'sl'; break
            if cp > entry_price * (1 + TAKE_PROFIT):
                exit_price = cp; exit_date = frow['date']; exit_reason = 'tp'; break
        
        if exit_price is None and hold <= len(future):
            exit_price = future.iloc[hold-1]['close']
            exit_date = future.iloc[hold-1]['date']
        elif exit_price is None:
            continue
        
        ret = (exit_price - entry_price) / entry_price * 100
        results.append({
            'sym': sym, 'entry': entry_date, 'exit': exit_date,
            'hold': hold, 'ret': round(ret, 2), 'bonus': bonus, 'reason': exit_reason
        })

res_df = pd.DataFrame(results)
print(f"回测完成: {len(res_df)} 笔交易, 耗时 {time.time()-t0:.0f}s")

# ── 结果输出 ──
print(f"\n{'='*50}")
print(f"【波段启动策略回测 {START}~{END}】")
print(f"总信号: {signal_count} | 总交易: {len(res_df)}")
print(f"信号分布(加分): {sig_df['bonus'].value_counts().to_dict()}")
print('='*50)

for hold in HOLD_DAYS:
    sub = res_df[res_df['hold'] == hold]
    if len(sub) == 0: continue
    wr = len(sub[sub['ret'] > 0]) / len(sub) * 100
    print(f"\nT+{hold}  {len(sub)}笔 胜率{wr:.1f}% 均值{sub['ret'].mean():+.2f}% 中位{sub['ret'].median():+.2f}%")
    print(f"       最大{sub['ret'].max():+.2f}% 最小{sub['ret'].min():+.2f}% Sharpe:{sub['ret'].mean()/max(sub['ret'].std(),0.01):.2f}")
    tp = len(sub[sub['reason']=='tp']); sl = len(sub[sub['reason']=='sl']); he = len(sub[sub['reason']=='hold_end'])
    print(f"       止盈{tp} 止损{sl} 到期{he}")
    
    for b in [0, 1, 2]:
        sb = sub[sub['bonus'] == b]
        if len(sb) > 0:
            wrb = len(sb[sb['ret'] > 0]) / len(sb) * 100
            print(f"  bonus={b}({len(sb)}笔): 胜率{wrb:.1f}% 均{sb['ret'].mean():+.2f}%")

# 按年
res_df['yr'] = res_df['entry'].str[:4]
print("\n--- 按年(T+5) ---")
for yr in sorted(res_df[res_df['hold']==5]['yr'].unique()):
    sub = res_df[(res_df['hold']==5) & (res_df['yr']==yr)]
    wr = len(sub[sub['ret']>0])/len(sub)*100
    print(f"  {yr}: {len(sub)}笔 胜率{wr:.1f}% 均{sub['ret'].mean():+.2f}%")

# Top/Bottom
print("\n--- 最佳/最差(T+5) ---")
t5 = res_df[res_df['hold']==5].nlargest(3, 'ret')
for _,r in t5.iterrows(): print(f"  +{r['ret']:+.1f}% {r['sym']} {r['entry']} ({r['reason']})")
t5 = res_df[res_df['hold']==5].nsmallest(3, 'ret')
for _,r in t5.iterrows(): print(f"  {r['ret']:+.1f}% {r['sym']} {r['entry']} ({r['reason']})")

conn.close()
print(f"\n总耗时: {time.time()-t0:.0f}s ✓")
