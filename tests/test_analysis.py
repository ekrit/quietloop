from scraper.analysis import (
    MIN_GROUP_SIZE,
    MIN_RESOLVED,
    compute_group_stats,
    score_groups,
)


def _listing(id_, status, price_bam=1000, days_listed=10, price_history=None, seller_type="private"):
    return {
        "id": id_,
        "status": status,
        "price_bam": price_bam,
        "days_listed": days_listed,
        "price_history": price_history or [{"date": "2026-07-01", "price_bam": price_bam}],
        "seller_type": seller_type,
    }


def _padded_group(n_total, removed, aged_out, **kwargs):
    """Build a group with exactly `removed` removed + `aged_out` aged_out
    listings, padded with active ones up to n_total, so tests can control
    both n and resolved-count independently."""
    listings = []
    for i in range(removed):
        listings.append(_listing(f"r{i}", "removed", **kwargs))
    for i in range(aged_out):
        listings.append(_listing(f"a{i}", "aged_out", **kwargs))
    for i in range(n_total - removed - aged_out):
        listings.append(_listing(f"x{i}", "active", **kwargs))
    return listings


def test_below_min_group_size_is_insufficient():
    listings = _padded_group(MIN_GROUP_SIZE - 1, removed=3, aged_out=3)
    stats = compute_group_stats("g", listings)
    assert stats.insufficient_data
    assert stats.score is None
    assert stats.n == MIN_GROUP_SIZE - 1  # raw counts still populated


def test_below_min_resolved_is_insufficient_even_with_enough_listings():
    listings = _padded_group(MIN_GROUP_SIZE + 10, removed=1, aged_out=1)  # resolved=2 < MIN_RESOLVED
    stats = compute_group_stats("g", listings)
    assert stats.insufficient_data
    assert stats.score is None


def test_sufficient_data_computes_sell_through_and_speed():
    listings = _padded_group(20, removed=6, aged_out=4, days_listed=8)
    stats = compute_group_stats("g", listings)
    assert not stats.insufficient_data
    assert stats.sell_through_rate == 6 / 10
    assert stats.median_days_to_sell == 8


def test_price_drop_detected_from_history():
    listings = _padded_group(MIN_GROUP_SIZE, removed=3, aged_out=2)
    # give one removed listing an actual price drop
    listings[0]["price_history"] = [
        {"date": "2026-07-01", "price_bam": 1200},
        {"date": "2026-07-10", "price_bam": 1000},
    ]
    stats = compute_group_stats("g", listings)
    assert stats.discount_rate == 1 / MIN_GROUP_SIZE


def test_score_groups_ranks_higher_sell_through_higher():
    strong = compute_group_stats("strong", _padded_group(20, removed=9, aged_out=1, days_listed=3))
    weak = compute_group_stats("weak", _padded_group(20, removed=1, aged_out=9, days_listed=30))
    score_groups([strong, weak])

    assert strong.score is not None and weak.score is not None
    assert strong.score > weak.score


def test_insufficient_data_groups_excluded_from_normalization():
    strong = compute_group_stats("strong", _padded_group(20, removed=9, aged_out=1))
    thin = compute_group_stats("thin", _padded_group(3, removed=1, aged_out=0))
    score_groups([strong, thin])

    assert strong.score is not None
    assert thin.score is None
    assert thin.insufficient_data
