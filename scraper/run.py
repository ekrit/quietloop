"""Orchestrates a single scraping run.

For each watch-listed brand (scraper/config.py), pages through olx.ba search
results newest-first for cars priced >= 25,000 KM and mileage >= 50,000 km,
stops once past the 45-day publish window, enriches brand-new listings with
a detail-page fetch, and merges the result into local JSON storage.

See docs/RESEARCH.md for the full rationale. This has not been run against
the live site (network access to olx.ba was blocked in the sandbox this was
built in) — see the module docstrings in parser.py and config.py for what
needs confirming first.
"""
from __future__ import annotations

import argparse
import logging
from datetime import date
from urllib.parse import urlencode

from . import config
from .http_client import CircuitOpenError, PoliteSession
from .parser import parse_detail_page, parse_search_results
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


def scrape_brand(session: PoliteSession, brand: config.Brand, run_date: date) -> list[dict]:
    collected: list[dict] = []
    consecutive_empty_pages = 0

    for page in range(1, config.MAX_PAGES_PER_BRAND + 1):
        url = build_search_url(brand, page)
        logger.info("fetching %s (brand=%s, page=%d)", url, brand.name, page)
        response = session.get(url)
        page_listings = parse_search_results(response.text, reference_date=run_date)

        if not page_listings:
            break  # no more results at all

        in_window = [item for item in page_listings if within_window(item.get("published_date"), run_date)]
        for item in in_window:
            item["brand"] = brand.name
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
                break
        else:
            consecutive_empty_pages = 0

    return collected


def enrich_new_listings(session: PoliteSession, state: dict, listings: list[dict]) -> None:
    """Fetch the detail page only for listings not already in state — spec
    fields don't change over a listing's life, so existing listings never
    need a detail re-fetch (docs/RESEARCH.md §2). Capped per run (see
    config.MAX_DETAIL_FETCHES_PER_RUN) so an unusually large batch of new
    listings — most likely on the very first cold-start run — can't blow
    past the CI job's time budget."""
    fetched = 0
    skipped_due_to_cap = 0
    for item in listings:
        if item["id"] in state:
            continue
        if fetched >= config.MAX_DETAIL_FETCHES_PER_RUN:
            skipped_due_to_cap += 1
            continue
        try:
            response = session.get(item["url"])
        except CircuitOpenError:
            raise
        except Exception:
            logger.exception("failed to fetch detail page for %s", item.get("url"))
            continue
        finally:
            fetched += 1
        item.update(parse_detail_page(response.text))

    if skipped_due_to_cap:
        logger.warning(
            "hit MAX_DETAIL_FETCHES_PER_RUN (%d) — %d new listings saved with "
            "card-level fields only this run",
            config.MAX_DETAIL_FETCHES_PER_RUN,
            skipped_due_to_cap,
        )


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
    try:
        for brand in config.BRAND_WATCHLIST:
            try:
                for item in scrape_brand(session, brand, run_date):
                    all_listings.setdefault(item["id"], item)  # de-dupe across brand queries
            except CircuitOpenError:
                circuit_opened = True
                raise  # systemic — stop the whole run rather than hammering
            except Exception:
                brands_failed += 1
                logger.exception("brand=%s failed, continuing with remaining brands", brand.name)
        enrich_new_listings(session, state, list(all_listings.values()))
    except CircuitOpenError as exc:
        logger.error("stopping run early: %s", exc)

    # whatever was collected before a failure still gets saved below —
    # partial data beats losing the whole day's run to one bad page.

    scraped = list(all_listings.values())
    save_raw_snapshot(run_date, scraped)
    state = merge_into_state(state, scraped, run_date)
    save_state(state)

    healthy = not circuit_opened and brands_failed < len(config.BRAND_WATCHLIST)
    logger.info(
        "run complete: %d listings scraped today, %d total tracked in state, healthy=%s",
        len(scraped),
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
