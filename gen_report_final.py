#!/usr/bin/env python3
"""生成两张回测报告PDF：满仓调仓 vs NAV25%"""
import sqlite3
from datetime import datetime, timedelta
from collections import defaultdict
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as mticker
from matplotlib.backends.backend_pdf import PdfPages
import numpy as np

plt.rcParams['font.sans-serif'] = ['WenQuanYi Zen Hei']
plt.rcParams['axes.unicode_minus'] = False

# ── 数据加载 ──
TDB, SDB = '/home/ubuntu/databases/trend_picks.db', '/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db'
tconn, sconn = sqlite3.connect(TDB), sqlite3.connect(SDB)

signals = tconn.execute("SELECT dp.date, dp.symbol, dp.name, s.name, dp.buy_price FROM daily_picks dp JOIN strategies s ON dp.strategy_id=s.id WHERE s.name IN ('极品B','超缩量') ORDER BY dp.date").fetchall()
tconn.close()

seen = set()
data = []
for r in signals:
    k = (r[0],r[1])
    if k in seen: continue
    seen.add(k)
    if not (r[1].startswith('6') or r[1].startswith('00') or r[1].startswith('001') or r[1].startswith('002') or r[1].startswith('003')): continue
    data.append({'date':r[0],'symbol':r[1],'name':r[2],'strategy':r[3],'buy_price':r[4] or 0,'st':r[2].startswith('*ST') or r[2].startswith('ST')})

def get_path(sig, extra=80):
    bd = datetime.strptime(sig['date'],'%Y-%m-%d')
    rows = sconn.execute("SELECT date,close_qfq FROM stock_daily WHERE symbol=? AND date>=? AND date<=? ORDER BY date",
                         (sig['symbol'], bd.strftime('%Y-%m-%d'), (bd+timedelta(days=extra)).strftime('%Y-%m-%d'))).fetchall()
    if not rows: return None
    bp = sig['buy_price']
    if not bp or bp<=0: return None
    return {r[0]: r[1] for r in rows if r[1] and r[1]>0}

items = []
price_map = defaultdict(dict)
all_dates_set = set()
for sig in data:
    p = get_path(sig, 80)
    if p:
        items.append({'sig':sig, 'prices':p})
        for d in p:
            all_dates_set.add(d)
            price_map[sig['symbol']][d] = p[d]

all_dates = sorted(all_dates_set)
print(f'信号: {len(items)}个, 交易日: {len(all_dates)}个')

sig_by_date = defaultdict(list)
for item in items:
    sig_by_date[item['sig']['date']].append(item)

