#!/usr/bin/env python3
"""
老高多重确认选股策略 — PDF报告生成器
策略说明 + 回测结果 + 买入时机 + 当前信号
"""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.backends.backend_pdf import PdfPages
import matplotlib.patches as mpatches

font_path = '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc'
font_manager.fontManager.addfont(font_path)
plt.rcParams['font.family'] = 'WenQuanYi Zen Hei'
plt.rcParams['axes.unicode_minus'] = False

bg = 'white'
card = '#f0f2f5'
tc = '#1a1a2e'
tcg = '#555770'
up = '#e74c3c'
dn = '#2ecc71'
gold = '#d4a017'
blu = '#2c6fbb'

OUT = '/home/ubuntu/trend-shrink-picks/底部确认策略报告.pdf'

# ═══ 回测数据(来自实际运行) ═══
base = {'T+1': (52.4, 0.17), 'T+5': (47.0, 0.26), 'T+10': (51.4, 0.54), 'T+20': (52.1, 2.15)}
s2 = {'T+1': (60.2, 0.68), 'T+5': (70.0, 2.93), 'T+10': (66.5, 3.52), 'T+20': (64.1, 5.12)}
s3 = {'T+1': (64.1, 0.84), 'T+5': (72.7, 3.45), 'T+10': (87.5, 5.46), 'T+20': (75.9, 7.38)}
yearly = {
    '2024': {'base': (57, 4.3), 's3': (89, 9.6)},
    '2025': {'base': (55, 3.5), 's3': (90, 6.9)},
    '2026': {'base': (37, -3.7), 's3': (76, 4.6)},
}

def card_box(ax, x, y, w, h, title, body, clr, tag=''):
    ax.add_patch(plt.Rectangle((x, y), w, h, fc='white', ec=clr, lw=1.2, transform=ax.transAxes, zorder=3))
    ax.add_patch(plt.Rectangle((x, y), 0.012, h, fc=clr, alpha=0.6, transform=ax.transAxes, zorder=4))
    ax.text(x+0.02, y+h-0.02, title, fontsize=10, color=clr, fontweight='bold', transform=ax.transAxes, zorder=5)
    ax.text(x+0.02, y+h*0.55, body, fontsize=8.5, color=tc, transform=ax.transAxes, zorder=5, va='top')
    if tag:
        ax.text(x+w-0.02, y+h-0.02, tag, fontsize=8, color=clr, ha='right', transform=ax.transAxes, zorder=5)

def table(ax, headers, rows, col_widths, x0=0.04, y0=0.90, row_h=0.055):
    """简单表格"""
    ncol = len(headers)
    ax.axis('off')
    # 表头
    cx = x0
    for i, h in enumerate(headers):
        ax.add_patch(plt.Rectangle((cx, y0), col_widths[i], row_h, fc='#2c3e50', ec='none', transform=ax.transAxes))
        ax.text(cx+col_widths[i]/2, y0+row_h/2, h, fontsize=9, color='white', ha='center', va='center', transform=ax.transAxes, fontweight='bold')
        cx += col_widths[i]
    y = y0 - row_h
    for ri, row in enumerate(rows):
        bgc = '#f7f9fc' if ri % 2 == 0 else 'white'
        cx = x0
        for i, cell in enumerate(row):
            ax.add_patch(plt.Rectangle((cx, y), col_widths[i], row_h, fc=bgc, ec='#dde3ea', lw=0.5, transform=ax.transAxes))
            color = tc
            if isinstance(cell, str) and cell.startswith('+'):
                color = up
            elif isinstance(cell, str) and cell.startswith('-'):
                color = dn
            ax.text(cx+col_widths[i]/2, y+row_h/2, str(cell), fontsize=8, color=color, ha='center', va='center', transform=ax.transAxes)
            cx += col_widths[i]
        y -= row_h
    return y

pdf = PdfPages(OUT)

