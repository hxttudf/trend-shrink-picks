#!/usr/bin/env python3
"""2026年底部确认信号 × 老高skill确认规则 → 回测
老高确认条件(信号日及之前数据, 无未来函数):
  R1 多头排列: cur > ma20 > ma60 (skill: MA60之上才做多)
  R2 距MA20: 2% <= (cur-ma20)/ma20 <= 15% (skill简单策略: 已启动未涨飞)
  R3 量比>0.8: 当日量/前20日均量 (skill: 量能配合)
  R4 长底>=120天 (老高: 长底更真突破, 短底谨慎)
  R5 MA20向上: ma20今 > ma20 5日前 (趋势确认)
  R6 无出货风险: 信号日前5日无"放量下跌"(量比>1.2且跌>3%)
  R7 有启动信号: 前10日内有放量阳线(量比>=1.5且涨>=3%) (阶段B)
确认=全部满足R1-R7; 分档: 严格(全满足) / 宽松(满足>=5项)
"""
import sqlite3
from collections import defaultdict

SCORES_DB = "/home/ubuntu/trend-shrink-picks/bc_scores2.db"
DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"

conn = sqlite3.connect(SCORES_DB)
rows = conn.execute(
    "SELECT bt_date, symbol, score, s65, drop_pct, bottom_days, vol_shrink, cur, ma20, ma60 "
    "FROM scores WHERE score BETWEEN 80 AND 88 AND s65>=4 AND bottom_days>=90 "
    "AND abs(drop_pct) BETWEEN 20 AND 65 AND is_st=0 AND bt_date LIKE '2026%'"
).fetchall()
conn.close()
print(f"2026年worth候选: {len(rows)}")

# 市场过滤(上证>MA60) + Top3
db = sqlite3.connect(DB)
idx = [r[0] for r in db.execute(
    "SELECT date FROM stock_daily WHERE symbol='000001.SH' AND close_qfq>0 ORDER BY date")]
idx_close = [r[0] for r in db.execute(
    "SELECT close_qfq FROM stock_daily WHERE symbol='000001.SH' AND close_qfq>0 ORDER BY date")]
idx_ma60 = {}
for i in range(59, len(idx_close)):
    idx_ma60[int(idx[i].replace('-', ''))] = sum(idx_close[i-59:i+1]) / 60
idx_close_by_date = {}
for i, d in enumerate(idx):
    idx_close_by_date[int(d.replace('-', ''))] = idx_close[i]

sigs = [r for r in rows if idx_close_by_date.get(r[0], 0) > idx_ma60.get(r[0], 0)]
by_bd = defaultdict(list)
for r in sigs:
    by_bd[r[0]].append(r)
sig_v4 = []
for bd, lst in by_bd.items():
    lst.sort(key=lambda r: -r[2])
    sig_v4.extend(lst[:3])
print(f"V4严格口径(Top3+市场过滤): {len(sig_v4)}")

# 预取信号股日线
sym_all = set(r[1] for r in rows)
series = {}
for sym in sym_all:
    c = db.execute(
        "SELECT date, open, high, low, close, close_qfq, volume FROM stock_daily "
        "WHERE symbol=? AND close_qfq>0 ORDER BY date", (sym,)).fetchall()
    series[sym] = c  # [(date, o, h, l, c, cqfq, vol), ...]

def laogao_check(sym, bd):
    """老高规则确认, 返回 (确认bool, 满足项数, 明细)"""
    bd_str = f"{bd//10000}-{bd%10000//100:02d}-{bd%100:02d}"
    c = series.get(sym, [])
    idx_sig = next((i for i, r in enumerate(c) if r[0] == bd_str), None)
    if idx_sig is None or idx_sig < 25:
        return None
    cur = c[idx_sig][5]
    def ma(n, at):
        if at - n + 1 < 0:
            return None
        return sum(r[5] for r in c[at-n+1:at+1]) / n
    ma20 = ma(20, idx_sig)
    ma60 = ma(60, idx_sig)
    ma20_5 = ma(20, idx_sig - 5)
    if ma20 is None or ma60 is None or ma20_5 is None:
        return None
    # 量比: 当日量/前20日均量
    vols = [r[6] for r in c[idx_sig-20:idx_sig]]
    avg_vol = sum(vols) / len(vols) if vols else 0
    vr = c[idx_sig][6] / avg_vol if avg_vol else 0
    r1 = cur > ma20 > ma60
    dist = (cur - ma20) / ma20 * 100
    r2 = 2 <= dist <= 15
    r3 = vr > 0.8
    r4 = False  # 长底>=120天(从bc_scores2的bottom_days算, 调用方传)
    # 出货风险: 前5日放量下跌
    r6 = True
    for k in range(1, 6):
        if idx_sig - k < 1:
            break
        prev_c = c[idx_sig-k-1][5]
        chg = (c[idx_sig-k][5] / prev_c - 1) * 100
        vk = c[idx_sig-k][6]
        av = sum(r[6] for r in c[idx_sig-k-20:idx_sig-k]) / 20 if idx_sig-k >= 20 else avg_vol
        if chg < -3 and (vk / av if av else 0) > 1.2:
            r6 = False
            break
    # 启动信号: 前10日放量阳线
    r7 = False
    for k in range(1, 11):
        if idx_sig - k < 1:
            break
        prev_c = c[idx_sig-k-1][5]
        chg = (c[idx_sig-k][5] / prev_c - 1) * 100
        vk = c[idx_sig-k][6]
        av = sum(r[6] for r in c[idx_sig-k-20:idx_sig-k]) / 20 if idx_sig-k >= 20 else avg_vol
        if chg >= 3 and (vk / av if av else 0) >= 1.5:
            r7 = True
            break
    r5 = ma20 > ma20_5
    return (r1, r2, r3, r5, r6, r7, dist, vr)

