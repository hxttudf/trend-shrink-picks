# 聚宽策略 — 趋势缩量选股
# 策略：极品B + 超缩量 | 仓位：NAV25%×4只 | 持有20交易日 | 无调仓无止损
# 标的：沪深主板（排除创业板300/科创板688/北交所4/8开头）
# 买入：信号日次日开盘 | 卖出：持有20个交易日后收盘

def initialize(context):
    # ── 策略参数 ──
    g.max_positions = 4          # 最大持仓数
    g.position_pct = 0.25        # 单票仓位比例（NAV25%）
    g.hold_days = 20             # 持有交易日数
    g.min_ma20 = 10              # 距MA20最小距离%
    g.max_ma20 = 25              # 距MA20最大距离%
    g.max_vol_ratio = 0.30       # 最大量比
    g.min_pct_20d = 3            # 20日最小涨幅%
    g.max_pct_20d = 15           # 20日最大涨幅%
    
    # 超缩量（更严）：量比<0.15, 距MA20 10-20%
    g.ultra_vol_ratio = 0.15
    g.ultra_min_ma20 = 10
    g.ultra_max_ma20 = 20
    
    # 运行时间
    # 每日收盘后选股，次日开盘交易
    run_daily(screen_stocks, time='after_close')
    run_daily(trade, time='open')

def screen_stocks(context):
    """收盘后筛选股票"""
    today = context.current_dt.strftime('%Y-%m-%d')
    log.info(f'[{today} 选股]')
    
    candidates = []
    
    # 获取全市场股票列表
    all_stocks = get_all_securities(['stock']).index.tolist()
    
    for stock in all_stocks:
        # ── 板块过滤 ──
        code = stock[0:3]
        if code in ('300','301','688','689'):  # 创业板/科创板
            continue
        if code.startswith('4') or code.startswith('8'):  # 北交所/三板
            continue
        if code.startswith('9'):  # 新三板
            continue
        
        # ── 获取数据 ──
        df = attribute_history(stock, 60, '1d', 
                               ['close', 'volume', 'high_limit', 'low_limit'],
                               df=True, skip_paused=True)
        if df is None or len(df) < 60:
            continue
        
        close = df['close'].values
        volume = df['volume'].values
        
        if len(close) < 21:
            continue
        
        today_close = close[-1]
        today_vol = volume[-1]
        
        # ── 涨停/跌停检查 ──
        high_limit = df['high_limit'].values[-1]
        low_limit = df['low_limit'].values[-1]
        if today_close >= high_limit:  # 涨停买不进
            continue
        if today_close <= low_limit:   # 跌停不买
            continue
        
        # ── 计算指标 ──
        # MA20
        ma20 = close[-20:].mean()
        if ma20 == 0:
            continue
        
        # 距MA20距离
        dist_ma20 = (today_close / ma20 - 1) * 100
        
        # 20日均量（不含当日）
        avg_vol_20 = volume[-21:-1].mean()
        if avg_vol_20 == 0:
            continue
        
        # 量比
        vol_ratio = today_vol / avg_vol_20
        
        # 20日涨幅
        price_20ago = close[-21]
        if price_20ago == 0:
            continue
        pct_20d = (today_close / price_20ago - 1) * 100
        
        # MA60
        ma60 = close[-60:].mean()
        
        # ── 极品B条件 ──
        cond_b = (
            g.min_ma20 <= dist_ma20 < g.max_ma20 and
            vol_ratio < g.max_vol_ratio and
            g.min_pct_20d <= pct_20d < g.max_pct_20d and
            today_close > ma20 > ma60
        )
        
        # ── 超缩量条件 ──
        cond_ultra = (
            g.ultra_min_ma20 <= dist_ma20 < g.ultra_max_ma20 and
            vol_ratio < g.ultra_vol_ratio and
            g.min_pct_20d <= pct_20d < g.max_pct_20d and
            today_close > ma20 > ma60
        )
        
        if cond_b or cond_ultra:
            # 获取股票名称
            name = get_security_info(stock).display_name
            strategy = '极品B' if cond_b else '超缩量'
            candidates.append({
                'stock': stock,
                'name': name,
                'strategy': strategy,
                'dist_ma20': round(dist_ma20, 1),
                'vol_ratio': round(vol_ratio, 2),
                'pct_20d': round(pct_20d, 1),
                'close': today_close
            })
    
    # 保存候选
    g.candidates = candidates
    log.info(f'  选出{len(candidates)}只: {[c["name"] for c in candidates]}')

def trade(context):
    """开盘执行交易"""
    # ── 1. 卖出到期持仓 ──
    for stock in list(context.portfolio.positions.keys()):
        pos = context.portfolio.positions[stock]
        if pos.total_amount == 0:
            continue
        
        # 获取持仓天数
        hold_info = g.hold_info.get(stock, {})
        hold_days = hold_info.get('days', 0) + 1
        hold_info['days'] = hold_days
        g.hold_info[stock] = hold_info
        
        if hold_days >= g.hold_days:
            # 到期，全部卖出
            order_target_value(stock, 0)
            log.info(f'  卖出[{stock}] {get_security_info(stock).display_name} 持有{hold_days}d到期')
    
    # ── 2. 买入新信号 ──
    if hasattr(g, 'candidates') and g.candidates:
        # 计算当前可用仓位
        current_positions = len([s for s in context.portfolio.positions.keys() 
                                 if context.portfolio.positions[s].total_amount > 0])
        available_slots = g.max_positions - current_positions
        
        if available_slots > 0 and g.candidates:
            # 按策略优先级排序：超缩量 > 极品B
            g.candidates.sort(key=lambda x: 0 if x['strategy'] == '超缩量' else 1)
            
            # 只取可用仓位数量的候选
            to_buy = g.candidates[:available_slots]
            
            nav = context.portfolio.total_value
            target_value = nav * g.position_pct
            
            for c in to_buy:
                stock = c['stock']
                if stock in context.portfolio.positions and context.portfolio.positions[stock].total_amount > 0:
                    continue  # 已持仓不重复买
                
                # 成交额过滤（避免流动性太差的）
                df = attribute_history(stock, 1, '1d', ['money'], df=True, skip_paused=True)
                if df is not None and len(df) > 0:
                    turnover = df['money'].values[-1]
                    if turnover < 5000000:  # 日成交额<500万跳过
                        log.info(f'  跳过[{stock}] {c["name"]} 成交额不足{turnover/10000:.0f}万')
                        continue
                
                order_target_value(stock, target_value)
                g.hold_info[stock] = {'days': 0}
                log.info(f'  买入[{stock}] {c["name"]} ({c["strategy"]}) '
                        f'距MA20:{c["dist_ma20"]}% 量比:{c["vol_ratio"]} '
                        f'20日涨幅:{c["pct_20d"]}% 仓位{target_value/10000:.1f}万')
    
    # 清空候选
    g.candidates = []

# 初始化持仓记录
g.hold_info = {}

def handle_data(context, data):
    """聚宽要求必须有此函数, 保持空"""
    pass
