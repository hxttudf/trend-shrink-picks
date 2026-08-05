#!/usr/bin/env python3
"""
波段启动策略 — 全量回测
基于抖音"明月夜"视频的三个必要条件 + 两个加分条件

必要条件:
  ① 洗盘吸筹: 10-30天内价格跌5-20%，缩量（量比<0.8）
  ② 放量阳线: close>open 且 volume > 1.5×20日均量
  ③ 回调缩量: 放量后1-5天回调<10%，缩量（量比<1.0）

加分条件:
  ④ 阳线多于阴线（近10天阳线占比>50%）
  ⑤ 连续小阳线（最近3-5天实体小的阳线）

买入: 满足①②③条件的回调日收盘（条件③触发日）
卖出: T+5/T+10/T+20 或 止损/止盈
"""
import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

# ── 配置 ──
DB = '/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db'
START_DATE = '2024-01-01'
END_DATE = '2026-07-16'
MIN_PRICE = 5.0   # 最低价过滤（ST/低价股）
MAX_PRICE = 500.0  # 最高价过滤
MIN_VOLUME = 100000  # 最小成交量

# ── 参数 ──
WASH_MAX_DAYS = 30     # 洗盘最大天数
WASH_MIN_DROP = 5.0    # 洗盘最小跌幅%
WASH_MAX_DROP = 25.0   # 洗盘最大跌幅%
WASH_VOL_RATIO = 0.8   # 洗盘期量比上限
BREAK_VOL_RATIO = 1.5  # 放量阳线量比下限
PULLBACK_MAX_DAYS = 5  # 回调最大天数
PULLBACK_MAX_DROP = 10.0  # 回调最大跌幅%
PULLBACK_VOL_RATIO = 1.0  # 回调缩量比上限
YANG_RATIO_MIN = 0.5   # 阳线占比下限

HOLD_DAYS = [5, 10, 20]
STOP_LOSS = 0.07  # 止损-7%
TAKE_PROFIT = 0.15  # 止盈+15%

conn = sqlite3.connect(DB)

print(f"波段启动策略回测: {START_DATE} ~ {END_DATE}")
print("=" * 60)

# ── 加载数据 ──
print("\n加载数据...")
df = pd.read_sql(
    "SELECT symbol, date, close_qfq as close, volume, open_qfq as open "
    "FROM stock_daily WHERE date >= ? AND date <= ? AND close_qfq > 0 AND volume > 0",
    conn, params=(START_DATE, END_DATE)
)
print(f"  总行数: {len(df):,}")
print(f"  股票数: {df['symbol'].nunique():,}")

# ── 特征计算 ──
print("\n计算特征...")
df = df.sort_values(['symbol', 'date']).reset_index(drop=True)

# 20日均量
df['avgv_20'] = df.groupby('symbol')['volume'].transform(
    lambda x: x.rolling(20, min_periods=10).mean()
)
df['vol_ratio'] = df['volume'] / df['avgv_20']

# 5日均线
df['ma5'] = df.groupby('symbol')['close'].transform(
    lambda x: x.rolling(5, min_periods=3).mean()
)

# 涨跌幅
df['pct_chg'] = df.groupby('symbol')['close'].transform(lambda x: x.pct_change(1) * 100)

# 是否为阳线
df['is_yang'] = (df['close'] > df['open']).astype(int)

# N天内阳线占比
df['yang_ratio_10'] = df.groupby('symbol')['is_yang'].transform(
    lambda x: x.rolling(10, min_periods=5).mean()
)

# N天跌幅
for n in [10, 20, 30]:
    df[f'drop_{n}d'] = df.groupby('symbol')['close'].transform(
        lambda x: (x - x.shift(n)) / x.shift(n) * 100
    )

# N天量比均值
for n in [10, 20, 30]:
    df[f'avg_vr_{n}d'] = df.groupby('symbol')['vol_ratio'].transform(
        lambda x: x.rolling(n, min_periods=5).mean()
    )

