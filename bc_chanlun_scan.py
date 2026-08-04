#!/usr/bin/env python3
"""全市场缠论扫描: 最近7个交易日内出现 二买/三买 的股票
复用chanlun_api的笔/中枢算法, 检测:
  三买: 最近7日内结束的bottom笔, 低点>之前中枢上沿(突破后回踩不破)
  二买: 底背驰一买之后的回调bottom(不创新低), 在最近7日内结束
"""
import sqlite3
import sys

DB = "/home/ubuntu/Sequoia-X-a/data/sequoia_v2.db"
BATCH = 400

def merge_inclusion(k):
    merged = []
    for r in k:
        h, l = r[1], r[2]
        if not merged:
            merged.append([r[0], h, l])
            continue
        ph, pl = merged[-1][1], merged[-1][2]
        if (h >= ph and l <= pl) or (h <= ph and l >= pl):
            if len(merged) >= 2:
                dir_up = merged[-1][1] > merged[-2][1]
            else:
                dir_up = h >= ph
            if dir_up:
                merged[-1][1] = max(ph, h)
                merged[-1][2] = max(pl, l)
            else:
                merged[-1][1] = min(ph, h)
                merged[-1][2] = min(pl, l)
        else:
            merged.append([r[0], h, l])
    return merged

def chanlun_bis(qf_rows):
    """返回 (bi, zs_list): 笔序列[(idx,type,price)], 中枢[{bi_idx,lo,hi}]"""
    merged = merge_inclusion(qf_rows)
    fractals = []
    for i in range(1, len(merged) - 1):
        h0, l0 = merged[i-1][1], merged[i-1][2]
        h1, l1 = merged[i][1], merged[i][2]
        h2, l2 = merged[i+1][1], merged[i+1][2]
        if h1 > h0 and h1 > h2 and l1 > l0 and l1 > l2:
            fractals.append((i, 'top', h1))
        elif l1 < l0 and l1 < l2 and h1 < h0 and h1 < h2:
            fractals.append((i, 'bottom', l1))
    bi = []
    for f in fractals:
        if not bi:
            bi.append(f)
            continue
        if f[1] == bi[-1][1]:
            if (f[1] == 'top' and f[2] > bi[-1][2]) or (f[1] == 'bottom' and f[2] < bi[-1][2]):
                bi[-1] = f
        else:
            if f[0] - bi[-1][0] >= 4:
                bi.append(f)
            else:
                if (f[1] == 'top' and f[2] > bi[-1][2]) or (f[1] == 'bottom' and f[2] < bi[-1][2]):
                    bi[-1] = f
    zs_list = []
    for i in range(len(bi) - 2):
        a, b, c = bi[i], bi[i+1], bi[i+2]
        segs = []
        for x, y in [(a, b), (b, c)]:
            lo, hi = min(x[2], y[2]), max(x[2], y[2])
            segs.append((lo, hi))
        zs_hi = min(s[1] for s in segs)
        zs_lo = max(s[0] for s in segs)
        if zs_hi > zs_lo:
            zs_list.append({"bi_idx": i, "lo": zs_lo, "hi": zs_hi})
    return bi, zs_list, merged

