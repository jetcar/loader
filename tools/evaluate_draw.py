"""
evaluate_draw.py — Evaluate pending suggestion files against actual draw results.

For every suggestions_<TIMESTAMP>.json that has a target_draw_label, checks if
that draw is present in jokker_results.json. If it is, and no matching
evaluation_<TIMESTAMP>.json exists yet, computes prize winnings for the top5,
top50, and top500 tiers and saves the result.

Designed to be run unconditionally after each scrape: it simply skips files
that are already evaluated or whose target draw has not arrived yet.
"""

import glob
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "data"

PRIZE_TABLE = {
    7: 1_000_000.00,
    6: 30_000.00,
    5: 1_000.00,
    4: 50.00,
    3: 6.00,
    2: 2.00,
    1: 0.0,
    0: 0.0,
}
COST_PER_LINE = 2.00


def count_jokker_matches(suggestion: str, draw_number: str) -> int:
    """Return how many consecutive digits match from the right."""
    matches = 0
    for s_digit, d_digit in zip(reversed(suggestion), reversed(draw_number)):
        if s_digit == d_digit:
            matches += 1
        else:
            break
    return matches


def load_draws() -> list[dict]:
    results_path = DATA_DIR / "jokker_results.json"
    if not results_path.exists():
        return []
    with open(results_path, encoding="utf-8") as fh:
        data = json.load(fh)
    return data.get("draws", [])


def find_draw_by_label(draws: list[dict], label: str) -> dict | None:
    return next((d for d in draws if str(d.get("draw_label")) == str(label)), None)


def _tier_result(entries: list[dict], draw_number: str) -> dict:
    results = []
    total_winnings = 0.0
    for entry in entries:
        number = entry if isinstance(entry, str) else entry.get("number", "")
        matches = count_jokker_matches(number, draw_number)
        prize = PRIZE_TABLE.get(matches, 0.0)
        total_winnings += prize
        results.append({"number": number, "matches": matches, "prize": prize})

    lines = len(results)
    cost = lines * COST_PER_LINE
    net = total_winnings - cost
    return {
        "lines": lines,
        "cost": cost,
        "winnings": total_winnings,
        "net": net,
        "results": results,
    }


def evaluate_file(suggestion_path: Path, draws: list[dict]) -> Path | None:
    """Evaluate one suggestion file. Returns path of written evaluation file, or None."""
    ts_match = re.search(r"suggestions_(\w+)\.json$", suggestion_path.name)
    if not ts_match:
        return None
    ts = ts_match.group(1)

    eval_path = DATA_DIR / f"evaluation_{ts}.json"
    if eval_path.exists():
        return None  # already done

    with open(suggestion_path, encoding="utf-8") as fh:
        s = json.load(fh)

    target_label = s.get("target_draw_label")
    if not target_label:
        return None  # old file without target label

    draw = find_draw_by_label(draws, target_label)
    if not draw:
        return None  # draw not yet available

    draw_number = draw["number"]
    suggestions = s.get("suggestions", {})

    evaluation = {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "suggestion_file": suggestion_path.name,
        "suggestion_timestamp": ts,
        "target_draw_label": target_label,
        "draw_date": draw.get("draw_date"),
        "draw_number": draw_number,
        "cost_per_line": COST_PER_LINE,
        "top5": _tier_result(suggestions.get("top5", []), draw_number),
        "top50": _tier_result(suggestions.get("top50", []), draw_number),
        "top500": _tier_result(suggestions.get("top500", []), draw_number),
    }

    with open(eval_path, "w", encoding="utf-8") as fh:
        json.dump(evaluation, fh, indent=2, ensure_ascii=False)
    return eval_path


def main() -> None:
    draws = load_draws()
    if not draws:
        print("No draw data found, skipping evaluation.")
        return

    suggestion_files = sorted(DATA_DIR.glob("suggestions_*.json"))
    if not suggestion_files:
        print("No suggestion files found.")
        return

    evaluated = 0
    for path in suggestion_files:
        result = evaluate_file(path, draws)
        if result:
            print(f"Evaluated: {result.name}")
            evaluated += 1

    if evaluated == 0:
        print("No new evaluations to perform.")
    else:
        print(f"Done. {evaluated} evaluation file(s) written.")


if __name__ == "__main__":
    main()