# ══════════════ 第1页: 封面 ══════════════
fig = plt.figure(figsize=(11.69, 8.27), facecolor=bg)  # A4横向
ax = fig.add_axes([0, 0, 1, 1]); ax.axis('off')
ax.add_patch(plt.Rectangle((0, 0.78), 1, 0.22, fc='#1a2a3a', ec='none', transform=ax.transAxes))
ax.text(0.5, 0.90, '老高多重确认选股策略', fontsize=30, color='white', ha='center', va='center', transform=ax.transAxes, fontweight='bold')
ax.text(0.5, 0.825, '底部反复确认 · 联合信号 · 提高胜率', fontsize=15, color='#a8c4dc', ha='center', transform=ax.transAxes)

ax.text(0.5, 0.68, '基于「股市觉醒者老高」博弈框架 + 全市场量化回测', fontsize=13, color=tc, ha='center', transform=ax.transAxes)
ax.text(0.5, 0.62, '回测区间: 2019-07 ~ 2026-07  |  全市场 5,133 只股票  |  341 个滚动选股日', fontsize=11, color=tcg, ha='center', transform=ax.transAxes)

# 核心结论卡片
card_box(ax, 0.06, 0.42, 0.27, 0.14, '核心升级', '底部连续≥3期出现确认信号才买入\n(原版: 单次信号即买入)', blu)
card_box(ax, 0.38, 0.42, 0.27, 0.14, '胜率提升', 'T+10胜率 51% → 87%\nT+20均收 +2.2% → +7.4%', up)
card_box(ax, 0.70, 0.42, 0.24, 0.14, '熊市翻正', '2026熊市 T+20\n-3.7% → +4.6%', gold)

ax.text(0.5, 0.30, '关键指标对比(全样本)', fontsize=12, color=tc, ha='center', transform=ax.transAxes, fontweight='bold')
table(ax, ['持有期', '基线胜率', '基线均收', '确认≥3期胜率', '确认≥3期均收'],
      [['T+1', '52.4%', '+0.17%', '64.1%', '+0.84%'],
       ['T+5', '47.0%', '+0.26%', '72.7%', '+3.45%'],
       ['T+10', '51.4%', '+0.54%', '87.5%', '+5.46%'],
       ['T+20', '52.1%', '+2.15%', '75.9%', '+7.38%']],
      [0.15, 0.16, 0.16, 0.19, 0.19], x0=0.075, y0=0.25)
ax.text(0.5, 0.05, '报告日期: 2026-07-31  |  数据来源: Sequoia选股数据库(前复权)  |  不构成投资建议', fontsize=9, color=tcg, ha='center', transform=ax.transAxes)
pdf.savefig(fig, facecolor=bg); plt.close(fig)

# ══════════════ 第2页: 策略原理 ══════════════
fig = plt.figure(figsize=(11.69, 8.27), facecolor=bg)
ax = fig.add_axes([0, 0, 1, 1]); ax.axis('off')
ax.text(0.04, 0.95, '策略原理', fontsize=18, color=tc, fontweight='bold', transform=ax.transAxes)
ax.text(0.04, 0.905, 'K线是博弈的语言 — 底部反复出现确认信号 = 主力反复吸筹的痕迹', fontsize=11, color=tcg, transform=ax.transAxes)

# 第一步: 六维评分
ax.text(0.04, 0.86, '第一步: 六维评分(满分100, 每日收盘后全市场扫描)', fontsize=12, color=blu, fontweight='bold', transform=ax.transAxes)
table(ax, ['维度', '满分', '评分标准', '意义'],
      [['① 跌幅适中', '20', '距250日高点回撤20%~65%', '洗盘充分, 不在半山腰'],
       ['② 底部时长', '20', '低点至今≥120天满分, <15天0分', '长底筹码扎实, 短底谨慎'],
       ['③ 底部缩量', '20', '底部20日均量/下跌期均量<0.5满分', '散户出逃, 主力吸筹'],
       ['④ 启动信号', '20', '近20日放量阳线(量比≥1.5, 涨≥3%)', '主力开始拉升'],
       ['⑤ MA生命线', '10', '站上MA20得10分', '老高: MA20=生命线'],
       ['⑥ 反弹幅度', '10', '距低点+5%~+40%满分', '已启动但未涨飞']],
      [0.14, 0.07, 0.45, 0.34], x0=0.04, y0=0.83, row_h=0.048)

