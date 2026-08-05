#!/usr/bin/env python3
"""
资金流向日报 — 拉取同花顺行业资金+涨停情绪+北向资金，存DB并输出分析
用法: python3 fund_flow_daily.py midday    # 午盘
      python3 fund_flow_daily.py close     # 收盘
"""
import sys, json, sqlite3, time
from datetime import date
from pathlib import Path
from collections import Counter

# akshare 路径
sys.path.insert(0, '/home/ubuntu/Sequoia-X-a/.venv-host/lib/python3.12/site-packages')

import akshare as ak
import pandas as pd

DB_PATH = "/home/ubuntu/databases/资金流向.db"
TIME_SLOT = sys.argv[1] if len(sys.argv) > 1 else "close"
TODAY = date.today().strftime("%Y-%m-%d")
TODAY_ZT = date.today().strftime("%Y%m%d")

# ═══════════════════════════
# 1. 数据拉取
# ═══════════════════════════

def fetch_sector_funds():
    """行业资金流向（10jqka）"""
    for attempt in range(3):
        try:
            df = ak.stock_fund_flow_industry(symbol="即时")
            df['净额'] = pd.to_numeric(df['净额'], errors='coerce')
            return df
        except Exception as e:
            time.sleep(2 * (attempt + 1))
    return pd.DataFrame()

def fetch_zt_data():
    """涨停情绪 — 优先东财，失败则从Sequoia-X DB计算"""
    zt, strong, dt = pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    
    # 1. 尝试东财
    try:
        zt = ak.stock_zt_pool_em(date=TODAY_ZT)
        strong = ak.stock_zt_pool_strong_em(date=TODAY_ZT)
        try:
            dt = ak.stock_zt_pool_dtgc_em(date=TODAY_ZT)
        except:
            pass
        if len(zt) > 0:
            return zt, strong, dt
    except Exception as e:
        print(f"  ⚠ 东财涨停失败: {e}，尝试Sequoia-X DB兜底", file=sys.stderr)
    
    # 2. 兜底：从 Sequoia-X DB 计算涨跌停
    try:
        seq_conn = sqlite3.connect("/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db")
        today_str = TODAY.replace('-', '')
        df = pd.read_sql(f"""
            SELECT code, name, close, pre_close, change_pct, volume, amount
            FROM stock_daily WHERE date = '{today_str}'
        """, seq_conn)
        seq_conn.close()
        
        if len(df) > 0:
            df['change_pct'] = pd.to_numeric(df['change_pct'], errors='coerce')
            # 科创板/创业板 20%，主板 10%
            zt_list, dt_list = [], []
            for _, r in df.iterrows():
                code = str(r['code'])
                pct = r['change_pct']
                limit = 20 if code.startswith('688') or code.startswith('300') else 10
                if pct >= limit * 0.98:  # 接近涨停就算
                    zt_list.append({'名称': r['name'], '代码': code, '涨跌幅': pct,
                                    '连板数': 0, '所属行业': '', '封板资金': 0,
                                    '首次封板时间': '', '最后封板时间': '', '炸板次数': 0,
                                    '涨停统计': '', '成交额': r.get('amount', 0)})
                elif pct <= -limit * 0.98:
                    dt_list.append({'名称': r['name'], '代码': code, '涨跌幅': pct})
            
            zt = pd.DataFrame(zt_list) if zt_list else pd.DataFrame()
            dt = pd.DataFrame(dt_list) if dt_list else pd.DataFrame()
            # strong 近似 = zt（自己算的没有强势涨停区分）
            strong = zt.copy() if len(zt) > 0 else pd.DataFrame()
            print(f"  ✅ Sequoia-X兜底: 涨停{len(zt)}只, 跌停{len(dt)}只", file=sys.stderr)
    except Exception as e:
        print(f"  ⚠ Sequoia-X兜底也失败: {e}", file=sys.stderr)
    
    return zt, strong, dt

def fetch_north_flow():
    """北向资金"""
    try:
        north = ak.stock_hsgt_fund_flow_summary_em()
        hgt = north[(north['板块'] == '沪股通') & (north['资金方向'] == '北向')]
        sgt = north[(north['板块'] == '深股通') & (north['资金方向'] == '北向')]
        hgt_net = hgt['资金净流入'].values[0] if len(hgt) > 0 else 0
        sgt_net = sgt['资金净流入'].values[0] if len(sgt) > 0 else 0
        return hgt_net / 10000, sgt_net / 10000  # 万 → 亿
    except:
        return 0, 0

