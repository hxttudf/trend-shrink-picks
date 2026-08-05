#!/usr/bin/env python3
"""午盘复盘 — no_agent 模式，融合 market-close-review 框架，实时行情+akshare+DB"""
import sqlite3, socket, subprocess, pandas as pd
from datetime import date

DB = '/home/ubuntu/databases/wind_data.db'
today = date.today().strftime('%Y%m%d')

def qt_raw(code):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect(('qt.gtimg.cn', 80))
        s.send(f'GET /q={code} HTTP/1.0\r\nHost: qt.gtimg.cn\r\nUser-Agent: curl/7.68\r\nConnection: close\r\n\r\n'.encode())
        data = b''
        while True:
            d = s.recv(4096)
            if not d: break
            data += d
        s.close()
        raw = data.split(b'\r\n\r\n', 1)[1].decode('gbk', 'ignore').split('"')[1]
        f = raw.split('~')
        return f[3], f[32]
    except:
        return 'N/A', 'N/A'

def q(sql, params=()):
    conn = sqlite3.connect(DB)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows

# ── 上午实时指数 ──
idx_live = {
    '上证指数': qt_raw('sh000001'), '深证成指': qt_raw('sz399001'),
    '创业板指': qt_raw('sz399006'), '科创50': qt_raw('sh000688'),
    '沪深300': qt_raw('sh000300'),
}

# ── 今日涨停/跌停/连板：akshare实时 ──
import akshare as ak
import os, urllib3
os.environ.setdefault('AKSHARE_HTTPS_VERIFY', 'false')
urllib3.disable_warnings()

zt_now, dt_now = 0, 0
lb_data = []
zt_top = []
max_lb = 0

def _ak_zt(date_str):
    zt, dt = 0, 0
    df = None
    try:
        df = ak.stock_zt_pool_em(date=date_str)
        if df is not None: zt = len(df)
    except Exception:
        pass
    try:
        dt_df = ak.stock_zt_pool_dtgc_em(date=date_str)
        if dt_df is not None: dt = len(dt_df)
    except Exception:
        pass
    return df, zt, dt

zt_df, zt_now, dt_now = _ak_zt(today)

if zt_df is not None and '连板数' in zt_df.columns:
    lb_sorted = zt_df[zt_df['连板数'] >= 2].sort_values('连板数', ascending=False)
    for _, r in lb_sorted.iterrows():
        day = int(r['连板数'])
        lb_data.append((r['名称'], day, r['代码']))
        if day > max_lb: max_lb = day
    zt_top = [(r['名称'], int(r['连板数']), r['代码']) for _, r in zt_df.sort_values('连板数', ascending=False).head(3).iterrows() if int(r['连板数']) >= 2]

def normalize_net(net_val):
    """Wind DB net_flow 单位归一化 → 亿元
    历史数据单位混杂(元/百元/万元)，按量级启发判断"""
    if net_val is None or net_val == 0:
        return 0
    av = abs(net_val)
    if av > 1000000:      # >100万 → 存的是原始元
        return net_val / 100000000
    elif av > 1000:        # 1千~100万 → 存的是百元
        return net_val / 10000000
    else:                  # <1000 → 存的是万元(修正后的正确单位)
        return net_val / 10000
last_td = q("SELECT MAX(trade_date) FROM wind_zt_pool WHERE trade_date<?", (today,))[0][0]
zt_yest = q("SELECT COUNT(*) FROM wind_zt_pool WHERE trade_date=?", (last_td,))[0][0] if last_td else 0
dt_yest = q("SELECT COUNT(*) FROM wind_dt_pool WHERE trade_date=?", (last_td,))[0][0] if last_td else 0
br_yest = q("SELECT up_count, down_count FROM wind_market_breadth WHERE trade_date=? ORDER BY id DESC LIMIT 1", (last_td,))
up_y, down_y = br_yest[0] if br_yest else (0, 0)
amt_y = q("SELECT total_amount FROM wind_market_breadth WHERE trade_date=? ORDER BY id DESC LIMIT 1", (last_td,))
amt_y_str = f"{amt_y[0][0]/1e8:.0f}亿" if amt_y and amt_y[0][0] else '?'

# 昨日行业资金流参考（Wind DB优先，akshare兜底）
in_top_y = []
# ① Wind DB（归一化）
wind_in = q("""SELECT industry_name, net_flow FROM wind_all_industry_flows
               WHERE trade_date=? AND net_flow>0 ORDER BY net_flow DESC LIMIT 3""", (last_td,)) if last_td else []
