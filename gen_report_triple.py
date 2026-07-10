#!/usr/bin/env python3
"""回测：极品A+极品B+超缩量 + 续期20天 + 有多少买多少 + HTML报告"""
import sqlite3
from datetime import datetime, timedelta
from collections import defaultdict
import json, os

TDB,SDB='/home/ubuntu/databases/trend_picks.db','/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db'
ct=sqlite3.connect(TDB); cs=sqlite3.connect(SDB)

# 获取极品A+极品B+超缩量 所有信号
raw=ct.execute("""
    SELECT dp.date, dp.symbol, dp.name
    FROM daily_picks dp 
    JOIN strategies s ON dp.strategy_id=s.id 
    WHERE s.name IN ('极品A','极品B','超缩量') 
    ORDER BY dp.date
""").fetchall()
ct.close()

# 去重 + 沪深主板过滤
seen=set(); data=[]
for r in raw:
    k=(r[0],r[1])
    if k in seen: continue
    seen.add(k)
    if r[1][:3] not in ('600','601','603','605','000','001','002','003'): continue
    ct2=sqlite3.connect(TDB)
    bp=ct2.execute("SELECT buy_price FROM daily_picks WHERE date=? AND symbol=? LIMIT 1",(r[0],r[1])).fetchone()
    ct2.close()
    data.append({'d':r[0],'s':r[1],'n':r[2],'bp':bp[0] if bp else 0})

print(f'总信号（去重沪深主板）: {len(data)}个')

# 统计策略分布
raw_all=ct=sqlite3.connect(TDB)
strat_count=raw_all.execute("""
    SELECT s.name, COUNT(DISTINCT dp.date||dp.symbol)
    FROM daily_picks dp JOIN strategies s ON dp.strategy_id=s.id
    WHERE s.name IN ('极品A','极品B','超缩量')
    GROUP BY s.name
""").fetchall()
raw_all.close()
for sn, cnt in strat_count:
    print(f'  {sn}: {cnt}个')

# K线数据
def get_kl(sig):
    bd=datetime.strptime(sig['d'],'%Y-%m-%d')
    rows=cs.execute("SELECT date,open,close,close_qfq FROM stock_daily WHERE symbol=? AND date>=? AND date<=? ORDER BY date",
                    (sig['s'],bd.strftime('%Y-%m-%d'),(bd+timedelta(days=85)).strftime('%Y-%m-%d'))).fetchall()
    if not rows or len(rows)<3: return None
    bp=sig['bp']
    if not bp or bp<=0: return None
    return [{'d':r[0],'c':r[3]} for r in rows if r[2] and r[2]>0 and r[3] and r[3]>0]

items=[]; pc=defaultdict(lambda:{})
ads=set()
for sig in data:
    k=get_kl(sig)
    if k:
        items.append({'sig':sig,'kl':k})
        for x in k:
            ads.add(x['d'])
            pc[sig['s']][x['d']]=x['c']

ad=sorted(ads); sbd=defaultdict(list)
for item in items:
    sbd[item['sig']['d']].append(item)
print(f'交易日:{len(ad)}个')

# ── 模拟 ──
cash=200000; pf=[]; trades=[]; daily_log=[]
dup_renew=0; dup_skip=0

