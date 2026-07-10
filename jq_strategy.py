# 聚宽策略 — 趋势缩量选股
# 策略：极品B + 超缩量 | 仓位：NAV25%×4只 | 持有20交易日 | 无调仓无止损
# 标的：沪深主板
# 买入：信号日次日开盘 | 卖出：持有20个交易日后收盘

def initialize(context):
    g.max_positions = 4
    g.position_pct = 0.25
    g.hold_days = 20
    g.hold_info = {}
    g.candidates = []
    g.verbose = False  # 改为True可看每级过滤
    
    # 极品B
    g.pb = {'dl':12,'dh':25,'vr':0.30,'pl':3,'ph':15,'ma60':True}
    # 超缩量
    g.us = {'dl':10,'dh':20,'vr':0.15,'pl':3,'ph':15,'ma60':True}
    
    run_daily(screen_stocks, time='after_close')
    run_daily(trade, time='open')

def screen_stocks(context):
    today = context.current_dt.strftime('%Y-%m-%d')
    log.info(f'[{today} 选股]')
    
    all_stocks = get_all_securities(['stock']).index.tolist()
    log.info(f'  全市场: {len(all_stocks)}只')
    
    # 只用基础字段，不用high_limit/low_limit（聚宽可能返回异常值）
    FIELDS = ['close', 'volume', 'money']
    
    candidates = []
    s_all, s_board, s_data, s_pass = 0, 0, 0, 0
    
    for stock in all_stocks:
        s_all += 1
        if s_all % 1000 == 0 and g.verbose:
            log.info(f'  扫描进度: {s_all}/{len(all_stocks)}')
        
        # ── 板块过滤 ──
        code3 = stock[0:3]
        if code3 in ('300','301','688','689'): continue
        if stock[0] in ('4','8','9'): continue
        s_board += 1
        
        # ── 获取60日数据 ──
        df = attribute_history(stock, 60, '1d', FIELDS, df=True, skip_paused=True)
        if df is None or len(df) < 60:
            continue
        s_data += 1
        
        close = df['close'].values
        volume = df['volume'].values
        
        # 检查是否有NaN
        import numpy as np
        if np.isnan(close).any() or np.isnan(volume).any():
            continue
        
        today_c = close[-1]
        today_v = volume[-1]
        
        # ── 指标计算 ──
        ma20 = close[-20:].mean()
        if ma20 <= 0: continue
        
        dist_ma20 = (today_c / ma20 - 1) * 100
        
        avg_v20 = volume[-21:-1].mean()
        if avg_v20 <= 0: continue
        vol_ratio = today_v / avg_v20
        
        p20 = close[-21]
        if p20 <= 0: continue
        pct_20d = (today_c / p20 - 1) * 100
        
        ma60 = close[-60:].mean()
        
        # 基础条件检查
        if dist_ma20 < g.us['dl'] or dist_ma20 >= g.pb['dh']: continue  # 距MA20范围
        if vol_ratio >= g.pb['vr']: continue  # 量比上限
        
        # ── 极品B ──
        cond_b = (
            g.pb['dl'] <= dist_ma20 < g.pb['dh'] and
            vol_ratio < g.pb['vr'] and
            g.pb['pl'] <= pct_20d < g.pb['ph'] and
            today_c > ma20 > ma60
        )
        
        # ── 超缩量 ──
        cond_ultra = (
            g.us['dl'] <= dist_ma20 < g.us['dh'] and
            vol_ratio < g.us['vr'] and
            g.us['pl'] <= pct_20d < g.us['ph'] and
            today_c > ma20 > ma60
        )
        
        if cond_b or cond_ultra:
            name = get_security_info(stock).display_name
            strategy = '极品B' if cond_b else '超缩量'
            candidates.append({
                'stock': stock, 'name': name, 'strategy': strategy,
                'd': round(dist_ma20, 1), 'vr': round(vol_ratio, 2),
                'p20': round(pct_20d, 1), 'c': today_c
            })
    
    g.candidates = candidates
    log.info(f'  过滤: 全市场{s_all} → 主板{s_board} → 数据够{s_data} → 策略命中{len(candidates)}')
    if candidates:
        for c in candidates:
            log.info(f'    {c["stock"]} {c["name"]} ({c["strategy"]}) '
                     f'距MA20:{c["d"]}% 量比:{c["vr"]} 20日:{c["p20"]}%')
    else:
        log.info('  ❌ 选股结果为空')

def trade(context):
    # ── 卖出到期 ──
    for stock in list(context.portfolio.positions.keys()):
        pos = context.portfolio.positions[stock]
        if pos.total_amount == 0:
            continue
        info = g.hold_info.get(stock, {})
        info['days'] = info.get('days', 0) + 1
        g.hold_info[stock] = info
        if info['days'] >= g.hold_days:
            order_target_value(stock, 0)
            log.info(f'  卖出[{stock}] 持有{info["days"]}d到期')
    
    # ── 买入新信号 ──
    if g.candidates:
        current = len([s for s in context.portfolio.positions.keys()
                       if context.portfolio.positions[s].total_amount > 0])
        slots = g.max_positions - current
        if slots > 0:
            g.candidates.sort(key=lambda x: 0 if x['strategy'] == '超缩量' else 1)
            to_buy = g.candidates[:slots]
            target = context.portfolio.total_value * g.position_pct
            
            for c in to_buy:
                stock = c['stock']
                if stock in context.portfolio.positions and context.portfolio.positions[stock].total_amount > 0:
                    g.hold_info[stock]['days'] = 0
                    log.info(f'  续期[{stock}] {c["name"]}')
                    continue
                
                available = min(target, context.portfolio.available_cash)
                if available > 1000:
                    order_target_value(stock, available)
                    g.hold_info[stock] = {'days': 0}
                    log.info(f'  买入[{stock}] {c["name"]} ({c["strategy"]}) {available/10000:.2f}万')
    
    g.candidates = []

def handle_data(context, data):
    pass