in_top_y = [(r[0], normalize_net(r[1])) for r in wind_in if r[0] and normalize_net(r[1]) >= 0.5]
# ② Wind无数据 → akshare实时（当日快照）
if not in_top_y:
    try:
        ydf = ak.stock_fund_flow_industry(symbol="即时")
        ydf['净额'] = pd.to_numeric(ydf['净额'], errors='coerce')
        ypos = ydf[ydf['净额'] > 0].sort_values('净额', ascending=False)
        in_top_y = [(r['行业'], r['净额']) for _, r in ypos.head(3).iterrows() if r['净额'] >= 1]
    except Exception:
        pass

# ── 格式化指数 ──
def idx_line(key, label):
    v = idx_live.get(key)
    if not v: return ''
    p, c = v
    if p == 'N/A' or c == 'N/A': return ''
    arrow = '涨' if float(c) >= 0 else '跌'
    return f'{label} {p} {arrow}{c}%'

lines = []
for k, lbl in [('上证指数','上证'),('深证成指','深证'),('创业板指','创业板'),('科创50','科创50'),('沪深300','沪深300')]:
    l = idx_line(k, lbl)
    if l: lines.append(l)
idx_str = '\n'.join(lines)

# ── 分析段 ──
# 判断上午强弱：从指数涨跌
sh_p = idx_live.get('上证指数', ('0','0'))[1]
sh_is_up = sh_p != 'N/A' and float(sh_p) >= 0

# 情绪（基于今日涨停实时）
if zt_now >= 50: qingxu = '情绪活跃'
elif zt_now >= 30: qingxu = '情绪一般'
elif zt_now >= 15: qingxu = '情绪偏低'
else: qingxu = '情绪冰点'

# 连板梯队
lb_strs = [(n, d) for n, d, _ in lb_data if d >= 3]
lb_detail = '、'.join([f'{n}{d}连板' for n, d in lb_strs]) if lb_strs else '暂无'
lianban_thick = len([x for x in lb_data if x[1] >= 5])
lianban_mid = len([x for x in lb_data if 3 <= x[1] <= 4])

# 上午环境判断
if sh_is_up and zt_now > zt_yest:
    huan_jing = '偏强'
elif not sh_is_up and zt_now < zt_yest:
    huan_jing = '偏弱'
else:
    huan_jing = '震荡'

# 主线：今日实时涨停行业的分布
# 用涨停股所属行业推断上午热点
try:
    if '所属行业' in zt_df.columns:
        hot_inds = zt_df['所属行业'].value_counts().head(3)
        hot_ind_str = ' / '.join([f'{ind}({cnt})' for ind, cnt in hot_inds.items()])
    else:
        hot_ind_str = '待盘后确认'
except:
    hot_ind_str = '待盘后确认'

# 持续性评估
if zt_now >= 30 and max_lb >= 4: chixu = '较强'
elif zt_now >= 20 and max_lb >= 3: chixu = '一般'
else: chixu = '偏弱'

zt_chg = zt_now - zt_yest
zt_chg_mark = f'{"+" if zt_chg>=0 else ""}{zt_chg}'

# 资金流格式化
in_flow_str = ' / '.join([f'{r[0]}+{r[1]:.1f}亿' for r in in_top_y]) if in_top_y else '暂无数据'

# ── 热点龙头鱼身处分析 ──
SEQUOIA_DB = '/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db'
def sq(sql, params=()):
    conn = sqlite3.connect(SEQUOIA_DB)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows

