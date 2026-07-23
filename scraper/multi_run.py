"""Orchestrates a scraping run for the non-car testing verticals (see
categories.py's module docstring for what/why -- bicycles, PCs/laptops,
expensive clothing, sports/ski equipment, 2026-07-23 through 2026-08-01).

Deliberately a separate entry point from run.py (cars), not a generalization
of it in place, so this testing expansion can't destabilize the proven car
pipeline. Reuses the same underlying building blocks though: http_client,
parser (both already category-agnostic), and storage (now parameterized by
path -- see storage.py).

Each vertical pages its subcategory watchlist newest-first, applies a
client-side price floor (the site's cijena_min param is sent but, per the
car pipeline's own findings, not reliably enforced -- so this is the real
gate, same as cars), and stops each subcategory once it runs past the
45-day window, same shape as run.py's scrape_brand(). No mileage/year
filters -- those are car-specific concepts that don't apply here.

Self-limiting: past categories.TESTING_END_DATE this exits immediately
without scraping, so the workflow calling this daily doesn't need to be
separately remembered/disabled once the testing window is over.
"""
from __future__ import annotations

import argparse
import logging
from datetime import date
from urllib.parse import urlencode

from . import config
from .categories import VERTICALS, TESTING_END_DATE, SubCategory, Vertical
from .http_client import CircuitOpenError, PoliteSession
from .parser import parse_search_results
from .storage import load_state, merge_into_state, save_raw_snapshot, save_state

logger = logging.getLogger(__name__)


def build_search_url(subcat: SubCategory, page: int, min_price_bam: int) -> str:
    params = {
        "category_id": subcat.category_id,
        config.PRICE_MIN_PARAM: min_price_bam,
        config.SORT_PARAM: config.SORT_VALUE_NEWEST,
        "page": page,
    }
    return f"{config.BASE_URL}{config.SEARCH_PATH}?{urlencode(params)}"


def within_window(published_date: str | None, run_date: date) -> bool:
    if not published_date:
        return True
    age = (run_date - date.fromisoformat(published_date)).days
    return age <= config.MAX_LISTING_AGE_DAYS


def scrape_subcategory(
    session: PoliteSession, subcat: SubCategory, vertical: Vertical, run_date: date
) -> list[dict]:
    collected: list[dict] = []
    consecutive_empty_pages = 0

    for page in range(1, vertical.max_pages_per_subcategory + 1):
        url = build_search_url(subcat, page, vertical.min_price_bam)
        logger.info("fetching %s (vertical=%s, subcat=%s, page=%d)", url, vertical.slug, subcat.name, page)
        response = session.get(url)
        page_listings = parse_search_results(response.text)

        if not page_listings:
            break

        in_window = [item for item in page_listings if within_window(item.get("published_date"), run_date)]
        for item in in_window:
            item["subcategory"] = subcat.name
            if (item.get("price_bam") or 0) < vertical.min_price_bam:
                continue
            collected.append(item)

        if not in_window:
            consecutive_empty_pages += 1
            if consecutive_empty_pages >= vertical.consecutive_empty_pages_to_stop:
                logger.info(
                    "stopping vertical=%s subcat=%s at page=%d: %d consecutive pages past the %d-day window",
                    vertical.slug,
                    subcat.name,
                    page,
                    consecutive_empty_pages,
                    config.MAX_LISTING_AGE_DAYS,
                )
                break
        else:
            consecutive_empty_pages = 0

    return collected


def run_vertical(session: PoliteSession, vertical: Vertical, run_date: date) -> tuple[dict, bool]:
    state = load_state(vertical.state_path)
    all_listings: dict[str, dict] = {}
    subcats_failed = 0
    circuit_opened = False

    try:
        for subcat in vertical.subcategories:
            try:
                for item in scrape_subcategory(session, subcat, vertical, run_date):
                    all_listings.setdefault(item["id"], item)
            except CircuitOpenError:
                circuit_opened = True
                raise
            except Exception:
                subcats_failed += 1
                logger.exception(
                    "vertical=%s subcat=%s failed, continuing with remaining subcategories",
                    vertical.slug,
                    subcat.name,
                )
    except CircuitOpenError as exc:
        logger.error("stopping vertical=%s early: %s", vertical.slug, exc)

    scraped = list(all_listings.values())
    save_raw_snapshot(run_date, scraped, vertical.raw_dir)
    state = merge_into_state(state, scraped, run_date)
    save_state(state, vertical.state_path)

    healthy = not circuit_opened and subcats_failed < len(vertical.subcategories)
    logger.info(
        "vertical=%s complete: %d listings scraped today, %d total tracked, healthy=%s",
        vertical.slug,
        len(scraped),
        len(state),
        healthy,
    )
    return state, healthy


def run(run_date: date | None = None) -> bool:
    """Returns overall healthy flag across all verticals. Exits early
    (returns True, nothing scraped) once past TESTING_END_DATE."""
    run_date = run_date or date.today()

    if run_date > date.fromisoformat(TESTING_END_DATE):
        logger.info(
            "run_date %s is past TESTING_END_DATE %s -- this was a time-boxed testing "
            "expansion (see categories.py), skipping without scraping.",
            run_date,
            TESTING_END_DATE,
        )
        return True

    session = PoliteSession()
    overall_healthy = True
    for vertical in VERTICALS:
        try:
            _, healthy = run_vertical(session, vertical, run_date)
            overall_healthy = overall_healthy and healthy
        except Exception:
            overall_healthy = False
            logger.exception("vertical=%s failed entirely, continuing with remaining verticals", vertical.slug)

    return overall_healthy


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    arg_parser = argparse.ArgumentParser(description=__doc__)
    arg_parser.add_argument("--date", help="override run date (YYYY-MM-DD)")
    args = arg_parser.parse_args()
    run_date = date.fromisoformat(args.date) if args.date else None
    healthy = run(run_date=run_date)
    if not healthy:
        logger.error("run was unhealthy (see errors above) — exiting nonzero so this gets flagged")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
