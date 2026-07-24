"""Local JSON persistence for scraped listings.

See docs/RESEARCH.md §3 for the design: `data/raw/YYYY-MM-DD.json` is an
untouched daily snapshot (audit trail); `data/listings.json` is the mutable
state table keyed by listing id that the future dashboard would read.

`status` is treated as terminal once it leaves "active": a `removed` or
`aged_out` record is never re-activated, even if the same listing id
reappears in a later scrape (a repost on olx.ba would ordinarily get a new
id anyway — see docs/RESEARCH.md "Repost detection").
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from .config import MAX_LISTING_AGE_DAYS, RAW_DIR, STATE_PATH
from .currency import bam_to_eur, price_per_km


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _days_between(d1: date, d2: date) -> int:
    return (d2 - d1).days


def load_state(state_path: Path = STATE_PATH) -> dict:
    if not state_path.exists():
        return {}
    with state_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state: dict, state_path: Path = STATE_PATH) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = state_path.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
    tmp_path.replace(state_path)


def save_raw_snapshot(run_date: date, listings: list[dict], raw_dir: Path = RAW_DIR) -> Path:
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"{run_date.isoformat()}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(listings, f, ensure_ascii=False, indent=2, sort_keys=True)
    return path


def merge_into_state(
    state: dict,
    scraped: list[dict],
    run_date: date,
    max_listing_age_days: int = MAX_LISTING_AGE_DAYS,
    incomplete_groups: frozenset[str] = frozenset(),
) -> dict:
    """Apply one day's scraped listings onto the state table (mutated and
    returned). See module docstring and docs/RESEARCH.md §2/§5 for the
    removed vs. aged_out distinction.

    `incomplete_groups`: brand/subcategory names (checked against a
    record's `brand` or `subcategory` field, whichever it has) whose scan
    hit its page cap without reaching a natural stop this run -- see
    docs/RESEARCH.md §6b/§10.1. A group's records still get new listings
    added and last_seen/price updated for whatever WAS re-seen, but are
    exempted from the removed/aged_out determination below, since "not
    seen" isn't a trustworthy signal when the scan is known to be
    incomplete. Confirmed via real data that just raising the page cap
    doesn't reliably fix this for the highest-volume groups (bumping cars'
    cap 60->250 still hit the new cap for the same 6 brands and made the
    false-removal rate *worse*, not better) -- this is the actual fix.
    """
    seen_ids = set()

    for item in scraped:
        listing_id = item["id"]
        seen_ids.add(listing_id)
        price_bam = item.get("price_bam")

        existing = state.get(listing_id)
        if existing is None:
            enriched = dict(item)
            enriched["price_eur"] = bam_to_eur(price_bam)
            enriched["price_per_km"] = price_per_km(price_bam, item.get("mileage_km"))
            enriched["first_seen_date"] = run_date.isoformat()
            enriched["last_seen_date"] = run_date.isoformat()
            enriched["status"] = "active"
            enriched["price_history"] = [{"date": run_date.isoformat(), "price_bam": price_bam}]
            enriched["scraped_at"] = _now_iso()
            state[listing_id] = enriched
            continue

        if existing.get("status") != "active":
            continue  # terminal — don't resurrect or keep mutating it

        existing["last_seen_date"] = run_date.isoformat()
        existing["scraped_at"] = _now_iso()
        for key, value in item.items():
            if key == "price_history" or value is None:
                continue
            existing[key] = value
        existing["price_eur"] = bam_to_eur(existing.get("price_bam"))
        existing["price_per_km"] = price_per_km(existing.get("price_bam"), existing.get("mileage_km"))

        last_price = existing["price_history"][-1]["price_bam"] if existing.get("price_history") else None
        if price_bam is not None and price_bam != last_price:
            existing.setdefault("price_history", []).append({"date": run_date.isoformat(), "price_bam": price_bam})

    # status transitions: only ever touch records still "active" going in.
    # Runs over the whole state (including entries just inserted above), so
    # a brand-new listing whose published_date is already stale gets caught
    # and frozen as aged_out on the very same run.
    for record in state.values():
        if record.get("status") != "active":
            continue
        if (record.get("brand") in incomplete_groups) or (record.get("subcategory") in incomplete_groups):
            continue  # today's scan didn't fully cover this group -- don't guess

        published = record.get("published_date")
        listing_id = record["id"]
        age_days = _days_between(date.fromisoformat(published), run_date) if published else None

        if listing_id not in seen_ids:
            if age_days is not None and age_days > max_listing_age_days:
                record["status"] = "aged_out"
                record["aged_out_date"] = run_date.isoformat()
            else:
                record["status"] = "removed"
                record["removed_date"] = run_date.isoformat()
        elif age_days is not None and age_days > max_listing_age_days:
            record["status"] = "aged_out"
            record["aged_out_date"] = run_date.isoformat()

    # days_listed: frozen at removed_date/aged_out_date once terminal, so it
    # stops growing the moment a listing leaves scope (rather than counting
    # up forever using today's date).
    for record in state.values():
        published = record.get("published_date")
        if not published:
            continue
        if record.get("removed_date"):
            end = date.fromisoformat(record["removed_date"])
        elif record.get("aged_out_date"):
            end = date.fromisoformat(record["aged_out_date"])
        else:
            end = run_date
        record["days_listed"] = _days_between(date.fromisoformat(published), end)

    return state
