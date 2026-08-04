#!/usr/bin/env python3
import sqlite3

tc = sqlite3.connect("/home/ubuntu/databases/trend_picks.db")
sc = sqlite3.connect("/home/ubuntu/databases/Sequoia选股.db")
tc.row_factory = sqlite3.Row
sc.row_factory = sqlite3.Row

signals = tc.execute("""
    SELECT dp.symbol, dp.date, COALESCE(dp.name,"") as name
    FROM daily_picks dp WHERE dp.strategy_id = "premium_b"
    ORDER BY dp.date
""").fetchall()

syms = list(set(s["symbol"] for s in signals))
klines = {}
for sym in syms:
    rows = sc.execute(
        "SELECT date, close_qfq, volume FROM stock_daily WHERE symbol=? AND close_qfq>0 ORDER BY date",
        (sym,)
    ).fetchall()
    if rows:
        klines[sym] = rows

di = {}
for sym, rows in klines.items():
    di[sym] = {r["date"]: i for i, r in enumerate(rows)}

results = []
skipped = []
for sig in signals:
    sym, ds = sig["symbol"], sig["date"]
    rows = klines.get(sym, [])
    si = di.get(sym, {}).get(ds)
    if si is None:
        skipped.append((sym, ds, "no kline"))
        continue

    t1 = None
    for n in [1,2,3]:
        idx = si + n
        if idx < len(rows):
            t1 = rows[idx]
            break
    if t1 is None:
        skipped.append((sym, ds, "no T+1/2/3"))
        continue

    t1_idx = di[sym][t1["date"]]
    if t1_idx < 1:
        skipped.append((sym, ds, "no prev"))
        continue
    prev_of_t1 = rows[t1_idx - 1]["close_qfq"]
    if prev_of_t1 <= 0:
        skipped.append((sym, ds, "bad prev"))
        continue
    t1_ret = (t1["close_qfq"] / prev_of_t1 - 1) * 100

    # 量比(5日)
    avg5 = None
    t1_di = t1_idx
    if t1_di >= 5:
        vs = [rows[i]["volume"] for i in range(t1_di-5, t1_di)
              if rows[i]["volume"] and rows[i]["volume"] > 0]
        avg5 = sum(vs)/len(vs) if vs else None
    vr5 = t1["volume"] / avg5 if avg5 and avg5 > 0 else 0

    # T+20收益(从T+1尾盘买入)
    sell_idx = si + 21
    if sell_idx >= len(rows):
        skipped.append((sym, ds, "no T+20"))
        continue
    ret20 = (rows[sell_idx]["close_qfq"] / t1["close_qfq"] - 1) * 100

    is_drop = t1_ret <= -2.0 and vr5 >= 1.5

    results.append({
        "symbol": sym, "name": sig["name"], "sig_date": ds,
        "t1_date": t1["date"], "t1_pct": round(t1_ret, 1),
        "vr5": round(vr5, 2), "ret20": round(ret20, 2),
        "filtered": is_drop
    })

# Sort by return
results.sort(key=lambda r: r["ret20"], reverse=True)

rets = [r["ret20"] for r in results]
wr = sum(1 for r in rets if r > 0) / len(rets) * 100
avg = sum(rets) / len(rets)
wins = sum(1 for r in rets if r > 0)
losses = sum(1 for r in rets if r <= 0)
filtered_cnt = sum(1 for r in results if r["filtered"])
filtered_wins = sum(1 for r in results if r["filtered"] and r["ret20"] > 0)
filtered_losses = sum(1 for r in results if r["filtered"] and r["ret20"] <= 0)

print("极品B 共{}笔信号 (跳过{})".format(len(results), len(skipped)))
print("总T+20收益: 均{:+.2f}%  胜率{:.1f}% ({}赢/{}亏)".format(avg, wr, wins, losses))
print("放量大跌过滤后({}笔过滤):".format(filtered_cnt))
filtered_rets = [r["ret20"] for r in results if not r["filtered"]]
if filtered_rets:
    f_avg = sum(filtered_rets)/len(filtered_rets)
    f_wr = sum(1 for r in filtered_rets if r>0)/len(filtered_rets)*100
    print("  均{:+.2f}%  胜率{:.1f}%".format(f_avg, f_wr))
print("  过滤掉: 赢家{}笔, 输家{}笔".format(filtered_wins, filtered_losses))
print()

# 分割线
sep = "-"*90

# 表格头
hdr = "{:>3s} {:8s} {:12s} {:12s} {:12s} {:>8s} {:>8s} {:>10s} {:>4s}".format(
    "序号","代码","名称","信号日","T+1日","T+1涨跌","量比5日","T+20收益","过滤?")
print(hdr)
print(sep)

for i, r in enumerate(results, 1):
    tag = "⚠过滤" if r["filtered"] else ""
    line = "{:3d} {:8s} {:12s} {:12s} {:12s} {:>+8.1f}% {:8.2f} {:>+10.2f}% {:>4s}".format(
        i, r["symbol"], r["name"], r["sig_date"], r["t1_date"],
        r["t1_pct"], r["vr5"], r["ret20"], tag)
    print(line)

print()
for sym, ds, reason in skipped:
    print("  跳过 {} {}: {}".format(sym, ds, reason))

tc.close()
sc.close()
