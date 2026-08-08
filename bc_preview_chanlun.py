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


def laogao_conds(closes, vols, i):
    """老高5条件(D3): 均线多头/回踩2-15/底部120/均线上翘/放量启动"""
    if i < 60:
        return None
    cur = closes[i]
    ma20 = sum(closes[i - 19:i + 1]) / 20
    ma60 = sum(closes[i - 59:i + 1]) / 60
    ma20_5 = sum(closes[i - 24:i - 4]) / 20
    if ma60 <= 0:
        return None
    dist = (cur - ma20) / ma20 * 100
    lo = min(closes[max(0, i - 249):i + 1])
    li = closes[max(0, i - 249):i + 1].index(lo) + max(0, i - 249)
    r7 = False
    for k in range(1, 11):
        if i - k < 1:
            break
        chg = (closes[i - k] / closes[i - k - 1] - 1) * 100
        a = sum(vols[max(0, i - k - 20):i - k]) / min(20, i - k) if i - k > 0 else 1
        if chg >= 3 and (vols[i - k] / a if a else 0) >= 1.5:
            r7 = True
            break
    return (cur > ma20 > ma60, 2 <= dist <= 15, (i - li) >= 120, ma20 > ma20_5, r7)


def _lin(v, p20, p80, lo, hi):
    """线性映射: 因子值v按历史分位边界[p20,p80]映射到[lo,hi], 超出截断"""
    if p80 <= p20:
        return 0.0
    x = (v - p20) / (p80 - p20)
    return max(lo, min(hi, lo + x * (hi - lo)))


def calc_score(typ, zd, zg, closes, highs, lows, vols, i):
    """分类型连续强度分(0-100): 一买=深跌超跌(原); 二买=强势回调低吸(站上MA20+回调深度);
    三买=突破回踩(突破力度+箱体高度-回踩深度) — 边界来自2021-2026回测样本外验证
    与chanlun_full.calc_score一致(分类型打分, 互不影响); 只用≤i数据"""
    if i < 20 or i >= len(closes):
        return 50.0
    c0 = closes[i]
    if c0 <= 0:
        return 50.0
    if typ == '一买':
        avg = sum(vols[i - 20:i]) / 20 if i >= 20 else 1
        vr = vols[i] / avg if avg else 1
        s = 50.0 + max(-20.0, min(20.0, (vr - 1) * 15))
        c10 = closes[i - 10]
        chg = (c0 - c10) / c10 * 100 if c10 else 0
        s += max(-25.0, min(25.0, -chg * 0.8))
        return round(max(0.0, min(100.0, s)), 1)
    if typ == '二买':
        # 胜率导向v2(回测样本外: 胜率top20% 62.6% vs 基准60.7%, 收益4.69%): 
        # 深回踩+位置适中(避开过热)+站上均线适度+距低点近+涨停少
        if i < 60:
            ma20 = sum(closes[i - 20:i + 1]) / 21
            L20 = min(lows[i - 20:i + 1])
            b5 = (c0 / ma20 - 1) * 100 if ma20 > 0 else 0
            b1 = (c0 - L20) / L20 * 100 if L20 > 0 else 0
            s = 50.0 + _lin(b5, -1.62, 5.66, -15, 15) + _lin(b1, -65.53, 9.73, -12, 12)
            return round(max(0.0, min(100.0, s)), 1)
        ma20 = sum(closes[i - 20:i + 1]) / 21
        L60 = min(lows[i - 60:i + 1])
        H60 = max(highs[i - 60:i + 1])
        H40 = max(highs[i - 40:i + 1])
        b5 = (c0 / ma20 - 1) * 100 if ma20 > 0 else 0
        t1 = (c0 - H40) / H40 * 100 if H40 > 0 else 0
        pos60 = (c0 - L60) / (H60 - L60) * 100 if H60 > L60 else 50
        dist_lo = (c0 / L60 - 1) * 100 if L60 > 0 else 0
        limit20 = int(sum(1 for k in range(i - 20, i + 1) if k > 0 and closes[k] and closes[k - 1] and highs[k] > closes[k - 1] * 1.09))
        s = 50.0 + _lin(-t1, 0, 35, -10, 12)
        if pos60 < 30:
            s += (pos60 - 30) * 0.3
        elif pos60 <= 65:
            s += 8.0
        else:
            s += 8.0 - (pos60 - 65) * 0.45
        s += _lin(b5, -4, 7, -8, 8)
        if b5 > 10:
            s -= (b5 - 10) * 0.6
        if dist_lo < 10:
            s += dist_lo * 0.2
        elif dist_lo <= 35:
            s += 5.0
        else:
            s += 5.0 - (dist_lo - 35) * 0.3
        s -= limit20 * 2.0
        return round(max(0.0, min(100.0, s + 15.0)), 1)  # +15平移: 排序不变, 恢复75+强信号区间
    if typ == '三买':
        H40 = max(highs[i - 40:i + 1])
        H40p = max(highs[i - 80:i - 40]) if i >= 80 else H40
        L60 = min(lows[i - 60:i + 1])
        t2 = (H40 / H40p - 1) * 100 if H40p > 0 else 0
        t5 = (H40 - L60) / L60 * 100 if L60 > 0 else 0
        t1 = (c0 - H40) / H40 * 100 if H40 > 0 else 0
        s = 50.0 + _lin(t2, -0.98, 29.25, 0, 15) + _lin(t5, 24.49, 68.88, 0, 15) + _lin(-t1, 9.97, 77.37, -8, 8)
        return round(max(0.0, min(100.0, s)), 1)
    # 卖点: 原逻辑(涨得多分高)
    c10 = closes[i - 10]
    chg = (c0 - c10) / c10 * 100 if c10 else 0
    s = 50.0 + max(-25.0, min(25.0, chg * 0.8))
    return round(max(0.0, min(100.0, s)), 1)


