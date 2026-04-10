"""
Jokker results analyzer.

Loads scraped draw history from data/jokker_results.json,
performs statistical analysis, optionally uses OpenAI to generate insights,
and produces suggested 7-digit numbers at three confidence levels:
  - top5   (5 highest-probability suggestions)
  - top50  (50 suggestions)
  - top500 (500 suggestions)

The output is saved to data/suggestions.json.
"""

import json
import math
import os
import random
import re
import sys
from collections import Counter
from datetime import datetime, timezone

# OpenAI is optional; statistical analysis works without it.
try:
    from openai import OpenAI  # type: ignore
    _OPENAI_AVAILABLE = True
except ImportError:
    _OPENAI_AVAILABLE = False

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
RESULTS_FILE = os.path.join(DATA_DIR, "jokker_results.json")
OUTPUT_FILE = os.path.join(DATA_DIR, "suggestions.json")

DIGIT_POSITIONS = 7   # Jokker has 7 digits
DIGIT_RANGE = 10      # Each digit is 0-9


# ---------------------------------------------------------------------------
# Statistical helpers
# ---------------------------------------------------------------------------

def load_draws(path: str = RESULTS_FILE) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    draws = data.get("draws", [])
    # Keep only draws with valid 7-digit sequences
    valid = [d for d in draws if isinstance(d.get("digits"), list) and len(d["digits"]) == 7]
    print(f"Loaded {len(valid)} valid draws (out of {len(draws)} total)")
    return valid


def position_frequency(draws: list[dict]) -> list[Counter]:
    """
    Return a list of 7 Counters, one per digit position,
    counting how many times each digit (0-9) appeared.
    """
    counters: list[Counter] = [Counter() for _ in range(DIGIT_POSITIONS)]
    for draw in draws:
        for pos, digit in enumerate(draw["digits"]):
            counters[pos][digit] += 1
    return counters


def position_weights(counters: list[Counter], draws: list[dict]) -> list[list[float]]:
    """
    Convert per-position Counters to probability weight lists (index = digit value).
    Returns a 7×10 matrix of floats.
    """
    total = max(len(draws), 1)
    weights = []
    for counter in counters:
        row = []
        for digit in range(DIGIT_RANGE):
            row.append(counter.get(digit, 0) / total)
        weights.append(row)
    return weights


def overall_number_frequency(draws: list[dict]) -> Counter:
    """Count how many times each full 7-digit number appeared."""
    return Counter(d["number"] for d in draws)


def generate_weighted_number(weights: list[list[float]]) -> str:
    """Generate a single 7-digit number using per-position weighted sampling."""
    digits = []
    for pos_weights in weights:
        # Weighted choice over digits 0-9
        total = sum(pos_weights)
        r = random.random() * total
        cumulative = 0.0
        chosen = 0
        for digit, w in enumerate(pos_weights):
            cumulative += w
            if r <= cumulative:
                chosen = digit
                break
        digits.append(str(chosen))
    return "".join(digits)


def score_number(number: str, weights: list[list[float]]) -> float:
    """
    Score a candidate 7-digit number as the product of per-position probabilities.
    Higher = more likely based on historical frequencies.
    """
    score = 1.0
    for pos, ch in enumerate(number):
        digit = int(ch)
        score *= weights[pos][digit]
    return score


def generate_candidate_pool(
    weights: list[list[float]],
    num_freq: Counter,
    pool_size: int = 5000,
) -> list[tuple[str, float]]:
    """
    Generate a large pool of candidate numbers, score each one, and return
    the pool sorted by score descending.
    """
    seen: set[str] = set()
    candidates: list[tuple[str, float]] = []

    # Include historically drawn numbers with a bonus
    for number, count in num_freq.most_common(1000):
        if number not in seen:
            seen.add(number)
            base_score = score_number(number, weights)
            # Slight bonus for numbers drawn before (they are "real" draws)
            bonus = 1.0 + math.log1p(count) * 0.05
            candidates.append((number, base_score * bonus))

    # Fill the rest with weighted random samples
    attempts = 0
    max_attempts = pool_size * 20
    while len(candidates) < pool_size and attempts < max_attempts:
        attempts += 1
        num = generate_weighted_number(weights)
        if num not in seen:
            seen.add(num)
            candidates.append((num, score_number(num, weights)))

    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates


def build_suggestions(
    candidates: list[tuple[str, float]],
    counts: tuple[int, int, int] = (5, 50, 500),
) -> dict:
    """Slice the sorted candidate pool into the three suggestion tiers."""
    n5, n50, n500 = counts
    top500 = [c[0] for c in candidates[:n500]]
    top50 = top500[:n50]
    top5 = top50[:n5]
    return {"top5": top5, "top50": top50, "top500": top500}


# ---------------------------------------------------------------------------
# AI-powered analysis (optional, uses OpenAI)
# ---------------------------------------------------------------------------

