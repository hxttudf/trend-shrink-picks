#!/usr/bin/env python3
"""在基准81信号上找亏损特征"""
import sqlite3
SRC_DB = "/home/ubuntu/databases/Sequoia选股.db"
conn = sqlite3.connect(SRC_DB)
c = conn.cursor()

BASE_SQL = "dist_ma20>=12 AND dist_ma20<25 AND vol_ratio>=0 AND vol_ratio<0.3 AND pct_20d>=3 AND pct_20d<15 AND price>ma20 AND ma20>ma60"

# 0:sym,1:date,2:price,3:open,4:high,5:low,6:body,7:us,8:ls,9:rp,10:ma20,11:ma60,12:d20,13:vr,14:p20,15:t5,16:t20
c.execute(f"SELECT symbol,date,price,open,high,low,body,upper_shadow,lower_shadow,range_pct,ma20,ma60,dist_ma20,vol_ratio,pct_20d,t5_ret,t20_ret FROM candle_cache WHERE {BASE_SQL}")
rows = [r for r in c.fetchall() if r[16] is not None]
print(f"基准信号: {len(rows)}")

wins = [r for r in rows if r[16] > 0]
loss = [r for r in rows if r[16] <= 0]
print(f"赢家: {len(wins)} T5均{sum(r[15] for r in wins if r[15])/sum(1 for r in wins if r[15]):.1f}%")
print(f"输家: {len(loss)} T5均{sum(r[15] for r in loss if r[15])/sum(1 for r in loss if r[15]):.1f}%")

# 特征对比
print(f"\n{'特征':<20} {'赢家均值':>10} {'输家均值':>10} {'差值':>10}")
print("-"*50)
feats = [
    ("dist_ma20", 12), ("vol_ratio", 13), ("pct_20d", 14), ("body", 6),
    ("body/rng", 9), ("upper_shadow", 7), ("lower_shadow", 8),
    ("price", 2), ("open", 3),
]
for name, idx in feats:
    wv = sum(r[idx] for r in wins)/len(wins)
    lv = sum(r[idx] for r in loss)/len(loss)
    print(f"{name:<20} {wv:>10.4f} {lv:>10.4f} {wv-lv:>+10.4f}")

print(f"\n收阳比例: 赢家{sum(1 for r in wins if r[2]>r[3])}/{len(wins)} = {sum(1 for r in wins if r[2]>r[3])/len(wins)*100:.0f}%")
print(f"          输家{sum(1 for r in loss if r[2]>r[3])}/{len(loss)} = {sum(1 for r in loss if r[2]>r[3])/len(loss)*100:.0f}%")

# 检查输家是否body全为0
loss_body0 = sum(1 for r in loss if r[6] == 0)
print(f"\n输家 body=0: {loss_body0}/{len(loss)}")
win_body0 = sum(1 for r in wins if r[6] == 0)
print(f"赢家 body=0: {win_body0}/{len(wins)}")

# 输家详细
print(f"\n输家列表:")
for r in sorted(loss, key=lambda x: x[16]):
    print(f"  {r[0]} {r[1]} T20={r[16]:+.1f}% T5={r[15]:+.1f}% "
          f"d={r[12]:.1f} vr={r[13]:.2f} p20={r[14]:.1f}% "
          f"body={r[6]:.4f} rng={r[9]:.4f} {'阳' if r[2]>r[3] else '阴'} "
          f"o={r[3]:.4f} c={r[2]:.4f}")

# 规则测试
print(f"\n{'='*60}")
print(f"规则过滤效果（希望：排除输家>排除赢家）")
print(f"{'='*60}")
rules = [
    ("body>0", lambda r: r[6] > 0),
    ("body>0.005", lambda r: r[6] > 0.005),
    ("body/rng>0", lambda r: r[9] > 0),
    ("收阳", lambda r: r[2] > r[3]),
    ("vr>=0.1", lambda r: r[13] >= 0.1),
    ("vr>=0.15", lambda r: r[13] >= 0.15),
    ("d20>=14", lambda r: r[12] >= 14),
    ("d20>=15", lambda r: r[12] >= 15),
    ("收阳+vr>=0.1", lambda r: r[2]>r[3] and r[13]>=0.1),
    ("body>0+vr>=0.1", lambda r: r[6]>0 and r[13]>=0.1),
    ("body>0+vr>=0.1+d20>=14", lambda r: r[6]>0 and r[13]>=0.1 and r[12]>=14),
    ("body>0+d20>=14", lambda r: r[6]>0 and r[12]>=14),
    ("d20>=14+p20>=8", lambda r: r[12]>=14 and r[14]>=8),
    ("d20>=14+vr>=0.15", lambda r: r[12]>=14 and r[13]>=0.15),
    ("p20>10", lambda r: r[14] > 10),
    ("vr<0.25", lambda r: r[13] < 0.25),
    ("vr<0.25+d20>=14", lambda r: r[13]<0.25 and r[12]>=14),
]

for name, fn in rules:
    kept = [r for r in rows if fn(r)]
    n = len(kept)
    kw = sum(1 for r in kept if r[16] > 0)
    kl = n - kw
    excl = [r for r in rows if not fn(r)]
    ew = sum(1 for r in excl if r[16] > 0)
    el = len(excl) - ew
    net = el - ew  # positive = good (excluded more losers than winners)
    pct_keep = n/81*100
    kwr = kw/n*100 if n>0 else 0
    marker = " ✅" if net > 3 and n >= 60 else ""
    print(f"  {name:<25} | 保留{n:>2}({pct_keep:.0f}%) | 赢{kw}/输{kl}({kwr:.0f}%) | 排除{el}输{ew}赢 | 净{net:>+2}{marker}")

conn.close()
