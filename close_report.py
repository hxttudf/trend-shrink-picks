#!/usr/bin/env python3
"""尾盘复盘报告 — no_agent模式，自动采集+格式化输出"""
import json, subprocess, re, socket, time, sys
from datetime import date

# ── 数据采集 ──
def qt_raw(code, retry=2):
    for attempt in range(retry):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(3)
            s.connect(('qt.gtimg.cn', 80))
            s.send(f'GET /q={code} HTTP/1.0\r\nHost: qt.gtimg.cn\r\nUser-Agent: curl/7.68\r\nConnection: close\r\n\r\n'.encode())
            data = b''
            while True:
                d = s.recv(4096)
                if not d: break
                data += d
            s.close()
            body = data.split(b'\r\n\r\n', 1)[1]
            raw = body.decode('gbk', 'ignore').split('"')[1]
            f = raw.split('~')
            return f[3], f[32]
        except:
            if attempt < retry - 1: time.sleep(0.5)
    return 'N/A', 'N/A'

# 指数
idx = {
    '上证指数': 'sh000001', '深证成指': 'sz399001',
    '创业板指': 'sz399006', '科创50': 'sh000688',
    '沪深300': 'sh000300'
}
idata = {}
for name, qc in idx.items():
    p, c = qt_raw(qc)
    idata[name] = (p, c)

# 新闻 & 涨停数
news_titles = []
try:
    cmd = ['node', 'scripts/cli.mjs', 'call', 'financial_docs', 'get_financial_news',
           '{"query":"涨停复盘"}']
    out = subprocess.check_output(cmd, cwd='/home/ubuntu/.hermes/skills/wind-mcp-skill',
                                   timeout=20, stderr=subprocess.DEVNULL).decode()
    for item in json.loads(out).get('data', {}).get('items', [])[:8]:
        news_titles.append(item.get('title', ''))
except:
    pass

all_t = ' '.join(news_titles)
zt = re.search(r'(\d+)只涨停', all_t)
zt = zt.group(1) if zt else '?'
dt = re.search(r'(\d+)家跌停', all_t)
dt = dt.group(1) if dt else (re.search(r'(\d+)只跌停', all_t).group(1) if re.search(r'(\d+)只跌停', all_t) else '?')

# ── 输出报告 ──
sh = idata['上证指数']
sz = idata['深证成指']
cy = idata['创业板指']
kc = idata['科创50']
hs = idata['沪深300']

print(f'''【1.今日市场全景】
上证 {sh[0]} {sh[1]} | 深证 {sz[0]} {sz[1]}
创业板 {cy[0]} {cy[1]} | 科创50 {kc[0]} {kc[1]}
沪深300 {hs[0]} {hs[1]} | 涨停{zt}家 跌停{dt}家
（两市整体表现解读）

【2.主线与轮动结构】
（今日最强方向及扩散，冲高回落方向，主线和轮动区分）

【3.核心个股反馈】
（龙头/中军/高位股反馈，连板晋级/炸板，市场强度判断）

【4.情绪与资金结构】
（情绪阶段：加强/分歧/修复/退潮，资金偏好：趋势容量/连板接力/低位试错）

【5.今日最重要的边际变化】
（与昨日比最关键的变量）

【6.明日重点观察】
（具体变量）

【7.复盘结论】
''')

# Kuma心跳
subprocess.run(['bash', '/home/ubuntu/.hermes/scripts/kuma_ping.sh', '尾盘复盘', 'done'],
               capture_output=True, timeout=10)
