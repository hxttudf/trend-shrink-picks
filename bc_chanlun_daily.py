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
    cats = {}
    # 每股取最新日期记录(不依赖统一MAX(date): 部分股票/ETF当日未写入时名称不缺失)
    for r in seq.execute(
            "SELECT b.symbol, b.name, b.is_etf FROM stock_basics b "
            "JOIN (SELECT symbol, MAX(date) md FROM stock_basics GROUP BY symbol) x "
            "ON b.symbol=x.symbol AND b.date=x.md"):
        names[r[0]] = r[1]
        # is_etf三态(0=股票/1=ETF/2=指数) → category; 无basics行按后缀兜底
        cats[r[0]] = {0: 'stock', 1: 'etf', 2: 'index'}.get(r[2],
                          'index' if '.' in r[0] else 'stock')

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
    win_n = 0    # 7日窗口内实际信号数(=sum(by_type), 摘要括号口径)
    sync_n = 0   # 全历史结构UPSERT次数(多为已有行重写, 不代表新信号)
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
            _cat = cats.get(sym, 'index' if '.' in sym else 'stock')
            for bs in d.get("buy_sell", []):
                cur.append((sym, nm, bs['type'], bs['time'], bs['price'],
                            bs.get('zd') or 0, bs.get('zg') or 0,
                            bs.get('strength') or 'neutral', bs.get('score') or 50, _cat))
                by_type[bs['type']] = by_type.get(bs['type'], 0) + 1
                win_n += 1
            if cur:
                picks.executemany(
                    "INSERT INTO chanlun_signals "
                    "(symbol, name, signal_type, signal_date, price, ref_zd, ref_zg, status, strength, strength_score, category) "
                    "VALUES (?,?,?,?,?,?,?,'ok',?,?,?) "
                    "ON CONFLICT(symbol, signal_type, signal_date) DO UPDATE SET "
                    "price=excluded.price, ref_zd=excluded.ref_zd, ref_zg=excluded.ref_zg, "
                    "status='ok', strength=excluded.strength, strength_score=excluded.strength_score, "
                    "category=excluded.category", cur)
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
                    "INSERT INTO chanlun_signals (symbol, name, signal_type, signal_date, price, status, confirmed_date, confirmed_later, category) "
                    "VALUES (?,?,?,?,?,'ok',?,?,?) "
                    "ON CONFLICT(symbol, signal_type, signal_date) DO UPDATE SET price=excluded.price, status='ok'",
                    (sym, nm, x['type'], x['time'], x['price'], today, later, _cat))
                total += 1
                sync_n += 1
            # 窗口内信号: 更新分数/强度(有score)
            for bs in d.get("buy_sell", []):
                picks.execute(
                    "UPDATE chanlun_signals SET strength=?, strength_score=?, status='ok' "
                    "WHERE symbol=? AND signal_type=? AND signal_date=?",
                    (bs.get('strength') or 'neutral', bs.get('score') or 50, sym, bs['type'], bs['time']))
            # 状态验证(用户定案): 在结构=ok(有效); 不在结构=证伪(error) — 结构消失即证伪
            try:
                rows = picks.execute(
                    "SELECT signal_type, signal_date, status FROM chanlun_signals WHERE symbol=?", (sym,)).fetchall()
                for t, dt, st in rows:
                    new_st = 'ok' if (t, dt) in sig_set else 'error'
                    if new_st != st:
                        if new_st == 'error':
                            # ok→error: 记录推翻日期(当天) + 推翻时机(overturned_later: 推翻日-信号日交易日差>=2=1事后推翻/<=1=0当时推翻, 同confirmed_later语义)
                            si = td_idx.get(dt, -1)
                            ov_later = 1 if (si >= 0 and ci - si >= 2) else (0 if si >= 0 else None)
                            picks.execute(
                                "UPDATE chanlun_signals SET status='error', overturned_date=?, overturned_later=? WHERE symbol=? AND signal_type=? AND signal_date=?",
                                (today, ov_later, sym, t, dt))
                        else:
                            picks.execute(
                                "UPDATE chanlun_signals SET status='ok', overturned_date=NULL, overturned_later=NULL WHERE symbol=? AND signal_type=? AND signal_date=?",
                                (sym, t, dt))
            except Exception:
                pass
        picks.commit()
        if batch_i % (BATCH * 5) == 0:
            print(f"  批{batch_i//BATCH+1}: 累计{total}条, {time.time()-t0:.0f}s", flush=True)

    picks.commit()
    # 补录欠账: confirmed_date为空的信号用signal_date回填(近似首次算出日下界; 新信号INSERT时已写today, 不覆盖), later=0当天确认
    picks.execute("UPDATE chanlun_signals SET confirmed_date=signal_date, confirmed_later=COALESCE(confirmed_later,0) WHERE confirmed_date IS NULL")
    picks.commit()
    picks.close()
    seq.close()
    # 摘要(交付内容) — 两个口径分开, 勿混用total:
    #   sync_n = 全历史结构UPSERT次数(多为已有行重写), win_n+by_type = 7日窗口实际信号
    parts = " ".join(f"{k}{v}" for k, v in sorted(by_type.items()))
    print(f"📐 缠论每日更新完成: 当日窗口信号{win_n}条 ({parts}); 全历史结构同步{sync_n}次 耗时{time.time()-t0:.0f}s")
    # 重建日期统计缓存(chanlun_dates_cache, 供dates接口直读毫秒返回)
    try:
        import subprocess
        subprocess.run([sys.executable, '/home/ubuntu/trend-shrink-picks/rebuild_dates_cache.py'],
                       timeout=300, capture_output=True)
        print("日期统计缓存已重建")
    except Exception as e:
        print(f"日期统计缓存重建失败: {e}")


if __name__ == "__main__":
    main()
