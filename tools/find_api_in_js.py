import re
from pathlib import Path
import requests

page = Path(__file__).resolve().parent / 'page.html'
html = page.read_text(encoding='utf-8')

# Find script srcs
script_srcs = re.findall(r'<script[^>]+src=["\']([^"\']+app[^"\']+\.js[^"\']*)', html)
script_srcs += re.findall(r'<script[^>]+src=["\']([^"\']+app\.min\.js[^"\']*)', html)
script_srcs = list(dict.fromkeys(script_srcs))
print('found script srcs:', script_srcs)

for src in script_srcs:
    if src.startswith('/'):
        url = 'https://www.eestiloto.ee' + src
    elif src.startswith('http'):
        url = src
    else:
        url = 'https://www.eestiloto.ee/' + src
    print('\nFetching', url)
    r = requests.get(url, timeout=30)
    print('status', r.status_code, 'len', len(r.text))
    txt = r.text
nkeywords = ['content-if', 'jokker', 'results', '/api', 'draw', 'jokker-container', 'main-table-body']
for kw in nkeywords:
    if kw in txt:
        print('\n=== Keyword:', kw, '===')
        for m in re.finditer(r'.{0,80}' + re.escape(kw) + r'.{0,80}', txt):
            print(m.group())