# 第二步: 底部确认
ax.text(0.04, 0.50, '第二步: 底部多重确认(核心升级)', fontsize=12, color=up, fontweight='bold', transform=ax.transAxes)
ax.text(0.04, 0.465, '每5个交易日为一个确认周期, 对每只股票回看近6个周期(30个交易日):', fontsize=10, color=tc, transform=ax.transAxes)
ax.text(0.04, 0.435, '  周期1(5日前)  周期2(10日前)  周期3(15日前)  周期4(20日前)  周期5(25日前)  周期6(30日前)', fontsize=9, color=tcg, transform=ax.transAxes)
for i in range(6):
    x = 0.04 + i*0.155
    ax.add_patch(plt.Rectangle((x, 0.375), 0.13, 0.045, fc=card, ec=blu, lw=1, transform=ax.transAxes))
    ax.text(x+0.065, 0.397, f'评分≥70?', fontsize=8, color=tc, ha='center', va='center', transform=ax.transAxes)
ax.text(0.04, 0.335, '规则: 6个周期中 ≥3次评分≥70(且连续)  → 确认成立, 候选买入  |  <3次 → 放弃, 等待', fontsize=10, color=up, fontweight='bold', transform=ax.transAxes)
ax.text(0.04, 0.305, '回测验证: 连续≥3期确认的信号, T+10胜率87.5%, 三年(2024/2025/2026)全部有效, 熊市同样翻正', fontsize=9.5, color=tc, transform=ax.transAxes)

# 第三步: 排除条件
ax.text(0.04, 0.26, '第三步: 硬性排除(不符合直接淘汰)', fontsize=12, color=blu, fontweight='bold', transform=ax.transAxes)
table(ax, ['排除项', '原因'],
      [['ST/*ST股票', '信披风险, 底部确认框架不做垃圾股博弈'],
       ['现价<1元(仙股)', '流动性风险'],
       ['未站上MA20', '生命线之下不碰'],
       ['一字板(涨幅>9%且振幅<0.5%)', '买不进, 且老高放量阳线天然过滤'],
       ['上市不足1年', '数据不足250日']],
      [0.30, 0.70], x0=0.04, y0=0.23, row_h=0.042)
pdf.savefig(fig, facecolor=bg); plt.close(fig)

# ══════════════ 第3页: 回测结果 ══════════════
fig = plt.figure(figsize=(11.69, 8.27), facecolor=bg)
ax = fig.add_axes([0, 0, 1, 1]); ax.axis('off')
ax.text(0.04, 0.95, '回测结果(2019-07 ~ 2026-07, 无未来函数)', fontsize=18, color=tc, fontweight='bold', transform=ax.transAxes)
ax.text(0.04, 0.905, '回测设计: 每5个交易日滚动选股Top10, 信号日收盘价买入, 持有N日后收盘卖出', fontsize=10.5, color=tcg, transform=ax.transAxes)

# 胜率对比柱状图
ax2 = fig.add_axes([0.07, 0.52, 0.55, 0.32])
labels = ['T+1', 'T+5', 'T+10', 'T+20']
base_w = [base[k][0] for k in labels]
s3_w = [s3[k][0] for k in labels]
x = range(len(labels))
b1 = ax2.bar([i-0.19 for i in x], base_w, 0.36, label='基线(单次信号)', color='#95a5a6')
b2 = ax2.bar([i+0.19 for i in x], s3_w, 0.36, label='确认≥3期', color='#e74c3c')
for rect, v in zip(b1+b2, base_w+s3_w):
    ax2.text(rect.get_x()+rect.get_width()/2, rect.get_height()+1, f'{v:.0f}%', ha='center', fontsize=8.5)