for date in ad:
    today_c={}
    for p in pf:
        c=pc.get(p['sym'],{}).get(date)
        if c: today_c[p['sym']]=c
    
    prev_nav=cash+sum(p['ev'] for p in pf)
    
    # 到期卖出
    i=0
    while i<len(pf):
        p=pf[i]; c=today_c.get(p['sym'])
        if c is None: i+=1; continue
        p['hc']=p.get('hc',0)+1
        
        expire_days = p.get('extended', 20)  # 续期后的天数
        if p['hc'] >= expire_days:
            ev=p['ev']*(c/p['bp']) if p['bp']>0 else p['ev']
            ret=(c/p['bp']-1)*100 if p['bp']>0 else 0
            cash+=ev
            trades.append({'n':p['n'],'s':p['sym'],'ret':round(ret,1),'pnl':round(ev-p['ev'],2),
                          'buy':p['d'],'sell':date,'hc':p['hc']})
            pf.pop(i)
        else:
            p['lp']=c; i+=1
    
    # 新信号
    if date in sbd:
        nav=cash+sum(p['ev']*(today_c.get(p['sym'],p.get('lp',p['bp']))/p['bp']) if p['bp']>0 else p['ev'] for p in pf)
        target=nav*0.25
        
        for item in sbd[date]:
            sig=item['sig']
            
            # 检查是否已持有
            existing=None
            for p in pf:
                if p['sym']==sig['s']:
                    existing=p; break
            
            if existing:
                # 持有中再次命中 → 续期20天
                existing['hc']=0
                existing['extended']=20
                dup_renew+=1
                continue
            
            # 新开仓 — 有多少买多少
            if len(pf)<4:
                buy_amt=min(target,cash)
                if buy_amt>1000:
                    bp=sig['bp']; cost=bp*0.001
                    cash-=buy_amt
                    pf.append({'sym':sig['s'],'n':sig['n'],'bp':bp+cost,'d':sig['d'],
                              'ev':buy_amt,'lp':bp+cost,'hc':0})
    
    # 日终
    nav=cash
    positions=[]
    for p in pf:
        cp=today_c.get(p['sym']) or p.get('lp',p['bp'])
        cv=p['ev']*(cp/p['bp']) if p['bp']>0 else p['ev']
        ret=(cp/p['bp']-1)*100 if p['bp']>0 else 0
        positions.append({'n':p['n'],'s':p['sym'],'ev':round(p['ev'],2),'cv':round(cv,2),
                         'ret':round(ret,1),'hc':p['hc']})
        nav+=cv
    
    daily_log.append({'d':date,'nav':round(nav,2),'cash':round(cash,2),
                      'pos':positions,'pnl':round(nav-prev_nav,2),'pc':len(positions)})

for p in pf:
    cp=pc.get(p['sym'],{}).get(ad[-1],p.get('lp',p['bp']))
    cash+=p['ev']*(cp/p['bp']) if p['bp']>0 else p['ev']

final=cash; total_ret=(final/200000-1)*100; cagr=((final/200000)**(1/2.1)-1)*100
closed=[t for t in trades if t.get('ret') is not None]
wins=sum(1 for t in closed if t['ret']>0)
total_pnl=sum(t['pnl'] for t in closed)
cs.close()

print(f'\n最终:{final/10000:.2f}万 CAGR={cagr:.1f}% 交易:{len(closed)}笔 胜率:{wins/len(closed)*100:.0f}%')
print(f'续期处理:{dup_renew}次')

# ── 生成图表 ──
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as mticker
plt.rcParams['font.sans-serif']=['WenQuanYi Zen Hei']
plt.rcParams['axes.unicode_minus']=False

img_dir='/home/ubuntu/trend-shrink-picks/report_images'
os.makedirs(img_dir,exist_ok=True)
dates_dt=[datetime.strptime(d['d'],'%Y-%m-%d') for d in daily_log]

# 资产曲线
fig=plt.figure(figsize=(12,5))
ax=plt.axes()
ax.plot(dates_dt,[d['nav'] for d in daily_log],'b-',lw=1.5,label='总资产')
ax.plot(dates_dt,[d['cash'] for d in daily_log],'orange',lw=0.8,alpha=0.6,label='现金')
ax.axhline(y=200000,color='gray',ls='--',lw=0.5,alpha=0.4)
ax.fill_between(dates_dt,200000,[d['nav'] for d in daily_log],alpha=0.1,color='green' if final>200000 else 'red')
ax.set_title('资产曲线',fontsize=14,fontweight='bold')
ax.set_ylabel('金额（万）')
ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x,p: f'{x/10000:.0f}'))
ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
ax.tick_params(axis='x',rotation=45); ax.grid(True,alpha=0.3); ax.legend(fontsize=10)
plt.tight_layout(); plt.savefig(f'{img_dir}/equity.png',dpi=120); plt.close()