def fetch_market_turnover():
    """全市场成交额（腾讯qt，亿元）"""
    import http.client
    import os
    try:
        # 清空代理直连腾讯qt
        conn = http.client.HTTPConnection('qt.gtimg.cn', timeout=10)
        codes = ["sh000001", "sz399001", "sz399006"]
        conn.request("GET", f"/q={'%2C'.join(codes)}")
        resp = conn.getresponse()
        data = resp.read().decode('gbk')
        conn.close()

        total_turnover = 0
        for line in data.strip().split(';\n'):
            if not line.strip():
                continue
            code = line.split('=')[0].replace('v_', '')
            if code not in codes:
                continue
            fields = line.split('"')[1].split('~')
            # composite field [35]: "price/volume/amount(元)"
            if len(fields) > 35:
                composite = fields[35]
                parts = composite.split('/')
                if len(parts) > 2 and parts[2]:
                    total_turnover += float(parts[2]) / 1e8  # 元 → 亿
        return round(total_turnover, 2)
    except Exception as e:
        print(f"  ⚠ 成交额抓取失败: {e}", file=sys.stderr)
        return 0

# ── 行业→门类 映射（11大门类）──
INDUSTRY_GATE = {
    # 能源
    "煤炭开采加工": "能源", "油气开采及服务": "能源", "石油加工贸易": "能源", "燃气": "能源",
    # 原材料
    "小金属": "原材料", "工业金属": "原材料", "金属新材料": "原材料", "钢铁": "原材料",
    "非金属材料": "原材料", "化学制品": "原材料", "化学原料": "原材料", "化学纤维": "原材料",
    "化工合成材料": "原材料", "化工新材料": "原材料", "农化制品": "原材料", "塑料制品": "原材料",
    "建筑材料": "原材料", "造纸": "原材料", "贵金属": "原材料",
    # 工业
    "通用设备": "工业", "专用设备": "工业", "自动化设备": "工业", "工程机械": "工业",
    "轨交设备": "工业", "电机": "工业", "电网设备": "工业", "电力设备": "工业",
    "光伏设备": "工业", "风电设备": "工业", "电池": "工业", "其他电源设备": "工业",
    "建筑装饰": "工业", "环保": "工业", "物流": "工业", "综合": "工业",
    # 可选消费
    "汽车整车": "可选消费", "汽车零部件": "可选消费", "汽车服务及其他": "可选消费",
    "家用电器": "可选消费", "厨卫电器": "可选消费", "小家电": "可选消费",
    "服装家纺": "可选消费", "家用轻工": "可选消费", "美容护理": "可选消费",
    "教育": "可选消费", "旅游及酒店": "可选消费", "零售": "可选消费", "互联网电商": "可选消费",
    "传媒": "可选消费", "影视院线": "可选消费", "游戏": "可选消费", "体育": "可选消费",
    "纺织制造": "可选消费",
    # 主要消费
    "食品加工制造": "主要消费", "饮料制造": "主要消费", "农产品加工": "主要消费",
    "种植业与林业": "主要消费", "养殖业": "主要消费", "饲料": "主要消费",
    # 医药卫生
    "化学制药": "医药卫生", "生物制品": "医药卫生", "医疗器械": "医药卫生",
    "医药商业": "医药卫生", "中药": "医药卫生", "医疗服务": "医药卫生",
    # 金融地产
    "银行": "金融地产", "证券": "金融地产", "保险及其他": "金融地产",
    "房地产开发": "金融地产", "房地产服务": "金融地产", "多元金融": "金融地产",
    # 信息技术
    "半导体及元件": "信息技术", "半导体": "信息技术", "元件": "信息技术",
    "消费电子": "信息技术", "光学光电子": "信息技术", "其他电子": "信息技术",
    "计算机应用": "信息技术", "IT服务": "信息技术", "计算机设备": "信息技术",
    "软件开发": "信息技术",
    # 电信业务
    "通信服务": "电信业务", "通信设备": "电信业务",
    # 公用事业
    "电力": "公用事业", "港口航运": "公用事业", "公路铁路运输": "公用事业",
    "机场航运": "公用事业",
    # 军工（归入工业）
    "军工电子": "工业", "军工装备": "工业", "地面兵装": "工业", "航天装备": "工业", "航空装备": "工业",
}