def detect(sym, qf_rows):
    """返回该股最近7交易日内的 二买/三买 信号列表(每类最多1个)"""
    if len(qf_rows) < 120:
        return []
    bi, zs_list, merged = chanlun_bis(qf_rows)
    if len(bi) < 5:
        return []
    last7 = set(r[0] for r in qf_rows[-7:])
    res = []
    # 三买: 最后一个bottom笔, 低点>其前面最近中枢上沿(突破后回踩不破), 且该笔在最近7日
    last_bottom = None
    b_idx = -1
    for idx in range(len(bi) - 1, -1, -1):
        if bi[idx][1] == 'bottom':
            last_bottom = bi[idx]
            b_idx = idx
            break
    if last_bottom is not None and merged[last_bottom[0]][0] in last7:
        # 找该笔之前最近的中枢(中枢由bi_idx起的3笔构成, 需完全在该笔之前)
        zs_before = [z for z in zs_list if z["bi_idx"] + 2 < b_idx]
        if zs_before:
            zs = zs_before[-1]
            # 三买: 低点>中枢上沿 且 突破幅度不超过35%(刚突破回踩, 排除暴涨)
            if last_bottom[2] > zs["hi"] and last_bottom[2] < zs["hi"] * 1.35:
                return [("三买", merged[last_bottom[0]][0], round(last_bottom[2], 2),
                         round(zs["lo"], 2), round(zs["hi"], 2))]
    # 二买: 底背驰一买后的回调bottom(不创新低), 在最近7日内结束
    if len(bi) >= 5:
        def force(b1, b2):
            return abs(b2[2] / b1[2] - 1) * 100 if b1[2] else 0
        for j in range(len(bi) - 1, 2, -1):
            if bi[j][1] != 'bottom':
                continue
            d1 = force(bi[j-3], bi[j-2])
            d2 = force(bi[j-1], bi[j])
            if j >= 4 and bi[j-2][1] == 'top' and bi[j-1][1] == 'bottom' and d2 < d1:
                # bi[j] = 背驰底(一买), 其后回调底不创新低且在最近7日
                for k in range(j + 1, len(bi)):
                    if bi[k][1] == 'bottom' and bi[k][2] > bi[j][2] and merged[bi[k][0]][0] in last7:
                        return [("二买", merged[bi[k][0]][0], round(bi[k][2], 2),
                                 round(bi[j][2], 2), round(bi[j-1][2], 2))]
                break
    return res

def main():
    conn = sqlite3.connect(DB)
    syms = [r[0] for r in conn.execute(
        "SELECT DISTINCT symbol FROM stock_daily WHERE close_qfq>0 "
        "AND date>='2024-01-01' AND symbol NOT LIKE '%.SH' AND symbol NOT LIKE '%.BJ'").fetchall()]
    # 名称
    names = {}
    for r in conn.execute("SELECT symbol, name FROM stock_basics WHERE date=(SELECT MAX(date) FROM stock_basics)"):
        names[r[0]] = r[1]
    print(f"扫描 {len(syms)} 只...", flush=True)

    all_hits = []
    for batch_i in range(0, len(syms), BATCH):
        batch = syms[batch_i:batch_i + BATCH]
        ph = ",".join("?" * len(batch))
        rows = conn.execute(
            f"SELECT symbol, date, high, low, close, close_qfq FROM stock_daily "
            f"WHERE symbol IN ({ph}) AND close_qfq>0 ORDER BY symbol, date", batch).fetchall()
        # 按symbol分组
        per = {}
        for r in rows:
            per.setdefault(r[0], []).append(r)
        for sym in batch:
            data = per.get(sym, [])
            if len(data) < 120:
                continue
            qf_rows = []
            for r in data:
                ratio = r[5] / r[4] if r[4] else 1
                qf_rows.append([r[1], r[2] * ratio, r[3] * ratio, r[5]])
            hits = detect(sym, qf_rows)
            for h in hits:
                nm = names.get(sym, "?")
                # 排除ST和仙股(<2元)
                if 'ST' in nm.upper() or qf_rows[-1][3] < 2.0:
                    continue
                all_hits.append((sym, nm, h[0], h[1], h[2], h[3], h[4]))
        if (batch_i // BATCH) % 3 == 0:
            print(f"  批{batch_i//BATCH+1}: 累计{len(all_hits)}个信号", flush=True)

    conn.close()
    all_hits.sort(key=lambda x: (x[3], x[0]))
    print(f"\n===== 最近7个交易日 二买/三买 信号: {len(all_hits)}个 =====")
    for sym, name, typ, date, price, zlo, zhi in all_hits:
        print(f"  {sym} {name:8s} {typ} {date} @{price:.2f} (中枢 {zlo:.2f}~{zhi:.2f})")

if __name__ == "__main__":
    main()
