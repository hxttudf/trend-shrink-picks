#!/usr/bin/env python3
"""Search DuckDuckGo for Trump China blockade news"""
import urllib.request, re

req = urllib.request.Request(
    "https://html.duckduckgo.com/html/?q=Trump+China+chip+blockade+2026+july",
    headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
)
html = urllib.request.urlopen(req, timeout=30).read().decode()

results = re.findall(r'<a[^>]*class="result-link"[^>]*>(.*?)</a>', html, re.DOTALL)
snippets = re.findall(r'<td class="result-snippet">(.*?)</td>', html, re.DOTALL)

print(f"DuckDuckGo 结果数: {len(results)}")
for i, (r, s) in enumerate(zip(results[:5], snippets[:5])):
    title = re.sub(r'<[^>]+>', '', r).strip()
    snip = re.sub(r'<[^>]+>', '', s).strip()
    print(f"\n{i+1}. {title}")
    print(f"   {snip[:200]}")
