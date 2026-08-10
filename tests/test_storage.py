from datetime import date

from scraper.storage import merge_into_state


def _listing(id_, price, published_date, mileage=100000):
    return {
        "id": id_,
        "url": f"https://example.com/artikal/{id_}",
        "brand": "Volkswagen",
        "title": "Test listing",
        "price_bam": price,
        "mileage_km": mileage,
        "year": 2018,
        "published_date": published_date,
    }


def test_new_listing_is_added():
    run_date = date(2026, 7, 22)
    state = merge_into_state({}, [_listing("a1", 24500, "2026-07-20")], run_date)

    assert state["a1"]["status"] == "active"
    assert state["a1"]["first_seen_date"] == "2026-07-22"
    assert state["a1"]["price_history"] == [{"date": "2026-07-22", "price_bam": 24500}]
    assert state["a1"]["days_listed"] == 2


def test_price_change_is_recorded():
    state = merge_into_state({}, [_listing("a1", 24500, "2026-07-20")], date(2026, 7, 22))
    state = merge_into_state(state, [_listing("a1", 23000, "2026-07-20")], date(2026, 7, 23))

    assert [p["price_bam"] for p in state["a1"]["price_history"]] == [24500, 23000]
    assert state["a1"]["last_seen_date"] == "2026-07-23"


def test_unchanged_price_does_not_duplicate_history():
    state = merge_into_state({}, [_listing("a1", 24500, "2026-07-20")], date(2026, 7, 22))
    state = merge_into_state(state, [_listing("a1", 24500, "2026-07-20")], date(2026, 7, 23))

    assert len(state["a1"]["price_history"]) == 1


def test_disappearance_within_window_is_removed():
    state = merge_into_state({}, [_listing("a1", 24500, "2026-07-20")], date(2026, 7, 22))
    state = merge_into_state(state, [], date(2026, 7, 25))

    assert state["a1"]["status"] == "removed"
    assert state["a1"]["removed_date"] == "2026-07-25"
    assert state["a1"]["days_listed"] == 5  # 07-20 -> 07-25


def test_stale_listing_becomes_aged_out_not_removed():
    # published well over 45 days before it's first even seen
    state = merge_into_state({}, [_listing("a1", 24500, "2026-06-01")], date(2026, 7, 22))

    assert state["a1"]["status"] == "aged_out"
    assert "removed_date" not in state["a1"]
    assert state["a1"]["aged_out_date"] == "2026-07-22"


def test_terminal_status_is_never_reactivated():
    state = merge_into_state({}, [_listing("a1", 24500, "2026-06-01")], date(2026, 7, 22))
    assert state["a1"]["status"] == "aged_out"

    # site still shows it (or a scrape glitch re-includes it) on a later day
    state = merge_into_state(state, [_listing("a1", 24500, "2026-06-01")], date(2026, 7, 23))

    assert state["a1"]["status"] == "aged_out"
    assert state["a1"]["last_seen_date"] == "2026-07-22"  # untouched, not refreshed


def test_aged_out_days_listed_is_frozen():
    state = merge_into_state({}, [_listing("a1", 24500, "2026-06-01")], date(2026, 7, 22))
    days_at_ageout = state["a1"]["days_listed"]

    state = merge_into_state(state, [], date(2026, 8, 1))

    assert state["a1"]["days_listed"] == days_at_ageout


def test_incomplete_group_skips_removal_for_its_brand():
    # simulates a brand whose scan hit its page cap without a natural stop
    # (docs/RESEARCH.md §6b/§10.1) -- listing should stay active rather
    # than being falsely marked removed just because it wasn't re-seen.
    state = merge_into_state({}, [_listing("a1", 24500, "2026-07-20")], date(2026, 7, 22))
    state = merge_into_state(state, [], date(2026, 7, 25), incomplete_groups=frozenset({"Volkswagen"}))

    assert state["a1"]["status"] == "active"
    assert "removed_date" not in state["a1"]


def test_incomplete_group_does_not_affect_other_brands():
    state = merge_into_state(
        {},
        [_listing("a1", 24500, "2026-07-20"), _listing("b1", 30000, "2026-07-20")],
        date(2026, 7, 22),
    )
    state["b1"]["brand"] = "Audi"
    state = merge_into_state(state, [], date(2026, 7, 25), incomplete_groups=frozenset({"Volkswagen"}))

    assert state["a1"]["status"] == "active"  # protected -- Volkswagen incomplete
    assert state["b1"]["status"] == "removed"  # Audi's scan was complete, so this is real


def test_incomplete_group_still_updates_listings_that_were_seen():
    state = merge_into_state({}, [_listing("a1", 24500, "2026-07-20")], date(2026, 7, 22))
    state = merge_into_state(
        state, [_listing("a1", 23000, "2026-07-20")], date(2026, 7, 25), incomplete_groups=frozenset({"Volkswagen"})
    )

    # re-seen listings still get their price/last_seen updated even though
    # the brand is flagged incomplete -- the exemption only applies to the
    # "wasn't seen at all" removal/aged_out determination
    assert state["a1"]["status"] == "active"
    assert state["a1"]["last_seen_date"] == "2026-07-25"
    assert state["a1"]["price_history"][-1]["price_bam"] == 23000


def test_incomplete_group_checked_against_subcategory_field_too():
    listing = _listing("a1", 900, "2026-07-20")
    del listing["brand"]
    listing["subcategory"] = "Kopacke"
    state = merge_into_state({}, [listing], date(2026, 7, 22))
    state = merge_into_state(state, [], date(2026, 7, 25), incomplete_groups=frozenset({"Kopacke"}))

    assert state["a1"]["status"] == "active"
