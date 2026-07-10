# 聚宽策略 — 趋势缩量选股
# 策略：极品B + 超缩量 | 仓位：NAV25%×4只 | 持有20交易日
# 标的：沪深主板
# 买入：信号日次日开盘 | 卖出：持有20个交易日后收盘

DEBUG_STOCKS = ('000892.XSHE','002989.XSHE','000811.XSHE','605028.XSHG','000608.XSHE','603813.XSHG')

def initialize(context):
    set_option('use_real_price', False)
    g.max_positions = 4
    g.position_pct = 0.25
    g.hold_days = 20
    g.hold_info = {}
    g.candidates = []
    g.pb = {'dl':12,'dh':25,'vr':0.30,'pl':3,'ph':15,'ma60':True}
    g.us = {'dl':10,'dh':20,'vr':0.15,'pl':3,'ph':15,'ma60':True}
    run_daily(screen_stocks, time='after_close')
    run_daily(trade, time='open')

def screen_stocks(context):
    today = context.current_dt.strftime('%Y-%m-%d')
    all_stocks = get_all_securities(['stock']).index.tolist()
    log.info(f'[{today}] 选股: 扫描{len(all_stocks)}只')
    candidates = []
    passed_board = 0
    passed_data = 0
    
    for stock in all_stocks:
        code3 = stock[0:3]
        if code3 in ('300','301','688','689'): continue
        if stock[0] in ('4','8','9'): continue
        passed_board += 1
        
        df = attribute_history(stock, 60, '1d',
                               ['close', 'volume', 'high_limit'], df=True, skip_paused=True, fq='pre')
        if df is None or len(df) < 60: continue
        passed_data += 1
        
        close = df['close'].values
        volume = df['volume'].values
        hl = df['high_limit'].values[-1]
        import numpy as np
        if np.isnan(close).any() or np.isnan(volume).any(): continue
        
        today_c = close[-1]; today_v = volume[-1]
        
        # 涨停检查：排除信号日已涨停的票（次日买不进）
        if hl and hl > 0 and today_c >= hl * 0.995:
            continue
        
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
        
        cond_b = (g.pb['dl'] <= dist_ma20 < g.pb['dh'] and
                  vol_ratio < g.pb['vr'] and
                  g.pb['pl'] <= pct_20d < g.pb['ph'] and
                  today_c > ma20 > ma60)
        cond_ultra = (g.us['dl'] <= dist_ma20 < g.us['dh'] and
                      vol_ratio < g.us['vr'] and
                      g.us['pl'] <= pct_20d < g.us['ph'] and
                      today_c > ma20 > ma60)
        
        if cond_b or cond_ultra:
            name = get_security_info(stock).display_name
            s = '极品B' if cond_b else '超缩量'
            candidates.append({'stock':stock,'name':name,'strategy':s,
                               'd':round(dist_ma20,1),'vr':round(vol_ratio,2),
                               'p20':round(pct_20d,1),'c':round(today_c,2),'ma20':round(ma20,2)})
        elif stock in DEBUG_STOCKS:
            fail = []
            if not (g.pb['dl'] <= dist_ma20 < g.pb['dh']): fail.append(f'距MA20({dist_ma20:.1f}%)')
            if not (vol_ratio < g.pb['vr']): fail.append(f'量比({vol_ratio:.2f})')
            if not (g.pb['pl'] <= pct_20d < g.pb['ph']): fail.append(f'20日涨幅({pct_20d:.1f}%)')
            if not (today_c > ma20 > ma60): fail.append(f'MA排列')
            log.info(f'  [DEBUG]{stock} {get_security_info(stock).display_name} '
                     f'收盘{round(today_c,2)} MA20{round(ma20,2)} MA60{round(ma60,2)} '
                     f'距MA20{dist_ma20:.1f}% 量比{vol_ratio:.2f} 20日涨幅{pct_20d:.1f}% '
                     f'未命中: {", ".join(fail)}')
    
    g.candidates = candidates
    log.info(f'[{today}] 选股: 主板{passed_board}→数据够{passed_data}→命中{len(candidates)}')
    for c in candidates:
        log.info(f'  +{c["stock"]} {c["name"]} ({c["strategy"]}) '
                 f'收盘{c["c"]} MA20{c["ma20"]} '
                 f'MA20距离{c["d"]}% 量比{c["vr"]} 20日涨幅{c["p20"]}%')

def trade(context):
    today = context.current_dt.strftime('%Y-%m-%d')
    
    # 卖出到期
    for stock in list(context.portfolio.positions.keys()):
        pos = context.portfolio.positions[stock]
        if pos.total_amount == 0: continue
        info = g.hold_info.get(stock, {})
        info['days'] = info.get('days', 0) + 1
        g.hold_info[stock] = info
        if info['days'] >= g.hold_days:
            order_target_value(stock, 0)
            log.info(f'[{today}] 卖出 {stock} {pos.total_amount}股')
    
    # 买入新信号
    if not g.candidates: return
    
    current = len([s for s in context.portfolio.positions.keys()
                   if context.portfolio.positions[s].total_amount > 0])
    slots = g.max_positions - current
    if slots <= 0: return
    
    g.candidates.sort(key=lambda x: 0 if x['strategy'] == '超缩量' else 1)
    target = context.portfolio.total_value * g.position_pct
    
    for c in g.candidates[:slots]:
        stock = c['stock']
        
        # 已持有 → 续期
        if stock in context.portfolio.positions and context.portfolio.positions[stock].total_amount > 0:
            g.hold_info[stock]['days'] = 0
            log.info(f'[{today}] 续期 {stock} {c["name"]}')
            continue
        
        # 停牌检查
        try:
            cur = get_current_data()[stock]
            if cur.paused:
                log.info(f'  ⏸停牌跳过 {stock} {c["name"]}')
                continue
            if cur.high_limit and cur.last_price and cur.last_price >= cur.high_limit * 0.995:
                log.info(f'  ⛔涨停跳过 {stock} {c["name"]}')
                continue
        except:
            pass
        
        available = min(target, context.portfolio.available_cash)
        if available > 1000:
            order_target_value(stock, available)
            g.hold_info[stock] = {'days': 0}
            log.info(f'[{today}] 买入 {stock} {c["name"]} ({c["strategy"]}) {available/10000:.2f}万')
    
    g.candidates = []

def handle_data(context, data):
    pass
