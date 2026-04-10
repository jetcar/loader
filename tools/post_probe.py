import re
from pathlib import Path
import requests

page = Path(__file__).resolve().parent / 'page.html'
html = page.read_text(encoding='utf-8')
# extract csrfToken input value
m = re.search(r'name="csrfToken" value="([^"]+)"', html)
csrf = m.group(1) if m else ''
print('csrfToken:', csrf)

HEADERS = {
    'User-Agent': 'Mozilla/5.0',
    'Referer': 'https://www.eestiloto.ee/et/results/?game=JOKKER',
}

base = 'https://www.eestiloto.ee'
endpoints = [
    '/app/getDrawsByIds',
    '/app/getDrawResults',
    '/app/getDraws',
    '/app/getDrawResultsByGame',
    '/app/getDrawResultsByIds',
    '/app/getDrawsByGame',
    '/app/getDrawResultsByFilter',
    '/app/getResults',
    '/app/draws',
    '/app/results',
]

payload = {
    'gameTypes': 'JOKKER',
    'dateFrom': '',
    'dateTo': '',
    'drawLabelFrom': '',
    'drawLabelTo': '',
    'pageIndex': 1,
    'orderBy': 'drawDate_desc',
    'sortLabelNumeric': True,
    'csrfToken': csrf,
}

for ep in endpoints:
    url = base + ep
    try:
        print('\nPOST', url)
        r = requests.post(url, data=payload, headers=HEADERS, timeout=20)
        print(' status', r.status_code, 'ctype', r.headers.get('Content-Type',''))
        txt = r.text
        snippet = txt[:1000]
        print(' len', len(txt))
        if r.headers.get('Content-Type','').startswith('application/json'):
            print(' json keys:', r.json().keys())
        else:
            print(' snippet:', snippet.replace('\n',' '))
    except Exception as e:
        print(' error', e)