def rets(sym, bd):
    bd_str = f"{bd//10000}-{bd%10000//100:02d}-{bd%100:02d}"
    c = series.get(sym, [])
    idx_sig = next((i for i, r in enumerate(c) if r[0] == bd_str), None)
    if idx_sig is None:
        return None
    base = c[idx_sig][5]
    out = {}
    for h in [5, 10, 20]:
        if idx_sig + h < len(c):
            out[h] = (c[idx_sig+h][5] / base - 1) * 100
    return out

def stat(group, label):
    ra = [rets(r[1], r[0]) for r in group]
    ra = [x for x in ra if x]
    if not ra:
        print(f"  {label}: 无数据")
        return
    parts = []
    for h in [5, 10, 20]:
        vals = [x[h] for x in ra if h in x]
        if not vals:
            continue
        w = sum(1 for v in vals if v > 0)
        parts.append(f"T+{h} {w/len(vals)*100:.0f}%/{sum(vals)/len(vals):+.1f}%")
    print(f"  {label} (n={len(ra)}): " + " | ".join(parts))

# 对V4信号跑老高确认
results = []
for r in sig_v4:
    bd, sym = r[0], r[1]
    bottom_days = r[5]
    lc = laogao_check(sym, bd)
    if lc is None:
        continue
    r1, r2, r3, r5, r6, r7, dist, vr = lc
    r4 = bottom_days >= 120
    ok_cnt = sum([r1, r2, r3, r4, r5, r6, r7])
    confirmed_strict = ok_cnt == 7
    confirmed_loose = ok_cnt >= 5
    results.append((r, ok_cnt, confirmed_strict, confirmed_loose, r1, r2, r3, r4, r5, r6, r7))

print("\n=== 老高确认统计 ===")
n = len(results)
print(f"V4信号总数: {n}")
print(f"严格确认(7项全满足): {sum(1 for x in results if x[2])}")
print(f"宽松确认(>=5项): {sum(1 for x in results if x[3])}")
print("\n各条件满足率:")
for i, name in [(4,'R1多头排列'), (5,'R2距MA20 2-15%'), (6,'R3量比>0.8'),
                (7,'R4长底>=120天'), (8,'R5 MA20向上'), (9,'R6无出货风险'), (10,'R7有启动信号')]:
    print(f"  {name}: {sum(1 for x in results if x[i])}/{n}")

print("\n=== 回测对比 (2026年) ===")
stat(sig_v4, "全部V4信号(基准)")
stat([x[0] for x in results if x[2]], "老高严格确认")
stat([x[0] for x in results if not x[2]], "老高不确认")
stat([x[0] for x in results if x[3]], "老高宽松确认(>=5)")
stat([x[0] for x in results if not x[3]], "宽松不确认")

# 明细
print("\n=== 信号明细 ===")
for r, ok, cs, cl, r1, r2, r3, r4, r5, r6, r7 in results:
    bd, sym = r[0], r[1]
    name = "?"
    rets10 = rets(sym, bd)
    rt = f"{rets10[10]:+.1f}%" if rets10 and 10 in rets10 else "?"
    marks = "".join(["✓" if v else "✗" for v in [r1, r2, r3, r4, r5, r6, r7]])
    print(f"  {bd} {sym} 分{r[2]:.0f} {ok}/7 [{marks}] T+10={rt}")

db.close()
