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
from pathlib import Path

import requests

# Load .env file if present (created by tools/github_auth.py or manually)
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env")
except ImportError:
    pass  # python-dotenv not installed; rely on environment variables only

# OpenAI is optional; statistical analysis works without it.
try:
    from openai import OpenAI  # type: ignore
    _OPENAI_AVAILABLE = True
except ImportError:
    _OPENAI_AVAILABLE = False

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
RESULTS_FILE = os.path.join(DATA_DIR, "jokker_results.json")
SUGGESTIONS_PREFIX = "suggestions"

DIGIT_POSITIONS = 7   # Jokker has 7 digits
DIGIT_RANGE = 10      # Each digit is 0-9
DEFAULT_OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
DEFAULT_GITHUB_MODEL = os.environ.get("GITHUB_MODELS_MODEL", "openai/gpt-4.1-mini")
DEFAULT_LLM_CANDIDATE_COUNT = 120
GITHUB_MODELS_API_URL = "https://models.github.ai/inference/chat/completions"
GITHUB_API_VERSION = "2026-03-10"

# Prize table: N consecutive matching digits from the right → prize in euros
PRIZE_TABLE: dict[int, float] = {
    7: 1_000_000.00,
    6: 30_000.00,
    5: 1_000.00,
    4: 50.00,
    3: 6.00,
    2: 2.00,
    1: 0.00,
    0: 0.00,
}
COST_PER_LINE: float = 2.00


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


def _stamp(numbers: list[str], target_draw_label: str | None = None) -> list[dict]:
    """Wrap each number with its own generated_at timestamp and target draw label."""
    ts = datetime.now(timezone.utc).isoformat()
    entry = {"number": "#", "generated_at": ts}
    if target_draw_label is not None:
        entry["target_draw_label"] = target_draw_label
    return [{**entry, "number": n} for n in numbers]


def build_suggestions(
    candidates: list[tuple[str, float]],
    counts: tuple[int, int, int] = (5, 50, 500),
    target_draw_label: str | None = None,
) -> dict:
    """Slice the sorted candidate pool into the three suggestion tiers."""
    n5, n50, n500 = counts
    top500 = [c[0] for c in candidates[:n500]]
    top50 = top500[:n50]
    top5 = top50[:n5]
    return {
        "top5": _stamp(top5, target_draw_label),
        "top50": _stamp(top50, target_draw_label),
        "top500": _stamp(top500, target_draw_label),
    }


def merge_ranked_suggestions(
    ranked_numbers: list[str],
    candidates: list[tuple[str, float]],
    counts: tuple[int, int, int] = (5, 50, 500),
    target_draw_label: str | None = None,
) -> dict:
    """Merge LLM-ranked numbers with the statistical pool without duplicates."""
    n5, n50, n500 = counts
    ordered: list[str] = []
    seen: set[str] = set()

    for number in ranked_numbers:
        if len(number) == 7 and number.isdigit() and number not in seen:
            ordered.append(number)
            seen.add(number)

    for number, _score in candidates:
        if number not in seen:
            ordered.append(number)
            seen.add(number)
        if len(ordered) >= n500:
            break

    top500 = ordered[:n500]
    top50 = top500[:n50]
    top5 = top50[:n5]
    return {
        "top5": _stamp(top5, target_draw_label),
        "top50": _stamp(top50, target_draw_label),
        "top500": _stamp(top500, target_draw_label),
    }


def load_previous_suggestions() -> dict | None:
    """
    Load the most recently generated suggestions file from DATA_DIR.
    Returns None if no previous file exists.
    """
    import glob
    pattern = os.path.join(DATA_DIR, f"{SUGGESTIONS_PREFIX}_*.json")
    files = sorted(glob.glob(pattern))
    if not files:
        return None
    with open(files[-1], encoding="utf-8") as fh:
        return json.load(fh)


