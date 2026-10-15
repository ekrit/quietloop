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

    def fake_scrape_brand(session, brand, run_date, **kwargs):
        raise CircuitOpenError("3 consecutive hostile responses")

    state, healthy = _run_with_scrape_brand(fake_scrape_brand, watchlist)

    assert healthy is False
    assert state["a1"]["status"] == "active"
    assert state["b1"]["status"] == "active"


def test_unexpected_brand_exception_protects_that_brand_from_false_removal():
    # A brand-specific exception (not the circuit breaker) also must not
    # let merge_into_state treat that brand's listings as legitimately gone.
    watchlist = [config.Brand("Volkswagen", brand_id=89), config.Brand("Audi", brand_id=7)]

    def fake_scrape_brand(session, brand, run_date, **kwargs):
        if brand.name == "Volkswagen":
            raise ValueError("boom")
        return [], False  # Audi completes cleanly with nothing new

    state, healthy = _run_with_scrape_brand(fake_scrape_brand, watchlist)

    assert state["a1"]["status"] == "active"  # Volkswagen protected
    assert state["b1"]["status"] == "removed"  # Audi's scan genuinely completed and saw nothing


def test_brand_that_completes_naturally_is_not_treated_as_incomplete():
    watchlist = [config.Brand("Volkswagen", brand_id=89)]

    def fake_scrape_brand(session, brand, run_date, **kwargs):
        return [], False  # natural stop, zero results today

    state, healthy = _run_with_scrape_brand(fake_scrape_brand, watchlist)

    assert healthy is True
    assert state["a1"]["status"] == "removed"  # genuinely not seen, scan was complete


def _car_html(ids, published=(2026, 8, 24)):
    import json
    from datetime import datetime, timezone

    ts = int(datetime(*published, 12, tzinfo=timezone.utc).timestamp())
    results = [
        {
            "id": i,
            "title": "Volkswagen Golf",
            "price": 30000,
            "date": ts,
            "images": [],
            "user_type": "user",
            "state": "used",
            "status": "active",
            "brand_id": 89,
            "category_id": 18,
            "city_id": 1,
            "special_labels": [
                {"value": "150.000", "label": "Kilometraža", "unit": "km"},
                {"value": 2019, "label": "Godište", "unit": None},
            ],
        }
        for i in ids
    ]
    payload = json.dumps({"state": {"search": {"results": results}}})
    return f"<html><script>window.__NUXT__=(function(){{return {payload}}})()</script></html>"


class _PagedSession:
    def __init__(self, pages):
        self.pages = pages
        self.calls = 0

    def get(self, url, **kwargs):
        html = self.pages[min(self.calls, len(self.pages) - 1)]
        self.calls += 1
        return type("R", (), {"text": html})()


def test_scrape_brand_stops_when_site_repeats_results():
    # Big brands: past a certain depth the site keeps serving already-seen
    # listings instead of an empty page. Must stop early (not burn all
    # MAX_PAGES_PER_BRAND) and report the scan as incomplete.
    session = _PagedSession([_car_html([1, 2]), _car_html([3, 4]), _car_html([3, 4])])

    items, incomplete = run.scrape_brand(session, config.Brand("Volkswagen", brand_id=89), date(2026, 8, 25))

    assert session.calls == 3
    assert incomplete is True
    assert sorted(i["id"] for i in items) == ["1", "2", "3", "4"]


def test_run_is_unhealthy_when_no_brand_completes():
    watchlist = [config.Brand("Volkswagen", brand_id=89)]

    def fake_scrape_brand(session, brand, run_date, **kwargs):
        return [], True  # every brand incomplete -> removal detection fully off

    _, healthy = _run_with_scrape_brand(fake_scrape_brand, watchlist)

    assert healthy is False


def test_repeat_after_passing_window_edge_counts_as_complete():
    # Small brand: its scan already reached listings older than 45 days, so
    # everything in-window was seen -- a trailing repeated page is just the
    # end of results, not truncation.
    old = _car_html([9], published=(2025, 7, 1))
    session = _PagedSession([_car_html([1, 2]), old, old])

    items, incomplete = run.scrape_brand(session, config.Brand("Toyota", brand_id=1), date(2026, 8, 25))

    assert incomplete is False
    assert sorted(i["id"] for i in items) == ["1", "2"]


def test_depth_capped_brand_stops_once_nothing_is_new():
    session = _PagedSession([_car_html([1, 2]), _car_html([3, 4]), _car_html([5, 6])])
    brand = config.Brand("Volkswagen", brand_id=89, depth_capped=True)

    items, incomplete = run.scrape_brand(session, brand, date(2026, 8, 25), known_ids=frozenset({"3", "4"}))

    assert session.calls == 2
    assert incomplete is True
    assert sorted(i["id"] for i in items) == ["1", "2"]


def test_watchlist_runs_depth_capped_brands_last():
    flags = [b.depth_capped for b in config.BRAND_WATCHLIST]
    assert flags == sorted(flags)
    assert len(config.BRAND_WATCHLIST) == 30
