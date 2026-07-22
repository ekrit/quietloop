"""Orchestrates a single scraping run.

Pages through olx.ba's whole car category (scraper/config.py) newest-first,
stops once past the 45-day publish window, and merges the result into
local JSON storage. There's no per-brand watchlist/querying: the price/
mileage/year filters already gate for "expensive enough to be worth
analyzing" regardless of brand, so every car in the category gets scraped
once and `brand` is derived from the listing itself (see parser.py's
_guess_brand) rather than from which per-brand search found it.

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


def build_search_url(page: int) -> str:
    params = {
        "category_id": config.CARS_CATEGORY_ID,
        config.MILEAGE_MIN_PARAM: config.MIN_MILEAGE_KM,
        config.PRICE_MIN_PARAM: config.MIN_PRICE_BAM,
        config.YEAR_MIN_PARAM: config.MIN_YEAR,
        config.SORT_PARAM: config.SORT_VALUE_NEWEST,
        "page": page,
    }
    return f"{config.BASE_URL}{config.SEARCH_PATH}?{urlencode(params)}"


def within_window(published_date: str | None, run_date: date) -> bool:
    if not published_date:
        # unknown publish date - keep it rather than silently dropping;
        # merge_into_state will still cap it once a date is known.
        return True
    age = (run_date - date.fromisoformat(published_date)).days
    return age <= config.MAX_LISTING_AGE_DAYS


def scrape_all(session: PoliteSession, run_date: date) -> tuple[list[dict], int]:
    """Pages through the whole category once. Returns (listings, pages_failed).

    A single bad page is logged and skipped (not fatal) so one glitch can't
    lose the rest of the crawl — but too many in a row (site fully broken,
    payload structure changed) stops the run early rather than burning the
    whole page budget on guaranteed failures.
    """
    collected: dict[str, dict] = {}
    consecutive_empty_pages = 0
    consecutive_page_failures = 0
    pages_failed = 0

    for page in range(1, config.MAX_PAGES + 1):
        url = build_search_url(page)
        logger.info("fetching %s (page=%d)", url, page)
        try:
            response = session.get(url)
            page_listings = parse_search_results(response.text)
        except CircuitOpenError:
            raise  # systemic — stop the whole run rather than hammering
        except Exception:
            pages_failed += 1
            consecutive_page_failures += 1
            logger.exception("page=%d failed, skipping", page)
            if consecutive_page_failures >= config.CONSECUTIVE_PAGE_FAILURES_TO_STOP:
                logger.error("stopping after %d consecutive page failures", consecutive_page_failures)
                break
            continue
        consecutive_page_failures = 0

        if not page_listings:
            break  # no more results at all

        in_window = [item for item in page_listings if within_window(item.get("published_date"), run_date)]
        for item in in_window:
            # safety net: don't trust server-side filters blindly, and don't
            # trust the parser's extraction blindly either.
            if (item.get("price_bam") or 0) < config.MIN_PRICE_BAM:
                continue
            if (item.get("mileage_km") or 0) < config.MIN_MILEAGE_KM:
                continue
            if (item.get("year") or 0) < config.MIN_YEAR:
                continue
            collected.setdefault(item["id"], item)  # dedupe against overlapping pagination

        if not in_window:
            consecutive_empty_pages += 1
            if consecutive_empty_pages >= config.CONSECUTIVE_EMPTY_PAGES_TO_STOP:
                logger.info(
                    "stopping at page=%d: %d consecutive pages past the %d-day window",
                    page,
                    consecutive_empty_pages,
                    config.MAX_LISTING_AGE_DAYS,
                )
                break
        else:
            consecutive_empty_pages = 0

    return list(collected.values()), pages_failed


def run(run_date: date | None = None) -> tuple[dict, bool]:
    """Returns (state, healthy). `healthy` is False if the circuit breaker
    tripped or the run ended with zero listings collected — a likely
    systemic problem (site blocking us, network down, payload structure
    changed) rather than normal day-to-day variation. Partial data is still
    saved either way (see below) — this flag is purely so the caller (see
    `main`) can surface a loud failure for an unattended daily run instead
    of silently persisting an empty/near-empty snapshot."""
    run_date = run_date or date.today()

    session = PoliteSession()
    state = load_state()

    circuit_opened = False
    scraped: list[dict] = []
    pages_failed = 0
    try:
        scraped, pages_failed = scrape_all(session, run_date)
    except CircuitOpenError as exc:
        circuit_opened = True
        logger.error("stopping run early: %s", exc)

    # whatever was collected before a failure still gets saved below —
    # partial data beats losing the whole day's run to one bad page.

    save_raw_snapshot(run_date, scraped)
    state = merge_into_state(state, scraped, run_date)
    save_state(state)

    healthy = not circuit_opened and len(scraped) > 0
    logger.info(
        "run complete: %d listings scraped today (%d page failures), %d total tracked in state, healthy=%s",
        len(scraped),
        pages_failed,
        len(state),
        healthy,
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