def fetch_concept_boards():
    """概念板块行情（东财）"""
    try:
        df = ak.stock_board_concept_spot_em()
        numeric_cols = ['涨跌幅', '换手率', '成交额']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        return df
    except:
        return pd.DataFrame()

def fetch_lhb():
    """龙虎榜"""
    try:
        df = ak.stock_lhb_ggtj_sina()
        return df
    except:
        pass
    try:
        df = ak.stock_lhb_stock_detail_date_em(symbol='20260618')
        return df
    except:
        return pd.DataFrame()

def build_industry_tree(fund_df):
    """构建三层树：门类→行业→净额（全行业保留，展流入流出各3）"""
    gate_net = {}
    for _, r in fund_df.iterrows():
        gate = INDUSTRY_GATE.get(r['行业'], '综合')
        if gate not in gate_net:
            gate_net[gate] = {'net': 0, 'industries': []}
        gate_net[gate]['net'] += r['净额']
        gate_net[gate]['industries'].append({
            'name': r['行业'],
            'net': r['净额'],
            'pct': r.get('行业-涨跌幅', 0) or 0
        })
    
    result = []
    for gate in sorted(gate_net, key=lambda g: -gate_net[g]['net']):
        info = gate_net[gate]
        all_inds = sorted(info['industries'], key=lambda x: -x['net'])
        # 保留流入TOP3和流出TOP3（去重）
        top_in = [x for x in all_inds if x['net'] > 0][:3]
        top_out = [x for x in all_inds if x['net'] < 0][-3:]  # 流出最大的
        
        shown = []
        for x in top_in:
            shown.append(x)
        # 流出TOP3倒序（流出最多的在前）
        for x in reversed(top_out):
            if x not in shown:
                shown.append(x)
        
        result.append({
            'gate': gate,
            'net': info['net'],
            'top_industries': shown
        })
    return result

def detect_concept_breakout(concept_df, zt_df):
    """检测概念板块爆发"""
    if len(concept_df) == 0:
        return []
    
    # 如果涨停数据有概念字段，精准匹配
    zt_concepts = Counter()
    zt_stock_concept = {}
    has_concept_field = '所属概念' in zt_df.columns and len(zt_df) > 0
    
    if has_concept_field:
        for _, r in zt_df.iterrows():
            name = r.get('名称', '')
            concepts_str = r.get('所属概念', '')
            if pd.isna(concepts_str) or not concepts_str:
                continue
            for c in str(concepts_str).split(';'):
                c = c.strip()
                if c:
                    zt_concepts[c] += 1
                    zt_stock_concept.setdefault(c, []).append(name)

    # 取涨幅TOP5概念，结合涨停分布
    chg_col = None
    for col in ['涨跌幅', '涨幅']:
        if col in concept_df.columns:
            chg_col = col
            break
    
    name_col = '名称' if '名称' in concept_df.columns else concept_df.columns[0]
    
    breakouts = []
    if chg_col and has_concept_field and len(zt_concepts) > 0:
        # 有涨停概念映射 → 精准匹配
        concept_chg = {}
        for _, row in concept_df.iterrows():
            cn = str(row[name_col])
            concept_chg[cn] = float(row[chg_col]) if not pd.isna(row[chg_col]) else 0
        
        for concept, cnt in zt_concepts.most_common(15):
            if cnt >= 2:
                breakouts.append({
                    'concept': concept,
                    'chg': concept_chg.get(concept, 0),
                    'zt_count': cnt,
                    'zt_stocks': set(zt_stock_concept.get(concept, []))
                })
                if len(breakouts) >= 5:
                    break
    elif chg_col:
        # 无涨停映射 → 直接展示涨幅TOP概念
        top = concept_df.nlargest(8, chg_col)
        for _, row in top.iterrows():
            breakouts.append({
                'concept': str(row[name_col]),
                'chg': float(row[chg_col]),
                'zt_count': 0,
                'zt_stocks': set()
            })
            if len(breakouts) >= 5:
                break

    if has_concept_field:
        breakouts.sort(key=lambda b: -b['zt_count'])
    else:
        breakouts.sort(key=lambda b: -b['chg'])
    return breakouts

print(f"⏳ 拉取 {TODAY} {TIME_SLOT} 数据...", file=sys.stderr)

