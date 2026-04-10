"""
Jokker results scraper for eestiloto.ee

Fetches historical Jokker lottery draw results and saves them to data/jokker_results.json.
Jokker is a 7-digit number game where each digit is 0-9.
"""

import json
import math
import os
import re
import sys
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

RESULTS_URL = "https://www.eestiloto.ee/et/results/"
JOKKER_GAME_PARAM = "?game=JOKKER"
PAGE_PARAM = "&page={page}"
AJAX_RESULTS_URL = "https://www.eestiloto.ee/app/ajaxDrawStatistic"
PAGE_SIZE = 10

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

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
OUTPUT_FILE = os.path.join(DATA_DIR, "jokker_results.json")


def create_session() -> requests.Session:
    """Create a requests session with the headers expected by eestiloto.ee."""
    session = requests.Session()
    session.headers.update(HEADERS)
    return session


def fetch_page(url: str, retries: int = 3, delay: float = 2.0) -> str:
    """Fetch a URL with retries and return the HTML content."""
    for attempt in range(1, retries + 1):
        try:
            response = requests.get(url, headers=HEADERS, timeout=30)
            response.raise_for_status()
            return response.text
        except requests.RequestException as exc:
            print(f"  Attempt {attempt}/{retries} failed for {url}: {exc}", file=sys.stderr)
            if attempt < retries:
                time.sleep(delay)
    raise RuntimeError(f"Failed to fetch {url} after {retries} attempts")


def fetch_csrf_token(session: requests.Session, retries: int = 3, delay: float = 2.0) -> str:
    """Fetch the Jokker results page and extract the CSRF token required by the AJAX API."""
    page_url = RESULTS_URL + JOKKER_GAME_PARAM
    for attempt in range(1, retries + 1):
        try:
            response = session.get(page_url, timeout=30)
            response.raise_for_status()
            match = re.search(r'name="csrfToken" value="([^"]+)"', response.text)
            if not match:
                raise RuntimeError("CSRF token not found in results page")
            return match.group(1)
        except (requests.RequestException, RuntimeError) as exc:
            print(f"  Attempt {attempt}/{retries} failed to fetch CSRF token: {exc}", file=sys.stderr)
            if attempt < retries:
                time.sleep(delay)

    raise RuntimeError(f"Failed to fetch CSRF token after {retries} attempts")


