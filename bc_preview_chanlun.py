#!/usr/bin/env python3
"""盘中缠论信号预览 — 用 stock_daily历史 + preview_daily(今日盘中) 跑信号
输出到 trend_picks.db.preview_signals 独立表(每次覆盖)
绝不写 chanlun_signals(只有收盘后 bc_chanlun_daily 才写正式表)
status: 今日='preview'(未确认, 收盘后可能变) / 窗口内历史='ok'
用法: python3 bc_preview_chanlun.py [window]
stdout: 今日预览信号摘要"""
import sqlite3
import sys
import time

sys.path.insert(0, "/home/ubuntu/trend-shrink-picks")
from chanlun_full import merge_inclusion, calc_bi, calc_zhongshu_bi, macd_data, find_all_signals

SEQ_DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"
PICKS_DB = "/home/ubuntu/databases/trend_picks.db"
BATCH = 300
WINDOW = int(sys.argv[1]) if len(sys.argv) > 1 else 7
MIN_BARS = 150


def main():
    t0 = time.time()
    seq = sqlite3.connect(SEQ_DB)
    pd = seq.execute("SELECT MAX(date) FROM preview_daily").fetchone()
    if not pd or not pd[0]:
        print("无盘中数据, 先跑 bc_preview_data.py")
        return
    TODAY = pd[0]
    print(f"预览日: {TODAY}", flush=True)
    syms = [r[0] for r in seq.execute(
        "SELECT DISTINCT symbol FROM stock_daily WHERE close_qfq>0 AND date>='2019-01-01'").fetchall()]
    names = {}
    for r in seq.execute("SELECT symbol, name FROM stock_basics WHERE date=(SELECT MAX(date) FROM stock_basics)"):
        names[r[0]] = r[1]

    picks = sqlite3.connect(PICKS_DB, timeout=30)
    picks.execute("DROP TABLE IF EXISTS preview_signals")
    picks.execute("""CREATE TABLE preview_signals(
        symbol TEXT NOT NULL, name TEXT, signal_type TEXT NOT NULL, signal_date TEXT NOT NULL,
        price REAL, ref_zd REAL, ref_zg REAL, status TEXT DEFAULT 'preview',
        ts TEXT DEFAULT (datetime('now','localtime')))""")
    picks.execute("CREATE INDEX idx_ps_date ON preview_signals(signal_date)")

    total = 0
    by_type = {}
    today_sigs = []
    for batch_i in range(0, len(syms), BATCH):
        batch = syms[batch_i:batch_i + BATCH]
        rows = seq.execute(
            "SELECT symbol, date, high, low, close, close_qfq FROM stock_daily "
            f"WHERE symbol IN ({','.join('?' * len(batch))}) AND close_qfq>0 AND date<? "
            "ORDER BY symbol, date", batch + [TODAY]).fetchall()
        prow = seq.execute(
            "SELECT symbol, high, low, close, close_qfq FROM preview_daily "
            f"WHERE symbol IN ({','.join('?' * len(batch))})", batch).fetchall()
        pper = {r[0]: r for r in prow}
        per = {}
        for r in rows:
            per.setdefault(r[0], []).append(r)
        for sym in batch:
            data = per.get(sym, [])
            pr = pper.get(sym)
            if pr is not None:
                # 追加今日盘中K线(用qfq复权)
                ratio = pr[4] / pr[3] if pr[3] else 1
                data = data + [(sym, TODAY, pr[1] * ratio, pr[2] * ratio, pr[3] * ratio, pr[4])]
            if len(data) < MIN_BARS:
                continue
            qf = []
            for r in data:
                ratio = r[5] / r[4] if r[4] else 1
                qf.append([r[1], r[2] * ratio, r[3] * ratio, r[5]])
            try:
                merged = merge_inclusion(qf)
                bi = calc_bi(merged)
                if len(bi) < 8:
                    continue
                zs_list = calc_zhongshu_bi(bi)
                dif, dea, hist = macd_data([r[3] for r in qf])
                sigs = find_all_signals(bi, zs_list, dif, merged)
            except Exception:
                continue
            nm = names.get(sym, "?")
            if 'ST' in nm.upper():
                continue
            wd = set(r[0] for r in qf[-WINDOW:])
            cur = []
            for typ, d, p, zd, zg in sigs:
                if d in wd:
                    # 预览口径: 最后2个交易日(今+昨)未确认=preview, 更早已T+1确认=ok
                    st = 'preview' if d >= qf[-2][0] else 'ok'
                    cur.append((sym, nm, typ, d, p, zd, zg, st))
                    by_type[typ] = by_type.get(typ, 0) + 1
                    if d == TODAY:
                        today_sigs.append((sym, nm, typ, d, p))
            if cur:
                picks.executemany(
                    "INSERT INTO preview_signals "
                    "(symbol, name, signal_type, signal_date, price, ref_zd, ref_zg, status) "
                    "VALUES (?,?,?,?,?,?,?,?)", cur)
                total += len(cur)
        picks.commit()
        if batch_i % (BATCH * 5) == 0:
            print(f"  批{batch_i//BATCH+1}: 累计{total}条, {time.time()-t0:.0f}s", flush=True)

    picks.commit()
    picks.close()
    seq.close()
    parts = " ".join(f"{k}{v}" for k, v in sorted(by_type.items()))
    print(f"预览信号: {total}条 ({parts}) 耗时{time.time()-t0:.0f}s")
    # 上一交易日(正式表即将写入的) + 今日(新形成) 分开列
    pconn = sqlite3.connect(PICKS_DB)
    prev_sigs = pconn.execute(
        "SELECT symbol, name, signal_type, price FROM preview_signals "
        "WHERE signal_date=(SELECT MAX(signal_date) FROM preview_signals WHERE status='preview' AND signal_date<?) "
        "AND status='preview' ORDER BY signal_type, symbol", (TODAY,)).fetchall()
    pconn.close()
    print(f"===== 上一交易日预览信号 {len(prev_sigs)}条 (未确认, 收盘后写入正式表) =====")
    for sym, nm, typ, p in prev_sigs[:20]:
        print(f"  {sym} {nm} {typ} @{p:.2f}")
    if len(prev_sigs) > 20:
        print(f"  ... 共{len(prev_sigs)}条")
    print(f"===== 今日({TODAY})新信号 {len(today_sigs)}条 =====")
    for sym, nm, typ, d, p in today_sigs:
        print(f"  {sym} {nm} {typ} @{p:.2f}")


if __name__ == "__main__":
    main()
