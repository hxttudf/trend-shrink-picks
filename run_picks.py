#!/usr/bin/env python3
"""每日趋势缩量选股 + T+N收益回填"""
import sqlite3, json, sys, os
from datetime import date, datetime, timedelta
from pathlib import Path

os.environ["HTTP_PROXY"] = ""
os.environ["HTTPS_PROXY"] = ""

SRC_DB = "/home/ubuntu/databases/Sequoia选股.db"
OUT_DB = "/home/ubuntu/databases/trend_picks.db"


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def init_out_db():
    conn = sqlite3.connect(OUT_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_picks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            name TEXT DEFAULT '',
            close_qfq REAL,
            ma20 REAL,
            ma60 REAL,
            dist_ma20 REAL,
            vol_ratio REAL,
            pct_20d REAL,
            volume REAL,
            avg_vol_20d REAL,
            buy_price REAL,
            ret_t1 REAL,
            ret_t2 REAL,
            ret_t3 REAL,
            ret_t5 REAL,
            ret_t10 REAL,
            ret_t15 REAL,
            ret_t20 REAL,
            created_at TEXT DEFAULT (datetime('now','+8 hours'))
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_dp_date ON daily_picks(date)
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_summary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT UNIQUE,
            pick_count INTEGER,
            symbols TEXT,
            run_at TEXT DEFAULT (datetime('now','+8 hours'))
        )
    """)
    conn.commit()
    return conn


def run_picks(today_str, out_conn):
    """运行选股逻辑，存入DB"""
    conn = sqlite3.connect(SRC_DB)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    log(f"扫描全市场 {today_str}")

    stocks = c.execute("""
        SELECT DISTINCT symbol FROM stock_daily WHERE date = ? AND close_qfq > 0
    """, (today_str,)).fetchall()

    if not stocks:
        log("无数据（非交易日或数据未更新）")
        conn.close()
        return []

    total = len(stocks)
    log(f"全市场 {total} 只")

    results = []
    batch_size = 500

    for i in range(0, total, batch_size):
        batch = [r["symbol"] for r in stocks[i:i + batch_size]]
        placeholders = ",".join(["?"] * len(batch))

        rows = c.execute(f"""
            SELECT symbol,
                   close_qfq as close,
                   volume,
                   (SELECT AVG(close_qfq) FROM (
                       SELECT close_qfq FROM stock_daily
                       WHERE symbol = a.symbol AND date <= a.date
                       ORDER BY date DESC LIMIT 20
                   )) as ma20,
                   (SELECT AVG(close_qfq) FROM (
                       SELECT close_qfq FROM stock_daily
                       WHERE symbol = a.symbol AND date <= a.date
                       ORDER BY date DESC LIMIT 60
                   )) as ma60,
                   (SELECT AVG(volume) FROM (
                       SELECT volume FROM stock_daily
                       WHERE symbol = a.symbol AND date < a.date AND volume > 0
                       ORDER BY date DESC LIMIT 20
                   )) as avg_vol_20d,
                   (SELECT close_qfq FROM stock_daily
                    WHERE symbol = a.symbol
                    AND date <= date(a.date, '-20 days')
                    ORDER BY date DESC LIMIT 1
                   ) as close_20d_ago
            FROM stock_daily a
            WHERE a.date = ? AND a.symbol IN ({placeholders})
              AND a.close_qfq > 0
        """, (today_str, *batch))

        for r in rows.fetchall():
            close = r["close"]
            ma20 = r["ma20"]
            ma60 = r["ma60"]
            avg_vol = r["avg_vol_20d"]
            close_20d = r["close_20d_ago"]

            if not all([ma20, ma60, avg_vol, close_20d]):
                continue
            if not (close > ma20 > ma60):
                continue

            dist = (close / ma20 - 1) * 100
            if not (10 <= dist < 20):
                continue

            volume = r["volume"]
            vol_ratio = volume / avg_vol if avg_vol > 0 else 999
            if not (vol_ratio < 0.3):
                continue

            pct_20d = (close / close_20d - 1) * 100
            if not (5 <= pct_20d < 25):
                continue

            results.append({
                "symbol": r["symbol"],
                "close_qfq": round(close, 4),
                "ma20": round(ma20, 4),
                "ma60": round(ma60, 4),
                "dist_ma20": round(dist, 2),
                "vol_ratio": round(vol_ratio, 2),
                "pct_20d": round(pct_20d, 2),
                "volume": int(volume) if volume else 0,
                "avg_vol_20d": int(avg_vol) if avg_vol else 0,
            })

    conn.close()

    # 计算买入价并存入DB
    if results:
        symbols = [p["symbol"] for p in results]
        names = _fetch_names(symbols)
        _save_picks(out_conn, results, names, today_str)
        _backfill_returns(out_conn, today_str)

    return results


def _fetch_names(symbols):
    if not symbols:
        return {}
    conn = sqlite3.connect(SRC_DB)
    try:
        ph = ",".join("?" * len(symbols))
        cur = conn.execute(
            f"SELECT symbol, name FROM stock_basics WHERE symbol IN ({ph}) GROUP BY symbol HAVING MAX(date)",
            symbols
        )
        return {r[0]: r[1] for r in cur.fetchall()}
    except Exception as e:
        log(f"取名称失败: {e}")
        return {}
    finally:
        conn.close()


def _save_picks(out_conn, picks, names, today_str):
    cursor = out_conn.cursor()
    for p in picks:
        sym = p["symbol"]
        cursor.execute("""
            INSERT INTO daily_picks 
            (date, symbol, name, close_qfq, ma20, ma60, dist_ma20, vol_ratio, pct_20d, volume, avg_vol_20d)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (
            today_str, sym, names.get(sym, ""),
            p["close_qfq"], p["ma20"], p["ma60"],
            p["dist_ma20"], p["vol_ratio"], p["pct_20d"],
            p["volume"], p["avg_vol_20d"],
        ))

    cursor.execute("""
        INSERT OR REPLACE INTO daily_summary (date, pick_count, symbols)
        VALUES (?, ?, ?)
    """, (today_str, len(picks), ", ".join(p["symbol"] for p in picks)))
    out_conn.commit()


