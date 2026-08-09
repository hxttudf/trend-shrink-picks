#!/usr/bin/env python3
"""一次性重算: DB全部二买/三买信号的strength_score(用v3公式, calc_score已更新)
分批处理(每只股票独立缓存K线, 内存友好)
"""
import sqlite3, sys, time
sys.path.insert(0, '/home/ubuntu/trend-shrink-picks')
import chanlun_full as cf

PICKS_DB = "/home/ubuntu/databases/trend_picks.db"
SEQ_DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"

def main():
    t0 = time.time()
    picks = sqlite3.connect(PICKS_DB)
    seq = sqlite3.connect(SEQ_DB)
    rows = picks.execute(
        "SELECT symbol, signal_type, signal_date FROM chanlun_signals "
        "WHERE signal_type IN ('二买','三买')").fetchall()
    by_sym = {}
    for sym, typ, sd in rows:
        by_sym.setdefault(sym, []).append((typ, sd))
    print(f"共 {len(by_sym)} 只股票, {len(rows)} 条二买/三买记录", flush=True)
    n_upd = 0
    n_skip = 0
    for si, (sym, recs) in enumerate(by_sym.items()):
        px = seq.execute(
            "SELECT date, high_qfq, low_qfq, close_qfq, volume FROM stock_daily "
            "WHERE symbol=? AND close_qfq>0 ORDER BY date", (sym,)).fetchall()
        if len(px) < 80:
            n_skip += len(recs)
            continue
        dates = [r[0] for r in px]
        highs = [r[1] or 0 for r in px]
        lows = [r[2] or 0 for r in px]
        closes = [r[3] for r in px]
        vols = [r[4] or 0 for r in px]
        for typ, sd in recs:
            try:
                i = dates.index(sd)
            except ValueError:
                n_skip += 1
                continue
            if i < 80:
                n_skip += 1
                continue
            try:
                sc = cf.calc_score(typ, 0, 0, closes, highs, lows, vols, i)
            except Exception:
                sc = 50.0
            st = cf.calc_strength(sc)
            picks.execute(
                "UPDATE chanlun_signals SET strength_score=?, strength=? WHERE symbol=? AND signal_type=? AND signal_date=?",
                (sc, st, sym, typ, sd))
            n_upd += 1
        picks.commit()
        if (si + 1) % 500 == 0:
            print(f"  {si+1} 只, 更新{n_upd}, 耗时{time.time()-t0:.0f}s", flush=True)
    picks.commit()
    picks.close(); seq.close()
    print(f"✅ 完成: 更新{n_upd}条, 跳过{n_skip}, 耗时{time.time()-t0:.0f}s")

if __name__ == "__main__":
    main()
