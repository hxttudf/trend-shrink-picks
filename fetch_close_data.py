#!/usr/bin/env python3
"""收盘数据采集 — raw socket 直连qt，输出JSON"""
import json, subprocess, re, socket, sys, time
from datetime import date

def qt_raw(code, retry=2):
    """raw socket 拉腾讯行情，带重试"""
    for attempt in range(retry):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(3)
            s.connect(('qt.gtimg.cn', 80))
            req = f'GET /q={code} HTTP/1.0\r\nHost: qt.gtimg.cn\r\nUser-Agent: curl/7.68\r\nConnection: close\r\n\r\n'
            s.send(req.encode())
            data = b''
            while True:
                d = s.recv(4096)
                if not d: break
                data += d
            s.close()
            body = data.split(b'\r\n\r\n', 1)[1]
            raw = body.decode('gbk', 'ignore')
            raw = raw.split('"')[1]
            f = raw.split('~')
            return f[3], f[32]
        except:
            if attempt < retry - 1:
                time.sleep(0.5)
            continue
    return 'N/A', 'N/A'

# 指数
idx_codes = {
    '上证指数': 'sh000001', '深证成指': 'sz399001',
    '创业板指': 'sz399006', '科创50': 'sh000688',
    '沪深300': 'sh000300'
}
idx_data = {}
for name, qc in idx_codes.items():
    p, c = qt_raw(qc)
    idx_data[name] = {'price': p, 'chg': c}

# 涨停新闻
news_titles = []
try:
    cmd = ['node', 'scripts/cli.mjs', 'call', 'financial_docs', 'get_financial_news',
           '{"query":"涨停复盘"}']
    out = subprocess.check_output(cmd, cwd='/home/ubuntu/.hermes/skills/wind-mcp-skill',
                                   timeout=20, stderr=subprocess.DEVNULL).decode()
    data = json.loads(out)
    for item in data.get('data', {}).get('items', [])[:8]:
        news_titles.append(item.get('title', ''))
except:
    pass

# 解析
all_t = ' '.join(news_titles)
zt, dt = '?', '?'
m = re.search(r'(\d+)只涨停', all_t)
if m: zt = m.group(1)
m = re.search(r'(\d+)家跌停', all_t)
if m: dt = m.group(1)
m = re.search(r'(\d+)只跌停', all_t)
if m: dt = m.group(1)

out_data = {
    'date': date.today().isoformat(),
    'indices': idx_data,
    'limit_up': zt, 'limit_down': dt,
    'news': news_titles[:6]
}
print(json.dumps(out_data, ensure_ascii=False))
