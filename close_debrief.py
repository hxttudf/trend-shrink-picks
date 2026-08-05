#!/usr/bin/env python3
"""尾盘复盘 — 全自动A股情绪+主线+资金复盘报告 (no-agent cron)"""
import sqlite3, json, subprocess, time, sys, re, os
from datetime import date, timedelta, datetime
from collections import Counter, defaultdict

today = date.today().strftime("%Y%m%d")
yesterday = (date.today() - timedelta(days=1)).strftime("%Y%m%d")
day2ago = (date.today() - timedelta(days=2)).strftime("%Y%m%d")

# ── 配置 ──
DB = '/home/ubuntu/databases/wind_data.db'
SDB = '/home/ubuntu/databases/Sequoia选股.db'
TODAY = today

def q(sql, params=()):
    conn = sqlite3.connect(DB)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows
def sq(sql, params=()):
    conn = sqlite3.connect(SDB)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows

# ── 1. 涨停复盘 ──
zt_today = q("SELECT stock_code, stock_name, zt_time, status FROM wind_zt_pool WHERE trade_date=? ORDER BY zt_time", (TODAY,))
dt_today = q("SELECT stock_code, stock_name FROM wind_dt_pool WHERE trade_date=?", (TODAY,))
zt_yest = q("SELECT stock_code, stock_name, zt_time, status FROM wind_zt_pool WHERE trade_date=?", (yesterday,))
dt_yest_q = q("SELECT stock_code, stock_name FROM wind_dt_pool WHERE trade_date=?", (yesterday,))
# 再往前一天
zt_day2 = q("SELECT stock_code, stock_name, zt_time, status FROM wind_zt_pool WHERE trade_date=?", (day2ago,))

zt_now = len(zt_today)
zt_yest_cnt = len(zt_yest)
dt_now = len(dt_today)
dt_yest_cnt = len(dt_yest_q)

zt_codes_today = {r[0] for r in zt_today}
zt_codes_yest = {r[0] for r in zt_yest}
zt_codes_day2 = {r[0] for r in zt_day2}
dt_codes_today = {r[0] for r in dt_today}

