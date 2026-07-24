import json
from datetime import date, datetime, timezone

from scraper.categories import SubCategory, Vertical
from scraper.multi_run import build_search_url, run_vertical, within_window

_PUBLISHED_TS = int(datetime(2026, 7, 23, 12, 0, 0, tzinfo=timezone.utc).timestamp())


def _make_html(results: list[dict]) -> str:
    payload = {"state": {"search": {"results": results}}}
    js_object = json.dumps(payload)
    return f"<html><body><script>window.__NUXT__=(function(){{return {js_object}}})()</script></body></html>"


def _sample_item(**overrides) -> dict:
    item = {
        "id": 555,
        "title": "Test bicycle",
        "price": 900,
        "date": _PUBLISHED_TS,
        "images": [],
        "user_type": "user",
        "state": "used",
        "status": "active",
        "brand_id": None,
        "category_id": 22,
        "city_id": 1,
        "special_labels": None,
    }
    item.update(overrides)
    return item


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeSession:
    """Returns one page of results, then empty pages forever."""

    def __init__(self, pages: list[list[dict]]) -> None:
        self._pages = pages
        self._calls = 0

    def get(self, url: str, **kwargs) -> _FakeResponse:
        page_idx = self._calls
        self._calls += 1
        results = self._pages[page_idx] if page_idx < len(self._pages) else []
        return _FakeResponse(_make_html(results))


def test_build_search_url_has_no_car_specific_params():
    url = build_search_url(SubCategory("Bicikli", 22), page=2, min_price_bam=500)
    assert "category_id=22" in url
    assert "cijena_min=500" in url
    assert "page=2" in url
    assert "kilometra" not in url
    assert "godiste" not in url


def test_within_window():
    assert within_window("2026-07-20", date(2026, 7, 22))
    assert not within_window("2026-01-01", date(2026, 7, 22))
    assert within_window(None, date(2026, 7, 22))


def test_run_vertical_filters_by_price_and_keeps_old_listings(tmp_path):
    vertical = Vertical(
        name="Bicycles",
        slug="bicycles",
        min_price_bam=500,
        subcategories=[SubCategory("Bicikli", 22)],
        max_pages_per_subcategory=5,
    )
    session = _FakeSession(
        [
            [_sample_item(id=1, price=900), _sample_item(id=2, price=300)],  # below threshold dropped
        ]
    )

    original_state_path = Vertical.state_path
    original_raw_dir = Vertical.raw_dir
    try:
        Vertical.state_path = property(lambda self: tmp_path / "listings.json")
        Vertical.raw_dir = property(lambda self: tmp_path / "raw")

        state, healthy = run_vertical(session, vertical, date(2026, 7, 23))
        assert healthy
        assert set(state.keys()) == {"1"}
        assert state["1"]["status"] == "active"

        # second day: id=1 no longer appears -> removed; a brand-new id=3 appears
        session2 = _FakeSession([[_sample_item(id=3, price=600)]])
        state2, healthy2 = run_vertical(session2, vertical, date(2026, 7, 24))
        assert healthy2
        assert state2["1"]["status"] == "removed"
        assert state2["3"]["status"] == "active"
    finally:
        Vertical.state_path = original_state_path
        Vertical.raw_dir = original_raw_dir


def test_run_vertical_tags_brand_and_model_hint(tmp_path):
    vertical = Vertical(
        name="Bicycles",
        slug="bicycles",
        min_price_bam=500,
        subcategories=[SubCategory("Bicikli", 22)],
        known_brands=["Specialized", "Trek"],
        max_pages_per_subcategory=5,
    )
    session = _FakeSession(
        [
            [
                _sample_item(id=1, price=900, title="Specialized Rockhopper 29 2022"),
                _sample_item(id=2, price=900, title="Nepoznata marka bicikl 26 in"),
            ],
        ]
    )

    original_state_path = Vertical.state_path
    original_raw_dir = Vertical.raw_dir
    try:
        Vertical.state_path = property(lambda self: tmp_path / "listings.json")
        Vertical.raw_dir = property(lambda self: tmp_path / "raw")

        state, healthy = run_vertical(session, vertical, date(2026, 7, 23))
        assert healthy
        assert state["1"]["brand"] == "Specialized"
        assert state["1"]["model_hint"] == "Rockhopper 29 2022"
        assert state["2"]["brand"] is None
        assert state["2"]["model_hint"] is None
    finally:
        Vertical.state_path = original_state_path
        Vertical.raw_dir = original_raw_dir