# 最近N根K线的实体大小（(close-open)/open %）
df['body_pct'] = abs(df['close'] - df['open']) / df['open'] * 100

# 连续阳线计数
def count_consecutive_yang(s):
    """计算最近连续阳线数（从最后一天往前数）"""
    cnt = 0
    for v in reversed(s.values):
        if v == 1:
            cnt += 1
        else:
            break
    return cnt

consec_yang = df.groupby('symbol')['is_yang'].rolling(10, min_periods=1).apply(
    lambda x: count_consecutive_yang(x) if len(x) > 0 else 0
).reset_index(0, drop=True)
df['consec_yang'] = consec_yang

print("  特征计算完成")

# ── 信号扫描 ──
print("\n扫描信号...")
signals = []

# 按股票分组处理
for sym, grp in df.groupby('symbol'):
    grp = grp.sort_values('date').reset_index(drop=True)
    if len(grp) < 60:
        continue
    
    for i in range(60, len(grp)):
        row = grp.iloc[i]
        
        # 基础过滤
        if row['close'] < MIN_PRICE or row['close'] > MAX_PRICE:
            continue
        if row['volume'] < MIN_VOLUME:
            continue
        
        # 窗口数据
        window = grp.iloc[i-30:i+1]
        
        # 条件①: 洗盘吸筹
        # 近10-30天内价格下跌5-25%
        drop_10d = row['drop_10d'] if pd.notna(row['drop_10d']) else 0
        drop_20d = row['drop_20d'] if pd.notna(row['drop_20d']) else 0
        drop_30d = row['drop_30d'] if pd.notna(row['drop_30d']) else 0
        
        # 洗盘期量比均值低
        avg_vr_20d = row['avg_vr_20d'] if pd.notna(row['avg_vr_20d']) else 99
        
        wash_ok = False
        wash_type = ''
        # 情形A: 10天跌5-20%，量比<0.8
        if WASH_MIN_DROP <= -drop_10d <= WASH_MAX_DROP and avg_vr_20d < WASH_VOL_RATIO:
            wash_ok = True
            wash_type = '10d缩量跌'
        # 情形B: 20天跌8-25%，量比<0.8
        elif WASH_MIN_DROP <= -drop_20d <= WASH_MAX_DROP and avg_vr_20d < WASH_VOL_RATIO:
            wash_ok = True
            wash_type = '20d缩量跌'
        # 情形C: 30天跌10-25%，量比<0.8
        elif WASH_MIN_DROP <= -drop_30d <= WASH_MAX_DROP and avg_vr_20d < WASH_VOL_RATIO:
            wash_ok = True
            wash_type = '30d缩量跌'
        
        if not wash_ok:
            continue
        
        # 条件②: 放量阳线（在洗盘后的某一天）
        yang_found = False
        yang_idx = -1
        yang_vol_ratio = 0
        
        # 在最近5天内找放量阳线
        for j in range(max(0, i-5), i):
            r2 = grp.iloc[j]
            if (r2['is_yang'] == 1 and 
                pd.notna(r2['vol_ratio']) and 
                r2['vol_ratio'] >= BREAK_VOL_RATIO):
                yang_found = True
                yang_idx = j
                yang_vol_ratio = r2['vol_ratio']
                break
        
        if not yang_found:
            continue
        
        # 条件③: 回调缩量（放量阳线后到当前）
        callback_window = grp.iloc[yang_idx:i+1]
        if len(callback_window) < 2:
            continue
        
        callback_high = callback_window['close'].max()
        callback_drop = (callback_high - row['close']) / callback_high * 100
        
        # 回调不能太大（<10%），且当前缩量
        if callback_drop > PULLBACK_MAX_DROP:
            continue
        if pd.notna(row['vol_ratio']) and row['vol_ratio'] > PULLBACK_VOL_RATIO:
            continue
        if callback_drop < 0:
            continue  # 没有回调（还在涨）也不是我们要的
        
        # 加分条件④: 阳线多于阴线
        yang_ratio = row['yang_ratio_10'] if pd.notna(row['yang_ratio_10']) else 0
        bonus_yang = yang_ratio >= YANG_RATIO_MIN
        
        # 加分条件⑤: 连续小阳线
        bonus_consec = 3 <= row['consec_yang'] <= 7 and row['body_pct'] < 3.0
        
        bonus_score = (1 if bonus_yang else 0) + (1 if bonus_consec else 0)
        
        signals.append({
            'symbol': sym,
            'date': row['date'],
            'price': row['close'],
            'vol_ratio': row['vol_ratio'],
            'wash_type': wash_type,
            'wash_drop_20d': round(drop_20d, 2),
            'yang_vol_ratio': round(yang_vol_ratio, 2),
            'callback_drop': round(callback_drop, 2),
            'yang_ratio_10': round(yang_ratio, 3),
            'consec_yang': row['consec_yang'],
            'bonus_score': bonus_score,
            'ma5': row['ma5'],
        })