# ── 模拟引擎（逐日，记录完整状态）──
def simulate_full(name, mode='rebalance', pct=0.25, max_pos=4):
    """返回: trades, daily_log
    daily_log: [{'date':, 'nav':, 'cash':, 'positions':[{'sym','val','entry_val','ret'}], 'action':}]
    """
    cash = 200000
    pf = []  # [{symbol, name, buy_price, buy_date, entry_val, last_price}]
    trades = []
    daily_log = []
    
    for date in all_dates:
        dt = datetime.strptime(date, '%Y-%m-%d')
        action = ''
        
        # ── 平仓到期（收盘后检查）──
        i = 0
        while i < len(pf):
            p = pf[i]
            bd = datetime.strptime(p['buy_date'], '%Y-%m-%d')
            days_held = (dt - bd).days
            if days_held >= 28:  # ≈20交易日
                # 收盘价平仓
                cp = price_map.get(p['symbol'], {}).get(date, p.get('last_price', p['buy_price']))
                ret = (cp/p['buy_price']-1)*100 if p['buy_price']>0 else 0
                exit_val = p['entry_val'] * (cp/p['buy_price']) if p['buy_price']>0 else p['entry_val']
                pnl = exit_val - p['entry_val']
                cash += exit_val
                trades.append({
                    'name': p['name'], 'symbol': p['symbol'],
                    'buy_date': p['buy_date'], 'sell_date': date,
                    'buy_price': round(p['buy_price'],2), 'sell_price': round(cp,2),
                    'ret': round(ret,1), 'pnl': round(pnl,2),
                    'hold_days': days_held, 'entry_val': round(p['entry_val'],2),
                    'exit_val': round(exit_val,2),
                    'action': '开盘买入,收盘卖出' if days_held == 0 else 'T+20收盘到期'
                })
                action += f'平仓{p["name"]}({p["symbol"]})收益{ret:.1f}%; '
                pf.pop(i)
            else:
                p['last_price'] = price_map.get(p['symbol'], {}).get(date, p.get('last_price', p['buy_price']))
                i += 1
        
        # ── 新信号（收盘后判断）──
        if date in sig_by_date:
            new_items = sig_by_date[date]
            for item in new_items:
                sig = item['sig']
                
                if mode == 'rebalance':
                    # 先算总资产（当前收盘价）
                    total_val = cash
                    for p in pf:
                        cp = price_map.get(p['symbol'], {}).get(date, p.get('last_price', p['buy_price']))
                        val = p['entry_val'] * (cp/p['buy_price']) if p['buy_price']>0 else p['entry_val']
                        total_val += val
                    
                    total_pos = len(pf)
                    new_count = len(new_items)
                    target = total_val / (total_pos + new_count)
                    
                    # 卖出超额部分（收盘价）
                    rebal_sells = []
                    for p in pf:
                        cp = price_map.get(p['symbol'], {}).get(date, p.get('last_price', p['buy_price']))
                        cur_val = p['entry_val'] * (cp/p['buy_price']) if p['buy_price']>0 else p['entry_val']
                        if cur_val > target * 1.001:
                            sell_val = cur_val - target
                            sell_ratio = target / cur_val
                            cash += sell_val
                            p['entry_val'] *= sell_ratio
                            p['last_price'] = cp
                            rebal_sells.append(f'减仓{p["name"]}{sell_val/10000:.1f}万')
                    
                    action += '; '.join(rebal_sells) + ('; ' if rebal_sells else '')
                    
                    # 买入新信号（次日开盘价）
                    bp = sig['buy_price']
                    if cash >= target:
                        cash -= target
                        pf.append({
                            'symbol': sig['symbol'], 'name': sig['name'],
                            'buy_price': bp, 'buy_date': date,
                            'entry_val': target, 'last_price': bp
                        })
                        action += f'买入{sig["name"]}({sig["symbol"]}){target/10000:.1f}万; '
                
                elif mode == 'nav':
                    # NAV25%
                    nav = cash
                    for p in pf:
                        cp = price_map.get(p['symbol'], {}).get(date, p.get('last_price', p['buy_price']))
                        val = p['entry_val'] * (cp/p['buy_price']) if p['buy_price']>0 else p['entry_val']
                        nav += val
                    pv = nav * pct
                    if len(pf) < max_pos and cash >= pv:
                        cash -= pv
                        pf.append({
                            'symbol': sig['symbol'], 'name': sig['name'],
                            'buy_price': sig['buy_price'], 'buy_date': date,
                            'entry_val': pv, 'last_price': sig['buy_price']
                        })
                        action += f'买入{sig["name"]}({sig["symbol"]}){pv/10000:.1f}万; '
        
        # ── 记录日终状态（收盘后）──
        pos_info = []
        nav = cash
        for p in pf:
            cp = price_map.get(p['symbol'], {}).get(date, p.get('last_price', p['buy_price']))
            cur_val = p['entry_val'] * (cp/p['buy_price']) if p['buy_price']>0 else p['entry_val']
            ret = (cp/p['buy_price']-1)*100 if p['buy_price']>0 else 0
            pos_info.append({
                'symbol': p['symbol'], 'name': p['name'],
                'buy_date': p['buy_date'],
                'entry_val': round(p['entry_val'],2),
                'cur_val': round(cur_val,2),
                'ret': round(ret,1),
                'last_price': round(cp,2),
                'buy_price': p['buy_price']
            })
            nav += cur_val
        
        daily_log.append({
            'date': date,
            'nav': round(nav,2),
            'cash': round(cash,2),
            'positions': pos_info,
            'action': action.strip('; ')
        })
    
    # 期末平仓
    last_date = all_dates[-1]
    for p in pf:
        cp = price_map.get(p['symbol'], {}).get(last_date, p.get('last_price', p['buy_price']))
        ret = (cp/p['buy_price']-1)*100 if p['buy_price']>0 else 0
        exit_val = p['entry_val'] * (cp/p['buy_price']) if p['buy_price']>0 else p['entry_val']
        pnl = exit_val - p['entry_val']
        cash += exit_val
        trades.append({
            'name': p['name'], 'symbol': p['symbol'],
            'buy_date': p['buy_date'], 'sell_date': last_date,
            'buy_price': round(p['buy_price'],2), 'sell_price': round(cp,2),
            'ret': round(ret,1), 'pnl': round(pnl,2),
            'hold_days': 999, 'entry_val': round(p['entry_val'],2),
            'exit_val': round(exit_val,2), 'action': '期末平仓'
        })
    
    return trades, daily_log