def fetch_draws_page(
    session: requests.Session,
    csrf_token: str,
    page_index: int,
    retries: int = 3,
    delay: float = 2.0,
) -> dict:
    """Fetch a single page of Jokker draw statistics from the AJAX endpoint."""
    payload = {
        "gameTypes": "JOKKER",
        "dateFrom": "",
        "dateTo": "",
        "drawLabelFrom": "",
        "drawLabelTo": "",
        "pageIndex": page_index,
        "orderBy": "drawDate_desc",
        "sortLabelNumeric": True,
        "csrfToken": csrf_token,
    }
    headers = {
        "Referer": RESULTS_URL + JOKKER_GAME_PARAM,
        "X-Requested-With": "XMLHttpRequest",
    }

    for attempt in range(1, retries + 1):
        try:
            response = session.post(AJAX_RESULTS_URL, data=payload, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()
            status_code = data.get("statusCode")
            if status_code != 200:
                raise RuntimeError(f"Unexpected statusCode {status_code} for page {page_index}")
            return data
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            print(
                f"  Attempt {attempt}/{retries} failed for API page {page_index}: {exc}",
                file=sys.stderr,
            )
            if attempt < retries:
                time.sleep(delay)

    raise RuntimeError(f"Failed to fetch API page {page_index} after {retries} attempts")


def parse_api_draws(items: list[dict]) -> list[dict]:
    """Map ajaxDrawStatistic items to the local JSON schema used by the analyzer."""
    draws: list[dict] = []

    for item in items:
        results = item.get("results") or []
        winning_number = ""
        if results and isinstance(results[0], dict):
            winning_number = str(results[0].get("winningNumber") or "")

        digits = _extract_digits(winning_number)
        if not digits:
            continue

        draw_date = item.get("drawDate")
        if isinstance(draw_date, (int, float)):
            iso_date = datetime.fromtimestamp(draw_date / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        else:
            iso_date = _parse_date(str(draw_date or ""))

        draws.append(
            {
                "draw_date": iso_date,
                "draw_label": str(item.get("drawLabel") or ""),
                "digits": digits,
                "number": "".join(str(digit) for digit in digits),
            }
        )

    return draws


def parse_draws(html: str) -> list[dict]:
    """
    Parse Jokker draw results from an HTML page.

    Returns a list of dicts with keys: draw_date, draw_number, digits.
    """
    soup = BeautifulSoup(html, "lxml")
    draws = []

    # Try multiple possible HTML structures used by eestiloto.ee
    # Strategy 1: Look for a section/div dedicated to Jokker results
    jokker_sections = (
        soup.find_all("div", class_=re.compile(r"jokker", re.I))
        or soup.find_all("section", class_=re.compile(r"jokker", re.I))
    )

    if jokker_sections:
        for section in jokker_sections:
            draws.extend(_parse_section(section))
        if draws:
            return draws

    # Strategy 2: Look for result rows inside any results container
    result_containers = soup.find_all(
        "div", class_=re.compile(r"result", re.I)
    )
    for container in result_containers:
        draws.extend(_parse_section(container))
    if draws:
        return draws

    # Strategy 3: Parse tables that look like draw result tables
    for table in soup.find_all("table"):
        draws.extend(_parse_table(table))
    if draws:
        return draws

    # Strategy 4: Scan the full text for 7-digit patterns with nearby dates
    draws.extend(_parse_by_pattern(soup))
    return draws


def _parse_section(section) -> list[dict]:
    """Extract draw info from a results section."""
    draws = []
    date_el = (
        section.find(class_=re.compile(r"date|draw.?date|kuupäev", re.I))
        or section.find("time")
    )
    date_str = date_el.get_text(strip=True) if date_el else ""

    # Numbers can be in a span/div per digit, or space-separated in one element
    number_els = section.find_all(
        class_=re.compile(r"number|digit|ball|num", re.I)
    )
    if number_els:
        digits_text = "".join(el.get_text(strip=True) for el in number_els)
    else:
        numbers_container = section.find(
            class_=re.compile(r"numbers|winning|võidu", re.I)
        )
        digits_text = numbers_container.get_text(strip=True) if numbers_container else ""

    digits = _extract_digits(digits_text)
    if digits:
        draws.append(_make_draw(date_str, digits))
    return draws


def _parse_table(table) -> list[dict]:
    """Extract draw info from an HTML table."""
    draws = []
    for row in table.find_all("tr"):
        cells = row.find_all(["td", "th"])
        row_text = " ".join(c.get_text(strip=True) for c in cells)
        digits = _extract_digits(row_text)
        date_match = re.search(r"\d{1,2}\.\d{1,2}\.\d{4}", row_text)
        if digits:
            draws.append(_make_draw(date_match.group() if date_match else "", digits))
    return draws


def _parse_by_pattern(soup) -> list[dict]:
    """
    Last-resort parser: scan all visible text for patterns matching:
      - A date like DD.MM.YYYY
      - A 7-digit sequence (possibly space-separated)
    """
    draws = []
    text = soup.get_text(separator=" ")
    # Match lines like: "01.04.2026  6 0 5 8 1 0 8" or "6058108"
    pattern = re.compile(
        r"(\d{1,2}\.\d{1,2}\.\d{4})[^\d]*"  # date
        r"((?:\d\s*){7})"                     # 7 single digits possibly spaced
    )
    for match in pattern.finditer(text):
        date_str = match.group(1)
        digits = _extract_digits(match.group(2))
        if digits:
            draws.append(_make_draw(date_str, digits))
    return draws


def _extract_digits(text: str) -> list[int] | None:
    """
    Extract exactly 7 single digits (0-9) from a text string.

    Handles both:
      - Space-separated: "6 0 5 8 1 0 8"
      - Concatenated 7-digit number: "6058108"
    Returns None if extraction fails.
    """
    # Remove non-digit characters except spaces used as separators
    cleaned = text.strip()
    # If it looks like spaced digits: "6 0 5 8 1 0 8"
    spaced = re.findall(r"\b\d\b", cleaned)
    if len(spaced) == 7:
        return [int(d) for d in spaced]
    # If it's a 7-digit run inside text
    run = re.search(r"\b(\d{7})\b", cleaned)
    if run:
        return [int(c) for c in run.group(1)]
    # Fallback: extract all digits and check length
    all_digits = re.sub(r"\D", "", cleaned)
    if len(all_digits) == 7:
        return [int(c) for c in all_digits]
    return None


def _parse_date(date_str: str) -> str:
    """Normalise a date string to ISO format (YYYY-MM-DD)."""
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(date_str.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return date_str.strip()


def _make_draw(date_str: str, digits: list[int]) -> dict:
    return {
        "draw_date": _parse_date(date_str),
        "digits": digits,
        "number": "".join(str(d) for d in digits),
    }


def load_existing_draws(path: str = OUTPUT_FILE) -> list[dict]:
    """Load previously saved draws from disk. Returns empty list if file absent."""
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return data.get("draws") or []


def fetch_all_results(
    max_pages: int | None = None,
    stop_after_keys: set[str] | None = None,
) -> list[dict]:
    """
    Fetch Jokker results across available API pages and deduplicate.

    When *stop_after_keys* is provided (incremental mode), fetching stops as
    soon as a page contains only draws already in that set.

    Returns a list of draw dicts sorted by date descending.
    """
    session = create_session()
    csrf_token = fetch_csrf_token(session)
    all_draws: list[dict] = []
    seen_keys: set[str] = set()
    page = 1
    total_pages: int | None = None

    while max_pages is None or page <= max_pages:
        print(f"Fetching API page {page}: {AJAX_RESULTS_URL}")
        try:
            response_data = fetch_draws_page(session, csrf_token, page)
        except RuntimeError as exc:
            print(f"  Stopping at page {page}: {exc}", file=sys.stderr)
            break

        if total_pages is None:
            draw_count = int(response_data.get("drawCount") or 0)
            total_pages = max(1, math.ceil(draw_count / PAGE_SIZE)) if draw_count else 1
            print(f"  API reports {draw_count} total draws across {total_pages} pages")

        page_draws = parse_api_draws(response_data.get("draws") or [])
        if not page_draws:
            print(f"  No draws found on page {page}, stopping.")
            break

        new_draws = 0
        for draw in page_draws:
            key = f"{draw['draw_date']}_{draw['number']}"
            if key not in seen_keys:
                seen_keys.add(key)
                all_draws.append(draw)
                new_draws += 1

        print(f"  Found {new_draws} new draws on page {page} (total: {len(all_draws)})")

        # In incremental mode stop once every draw on this page is already known
        if stop_after_keys is not None:
            page_keys = {f"{d['draw_date']}_{d['number']}" for d in page_draws}
            if page_keys.issubset(stop_after_keys):
                print("  All draws on this page already known — stopping early.")
                break

        time.sleep(1)  # Be polite

        if total_pages is not None and page >= total_pages:
            break

        page += 1

    # Sort by date descending
    all_draws.sort(key=lambda d: d["draw_date"], reverse=True)
    return all_draws


def save_results(draws: list[dict], path: str = OUTPUT_FILE) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "total_draws": len(draws),
        "draws": draws,
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    print(f"Saved {len(draws)} draws to {path}")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Jokker results scraper")
    parser.add_argument(
        "--incremental",
        action="store_true",
        help=(
            "Fetch only draws newer than those already in jokker_results.json "
            "and merge with the existing file. By default fetches everything."
        ),
    )
    args = parser.parse_args()

    max_pages_raw = os.environ.get("SCRAPER_MAX_PAGES", "").strip()
    max_pages = int(max_pages_raw) if max_pages_raw else None

    if args.incremental:
        existing = load_existing_draws()
        if existing:
            stop_keys = {f"{d['draw_date']}_{d['number']}" for d in existing}
            print(f"Incremental mode: {len(existing)} existing draws, fetching new ones only.")
        else:
            stop_keys = None
            print("Incremental mode: no existing data found, fetching all draws.")

        new_draws = fetch_all_results(max_pages=max_pages, stop_after_keys=stop_keys)

        if existing:
            existing_keys = {f"{d['draw_date']}_{d['number']}" for d in existing}
            truly_new = [d for d in new_draws if f"{d['draw_date']}_{d['number']}" not in existing_keys]
            print(f"Merging {len(truly_new)} new draw(s) with {len(existing)} existing draws.")
            merged = truly_new + existing
            merged.sort(key=lambda d: d["draw_date"], reverse=True)
            draws = merged
        else:
            draws = new_draws
    else:
        draws = fetch_all_results(max_pages=max_pages)

    if not draws:
        print("WARNING: No draws fetched. Saving empty results.", file=sys.stderr)
    save_results(draws)


if __name__ == "__main__":
    main()
