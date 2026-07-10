#!/usr/bin/env python3
"""趋势缩量选股 — 交互式回测平台"""
import sqlite3, os, io, base64, json
from datetime import datetime, timedelta, date
from collections import defaultdict
import streamlit as st
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

plt.rcParams['font.sans-serif'] = ['WenQuanYi Zen Hei']
plt.rcParams['axes.unicode_minus'] = False

TDB = "/home/ubuntu/databases/trend_picks.db"
SDB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"
IMG_DIR = "/home/ubuntu/trend-shrink-picks/report_images"
os.makedirs(IMG_DIR, exist_ok=True)

STRATEGY_NAMES = {
    'original': '原版', 'premium_a': '极品A',
    'premium_b': '极品B', 'ultra_shrink': '超缩量'
}
STRAT_NAME_TO_ID = {v: k for k, v in STRATEGY_NAMES.items()}

# ── 数据获取 ──

@st.cache_data(ttl=60)
def get_strategies():
    conn = sqlite3.connect(TDB)
    rows = conn.execute("SELECT id, name FROM strategies").fetchall()
    conn.close()
    return {r[1]: r[0] for r in rows}

@st.cache_data(ttl=60)
def get_today_signals():
    today = date.today().strftime('%Y-%m-%d')
    conn = sqlite3.connect(TDB)
    rows = conn.execute("""
        SELECT dp.date, s.name as strategy, dp.symbol, dp.name as stock_name,
               dp.close_qfq, dp.dist_ma20, dp.vol_ratio, dp.pct_20d,
               dp.buy_price, dp.ma20, dp.ma60, dp.volume
        FROM daily_picks dp
        JOIN strategies s ON dp.strategy_id=s.id
        WHERE dp.date=?
        ORDER BY dp.strategy_id
    """, (today,)).fetchall()
    conn.close()
    return rows

@st.cache_data(ttl=60)
def get_date_range():
    conn = sqlite3.connect(TDB)
    row = conn.execute("SELECT MIN(date), MAX(date) FROM daily_picks").fetchone()
    conn.close()
    return row[0] or '2024-01-01', row[1] or date.today().strftime('%Y-%m-%d')

def get_signals_for_backtest(strategy_names, start_date, end_date):
    """获取指定策略和时间范围内的信号（去重+主板过滤）"""
    strat_ids = [STRAT_NAME_TO_ID[n] for n in strategy_names if n in STRAT_NAME_TO_ID]
    if not strat_ids:
        return []
    
    placeholders = ','.join('?' for _ in strat_ids)
    conn = sqlite3.connect(TDB)
    raw = conn.execute(f"""
        SELECT dp.date, dp.symbol, dp.name, dp.buy_price
        FROM daily_picks dp
        JOIN strategies s ON dp.strategy_id=s.id
        WHERE s.id IN ({placeholders})
          AND dp.date >= ? AND dp.date <= ?
        ORDER BY dp.date
    """, (*strat_ids, start_date, end_date)).fetchall()
    conn.close()
    
    # 去重
    seen = set()
    data = []
    for r in raw:
        k = (r[0], r[1])
        if k in seen:
            continue
        seen.add(k)
        # 沪深主板过滤
        prefix = r[1][:3]
        if prefix not in ('600','601','603','605','000','001','002','003'):
            continue
        data.append({'d': r[0], 's': r[1], 'n': r[2], 'bp': r[3] or 0})
    return data


# ── 回测引擎 ──

