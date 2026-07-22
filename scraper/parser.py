"""HTML parsing for olx.ba car search-results and listing detail pages.

IMPORTANT — written without direct access to the live site (network access
to olx.ba was blocked in the sandbox this was built in, see docs/RESEARCH.md).
Before trusting this against real data:

  1. Save a real search-results page and a real listing detail page's HTML
     locally, then run this module directly against them, e.g.:
         python -c "from scraper.parser import parse_search_results as p; \\
             print(p(open('sample_search.html').read()))"
     and check the extracted fields actually look right.
  2. If a page embeds a JSON state blob (`__NEXT_DATA__` for Next.js,
     `__NUXT__` for Nuxt, or similar — common on modern OLX-family sites),
     prefer wiring up direct field extraction from that over the regex
     fallback below — it's far more robust to markup changes. `_find_next_data`
     already detects a `__NEXT_DATA__` blob if present; only the actual field
     mapping in `_parse_search_results_html` still needs replacing.
  3. The HTML fallback below assumes each listing "card" is some ancestor of
     an `<a href=".../artikal/...">` link, found by climbing parents until
     climbing further would pull in a second listing's link (`_find_card`).
     That heuristic is the first thing to tune if extracted price/mileage/
     year look wrong or bleed between adjacent listings.
"""
from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from datetime import date, timedelta
from typing import Optional

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_PRICE_RE = re.compile(r"([\d][\d.,]*)\s*KM\b")
_MILEAGE_RE = re.compile(r"([\d][\d.,]*)\s*km\b")
_YEAR_RE = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")
_ITEM_HREF_RE = re.compile(r"/artikal/")
_ID_FROM_URL_RE = re.compile(r"(\d{5,})/?(?:[?#].*)?$")

_RELATIVE_DATE_RE = re.compile(r"prije\s+(\d+)\s+(dan|dana|sat|sati|minut|minuta)", re.IGNORECASE)
_ABSOLUTE_DATE_RE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b")

_MAX_CARD_ANCESTOR_LEVELS = 6


