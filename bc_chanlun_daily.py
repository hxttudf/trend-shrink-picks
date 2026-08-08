#!/usr/bin/env python3
"""每日缠论信号更新(增量): 扫描最近N日全市场信号 → 写chanlun_signals表
先删最近窗口内的旧信号(笔会随新K线修正), 再写入新计算信号
用法: python3 bc_chanlun_daily.py [window]
stdout输出当日摘要(供cron no_agent交付)"""
import sqlite3
import sys
import time

sys.path.insert(0, "/home/ubuntu/trend-shrink-picks")
from chanlun_full import analyze

SEQ_DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"
PICKS_DB = "/home/ubuntu/databases/trend_picks.db"
BATCH = 300
WINDOW = int(sys.argv[1]) if len(sys.argv) > 1 else 7


def main():
    seq = sqlite3.connect(SEQ_DB)
    syms = [r[0] for r in seq.execute(
        "SELECT DISTINCT symbol FROM stock_daily WHERE close_qfq>0 AND date>='2024-01-01'").fetchall()]
    names = {}
    for r in seq.execute("SELECT symbol, name FROM stock_basics WHERE date=(SELECT MAX(date) FROM stock_basics)"):
        names[r[0]] = r[1]

    picks = sqlite3.connect(PICKS_DB, timeout=30)
    picks.execute("""CREATE TABLE IF NOT EXISTS chanlun_signals (
        symbol TEXT NOT NULL, name TEXT, signal_type TEXT NOT NULL, signal_date TEXT NOT NULL,
        price REAL, ref_zd REAL, ref_zg REAL,
        PRIMARY KEY (symbol, signal_type, signal_date))""")
    picks.execute("CREATE INDEX IF NOT EXISTS idx_chanlun_date ON chanlun_signals(signal_date)")

    # 信号确认机制(用户定案): confirmed_date=信号首次被算出的日期; confirmed_later=1事后确认/0当天确认
    # 每天: 全历史结构(all_signals)同步写入+状态验证 — 当时算不出的信号, 事后确认时补录(confirmed_later=1)
    rows = seq.execute("SELECT MAX(date) FROM stock_daily").fetchone()
    last_date = rows[0] if rows and rows[0] else ""

    t0 = time.time()
    total = 0
    by_type = {}
    for batch_i in range(0, len(syms), BATCH):
        batch = syms[batch_i:batch_i + BATCH]
        for sym in batch:
            try:
                d = analyze(sym, window_days=WINDOW, include_all=True)
            except Exception:
                continue
            if d.get("error"):
                continue
            nm = names.get(sym, "?")
            if 'ST' in nm.upper():
                continue
            cur = []
            for bs in d.get("buy_sell", []):
                cur.append((sym, nm, bs['type'], bs['time'], bs['price'],
                            bs.get('zd') or 0, bs.get('zg') or 0,
                            bs.get('strength') or 'neutral', bs.get('score') or 50))
                by_type[bs['type']] = by_type.get(bs['type'], 0) + 1
            if cur:
                picks.executemany(
                    "INSERT OR REPLACE INTO chanlun_signals "
                    "(symbol, name, signal_type, signal_date, price, ref_zd, ref_zg, status, strength, strength_score) "
                    "VALUES (?,?,?,?,?,?,?,'ok',?,?)", cur)
                total += len(cur)
            # 全历史结构同步(UPSERT): 新信号记录确认信息(confirmed_date=今天, later=交易日差>=2才算事后), 已有只更新价格+状态
            today = d.get('cur_date') or last_date
            all_sigs = d.get("all_signals", [])
            sig_set = {(x['type'], x['time']) for x in all_sigs}
            # 交易日序列(该股票截至today): 事后确认判定用交易日差
            tds_sym = [r[0] for r in seq.execute(
                "SELECT date FROM stock_daily WHERE symbol=? AND date<=? ORDER BY date", (sym, today))]
            td_idx = {d: i for i, d in enumerate(tds_sym)}
            ci = td_idx.get(today, len(tds_sym) - 1)
            for x in all_sigs:
                si = td_idx.get(x['time'], -1)
                # 事后确认判定交给回放脚本(逐日验证首次可算出日); daily新记录默认当时确认(later=0, 不误标"后")
                later = 0
                picks.execute(
                    "INSERT INTO chanlun_signals (symbol, name, signal_type, signal_date, price, status, confirmed_date, confirmed_later) "
                    "VALUES (?,?,?,?,?,'ok',?,?) "
                    "ON CONFLICT(symbol, signal_type, signal_date) DO UPDATE SET price=excluded.price, status='ok'",
                    (sym, nm, x['type'], x['time'], x['price'], today, later))
                total += 1
            # 窗口内信号: 更新分数/强度(有score)
            for bs in d.get("buy_sell", []):
                picks.execute(
                    "UPDATE chanlun_signals SET strength=?, strength_score=?, status='ok' "
                    "WHERE symbol=? AND signal_type=? AND signal_date=?",
                    (bs.get('strength') or 'neutral', bs.get('score') or 50, sym, bs['type'], bs['time']))
            # 状态验证: 不在当前结构的记录 → error(被推翻/类型演化)
            try:
                rows = picks.execute(
                    "SELECT signal_type, signal_date, status FROM chanlun_signals WHERE symbol=?", (sym,)).fetchall()
                for t, dt, st in rows:
                    new_st = 'ok' if (t, dt) in sig_set else 'error'
                    if new_st != st:
                        picks.execute(
                            "UPDATE chanlun_signals SET status=? WHERE symbol=? AND signal_type=? AND signal_date=?",
                            (new_st, sym, t, dt))
            except Exception:
                pass
        picks.commit()
        if batch_i % (BATCH * 5) == 0:
            print(f"  批{batch_i//BATCH+1}: 累计{total}条, {time.time()-t0:.0f}s", flush=True)

    picks.commit()
    picks.close()
    seq.close()
    # 摘要(交付内容)
    parts = " ".join(f"{k}{v}" for k, v in sorted(by_type.items()))
    print(f"📐 缠论每日更新完成: {total}条信号 ({parts}) 耗时{time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