def run_backtest(strategy_names, start_date, end_date, initial_capital=200000):
    """完整回测：NAV25%/只×4只，续期20天，有多少买多少"""
    signals = get_signals_for_backtest(strategy_names, start_date, end_date)
    if not signals:
        return None
    
    # 获取K线
    cs = sqlite3.connect(SDB)
    
    def get_kl(sig):
        bd = datetime.strptime(sig['d'], '%Y-%m-%d')
        rows = cs.execute(
            "SELECT date, close_qfq FROM stock_daily WHERE symbol=? AND date>=? AND date<=? ORDER BY date",
            (sig['s'], bd.strftime('%Y-%m-%d'), (bd + timedelta(days=85)).strftime('%Y-%m-%d'))
        ).fetchall()
        if not rows or len(rows) < 3 or not sig['bp'] or sig['bp'] <= 0:
            return None
        return [{'d': r[0], 'c': r[1]} for r in rows if r[1] and r[1] > 0]
    
    items = []
    pc = defaultdict(lambda: {})
    ads = set()
    
    for sig in signals:
        k = get_kl(sig)
        if k:
            items.append({'sig': sig, 'kl': k})
            for x in k:
                ads.add(x['d'])
                pc[sig['s']][x['d']] = x['c']
    
    if not items:
        cs.close()
        return None
    
    ad = sorted(ads)
    sbd = defaultdict(list)
    for item in items:
        sbd[item['sig']['d']].append(item)
    
    # ── 模拟 ──
    cash = initial_capital
    pf = []  # 持仓列表
    trades = []
    daily_log = []
    dup_renew = 0
    dup_skip = 0
    
    for date_idx, cur_date in enumerate(ad):
        # 当日价格
        today_c = {}
        for p in pf:
            c = pc.get(p['sym'], {}).get(cur_date)
            if c:
                today_c[p['sym']] = c
        
        prev_nav = cash + sum(p['ev'] for p in pf)
        
        # 到期卖出
        i = 0
        while i < len(pf):
            p = pf[i]
            c = today_c.get(p['sym'])
            if c is None:
                i += 1
                continue
            p['hc'] = p.get('hc', 0) + 1
            
            expire_days = p.get('extended', 20)
            if p['hc'] >= expire_days:
                ev = p['ev'] * (c / p['bp']) if p['bp'] > 0 else p['ev']
                ret = (c / p['bp'] - 1) * 100 if p['bp'] > 0 else 0
                cash += ev
                trades.append({
                    'n': p['n'], 's': p['sym'],
                    'ret': round(ret, 1), 'pnl': round(ev - p['ev'], 2),
                    'buy': p['d'], 'sell': cur_date, 'hc': p['hc']
                })
                pf.pop(i)
            else:
                p['lp'] = c
                i += 1
        
        # 新信号
        if cur_date in sbd:
            nav = cash + sum(
                p['ev'] * (today_c.get(p['sym'], p.get('lp', p['bp'])) / p['bp']) if p['bp'] > 0 else p['ev']
                for p in pf
            )
            target = nav * 0.25
            
            for item in sbd[cur_date]:
                sig = item['sig']
                
                # 检查是否已持有
                existing = None
                for p in pf:
                    if p['sym'] == sig['s']:
                        existing = p
                        break
                
                if existing:
                    existing['hc'] = 0
                    existing['extended'] = 20
                    dup_renew += 1
                    continue
                
                # 新开仓
                if len(pf) < 4:
                    buy_amt = min(target, cash)
                    if buy_amt > 1000:
                        bp = sig['bp']
                        cost = bp * 0.001
                        cash -= buy_amt
                        pf.append({
                            'sym': sig['s'], 'n': sig['n'], 'bp': bp + cost,
                            'd': sig['d'], 'ev': buy_amt, 'lp': bp + cost, 'hc': 0
                        })
        
        # 日终记录
        nav = cash
        positions = []
        for p in pf:
            cp = today_c.get(p['sym']) or p.get('lp', p['bp'])
            cv = p['ev'] * (cp / p['bp']) if p['bp'] > 0 else p['ev']
            ret = (cp / p['bp'] - 1) * 100 if p['bp'] > 0 else 0
            positions.append({
                'n': p['n'], 's': p['sym'], 'ev': round(p['ev'], 2),
                'cv': round(cv, 2), 'ret': round(ret, 1), 'hc': p['hc']
            })
            nav += cv
        
        daily_log.append({
            'd': cur_date, 'nav': round(nav, 2), 'cash': round(cash, 2),
            'pos': positions, 'pnl': round(nav - prev_nav, 2), 'pc': len(positions)
        })
    
    # 清仓
    for p in pf:
        cp = pc.get(p['sym'], {}).get(ad[-1], p.get('lp', p['bp']))
        cash += p['ev'] * (cp / p['bp']) if p['bp'] > 0 else p['ev']
    
    cs.close()
    
    final = cash
    total_ret = (final / initial_capital - 1) * 100
    years = (datetime.strptime(ad[-1], '%Y-%m-%d') - datetime.strptime(ad[0], '%Y-%m-%d')).days / 365.25
    cagr = ((final / initial_capital) ** (1 / years) - 1) * 100 if years > 0 else 0
    closed = [t for t in trades if t.get('ret') is not None]
    wins = sum(1 for t in closed if t['ret'] > 0)
    total_pnl = sum(t['pnl'] for t in closed)
    
    return {
        'signals': len(signals),
        'items': len(items),
        'final': final, 'total_ret': total_ret, 'cagr': cagr,
        'trades': closed, 'wins': wins, 'total_pnl': total_pnl,
        'daily_log': daily_log, 'trading_days': len(ad),
        'dup_renew': dup_renew,
        'start_date': ad[0], 'end_date': ad[-1],
        'initial_capital': initial_capital,
        'pf': pf, 'pc': dict(pc), 'ad': ad
    }


