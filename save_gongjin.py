#!/usr/bin/env python3
"""Save 共进股份 analysis to DB"""
import sqlite3, json

DB = '/home/ubuntu/databases/stock_analyses.db'
today = '2026-07-16'

data = {
    'stock_code': '603118', 'stock_name': '共进股份', 'exchange': 'SH', 'industry': '通信设备',
    'theme_tags': '光猫,ONU,CPE,宽带终端,OEM/ODM',
    'analysis_date': today,
    'price': 14.95, 'price_change_pct': None, 'pe_ttm': 135.9, 'pb': 2.11, 'market_cap': 107.0,
    'fiscal_period': '2025年报',
    'revenue': 91.98, 'net_profit': 0.78,
    'gross_margin': 11.47, 'net_margin': 0.85, 'debt_ratio': 55.0, 'oper_cf': None,
    's1_辩证确定性': '营收91.98亿净利仅7778万，净利率0.85%。Q1营收+6.2%增速极慢。毛利率10-12%代工水平，无定价权。PE135x完全脱离基本面。低确定性。',
    's2_主线思维': '宽带终端ODM不在当前AI/科技主线上。主线上的是AI算力、半导体、消费电子——共进是做光猫的，边缘角色。',
    's3_买特殊性': '无。宽带终端ODM门槛低，竞争激烈（中兴、烽火、天邑、剑桥都有同类业务）。公司主营产品可替代性极强。',
    's4_整体观': '前复权10.86→17.70区间，当前13.59在39.9%分位。6月低11.01→7月高14.80(+34%)后回撤-8.2%，呈冲高回落形态。',
    's5_抓主要矛盾': '无持续催化。市场偶炒\"F5G\"\"千兆光网\"概念但缺乏业绩支撑。收入靠运营商集采，不确定性大。',
    's6_马太效应': 'PE 135x vs 净利润率0.85% — 估值与基本面严重脱节。即便以30x PE合理估值，净利0.78亿仅值23.4亿市值，当前107亿需净利3.5亿才能支撑。',
    's7_摸石过河': 'H1 2026财报验证营收增速是否继续低迷。当前无明确催化剂，Q2大概率继续低增长。',
    'mr_summary': '宽带终端ODM厂商，营收92亿但净利仅0.78亿（净利率0.85%）。PE 135x完全脱离基本面。近期概念炒作冲高34%后回落。无确定性、无特殊性、无催化。',
    'serenity_layer': '纯故事 ⭐ — 低门槛ODM制造，无技术壁垒，客户切换成本低。运营商集采招标，价格战激烈。',
    'serenity_bottleneck': '无卡点。共进是通信终端代工厂，可替代性极强。竞争对手包括烽火、中兴、剑桥等数十家同类型企业。',
    'recommendation': 'AVOID',
    'conclusion': '净利率0.85%、PE135x、增速6%的三元悖论。A股通信设备代工厂的正常PE应在20-30x（对标中兴通讯34x）。当前股价严重高估。',
    'risk_factors': '1. 净利率<1%，利润极度脆弱，一个季度波动就可能亏损 2. 主力/机构持股比例低 3. 运营商CAPEX周期下行 4. 股价无业绩支撑',
}

conn = sqlite3.connect(DB)
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
    (data['stock_code'], data['stock_name'], data['exchange'], data['industry'], data['theme_tags'],
     data['analysis_date'], data['price'], data['price_change_pct'], data['pe_ttm'], data['pb'], data['market_cap'],
     data['fiscal_period'], data['revenue'], data['net_profit'], data['gross_margin'], data['net_margin'], data['debt_ratio'], data['oper_cf'],
     data['s1_辩证确定性'], data['s2_主线思维'], data['s3_买特殊性'], data['s4_整体观'], data['s5_抓主要矛盾'], data['s6_马太效应'], data['s7_摸石过河'],
     data['mr_summary'], data['serenity_layer'], data['serenity_bottleneck'],
     data['recommendation'], data['conclusion'], data['risk_factors'], json.dumps(data, ensure_ascii=False)))
conn.commit()
conn.close()
print('DB写入完成')
