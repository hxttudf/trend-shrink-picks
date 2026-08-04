#!/usr/bin/env python3
"""D3/W30 标记落库 — 对最近N天缠论买点算标记, 更新 chanlun_signals.d3/w30 列
D3: 二买 + 老高5条件(均线多头+回踩2-15%+底部>=120天+均线上翘+放量启动)
W30: 缠论买点 + worth确认后30天内(含同日)
用法: python3 bc_flag_d3w30.py [窗口天数=40]
stdout输出摘要"""
import sqlite3, sys, time
from datetime import date

TREND_DB = "/home/ubuntu/databases/trend_picks.db"
SEQ_DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"
WIN = int(sys.argv[1]) if len(sys.argv) > 1 else 40  # 回溯窗口(天)


def laogao_conds(closes, vols, i):
    """老高5条件(D3用): 返回(r1,r2,r4,r5,r7)或None"""
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


def calc_strength(typ, zd, zg, closes, vols, i):
    """强度评分(回测最优参数): 强=放量1.5x+深度超跌20%/远离中枢5%; 弱=极度缩量0.6x/贴中枢3%"""
    if i < 20 or i >= len(closes):
        return 'neutral'
    c0 = closes[i]
    avg = sum(vols[i - 20:i]) / 20 if i >= 20 else 1
    vr = vols[i] / avg if avg else 0
    if typ == '三买' and zg and zg > 0:
        brk = (c0 - zg) / zg * 100
        if brk > 5 and vr > 1.5:
            return 'strong'
        if brk < 3:
            return 'weak'
        return 'neutral'
    if typ in ('一买', '二买'):
        c10 = closes[i - 10]
        drop10 = (c0 - c10) / c10 * 100 if c10 else 0
        if drop10 < -20:
            return 'strong'
        if vr < 0.6 and drop10 > -20:
            return 'weak'
        return 'neutral'
    if typ == '三卖' and zd and zd > 0:
        brk = (zd - c0) / zd * 100
        if brk > 5 and vr > 1.5:
            return 'strong'
        if brk < 3:
            return 'weak'
        return 'neutral'
    if typ in ('一卖', '二卖'):
        c10 = closes[i - 10]
        rise10 = (c0 - c10) / c10 * 100 if c10 else 0
        if rise10 > 20:
            return 'strong'
        if vr < 0.6 and rise10 < 20:
            return 'weak'
        return 'neutral'
    return 'neutral'


def main():
    t0 = time.time()
    picks = sqlite3.connect(TREND_DB)
    seq = sqlite3.connect(SEQ_DB)
    # worth映射
    worth = {}
    for r in picks.execute(
            "SELECT date, symbol FROM bottom_confirm_picks WHERE status='worth'").fetchall():
        worth.setdefault(r[1], []).append(r[0])

    # 窗口内全部信号(买+卖)
    rows = picks.execute(
        "SELECT symbol, name, signal_type, signal_date, ref_zd, ref_zg FROM chanlun_signals "
        "WHERE status='ok' AND signal_date >= date('now', ?)",
        (f'-{WIN} day',)).fetchall()
    # 先清窗口内标记
    picks.execute("UPDATE chanlun_signals SET d3=0, w30=0, strength='neutral' WHERE signal_date >= date('now', ?)",
                  (f'-{WIN} day',))
    picks.commit()

    cache = {}
    n_d3 = n_w30 = 0
    n_str = {'strong': 0, 'neutral': 0, 'weak': 0}
    for sym, name, typ, sdate, zd, zg in rows:
        if sym not in cache:
            k = seq.execute(
                "SELECT date, close, close_qfq, volume FROM stock_daily "
                "WHERE symbol=? AND close_qfq>0 ORDER BY date", (sym,)).fetchall()
            if len(k) < 120:
                cache[sym] = None
                continue
            cache[sym] = ([r[2] for r in k], [r[3] for r in k], {r[0]: i for i, r in enumerate(k)})
        pc = cache[sym]
        if pc is None:
            continue
        closes, vols, d2i = pc
        idx = d2i.get(sdate)
        if idx is None:
            continue
        # 强度评分(全部信号)
        st = calc_strength(typ, zd, zg, closes, vols, idx)
        picks.execute("UPDATE chanlun_signals SET strength=? WHERE symbol=? AND signal_date=? AND signal_type=?",
                      (st, sym, sdate, typ))
        n_str[st] += 1
        f_d3 = f_w30 = 0
        if typ == '二买':
            c = laogao_conds(closes, vols, idx)
            if c and c[0] and c[1] and c[2] and c[3] and c[4]:
                f_d3 = 1
        for w in worth.get(sym, []):
            d0 = date.fromisoformat(w)
            d1 = date.fromisoformat(sdate)
            if 0 <= (d1 - d0).days <= 30:
                f_w30 = 1
                break
        if f_d3 or f_w30:
            picks.execute("UPDATE chanlun_signals SET d3=?, w30=? WHERE symbol=? AND signal_date=? AND signal_type=?",
                          (f_d3, f_w30, sym, sdate, typ))
            n_d3 += f_d3
            n_w30 += f_w30
    picks.commit()
    picks.close()
    seq.close()
    print(f"✅ D3/W30+强度标记: 窗口{WIN}天 | 信号{len(rows)}条 | "
          f"D3{n_d3}/W30{n_w30} | 强度 强{n_str['strong']}/中{n_str['neutral']}/弱{n_str['weak']} | {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
