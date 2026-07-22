"""Runtime configuration for the olx.ba car scraper.

Values flagged NEEDS VERIFICATION are unconfirmed guesses; values flagged
CONFIRMED (NOT) are backed by an actual live run against olx.ba via the
"Debug fetch" GitHub Actions workflow (this sandbox itself can't reach the
site directly — see docs/RESEARCH.md).
"""
from __future__ import annotations

from pathlib import Path

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


# No brand watchlist / per-brand querying anymore (see docs/RESEARCH.md §6):
# the price/mileage/year filters already gate for "expensive enough to be
# worth analyzing" regardless of brand, so pre-selecting brands via the
# search query was just deciding the answer before the data could. Instead
# every car in the category gets scraped once, and `brand` is derived from
# the listing itself (parser.py's _guess_brand): first via CONFIRMED_BRAND_IDS
# below when the numeric id is known, otherwise by matching KNOWN_BRANDS
# against the title text.

# Confirmed from real scraped data (data/listings.json) on 2026-07-22 --
# these are the only olx.ba brand_ids actually verified so far. Extend this
# as more brand_ids get confirmed from future scrapes (e.g. by checking
# which id repeatedly co-occurs with a given brand name in titles).
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
# Hard safety cap regardless of cutoff logic. There's now a single sweep of
# the whole category (no per-brand loop), so this bounds the entire crawl,
# not one brand's worth -- initial guess, not yet tuned against real total
# category volume. 800 pages * ~3s avg delay =~ 40 min, comfortably inside
# the 120-minute job timeout.
MAX_PAGES = 800
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
