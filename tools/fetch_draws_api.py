import re
import time
from pathlib import Path
import requests
import json

PAGE_URL = "https://www.eestiloto.ee/et/results/?game=JOKKER"
API_PATH = "/app/getDrawsByIds"

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0",
    "Referer": PAGE_URL,
    "X-Requested-With": "XMLHttpRequest",
})

print('GET', PAGE_URL)
resp = session.get(PAGE_URL, timeout=30)
print(' status', resp.status_code)
html = resp.text
m = re.search(r'name="csrfToken" value="([^"]+)"', html)
csrf = m.group(1) if m else ''
print('csrfToken:', csrf)

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

url = 'https://www.eestiloto.ee' + API_PATH
print('\nPOST', url)
try:
    r = session.post(url, data=payload, timeout=30)
    print(' status', r.status_code)
    ctype = r.headers.get('Content-Type','')
    print(' content-type', ctype)
    txt = r.text
    print(' len', len(txt))
    # Try parse JSON
    data = None
    try:
        data = r.json()
        print('json keys:', list(data.keys())[:20])
    except Exception as e:
        print('json parse failed', e)
        print('snippet:', txt[:1000])

    # Attempt to find draws list in the response
    draws = None
    if isinstance(data, dict):
        # Common keys: draws, results, drawResults, drawList
        for k in ('draws','results','drawResults','drawList','drawsList'):
            if k in data:
                draws = data[k]
                print('found draws key:', k, 'len', len(draws) if draws else 0)
                break
        if draws is None:
            # search for any list of objects containing winningNumber
            for v in data.values():
                if isinstance(v, list) and v and isinstance(v[0], dict) and ('winningNumber' in v[0] or 'drawDate' in v[0]):
                    draws = v
                    print('found candidate list at top-level value')
                    break
    if draws is None:
        print('No draws found in API response')
    else:
        out_draws = []
        for d in draws:
            # try to extract winningNumber and drawDate
            winning = None
            if 'winningNumber' in d:
                winning = d['winningNumber']
            elif 'winningNumbers' in d:
                winning = d['winningNumbers']
            elif 'number' in d:
                winning = d['number']
            # normalize to list of ints
            digits = None
            if isinstance(winning, str):
                parts = re.findall(r"\d", winning)
                if len(parts) == 7:
                    digits = [int(p) for p in parts]
                else:
                    parts2 = [p for p in re.split(r'[^0-9]', winning) if p]
                    if parts2 and all(len(p)==1 for p in parts2) and len(parts2)==7:
                        digits = [int(p) for p in parts2]
                    elif parts2 and len(''.join(parts2))==7:
                        digits = [int(c) for c in ''.join(parts2)]
            # draw date
            draw_date = ''
            if 'drawDate' in d:
                # might be epoch ms
                try:
                    dd = int(d['drawDate'])
                    if dd > 1e12:  # micro? unlikely
                        dd = dd/1000
                    draw_date = time.strftime('%Y-%m-%d', time.gmtime(dd/1000 if dd>1e9 else dd))
                except Exception:
                    draw_date = str(d.get('drawDate',''))
            elif 'date' in d:
                draw_date = d['date']
            elif 'drawLabel' in d:
                draw_date = d['drawLabel']

            if digits:
                out = {
                    'draw_date': draw_date,
                    'digits': digits,
                    'number': ''.join(str(x) for x in digits),
                }
                out_draws.append(out)
        print('mapped', len(out_draws), 'draws')
        # Save to data/jokker_results.json in expected format
        data_dir = Path(__file__).resolve().parent.parent / 'data'
        data_dir.mkdir(exist_ok=True)
        out = {
            'fetched_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'total_draws': len(out_draws),
            'draws': out_draws,
        }
        out_path = data_dir / 'jokker_results.json'
        out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding='utf-8')
        print('Saved', out_path)

except Exception as e:
    print('POST error', e)
