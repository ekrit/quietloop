"""Runtime configuration for the olx.ba car scraper.

Values flagged NEEDS VERIFICATION are best-effort guesses based on
docs/RESEARCH.md — this was written without direct access to olx.ba
(network access to the site was blocked in the sandbox this was built in).
Confirm them against the live site before trusting results, then fix here.
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

# NEEDS VERIFICATION: param is confirmed present in real URLs; exact units
# not confirmed from this environment (docs/RESEARCH.md, item 3).
MILEAGE_MIN_PARAM = "kilometra-a_min"
# NEEDS VERIFICATION: guessed param name for the price floor (docs item 3).
PRICE_MIN_PARAM = "cijena_min"
# NEEDS VERIFICATION: guessed sort param/value for "newest published first" —
# also verify this is true publish date and not a bump/renew date
# (docs/RESEARCH.md item 6).
SORT_PARAM = "sort"
SORT_VALUE_NEWEST = "newest"
# Confirmed present in real URLs (docs/RESEARCH.md §1) as a year-range filter.
YEAR_MIN_PARAM = "godiste_min"

# --- Scope filters (per your instructions) ---------------------------------

MIN_PRICE_BAM = 25_000
MIN_MILEAGE_KM = 50_000
MIN_YEAR = 2016  # inclusive — "younger than 2016" read as 2016 model year or newer
MAX_LISTING_AGE_DAYS = 45


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


# See docs/RESEARCH.md §6 for rationale (your list + BMW).
BRAND_WATCHLIST: list[Brand] = [
    Brand("Volkswagen"),
    Brand("Skoda"),
    Brand("Audi"),
    Brand("Mercedes-Benz"),
    Brand("Porsche"),
    Brand("BMW"),
]

# --- HTTP behavior (see docs/RESEARCH.md "Politeness / risk-reduction") ----

REQUEST_DELAY_SECONDS = (2.0, 4.0)  # randomized delay range between requests
REQUEST_TIMEOUT_SECONDS = 20
MAX_RETRIES = 3
MAX_PAGES_PER_BRAND = 60  # hard safety cap regardless of cutoff logic
CONSECUTIVE_EMPTY_PAGES_TO_STOP = 2
# Caps detail-page fetches in a single run — mainly protects the very first
# run (a cold-start backfill could otherwise find hundreds/thousands of
# "new" listings at once and blow well past any CI job timeout). Listings
# beyond the cap still get saved with search-card-level fields; they just
# permanently miss the detail-only fields (fuel_type, engine, etc.) since
# existing listings are never re-fetched for detail (see run.py).
MAX_DETAIL_FETCHES_PER_RUN = 300

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

BAM_PER_EUR = 1.95583  # fixed currency-board peg
