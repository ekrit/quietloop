"""Orchestrates a single scraping run.

For each watch-listed brand (scraper/config.py), pages through search
results newest-first for cars priced >= 25,000 KM and mileage >= 50,000 km,
stops once past the 45-day publish window, and merges the result into local
JSON storage.

Per-brand querying was briefly dropped in favor of one brand-agnostic sweep
of the whole category (the idea being: the price/mileage/year filters
already gate for "worth analyzing" regardless of brand, so why pre-select
brands at all). That made things worse, not better — a real run hit the
800-page hard cap without ever reaching the natural 45-day-window stop
condition, because total unfiltered category volume is too high to
exhaustively traverse in a sane page budget. It then marked ~1,820
previously-tracked listings `removed` simply because the shallow crawl
never got back around to seeing them, not because they'd actually left the
site. Per-brand text search apparently narrows things down enough that
exhaustive 45-day coverage actually works (proven separately) — so this is
back to per-brand querying, just covering more brands than originally.

The same problem recurred at brand-scope once the watchlist grew large
enough (docs/RESEARCH.md §6b): Volkswagen, Skoda, Audi, Mercedes-Benz, BMW,
and Peugeot all hit `MAX_PAGES_PER_BRAND` without a natural stop. Raising
the cap 60→250 didn't fix it — the same 6 brands hit the new cap too, and
the false-removal rate got *worse*. Rather than keep guessing at a bigger
number, `scrape_brand` now reports whether it actually reached a natural
stop; `run()` tracks which brands didn't and tells `merge_into_state` to
skip removed/aged_out determination for them that day (`incomplete_
groups`) — a brand's unseen listings just stay untouched until a day the
scan does complete, rather than getting guessed at.

Listing data (price, year, mileage, fuel type, etc.) comes from the search
page's embedded Nuxt SSR state payload (see parser.py, nuxt_payload.py) —
verified against the real live site via the "Debug fetch" workflow, not
guessed. There is currently no detail-page enrichment step: the search
payload carries no url/slug for individual listings, so the real detail
page URL pattern isn't confirmed yet, and some schema fields (customs_paid,
first_owner, damage_flag, registered_until, drivetrain, body_type, doors,
color, engine_ccm, description_length, canton) aren't populated as a
result. See parser.py's module docstring for details.
"""
from __future__ import annotations

import argparse
import logging
from datetime import date
from urllib.parse import urlencode

from . import config
from .http_client import CircuitOpenError, PoliteSession
from .parser import parse_search_results
from .storage import load_state, merge_into_state, save_raw_snapshot, save_state

logger = logging.getLogger(__name__)


def build_search_url(brand: config.Brand, page: int) -> str:
    params = {
        "category_id": config.CARS_CATEGORY_ID,
        config.MILEAGE_MIN_PARAM: config.MIN_MILEAGE_KM,
        config.PRICE_MIN_PARAM: config.MIN_PRICE_BAM,
        config.YEAR_MIN_PARAM: config.MIN_YEAR,
        config.SORT_PARAM: config.SORT_VALUE_NEWEST,
        "page": page,
    }
    params.update(brand.query_params())
    return f"{config.BASE_URL}{config.SEARCH_PATH}?{urlencode(params)}"


def within_window(published_date: str | None, run_date: date) -> bool:
    if not published_date:
        # unknown publish date - keep it rather than silently dropping;
        # merge_into_state will still cap it once a date is known.
        return True
    age = (run_date - date.fromisoformat(published_date)).days
    return age <= config.MAX_LISTING_AGE_DAYS


