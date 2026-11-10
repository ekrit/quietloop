import json
from datetime import datetime, timezone

import pytest

from scraper.nuxt_payload import NuxtPayloadError
from scraper.parser import parse_search_results

# This mimics the REAL shape confirmed against the live site (see the
# "Debug fetch" workflow run history and docs/RESEARCH.md) -- a Nuxt SSR
# state payload with state.search.results as an array of listing objects,
# with year/mileage/fuel_type inside special_labels rather than as
# top-level fields. Values below are synthetic, but the shape is real.

_PUBLISHED_TS = int(datetime(2026, 7, 20, 12, 0, 0, tzinfo=timezone.utc).timestamp())


def _make_html(results: list[dict]) -> str:
    payload = {"state": {"search": {"results": results}}}
    # Serialize as a JS object literal (valid JSON is valid JS), wrapped in
    # the same (function(){...})() IIFE shape the real site uses.
    js_object = json.dumps(payload)
    return f"""
    <html><body>
    <script>window.__NUXT__=(function(){{return {js_object}}})()</script>
    </body></html>
    """


def _sample_item(**overrides) -> dict:
    item = {
        "id": 12345678,
        "title": "Volkswagen Passat 2.0 TDI",
        "price": 24500,
        "display_price": "24.500 KM",
        "date": _PUBLISHED_TS,
        "images": ["https://cdn.example.com/1.jpg", "https://cdn.example.com/2.jpg"],
        "user_type": "user",
        "state": "used",
        "status": "active",
        "brand_id": 42,
        "category_id": 18,
        "city_id": 7,
        "special_labels": [
            {"value": "dizel", "label": "Gorivo", "unit": None},
            {"value": "185.000", "label": "Kilometraža", "unit": "km"},
            {"value": 2018, "label": "Godište", "unit": None},
        ],
    }
    item.update(overrides)
    return item


def test_parse_search_results_extracts_real_shape():
    html = _make_html([_sample_item()])
    listings = parse_search_results(html)

    assert len(listings) == 1
    listing = listings[0]
    assert listing["id"] == "12345678"
    assert listing["title"] == "Volkswagen Passat 2.0 TDI"
    assert listing["price_bam"] == 24500
    assert listing["published_date"] == "2026-07-20"
    assert listing["photo_count"] == 2
    assert listing["seller_type"] == "private"
    assert listing["year"] == 2018
    assert listing["mileage_km"] == 185000
    assert listing["fuel_type"] == "dizel"
    assert listing["brand_id"] == 42
    assert listing["brand"] == "Volkswagen"  # guessed from title, brand_id=42 unconfirmed


def test_brand_guessed_from_confirmed_id_even_if_title_is_generic():
    # 89 is Volkswagen's real confirmed brand_id (see config.CONFIRMED_BRAND_IDS)
    html = _make_html([_sample_item(brand_id=89, title="2018 diesel wagon, low mileage")])
    listing = parse_search_results(html)[0]
    assert listing["brand"] == "Volkswagen"


def test_brand_guessed_from_title_prefers_longest_match():
    # Must match "Land Rover", not stop at the shorter "Rover" substring
    html = _make_html([_sample_item(brand_id=999999, title="Land Rover Discovery Sport")])
    listing = parse_search_results(html)[0]
    assert listing["brand"] == "Land Rover"


def test_brand_none_when_nothing_matches():
    html = _make_html([_sample_item(brand_id=999999, title="Some Random Car Model XYZ")])
    listing = parse_search_results(html)[0]
    assert listing["brand"] is None


def test_parse_search_results_multiple_items():
    html = _make_html([_sample_item(id=1), _sample_item(id=2, title="Skoda Superb")])
    listings = parse_search_results(html)

    assert [l["id"] for l in listings] == ["1", "2"]


def test_dealer_seller_type_detected():
    html = _make_html([_sample_item(user_type="business")])
    listing = parse_search_results(html)[0]
    assert listing["seller_type"] == "dealer"


def test_missing_special_label_leaves_field_absent():
    item = _sample_item()
    item["special_labels"] = [{"value": "dizel", "label": "Gorivo", "unit": None}]
    html = _make_html([item])
    listing = parse_search_results(html)[0]

    assert listing["fuel_type"] == "dizel"
    assert "year" not in listing
    assert "mileage_km" not in listing


def test_no_results_returns_empty_list():
    html = _make_html([])
    assert parse_search_results(html) == []


def test_missing_nuxt_payload_raises():
    with pytest.raises(NuxtPayloadError):
        parse_search_results("<html><body>no payload here</body></html>")


def _flatten(obj):
    """Encodes `obj` the way Nuxt 3's __NUXT_DATA__ does: a flat JSON array
    whose containers hold indices into the array."""
    values: list = []

    def add(v):
        idx = len(values)
        values.append(None)
        if isinstance(v, dict):
            values[idx] = {k: add(x) for k, x in v.items()}
        elif isinstance(v, list):
            values[idx] = [add(x) for x in v]
        else:
            values[idx] = v
        return idx

    add(obj)
    return values


def _make_nuxt3_html(listings, key='search:{"category_id":"18"}'):
    values = _flatten({"data": {key: {"listings": listings}}, "state": {}})
    return (
        '<html><script>window.__NUXT__={};window.__NUXT__.config={public:{}}</script>'
        '<script type="application/json" data-nuxt-data="nuxt-app" id="__NUXT_DATA__">'
        + json.dumps(values)
        + "</script></html>"
    )


def _nuxt3_item(**overrides):
    item = {
        "id": 79207051,
        "type": "single",
        "title": "Mercedes-Benz GLC 200d 4MATIC",
        "url": "/artikal/79207051",
        "images": ["https://cdn.example.com/1.jpeg", "https://cdn.example.com/2.jpeg"],
        "price": 60900,
        "priceLabel": "60.900 KM",
        "date": _PUBLISHED_TS,
        "shop": True,
        "state": "used",
        "attributes": [
            {"label": "Gorivo", "value": "dizel"},
            {"label": "Kilometraža", "value": "100.826 km"},
            {"label": "Godište", "value": "2022"},
        ],
    }
    item.update(overrides)
    return item


def test_parses_nuxt3_payload():
    listing = parse_search_results(_make_nuxt3_html([_nuxt3_item()]))[0]

    assert listing["id"] == "79207051"
    assert listing["url"] == "https://olx.ba/artikal/79207051"
    assert listing["price_bam"] == 60900
    assert listing["mileage_km"] == 100826
    assert listing["year"] == 2022
    assert listing["fuel_type"] == "dizel"
    assert listing["seller_type"] == "dealer"
    assert listing["published_date"] == "2026-07-20"
    assert listing["photo_count"] == 2


def test_nuxt3_private_seller_and_empty_listings():
    assert parse_search_results(_make_nuxt3_html([_nuxt3_item(shop=False)]))[0]["seller_type"] == "private"
    assert parse_search_results(_make_nuxt3_html([])) == []


def test_nuxt3_payload_without_search_listings_raises():
    with pytest.raises(NuxtPayloadError):
        parse_search_results(_make_nuxt3_html([_nuxt3_item()], key="nav-tree:18"))