# 连板
liangban = []
for code, name, zt_time, status in zt_today:
    streak = 1
    d = TODAY
    while True:
        d_prev = (datetime.strptime(d, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")
        prev_zt = q("SELECT 1 FROM wind_zt_pool WHERE trade_date=? AND stock_code=? AND status>=0", (d_prev, code))
        if prev_zt:
            streak += 1
            d = d_prev
        else:
            break
    liangban.append((name, streak, code))

liangban.sort(key=lambda x: -x[1])
max_lb = liangban[0][1] if liangban else 0

# 连板梯队
lb_detail_parts = []
for n in range(max_lb, 0, -1):
    cnt = sum(1 for _, s, _ in liangban if s == n)
    if cnt:
        names = [nm for nm, s, _ in liangban if s == n]
        lb_detail_parts.append(f"{n}板{cnt}家({','.join(names[:3])})")

# 连板家数
liangban_cnt = len(liangban)
lianban_thick = liangban_cnt

# 昨日涨停今日表现
zt_keep = zt_codes_today & zt_codes_yest
zt_keep_cnt = len(zt_keep)
zt_keep_names = [r[1] for r in zt_today if r[0] in zt_keep]

# 断板票（昨天涨停今天没涨停）
break_zt = zt_codes_yest - zt_codes_today
break_zt_cnt = len(break_zt)
# 其中跌停/大跌的
break_dt = break_zt & dt_codes_today
break_dt_cnt = len(break_dt)

# ── 2. 题材板块分析 ──
all_zt_names = [r[1] for r in zt_today]

hot_industry_detail = ""

# 首次涨停
first_zt = []

# ── 3. 情绪判断 ──
if zt_now >= 80:
    qingxu_stage = '沸点🔥'
elif zt_now >= 50:
    qingxu_stage = '活跃🔥'
elif zt_now >= 30:
    qingxu_stage = '中性'
elif zt_now >= 15:
    qingxu_stage = '低迷❄️'
else:
    qingxu_stage = '冰点🧊'

zt_chg = zt_now - zt_yest_cnt
zt_chg_str = f'+{zt_chg}' if zt_chg > 0 else (str(zt_chg) if zt_chg < 0 else '持平')

dt_chg = dt_now - dt_yest_cnt
dt_chg_str = f'+{dt_chg}' if dt_chg > 0 else (str(dt_chg) if dt_chg < 0 else '持平')

# 前日涨停今日表现
yest_good = zt_yest_cnt

# ── 4. 资金流向 ──
out_top = q("""
    SELECT industry_name, net_flow FROM wind_industry_flows
    WHERE trade_date=? ORDER BY net_flow DESC LIMIT 5
""", (TODAY,))
in_top = q("""
    SELECT industry_name, net_flow FROM wind_industry_flows
    WHERE trade_date=? ORDER BY net_flow ASC LIMIT 5
""", (TODAY,))

out_top_print = '、'.join(f'{s}({f/1e8:.1f}亿)' for s,f in out_top) if out_top else '暂无'
in_top_print = '、'.join(f'{s}({-f/1e8:.1f}亿)' for s,f in in_top) if in_top else '暂无'

outflow_strs = [s for s,f in out_top]

# 成交量估算
total_amt_q = sq("SELECT SUM(turnover) FROM stock_daily WHERE date=?", (TODAY,))
total_amt = f'{total_amt_q[0][0]/1e8:.0f}亿' if total_amt_q and total_amt_q[0][0] else 'N/A'

# 跌停增加触发注意
dt_warning = dt_now - dt_yest_cnt

# 沪深300涨跌
hs300 = q("SELECT change_pct FROM wind_index_snapshots WHERE wind_code='000300.SH' AND trade_date=? LIMIT 1", (TODAY,))
hs300_chg = hs300[0][0] if hs300 else None

# ── 资金流向外部信息（新增） ──
zz = out_top_print if out_top else ''

# 行业资金流入最多的
in_flow_top = out_top[:3] if out_top else []
in_flow_str = '、'.join(f'{s}({f/1e8:.1f}亿)' for s,f in out_top) if out_top else '无明显集中流入'

# ── 5. 市场广度 ──
breadth = q("SELECT up_count, down_count, flat_count FROM wind_market_breadth WHERE trade_date=? LIMIT 1", (TODAY,))
if breadth:
    up, down, flat = breadth[0]
    up_ratio = up / (up + down + flat) * 100 if (up + down + flat) > 0 else 0
    breadth_str = f'上涨{up}家 下跌{down}家 平盘{flat}家（涨跌比{up/ max(down,1):.2f}）'
else:
    breadth_str = ''

# ── 指数收盘 ──
indexes = q("SELECT index_name, change_pct FROM wind_index_snapshots WHERE trade_date=?", (TODAY,))
index_lines = []
for nm, chg in indexes:
    if chg:
        icon = '📈' if float(chg) > 0 else '📉'
        index_lines.append(f'{icon} {nm} {chg}%')

# ── 涨跌停对比 ──
zt_keep_names_str = '、'.join(zt_keep_names[:5]) if zt_keep_names else '无'
break_names = [r[1] for r in zt_today if r[0] not in zt_codes_yest]
break_names_str = '、'.join(r[1] for r in zt_yest if r[0] not in zt_codes_today)[:60]

# ── 前日涨停连板率 ──
lianban_rate = (liangban_cnt / max(zt_now, 1)) * 100

# 今日首板（今天涨停昨天没涨停）
shouban = [(code, name) for code, name, _, _ in zt_today if code not in zt_codes_yest]
shouban_cnt = len(shouban)

# ── 北向资金（无独立表，跳过）──
north_str = ''

# ── 龙虎榜 Top ──
lhb_top = q("""
    SELECT stock_name, total_buy, total_sell FROM wind_lhb
    WHERE trade_date=? ORDER BY (total_buy + total_sell) DESC LIMIT 3
""", (TODAY,))
lhb_lines = [f'{s} 买方{b:.1f}亿/卖方{c:.1f}亿' for s,b,c in lhb_top] if lhb_top else []

# ── 主力资金 ──
zy = q("""
    SELECT stock_name, net_buy FROM wind_lhb
    WHERE trade_date=? ORDER BY ABS(net_buy) DESC LIMIT 3
""", (TODAY,))
zy_lines = []

# ── 最高标连板股 ──
if liangban:
    top_lb = liangban[0]
    top_lb_line = f'最高标：{top_lb[0]}（{top_lb[1]}连板）'
else:
    top_lb_line = '最高标：无'

# 昨日涨停今日断板且跌停
break_dt_names = [r[1] for r in dt_today if r[0] in break_zt]

# ── 趋势票扫描 ──
SIGNAL_DB = '/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db'

trend_lines = []
try:
    t_today = TODAY
    conn = sqlite3.connect(SIGNAL_DB)

    ld = conn.execute("SELECT MAX(date) FROM stock_daily WHERE date<?", (t_today,)).fetchone()
    last_date = ld[0] if ld else None

    if last_date:
        mkt = conn.execute("SELECT AVG(pct_60d) FROM ("
            "SELECT ROUND((a.close - c60.close)/c60.close*100,2) as pct_60d FROM stock_daily a "
            "JOIN stock_daily c60 ON a.symbol=c60.symbol AND c60.date=("
                "SELECT date FROM stock_daily WHERE symbol=a.symbol AND date<=date(a.date,'-60 days') ORDER BY date DESC LIMIT 1"
            ") WHERE a.date=? AND a.close>0 AND c60.close>0)", (last_date,)).fetchone()
        mkt_60 = round(mkt[0], 1) if mkt and mkt[0] else 'N/A'

        # 趋势票: 20日涨3-30%, 60日涨>5%, 且close>ma20>ma60 (多头排列)
        rows = conn.execute("""
            SELECT a.symbol, a.close,
                   ROUND((a.close - b.close)/b.close*100,2) as pct_1d,
                   ROUND((a.close - c20.close)/c20.close*100,2) as pct_20d,
                   ROUND((a.close - c60.close)/c60.close*100,2) as pct_60d
            FROM stock_daily a
            JOIN stock_daily b ON a.symbol=b.symbol AND b.date=(
                SELECT MAX(date) FROM stock_daily WHERE symbol=a.symbol AND date<a.date)
            JOIN stock_daily c20 ON a.symbol=c20.symbol AND c20.date=(
                SELECT date FROM stock_daily WHERE symbol=a.symbol AND date<=date(a.date,'-20 days') ORDER BY date DESC LIMIT 1)
            JOIN stock_daily c60 ON a.symbol=c60.symbol AND c60.date=(
                SELECT date FROM stock_daily WHERE symbol=a.symbol AND date<=date(a.date,'-60 days') ORDER BY date DESC LIMIT 1)
            WHERE a.date=? AND a.close>0
              AND ROUND((a.close - c20.close)/c20.close*100,2) BETWEEN 3 AND 30
              AND ROUND((a.close - c60.close)/c60.close*100,2) > 5
              AND a.close > (SELECT AVG(close) FROM (
                  SELECT close FROM stock_daily WHERE symbol=a.symbol AND date<=a.date ORDER BY date DESC LIMIT 20))
              AND (SELECT AVG(close) FROM (
                  SELECT close FROM stock_daily WHERE symbol=a.symbol AND date<=a.date ORDER BY date DESC LIMIT 20))
                  > (SELECT AVG(close) FROM (
                  SELECT close FROM stock_daily WHERE symbol=a.symbol AND date<=a.date ORDER BY date DESC LIMIT 60))
            ORDER BY ROUND((a.close - c60.close)/c60.close*100,2) DESC
            LIMIT 30
        """, (last_date,)).fetchall()

        if rows:
            # 批量查股票名称
            syms = list(set(r[0] for r in rows))
            name_map = {}
            for i in range(0, len(syms), 500):
                batch = syms[i:i+500]
                ph = ",".join("?" * len(batch))
                for r2 in conn.execute(f"SELECT symbol, name FROM stock_basics WHERE symbol IN ({ph})", batch):
                    name_map[r2[0]] = r2[1]

            main = [(r[0], r[1], r[2], r[3], r[4]) for r in rows if r[0][:2] != '68']
            kechuang = [(r[0], r[1], r[2], r[3], r[4]) for r in rows if r[0][:2] == '68']

            trend_lines.append(f'▶ 主板趋势票（60日涨幅排序，多地{last_date}）:')
            trend_lines.append(f'  全市场60日平均: {mkt_60}%')
            if main:
                for sym, close, p1, p20, p60 in main[:8]:
                    nm = sym.split('.')[0]
                    nme = name_map.get(sym, '')
                    trend_lines.append(f'  {nm} {nme} {close:>8.2f} 日{p1:>+.1f}% 20日{p20:>+.1f}% 60日{p60:>+.1f}%')
            if len(main) > 8:
                trend_lines.append(f'  ...还有{len(main)-8}只')

            if kechuang:
                trend_lines.append(f'')
                trend_lines.append(f'▶ 科创板趋势票:')
                for sym, close, p1, p20, p60 in kechuang[:5]:
                    nm = sym.split('.')[0]
                    nme = name_map.get(sym, '')
                    trend_lines.append(f'  {nm} {nme} {close:>8.2f} 日{p1:>+.1f}% 20日{p20:>+.1f}% 60日{p60:>+.1f}%')
    conn.close()
except Exception as e:
    trend_lines.append(f'（趋势扫描异常: {str(e)[:30]}）')

trend_section = '\n'.join(trend_lines) if trend_lines else '（暂无数据）'

# ── 其它数据 ──
shanghai_bourse = q("SELECT stock_name, net_buy FROM wind_lhb WHERE trade_date=? AND stock_code LIKE '6%' ORDER BY ABS(net_buy) DESC LIMIT 3", (TODAY,))
shenzhen_bourse = q("SELECT stock_name, net_buy FROM wind_lhb WHERE trade_date=? AND stock_code LIKE '0%' ORDER BY ABS(net_buy) DESC LIMIT 3", (TODAY,))

# 龙虎榜买卖方
lhb_buy_sell = q("SELECT stock_name, total_buy, total_sell FROM wind_lhb WHERE trade_date=? AND total_buy>0 AND total_sell>0 ORDER BY (total_buy-total_sell) DESC LIMIT 3", (TODAY,))

# 今日热点概念（表可能不存在）
concepts = ''
try:
    concepts_q = q("""
        SELECT concept_name, stock_count FROM wind_concept_hot
        WHERE trade_date=? ORDER BY stock_count DESC LIMIT 5
    """, (TODAY,))
    concepts = '、'.join(f'{n}({c}只)' for n,c in concepts_q) if concepts_q else ''
except Exception:
    concepts = ''

# ── Compose report ──
lines = []
header_date = date.today().strftime("%Y-%m-%d")
lines.append(f'📊 {header_date} 尾盘复盘')
lines.append('')

# 指数：只展示上证+深证+创业板+科创50
idx_short = []
for l in index_lines:
    idx_short.append(l)
if len(idx_short) > 4:
    idx_short = idx_short[:4]
if idx_short:
    lines.append('【指数】' + ' | '.join(idx_short))
    lines.append('')

# 今日总览：涨跌比→涨停→跌停→最高板→情绪
overview_parts = [breadth_str]

# 涨停
zt_parts = [f'涨停{zt_now}家']
if zt_now > 0:
    # 连板 vs 首板
    if liangban_cnt > 0:
        max_lb_str = f'高标{liangban[0][0]}({liangban[0][1]}板)' if liangban else ''
        zt_parts.append(f'1板{shouban_cnt}')
        if liangban_cnt > 1:
            zt_parts.append(f'连板{liangban_cnt}家')
            zt_parts.append(f'最高{max_lb}')
        zt_parts.append(f'前日{zt_yest_cnt}家')
    else:
        zt_parts.append(f'前日{zt_yest_cnt}家')
# 行情判断
if zt_now > zt_yest_cnt * 1.3:
    zt_parts.append('🔥升温')
elif zt_now < zt_yest_cnt * 0.7:
    zt_parts.append('❄降温')

overview_parts.append('｜'.join(zt_parts))

# 跌停
if dt_now > 0:
    overview_parts.append(f'跌停{dt_now}家')
    if dt_chg_str.startswith('+'):
        overview_parts.append('⚠风险上升')

# 情绪
overview_parts.append(f'情绪{str(qingxu_stage).replace("沸点🔥","🔥沸点").replace("中性","◻中性").replace("冰点","🧊冰点")}')

lines.append('｜'.join(overview_parts))
lines.append('')

# 资金特征（简略）
fund_parts = []
if total_amt and total_amt != 'N/A':
    fund_parts.append(f'成交{total_amt}')
if zt_now > zt_yest_cnt:
    fund_parts.append(f'放量{zt_now-zt_yest_cnt}家')
else:
    fund_parts.append(f'缩量{abs(zt_now-zt_yest_cnt)}家')
if fund_parts:
    lines.append(' '.join(fund_parts))

# 龙虎榜（如果有）
if lhb_lines:
    for l in lhb_lines[:2]:
        lines.append(f'  {l}')
    lines.append('')

# 高标解析（核心信号）
if liangban:
    lines.append(f'高标{liangban[0][0]}({liangban[0][1]}板) 昨日涨停{zt_yest_cnt}家，今连板{liangban_cnt}家，首板{shouban_cnt}家，断板{break_zt_cnt}家')
else:
    lines.append(f'今日无连板 昨日涨停{zt_yest_cnt}家，首板{shouban_cnt}家')
lines.append('')

# 明日关注（3条以内，有实质内容）
watch_items = []
if liangban:
    watch_items.append(f'{liangban[0][0]}能否继续晋级')
if zt_now > 0:
    watch_items.append(f'涨停是否维持{zt_now}家以上')
if dt_now > 3:
    watch_items.append(f'跌停数{dt_now}是否续增')
if not watch_items:
    watch_items.append('关注开盘方向选择')

lines.append(f'关注: {" | ".join(watch_items)}')
lines.append('')

# ── 牛（熊趋势分析 ──
lines.append('📊 市场趋势(综合诊断)')
conn_mkt = sqlite3.connect(SDB)
for sym, name in [('000001.SH','上证'), ('399006.SZ','创业板'), ('000688.SH','科创50')]:
    rows = conn_mkt.execute("SELECT date, close FROM stock_daily WHERE symbol=? AND close>0 ORDER BY date", (sym,)).fetchall()
    if len(rows) < 250: continue
    p = [r[1] for r in rows[-500:]]
    cur = p[-1]
    ma5=sum(p[-5:])/5; ma10=sum(p[-10:])/10; ma20=sum(p[-20:])/20; ma60=sum(p[-60:])/60; ma250=sum(p[-250:])/250
    yh=max(p[-250:]); yl=min(p[-250:])
    fh=(cur/yh-1)*100; fl=(cur/yl-1)*100
    
    if fh<=-20: base="🔴技术熊市"
    elif fl>=20: base="🟢技术牛市"
    else: base="⚪常规区间"
    
    if cur>ma5>ma10>ma20>ma60: ma_s="多头排列↑"
    elif cur<ma5<ma10<ma20<ma60: ma_s="空头排列↓"
    elif cur>ma60 and ma20>ma60: ma_s="牛市中回调" if cur<ma20 else "多头延续"
    elif cur<ma60 and ma20<ma60: ma_s="熊市中反弹" if cur>ma20 else "空头延续"
    elif cur>ma20>ma60: ma_s="短线转强"
    elif cur<ma20<ma60: ma_s="短线转弱"
    else: ma_s="均线缠绕"
    
    line_s="MA60之上(偏牛)" if cur>ma60 else "MA60之下(偏熊)"
    yr_s="年线上方" if cur>ma250 else "年线下方"
    lines.append(f'  {name}: {cur:.0f} ({base}) MA5={ma5:.0f} MA20={ma20:.0f} MA60={ma60:.0f} | {ma_s} | {line_s} | {yr_s}')
conn_mkt.close()
lines.append('')

print('\n'.join(lines))