fund = fetch_sector_funds()
zt, zt_strong, dt = fetch_zt_data()
north_hgt, north_sgt = fetch_north_flow()
total_turnover = fetch_market_turnover()
concept_boards = fetch_concept_boards() if TIME_SLOT == 'close' else pd.DataFrame()
lhb = fetch_lhb() if TIME_SLOT == 'close' else pd.DataFrame()

if len(fund) == 0:
    print("❌ 行业资金数据获取失败", file=sys.stderr)
    sys.exit(1)

# ═══════════════════════════
# 3. 计算指标
# ═══════════════════════════

# 情绪
zt_count = len(zt)
dt_count = len(dt)
strong_count = len(zt_strong)
fengban_rate = zt_count / max(strong_count, 1)
max_lianban = int(zt['连板数'].max()) if len(zt) > 0 else 0

# 行业资金
fund_sorted = fund.sort_values('净额', ascending=False)
top10 = fund_sorted.head(10)
bottom10 = fund_sorted.tail(10)
total_net = fund['净额'].sum()
inflow_n = len(fund[fund['净额'] > 0])
outflow_n = len(fund[fund['净额'] < 0])

# 涨停行业分布
zt_industries = {}
if len(zt) > 0:
    zt_ind_counter = Counter()
    for _, r in zt.iterrows():
        zt_ind_counter[r.get('所属行业', '未知')] += 1
    zt_industries = dict(zt_ind_counter.most_common(10))

# 连板梯队
lianban_list = []
if len(zt) > 0 and zt_count > 0:
    lb = zt[zt['连板数'] > 1][['名称', '连板数', '所属行业']].sort_values('连板数', ascending=False)
    lianban_list = [{'name': r['名称'], 'days': int(r['连板数']), 'industry': r['所属行业']} for _, r in lb.iterrows()]

# 行业树状结构
industry_tree = build_industry_tree(fund)

# 概念板块爆发检测（仅收盘）
concept_breakouts = detect_concept_breakout(concept_boards, zt) if len(concept_boards) > 0 and len(zt) > 0 else []

# 龙虎榜分析（仅收盘）
lhb_analysis = None
if len(lhb) > 0:
    try:
        # 尝试多个可能的列名
        buy_col = None
        sell_col = None
        for bc in ['累积购买额', '龙虎榜买入额', '买入金额', 'buy']:
            if bc in lhb.columns: buy_col = bc; break
        for sc in ['累积卖出额', '龙虎榜卖出额', '卖出金额', 'sell']:
            if sc in lhb.columns: sell_col = sc; break
        
        if buy_col and sell_col:
            total_buy = pd.to_numeric(lhb[buy_col], errors='coerce').sum()
            total_sell = pd.to_numeric(lhb[sell_col], errors='coerce').sum()
            lhb_analysis = {
                'count': len(lhb),
                'buy': total_buy / 10000,  # 万→亿
                'sell': total_sell / 10000,
                'net': (total_buy - total_sell) / 10000
            }
    except:
        pass

# ═══════════════════════════
# 4. 生成分析
# ═══════════════════════════

warnings = []

# 模糊匹配（不同数据源行业名可能略有差异）
all_fund_names_global = set(fund['行业'].values)
def fuzzy_ind_match(zt_ind):
    """返回匹配的fund行业名，无匹配返回None"""
    for fn in all_fund_names_global:
        if zt_ind in fn or fn in zt_ind:
            return fn
        # 归一化后再比
        si = zt_ind.replace('光电子','光电').replace('电子化学','电子化学品').replace('工程','')
        sf = fn.replace('光电子','光电').replace('电子化学','电子化学品').replace('工程','')
        if len(si) >= 2 and len(sf) >= 2 and (si in sf or sf in si):
            return fn
    return None

# 集中度
if len(fund_sorted) > 0:
    top1 = fund_sorted.iloc[0]
    if top1['净额'] > 100 and (len(fund_sorted) < 2 or fund_sorted.iloc[1]['净额'] < top1['净额'] * 0.3):
        warnings.append(f"极度集中: {top1['行业']}独吸{top1['净额']:.0f}亿，第二名仅{fund_sorted.iloc[1]['净额']:.0f}亿")

# 市场广度
if outflow_n > inflow_n * 3:
    warnings.append(f"资金面恶化: {inflow_n}行业流入 vs {outflow_n}行业流出")

