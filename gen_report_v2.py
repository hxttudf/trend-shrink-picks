#!/usr/bin/env python3
"""生成回测报告PDF — 简洁版，含完整交易表+收益图表"""
import sqlite3
from datetime import datetime
from collections import defaultdict

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import matplotlib.dates as mdates
import matplotlib.ticker as mticker
import numpy as np

plt.rcParams['font.sans-serif'] = ['WenQuanYi Zen Hei']
plt.rcParams['axes.unicode_minus'] = False

# ── 数据 ──
TREND_DB = '/home/ubuntu/databases/trend_picks.db'
OUTPUT = '/home/ubuntu/trend-shrink-picks/回测报告_沪深主板_含ST_上限4.pdf'
CAPITAL = 200000
POS_VAL = CAPITAL * 0.25
MAX_POS = 4
HOLD = 28

conn = sqlite3.connect(TREND_DB)
rows = conn.execute("""
    SELECT dp.date, dp.symbol, dp.name, s.name, dp.ret_t20, dp.buy_price
    FROM daily_picks dp JOIN strategies s ON dp.strategy_id = s.id
    WHERE s.name IN ('极品B', '超缩量') ORDER BY dp.date
""").fetchall()
conn.close()

seen = set()
signals = []
for r in rows:
    k = (r[0], r[1])
    if k in seen: continue
    seen.add(k)
    sym = r[1]
    if not (sym.startswith('6') or sym.startswith('00') or sym.startswith('001') or
            sym.startswith('002') or sym.startswith('003')): continue
    signals.append({
        'date': r[0], 'symbol': r[1], 'name': r[2], 'strategy': r[3],
        'ret': r[4] or 0, 'buy_p': r[5] or 0,
        'st': r[2].startswith('*ST') or r[2].startswith('ST')
    })

# 模拟
def simulate(sig_list):
    cash = CAPITAL
    pf = []
    trades = []
    for sig in sig_list:
        i = 0
        while i < len(pf):
            d = (datetime.strptime(sig['date'],'%Y-%m-%d') - datetime.strptime(pf[i]['date'],'%Y-%m-%d')).days
            if d >= HOLD:
                pnl = POS_VAL * pf[i]['ret'] / 100
                cash += POS_VAL + pnl
                trades.append({**pf[i], 'sell_date': sig['date'], 'pnl': pnl, 'hold': d})
                pf.pop(i)
            else: i += 1
        if len(pf) < MAX_POS and cash >= POS_VAL:
            cash -= POS_VAL
            pf.append(dict(sig))
        # skip silently
    for p in pf:
        pnl = POS_VAL * p['ret'] / 100
        cash += POS_VAL + pnl
        trades.append({**p, 'sell_date': '2026-05-06', 'pnl': pnl, 'hold': 28})
    return trades, cash

trades, final = simulate(signals)

# ── 统计 ──
total_ret = (final/CAPITAL-1)*100
cagr = ((final/CAPITAL)**(1/2.1)-1)*100
wins = sum(1 for t in trades if t['ret']>0)
rets = [t['ret'] for t in trades]

yearly = defaultdict(list)
for t in trades:
    yearly[t['date'][:4]].append(t)