def _strip_diacritics(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def _parse_number(text: str) -> float:
    # BiH formatting uses "." as a thousands separator, e.g. "24.500"
    cleaned = text.replace(".", "").replace(",", ".")
    return float(cleaned)


def _parse_published_date(text: str, reference: date) -> Optional[str]:
    text_low = text.lower()
    if "danas" in text_low:
        return reference.isoformat()
    if "jučer" in text_low or "juče" in text_low or "juce" in text_low:
        return (reference - timedelta(days=1)).isoformat()

    match = _RELATIVE_DATE_RE.search(text_low)
    if match:
        amount, unit = int(match.group(1)), match.group(2)
        if unit.startswith("dan"):
            return (reference - timedelta(days=amount)).isoformat()
        return reference.isoformat()  # hours/minutes ago -> published today

    match = _ABSOLUTE_DATE_RE.search(text)
    if match:
        day, month, year = (int(g) for g in match.groups())
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            return None

    return None


def _listing_id_from_url(url: str) -> str:
    match = _ID_FROM_URL_RE.search(url)
    if match:
        return match.group(1)
    logger.warning("could not extract a numeric id from %s, falling back to a url hash", url)
    return "hash-" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def _extract_year(title: str, card_text: str) -> Optional[int]:
    match = _YEAR_RE.search(title)
    if match:
        return int(match.group(1))
    # strip absolute posting dates (DD.MM.YYYY) first so a listing's "posted
    # on" date can't be mistaken for its model year
    stripped = _ABSOLUTE_DATE_RE.sub(" ", card_text)
    match = _YEAR_RE.search(stripped)
    return int(match.group(1)) if match else None


def _find_card(anchor, max_levels: int = _MAX_CARD_ANCESTOR_LEVELS):
    """Climb from an item link up to its enclosing "card", stopping as soon
    as climbing further would pull in a sibling listing's link too — this is
    structure-agnostic (doesn't depend on knowing real class names/depth),
    unlike a fixed ancestor-level count."""
    card = anchor
    for _ in range(max_levels):
        parent = card.parent
        if parent is None:
            break
        if len(parent.find_all("a", href=_ITEM_HREF_RE)) > 1:
            break
        card = parent
    return card


def _find_next_data(soup: BeautifulSoup) -> Optional[dict]:
    tag = soup.find("script", id="__NEXT_DATA__")
    if tag and tag.string:
        import json

        try:
            return json.loads(tag.string)
        except json.JSONDecodeError:
            return None
    return None


def parse_search_results(html: str, reference_date: Optional[date] = None) -> list[dict]:
    reference_date = reference_date or date.today()
    soup = BeautifulSoup(html, "lxml")

    if _find_next_data(soup) is not None:
        logger.warning(
            "page embeds a __NEXT_DATA__ JSON blob but field extraction from it "
            "isn't implemented yet — falling back to the HTML-regex parser, "
            "which is less reliable. See parser.py module docstring, item 2."
        )

    return _parse_search_results_html(soup, reference_date)


def _parse_search_results_html(soup: BeautifulSoup, reference_date: date) -> list[dict]:
    listings: list[dict] = []
    seen_urls: set[str] = set()

    for anchor in soup.find_all("a", href=_ITEM_HREF_RE):
        href = anchor.get("href", "")
        if not href:
            continue
        url = href if href.startswith("http") else f"https://olx.ba{href}"
        if url in seen_urls:
            continue
        seen_urls.add(url)

        card_text = _find_card(anchor).get_text(" ", strip=True)

        title = anchor.get_text(strip=True) or anchor.get("title", "")

        price_match = _PRICE_RE.search(card_text)
        price_bam = _parse_number(price_match.group(1)) if price_match else None

        mileage_match = _MILEAGE_RE.search(card_text)
        mileage_km = int(_parse_number(mileage_match.group(1))) if mileage_match else None

        listings.append(
            {
                "id": _listing_id_from_url(url),
                "url": url,
                "title": title,
                "price_bam": price_bam,
                "mileage_km": mileage_km,
                "year": _extract_year(title, card_text),
                "published_date": _parse_published_date(card_text, reference_date),
            }
        )

    return listings


# --- Listing detail page enrichment ---------------------------------------
#
# Only called for brand-new listings (see scraper/run.py) — spec fields don't
# change over a listing's life, so existing listings never need a re-fetch.

_DETAIL_LABELS = {
    "godiste": "year",
    "kilometraza": "mileage_km",
    "gorivo": "fuel_type",
    "mjenjac": "transmission",
    "transmisija": "transmission",
    "kubikaza": "engine_ccm",
    "broj vrata": "doors",
    "boja": "color",
    "karoserija": "body_type",
    "pogon": "drivetrain",
    "registrovan do": "registered_until",
}

_DAMAGE_KEYWORDS = ["havarisan", "havarija", "udaren", "ostecen", "lupljen"]
_CUSTOMS_KEYWORDS = ["carina placena", "ocarinjen"]
_FIRST_OWNER_KEYWORDS = ["prvi vlasnik"]
_NEGATION_WORDS = ["nije", "ne "]
_NEGATION_WINDOW = 15


def _has_unnegated_keyword(folded_text: str, keywords: list[str]) -> bool:
    """True if any keyword appears without a Bosnian negation ("nije"/"ne")
    shortly before it — a naive substring check would flag "nije havarisan"
    (NOT wrecked) as damaged, which is backwards."""
    for keyword in keywords:
        start = 0
        while True:
            idx = folded_text.find(keyword, start)
            if idx == -1:
                break
            preceding = folded_text[max(0, idx - _NEGATION_WINDOW) : idx]
            if not any(neg in preceding for neg in _NEGATION_WORDS):
                return True
            start = idx + len(keyword)
    return False


def _extract_labeled_attributes(text: str) -> dict:
    folded = _strip_diacritics(text.lower())
    result: dict = {}
    for label, field in _DETAIL_LABELS.items():
        match = re.search(re.escape(label) + r"\s*[:\-]?\s*([^\n]{1,40})", folded)
        if match:
            result[field] = match.group(1).strip()
    return result


def parse_detail_page(html: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    full_text = soup.get_text("\n", strip=True)
    folded = _strip_diacritics(full_text.lower())

    attributes = _extract_labeled_attributes(full_text)
    photo_count = len(soup.select("img[src*='olx.ba']")) or None

    customs_paid = _has_unnegated_keyword(folded, _CUSTOMS_KEYWORDS)
    first_owner = _has_unnegated_keyword(folded, _FIRST_OWNER_KEYWORDS)

    return {
        **attributes,
        "description_length": len(full_text),
        "damage_flag": _has_unnegated_keyword(folded, _DAMAGE_KEYWORDS),
        "customs_paid": customs_paid or None,
        "first_owner": first_owner or None,
        "photo_count": photo_count,
    }
