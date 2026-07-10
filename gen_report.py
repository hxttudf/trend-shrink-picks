#!/usr/bin/env python3
"""生成回测报告PDF — 沪深主板 含ST 上限4×25%"""
import sqlite3, os
from datetime import datetime, timedelta
from collections import defaultdict

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.backends.backend_pdf import PdfPages
import matplotlib.ticker as mticker

plt.rcParams['font.sans-serif'] = ['WenQuanYi Zen Hei', 'Noto Sans SC', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

# ── DB ──
TREND_DB = '/home/ubuntu/databases/trend_picks.db'
SEQ_DB = '/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db'
OUTPUT_PDF = '/home/ubuntu/trend-shrink-picks/回测报告_沪深主板_含ST_上限4.pdf'

CAPITAL = 200000
POS_VAL = CAPITAL * 0.25  # 5万
MAX_POS = 4
HOLD_DAYS = 28  # 自然日近似20交易日

# ── 获取信号 ──
conn = sqlite3.connect(TREND_DB)
rows = conn.execute("""
    SELECT dp.date, dp.symbol, dp.name, s.name as strategy,
           dp.ret_t20, dp.buy_price, dp.close_qfq
    FROM daily_picks dp
    JOIN strategies s ON dp.strategy_id = s.id
    WHERE s.name IN ('极品B', '超缩量')
    ORDER BY dp.date
""").fetchall()
conn.close()

seen = set()
signals = []
for r in rows:
    key = (r[0], r[1])
    if key in seen: continue
    seen.add(key)
    sym = r[1]
    # 只沪深主板
    if not (sym.startswith('6') or sym.startswith('00') or sym.startswith('001') or 
            sym.startswith('002') or sym.startswith('003')):
        continue
    signals.append({
        'date': r[0], 'symbol': r[1], 'name': r[2], 'strategy': r[3],
        'ret_t20': r[4], 'buy_price': r[5] or r[6],
        'is_st': r[2].startswith('*ST') or r[2].startswith('ST')
    })

print(f'信号数: {len(signals)}')

# ── 模拟交易 ──
def run_sim(sig_list):
    cash = CAPITAL
    portfolio = []
    orders = []  # (event_type, sig_dict, close_date, pnl, ret)
    
    for sig in sig_list:
        # 平到期
        i = 0
        while i < len(portfolio):
            p = portfolio[i]
            days = (datetime.strptime(sig['date'],'%Y-%m-%d') - datetime.strptime(p['date'],'%Y-%m-%d')).days
            if days >= HOLD_DAYS:
                ret = p['ret_t20'] or 0
                pnl = POS_VAL * ret / 100
                cash += POS_VAL + pnl
                orders.append(('卖出', p, sig['date'], round(pnl,2), ret))
                portfolio.pop(i)
            else:
                i += 1
        # 开仓
        if len(portfolio) < MAX_POS and cash >= POS_VAL:
            cash -= POS_VAL
            portfolio.append(dict(sig))
            orders.append(('买入', sig, None, None, None))
        else:
            orders.append(('跳过', sig, None, None, None))
    
    for p in portfolio:
        ret = p['ret_t20'] or 0
        pnl = POS_VAL * ret / 100
        cash += POS_VAL + pnl
        orders.append(('卖出(末)', p, '2026-05-06', round(pnl,2), ret))
    
    return orders, cash

orders, final_cash = run_sim(signals)

# 提取买卖配对
trades = []
buy_stack = []
for o in orders:
    if o[0] == '买入':
        buy_stack.append(o)
    elif o[0] in ('卖出', '卖出(末)'):
        if buy_stack:
            buy = buy_stack.pop(0)
            # buy: ('买入', sig, None, None, None)
            # sell: ('卖出', sig, close_date, pnl, ret)
            trades.append({
                'symbol': o[1]['symbol'],
                'name': o[1]['name'],
                'strategy': o[1]['strategy'],
                'is_st': o[1]['is_st'],
                'buy_date': buy[1]['date'],
                'sell_date': o[2],
                'buy_price': o[1]['buy_price'],
                'ret': o[4],
                'pnl': o[3],
                'hold_days': (datetime.strptime(o[2],'%Y-%m-%d') - datetime.strptime(buy[1]['date'],'%Y-%m-%d')).days
            })

print(f'交易笔数: {len(trades)}')

# ── 获取K线数据 ──
seq = sqlite3.connect(SEQ_DB)

# 建立symbol映射：trend_picks用"000506"格式，seq用"000506"格式（无后缀）
def get_kline(symbol, buy_date_str, lookback=20, lookforward=40):
    """获取买入日前后N天的K线"""
    try:
        bd = datetime.strptime(buy_date_str, '%Y-%m-%d')
    except:
        return None
    start = (bd - timedelta(days=lookback)).strftime('%Y-%m-%d')
    end = (bd + timedelta(days=lookforward)).strftime('%Y-%m-%d')
    
    df = pd.read_sql_query(f"""
        SELECT date, open, high, low, close, volume, close_qfq
        FROM stock_daily
        WHERE symbol = '{symbol}' AND date >= '{start}' AND date <= '{end}'
        ORDER BY date
    """, seq)
    if df.empty:
        return None
    df['date'] = pd.to_datetime(df['date'])
    df.set_index('date', inplace=True)
    return df

# ── 生成PDF ──
with PdfPages(OUTPUT_PDF) as pdf:
    # ── 第1页：总览 ──
    fig = plt.figure(figsize=(11.69, 8.27))  # A4横向
    fig.suptitle('趋势缩量选股 — 回测报告', fontsize=18, fontweight='bold', y=0.97)
    
    # 子区1：总览表格
    ax1 = plt.axes([0.05, 0.55, 0.45, 0.35])
    ax1.axis('off')
    total_ret = (final_cash / CAPITAL - 1) * 100
    cagr = ((final_cash / CAPITAL) ** (1/2.1) - 1) * 100
    wins = sum(1 for t in trades if t['ret'] > 0)
    total_pnl = sum(t['pnl'] for t in trades)
    
    overview = [
        ['参数', '值'],
        ['初始本金', f'{CAPITAL/10000:.0f}万'],
        ['标的范围', '沪深主板（含ST）'],
        ['策略', '极品B + 超缩量'],
        ['持仓上限', f'{MAX_POS}只 × {POS_VAL/CAPITAL*100:.0f}%/票'],
        ['持有期', f'{HOLD_DAYS}自然日（≈20交易日）'],
        ['', ''],
        ['总信号', f'{len(signals)}个（ST={sum(1 for s in signals if s["is_st"])}）'],
        ['成交笔数', f'{len(trades)}笔'],
        ['最终资产', f'{final_cash/10000:.1f}万'],
        ['总收益率', f'{total_ret:+.1f}%'],
        ['年化CAGR', f'{cagr:.1f}%'],
        ['总盈亏', f'{total_pnl/10000:+.2f}万'],
        ['胜率', f'{wins}/{len(trades)} = {wins/len(trades)*100:.1f}%'],
        ['平均每笔', f'{sum(t["ret"] for t in trades)/len(trades):+.1f}%'],
        ['单笔最高', f'{max(t["ret"] for t in trades):+.1f}%'],
        ['单笔最差', f'{min(t["ret"] for t in trades):+.1f}%'],
        ['回测区间', f'{signals[0]["date"]} ~ {signals[-1]["date"]}（2.1年）'],
    ]
    tbl = ax1.table(cellText=overview, loc='center', cellLoc='left', colWidths=[0.18, 0.25])
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(9)
    for (row, col), cell in tbl.get_celld().items():
        if row == 0:
            cell.set_facecolor('#2c3e50')
            cell.set_text_props(color='white', fontweight='bold')
        elif row % 2 == 0:
            cell.set_facecolor('#f0f0f0')
    
    # 子区2：资金曲线图
    ax2 = plt.axes([0.55, 0.55, 0.40, 0.35])
    equity = [CAPITAL]
    cur_pos = 0
    dates_line = []
    for t in trades:
        dates_line.append(t['buy_date'])
        equity.append(equity[-1] + t['pnl'])
        dates_line.append(t['sell_date'])
    # 画阶梯曲线
    xs = []
    ys = []
    for i, t in enumerate(trades):
        xs.append(t['buy_date'])
        ys.append(equity[i*2] if i*2 < len(equity) else CAPITAL)
        xs.append(t['sell_date'])
        ys.append(equity[i*2+1] if i*2+1 < len(equity) else CAPITAL)
    
    if xs:
        xd = [datetime.strptime(x, '%Y-%m-%d') for x in xs]
        ax2.plot(xd, ys, 'b-', linewidth=1.5)
        ax2.fill_between(xd, CAPITAL, ys, alpha=0.15, color='green' if ys[-1] > CAPITAL else 'red')
        ax2.axhline(y=CAPITAL, color='gray', linestyle='--', linewidth=0.5)
        ax2.set_title('资金曲线', fontsize=12, fontweight='bold')
        ax2.set_ylabel('资产（元）')
        ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, p: f'{x/10000:.0f}万'))
        ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
        ax2.tick_params(axis='x', rotation=45)
    
    # 子区3：按年汇总
    ax3 = plt.axes([0.05, 0.05, 0.90, 0.42])
    ax3.axis('off')
    
    # 分组显示：按年份
    yearly = defaultdict(list)
    for t in trades:
        yr = t['buy_date'][:4]
        yearly[yr].append(t)
    
    rows_data = []
    rows_data.append(['年份', '笔数', '平均T20', '胜率', '平均盈亏', '总盈亏', '最佳', '最差'])
    for yr in sorted(yearly.keys()):
        ts = yearly[yr]
        avg_r = sum(t['ret'] for t in ts)/len(ts)
        wr = sum(1 for t in ts if t['ret']>0)/len(ts)*100
        avg_p = sum(t['pnl'] for t in ts)/len(ts)
        sum_p = sum(t['pnl'] for t in ts)
        best = max(t['ret'] for t in ts)
        worst = min(t['ret'] for t in ts)
        rows_data.append([yr, str(len(ts)), f'{avg_r:+.1f}%', f'{wr:.0f}%',
                         f'{avg_p/10000:+.2f}万', f'{sum_p/10000:+.2f}万',
                         f'{best:+.1f}%', f'{worst:+.1f}%'])
    
    tbl2 = ax3.table(cellText=rows_data, loc='center', cellLoc='center', colWidths=[0.08]*8)
    tbl2.auto_set_font_size(False)
    tbl2.set_fontsize(8)
    for (row, col), cell in tbl2.get_celld().items():
        if row == 0:
            cell.set_facecolor('#2c3e50')
            cell.set_text_props(color='white', fontweight='bold')
        elif row % 2 == 0:
            cell.set_facecolor('#f0f0f0')
    
    pdf.savefig(fig)
    plt.close()
    
    # ── 逐股分析页 ──
    for i, t in enumerate(trades):
        print(f'生成图表: {i+1}/{len(trades)} {t["name"]} ({t["symbol"]})')
        fig = plt.figure(figsize=(11.69, 8.27))
        
        # K线图
        ax_k = plt.axes([0.08, 0.30, 0.55, 0.60])
        try:
            kdf = get_kline(t['symbol'], t['buy_date'])
        
        if kdf is not None and len(kdf) > 5:
            # 找到buy_date和sell_date的位置
            buy_dt = pd.Timestamp(t['buy_date'])
            # 找出买入日后的第一个交易日
            buy_idx = 0
            for idx, d in enumerate(kdf.index):
                if d >= buy_dt:
                    buy_idx = idx
                    break
            
            sell_dt = pd.Timestamp(t['sell_date'])
            sell_idx = len(kdf) - 1
            for idx, d in enumerate(kdf.index):
                if d >= sell_dt:
                    sell_idx = idx
                    break
            
            # 绘制K线
            mpl_f = kdf[['open','high','low','close','volume']].copy()
            mpl_f.columns = ['Open','High','Low','Close','Volume']
            
            # 使用mplfinance
            import mplfinance as mpf
            # 但mpf画到现有axes上比较tricky，改用自定义k线
            # 手动画candlestick
            width = 0.6
            up = kdf[kdf['close'] >= kdf['open']]
            down = kdf[kdf['close'] < kdf['open']]
            
            ax_k.bar(up.index, up['close'] - up['open'], width, bottom=up['open'], color='red', edgecolor='red')
            ax_k.bar(down.index, down['close'] - down['open'], width, bottom=down['open'], color='green', edgecolor='green')
            # 影线
            for idx, row in kdf.iterrows():
                ax_k.plot([idx, idx], [row['low'], row['high']], color='black', linewidth=0.5)
            
            # 买入/卖出标记
            if buy_idx < len(kdf):
                bx = kdf.index[buy_idx]
                by = kdf.iloc[buy_idx]['low'] * 0.98
                ax_k.scatter(bx, by, marker='^', color='blue', s=120, zorder=5, label='买入')
                ax_k.annotate(f'买入\n{t["buy_price"]:.2f}', (bx, by), 
                            textcoords="offset points", xytext=(0, -25),
                            ha='center', fontsize=8, color='blue', fontweight='bold')
            
            if sell_idx < len(kdf):
                sx = kdf.index[sell_idx]
                sy = kdf.iloc[sell_idx]['high'] * 1.02
                ax_k.scatter(sx, sy, marker='v', color='purple', s=120, zorder=5, label='卖出')
                sell_price = t['buy_price'] * (1 + t['ret']/100)
                ax_k.annotate(f'卖出\n{sell_price:.2f}', (sx, sy),
                            textcoords="offset points", xytext=(0, 20),
                            ha='center', fontsize=8, color='purple', fontweight='bold')
            
            # 标注持有区间
            ax_k.axvspan(kdf.index[buy_idx], kdf.index[sell_idx], alpha=0.1, color='yellow', label='持有期')
            
            ax_k.set_title(f'{t["name"]} ({t["symbol"]}) — {t["strategy"]}', fontsize=13, fontweight='bold')
            ax_k.set_ylabel('价格')
            ax_k.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
            ax_k.tick_params(axis='x', rotation=45)
            ax_k.grid(True, alpha=0.3)
            ax_k.legend(fontsize=8)
        else:
            ax_k.text(0.5, 0.5, 'K线数据缺失', ha='center', va='center', fontsize=14)
            ax_k.set_title(f'{t["name"]} ({t["symbol"]})', fontsize=13, fontweight='bold')
        
        # 交易详情表
        ax_info = plt.axes([0.08, 0.05, 0.55, 0.20])
        ax_info.axis('off')
        
        tag = '⚠ST' if t['is_st'] else '   '
        detail = [
            ['字段', '值'],
            ['股票', f'{t["name"]} ({t["symbol"]}) {tag}'],
            ['策略', t['strategy']],
            ['买入日期', t['buy_date']],
            ['卖出日期', t['sell_date']],
            ['持有天数', f'{t["hold_days"]}天'],
            ['买入价格', f'{t["buy_price"]:.2f}'],
            ['卖出价格', f'{t["buy_price"]*(1+t["ret"]/100):.2f}'],
            ['收益率', f'{t["ret"]:+.1f}%'],
            ['盈亏金额', f'{t["pnl"]:+.0f}元（{t["pnl"]/10000:+.2f}万）'],
        ]
        tbl_d = ax_info.table(cellText=detail, loc='center', cellLoc='left', colWidths=[0.12, 0.35])
        tbl_d.auto_set_font_size(False)
        tbl_d.set_fontsize(8)
        for (row, col), cell in tbl_d.get_celld().items():
            if row == 0:
                cell.set_facecolor('#2c3e50')
                cell.set_text_props(color='white', fontweight='bold')
        
        # 右半：收益分解柱状图
        ax_ret = plt.axes([0.68, 0.30, 0.28, 0.55])
        ax_ret.axis('off')
        
        ret_data = [
            ['累计收益', f'{t["ret"]:+.1f}%', t['ret']],
            ['盈亏金额', f'{t["pnl"]:+.0f}元', t['pnl']/10000],
        ]
        
        colors = ['#e74c3c' if t['ret'] < 0 else '#2ecc71',
                  '#e74c3c' if t['pnl'] < 0 else '#2ecc71']
        bars = ax_ret.barh(['收益率', '盈亏'], [t['ret'], t['pnl']/10000], color=colors, height=0.5)
        ax_ret.axvline(x=0, color='gray', linewidth=0.5)
        for bar, val in zip(bars, [t['ret'], t['pnl']/10000]):
            ax_ret.text(val + (1 if val >= 0 else -3), bar.get_y() + bar.get_height()/2,
                       f'{val:.1f}' + ('%' if bar == bars[0] else '万'),
                       va='center', fontsize=10, fontweight='bold')
        ax_ret.set_xlim(min(-5, t['ret']-5), max(t['ret']+5, 5))
        
        # 策略表现对比
        all_rets = [x['ret'] for x in trades]
        all_avg = sum(all_rets)/len(all_rets)
        ax_cmp = plt.axes([0.68, 0.05, 0.28, 0.20])
        ax_cmp.axis('off')
        cmp_data = [
            ['对比项', '值'],
            ['本笔收益', f'{t["ret"]:+.1f}%'],
            ['全部平均', f'{all_avg:+.1f}%'],
            ['差异', f'{t["ret"]-all_avg:+.1f}%'],
            ['全部中位', f'{sorted(all_rets)[len(all_rets)//2]:+.1f}%'],
            ['排名', f'{sum(1 for r in all_rets if r > t["ret"])+1}/{len(all_rets)}'],
        ]
        tbl_c = ax_cmp.table(cellText=cmp_data, loc='center', cellLoc='left', colWidths=[0.12, 0.15])
        tbl_c.auto_set_font_size(False)
        tbl_c.set_fontsize(8)
        for (row, col), cell in tbl_c.get_celld().items():
            if row == 0:
                cell.set_facecolor('#2c3e50')
                cell.set_text_props(color='white', fontweight='bold')
        
        pdf.savefig(fig)
        plt.close()
    
    # ── 最后一页：汇总统计 ──
    fig = plt.figure(figsize=(11.69, 8.27))
    fig.suptitle('附录：完整交易清单', fontsize=16, fontweight='bold', y=0.97)
    ax = plt.axes([0.02, 0.02, 0.96, 0.90])
    ax.axis('off')
    
    table_rows = [['#', '股票', '代码', '策略', 'ST', '买入', '卖出', '持有d', '收益%', '盈亏(元)']]
    for i, t in enumerate(trades, 1):
        table_rows.append([
            str(i), t['name'], t['symbol'], t['strategy'],
            '✓' if t['is_st'] else '',
            t['buy_date'], t['sell_date'], str(t['hold_days']),
            f'{t["ret"]:+.1f}%', f'{t["pnl"]:+.0f}'
        ])
    
    tbl_f = ax.table(cellText=table_rows, loc='center', cellLoc='center', colWidths=[0.03,0.07,0.07,0.07,0.03,0.09,0.09,0.05,0.07,0.08])
    tbl_f.auto_set_font_size(False)
    tbl_f.set_fontsize(7)
    for (row, col), cell in tbl_f.get_celld().items():
        if row == 0:
            cell.set_facecolor('#2c3e50')
            cell.set_text_props(color='white', fontweight='bold')
        elif row % 2 == 0:
            cell.set_facecolor('#f0f0f0')
        # 收益颜色
        if col == 8 and row > 0:
            val = table_rows[row][8]
            if val.startswith('+'):
                cell.set_text_props(color='red', fontweight='bold')
            elif val.startswith('-'):
                cell.set_text_props(color='green', fontweight='bold')
    
    pdf.savefig(fig)
    plt.close()

seq.close()
print(f'\n✅ 报告已生成: {OUTPUT_PDF}')
print(f'   共{len(trades)}笔交易, {pdf.get_pagecount()}页')
