import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://www.eestiloto.ee/",
}

candidates = [
    "https://content-if.eestiloto.ee/et/results/?game=JOKKER",
    "https://content-if.eestiloto.ee/et/results/jokker",
    "https://content-if.eestiloto.ee/api/results?game=JOKKER",
    "https://content-if.eestiloto.ee/api/results/jokker",
    "https://content-if.eestiloto.ee/api/drawresults?game=JOKKER",
    "https://content-if.eestiloto.ee/api/draws?game=JOKKER",
    "https://content-if.eestiloto.ee/api/v1/results?game=JOKKER",
    "https://content-if.eestiloto.ee/et/api/results/?game=JOKKER",
    "https://content-if.eestiloto.ee/content/results?game=JOKKER",
    "https://content-if.eestiloto.ee/jokker/results.json",
    "https://www.eestiloto.ee/et/results/data?game=JOKKER",
    "https://www.eestiloto.ee/et/results/data/jokker",
    "https://www.eestiloto.ee/et/results/jokker/data.json",
    "https://www.eestiloto.ee/et/results/?game=JOKKER&format=json",
]

for url in candidates:
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        print('\nURL:', url)
        print('  status:', r.status_code)
        ctype = r.headers.get('Content-Type', '')
        print('  content-type:', ctype)
        text = r.text.strip()
        print('  len:', len(text))
        if len(text) > 0:
            print('  snippet:', text[:500].replace('\n',' '))
    except Exception as e:
        print('\nURL:', url)
        print('  error:', e)