sig_df = pd.DataFrame(signals)
print(f"  总信号: {len(sig_df)}")

if len(sig_df) == 0:
    print("无信号，退出")
    conn.close()
    exit()

# ── 查看信号分布 ──
print(f"\n加分条件分布:")
print(sig_df['bonus_score'].value_counts().sort_index())

# ── 回测 ──
print(f"\n回测持仓（T+5/T+10/T+20 + 止损-7%/止盈+15%）...\n")

results = []
total_sigs = len(sig_df)

for idx, sig in sig_df.iterrows():
    if idx % 1000 == 0 and idx > 0:
        print(f"  进度: {idx}/{total_sigs}")
    
    sym = sig['symbol']
    entry_date = sig['date']
    entry_price = sig['price']
    
    # 获取后续数据
    future = df[(df['symbol'] == sym) & (df['date'] > entry_date)].sort_values('date')
    if len(future) == 0:
        continue
    
    bonus = sig['bonus_score']
    
    for hold in HOLD_DAYS:
        exit_date = None
        exit_price = None
        exit_reason = 'hold_end'
        max_price = entry_price
        
        for j in range(min(hold, len(future))):
            frow = future.iloc[j]
            current_price = frow['close']
            
            # 更新持仓期间最高价
            if current_price > max_price:
                max_price = current_price
            
            # 止损：跌破入场价的(1-STOP_LOSS)
            if current_price < entry_price * (1 - STOP_LOSS):
                exit_price = current_price
                exit_date = frow['date']
                exit_reason = 'stop_loss'
                break
            
            # 止盈：超过入场价的(1+TAKE_PROFIT)
            if current_price > entry_price * (1 + TAKE_PROFIT):
                exit_price = current_price
                exit_date = frow['date']
                exit_reason = 'take_profit'
                break
        
        if exit_price is None:
            # 持仓到期
            if hold <= len(future):
                frow = future.iloc[hold - 1]
                exit_price = frow['close']
                exit_date = frow['date']
            else:
                continue
        
        ret = (exit_price - entry_price) / entry_price * 100
        
        results.append({
            'symbol': sym,
            'entry_date': entry_date,
            'exit_date': exit_date,
            'hold_days': hold,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'return_pct': round(ret, 2),
            'bonus_score': bonus,
            'exit_reason': exit_reason,
        })

res_df = pd.DataFrame(results)
if len(res_df) == 0:
    print("无回测结果")
    conn.close()
    exit()

# ── 结果汇总 ──
print("\n" + "=" * 60)
print(f"【波段启动策略 — 全量回测结果】")
print(f"  回测区间: {START_DATE} ~ {END_DATE}")
print(f"  总信号数: {total_sigs}")
print(f"  总交易数: {len(res_df)}")
print("=" * 60)

