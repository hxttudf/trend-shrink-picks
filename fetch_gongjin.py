#!/usr/bin/env python3
"""Fetch 共进股份 data from East Money API"""
import urllib.request, json

# Financial data
print("=== 财务数据 ===")
url = 'https://datacenter.eastmoney.com/securities/api/data/v1/get?reportName=RPT_F10_FINANCE_MAINFINADATA&columns=ALL&filter=(SECUCODE=%22603118.SH%22)&pageNumber=1&pageSize=5&sortTypes=-1&sortColumns=REPORT_DATE'
d = json.loads(urllib.request.urlopen(url, timeout=15).read())
if d.get('code') == 0 and d.get('result') and d['result'].get('data'):
    for item in d['result']['data'][:5]:
        print(f"日期:{item.get('REPORT_DATE','')} 营收:{item.get('TOTALOPERATEREVE','')} 净利:{item.get('PARENTNETPROFIT','')} 扣非:{item.get('KCFJCXSYJLR','')} 毛利率:{item.get('XSMLL','')}% ROE:{item.get('ROEJQ','')}% 负债率:{item.get('ZCFZL','')}% 每股收益:{item.get('EPSJB','')}")
else:
    print(f'API返回: code={d.get("code")}, msg={d.get("message")}')

# Real-time indicators
print("\n=== 实时行情 ===")
url2 = 'https://push2.eastmoney.com/api/qt/stock/get?fltt=2&secid=1.603118&fields=f43,f44,f45,f46,f47,f48,f50,f51,f52,f57,f58,f84,f85,f116,f162,f167,f168,f170'
d2 = json.loads(urllib.request.urlopen(url2, timeout=10).read())
data = d2.get('data', {})
print(f'最新价:{data.get("f43")} 最高:{data.get("f44")} 最低:{data.get("f45")} 今开:{data.get("f46")}')
print(f'涨跌额:{data.get("f47")} 涨跌幅:{data.get("f170")}%')
print(f'成交额:{data.get("f48")} 成交量:{data.get("f50")} 换手率:{data.get("f51")}%')
print(f'总市值:{data.get("f84")} 流通市值:{data.get("f85")} PE(TTM):{data.get("f116")} PB:{data.get("f168")}')
print(f'总股本:{data.get("f162")} 流通股本:{data.get("f167")}')
