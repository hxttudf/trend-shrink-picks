#!/usr/bin/env python3
"""盘中数据拉取(预览用) — 复用 update_daily 的腾讯K线拉取
→ sequoia_v2.db.preview_daily 临时表(与 stock_daily 完全隔离, 每次覆盖)
收盘后由 update_daily.py 正常写正式数据, 本表作废
用法: python3 bc_preview_data.py
stdout: 拉取摘要"""
import sys, time, sqlite3, concurrent.futures
from datetime import date

sys.path.insert(0, "/home/ubuntu/Sequoia-X-a")
import backfill_v2

SEQ_DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"
TODAY = date.today().strftime("%Y-%m-%d")


def _sina_today(code, market):
    """新浪兜底: 返回(code, k)或None. 新浪不复权 → close_qfq=close; volume股→手÷100"""
    import subprocess as _sp
    prefix = "sh" if market == "1" else "sz"
    url = (f"https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData"
           f"?symbol={prefix}{code}&scale=240&ma=no&datalen=3")
    try:
        r = _sp.run(["curl", "-sL", "-m", "12", "--noproxy", "*", url,
                     "-H", "Referer: https://finance.sina.com.cn"], capture_output=True, text=True)
        import json
        data = json.loads(r.stdout) if r.stdout else []
        for d in data:
            if d.get("day", "").startswith(TODAY):
                v = float(d["volume"]) / 100.0
                return code, {"date": TODAY, "open": float(d["open"]), "high": float(d["high"]),
                              "low": float(d["low"]), "close": float(d["close"]),
                              "volume": v, "close_qfq": float(d["close"]),
                              "amount": round(float(d["close"]) * v, 2)}
    except Exception:
        pass
    return None


def fetch_one(code, name, market):
    try:
        klines = backfill_v2.fetch_kline_tx(code, market)
        for k in klines:
            if k["date"] == TODAY:
                return code, k
    except Exception:
        pass
    # 腾讯失败(限流/超时) → 新浪兜底
    return _sina_today(code, market) or (code, None)


def main():
    t0 = time.time()
    print(f"[{TODAY}] 获取全量A股列表...", flush=True)
    all_stocks = backfill_v2.get_all_stocks_sina()
    if not all_stocks:
        print("获取A股列表失败")
        sys.exit(1)
    filtered = [(c, n, m) for c, n, m in all_stocks if not c.startswith(("8", "4", "920"))]
    print(f"股票: {len(filtered)} 只(跳过北交所{len(all_stocks)-len(filtered)})", flush=True)

    # ETF并入预信号链路(与正式update_etf同源): stock_basics is_etf=1 → 腾讯fetch_kline_tx
    seq0 = sqlite3.connect("/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db")
    etfs = [r[0] for r in seq0.execute(
        "SELECT DISTINCT symbol FROM stock_basics WHERE is_etf=1 ORDER BY symbol")]
    seq0.close()
    # ETF市场码: 5开头=沪(1), 其余(15/16等深市)=0
    etf_list = [(c, "", ("1" if c[0] == "5" else "0")) for c in etfs]
    filtered = filtered + etf_list
    print(f"股票 {len(filtered) - len(etf_list)} 只 + ETF {len(etf_list)} 只, 合计拉取 {len(filtered)}", flush=True)

    done = fails = 0
    rows = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(fetch_one, c, n, m): c for c, n, m in filtered}
        for future in concurrent.futures.as_completed(futures):
            code, k = future.result()
            if k is None:
                fails += 1
                continue
            rows.append((code, TODAY, k["open"], k["high"], k["low"], k["close"],
                         k["volume"], k.get("close_qfq") or k["close"], k.get("amount") or 0))
            done += 1
            if len(rows) % 500 == 0:
                print(f"  {done}/{len(filtered)} 失败{fails}", flush=True)

    if not rows:
        print("无数据")
        return
    conn = sqlite3.connect(SEQ_DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS preview_daily(
        symbol TEXT, date TEXT, open REAL, high REAL, low REAL,
        close REAL, volume REAL, close_qfq REAL, amount REAL,
        batch_date TEXT, batch_seq INTEGER, batch_label TEXT,
        ts TEXT DEFAULT (datetime('now','localtime')))""")
    # 批次标识(与bc_preview_chanlun一致): 时段序号固定 midday=1/close=2, 不随具体时间漂移
    import datetime as _dt
    _h = _dt.datetime.now().hour
    BD = TODAY
    BS = 1 if 11 <= _h < 14 else 2
    BL = 'midday' if BS == 1 else 'close'
    print(f"盘中K批次: {BD} seq={BS} ({BL})", flush=True)
    conn.execute("DELETE FROM preview_daily WHERE batch_date < date('now','localtime','-7 days')")  # 留痕: 保留7天, 不覆盖
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pd_sym ON preview_daily(symbol)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pd_batch ON preview_daily(batch_date, batch_seq)")
    conn.executemany(
        "INSERT INTO preview_daily (symbol,date,open,high,low,close,volume,close_qfq,amount,batch_date,batch_seq,batch_label) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [r + (BD, BS, BL) for r in rows])
    conn.commit()
    conn.close()
    print(f"✅ 盘中数据: {done}只(失败{fails}) -> preview_daily | {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
