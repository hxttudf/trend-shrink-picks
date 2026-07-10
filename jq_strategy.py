# 聚宽策略 — 趋势缩量选股
# 策略：极品B + 超缩量 | 仓位：NAV25%×4只 | 持有20交易日 | 无调仓无止损
# 标的：沪深主板
# 买入：信号日次日开盘 | 卖出：持有20个交易日后收盘

def initialize(context):
    # ── 策略参数（与本地 run_picks.py 一致）──
    g.max_positions = 4
    g.position_pct = 0.25
    g.hold_days = 20
    g.hold_info = {}
    g.log_debug = True  # 改False可关掉详细日志
    
    # 极品B
    g.pb = {'dl':12,'dh':25,'vr':0.30,'pl':3,'ph':15,'ma60':True}
    # 超缩量
    g.us = {'dl':10,'dh':20,'vr':0.15,'pl':3,'ph':15,'ma60':True}
    
    run_daily(screen_stocks, time='after_close')
    run_daily(trade, time='open')

def debug(msg):
    if g.get('log_debug', False):
        log.info(msg)

def screen_stocks(context):
    today = context.current_dt.strftime('%Y-%m-%d')
    log.info(f'[{today} 选股]')
    
    all_stocks = get_all_securities(['stock']).index.tolist()
    debug(f'  全市场股票数: {len(all_stocks)}')
    
    candidates = []
    stage_all = 0
    stage_board = 0
    stage_data = 0
    stage_limit = 0
    
    for stock in all_stocks:
        stage_all += 1
        
        # ── 板块过滤：仅沪深主板 ──
        code3 = stock[0:3]
        if code3 in ('300','301','688','689'): continue
        if stock[0] in ('4','8','9'): continue
        stage_board += 1
        
        # ── 获取数据 ──
        df = attribute_history(stock, 60, '1d',
                               ['close', 'volume', 'high_limit', 'low_limit'],
                               df=True, skip_paused=True)
        if df is None or len(df) < 60:
            continue
        stage_data += 1
        
        close = df['close'].values
        volume = df['volume'].values
        
        today_close = close[-1]
        today_vol = volume[-1]
        
        # ── 涨停/跌停检查 ──
        high_limit = df['high_limit'].values[-1]
        low_limit = df['low_limit'].values[-1]
        # 防止聚宽返回0（字段无效）→ 跳过检查
        if high_limit and high_limit > 0 and today_close >= high_limit:
            continue
        if low_limit and low_limit > 0 and today_close <= low_limit:
            continue
        stage_limit += 1
        
        # ── 计算指标 ──
        ma20 = close[-20:].mean()
        if ma20 == 0: continue
        
        dist_ma20 = (today_close / ma20 - 1) * 100
        
        avg_vol_20 = volume[-21:-1].mean()
        if avg_vol_20 == 0: continue
        vol_ratio = today_vol / avg_vol_20
        
        price_20ago = close[-21]
        if price_20ago == 0: continue
        pct_20d = (today_close / price_20ago - 1) * 100
        
        ma60 = close[-60:].mean()
        
        # ── 极品B条件 ──
        cond_b = (
            g.pb['dl'] <= dist_ma20 < g.pb['dh'] and
            vol_ratio < g.pb['vr'] and
            g.pb['pl'] <= pct_20d < g.pb['ph'] and
            (not g.pb['ma60'] or (today_close > ma20 > ma60))
        )
        
        # ── 超缩量条件 ──
        cond_ultra = (
            g.us['dl'] <= dist_ma20 < g.us['dh'] and
            vol_ratio < g.us['vr'] and
            g.us['pl'] <= pct_20d < g.us['ph'] and
            (not g.us['ma60'] or (today_close > ma20 > ma60))
        )
        
        if cond_b or cond_ultra:
            name = get_security_info(stock).display_name
            strategy = '极品B' if cond_b else '超缩量'
            candidates.append({
                'stock': stock, 'name': name, 'strategy': strategy,
                'dist_ma20': round(dist_ma20, 1),
                'vol_ratio': round(vol_ratio, 2),
                'pct_20d': round(pct_20d, 1),
                'close': today_close
            })
    
    g.candidates = candidates
    log.info(f'  过滤统计: 总计{stage_all} → 主板{stage_board} → 数据够{stage_data} → 未涨停{stage_limit} → 策略命中{len(candidates)}')
    if candidates:
        for c in candidates:
            log.info(f'    {c["stock"]} {c["name"]} ({c["strategy"]}) '
                     f'MA20距离{c["dist_ma20"]}% 量比{c["vol_ratio"]} 20日涨幅{c["pct_20d"]}%')
    else:
        log.info('  选股结果为空')

def trade(context):
    # ── 1. 卖出到期持仓 ──
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
    
    # ── 2. 买入新信号 ──
    if g.candidates:
        current = len([s for s in context.portfolio.positions.keys()
                       if context.portfolio.positions[s].total_amount > 0])
        slots = g.max_positions - current
        
        if slots > 0:
            # 优先超缩量
            g.candidates.sort(key=lambda x: 0 if x['strategy'] == '超缩量' else 1)
            to_buy = g.candidates[:slots]
            target = context.portfolio.total_value * g.position_pct
            
            for c in to_buy:
                stock = c['stock']
                if stock in context.portfolio.positions and context.portfolio.positions[stock].total_amount > 0:
                    # 续期
                    g.hold_info[stock]['days'] = 0
                    log.info(f'  续期[{stock}] {c["name"]}')
                    continue
                
                # 成交额过滤
                df = attribute_history(stock, 1, '1d', ['money'], df=True, skip_paused=True)
                if df is not None and len(df) > 0:
                    turnover = df['money'].values[-1]
                    if turnover < 5000000:
                        log.info(f'  跳过[{stock}] {c["name"]} 成交额不足{turnover/10000:.0f}万')
                        continue
                
                available = min(target, context.portfolio.available_cash)
                if available > 1000:
                    order_target_value(stock, available)
                    g.hold_info[stock] = {'days': 0}
                    log.info(f'  买入[{stock}] {c["name"]} ({c["strategy"]}) '
                            f'仓位{available/10000:.2f}万')
    
    g.candidates = []

def handle_data(context, data):
    pass
