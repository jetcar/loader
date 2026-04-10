import requests
from pathlib import Path

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
URL = "https://www.eestiloto.ee/et/results/?game=JOKKER"

p = Path(__file__).resolve().parent
out = p / "page.html"

print('Fetching', URL)
resp = requests.get(URL, headers=HEADERS, timeout=30)
print('status', resp.status_code)
html = resp.text
print('len', len(html))
out.write_text(html, encoding='utf-8')
print('Saved to', out)
print('\n--- snippet ---\n')
print(html[:1000])