# 每日盈亏
fig=plt.figure(figsize=(12,4))
ax=plt.axes()
pnls=[d['pnl'] for d in daily_log]
colors=['#e74c3c' if p<0 else '#2ecc71' for p in pnls]
ax.bar(dates_dt,pnls,color=colors,width=1.5)
ax.axhline(y=0,color='gray',lw=0.5)
ax.set_title('每日盈亏',fontsize=14,fontweight='bold')
ax.set_ylabel('盈亏（元）')
ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
ax.tick_params(axis='x',rotation=45); ax.grid(True,alpha=0.3,axis='y')
plt.tight_layout(); plt.savefig(f'{img_dir}/daily_pnl.png',dpi=120); plt.close()

# 持仓数
fig=plt.figure(figsize=(12,3))
ax=plt.axes()
pcs=[d['pc'] for d in daily_log]
ax.fill_between(dates_dt,0,pcs,alpha=0.4,color='#3498db')
ax.plot(dates_dt,pcs,'b-',lw=1)
ax.set_title('每日持仓数量',fontsize=14,fontweight='bold')
ax.set_ylabel('持仓数'); ax.set_ylim(0,max(pcs)+1 if pcs else 3)
ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
ax.tick_params(axis='x',rotation=45); ax.grid(True,alpha=0.3)
plt.tight_layout(); plt.savefig(f'{img_dir}/positions.png',dpi=120); plt.close()

