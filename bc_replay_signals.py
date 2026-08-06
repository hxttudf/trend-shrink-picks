#!/usr/bin/env python3
"""滚动回放: 重建7/17-8/5历史信号(当时视角, 不含未来) + 对比今天视角标记推翻
确认日T(数据截止日) → 写入信号日=T前一个交易日的信号
status: 该信号在今天视角(chanlun_signals当前ok) → ok; 否则 error(被推翻)"""
import sqlite3, sys, time
sys.path.insert(0, '/home/ubuntu/trend-shrink-picks')
from chanlun_full import analyze

PICKS = '/home/ubuntu/databases/trend_picks.db'
SEQ = '/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db'
t0 = time.time()

seq = sqlite3.connect(SEQ)
trade_days = [r[0] for r in seq.execute(
    "SELECT DISTINCT date FROM stock_daily WHERE date<='2026-08-06' ORDER BY date")]
days = [d for d in trade_days if d >= '2026-07-20']  # 确认日: 7/20-8/6每个交易日
conf_pairs = []
for T in days:
    prev = [d for d in trade_days if d < T]
    if prev:
        conf_pairs.append((T, prev[-1]))
print(f"回放确认日: {[(t, s) for t, s in conf_pairs]}", flush=True)

syms = [r[0] for r in seq.execute(
    "SELECT DISTINCT symbol FROM stock_daily WHERE date='2026-08-06'")]
names = {r[0]: r[1] for r in seq.execute(
    "SELECT symbol, name FROM stock_basics WHERE date=(SELECT MAX(date) FROM stock_basics)")}
# 与正式任务一致: 跳过ST股(正式体系不要ST)
syms = [s for s in syms if 'ST' not in (names.get(s, '') or '').upper()]

picks = sqlite3.connect(PICKS, timeout=30)
now_ok = set()
for r in picks.execute("SELECT symbol, signal_type, signal_date FROM chanlun_signals WHERE status='ok'"):
    now_ok.add((r[0], r[1], r[2]))

rebuilt = {}  # sig_date -> [(sym, typ, price)]
for T, sig_date in conf_pairs:
    cnt = 0
    items = []
    for sym in syms:
        try:
            d = analyze(sym, window_days=7, as_of=T)
        except Exception:
            continue
        if d.get("error"):
            continue
        for bs in d.get("buy_sell", []):
            if bs['time'] == sig_date:
                items.append((sym, bs['type'], bs['price']))
                cnt += 1
    rebuilt[sig_date] = items
    print(f"  {T}: 重建{sig_date}信号 {cnt}条", flush=True)

total = 0
for sig_date, items in rebuilt.items():
    for sym, typ, price in items:
        st = 'ok' if (sym, typ, sig_date) in now_ok else 'error'
        picks.execute(
            "INSERT OR REPLACE INTO chanlun_signals "
            "(symbol, name, signal_type, signal_date, price, ref_zd, ref_zg, status) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (sym, names.get(sym, '?'), typ, sig_date, price, 0, 0, st))
        total += 1
picks.commit()
print(f"\n✅ 回放完成: 重建{total}条 (耗时{time.time()-t0:.0f}s)", flush=True)
for sig_date in sorted(rebuilt):
    items = rebuilt[sig_date]
    ok = sum(1 for s, t, p in items if (s, t, sig_date) in now_ok)
    print(f"  {sig_date}: {len(items)}条 (ok {ok} / 被推翻 {len(items)-ok})", flush=True)