# ── 生成PDF ──
with PdfPages(OUTPUT) as pdf:
    # 第1页：总览
    fig = plt.figure(figsize=(11.69, 8.27))
    
    # 左上：概览表
    ax1 = plt.axes([0.05, 0.50, 0.40, 0.40])
    ax1.axis('off')
    data = [
        ['回测参数', '值'],
        ['策略', '极品B + 超缩量'],
        ['标的范围', '沪深主板（含ST参考）'],
        ['初始本金', f'{CAPITAL/10000:.0f}万'],
        ['持仓上限', f'{MAX_POS}只 × 25%/票'],
        ['持有期', '20交易日（约28自然日）'],
        ['回测区间', f'{signals[0]["date"]} ~ {signals[-1]["date"]}'],
        ['', ''],
        ['总信号', f'{len(signals)}个（其中ST={sum(1 for s in signals if s["st"])}）'],
        ['成交笔数', f'{len(trades)}笔'],
        ['最终资产', f'{final/10000:.1f}万'],
        ['总收益率', f'{total_ret:+.1f}%'],
        ['年化CAGR', f'{cagr:.1f}%'],
        ['胜率', f'{wins}/{len(trades)} = {wins/len(trades)*100:.1f}%'],
        ['平均收益', f'{sum(rets)/len(rets):+.1f}%'],
        ['单笔最高', f'{max(rets):+.1f}%'],
        ['单笔最低', f'{min(rets):+.1f}%'],
        ['盈亏比', f'{sum(t["pnl"] for t in trades):+.0f}元'],
    ]
    tbl = ax1.table(cellText=data, loc='center', cellLoc='left', colWidths=[0.18, 0.22])
    tbl.auto_set_font_size(False); tbl.set_fontsize(8)
    for (r,c),cell in tbl.get_celld().items():
        if r==0: cell.set_facecolor('#2c3e50'); cell.set_text_props(color='white', fontweight='bold')
        elif r%2==0: cell.set_facecolor('#f0f0f0')
    
    # 右上：资金曲线
    ax2 = plt.axes([0.52, 0.50, 0.43, 0.40])
    equity = [CAPITAL]
    for t in trades: equity.append(equity[-1] + t['pnl'])
    dates_full = [signals[0]['date']] + [t['sell_date'] for t in trades]
    xd = [datetime.strptime(d,'%Y-%m-%d') for d in dates_full]
    ax2.plot(xd, equity, 'b-', linewidth=1.5)
    ax2.fill_between(xd, CAPITAL, equity, alpha=0.15, color='green' if equity[-1]>CAPITAL else 'red')
    ax2.axhline(y=CAPITAL, color='gray', linestyle='--', alpha=0.5)
    ax2.set_title('资金曲线', fontweight='bold')
    ax2.set_ylabel('资产')
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x,p: f'{x/10000:.0f}万'))
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax2.tick_params(axis='x', rotation=45)
    ax2.grid(True, alpha=0.3)
    
    # 下半：逐年统计
    ax3 = plt.axes([0.05, 0.05, 0.90, 0.35])
    ax3.axis('off')
    yr_data = [['年份', '笔数', '总盈亏', '平均T20', '胜率', '最佳', '最差']]
    for yr in sorted(yearly):
        ts = yearly[yr]
        avg = sum(t['ret'] for t in ts)/len(ts)
        wr = sum(1 for t in ts if t['ret']>0)/len(ts)*100
        sp = sum(t['pnl'] for t in ts)
        best = max(t['ret'] for t in ts)
        worst = min(t['ret'] for t in ts)
        yr_data.append([yr, str(len(ts)), f'{sp/10000:+.2f}万', f'{avg:+.1f}%', f'{wr:.0f}%', f'{best:+.1f}%', f'{worst:+.1f}%'])
    
    tbl2 = ax3.table(cellText=yr_data, loc='center', cellLoc='center', colWidths=[0.1]*7)
    tbl2.auto_set_font_size(False); tbl2.set_fontsize(9)
    for (r,c),cell in tbl2.get_celld().items():
        if r==0: cell.set_facecolor('#2c3e50'); cell.set_text_props(color='white', fontweight='bold')
    
    pdf.savefig(fig); plt.close(fig)
    
    # 第2页：收益分布
    fig = plt.figure(figsize=(11.69, 8.27))
    
    # 柱状图：按时间序
    ax4 = plt.axes([0.06, 0.55, 0.88, 0.38])
    trade_dates = [datetime.strptime(t['date'],'%Y-%m-%d') for t in trades]
    colors = ['#e74c3c' if r<0 else '#2ecc71' for r in rets]
    bars = ax4.bar(range(len(trades)), rets, color=colors, width=0.7)
    ax4.axhline(y=0, color='gray', linewidth=0.5)
    ax4.set_title('每笔交易收益率（按时间）', fontweight='bold')
    ax4.set_ylabel('T20收益率 %')
    ax4.set_xticks(range(0, len(trades), 5))
    ax4.set_xticklabels([trades[i]['date'] for i in range(0, len(trades), 5)], rotation=45, fontsize=7)
    ax4.grid(True, alpha=0.3, axis='y')
    # 平均线
    avg_v = sum(rets)/len(rets)
    ax4.axhline(y=avg_v, color='blue', linestyle='--', linewidth=0.8, label=f'平均{avg_v:+.1f}%')
    ax4.legend(fontsize=8)
    
    # 分布饼图
    ax5 = plt.axes([0.06, 0.05, 0.25, 0.42])
    buckets = {'<-10%':0, '-10~0%':0, '0~10%':0, '10~20%':0, '20~50%':0, '>50%':0}
    for r in rets:
        if r < -10: buckets['<-10%'] += 1
        elif r < 0: buckets['-10~0%'] += 1
        elif r < 10: buckets['0~10%'] += 1
        elif r < 20: buckets['10~20%'] += 1
        elif r < 50: buckets['20~50%'] += 1
        else: buckets['>50%'] += 1
    labels = [f'{k}\n({v}笔)' for k,v in buckets.items() if v>0]
    sizes = [v for v in buckets.values() if v>0]
    ax5.pie(sizes, labels=labels, autopct='%1.0f%%', startangle=90, 
            colors=['#e74c3c','#f39c12','#3498db','#2ecc71','#27ae60','#1abc9c'])
    ax5.set_title('T20收益分布', fontweight='bold')
    
    # 策略对比
    ax6 = plt.axes([0.40, 0.05, 0.55, 0.42])
    ax6.axis('off')
    strat_data = [['策略', '笔数', '平均T20', '胜率', '总盈亏']]
    for sn in ['极品B', '超缩量']:
        st = [t for t in trades if t['strategy']==sn]
        if not st: continue
        sa = sum(t['ret'] for t in st)/len(st)
        sw = sum(1 for t in st if t['ret']>0)/len(st)*100
        sp = sum(t['pnl'] for t in st)
        strat_data.append([sn, str(len(st)), f'{sa:+.1f}%', f'{sw:.0f}%', f'{sp/10000:+.2f}万'])
    # 含ST vs 排ST
    st_tr = [t for t in trades if t['st']]
    ns_tr = [t for t in trades if not t['st']]
    for label, group in [('含ST', st_tr), ('排ST', ns_tr)]:
        ga = sum(t['ret'] for t in group)/len(group)
        gw = sum(1 for t in group if t['ret']>0)/len(group)*100
        gp = sum(t['pnl'] for t in group)
        strat_data.append([label, str(len(group)), f'{ga:+.1f}%', f'{gw:.0f}%', f'{gp/10000:+.2f}万'])
    
    tbl3 = ax6.table(cellText=strat_data, loc='center', cellLoc='center', colWidths=[0.12]*5)
    tbl3.auto_set_font_size(False); tbl3.set_fontsize(9)
    for (r,c),cell in tbl3.get_celld().items():
        if r==0: cell.set_facecolor('#2c3e50'); cell.set_text_props(color='white', fontweight='bold')
    
    pdf.savefig(fig); plt.close(fig)
    
    # 后续页：完整交易清单
    # 每页最多25条交易
    per_page = 25
    pages = (len(trades) + per_page - 1) // per_page
    for pg in range(pages):
        fig = plt.figure(figsize=(11.69, 8.27))
        ax = plt.axes([0.02, 0.08, 0.96, 0.85])
        ax.axis('off')
        
        start = pg * per_page
        end = min(start + per_page, len(trades))
        
        ax.set_title(f'完整交易清单（第{pg+1}/{pages}页）', fontweight='bold', fontsize=14, y=0.98)
        
        hdr = ['#', '策略', '股票', '代码', 'ST', '买入', '卖出', '持有d', '收益率', '盈亏(元)']
        rows_t = [hdr]
        for i in range(start, end):
            t = trades[i]
            rows_t.append([
                str(i+1), t['strategy'][:3], t['name'], t['symbol'],
                '✓' if t['st'] else '',
                t['date'], t['sell_date'], str(t['hold']),
                f'{t["ret"]:+.1f}%', f'{t["pnl"]:+.0f}'
            ])
        
        tbl = ax.table(cellText=rows_t, loc='center', cellLoc='center',
                      colWidths=[0.03,0.05,0.08,0.07,0.03,0.09,0.09,0.05,0.08,0.09])
        tbl.auto_set_font_size(False); tbl.set_fontsize(7)
        for (r,c),cell in tbl.get_celld().items():
            if r == 0:
                cell.set_facecolor('#2c3e50')
                cell.set_text_props(color='white', fontweight='bold')
            elif r % 2 == 0:
                cell.set_facecolor('#f0f0f0')
            if c == 8 and r > 0:  # 收益率上色
                v = rows_t[r][8]
                if v.startswith('+'): cell.set_text_props(color='red', fontweight='bold')
                elif v.startswith('-'): cell.set_text_props(color='green', fontweight='bold')
        
        pdf.savefig(fig); plt.close(fig)
        print(f'  页{pg+1}/{pages}: 交易{start+1}-{end}')

print(f'\n✅ 报告生成: {OUTPUT}')
print(f'   共{len(trades)}笔交易, {pages+2}页')
