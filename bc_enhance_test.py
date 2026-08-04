#!/usr/bin/env python3
"""问题1+2: 无Top3对比 + MACD/均线多头增强测试
V4 worth条件: 80-88分/4期/底90/跌幅20-65/非ST + 市场过滤(上证>MA60)
增强: ①无Top3 ②MACD多头(DIF>DEA且柱>0) ③MA多头排列(MA5>MA10>MA20 或 cur>ma20>ma60)
"""
import sqlite3
from collections import defaultdict

SCORES_DB = "/home/ubuntu/trend-shrink-picks/bc_scores2.db"
DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"

conn = sqlite3.connect(SCORES_DB)
rows = conn.execute(
    "SELECT bt_date, symbol, score, s65, drop_pct, bottom_days FROM scores "
    "WHERE score BETWEEN 80 AND 88 AND s65>=4 AND bottom_days>=90 "
    "AND abs(drop_pct) BETWEEN 20 AND 65 AND is_st=0"
).fetchall()
conn.close()

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

def rets(bd, sym):
    bd_str = f"{bd//10000}-{bd%10000//100:02d}-{bd%100:02d}"
    fut = db.execute(
        "SELECT close_qfq FROM stock_daily WHERE symbol=? AND close_qfq>0 AND date>? ORDER BY date LIMIT 20",
        (sym, bd_str)).fetchall()
    cur = db.execute(
        "SELECT close_qfq FROM stock_daily WHERE symbol=? AND date=? AND close_qfq>0",
        (sym, bd_str)).fetchone()
    if not cur:
        return None
    base = cur[0]
    return {h: (fut[h-1][0]/base-1)*100 if len(fut) >= h else None for h in [5, 10, 20]}

# 预取: 每只股票的收盘序列(信号日前250天), 用于MACD/均线计算
# 只取信号涉及到的股票
sym_all = set(r[1] for r in rows)
close_cache = {}
for sym in sym_all:
    c = db.execute(
        "SELECT date, close_qfq FROM stock_daily WHERE symbol=? AND close_qfq>0 ORDER BY date",
        (sym,)).fetchall()
    close_cache[sym] = c  # [(date_str, close), ...]

def ema_last(series, period):
    """对序列算EMA, 返回最后值"""
    k = 2 / (period + 1)
    prev = series[0]
    for v in series[1:]:
        prev = v * k + prev * (1 - k)
    return prev

def macd_state(sym, bd):
    """信号日MACD状态: (dif, dea, hist) 用截至信号日的250天收盘"""
    bd_str = f"{bd//10000}-{bd%10000//100:02d}-{bd%100:02d}"
    c = close_cache.get(sym, [])
    closes = [x[1] for x in c if x[0] <= bd_str][-250:]
    if len(closes) < 60:
        return None
    e12 = ema_last(closes, 12)
    e26 = ema_last(closes, 26)
    dif = e12 - e26
    # DEA = EMA9(DIF序列)
    difs = []
    k12, k26, k9 = 2/13, 2/27, 2/10
    e12v = e26v = closes[0]
    difs = []
    for v in closes:
        e12v = v * k12 + e12v * (1 - k12)
        e26v = v * k26 + e26v * (1 - k26)
        difs.append(e12v - e26v)
    dea = difs[0]
    for d in difs[1:]:
        dea = d * k9 + dea * (1 - k9)
    return (dif, dea, (dif - dea) * 2)

def ma_state(sym, bd):
    """信号日均线状态: (ma5, ma10, ma20, ma60, cur)"""
    bd_str = f"{bd//10000}-{bd%10000//100:02d}-{bd%100:02d}"
    c = close_cache.get(sym, [])
    closes = [x[1] for x in c if x[0] <= bd_str][-60:]
    if len(closes) < 60:
        return None
    def ma(n):
        return sum(closes[-n:]) / n
    return (ma(5), ma(10), ma(20), ma(60), closes[-1])

# 市场过滤
sigs_mkt = [r for r in rows if idx_close_by_date.get(r[0], 0) > idx_ma60.get(r[0], 0)]
print(f"市场过滤后: {len(sigs_mkt)}")

def evaluate(sigs, label):
    ra = [rets(r[0], r[1]) for r in sigs]
    ra = [x for x in ra if x]
    if not ra:
        print(f"  {label}: 无数据")
        return
    parts = []
    for h in [5, 10, 20]:
        vals = [x[h] for x in ra if x[h] is not None]
        if not vals:
            continue
        w = sum(1 for v in vals if v > 0)
        parts.append(f"T+{h} {w/len(vals)*100:.0f}%/{sum(vals)/len(vals):+.1f}%")
    print(f"  {label} (n={len(ra)}): " + " | ".join(parts))

print("\n=== 问题1: Top3 vs 无Top3 ===")
evaluate(sigs_mkt, "无Top3(仅条件+市场)")
by_bd = defaultdict(list)
for r in sigs_mkt:
    by_bd[r[0]].append(r)
top3 = []
for bd, lst in by_bd.items():
    lst.sort(key=lambda r: -r[2])
    top3.extend(lst[:3])
evaluate(top3, "Top3")

print("\n=== 问题2: MACD增强 ===")
macd_ok = [r for r in sigs_mkt if macd_state(r[1], r[0]) is not None]
m_dif_dea = [r for r in macd_ok if macd_state(r[1], r[0])[0] > macd_state(r[1], r[0])[1]]
m_hist_pos = [r for r in macd_ok if macd_state(r[1], r[0])[2] > 0]
m_both = [r for r in macd_ok if macd_state(r[1], r[0])[0] > macd_state(r[1], r[0])[1] and macd_state(r[1], r[0])[2] > 0]
evaluate(macd_ok, "基准(有MACD数据)")
evaluate(m_dif_dea, "DIF>DEA")
evaluate(m_hist_pos, "MACD柱>0")
evaluate(m_both, "DIF>DEA且柱>0")

print("\n=== 问题2: MA多头排列增强 ===")
ma_all = [r for r in sigs_mkt if ma_state(r[1], r[0]) is not None]
ma5_10_20 = [r for r in ma_all if (lambda m: m[0] > m[1] > m[2])(ma_state(r[1], r[0]))]
ma_cur_20_60 = [r for r in ma_all if (lambda m: m[4] > m[2] > m[3])(ma_state(r[1], r[0]))]
ma_5_10_20_60 = [r for r in ma_all if (lambda m: m[0] > m[1] > m[2] > m[3])(ma_state(r[1], r[0]))]
evaluate(ma_all, "基准(有MA数据)")
evaluate(ma5_10_20, "MA5>MA10>MA20")
evaluate(ma_cur_20_60, "现价>MA20>MA60")
evaluate(ma_5_10_20_60, "MA5>MA10>MA20>MA60")

print("\n=== 组合: MACD多头 + 均线多头 ===")
comb1 = [r for r in m_both if (lambda m: m[4] > m[2] > m[3])(ma_state(r[1], r[0]))]
evaluate(comb1, "MACD多头+现价>MA20>MA60")
comb2 = [r for r in m_both if (lambda m: m[0] > m[1] > m[2])(ma_state(r[1], r[0]))]
evaluate(comb2, "MACD多头+MA5>MA10>MA20")

# 分年度: 最佳组合
print("\n=== 最佳组合分年度 ===")
for yr in ['2023', '2024', '2025', '2026']:
    gg = [r for r in comb1 if str(r[0]).startswith(yr)]
    evaluate(gg, f"{yr}")

db.close()