def _build_ai_prompt(draws: list[dict], weights: list[list[float]]) -> str:
    recent = draws[:50]  # Last 50 draws for the prompt
    draw_lines = "\n".join(
        f"  {d['draw_date']}: {' '.join(str(x) for x in d['digits'])}"
        for d in recent
    )

    freq_lines = []
    for pos in range(DIGIT_POSITIONS):
        top3 = sorted(range(DIGIT_RANGE), key=lambda d, p=pos: weights[p][d], reverse=True)[:3]
        freq_lines.append(f"  Position {pos+1}: most frequent digits are {top3}")
    freq_summary = "\n".join(freq_lines)

    return f"""You are a lottery analysis assistant. Analyze the following Jokker lottery draw history.
Jokker is a 7-digit number game where each digit is 0-9.

Recent draws (date: d1 d2 d3 d4 d5 d6 d7):
{draw_lines}

Per-position frequency summary:
{freq_summary}

Based on this historical data, suggest exactly 5 highly plausible 7-digit Jokker numbers.
Each suggestion should be a 7-character string of digits (e.g. "6058108").
Return ONLY a JSON array of 5 strings, nothing else.
Example: ["1234567","9876543","0011223","5544332","8877665"]
"""


def generate_ai_suggestions(
    draws: list[dict],
    weights: list[list[float]],
    api_key: str,
) -> list[str]:
    """Use OpenAI to generate 5 top suggestions."""
    client = OpenAI(api_key=api_key)
    prompt = _build_ai_prompt(draws, weights)

    print("Requesting AI suggestions from OpenAI…")
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        max_tokens=256,
    )
    content = response.choices[0].message.content.strip()

    # Parse the JSON array
    match = re.search(r"\[.*?\]", content, re.DOTALL)
    if not match:
        raise ValueError(f"Unexpected AI response format: {content}")
    suggestions = json.loads(match.group())
    # Validate each suggestion
    valid = []
    for s in suggestions:
        s = str(s).strip()
        if len(s) == 7 and s.isdigit():
            valid.append(s)
    return valid[:5]


# ---------------------------------------------------------------------------
# Analysis summary helpers
# ---------------------------------------------------------------------------

def build_analysis_report(
    draws: list[dict],
    counters: list[Counter],
    weights: list[list[float]],
    num_freq: Counter,
) -> dict:
    """Build a human-readable analysis report dict."""
    per_position = {}
    for pos in range(DIGIT_POSITIONS):
        sorted_digits = sorted(range(DIGIT_RANGE), key=lambda d: counters[pos][d], reverse=True)
        per_position[f"position_{pos + 1}"] = {
            "most_common": sorted_digits[:3],
            "least_common": sorted_digits[-3:],
            "frequencies": {str(d): counters[pos].get(d, 0) for d in range(DIGIT_RANGE)},
        }

    top_numbers = num_freq.most_common(10)
    return {
        "total_draws_analyzed": len(draws),
        "date_range": {
            "earliest": draws[-1]["draw_date"] if draws else None,
            "latest": draws[0]["draw_date"] if draws else None,
        },
        "per_position_analysis": per_position,
        "most_drawn_numbers": [{"number": n, "count": c} for n, c in top_numbers],
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main() -> None:
    draws = load_draws()
    if not draws:
        print("ERROR: No draws available for analysis. Run scraper first.", file=sys.stderr)
        sys.exit(1)

    # Statistical analysis
    counters = position_frequency(draws)
    weights = position_weights(counters, draws)
    num_freq = overall_number_frequency(draws)

    # Generate candidate pool (purely statistical)
    print("Generating candidate pool…")
    candidates = generate_candidate_pool(weights, num_freq, pool_size=5000)

    suggestions = build_suggestions(candidates)
    analysis = build_analysis_report(draws, counters, weights, num_freq)

    # Optionally replace top5 with AI suggestions
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if api_key and _OPENAI_AVAILABLE:
        try:
            ai_top5 = generate_ai_suggestions(draws, weights, api_key)
            if ai_top5:
                print(f"AI suggestions: {ai_top5}")
                # Merge: put AI suggestions first, fill rest from statistical pool
                existing_top5 = [s for s in suggestions["top5"] if s not in ai_top5]
                suggestions["top5"] = (ai_top5 + existing_top5)[:5]
                analysis["ai_top5_used"] = True
        except Exception as exc:  # pylint: disable=broad-except
            print(f"AI suggestion failed (falling back to statistical): {exc}", file=sys.stderr)
            analysis["ai_top5_used"] = False
            analysis["ai_error"] = str(exc)
    else:
        analysis["ai_top5_used"] = False
        if not api_key:
            print("No OPENAI_API_KEY set – using statistical suggestions only.")

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "game": "Jokker",
        "source": "https://www.eestiloto.ee/et/results/?game=JOKKER",
        "suggestions": suggestions,
        "analysis": analysis,
    }

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as fh:
        json.dump(output, fh, indent=2, ensure_ascii=False)
    print(f"Saved suggestions to {OUTPUT_FILE}")
    print(f"  top5:   {suggestions['top5']}")
    print(f"  top50:  {len(suggestions['top50'])} numbers")
    print(f"  top500: {len(suggestions['top500'])} numbers")


if __name__ == "__main__":
    main()