# ── 图表生成 ──

def generate_charts(result):
    """生成4张图表，返回base64编码"""
    daily_log = result['daily_log']
    closed = result['trades']
    initial = result['initial_capital']
    final = result['final']
    
    dates_dt = [datetime.strptime(d['d'], '%Y-%m-%d') for d in daily_log]
    navs = [d['nav'] for d in daily_log]
    cash_vals = [d['cash'] for d in daily_log]
    pnls = [d['pnl'] for d in daily_log]
    
    charts = {}
    
    # 1. 资产曲线
    fig, ax = plt.subplots(figsize=(10, 3.5))
    ax.plot(dates_dt, navs, 'b-', lw=1.5, label='总资产')
    ax.plot(dates_dt, cash_vals, 'orange', lw=0.8, alpha=0.6, label='现金')
    ax.axhline(y=initial, color='gray', ls='--', lw=0.5, alpha=0.4)
    ax.fill_between(dates_dt, initial, navs, alpha=0.1, color='green' if final > initial else 'red')
    ax.set_title('资产曲线', fontsize=13, fontweight='bold')
    ax.set_ylabel('金额（万）')
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, p: f'{x/10000:.0f}'))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax.tick_params(axis='x', rotation=30)
    ax.grid(True, alpha=0.3); ax.legend(fontsize=9)
    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=100); buf.seek(0)
    charts['equity'] = base64.b64encode(buf.read()).decode()
    plt.close(fig)
    
    # 2. 每日盈亏
    fig, ax = plt.subplots(figsize=(10, 3))
    colors = ['#e74c3c' if p < 0 else '#2ecc71' for p in pnls]
    ax.bar(dates_dt, pnls, color=colors, width=1.5)
    ax.axhline(y=0, color='gray', lw=0.5)
    ax.set_title('每日盈亏', fontsize=13, fontweight='bold')
    ax.set_ylabel('盈亏（元）')
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax.tick_params(axis='x', rotation=30)
    ax.grid(True, alpha=0.3, axis='y')
    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=100); buf.seek(0)
    charts['pnl'] = base64.b64encode(buf.read()).decode()
    plt.close(fig)
    
    # 3. 持仓数
    fig, ax = plt.subplots(figsize=(10, 2.5))
    pcs = [d['pc'] for d in daily_log]
    ax.fill_between(dates_dt, 0, pcs, alpha=0.4, color='#3498db')
    ax.plot(dates_dt, pcs, 'b-', lw=1)
    ax.set_title('每日持仓数量', fontsize=13, fontweight='bold')
    ax.set_ylabel('持仓数')
    ax.set_ylim(0, max(pcs) + 1 if pcs else 3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax.tick_params(axis='x', rotation=30)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=100); buf.seek(0)
    charts['positions'] = base64.b64encode(buf.read()).decode()
    plt.close(fig)
    
    # 4. 交易收益分布
    if closed:
        fig, ax = plt.subplots(figsize=(10, 3))
        rets = [t['ret'] for t in closed]
        colors2 = ['#e74c3c' if r < 0 else '#2ecc71' for r in rets]
        ax.bar(range(len(rets)), rets, color=colors2, width=0.7)
        ax.axhline(y=0, color='gray', lw=0.5)
        avgr = sum(rets) / len(rets)
        ax.axhline(y=avgr, color='blue', ls='--', lw=0.7, label=f'平均{avgr:+.1f}%')
        ax.set_title('每笔交易收益率', fontsize=13, fontweight='bold')
        ax.set_ylabel('收益率%')
        ax.set_xticks(range(0, len(rets), max(1, len(rets) // 6)))
        labels = [closed[i]['buy'] for i in range(0, len(rets), max(1, len(rets) // 6))]
        ax.set_xticklabels(labels, rotation=45, fontsize=8)
        ax.grid(True, alpha=0.3, axis='y')
        ax.legend(fontsize=9)
        plt.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=100); buf.seek(0)
        charts['trades'] = base64.b64encode(buf.read()).decode()
        plt.close(fig)
    
    return charts


# ── Streamlit UI ──

st.set_page_config(
    page_title="趋势缩量回测平台",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 侧边栏
with st.sidebar:
    st.title("📊 趋势缩量选股")
    st.caption("交互式回测平台")
    
    min_date, max_date = get_date_range()
    
    tab_mode = st.radio("功能", ["回测", "今日信号", "信号查询"])
    
    if tab_mode == "回测":
        st.divider()
        st.subheader("回测参数")
        
        start_date = st.date_input(
            "起始日期",
            datetime.strptime(min_date, '%Y-%m-%d').date() if min_date else date(2024, 1, 1),
            min_value=datetime.strptime(min_date, '%Y-%m-%d').date() if min_date else date(2024, 1, 1),
            max_value=datetime.strptime(max_date, '%Y-%m-%d').date() if max_date else date.today()
        )
        end_date = st.date_input(
            "结束日期",
            datetime.strptime(max_date, '%Y-%m-%d').date() if max_date else date.today(),
            min_value=datetime.strptime(min_date, '%Y-%m-%d').date() if min_date else date(2024, 1, 1),
            max_value=datetime.strptime(max_date, '%Y-%m-%d').date() if max_date else date.today()
        )
        
        st.subheader("策略选择")
        col1, col2 = st.columns(2)
        with col1:
            use_original = st.checkbox("原版", value=False)
            use_premium_a = st.checkbox("极品A", value=False)
        with col2:
            use_premium_b = st.checkbox("极品B", value=True)
            use_ultra = st.checkbox("超缩量", value=True)
        
        capital = st.number_input("起始资金", value=200000, step=50000, format="%d")
        
        run_btn = st.button("🚀 运行回测", type="primary", use_container_width=True)

# 主页面
if tab_mode == "今日信号":
    st.header("📡 今日信号")
    signals = get_today_signals()
    if signals:
        df = pd.DataFrame(signals, columns=[
            '日期', '策略', '代码', '名称', '收盘价', '距MA20%', '量比', '20日涨幅%',
            '买入价', 'MA20', 'MA60', '成交量'
        ])
        df['距MA20%'] = df['距MA20%'].apply(lambda x: f'{x:.1f}%')
        df['20日涨幅%'] = df['20日涨幅%'].apply(lambda x: f'{x:.1f}%')
        df['量比'] = df['量比'].apply(lambda x: f'{x:.2f}')
        df['收盘价'] = df['收盘价'].apply(lambda x: f'{x:.2f}')
        df['买入价'] = df['买入价'].apply(lambda x: f'{x:.2f}')
        df['MA20'] = df['MA20'].apply(lambda x: f'{x:.2f}')
        df['MA60'] = df['MA60'].apply(lambda x: f'{x:.2f}')
        st.dataframe(df, use_container_width=True, hide_index=True)
        
        st.divider()
        st.subheader("策略分布")
        strat_count = signals_df = pd.DataFrame(signals, columns=['日期', '策略', '代码', '名称', '收盘价', '距MA20%', '量比', '20日涨幅%', '买入价', 'MA20', 'MA60', '成交量'])
        sc = strat_count.groupby('策略').size().reset_index(name='数量')
        col1, col2, col3, col4 = st.columns(4)
        for i, row in sc.iterrows():
            [col1, col2, col3, col4][i % 4].metric(row['策略'], f"{row['数量']}只")
    else:
        st.info(f"📭 今日({date.today().strftime('%Y-%m-%d')})无信号数据，可能未到15:22或休市")

elif tab_mode == "信号查询":
    st.header("🔍 信号查询")
    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        q_date = st.text_input("查询日期 (YYYY-MM-DD，留空=全部)", value="")
    with col2:
        q_strat = st.selectbox("策略", ["全部", "原版", "极品A", "极品B", "超缩量"])
    with col3:
        q_limit = st.number_input("最多条数", value=50, min_value=1, max_value=500)
    
    query_btn = st.button("查询")
    
    if query_btn:
        conn = sqlite3.connect(TDB)
        conn.row_factory = sqlite3.Row
        
        where = []
        params = []
        if q_date:
            where.append("dp.date=?")
            params.append(q_date)
        if q_strat and q_strat != "全部":
            strat_id = STRAT_NAME_TO_ID.get(q_strat)
            if strat_id:
                where.append("dp.strategy_id=?")
                params.append(strat_id)
        
        where_sql = " AND ".join(where) if where else "1=1"
        rows = conn.execute(f"""
            SELECT dp.date, s.name as strategy, dp.symbol, dp.name as stock_name,
                   dp.close_qfq, dp.dist_ma20, dp.vol_ratio, dp.pct_20d,
                   dp.ret_t5, dp.ret_t10, dp.ret_t20, dp.buy_price
            FROM daily_picks dp
            JOIN strategies s ON dp.strategy_id=s.id
            WHERE {where_sql}
            ORDER BY dp.date DESC, dp.strategy_id
            LIMIT ?
        """, (*params, q_limit)).fetchall()
        conn.close()
        
        if rows:
            df = pd.DataFrame(rows, columns=[
                '日期', '策略', '代码', '名称', '收盘价', '距MA20%', '量比', '20日涨幅%',
                'T5%', 'T10%', 'T20%', '买入价'
            ])
            df['距MA20%'] = df['距MA20%'].apply(lambda x: f'{x:.1f}%' if x is not None else '-')
            df['20日涨幅%'] = df['20日涨幅%'].apply(lambda x: f'{x:.1f}%' if x is not None else '-')
            df['量比'] = df['量比'].apply(lambda x: f'{x:.2f}' if x is not None else '-')
            df['T5%'] = df['T5%'].apply(lambda x: f'{x:+.1f}%' if x is not None else '-')
            df['T10%'] = df['T10%'].apply(lambda x: f'{x:+.1f}%' if x is not None else '-')
            df['T20%'] = df['T20%'].apply(lambda x: f'{x:+.1f}%' if x is not None else '-')
            df['收盘价'] = df['收盘价'].apply(lambda x: f'{x:.2f}' if x is not None else '-')
            df['买入价'] = df['买入价'].apply(lambda x: f'{x:.2f}' if x is not None else '-')
            
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.caption(f"共 {len(rows)} 条记录")
        else:
            st.warning("无匹配信号")

elif tab_mode == "回测":
    st.header("📊 策略回测")
    
    if 'run_btn' not in dir() or not run_btn:
        st.info("请在左侧设置参数后点击「运行回测」")
    
    if 'run_btn' in dir() and run_btn:
        selected = []
        if use_original: selected.append('原版')
        if use_premium_a: selected.append('极品A')
        if use_premium_b: selected.append('极品B')
        if use_ultra: selected.append('超缩量')
        
        if not selected:
            st.warning("请至少选择一个策略")
            st.stop()
        
        if start_date >= end_date:
            st.warning("起始日期必须早于结束日期")
            st.stop()
        
        with st.spinner(f"回测中：{', '.join(selected)} ({start_date} ~ {end_date})..."):
            result = run_backtest(
                selected,
                start_date.strftime('%Y-%m-%d'),
                end_date.strftime('%Y-%m-%d'),
                capital
            )
        
        if result is None:
            st.error("回测失败：所选参数范围内无信号数据")
            st.stop()
        
        # ── 总览指标 ──
        st.subheader("📊 总览")
        
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.metric("最终资产", f"{result['final']/10000:.1f}万",
                      f"{result['total_ret']:+.1f}%")
        with col2:
            st.metric("年化CAGR", f"{result['cagr']:.1f}%")
        with col3:
            wr = result['wins'] / len(result['trades']) * 100 if result['trades'] else 0
            st.metric("胜率", f"{wr:.0f}%",
                      f"{result['wins']}/{len(result['trades'])}笔")
        with col4:
            avg_ret = sum(t['ret'] for t in result['trades']) / len(result['trades']) if result['trades'] else 0
            st.metric("平均收益", f"{avg_ret:+.1f}%",
                      f"最高{max(t['ret'] for t in result['trades']):+.1f}%")
        with col5:
            st.metric("续期处理", f"{result['dup_renew']}次")
        
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.metric("信号总数", f"{result['signals']}个",
                      f"日均{result['signals']/result['trading_days']:.1f}")
        with col2:
            st.metric("交易日", f"{result['trading_days']}天")
        with col3:
            tot_pnl = sum(t['pnl'] for t in result['trades'])
            st.metric("总盈亏", f"{tot_pnl/10000:+.2f}万")
        with col4:
            max_r = max(t['ret'] for t in result['trades']) if result['trades'] else 0
            min_r = min(t['ret'] for t in result['trades']) if result['trades'] else 0
            st.metric("单笔最高/低", f"{max_r:+.1f}% / {min_r:+.1f}%")
        with col5:
            avg_hc = sum(t['hc'] for t in result['trades']) / len(result['trades']) if result['trades'] else 0
            st.metric("平均持仓天数", f"{avg_hc:.0f}d")
        
        st.divider()
        
        # ── 图表 ──
        charts = generate_charts(result)
        
        tab1, tab2 = st.tabs(["📈 图表", "📝 交易明细"])
        
        with tab1:
            col1, col2 = st.columns(2)
            with col1:
                st.image(f"data:image/png;base64,{charts.get('equity', '')}", use_container_width=True)
            with col2:
                st.image(f"data:image/png;base64,{charts.get('pnl', '')}", use_container_width=True)
            
            col1, col2 = st.columns(2)
            with col1:
                st.image(f"data:image/png;base64,{charts.get('positions', '')}", use_container_width=True)
            with col2:
                st.image(f"data:image/png;base64,{charts.get('trades', '')}", use_container_width=True)
            
            # ├─ 盈亏日历 ──
            st.divider()
            st.subheader("🗓 盈亏日历")
            cal_data = defaultdict(dict)
            for d in result['daily_log']:
                ym = d['d'][:7]
                day = int(d['d'][8:10])
                cal_data[ym][day] = d['pnl']
            
            pnl_style = """
                <style>
                .cal-table {border-collapse:collapse;font-size:11px;width:100%;}
                .cal-table th {background:#2c3e50;color:white;padding:4px;text-align:center;}
                .cal-table td {padding:3px;text-align:center;border:1px solid #ecf0f1;min-width:22px;font-size:10px;}
                .day-num {font-size:8px;color:#999;}
                .pnl-big-pos {background:#c0392b;color:white;font-weight:bold;}
                .pnl-pos {background:#e74c3c;color:white;}
                .pnl-small-pos {background:#f1948a;}
                .pnl-zero {background:#f0f0f0;}
                .pnl-small-neg {background:#a9dfbf;}
                .pnl-neg {background:#27ae60;color:white;}
                .pnl-big-neg {background:#1e8449;color:white;font-weight:bold;}
                .cal-label {font-size:12px;color:#7f8c8d;margin-bottom:8px;}
                </style>
            """
            st.markdown(pnl_style, unsafe_allow_html=True)
            st.markdown(
                '<span class="cal-label">颜色：'
                '<span style="background:#c0392b;color:white;padding:1px 4px;">大赚</span> '
                '<span style="background:#e74c3c;color:white;padding:1px 4px;">中赚</span> '
                '<span style="background:#f1948a;padding:1px 4px;">小赚</span> '
                '<span style="background:#f0f0f0;padding:1px 4px;">持平</span> '
                '<span style="background:#a9dfbf;padding:1px 4px;">小亏</span> '
                '<span style="background:#27ae60;color:white;padding:1px 4px;">中亏</span> '
                '<span style="background:#1e8449;color:white;padding:1px 4px;">大亏</span>'
                '</span>',
                unsafe_allow_html=True
            )
            
            for ym in sorted(cal_data.keys()):
                days = cal_data[ym]
                first = datetime.strptime(ym + '-01', '%Y-%m-%d')
                fw = first.weekday()
                
                # determine month days
                m = int(ym[5:7])
                y = int(ym[:4])
                if m in (1,3,5,7,8,10,12):
                    md = 31
                elif m == 2:
                    md = 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28
                else:
                    md = 30
                
                st.markdown(f'<b style="font-size:13px;">{ym}</b>', unsafe_allow_html=True)
                
                html = '<table class="cal-table"><tr><th>一</th><th>二</th><th>三</th><th>四</th><th>五</th><th>六</th><th>日</th></tr><tr>'
                for _ in range(fw):
                    html += '<td></td>'
                for day in range(1, md + 1):
                    pnl = days.get(day)
                    cls = 'pnl-zero'
                    tip = ''
                    if pnl is not None:
                        tip = f'{ym}-{day:02d} {pnl:+.0f}元'
                        if pnl > 5000:
                            cls = 'pnl-big-pos'
                        elif pnl > 1000:
                            cls = 'pnl-pos'
                        elif pnl > 0:
                            cls = 'pnl-small-pos'
                        elif pnl == 0:
                            cls = 'pnl-zero'
                        elif pnl > -1000:
                            cls = 'pnl-small-neg'
                        elif pnl > -5000:
                            cls = 'pnl-neg'
                        else:
                            cls = 'pnl-big-neg'
                    html += f'<td class="{cls}" title="{tip}"><span class="day-num">{day}</span></td>'
                    if (fw + day) % 7 == 0:
                        html += '</tr><tr>'
                html += '</tr></table>'
                st.markdown(html, unsafe_allow_html=True)
            
            # ── 月度统计 ──
            st.divider()
            st.subheader("📆 月度统计")
            monthly = defaultdict(lambda: {'pnl': 0, 'trades': 0, 'win': 0})
            prev = capital
            for d in result['daily_log']:
                m = d['d'][:7]
                if monthly[m].get('begin') is None:
                    monthly[m]['begin'] = prev
                monthly[m]['end'] = d['nav']
                monthly[m]['pnl'] += d['pnl']
                prev = d['nav']
            for t in result['trades']:
                m = t['sell'][:7]
                monthly[m]['trades'] += 1
                if t['ret'] > 0:
                    monthly[m]['win'] += 1
            
            monthly_data = []
            for m in sorted(monthly.keys()):
                md = monthly[m]
                begin = md.get('begin', capital)
                end = md['end']
                ret = (end / begin - 1) * 100
                wr_m = f'{md["win"] / md["trades"] * 100:.0f}%' if md['trades'] else '-'
                monthly_data.append({
                    '月份': m, '起始NAV': f'{begin/10000:.2f}万',
                    '期末NAV': f'{end/10000:.2f}万', '月收益': ret,
                    '交易': md['trades'], '胜率': wr_m
                })
            
            df_m = pd.DataFrame(monthly_data)
            # format月收益
            df_m['月收益'] = df_m['月收益'].apply(lambda x: f'{x:+.1f}%')
            st.dataframe(df_m, use_container_width=True, hide_index=True)
        
        with tab2:
            # ── 交易明细 ──
            st.subheader("📝 交易明细")
            if result['trades']:
                trade_data = []
                for i, t in enumerate(result['trades'], 1):
                    trade_data.append({
                        '#': i, '股票': t['n'], '代码': t['s'],
                        '买入': t['buy'], '卖出': t['sell'],
                        '持有d': t['hc'], '收益率': f'{t["ret"]:+.1f}%',
                        '盈亏(元)': f'{t["pnl"]:+.0f}'
                    })
                df_t = pd.DataFrame(trade_data)
                # color rows
                def color_ret(val):
                    if val.startswith('+'):
                        return 'color:#e74c3c;'
                    elif val.startswith('-'):
                        return 'color:#27ae60;'
                    return ''
                
                st.dataframe(df_t, use_container_width=True, hide_index=True)
                
                # 下载交易明细
                csv = df_t.to_csv(index=False).encode('utf-8-sig')
                st.download_button(
                    "📥 下载交易明细CSV",
                    csv,
                    f"交易明细_{start_date}_{end_date}.csv",
                    "text/csv"
                )
            else:
                st.info("无已完成交易")
            
            st.divider()
            
            # ── 每日持仓 ──
            st.subheader("🏷 每日持仓")
            pos_days = [d for d in result['daily_log'] if d['pc'] > 0]
            if pos_days:
                pos_data = []
                for d in pos_days:
                    tags = ' | '.join(
                        f'{p["n"]}({p["ret"]:+.1f}%)' for p in d['pos']
                    )
                    pos_data.append({
                        '日期': d['d'], 'NAV': f'{d["nav"]/10000:.2f}万',
                        '现金': f'{d["cash"]/10000:.2f}万',
                        '持仓': tags, '数量': d['pc']
                    })
                df_p = pd.DataFrame(pos_data)
                st.dataframe(df_p, use_container_width=True, hide_index=True)
            else:
                st.info("回测期间无持仓记录")
        
        st.divider()
        
        # ── 回测摘要信息 ──
        strat_label = ' + '.join(selected)
        st.caption(
            f"策略：{strat_label} | "
            f"区间：{result['start_date']} ~ {result['end_date']} | "
            f"初始资金：{capital/10000:.0f}万 | "
            f"仓位：NAV25%/只×上限4只 | 持有期：20天到期/续期"
        )