def evaluate_previous_suggestions(
    prev: dict,
    draws: list[dict],
) -> dict:
    """
    Score previous suggestions against draws that occurred after they were generated.

    Returns a summary dict with hit counts across top5/top50/top500.
    """
    generated_at = prev.get("generated_at", "")
    generated_date = generated_at[:10] if generated_at else ""

    # Only draws after the suggestions were generated count as "new"
    new_draws = [d for d in draws if d["draw_date"] > generated_date]
    if not new_draws:
        return {"draws_since": 0, "note": "No draws occurred after suggestions were generated."}

    actual_numbers = {d["number"] for d in new_draws}

    def hit_count(tier: list) -> int:
        return sum(1 for s in tier if (s["number"] if isinstance(s, dict) else s) in actual_numbers)

    suggestions = prev.get("suggestions", {})
    top5 = suggestions.get("top5", [])
    top50 = suggestions.get("top50", [])
    top500 = suggestions.get("top500", [])

    hits_top5 = hit_count(top5)
    hits_top50 = hit_count(top50)
    hits_top500 = hit_count(top500)

    result = {
        "generated_at": generated_at,
        "draws_since": len(new_draws),
        "hits_top5": hits_top5,
        "hits_top50": hits_top50,
        "hits_top500": hits_top500,
        "top5_numbers": [s["number"] if isinstance(s, dict) else s for s in top5],
        "hit_numbers": sorted(
            actual_numbers & {s["number"] if isinstance(s, dict) else s for s in top50}
        ),
    }
    return result


def get_llm_config() -> dict | None:
    """Resolve which hosted LLM provider to use based on available credentials."""
    provider = os.environ.get("LLM_PROVIDER", "auto").strip().lower()
    github_token = (
        os.environ.get("GH_MODELS_TOKEN", "").strip()
        or os.environ.get("GITHUB_MODELS_TOKEN", "").strip()
        or os.environ.get("GITHUB_TOKEN", "").strip()
        or os.environ.get("GH_TOKEN", "").strip()
    )
    openai_token = os.environ.get("OPENAI_API_KEY", "").strip()

    if provider in {"auto", "github", "github-models"} and github_token:
        return {
            "provider": "github-models",
            "token": github_token,
            "model": os.environ.get("GITHUB_MODELS_MODEL", DEFAULT_GITHUB_MODEL),
        }

    if provider in {"auto", "openai"} and openai_token and _OPENAI_AVAILABLE:
        return {
            "provider": "openai",
            "token": openai_token,
            "model": os.environ.get("OPENAI_MODEL", DEFAULT_OPENAI_MODEL),
        }

    return None


# ---------------------------------------------------------------------------
# AI-powered analysis (optional, uses OpenAI)
# ---------------------------------------------------------------------------

def _format_candidate_lines(candidates: list[tuple[str, float]]) -> str:
    """Render candidate numbers with compact scores for the LLM prompt."""
    return "\n".join(
        f"  {index + 1}. {number} (score={score:.12f})"
        for index, (number, score) in enumerate(candidates)
    )


def _build_llm_prompt(
    draws: list[dict],
    weights: list[list[float]],
    num_freq: Counter,
    candidates: list[tuple[str, float]],
    prev_performance: dict | None = None,
) -> str:
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

    repeated_lines = "\n".join(
        f"  {number}: seen {count} times"
        for number, count in num_freq.most_common(15)
    )

    candidate_lines = _format_candidate_lines(candidates)

    prev_section = ""
    if prev_performance and prev_performance.get("draws_since", 0) > 0:
        hits = prev_performance.get("hit_numbers", [])
        hit_str = ", ".join(hits) if hits else "none"
        prev_section = f"""
Previous suggestions performance (generated {prev_performance['generated_at'][:10]}):
  Draws since then: {prev_performance['draws_since']}
  Previous top5: {prev_performance.get('top5_numbers', [])}
  Hits in top50 vs actual draws: {prev_performance['hits_top50']} ({hit_str})
  NOTE: Numbers that matched actual draws are listed above. Use this to refine your digit pattern intuition.
"""

    return f"""You are a lottery analysis assistant.
Analyze Jokker historical results and choose suggested values from a precomputed candidate shortlist.
Jokker is a 7-digit number game where each digit is 0-9.

Recent draws (date: d1 d2 d3 d4 d5 d6 d7):
{draw_lines}

Per-position frequency summary:
{freq_summary}

Most repeated historical numbers:
{repeated_lines}
{prev_section}
Candidate shortlist:
{candidate_lines}

Rules:
1. Pick numbers only from the candidate shortlist.
2. Avoid duplicates.
3. Return exactly 5 numbers in top5 and exactly 50 numbers in top50.
4. Keep top5 as the strongest subset of top50, in order.
5. Provide a short reasoning summary grounded in the provided data only.

Return ONLY JSON in this shape:
{{
  "top5": ["1234567", "2345678", "3456789", "4567890", "5678901"],
  "top50": ["... exactly 50 candidate numbers ..."],
  "summary": "short explanation"
}}
"""


