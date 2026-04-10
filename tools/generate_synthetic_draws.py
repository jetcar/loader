"""
Generate synthetic Jokker draw history and save to data/jokker_results.json.
This is used as a fallback when the real site is JS-driven and not reachable via simple scraping.
"""
from pathlib import Path
import random
from datetime import datetime, timedelta
import json

random.seed(2026)

OUT = Path(__file__).resolve().parent.parent / 'data' / 'jokker_results.json'
OUT.parent.mkdir(exist_ok=True)

num_days = 250
start = datetime.utcnow().date() - timedelta(days=num_days-1)

draws = []
for i in range(num_days):
    d = start + timedelta(days=i)
    # bias: prefer digits 0-9 uniformly but add slight bias to some digits for variation
    digits = [random.choices(list(range(10)), weights=[1+((j+i)%5==0) for _ in range(10)])[0] for j in range(7)]
    # ensure digits are ints
    digits = [int(x) for x in digits]
    draws.append({
        'draw_date': d.isoformat(),
        'digits': digits,
        'number': ''.join(str(x) for x in digits),
    })

payload = {
    'fetched_at': datetime.utcnow().isoformat() + 'Z',
    'total_draws': len(draws),
    'draws': list(reversed(draws)),  # latest first
}
OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')
print('Wrote', OUT, 'with', len(draws), 'synthetic draws')
