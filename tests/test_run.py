from datetime import date
from unittest.mock import patch

from scraper import config, run
from scraper.http_client import CircuitOpenError


def _existing_state():
    return {
        "a1": {
            "id": "a1",
            "brand": "Volkswagen",
            "status": "active",
            "published_date": "2026-08-20",
            "last_seen_date": "2026-08-24",
            "price_history": [{"date": "2026-08-20", "price_bam": 30000}],
        },
        "b1": {
            "id": "b1",
            "brand": "Audi",
            "status": "active",
            "published_date": "2026-08-20",
            "last_seen_date": "2026-08-24",
            "price_history": [{"date": "2026-08-20", "price_bam": 40000}],
        },
    }


def _run_with_scrape_brand(fake_scrape_brand, watchlist):
    with patch.object(run, "load_state", return_value=_existing_state()), patch.object(
        run, "save_state"
    ), patch.object(run, "save_raw_snapshot"), patch.object(
        config, "BRAND_WATCHLIST", watchlist
    ), patch.object(
        run, "scrape_brand", side_effect=fake_scrape_brand
    ):
        return run.run(run_date=date(2026, 8, 25))


def test_circuit_breaker_trip_protects_untried_brands_from_false_removal():
    # Regression test for the 2026-08-25 incident: olx.ba returned 403 on the
    # very first request, the circuit breaker tripped before ANY brand
    # finished, and every previously-active listing got wrongly marked
    # removed because incomplete_brands stayed empty (only page-cap
    # exhaustion populated it, not a circuit trip). Volkswagen never gets a
    # chance to run at all here -- it must still be protected.
    watchlist = [config.Brand("Volkswagen", brand_id=89), config.Brand("Audi", brand_id=7)]

    def fake_scrape_brand(session, brand, run_date):
        raise CircuitOpenError("3 consecutive hostile responses")

    state, healthy = _run_with_scrape_brand(fake_scrape_brand, watchlist)

    assert healthy is False
    assert state["a1"]["status"] == "active"
    assert state["b1"]["status"] == "active"


def test_unexpected_brand_exception_protects_that_brand_from_false_removal():
    # A brand-specific exception (not the circuit breaker) also must not
    # let merge_into_state treat that brand's listings as legitimately gone.
    watchlist = [config.Brand("Volkswagen", brand_id=89), config.Brand("Audi", brand_id=7)]

    def fake_scrape_brand(session, brand, run_date):
        if brand.name == "Volkswagen":
            raise ValueError("boom")
        return [], False  # Audi completes cleanly with nothing new

    state, healthy = _run_with_scrape_brand(fake_scrape_brand, watchlist)

    assert state["a1"]["status"] == "active"  # Volkswagen protected
    assert state["b1"]["status"] == "removed"  # Audi's scan genuinely completed and saw nothing


def test_brand_that_completes_naturally_is_not_treated_as_incomplete():
    watchlist = [config.Brand("Volkswagen", brand_id=89)]

    def fake_scrape_brand(session, brand, run_date):
        return [], False  # natural stop, zero results today

    state, healthy = _run_with_scrape_brand(fake_scrape_brand, watchlist)

    assert healthy is True
    assert state["a1"]["status"] == "removed"  # genuinely not seen, scan was complete
