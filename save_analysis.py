#!/usr/bin/env python3
"""Save stock analysis to DB"""
import sqlite3, json

DB = '/home/ubuntu/databases/stock_analyses.db'
today = '2026-07-15'

analyses = [
    {
        'stock_code': '000938', 'stock_name': '紫光股份', 'exchange': 'SZ', 'industry': 'IT设备',
        'theme_tags': 'AI算力,交换机,服务器,信创',
        'analysis_date': today, 'price': 84.05, 'price_change_pct': -3.92, 'pe_ttm': 60.29, 'pb': 6.54, 'market_cap': 1016.19,
        'fiscal_period': '', 'revenue': None, 'net_profit': None, 'gross_margin': None, 'net_margin': None, 'debt_ratio': None, 'oper_cf': None,
        's1_辩证确定性': 'AI算力主线，H3C网络设备国内第一。营收增速需财报验证(缺Wind数据)，PE60偏贵需高增速支撑',
        's2_主线思维': 'AI算力核心标的，与浪潮信息同属科技双主线',
        's3_买特殊性': 'H3C企业网交换机国内份额第一，紫光展锐芯片间接持股，A股稀缺的网络设备龙头',
        's4_整体观': '前复权25.15→38.41区间，当前35.53距3月高-7.5%，距MA20+17.5%',
        's5_抓主要矛盾': 'AI算力资本开支持续，H3C交换机+服务器双驱动',
        's6_马太效应': 'PE60x不算便宜，但AI赛道高增速下PEG可能合理(缺一致预期数据)',
        's7_摸石过河': 'Q2财报验证AI服务器出货增速',
        'mr_summary': 'AI算力网络龙头，近期放量拉升+40%后缩量回调，中线趋势strong',
        'serenity_layer': '控制稀缺层', 'serenity_bottleneck': 'H3C交换机在企业级市场地位稳固，客户迁移成本高',
        'recommendation': 'HOLD', 'conclusion': '中线看好AI算力主线，短期+40%涨幅需消化，等回踩MA20(≈30qfq)更安全',
        'risk_factors': 'AI资本开支放缓、H3C份额被华为侵蚀、PE60x不便宜',
    },
    {
        'stock_code': '000977', 'stock_name': '浪潮信息', 'exchange': 'SZ', 'industry': 'IT设备',
        'theme_tags': 'AI服务器,算力基建,信创',
        'analysis_date': today, 'price': 384.71, 'price_change_pct': -0.29, 'pe_ttm': 51.68, 'pb': 5.58, 'market_cap': 1243.80,
        'fiscal_period': '', 'revenue': None, 'net_profit': None, 'gross_margin': None, 'net_margin': None, 'debt_ratio': None, 'oper_cf': None,
        's1_辩证确定性': 'AI服务器国内份额第一，大模型竞赛直接拉动需求。营收趋势需Wind数据验证',
        's2_主线思维': 'AI算力最纯正标的，与紫光股份同属科技主线',
        's3_买特殊性': 'A股唯一纯正AI服务器标的，互联网大厂核心供应商，规模效应显著',
        's4_整体观': '前复权57.84→89.52区间，当前84.70距3月高-5.4%，距MA20+20.5%',
        's5_抓主要矛盾': '国内大模型军备竞赛→AI服务器采购持续高景气',
        's6_马太效应': 'PE51x较紫光60x更合理，但20日+46%涨幅极端超买',
        's7_摸石过河': '跟踪互联网大厂资本开支指引、浪潮JDM订单',
        'mr_summary': 'AI服务器龙头，近期暴涨+46%后缩量回调，弹性最大但短期超买严重',
        'serenity_layer': '控制稀缺层', 'serenity_bottleneck': 'GPU供应依赖NVIDIA/昇腾，供应链有卡脖子风险',
        'recommendation': 'HOLD', 'conclusion': 'AI主线最强弹性标的，短期超买需回调至MA20附近',
        'risk_factors': 'GPU供应受限、华为昇腾生态竞争、AI资本开支节奏波动',
    }
]

conn = sqlite3.connect(DB)
for a in analyses:
    conn.execute('''INSERT INTO stock_analyses 
        (stock_code, stock_name, exchange, industry, theme_tags,
         analysis_date, price, price_change_pct, pe_ttm, pb, market_cap,
         fiscal_period, revenue, net_profit, gross_margin, net_margin, debt_ratio, oper_cf,
         s1_辩证确定性, s2_主线思维, s3_买特殊性, s4_整体观, s5_抓主要矛盾, s6_马太效应, s7_摸石过河,
         mr_summary, serenity_layer, serenity_bottleneck,
         recommendation, conclusion, risk_factors, raw_report)
        VALUES (?,?,?,?,?,
                ?,?,?,?,?,?,
                ?,?,?,?,?,?,?,
                ?,?,?,?,?,?,?,
                ?,?,?,
                ?,?,?,?)''',
        (a['stock_code'], a['stock_name'], a['exchange'], a['industry'], a['theme_tags'],
         a['analysis_date'], a['price'], a['price_change_pct'], a['pe_ttm'], a['pb'], a['market_cap'],
         a['fiscal_period'], a['revenue'], a['net_profit'], a['gross_margin'], a['net_margin'], a['debt_ratio'], a['oper_cf'],
         a['s1_辩证确定性'], a['s2_主线思维'], a['s3_买特殊性'], a['s4_整体观'], a['s5_抓主要矛盾'], a['s6_马太效应'], a['s7_摸石过河'],
         a['mr_summary'], a['serenity_layer'], a['serenity_bottleneck'],
         a['recommendation'], a['conclusion'], a['risk_factors'], json.dumps(a, ensure_ascii=False)))
conn.commit()
conn.close()
print(f'DB写入完成: {len(analyses)} 条')