# 背离 + 共振
hot_in = []   # 涨停行业&资金流入
hot_not = []  # 涨停行业&资金未跟
for ind, cnt in list(zt_industries.items())[:8]:
    matched_fn = fuzzy_ind_match(ind)
    if matched_fn and matched_fn in set(top10['行业'].values):
        net = fund_sorted[fund_sorted['行业']==matched_fn]['净额'].values[0]
        hot_in.append(f"{ind}({net:+.0f}亿)")
    elif cnt >= 3:
        hot_not.append(ind)
        if cnt >= 5:
            warnings.append(f"背离信号: {ind}涨停{cnt}只但资金不在流入TOP15")

# 封板率
if fengban_rate < 0.4 and zt_count > 20:
    warnings.append(f"封板率低({fengban_rate:.0%})，冲板被砸多")

# 高标
if max_lianban < 4 and zt_count > 30:
    warnings.append(f"无高标(最高{max_lianban}板)，短线情绪偏弱")

# 生成结论
pieces = []
# 资金方向
if top1['净额'] > 50:
    pieces.append(f"资金主攻{top1['行业']}(+{top1['净额']:.0f}亿)")
if total_net < -300:
    pieces.append(f"全市场净流出{abs(total_net):.0f}亿，主力撤离明显")

# 情绪判断
if max_lianban >= 5:
    pieces.append(f"高标{max_lianban}板，短线情绪活跃")
elif max_lianban >= 3:
    pieces.append(f"连板高度{max_lianban}板，情绪一般")
else:
    pieces.append("无高标，短线情绪冰点")
if fengban_rate < 0.3 and zt_count > 20:
    pieces.append(f"封板率仅{fengban_rate:.0%}，炸板率高")

# 板块判断
severity = "偏空" if total_net < -300 and outflow_n > 60 else ("偏多" if total_net > 100 else "中性")
pieces.append(f"整体{severity}({total_net:+.0f}亿)")

analysis = "；".join(pieces) + "。"

# 操作建议
advice_lines = []
if severity == "偏多":
    advice_lines.append("可适度加仓，关注资金主攻方向")
elif severity == "偏空":
    advice_lines.append("控制仓位，等待资金回流信号")
else:
    advice_lines.append("轻仓观望，不追高不杀跌")

if top1['净额'] > 50:
    advice_lines.append(f"关注{top1['行业']}持续性，若次日缩量则止盈")
if outflow_n > 60:
    advice_lines.append(f"{outflow_n}行业流出，回避流出TOP5板块")
if max_lianban >= 5:
    advice_lines.append("高标活跃，短线可试错但严控仓位")
elif max_lianban < 3 and zt_count > 20:
    advice_lines.append("涨停虽多但无龙头，短线难做")

advice = "\n".join([f"  · {a}" for a in advice_lines])

# ═══════════════════════════
# 5. 存入DB
# ═══════════════════════════

conn = sqlite3.connect(DB_PATH)

# 快照
snapshot = {
    'date': TODAY,
    'time_slot': TIME_SLOT,
    'zt_count': zt_count,
    'dt_count': dt_count,
    'strong_zt_count': strong_count,
    'max_lianban': max_lianban,
    'fengban_rate': round(fengban_rate, 3),
    'north_hgt_net': round(north_hgt, 2),
    'north_sgt_net': round(north_sgt, 2),
    'total_net_flow': round(total_net, 2),
    'inflow_industries': inflow_n,
    'outflow_industries': outflow_n,
    'analysis': analysis,
    'top_sectors': json.dumps([{'name': r['行业'], 'net': float(r['净额'])} for _, r in top10.iterrows()], ensure_ascii=False),
    'bottom_sectors': json.dumps([{'name': r['行业'], 'net': float(r['净额'])} for _, r in bottom10.iterrows()], ensure_ascii=False),
    'warning_signals': json.dumps(warnings, ensure_ascii=False),
    'total_amount': total_turnover,
}

cols = ', '.join(snapshot.keys())
placeholders = ', '.join(['?' for _ in snapshot])
# UPSERT
conn.execute(f"INSERT OR REPLACE INTO fund_flow_daily ({cols}) VALUES ({placeholders})", list(snapshot.values()))
snapshot_id = conn.execute("SELECT id FROM fund_flow_daily WHERE date=? AND time_slot=?", (TODAY, TIME_SLOT)).fetchone()[0]