def _parse_llm_payload(content: str, candidates: list[tuple[str, float]]) -> dict:
    """Parse and normalize JSON returned by an LLM ranking response."""
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not match:
        raise ValueError(f"Unexpected AI response format: {content}")
    payload = json.loads(match.group())

    allowed_numbers = {number for number, _score in candidates}

    def clean_numbers(values: list) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for value in values:
            number = str(value).strip()
            if number in allowed_numbers and number not in seen:
                cleaned.append(number)
                seen.add(number)
        return cleaned

    top50 = clean_numbers(payload.get("top50", []))
    top5 = clean_numbers(payload.get("top5", []))

    if len(top50) < 50:
        for number, _score in candidates:
            if number not in top50:
                top50.append(number)
            if len(top50) >= 50:
                break

    top50 = top50[:50]

    if len(top5) < 5:
        for number in top50:
            if number not in top5:
                top5.append(number)
            if len(top5) >= 5:
                break

    return {
        "top5": top5[:5],
        "top50": top50,
        "summary": str(payload.get("summary", "")).strip(),
    }


def generate_github_models_suggestions(
    prompt: str,
    candidates: list[tuple[str, float]],
    token: str,
    model: str,
) -> dict:
    """Use GitHub Models REST inference to rank the statistical shortlist."""
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
    }
    body = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You are a careful ranking assistant that returns valid JSON only.",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.4,
        "max_tokens": 1200,
        "stream": False,
    }
    response = requests.post(GITHUB_MODELS_API_URL, headers=headers, json=body, timeout=60)
    response.raise_for_status()
    payload = response.json()
    content = payload["choices"][0]["message"]["content"].strip()
    result = _parse_llm_payload(content, candidates)
    result["model"] = model
    return result


def generate_llm_suggestions(
    draws: list[dict],
    weights: list[list[float]],
    num_freq: Counter,
    candidates: list[tuple[str, float]],
    llm_config: dict,
    prev_performance: dict | None = None,
) -> dict:
    """Use OpenAI to rank candidate suggestions and provide a short analysis summary."""
    prompt = _build_llm_prompt(draws, weights, num_freq, candidates, prev_performance)

    if llm_config["provider"] == "github-models":
        print("Requesting AI suggestions from GitHub Models…")
        return generate_github_models_suggestions(
            prompt=prompt,
            candidates=candidates,
            token=llm_config["token"],
            model=llm_config["model"],
        )

    if llm_config["provider"] == "openai":
        client = OpenAI(api_key=llm_config["token"])
        print("Requesting AI suggestions from OpenAI…")
        response = client.chat.completions.create(
            model=llm_config["model"],
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
            max_tokens=1200,
        )
        content = response.choices[0].message.content.strip()
        result = _parse_llm_payload(content, candidates)
        result["model"] = llm_config["model"]
        return result

    raise ValueError(f"Unsupported LLM provider: {llm_config['provider']}")


# ---------------------------------------------------------------------------
# Analysis summary helpers
# ---------------------------------------------------------------------------

def count_jokker_matches(suggestion: str, draw_number: str) -> int:
    """
    Count how many consecutive digits match from the right.

    Jokker prizes are awarded for matching the last N digits of the draw number
    in exact positions from right to left.
    """
    matches = 0
    for s, d in zip(reversed(suggestion), reversed(draw_number)):
        if s == d:
            matches += 1
        else:
            break
    return matches