# 交易收益
rets=[t['ret'] for t in closed]
fig=plt.figure(figsize=(12,4))
ax=plt.axes()
colors2=['#e74c3c' if r<0 else '#2ecc71' for r in rets]
ax.bar(range(len(rets)),rets,color=colors2,width=0.7)
ax.axhline(y=0,color='gray',lw=0.5)
avgr=sum(rets)/len(rets)
ax.axhline(y=avgr,color='blue',ls='--',lw=0.7,label=f'平均{avgr:+.1f}%')
ax.set_title('每笔交易收益率',fontsize=14,fontweight='bold')
ax.set_ylabel('收益率%')
ax.set_xticks(range(0,len(rets),max(1,len(rets)//8)))
ax.set_xticklabels([closed[i]['buy'] for i in range(0,len(rets),max(1,len(rets)//8))],rotation=45,fontsize=8)
ax.grid(True,alpha=0.3,axis='y'); ax.legend()
plt.tight_layout(); plt.savefig(f'{img_dir}/trade_returns.png',dpi=120); plt.close()

# ── HTML ──
# 月度
monthly=defaultdict(lambda:{'pnl':0,'trades':0,'win':0})
prev=200000
for d in daily_log:
    m=d['d'][:7]
    if monthly[m].get('begin') is None: monthly[m]['begin']=prev
    monthly[m]['end']=d['nav']
    monthly[m]['pnl']+=d['pnl']
    prev=d['nav']
for t in closed:
    m=t['sell'][:7]
    monthly[m]['trades']+=1
    if t['ret']>0: monthly[m]['win']+=1

cal_data=defaultdict(dict)
for d in daily_log:
    ym=d['d'][:7]; day=int(d['d'][8:10])
    cal_data[ym][day]=d['pnl']

# 每日持仓中有些日子很多数据，只保留非空
pos_days=[d for d in daily_log if d['pc']>0]

html=f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>极品A+极品B+超缩量 — 回测报告</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{font-family:'WenQuanYi Zen Hei','Microsoft YaHei',sans-serif;background:#f5f6fa;color:#2c3e50;}}
.header{{background:linear-gradient(135deg,#2c3e50,#3498db);color:white;padding:30px;text-align:center;}}
.header h1{{font-size:28px;margin-bottom:5px;}}
.header p{{font-size:14px;opacity:0.9;}}
.container{{max-width:1200px;margin:0 auto;padding:20px;}}
.card{{background:white;border-radius:8px;box-shadow:0 2px 10px rgba(0,0,0,0.08);padding:20px;margin-bottom:20px;}}
.card h2{{font-size:18px;color:#2c3e50;margin-bottom:15px;border-left:4px solid #3498db;padding-left:10px;}}
.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;}}
.metric{{text-align:center;padding:12px;background:#f8f9fa;border-radius:8px;}}
.metric .value{{font-size:22px;font-weight:bold;color:#2c3e50;}}
.metric .label{{font-size:12px;color:#7f8c8d;margin-top:3px;}}
.positive{{color:#e74c3c;font-weight:bold;}}
.negative{{color:#27ae60;font-weight:bold;}}
img{{max-width:100%;height:auto;border-radius:4px;}}
table{{width:100%;border-collapse:collapse;font-size:13px;}}
th{{background:#2c3e50;color:white;padding:8px;text-align:center;font-weight:normal;}}
td{{padding:6px 8px;text-align:center;border-bottom:1px solid #ecf0f1;}}
tr:hover{{background:#f8f9fa;}}
.pnl-big-pos{{background:#c0392b;color:white;font-weight:bold;}}
.pnl-pos{{background:#e74c3c;color:white;}}
.pnl-small-pos{{background:#f1948a;}}
.pnl-zero{{background:#f0f0f0;}}
.pnl-small-neg{{background:#a9dfbf;}}
.pnl-neg{{background:#27ae60;color:white;}}
.pnl-big-neg{{background:#1e8449;color:white;font-weight:bold;}}
.cal-table th{{background:#2c3e50;color:white;padding:4px;font-size:11px;}}
.cal-table td{{padding:3px;text-align:center;border:1px solid #ecf0f1;min-width:24px;font-size:11px;}}
.day-num{{font-size:9px;color:#999;}}
.position-tag{{display:inline-block;padding:2px 6px;margin:1px;border-radius:3px;font-size:11px;}}
.pos-green{{background:#d5f5e3;color:#1e8449;}}
.pos-red{{background:#fadbd8;color:#c0392b;}}
</style>
</head>
<body>
<div class="header">
<h1>趋势缩量选股 — 回测报告</h1>
<p>策略：极品A+极品B+超缩量 | 标的：沪深主板 | 持有中续期20天 | 仓位：有多少买多少</p>
</div>
<div class="container">
<div class="card">
<h2>📊 总览</h2>
<div class="metrics">
<div class="metric"><div class="value">{final/10000:.1f}<span style="font-size:14px">万</span></div><div class="label">最终资产</div></div>
<div class="metric"><div class="value positive">{total_ret:+.1f}%</div><div class="label">总收益率</div></div>
<div class="metric"><div class="value positive">{cagr:.1f}%</div><div class="label">年化CAGR</div></div>
<div class="metric"><div class="value">{len(closed)}<span style="font-size:14px">笔</span></div><div class="label">交易笔数</div></div>
<div class="metric"><div class="value positive">{wins/len(closed)*100:.0f}%</div><div class="label">胜率</div></div>
<div class="metric"><div class="value">{total_pnl/10000:+.2f}<span style="font-size:14px">万</span></div><div class="label">总盈亏</div></div>
<div class="metric"><div class="value positive">{sum(t['ret'] for t in closed)/len(closed):+.1f}%</div><div class="label">平均收益</div></div>
<div class="metric"><div class="value positive">{max(t['ret'] for t in closed):+.1f}%</div><div class="label">单笔最高</div></div>
<div class="metric"><div class="value negative">{min(t['ret'] for t in closed):+.1f}%</div><div class="label">单笔最低</div></div>
<div class="metric"><div class="value">{dup_renew}<span style="font-size:14px">次</span></div><div class="label">续期处理</div></div>
</div>
</div>
<div class="card"><h2>📈 资产曲线</h2><img src="report_images/equity.png"></div>
<div class="card"><h2>📅 每日盈亏</h2><img src="report_images/daily_pnl.png"></div>
<div class="card"><h2>📋 每日持仓数量</h2><img src="report_images/positions.png"></div>
<div class="card"><h2>🗓 盈亏日历</h2>
<p style="font-size:13px;color:#7f8c8d;margin-bottom:10px;">颜色：<span style="background:#c0392b;color:white;padding:1px 4px;">大赚</span> <span style="background:#e74c3c;color:white;padding:1px 4px;">中赚</span> <span style="background:#f1948a;padding:1px 4px;">小赚</span> <span style="background:#f0f0f0;padding:1px 4px;">持平</span> <span style="background:#a9dfbf;padding:1px 4px;">小亏</span> <span style="background:#27ae60;color:white;padding:1px 4px;">中亏</span> <span style="background:#1e8449;color:white;padding:1px 4px;">大亏</span></p>'''

for ym in sorted(cal_data.keys()):
    days=cal_data[ym]
    first=datetime.strptime(ym+'-01','%Y-%m-%d')
    fw=first.weekday()
    md=31 if ym[5:7] in ('01','03','05','07','08','10','12') else (29 if ym[5:7]=='02' and int(ym[:4])%4==0 else 28 if ym[5:7]=='02' else 30)
    html+=f'<h3 style="font-size:14px;margin:10px 0 5px;">{ym}</h3>'
    html+='<table class="cal-table"><tr><th>一</th><th>二</th><th>三</th><th>四</th><th>五</th><th>六</th><th>日</th></tr><tr>'
    for i in range(fw): html+='<td></td>'
    for day in range(1,md+1):
        pnl=days.get(day)
        cls='pnl-zero'; tooltip=''
        if pnl is not None:
            tooltip=f'{ym}-{day:02d} 盈亏:{pnl:+.0f}元'
            if pnl>5000: cls='pnl-big-pos'
            elif pnl>1000: cls='pnl-pos'
            elif pnl>0: cls='pnl-small-pos'
            elif pnl==0: cls='pnl-zero'
            elif pnl>-1000: cls='pnl-small-neg'
            elif pnl>-5000: cls='pnl-neg'
            else: cls='pnl-big-neg'
        html+=f'<td class="{cls}" title="{tooltip}"><span class="day-num">{day}</span></td>'
        if (i+day)%7==0: html+='</tr><tr>'
    html+='</tr></table>'

html+='''<div class="card"><h2>📆 月度统计</h2><table><tr><th>月份</th><th>起始NAV</th><th>期末NAV</th><th>月收益</th><th>交易</th><th>胜率</th></tr>'''
prev=200000
for m in sorted(monthly.keys()):
    md=monthly[m]
    begin=md.get('begin',prev)
    end=md['end']
    ret=(end/begin-1)*100
    wr_m=f'{md["win"]/md["trades"]*100:.0f}%' if md['trades'] else '-'
    rcls='positive' if ret>=0 else 'negative'
    html+=f'<tr><td>{m}</td><td>{begin/10000:.2f}万</td><td>{end/10000:.2f}万</td><td class="{rcls}">{ret:+.1f}%</td><td>{md["trades"]}</td><td>{wr_m}</td></tr>'
    prev=end
html+='</table></div>'

html+='<div class="card"><h2>📝 交易明细</h2><table><tr><th>#</th><th>股票</th><th>代码</th><th>买入</th><th>卖出</th><th>持有d</th><th>收益%</th><th>盈亏(元)</th></tr>'
for i,t in enumerate(closed,1):
    cls='positive' if t['ret']>0 else 'negative'
    html+=f'<tr><td>{i}</td><td>{t["n"]}</td><td>{t["s"]}</td><td>{t["buy"]}</td><td>{t["sell"]}</td><td>{t["hc"]}</td><td class="{cls}">{t["ret"]:+.1f}%</td><td>{t["pnl"]:+.0f}</td></tr>'
html+='</table></div>'

html+='<div class="card"><h2>🏷 每日持仓</h2><table><tr><th>日期</th><th>NAV</th><th>现金</th><th>持仓</th></tr>'
for d in pos_days:
    tags=''
    for p in d['pos']:
        rc='pos-green' if p['ret']>=0 else 'pos-red'
        tags+=f'<span class="position-tag {rc}">{p["n"]}<br><small>{p["ret"]:+.1f}%/{p["hc"]}d</small></span> '
    html+=f'<tr><td>{d["d"]}</td><td>{d["nav"]/10000:.2f}万</td><td>{d["cash"]/10000:.2f}万</td><td>{tags}</td></tr>'
html+='</table></div>'

html+='<div class="card"><h2>📊 交易收益分布</h2><img src="report_images/trade_returns.png"></div>'
html+='</div><div style="text-align:center;padding:20px;color:#95a5a6;font-size:12px;">回测区间：2024-05-07 ~ 2026-07-10 | 仅供参考</div></body></html>'

with open('/home/ubuntu/trend-shrink-picks/回测报告_三策略合并.html','w') as f: f.write(html)
print(f'✅ HTML: /home/ubuntu/trend-shrink-picks/回测报告_三策略合并.html')
