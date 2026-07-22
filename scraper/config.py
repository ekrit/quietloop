"""Runtime configuration for the olx.ba car scraper.

Values flagged NEEDS VERIFICATION are unconfirmed guesses; values flagged
CONFIRMED (NOT) are backed by an actual live run against olx.ba via the
"Debug fetch" GitHub Actions workflow (this sandbox itself can't reach the
site directly — see docs/RESEARCH.md).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# --- Paths ----------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
STATE_PATH = DATA_DIR / "listings.json"

# --- Site constants (see docs/RESEARCH.md §1) ------------------------------

BASE_URL = "https://olx.ba"
SEARCH_PATH = "/pretraga"
CARS_CATEGORY_ID = 18

# NEEDS VERIFICATION: param is confirmed present in real URLs; whether it's
# actually enforced server-side is unconfirmed (see PRICE/YEAR below, which
# are confirmed NOT enforced despite being valid-looking param names).
MILEAGE_MIN_PARAM = "kilometra-a_min"
# CONFIRMED NOT RELIABLY ENFORCED: a live run with cijena_min=25000 still
# returned a listing priced at 19,000 KM. Kept in the URL since it can't
# hurt, but the client-side safety net in run.py is what actually filters.
PRICE_MIN_PARAM = "cijena_min"
# NEEDS VERIFICATION: guessed sort param/value — page 1 with this param
# still returned a listing published well outside a "newest first" sense
# relative to others on the same page, so this may not be a real param at
# all (or "newest" isn't a valid value). Needs a real look at the site's
# actual sort UI/URL.
SORT_PARAM = "sort"
SORT_VALUE_NEWEST = "newest"
# CONFIRMED NOT RELIABLY ENFORCED: a live run with godiste_min=2016 still
# returned a listing from 2012. Same story as PRICE_MIN_PARAM above — kept
# in the URL, but run.py's client-side filter is the real gate.
YEAR_MIN_PARAM = "godiste_min"

# --- Scope filters (per your instructions) ---------------------------------

MIN_PRICE_BAM = 25_000
MIN_MILEAGE_KM = 50_000
MIN_YEAR = 2016  # inclusive — "younger than 2016" read as 2016 model year or newer
MAX_LISTING_AGE_DAYS = 45


# REVERTED (see docs/RESEARCH.md §6 and the 2026-07-22 postmortem): a
# brand-agnostic single sweep of the whole category was tried and made
# things *worse*, not better. A real run hit the 800-page hard cap without
# ever reaching the natural 45-day-window stop condition -- total unfiltered
# category volume is too high to exhaustively traverse in a sane page
# budget, whereas per-brand text search narrows things down enough that
# exhaustive 45-day coverage actually works (proven the day before). Worse,
# that run then marked ~1,820 previously-tracked listings `removed` simply
# because the shallow, truncated crawl never got back around to seeing them
# again -- not because they'd actually left the site. Back to per-brand
# querying, now covering all 17 brands below instead of the original 6.
@dataclass
class Brand:
    name: str
    # Prefer a numeric olx.ba `brand=<id>` filter once confirmed (precise).
    # Until then, falls back to the free-text `trazilica=<name>` search
    # param (works today, but can pick up false positives from listings
    # that merely mention the brand in their description/title).
    brand_id: Optional[int] = None

    def query_params(self) -> dict:
        if self.brand_id is not None:
            return {"brand": self.brand_id, "brands": self.brand_id}
        return {"trazilica": self.name}


# brand_id values below are CONFIRMED from real scraped data
# (data/listings.json) -- precise ID-based filtering for these 6; the rest
# still use free-text search since their real brand_id is unconfirmed.
BRAND_WATCHLIST: list[Brand] = [
    Brand("Volkswagen", brand_id=89),
    Brand("Skoda", brand_id=77),
    Brand("Audi", brand_id=7),
    Brand("Mercedes-Benz", brand_id=56),
    Brand("Porsche", brand_id=69),
    Brand("BMW", brand_id=11),
    Brand("Volvo"),
    Brand("Land Rover"),
    Brand("Toyota"),
    Brand("Lexus"),
    Brand("Hyundai"),
    Brand("Kia"),
    Brand("Ford"),
    Brand("Peugeot"),
    Brand("Renault"),
    Brand("Alfa Romeo"),
    Brand("Fiat"),
]

# Same mapping as BRAND_WATCHLIST's confirmed ids, kept as a dict for
# parser.py's _guess_brand() fallback (used to double-check/label a listing
# by its own brand_id/title even though run.py's per-brand loop already
# tags `brand` from which search found it -- see parser.py).
CONFIRMED_BRAND_IDS: dict[int, str] = {
    89: "Volkswagen",
    77: "Skoda",
    7: "Audi",
    56: "Mercedes-Benz",
    69: "Porsche",
    11: "BMW",
}

# Fallback brand-name matching against listing titles, for listings whose
# brand_id isn't in CONFIRMED_BRAND_IDS above. Sorted longest-first so e.g.
# "Land Rover"/"Alfa Romeo" match before any shorter/ambiguous substring
# could. Not exhaustive -- a title that doesn't match any of these ends up
# with brand=None rather than a guess, which is preferable to a wrong guess.
KNOWN_BRANDS: list[str] = sorted(
    [
        "Volkswagen", "Skoda", "Audi", "Mercedes-Benz", "Porsche", "BMW",
        "Volvo", "Land Rover", "Range Rover", "Toyota", "Lexus", "Hyundai",
        "Kia", "Ford", "Peugeot", "Renault", "Alfa Romeo", "Fiat",
        "Opel", "Citroen", "Seat", "Cupra", "Mini", "Jaguar", "Mazda",
        "Honda", "Nissan", "Mitsubishi", "Suzuki", "Subaru", "Chevrolet",
        "Dacia", "Jeep", "Chrysler", "Dodge", "Tesla", "Maserati",
        "Bentley", "Rolls-Royce", "Lamborghini", "Ferrari", "Aston Martin",
        "Lada", "Smart", "Saab", "Rover", "MG", "DS", "Infiniti", "Cadillac",
    ],
    key=len,
    reverse=True,
)

# --- HTTP behavior (see docs/RESEARCH.md "Politeness / risk-reduction") ----

REQUEST_DELAY_SECONDS = (2.0, 4.0)  # randomized delay range between requests
REQUEST_TIMEOUT_SECONDS = 20
MAX_RETRIES = 3
MAX_PAGES_PER_BRAND = 60  # hard safety cap regardless of cutoff logic
CONSECUTIVE_EMPTY_PAGES_TO_STOP = 2
# If this many pages in a row fail to fetch/parse, stop rather than burning
# the whole MAX_PAGES budget on guaranteed failures (e.g. site structure
# changed, every page now raises NuxtPayloadError).
CONSECUTIVE_PAGE_FAILURES_TO_STOP = 5

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

BAM_PER_EUR = 1.95583  # fixed currency-board peg