def calc_strength(score):
    """分数驱动强弱: >=75强(买入纪律), <=40弱"""
    if score >= 75:
        return 'strong'
    if score <= 40:
        return 'weak'
    return 'neutral'


def main():
    t0 = time.time()
    seq = sqlite3.connect(SEQ_DB)
    pd = seq.execute("SELECT MAX(date) FROM preview_daily").fetchone()
    if not pd or not pd[0]:
        print("无盘中数据, 先跑 bc_preview_data.py")
        return
    TODAY = pd[0]
    # 全市场统一的未确认窗口: 今天 + 上一交易日
    prev_day = seq.execute(
        "SELECT MAX(date) FROM stock_daily WHERE date<?", (TODAY,)).fetchone()[0]
    UNCONFIRMED = {TODAY, prev_day}
    print(f"预览日: {TODAY} (未确认窗口: {prev_day},{TODAY})", flush=True)
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
        d3 INTEGER DEFAULT 0, w30 INTEGER DEFAULT 0, strength TEXT DEFAULT 'neutral',
        strength_score REAL DEFAULT 50,
        ts TEXT DEFAULT (datetime('now','localtime')))""")
    picks.execute("CREATE INDEX idx_ps_date ON preview_signals(signal_date)")
    # worth映射(W30用)
    worth = {}
    for r in picks.execute("SELECT date, symbol FROM bottom_confirm_picks WHERE status='worth'").fetchall():
        worth.setdefault(r[1], []).append(r[0])
    import datetime

    total = 0
    by_type = {}
    today_sigs = []
    for batch_i in range(0, len(syms), BATCH):
        batch = syms[batch_i:batch_i + BATCH]
        rows = seq.execute(
            "SELECT symbol, date, high, low, close, close_qfq, volume FROM stock_daily "
            f"WHERE symbol IN ({','.join('?' * len(batch))}) AND close_qfq>0 AND date<? "
            "ORDER BY symbol, date", batch + [TODAY]).fetchall()
        prow = seq.execute(
            "SELECT symbol, high, low, close, close_qfq, volume FROM preview_daily "
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
                data = data + [(sym, TODAY, pr[1] * ratio, pr[2] * ratio, pr[3] * ratio, pr[4], pr[5])]
            if len(data) < MIN_BARS:
                continue
            qf = []
            vols = []
            for r in data:
                ratio = r[5] / r[4] if r[4] else 1
                qf.append([r[1], r[2] * ratio, r[3] * ratio, r[5]])
                vols.append(r[6] or 0)
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
                    # 只写未确认窗口(全市场最后2个交易日: 今+昨), 更早的已确认信号由正式表提供
                    if d not in UNCONFIRMED:
                        continue
                    st = 'preview'
                    # D3标记(二买+老高5条件) / W30标记(买点+worth后30天内) / 强度评分
                    f_d3 = 0
                    f_w30 = 0
                    f_str = 'neutral'
                    f_score = 50
                    try:
                        di = next(i for i, r in enumerate(qf) if r[0] == d)
                        closes_qf = [r[3] for r in qf]
                        highs_qf = [r[1] for r in qf]
                        lows_qf = [r[2] for r in qf]
                        f_score = calc_score(typ, zd, zg, closes_qf, highs_qf, lows_qf, vols, di)
                        f_str = calc_strength(f_score)
                        if typ == '二买':
                            c = laogao_conds(closes_qf, vols, di)
                            if c and c[0] and c[1] and c[2] and c[3] and c[4]:
                                f_d3 = 1
                        if '买' in typ:
                            for w in worth.get(sym, []):
                                d0 = datetime.date.fromisoformat(w)
                                d1 = datetime.date.fromisoformat(d)
                                if 0 <= (d1 - d0).days <= 30:
                                    f_w30 = 1
                                    break
                    except Exception:
                        pass
                    cur.append((sym, nm, typ, d, p, zd, zg, st, f_d3, f_w30, f_str, f_score))
                    by_type[typ] = by_type.get(typ, 0) + 1
                    if d == TODAY:
                        today_sigs.append((sym, nm, typ, d, p))
            if cur:
                picks.executemany(
                    "INSERT INTO preview_signals "
                    "(symbol, name, signal_type, signal_date, price, ref_zd, ref_zg, status, d3, w30, strength, strength_score) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", cur)
                total += len(cur)
        picks.commit()
        if batch_i % (BATCH * 5) == 0:
            print(f"  批{batch_i//BATCH+1}: 累计{total}条, {time.time()-t0:.0f}s", flush=True)

    picks.commit()
    picks.close()
    seq.close()
    parts = " ".join(f"{k}{v}" for k, v in sorted(by_type.items()))
    print(f"预览信号: {total}条 ({parts}) 耗时{time.time()-t0:.0f}s")
    # 未确认窗口(最后2个交易日)信号 + 今日新信号 分开列
    pconn = sqlite3.connect(PICKS_DB)
    prev_sigs = pconn.execute(
        "SELECT symbol, name, signal_type, price FROM preview_signals "
        "WHERE status='preview' ORDER BY signal_type, symbol").fetchall()
    prev_dates = pconn.execute(
        "SELECT DISTINCT signal_date FROM preview_signals WHERE status='preview' ORDER BY signal_date").fetchall()
    pconn.close()
    ds = ",".join(r[0] for r in prev_dates)
    print(f"===== 未确认窗口({ds})预览信号 {len(prev_sigs)}条 (未确认, 收盘后写入正式表) =====")
    for sym, nm, typ, p in prev_sigs[:20]:
        print(f"  {sym} {nm} {typ} @{p:.2f}")
    if len(prev_sigs) > 20:
        print(f"  ... 共{len(prev_sigs)}条")
    print(f"===== 今日({TODAY})新信号 {len(today_sigs)}条 =====")
    for sym, nm, typ, d, p in today_sigs:
        print(f"  {sym} {nm} {typ} @{p:.2f}")


if __name__ == "__main__":
    main()