# ── 运行两个策略 ──
print('运行满仓调仓...')
t1, log1 = simulate_full('满仓调仓', 'rebalance')
f1 = log1[-1]['cash']
print(f'运行NAV25%...')
t2, log2 = simulate_full('NAV25%', 'nav')
f2 = log2[-1]['cash']

# ── 生成报告PDF ──
def gen_pdf(name, trades, daily_log, output_path):
    """生成一份完整策略报告"""
    final_nav = daily_log[-1]['nav']
    total_ret = (final_nav/200000-1)*100
    cagr = ((final_nav/200000)**(1/2.1)-1)*100
    closed_trades = [t for t in trades if t['hold_days'] < 900]
    wins = sum(1 for t in closed_trades if t['ret'] > 0)
    win_rate = wins/len(closed_trades)*100 if closed_trades else 0
    empty_days = sum(1 for d in daily_log if len(d['positions'])==0)
    
    # 持仓数据
    pos_counts = [len(d['positions']) for d in daily_log]
    cash_pcts = [d['cash']/max(d['nav'],1)*100 for d in daily_log]
    dates_dt = [datetime.strptime(d['date'],'%Y-%m-%d') for d in daily_log]
    
    with PdfPages(output_path) as pdf:
        # ═══ 第1页：总览 ═══
        fig = plt.figure(figsize=(11.69, 8.27))
        fig.suptitle(f'{name} — 回测报告', fontsize=18, fontweight='bold', y=0.97)
        
        # 左上：概览表
        ax1 = plt.axes([0.04, 0.50, 0.42, 0.42])
        ax1.axis('off')
        info = [
            ['参数', '值'],
            ['策略', name],
            ['标的', '沪深主板（极品B+超缩量）'],
            ['初始本金', '20万'],
            ['买入', '信号日次日开盘价（T+1开盘）'],
            ['卖出', '收盘后检查, T+20到期/调仓'],
            ['持有期', '最长20交易日（收盘到期）'],
            ['回测区间', f'{daily_log[0]["date"]} ~ {daily_log[-1]["date"]}'],
            ['交易日', f'{len(daily_log)}天'],
            ['', ''],
            ['最终资产', f'{final_nav/10000:.2f}万'],
            ['总收益率', f'{total_ret:+.1f}%'],
            ['年化CAGR', f'{cagr:.1f}%'],
            ['成交笔数', f'{len(closed_trades)}笔'],
            ['胜率', f'{wins}/{len(closed_trades)} = {win_rate:.0f}%'],
            ['单笔平均', f'{sum(t["ret"] for t in closed_trades)/len(closed_trades):+.1f}%'],
            ['单笔最高', f'{max(t["ret"] for t in closed_trades):+.1f}%'],
            ['单笔最低', f'{min(t["ret"] for t in closed_trades):+.1f}%'],
            ['空仓天数', f'{empty_days}/{len(daily_log)}天 ({empty_days/len(daily_log)*100:.0f}%)'],
        ]
        tbl = ax1.table(cellText=info, loc='center', cellLoc='left', colWidths=[0.15, 0.27])
        tbl.auto_set_font_size(False); tbl.set_fontsize(8)
        for (r,c),cell in tbl.get_celld().items():
            if r==0: cell.set_facecolor('#2c3e50'); cell.set_text_props(color='white', fontweight='bold')
            elif r%2==0: cell.set_facecolor('#f0f0f0')
        
        # 右上：资产曲线
        ax2 = plt.axes([0.52, 0.50, 0.44, 0.42])
        ax2.plot(dates_dt, [d['nav'] for d in daily_log], 'b-', linewidth=1.2, label='总资产')
        ax2.plot(dates_dt, [d['cash'] for d in daily_log], 'orange', linewidth=0.8, alpha=0.7, label='现金')
        # 基准线
        ax2.axhline(y=200000, color='gray', linestyle='--', linewidth=0.5, alpha=0.5)
        ax2.fill_between(dates_dt, 200000, [d['nav'] for d in daily_log], 
                         alpha=0.12, color='green' if final_nav>200000 else 'red')
        ax2.set_title('资产曲线', fontweight='bold')
        ax2.set_ylabel('金额')
        ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x,p: f'{x/10000:.0f}万'))
        ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
        ax2.tick_params(axis='x', rotation=45)
        ax2.grid(True, alpha=0.3)
        ax2.legend(fontsize=8, loc='upper left')
        
        # 下半：持仓分布
        ax3 = plt.axes([0.04, 0.04, 0.92, 0.38])
        ax3.stackplot(dates_dt, cash_pcts, 
                      [100-c for c in cash_pcts],
                      labels=['现金%', '持仓%'],
                      colors=['#bdc3c7', '#3498db'], alpha=0.8)
        ax3.set_title('资产配置比例（收盘后）', fontweight='bold')
        ax3.set_ylabel('占比 %')
        ax3.set_ylim(0, 100)
        ax3.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
        ax3.tick_params(axis='x', rotation=45)
        ax3.legend(fontsize=8, loc='upper right')
        ax3.grid(True, alpha=0.3, axis='y')
        
        pdf.savefig(fig); plt.close(fig)
        
        # ═══ 第2页：收益分布+持仓数 ═══
        fig = plt.figure(figsize=(11.69, 8.27))
        
        # 每笔收益
        ax4 = plt.axes([0.06, 0.55, 0.88, 0.38])
        rets = [t['ret'] for t in closed_trades]
        colors = ['#e74c3c' if r<0 else '#2ecc71' for r in rets]
        x_idx = range(len(rets))
        ax4.bar(x_idx, rets, color=colors, width=0.7)
        ax4.axhline(y=0, color='gray', linewidth=0.5)
        avg_r = sum(rets)/len(rets) if rets else 0
        ax4.axhline(y=avg_r, color='blue', linestyle='--', linewidth=0.7, label=f'平均{avg_r:+.1f}%')
        ax4.set_title('每笔交易收益率', fontweight='bold')
        ax4.set_ylabel('收益率 %')
        ax4.set_xticks(range(0, len(rets), max(1, len(rets)//10)))
        ax4.set_xticklabels([closed_trades[i]['buy_date'] for i in range(0, len(rets), max(1, len(rets)//10))], 
                           rotation=45, fontsize=7)
        ax4.grid(True, alpha=0.3, axis='y')
        ax4.legend(fontsize=8)
        
        # 持仓数曲线
        ax5 = plt.axes([0.06, 0.05, 0.42, 0.42])
        ax5.fill_between(dates_dt, 0, pos_counts, alpha=0.4, color='#3498db')
        ax5.plot(dates_dt, pos_counts, 'b-', linewidth=1)
        ax5.axhline(y=1, color='orange', linestyle='--', linewidth=0.5, alpha=0.5)
        ax5.set_title('持仓数量（收盘后）', fontweight='bold')
        ax5.set_ylabel('持仓数')
        ax5.set_ylim(0, max(pos_counts)+1 if pos_counts else 3)
        ax5.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
        ax5.tick_params(axis='x', rotation=45)
        ax5.grid(True, alpha=0.3)
        
        # 收益分布饼图
        ax6 = plt.axes([0.56, 0.05, 0.38, 0.42])
        if rets:
            buckets = {'<-15%':0,'-15~0%':0,'0~10%':0,'10~20%':0,'20~50%':0,'>50%':0}
            for r in rets:
                if r < -15: buckets['<-15%']+=1
                elif r < 0: buckets['-15~0%']+=1
                elif r < 10: buckets['0~10%']+=1
                elif r < 20: buckets['10~20%']+=1
                elif r < 50: buckets['20~50%']+=1
                else: buckets['>50%']+=1
            labels = [f'{k}\n({v}笔)' for k,v in buckets.items() if v>0]
            sizes = [v for v in buckets.values() if v>0]
            colors_pie = ['#e74c3c','#f39c12','#3498db','#2ecc71','#27ae60','#1abc9c']
            ax6.pie(sizes, labels=labels, autopct='%1.0f%%', startangle=90, colors=colors_pie[:len(sizes)])
            ax6.set_title('收益分布', fontweight='bold')
        
        pdf.savefig(fig); plt.close(fig)
        
        # ═══ 第3页起：交易明细 ═══
        per_page = 20
        pages = (len(closed_trades) + per_page - 1) // per_page
        for pg in range(pages):
            fig = plt.figure(figsize=(11.69, 8.27))
            ax = plt.axes([0.02, 0.05, 0.96, 0.88])
            ax.axis('off')
            
            start = pg * per_page
            end = min(start + per_page, len(closed_trades))
            
            ax.set_title(f'交易明细（第{pg+1}/{pages}页）', fontweight='bold', fontsize=14, y=0.98)
            
            hdr = ['#', '股票', '代码', '买入日', '卖出日', '持有d', '买入价', '卖出价', '收益率', '盈亏']
            rows = [hdr]
            for i in range(start, end):
                t = closed_trades[i]
                rows.append([
                    str(i+1), t['name'], t['symbol'],
                    t['buy_date'], t['sell_date'], str(t['hold_days'] if t['hold_days']<900 else '期末'),
                    str(t['buy_price']), str(t['sell_price']),
                    f'{t["ret"]:+.1f}%', f'{t["pnl"]:+.0f}'
                ])
            
            tbl = ax.table(cellText=rows, loc='center', cellLoc='center',
                          colWidths=[0.03,0.07,0.07,0.09,0.09,0.05,0.06,0.06,0.07,0.08])
            tbl.auto_set_font_size(False); tbl.set_fontsize(7)
            for (r,c),cell in tbl.get_celld().items():
                if r==0:
                    cell.set_facecolor('#2c3e50'); cell.set_text_props(color='white', fontweight='bold')
                elif r%2==0:
                    cell.set_facecolor('#f0f0f0')
                if c==8 and r>0:
                    v = rows[r][8]
                    if v.startswith('+'): cell.set_text_props(color='red', fontweight='bold')
                    elif v.startswith('-'): cell.set_text_props(color='green', fontweight='bold')
            
            pdf.savefig(fig); plt.close(fig)
        
        # ═══ 最后2页：月度统计+资金变化表 ═══
        # 按月汇总
        monthly = defaultdict(list)
        for d in daily_log:
            m = d['date'][:7]
            monthly[m].append(d)
        
        fig = plt.figure(figsize=(11.69, 8.27))
        ax = plt.axes([0.02, 0.03, 0.96, 0.90])
        ax.axis('off')
        ax.set_title('月度资金变化', fontweight='bold', fontsize=14, y=0.98)
        
        m_rows = [['月份', '交易日', '期末NAV', '月收益', '现金%', '持仓数', '操作']]
        prev_nav = 200000
        for m in sorted(monthly.keys()):
            entries = monthly[m]
            last = entries[-1]
            first = entries[0]
            month_ret = (last['nav']/prev_nav-1)*100 if prev_nav else 0
            avg_cash = sum(e['cash']/max(e['nav'],1)*100 for e in entries)/len(entries)
            avg_pos = sum(len(e['positions']) for e in entries)/len(entries)
            # 主要操作
            actions = [e['action'] for e in entries if e['action']]
            main_action = actions[-1][:40] if actions else ''
            
            m_rows.append([
                m, str(len(entries)),
                f'{last["nav"]/10000:.2f}万',
                f'{month_ret:+.1f}%',
                f'{avg_cash:.0f}%',
                f'{avg_pos:.1f}只',
                main_action
            ])
            prev_nav = last['nav']
        
        tbl = ax.table(cellText=m_rows, loc='center', cellLoc='center',
                      colWidths=[0.07,0.05,0.08,0.06,0.05,0.05,0.50])
        tbl.auto_set_font_size(False); tbl.set_fontsize(7)
        for (r,c),cell in tbl.get_celld().items():
            if r==0:
                cell.set_facecolor('#2c3e50'); cell.set_text_props(color='white', fontweight='bold')
            elif r%2==0:
                cell.set_facecolor('#f0f0f0')
            if c==3 and r>0:
                v = m_rows[r][3]
                if v.startswith('+'): cell.set_text_props(color='red', fontweight='bold')
                elif v.startswith('-'): cell.set_text_props(color='green', fontweight='bold')
        
        pdf.savefig(fig); plt.close(fig)
    
    print(f'✅ {output_path} 生成完毕（{len(closed_trades)}笔交易）')

gen_pdf('满仓调仓', t1, log1, '/home/ubuntu/trend-shrink-picks/回测报告_满仓调仓.pdf')
gen_pdf('NAV25%×4只', t2, log2, '/home/ubuntu/trend-shrink-picks/回测报告_NAV25%.pdf')

sconn.close()
print('完成！')
