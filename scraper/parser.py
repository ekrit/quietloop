"""Parses search-results pages via the embedded Nuxt SSR state
payload (see scraper/nuxt_payload.py), rather than scraping HTML.

Confirmed against the real site (docs/RESEARCH.md): `state.search.results`
is a clean array of listing objects. Sample shape actually observed:

    {
      "id": 76750281, "title": "...", "price": 19000,
      "display_price": "19.000 KM", "date": 1784752607,   # unix timestamp
      "images": [...], "user_type": "user", "state": "used",
      "status": "active", "brand_id": ..., "category_id": ...,
      "special_labels": [
        {"value": "dizel", "label": "Gorivo", "unit": null},
        {"value": "260.000", "label": "Kilometraža", "unit": "km"},
        {"value": 2012, "label": "Godište", "unit": null}
      ]
    }

`special_labels` is where fuel/mileage/year actually live — they are NOT
separate top-level fields. This was found by trial and error against the
real payload (see the "Debug fetch" workflow run history), not guessed.

NOT yet confirmed: the real listing detail-page URL. Search results carry
no slug/url/permalink field at all, so `url` below is a best-effort guess
(`{BASE_URL}/artikal/{id}`) and likely wrong — the site's real detail links
were never found as plain <a href> tags on the search page, so the
frontend must construct them client-side from a slug computed from the
title. Detail-page enrichment (customs_paid, first_owner, damage_flag,
registered_until, drivetrain, body_type, doors, color, engine_ccm,
description_length, canton) is not implemented yet as a result — it needs
a confirmed detail URL first. Everything else in the schema that's
derivable from the search payload is filled in here.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .brand_matching import fold_brands, guess_brand_from_title, strip_diacritics
from .config import BASE_URL, CONFIRMED_BRAND_IDS, KNOWN_BRANDS
from .nuxt_payload import NuxtPayloadError, extract_nuxt_state

__all__ = ["NuxtPayloadError", "parse_search_results"]


_FOLDED_KNOWN_BRANDS = fold_brands(KNOWN_BRANDS)


def _guess_brand(title, brand_id) -> str | None:
    """No per-brand querying anymore (see config.py) -- every listing in the
    category gets scraped, so brand has to come from the listing itself.
    Prefers the numeric brand_id when it's one we've confirmed; falls back
    to matching KNOWN_BRANDS against the title text (scraper/brand_matching.py,
    shared with the testing verticals' own brand guessing in multi_run.py).
    Returns None rather than guessing wrong when nothing matches."""
    if brand_id in CONFIRMED_BRAND_IDS:
        return CONFIRMED_BRAND_IDS[brand_id]
    return guess_brand_from_title(title, _FOLDED_KNOWN_BRANDS)


# Bosnian special_label -> our field name. Extend this as new labels turn
# up in real data (e.g. "Broj vrata", "Snaga motora", "Karoserija").
_SPECIAL_LABEL_FIELDS = {
    "godiste": "year",
    "kilometraza": "mileage_km",
    "gorivo": "fuel_type",
}
_INTEGER_FIELDS = {"year", "mileage_km"}


def _convert_result_item(item: dict) -> dict:
    listing_id = str(item.get("id"))

    published_date = None
    raw_date = item.get("date")
    if isinstance(raw_date, (int, float)):
        published_date = datetime.fromtimestamp(raw_date, tz=timezone.utc).date().isoformat()

    extra: dict = {}
    for entry in item.get("special_labels") or []:
        label = strip_diacritics(str(entry.get("label", "")).lower())
        field = _SPECIAL_LABEL_FIELDS.get(label)
        if not field:
            continue
        value = entry.get("value")
        if field in _INTEGER_FIELDS:
            try:
                extra[field] = int(str(value).replace(".", ""))
            except (TypeError, ValueError):
                continue
        else:
            extra[field] = value

    user_type = item.get("user_type")
    seller_type = "private" if user_type in (None, "user") else "dealer"

    return {
        "id": listing_id,
        # NEEDS VERIFICATION -- see module docstring; search results carry
        # no url/slug field, this is an unconfirmed guess.
        "url": f"{BASE_URL}/artikal/{listing_id}",
        "title": item.get("title"),
        "brand": _guess_brand(item.get("title"), item.get("brand_id")),
        "price_bam": item.get("price"),
        "published_date": published_date,
        "photo_count": len(item.get("images") or []),
        "seller_type": seller_type,
        "condition_raw": item.get("state"),
        "brand_id": item.get("brand_id"),
        "category_id": item.get("category_id"),
        "city_id": item.get("city_id"),
        **extra,
    }


def parse_search_results(html: str) -> list[dict]:
    """Returns listing dicts extracted from a search-results page's
    embedded Nuxt payload. Raises NuxtPayloadError if the payload can't be
    found/evaluated -- treat that as a hard per-page failure (the site's
    structure likely changed), not as "zero results"."""
    state = extract_nuxt_state(html)
    results = state.get("state", {}).get("search", {}).get("results") or []
    return [_convert_result_item(item) for item in results]