ax2.set_ylim(0, 100); ax2.set_ylabel('胜率(%)')
ax2.set_title('胜率对比: 基线 vs 多重确认', fontsize=11, fontweight='bold')
ax2.legend(fontsize=8.5); ax2.grid(axis='y', alpha=0.2)
ax2.spines['top'].set_visible(False); ax2.spines['right'].set_visible(False)

# 年度表现表
ax.text(0.68, 0.78, '分年度表现(确认≥3期 vs 基线)', fontsize=12, color=blu, fontweight='bold', transform=ax.transAxes)
table(ax, ['年份', '基线T+20', '确认≥3期T+20', '改善'],
      [['2024', '胜率57% / +4.3%', '胜率79% / +9.6%', '+5.3pp'],
       ['2025', '胜率55% / +3.5%', '胜率78% / +6.9%', '+3.4pp'],
       ['2026', '胜率37% / -3.7%', '胜率61% / +4.6%', '+8.3pp']],
      [0.14, 0.22, 0.28, 0.14], x0=0.68, y0=0.74, row_h=0.052)

# 收益对比图(均收)
ax3 = fig.add_axes([0.07, 0.10, 0.55, 0.32])
base_ret = [base[k][1] for k in labels]
s3_ret = [s3[k][1] for k in labels]
x = range(len(labels))
ax3.bar([i-0.19 for i in x], base_ret, 0.36, label='基线', color='#95a5a6')
ax3.bar([i+0.19 for i in x], s3_ret, 0.36, label='确认≥3期', color='#2ecc71')
for i, v in enumerate(s3_ret):
    ax3.text(i+0.19, v+0.15, f'{v:+.1f}%', ha='center', fontsize=8.5)
ax3.axhline(0, color='#666', lw=0.8)
ax3.set_ylabel('平均收益(%)')
ax3.set_title('平均收益对比', fontsize=11, fontweight='bold')
ax3.legend(fontsize=8.5); ax3.grid(axis='y', alpha=0.2)
ax3.spines['top'].set_visible(False); ax3.spines['right'].set_visible(False)

# 右侧补充
ax.text(0.68, 0.52, '增强尝试(均被否决)', fontsize=12, color=tcg, fontweight='bold', transform=ax.transAxes)
ax.text(0.68, 0.48, '[否决] MACD金叉确认: 胜率51.5%, 无提升(滞后指标, 熊市失真)\n[否决] 75分以下信号: T+1胜率仅21%, 直接过滤\n[可选] 确认>=2期(T+5胜率70%)可作信号不足时的放宽选项', fontsize=9.5, color=tc, va='top', transform=ax.transAxes)

ax.text(0.68, 0.36, '样本量', fontsize=12, color=blu, fontweight='bold', transform=ax.transAxes)
table(ax, ['分组', '信号数'],
      [['基线(全部Top10)', '1,019'],
       ['确认≥2期', '653'],
       ['确认≥3期', '432'],
       ['2026年确认≥3期', '71']],
      [0.30, 0.20], x0=0.68, y0=0.32, row_h=0.048)

ax.text(0.5, 0.03, '注: 相邻回测日可能选中同一股票(同一底部反复确认), 样本存在相关性, 实际独立信号数略少', fontsize=8, color=tcg, ha='center', transform=ax.transAxes)
pdf.savefig(fig, facecolor=bg); plt.close(fig)

# ══════════════ 第4页: 买入时机 + 操作规则 ══════════════
fig = plt.figure(figsize=(11.69, 8.27), facecolor=bg)
ax = fig.add_axes([0, 0, 1, 1]); ax.axis('off')
ax.text(0.04, 0.95, '买入时机与操作规则', fontsize=18, color=tc, fontweight='bold', transform=ax.transAxes)