def _backfill_returns(out_conn, today_str):
    """回填所有还未计算T+N收益的记录"""
    conn = sqlite3.connect(SRC_DB)
    c = conn.cursor()
    cur = out_conn.cursor()

    # 找出所有需要回填的记录
    cur.execute("""
        SELECT id, date, symbol FROM daily_picks 
        WHERE ret_t1 IS NULL
        ORDER BY date
    """)
    pending = cur.fetchall()
    if not pending:
        return

    log(f"回填T+N收益: {len(pending)}条记录")

    for pid, pick_date, sym in pending:
        # T+1开盘 = 买入价
        n1 = c.execute(
            "SELECT date, open, close, close_qfq FROM stock_daily WHERE symbol=? AND date>? ORDER BY date LIMIT 1",
            (sym, pick_date)
        ).fetchone()
        if not n1:
            continue

        n1_date, n1_open, n1_close, n1_qfq = n1

        # 调整买入价: open * (close_qfq/close)
        if n1_close and n1_close > 0:
            buy_price = round(n1_open * (n1_qfq / n1_close), 4)
        else:
            buy_price = n1_qfq

        # 获取从买入日开始的所有close_qfq
        future = c.execute(
            "SELECT close_qfq FROM stock_daily WHERE symbol=? AND date>=? ORDER BY date",
            (sym, n1_date)
        ).fetchall()
        prices = [r[0] for r in future if r[0] and r[0] > 0]

        # 计算 T+1 ~ T+20 (index 0=T+1收盘, 1=T+2...)
        rets = {}
        for label, offset in [("ret_t1", 0), ("ret_t2", 1), ("ret_t3", 2),
                              ("ret_t5", 4), ("ret_t10", 9), ("ret_t15", 14), ("ret_t20", 19)]:
            if offset < len(prices):
                rets[label] = round((prices[offset] / buy_price - 1) * 100, 2)
            else:
                rets[label] = None

        # 更新DB
        updates = [f"{k}=?" for k in rets.keys()] + ["buy_price=?"]
        vals = [rets[k] for k in rets.keys()] + [buy_price, pid]
        cur.execute(f"UPDATE daily_picks SET {','.join(updates)} WHERE id=?", vals)

    out_conn.commit()
    conn.close()
    log("回填完成")


def main():
    today_str = date.today().strftime("%Y-%m-%d")
    log(f"=== 趋势缩量选股 {today_str} ===")

    out_conn = init_out_db()
    picks = run_picks(today_str, out_conn)

    if picks:
        log(f"信号: {len(picks)}只")
        for p in picks[:5]:
            log(f"  {p['symbol']} 距MA20:{p['dist_ma20']:.1f}% 量比:{p['vol_ratio']:.2f} 20日涨:{p['pct_20d']:.1f}%")
    else:
        log("无信号")

    out_conn.close()
    return {"date": today_str, "picks": len(picks)}


if __name__ == "__main__":
    result = main()
    print(json.dumps(result, ensure_ascii=False))