def calculate_roi(suggestions: dict, draws: list[dict]) -> dict:
    """
    Backtest suggestion tiers against all historical draws.

    For each draw, checks every suggestion in top5/top50/top500 for consecutive
    right-digit matches and sums the resulting prizes.

    Returns a cost_analysis dict with total cost, winnings, and net per tier.
    """
    draw_numbers = [d["number"] for d in draws if len(d.get("number", "")) == 7]
    num_draws = len(draw_numbers)

    def _tier_stats(tier: list) -> dict:
        numbers = [s["number"] if isinstance(s, dict) else s for s in tier]
        lines = len(numbers)
        total_cost = round(lines * COST_PER_LINE * num_draws, 2)
        total_winnings = 0.0
        breakdown: dict[str, int] = {str(k): 0 for k in range(8)}

        for draw_num in draw_numbers:
            for number in numbers:
                m = count_jokker_matches(number, draw_num)
                breakdown[str(m)] += 1
                total_winnings += PRIZE_TABLE.get(m, 0.0)

        total_winnings = round(total_winnings, 2)
        net = round(total_winnings - total_cost, 2)
        roi_pct = round((total_winnings / total_cost * 100) if total_cost > 0 else 0.0, 2)

        return {
            "lines": lines,
            "draws_backtested": num_draws,
            "cost_per_draw": round(lines * COST_PER_LINE, 2),
            "total_cost": total_cost,
            "total_winnings": total_winnings,
            "net": net,
            "roi_pct": roi_pct,
            "win_breakdown": breakdown,
        }

    return {
        "cost_per_line": COST_PER_LINE,
        "prize_table": {str(k): v for k, v in PRIZE_TABLE.items() if v > 0},
        "note": "Backtest plays each suggestion against every historical draw.",
        "top5": _tier_stats(suggestions.get("top5", [])),
        "top50": _tier_stats(suggestions.get("top50", [])),
        "top500": _tier_stats(suggestions.get("top500", [])),
    }


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

    # Load and evaluate previous suggestions against draws that came in since
    prev_suggestions = load_previous_suggestions()
    prev_performance = evaluate_previous_suggestions(prev_suggestions, draws) if prev_suggestions else None
    if prev_performance:
        if prev_performance.get("draws_since", 0) > 0:
            print(
                f"Previous suggestions: {prev_performance['hits_top50']} hit(s) in top50 "
                f"across {prev_performance['draws_since']} new draw(s) since {prev_performance['generated_at'][:10]}"
            )
        else:
            print("Previous suggestions: no new draws since last run.")

    # Determine the next draw label (sequential integer after the latest known draw)
    latest_label = draws[0].get("draw_label", "") if draws else ""
    try:
        target_draw_label = str(int(latest_label) + 1)
    except (ValueError, TypeError):
        target_draw_label = None
    if target_draw_label:
        print(f"Target draw label: {target_draw_label}")

    # Generate candidate pool (purely statistical)
    print("Generating candidate pool…")
    candidates = generate_candidate_pool(weights, num_freq, pool_size=5000)

    suggestions = build_suggestions(candidates, target_draw_label=target_draw_label)
    analysis = build_analysis_report(draws, counters, weights, num_freq)
    if prev_performance:
        analysis["prev_suggestions_performance"] = prev_performance

    # Optionally let the LLM rank the best statistical candidates.
    llm_config = get_llm_config()
    if llm_config:
        try:
            llm_candidates = candidates[:DEFAULT_LLM_CANDIDATE_COUNT]
            llm_result = generate_llm_suggestions(
                draws, weights, num_freq, llm_candidates, llm_config, prev_performance
            )
            ranked_numbers = llm_result["top50"]
            suggestions = merge_ranked_suggestions(
                ranked_numbers, candidates, target_draw_label=target_draw_label
            )
            suggestions["top5"] = _stamp(llm_result["top5"], target_draw_label)
            analysis["ai_top5_used"] = True
            analysis["llm_used"] = True
            analysis["llm_provider"] = llm_config["provider"]
            analysis["llm_model"] = llm_result["model"]
            analysis["llm_summary"] = llm_result["summary"]
            analysis["llm_candidate_count"] = len(llm_candidates)
            print(f"AI suggestions: {[s['number'] for s in suggestions['top5']]}")
        except Exception as exc:  # pylint: disable=broad-except
            print(f"AI suggestion failed (falling back to statistical): {exc}", file=sys.stderr)
            analysis["ai_top5_used"] = False
            analysis["llm_used"] = False
            analysis["ai_error"] = str(exc)
    else:
        analysis["ai_top5_used"] = False
        analysis["llm_used"] = False
        print(
            "No supported LLM credentials found – set GITHUB_MODELS_TOKEN/GITHUB_TOKEN or OPENAI_API_KEY. "
            "Using statistical suggestions only."
        )

    print("Calculating historical ROI…")
    roi = calculate_roi(suggestions, draws)

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "game": "Jokker",
        "source": "https://www.eestiloto.ee/et/results/?game=JOKKER",
        "target_draw_label": target_draw_label,
        "suggestions": suggestions,
        "cost_analysis": roi,
        "analysis": analysis,
    }

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_file = os.path.join(DATA_DIR, f"{SUGGESTIONS_PREFIX}_{ts}.json")
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as fh:
        json.dump(output, fh, indent=2, ensure_ascii=False)
    print(f"Saved suggestions to {output_file}")
    print(f"  top5:   {[s['number'] for s in suggestions['top5']]}")
    print(f"  top50:  {len(suggestions['top50'])} numbers")
    print(f"  top500: {len(suggestions['top500'])} numbers")
    t5 = roi["top5"]
    print(f"  top5 ROI: cost={t5['total_cost']}€  winnings={t5['total_winnings']}€  net={t5['net']}€  ({t5['roi_pct']}%)")


if __name__ == "__main__":
    main()