# 行业明细
for _, r in fund.iterrows():
    conn.execute("""
        INSERT OR REPLACE INTO sector_flows (snapshot_id, sector_name, net_flow, change_pct, inflow, outflow, company_count)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (snapshot_id, r['行业'], float(r['净额']),
          float(r.get('行业-涨跌幅', 0) or 0),
          float(r.get('流入资金', 0) or 0),
          float(r.get('流出资金', 0) or 0),
          int(r.get('公司家数', 0) or 0)))

# 大类汇总（存下来供输出用）
cat_rows = []
try:
    cat_rows = conn.execute("""
        SELECT ic.category, ROUND(SUM(sf.net_flow), 1)
        FROM sector_flows sf
        JOIN industry_categories ic ON sf.sector_name = ic.sector_name
        WHERE sf.snapshot_id = ?
        GROUP BY ic.category ORDER BY SUM(sf.net_flow) DESC
    """, (snapshot_id,)).fetchall()
except:
    pass

conn.commit()
conn.close()

# ═══════════════════════════
# 6. 输出（微信分两条：结论+风险+资金 | 行业树+细节）
# ═══════════════════════════

slot_label = "午盘" if TIME_SLOT == "midday" else "收盘"

# ── 构建两条消息 ──
msg1_lines = [f"{TODAY} {slot_label}复盘"]

# 总结
msg1_lines.append(f"\n总结: {analysis}")
msg1_lines.append(f"建议:")
msg1_lines.append(advice)

# 风险
if warnings:
    msg1_lines.append(f"\n风险:")
    for w in warnings[:4]:
        msg1_lines.append(f"  · {w}")

# 情绪
if zt_count > 0:
    lb_str = ', '.join([f"{lb['name']}({lb['days']}板)" for lb in lianban_list[:4]]) if lianban_list else '无'
    msg1_lines.append(f"\n涨跌停: {zt_count}涨停/{dt_count}跌停 封板率{fengban_rate:.0%} 最高{max_lianban}板")
    msg1_lines.append(f"连板: {lb_str}")

# 资金流向
msg1_lines.append(f"\n全市场: {inflow_n}流入/{outflow_n}流出 净差{total_net:+.0f}亿")
msg1_lines.append(f"流入TOP5: " + ", ".join([f"{r['行业']}(+{r['净额']:.0f}亿)" for _, r in top10.head(5).iterrows()]))
msg1_lines.append(f"流出TOP5: " + ", ".join([f"{r['行业']}({r['净额']:.0f}亿)" for _, r in fund_sorted.nsmallest(5, '净额').iterrows()]))

# 北向
if north_hgt != 0 or north_sgt != 0:
    msg1_lines.append(f"北向: 沪{north_hgt:+.1f}亿 深{north_sgt:+.1f}亿")

msg1 = "\n".join(msg1_lines)

# ── 第二条：行业树 + 概念 + 龙虎榜 + 交叉验证 ──
msg2_lines = []

# 行业门类树（全部展开）
msg2_lines.append("行业门类:")
for gate_info in industry_tree:
    gate = gate_info['gate']
    net = gate_info['net']
    ind_items = [f"{ind['name']}({ind['net']:+.0f}亿)" for ind in gate_info['top_industries']]
    msg2_lines.append(f"  {gate} {net:+.0f}亿: {', '.join(ind_items)}")

# 概念爆发
if concept_breakouts:
    items = [f"{cb['concept']}({cb['zt_count']}板)" for cb in concept_breakouts[:5]]
    msg2_lines.append(f"\n概念爆发: {', '.join(items)}")

# 龙虎榜
if lhb_analysis:
    direction = '流入' if lhb_analysis['net'] >= 0 else '流出'
    msg2_lines.append(f"\n龙虎榜: {lhb_analysis['count']}只 净{direction}{abs(lhb_analysis['net']):.1f}亿")

# 交叉验证
if len(zt) > 0 and len(fund) > 0:
    parts = []
    if hot_in:
        parts.append(f"共振: {', '.join(hot_in[:3])}")
    if hot_not:
        parts.append(f"背离: {', '.join(hot_not[:3])}")
    if parts:
        msg2_lines.append(f"\n{' | '.join(parts)}")

msg2 = "\n".join(msg2_lines)

# 输出分隔符供 cron/脚本解析
print("===MSG1===")
print(msg1)
print("===MSG2===")
print(msg2)