for hold in HOLD_DAYS:
    sub = res_df[res_df['hold_days'] == hold]
    if len(sub) == 0:
        continue
    
    win_rate = len(sub[sub['return_pct'] > 0]) / len(sub) * 100
    avg_ret = sub['return_pct'].mean()
    median_ret = sub['return_pct'].median()
    max_ret = sub['return_pct'].max()
    min_ret = sub['return_pct'].min()
    std_ret = sub['return_pct'].std()
    
    # 止盈止损分布
    tp = len(sub[sub['exit_reason'] == 'take_profit'])
    sl = len(sub[sub['exit_reason'] == 'stop_loss'])
    hold_end = len(sub[sub['exit_reason'] == 'hold_end'])
    
    # 按加分条件分层
    sub_bonus0 = sub[sub['bonus_score'] == 0]
    sub_bonus1 = sub[sub['bonus_score'] == 1]
    sub_bonus2 = sub[sub['bonus_score'] == 2]
    
    print(f"\nT+{hold} | 交易{len(sub)}笔 | 胜率{win_rate:.1f}% | 均收益{avg_ret:+.2f}% | 中位数{median_ret:+.2f}%")
    print(f"        | 最大{max_ret:+.2f}% | 最小{min_ret:+.2f}% | 标准差{std_ret:.2f}")
    print(f"        | 止盈{tp}笔 | 止损{sl}笔 | 到期{hold_end}笔")
    
    if len(sub_bonus0) > 0:
        wr0 = len(sub_bonus0[sub_bonus0['return_pct'] > 0]) / len(sub_bonus0) * 100
        print(f"  → 加分0分({len(sub_bonus0)}笔): 胜率{wr0:.1f}% 均收益{sub_bonus0['return_pct'].mean():+.2f}%")
    if len(sub_bonus1) > 0:
        wr1 = len(sub_bonus1[sub_bonus1['return_pct'] > 0]) / len(sub_bonus1) * 100
        print(f"  → 加分1分({len(sub_bonus1)}笔): 胜率{wr1:.1f}% 均收益{sub_bonus1['return_pct'].mean():+.2f}%")
    if len(sub_bonus2) > 0:
        wr2 = len(sub_bonus2[sub_bonus2['return_pct'] > 0]) / len(sub_bonus2) * 100
        print(f"  → 加分2分({len(sub_bonus2)}笔): 胜率{wr2:.1f}% 均收益{sub_bonus2['return_pct'].mean():+.2f}%")

# ── 按年份统计 ──
print("\n" + "-" * 40)
print("按年份统计 (T+5):")
res_df['year'] = res_df['entry_date'].str[:4]
for year in sorted(res_df[res_df['hold_days'] == 5]['year'].unique()):
    sub = res_df[(res_df['hold_days'] == 5) & (res_df['year'] == year)]
    if len(sub) > 0:
        wr = len(sub[sub['return_pct'] > 0]) / len(sub) * 100
        print(f"  {year}: {len(sub)}笔 胜率{wr:.1f}% 均收益{sub['return_pct'].mean():+.2f}%")

# ── 最佳/最差交易 ──
print("\n" + "-" * 40)
print("最佳5笔 (T+5):")
best5 = res_df[(res_df['hold_days'] == 5)].nlargest(5, 'return_pct')
for _, r in best5.iterrows():
    print(f"  {r['symbol']} {r['entry_date']}→{r['exit_date']} {r['return_pct']:+.2f}% ({r['exit_reason']})")

print("\n最差5笔 (T+5):")
worst5 = res_df[(res_df['hold_days'] == 5)].nsmallest(5, 'return_pct')
for _, r in worst5.iterrows():
    print(f"  {r['symbol']} {r['entry_date']}→{r['exit_date']} {r['return_pct']:+.2f}% ({r['exit_reason']})")

conn.close()
print("\n回测完成 ✓")
