# Jokker Lottery Analyzer

Automated tool that scrapes **Jokker** lottery results from
[eestiloto.ee](https://www.eestiloto.ee/et/results/?game=JOKKER),
analyzes historical draw data using statistics (and optionally OpenAI),
and publishes suggested numbers to a GitHub Release that a Windows app can
download automatically.

## Overview

**Jokker** is a daily 7-digit number game (each digit 0–9) run by Eesti Loto.

This project:
1. **Scrapes** recent draw results from eestiloto.ee (`scraper/scraper.py`)
2. **Analyzes** the data and generates three tiers of suggestions (`analyzer/analyzer.py`):
   - `top5` – 5 highest-confidence 7-digit numbers
   - `top50` – 50 suggested numbers
   - `top500` – 500 suggested numbers
3. **Publishes** the results as a GitHub Release (`data/suggestions.json`) which
   the Windows app downloads automatically.

## How It Works

```
┌─────────────────────────┐      ┌──────────────────────┐
│  GitHub Actions workflow │      │  eestiloto.ee/results │
│  (daily at 21:00 UTC)   │─────▶│  Jokker draw history  │
└────────────┬────────────┘      └──────────────────────┘
             │ scraper.py
             ▼
      data/jokker_results.json
             │ analyzer.py
             ▼
      data/suggestions.json
             │ gh release create
             ▼
   GitHub Release (tag: results-YYYY-MM-DD)
             │
             ▼
   Windows App downloads suggestions.json
```

## GitHub Actions Workflow

The workflow (`.github/workflows/jokker-analyzer.yml`) runs:
- **Daily at 21:00 UTC** (after the daily Jokker draw)
- **Manually** via `workflow_dispatch`

Each run:
1. Installs Python dependencies
2. Runs `scraper/scraper.py` to fetch the latest results
3. Runs `analyzer/analyzer.py` to generate suggestions
4. Creates (or replaces) a GitHub Release tagged `results-YYYY-MM-DD`
   with `suggestions.json` and `jokker_results.json` as release assets

## Secrets

| Secret | Required | Description |
|--------|----------|-------------|
| `OPENAI_API_KEY` | Optional | If set, the top-5 suggestions are enhanced using OpenAI GPT-4o-mini. Falls back to pure statistical analysis if absent. |

`GITHUB_TOKEN` is provided automatically by GitHub Actions.

## Output Format

`data/suggestions.json`:

```json
{
  "generated_at": "2026-04-09T21:00:00Z",
  "game": "Jokker",
  "source": "https://www.eestiloto.ee/et/results/?game=JOKKER",
  "suggestions": {
    "top5":   ["6058108", "1234567", "9876543", "0011223", "5544332"],
    "top50":  ["6058108", "...", "(50 numbers total)"],
    "top500": ["6058108", "...", "(500 numbers total)"]
  },
  "analysis": {
    "total_draws_analyzed": 120,
    "date_range": { "earliest": "2025-01-01", "latest": "2026-04-09" },
    "per_position_analysis": { ... },
    "most_drawn_numbers": [ ... ],
    "ai_top5_used": false
  }
}
```

## Windows App Integration

The Windows app should:
1. Call the GitHub Releases API to get the latest release for this repository:
   `GET https://api.github.com/repos/{owner}/{repo}/releases/latest`
2. Find the asset named `suggestions.json` in the release assets list
3. Download the asset and parse the `suggestions` field

The release tag format is always `results-YYYY-MM-DD` so the app can also
fetch a specific date's suggestions.

## Running Locally

```bash
pip install -r requirements.txt

# Scrape results (saved to data/jokker_results.json)
python scraper/scraper.py

# Analyze and generate suggestions (saved to data/suggestions.json)
python analyzer/analyzer.py

# Optionally enable AI-enhanced top-5
OPENAI_API_KEY=sk-... python analyzer/analyzer.py
```