def scrape_brand(session: PoliteSession, brand: config.Brand, run_date: date) -> tuple[list[dict], bool]:
    """Returns (collected, hit_page_cap). hit_page_cap is True if the loop
    ran out of MAX_PAGES_PER_BRAND without reaching a natural stop -- see
    storage.merge_into_state's incomplete_groups: a brand whose scan didn't
    finish shouldn't have its unseen listings marked removed/aged_out,
    since "not seen" isn't trustworthy when the scan itself is known to be
    incomplete (confirmed via real data 2026-07-24, docs/RESEARCH.md §6b --
    raising the cap alone doesn't reliably fix this for the highest-volume
    brands)."""
    collected: list[dict] = []
    consecutive_empty_pages = 0

    for page in range(1, config.MAX_PAGES_PER_BRAND + 1):
        url = build_search_url(brand, page)
        logger.info("fetching %s (brand=%s, page=%d)", url, brand.name, page)
        response = session.get(url)
        page_listings = parse_search_results(response.text)

        if not page_listings:
            return collected, False  # no more results at all -- naturally done

        in_window = [item for item in page_listings if within_window(item.get("published_date"), run_date)]
        for item in in_window:
            item["brand"] = brand.name  # authoritative: which search found it
            # safety net: don't trust server-side filters blindly, and don't
            # trust the parser's extraction blindly either.
            if (item.get("price_bam") or 0) < config.MIN_PRICE_BAM:
                continue
            if (item.get("mileage_km") or 0) < config.MIN_MILEAGE_KM:
                continue
            if (item.get("year") or 0) < config.MIN_YEAR:
                continue
            collected.append(item)

        if not in_window:
            consecutive_empty_pages += 1
            if consecutive_empty_pages >= config.CONSECUTIVE_EMPTY_PAGES_TO_STOP:
                logger.info(
                    "stopping brand=%s at page=%d: %d consecutive pages past the %d-day window",
                    brand.name,
                    page,
                    consecutive_empty_pages,
                    config.MAX_LISTING_AGE_DAYS,
                )
                return collected, False  # naturally done
        else:
            consecutive_empty_pages = 0

    logger.warning(
        "brand=%s hit MAX_PAGES_PER_BRAND=%d without a natural stop -- "
        "today's scan is incomplete for this brand, skipping removed/aged_out "
        "determination for it this run (see docs/RESEARCH.md §6b)",
        brand.name,
        config.MAX_PAGES_PER_BRAND,
    )
    return collected, True


def run(run_date: date | None = None) -> tuple[dict, bool]:
    """Returns (state, healthy). `healthy` is False if the circuit breaker
    tripped or every single brand failed — i.e. a likely systemic problem
    (site blocking us, network down) rather than one bad page. Partial data
    is still saved either way (see below) — this flag is purely so the
    caller (see `main`) can surface a loud failure for an unattended daily
    run instead of silently persisting an empty/near-empty snapshot."""
    run_date = run_date or date.today()

    session = PoliteSession()
    state = load_state()

    all_listings: dict[str, dict] = {}
    brands_failed = 0
    circuit_opened = False
    # CONFIRMED BUG 2026-08-26: only tracked brands that hit their page cap --
    # a brand that never got a chance to run at all (circuit breaker tripped
    # before/during its turn) or that raised an unexpected exception was
    # never added here, so merge_into_state trusted "not seen" as "actually
    # removed" for it. A live run where olx.ba returned 403 on the very
    # first request tripped the circuit breaker immediately, leaving this
    # set empty, and wrongly marked all ~8,921 previously-active listings
    # removed in one run (see docs/RESEARCH.md §6b/§14 for the incident and
    # data restore). Fixed by tracking the complement instead: only a brand
    # that affirmatively reached its own natural stop this run is trusted
    # for removal detection -- everything else (page cap, exception, never
    # attempted due to a circuit trip) defaults to incomplete.
    completed_brands: set[str] = set()
    try:
        for brand in config.BRAND_WATCHLIST:
            try:
                items, hit_cap = scrape_brand(session, brand, run_date)
                if not hit_cap:
                    completed_brands.add(brand.name)
                for item in items:
                    all_listings.setdefault(item["id"], item)  # de-dupe across brand queries
            except CircuitOpenError:
                circuit_opened = True
                raise  # systemic — stop the whole run rather than hammering
            except Exception:
                brands_failed += 1
                logger.exception("brand=%s failed, continuing with remaining brands", brand.name)
    except CircuitOpenError as exc:
        logger.error("stopping run early: %s", exc)

    # whatever was collected before a failure still gets saved below —
    # partial data beats losing the whole day's run to one bad page.

    incomplete_brands = {brand.name for brand in config.BRAND_WATCHLIST} - completed_brands

    scraped = list(all_listings.values())
    save_raw_snapshot(run_date, scraped)
    state = merge_into_state(state, scraped, run_date, incomplete_groups=frozenset(incomplete_brands))
    save_state(state)

    healthy = not circuit_opened and brands_failed < len(config.BRAND_WATCHLIST)
    logger.info(
        "run complete: %d listings scraped today, %d total tracked in state, "
        "healthy=%s, incomplete_brands=%s",
        len(scraped),
        len(state),
        healthy,
        sorted(incomplete_brands) or None,
    )
    return state, healthy


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    arg_parser = argparse.ArgumentParser(description=__doc__)
    arg_parser.add_argument("--date", help="override run date (YYYY-MM-DD), mainly for backfills/testing")
    args = arg_parser.parse_args()
    run_date = date.fromisoformat(args.date) if args.date else None
    _, healthy = run(run_date=run_date)
    if not healthy:
        logger.error("run was unhealthy (see errors above) — exiting nonzero so this gets flagged")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