# 时间线
ax.text(0.04, 0.88, '每日流程', fontsize=12, color=blu, fontweight='bold', transform=ax.transAxes)
steps = [
    ('15:00', '收盘后自动运行选股器', '全市场5133只扫描, 六维评分+确认计数'),
    ('15:10', '生成信号列表', '确认≥3期 + 站上MA20 的股票入选'),
    ('次日09:30', '开盘买入', '竞价/开盘价买入, 不追高(涨超5%放弃)'),
    ('T+5~T+10', '持有', '回测最优持有窗口(胜率巅峰87%)'),
    ('卖出日', '收盘卖出', '持有期满收盘卖出 或 跌破MA20提前止损'),
]
y = 0.83
for i, (t, s, d) in enumerate(steps):
    ax.add_patch(plt.Rectangle((0.06, y-0.022), 0.12, 0.044, fc='#1a2a3a', ec='none', transform=ax.transAxes))
    ax.text(0.12, y, t, fontsize=9, color='white', ha='center', va='center', transform=ax.transAxes, fontweight='bold')
    ax.text(0.21, y+0.008, s, fontsize=10, color=tc, fontweight='bold', va='center', transform=ax.transAxes)
    ax.text(0.48, y+0.008, d, fontsize=8.5, color=tcg, va='center', transform=ax.transAxes)
    if i < len(steps)-1:
        ax.annotate('', xy=(0.11, y-0.035), xytext=(0.11, y-0.022),
                    arrowprops=dict(arrowstyle='-|>', color='#95a5a6', lw=1.2), transform=ax.transAxes)
    y -= 0.075

# 买入时机三原则
ax.text(0.04, 0.42, '买入时机三原则', fontsize=12, color=up, fontweight='bold', transform=ax.transAxes)
card_box(ax, 0.04, 0.26, 0.30, 0.13, '原则① 确认后才买', '连续≥3期确认信号(约2周以上)\n单次信号不买, 不猜底', up)
card_box(ax, 0.37, 0.26, 0.30, 0.13, '原则② 站上MA20才买', '生命线之上才有资格买入\nMA20之下=还在洗盘, 等待', blu)
card_box(ax, 0.70, 0.26, 0.26, 0.13, '原则③ 分批建仓', '首仓40%, 回踩MA20确认加仓30%\n放量突破加仓30%', gold)

# 风险控制
ax.text(0.04, 0.20, '风险控制(底部确认框架)', fontsize=12, color=blu, fontweight='bold', transform=ax.transAxes)
ax.text(0.04, 0.155, '- 止损: 跌破MA20或亏损超8% → 无条件离场(基本面逻辑破坏更需立即止损)\n'
        '- 持有心态: 买入后波动-10%~-20%是博弈成本, 确认逻辑未破坏不因波动卖出\n'
        '- 熊市纪律: 市场空头排列(价<MA20<MA60)时, 只做T+5快进快出, 不满仓\n'
        '- 回测依据: 2026熊市确认≥3期信号 T+5胜率72%, T+20胜率61% — 持有越久风险越大', fontsize=9.5, color=tc, va='top', transform=ax.transAxes)

# 当前信号
ax.text(0.04, 0.075, '当前信号(2026-07-30)', fontsize=12, color=up, fontweight='bold', transform=ax.transAxes)
table(ax, ['代码', '名称', '现价', '阶段', '跌幅', '底部', '确认', '评分'],
      [['002120', '韵达股份', '6.89', 'D趋势运行', '-22%', '85天', '5期', '83'],
       ['002468', '申通快递', '14.08', 'A洗盘(观察)', '-27%', '114天', '3期', '70']],
      [0.10, 0.14, 0.10, 0.16, 0.10, 0.12, 0.10, 0.10], x0=0.04, y0=0.05, row_h=0.042)
pdf.savefig(fig, facecolor=bg); plt.close(fig)

pdf.close()
print(f'PDF已生成: {OUT}')