hot_analysis = ''
hot_themes_text = '暂无'
try:
    leaders = q("""
        SELECT z.stock_name, z.stock_code, COALESCE(s.streak_days, 1) as sd
        FROM wind_zt_pool z
        LEFT JOIN wind_streak s ON z.stock_code = s.stock_code AND s.trade_date = z.trade_date
        WHERE z.trade_date = ?
        ORDER BY sd DESC
        LIMIT 6
    """, (today,))
    
    if leaders:
        leader_lines = []
        for name, code, streak in leaders:
            seq_code = code.strip()
            if not seq_code.endswith('.SH') and not seq_code.endswith('.SZ'):
                seq_code = seq_code + ('.SH' if seq_code.startswith('6') or seq_code.startswith('9') else '.SZ')
            
            cum_ret = None
            vol_ratio = None
            try:
                rows_c = sq("SELECT close_qfq FROM stock_daily WHERE symbol=? AND date=? AND close_qfq>0 ORDER BY date DESC LIMIT 1",
                           (seq_code, today_dash))
                if rows_c:
                    cur_price = rows_c[0][0]
                    rows_p = sq("SELECT close_qfq FROM stock_daily WHERE symbol=? AND date<=? AND close_qfq>0 ORDER BY date DESC LIMIT 5, 1",
                               (seq_code, today_dash))
                    if rows_p:
                        start_price = rows_p[0][0]
                        if start_price > 0: cum_ret = (cur_price / start_price - 1) * 100
                
                rows_v = sq("SELECT volume / AVG(volume) OVER (ORDER BY date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) FROM stock_daily WHERE symbol=? AND date=? AND volume>0 ORDER BY date DESC LIMIT 1",
                           (seq_code, today_dash))
                if rows_v and rows_v[0][0]: vol_ratio = rows_v[0][0]
            except: pass
            
            if cum_ret is not None:
                if cum_ret < 15: stage = '鱼头🐟'
                elif cum_ret < 50: stage = '鱼身🔥'
                else: stage = '鱼尾⚠️'
            else:
                if streak <= 2: stage = '鱼头🐟'
                elif streak <= 4: stage = '鱼身🔥'
                else: stage = '鱼尾⚠️'
            
            detail = ''
            if cum_ret is not None: detail += f'涨幅{cum_ret:.0f}%'
            if vol_ratio and vol_ratio > 1.5: detail += ' 放量' if not detail else ' | 放量'
            
            leader_lines.append(f"  {name}（{streak}板）{stage}  {detail}" if detail else f"  {name}（{streak}板）{stage}")
        
        hot_analysis = '\n'.join(leader_lines)
    
    top_themes = q("""
        SELECT industry_name, net_flow FROM wind_all_industry_flows
        WHERE trade_date=? AND net_flow>0 ORDER BY net_flow DESC LIMIT 5
    """, (today,))
    if top_themes:
        def normalize_net(net_val):
            if net_val is None or net_val == 0: return 0
            av = abs(net_val)
            if av > 1000000: return net_val / 100000000
            elif av > 1000: return net_val / 10000000
            else: return net_val / 10000
        theme_lines = [f"  {r[0]}（资金{abs(normalize_net(r[1])):.0f}亿）" for r in top_themes if abs(normalize_net(r[1])) >= 1]
        hot_themes_text = '\n'.join(theme_lines) if theme_lines else '暂无明确主攻方向'
    else:
        hot_themes_text = '暂无明确主攻方向'
except Exception as e:
    hot_analysis = ''
    hot_themes_text = '暂无明确主攻方向'

# ── 输出 ──
out = f"""【1.上午市场全景】
{idx_str}
成交预估中 | 涨停{zt_now}家（前日全天{zt_yest}家，{zt_chg_mark}） | 跌停{dt_now}家
前日涨跌比{up_y}:{down_y} | 前日成交{amt_y_str}
涨停行业分布：{hot_ind_str}

【2.上午主线与轮动】
▶ 上午盘面：{huan_jing}
▶ 热点方向：{hot_ind_str}
▶ 情绪判断：{qingxu}，涨停{zt_now}家较前日全天{zt_yest}家{zt_chg_mark}
▶ 连板高标：{'最高' + str(max_lb) + '连板' if max_lb else '暂无'} | {lianban_thick}只≥5板 / {lianban_mid}只3-4板

【3.核心个股】
▶ 情绪龙头：{f'{zt_top[0][0]}（{zt_top[0][1]}连板）' if zt_top else '暂无'}
   {zt_top[1][0] if len(zt_top)>1 else ''}
   {zt_top[2][0] if len(zt_top)>2 else ''}
▶ 连板梯队：{f'最高{max_lb}板' if max_lb else '无连板'} | {lb_detail}
▶ 涨停{zt_now}家 vs 前日全天{zt_yest}家 → {'上午已超昨日，情绪强' if zt_now > zt_yest else '上午不到昨日一半，相对平淡'}

【4.情绪与资金】
▶ 情绪周期：{qingxu}
▶ 上午涨停{zt_now}家，{'超' if zt_now > zt_yest else '不达'}前日全天水平
▶ 行业资金参考：{in_flow_str}
▶ 持续性评估：{chixu}

【5.上午最重要的边际变化】
▶ 涨停数：{zt_now}家（前日全天{zt_yest}家）
▶ 连板高度：{f'最高{max_lb}连板' if max_lb else '无高标'}，{'梯队完整' if lianban_thick >= 2 else '高标有限'}
▶ 跌停{dt_now}家（前日{dt_yest}家），亏钱效应{'扩散' if dt_now > dt_yest else '收敛'}

【6.下午重点观察】
1. 涨停能否进一步扩围（超过前日{zt_yest}家）
2. {zt_top[0][0] + '能否回封/继续晋级' if zt_top else '新方向能否发酵'}
3. 下午指数能否稳住，防止冲高回落
4. 北向资金动向

【7.午盘结论】
上午市场{huan_jing}，涨停{zt_now}家{'超' if zt_now > zt_yest else '不及'}前日水平。
{f'连板高度{max_lb}板，{lianban_thick}只≥5板、{lianban_mid}只3-4板。' if max_lb else '无明显高标。'}
{'下午若涨停持续扩围可适当积极，否则控制仓位防范回落。' if zt_now >= 30 else '上午情绪偏弱，下午观察能否修复。'}"""
print(f"```\n{out}\n```")
