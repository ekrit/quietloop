"""Turns tracked listings into a ranked "what's worth importing" report.

This is the first pass at the actual decision-support layer the whole
project has been building toward (per-day scraping + state tracking was
always just the input). It's meant to be the data source for a future
website/browser extension that compares products and surfaces what pays
off to import into Bosnia for resale.

## What "worth importing" means here, and what it doesn't

There is no cross-border price data in this pipeline -- we only see what
things sell for *in Bosnia*, never what they'd cost to acquire elsewhere
to bring in. So this can't compute actual profit margin. What it *can*
measure, from the data we do have, is domestic demand strength: does a
given brand/subcategory's stock actually turn over, how fast, and does it
sell at asking price or does it need discounting first. That's a
legitimate proxy for "worth importing" (strong, fast, discount-free
demand is exactly what you want to be feeding inventory into) but it is a
proxy, not a margin calculation -- the report says this explicitly in its
output rather than pretending otherwise.

## The three signals, and why these three

- **Sell-through rate** = removed / (removed + aged_out). `removed` means
  a listing disappeared before its 45-day window ran out -- the best
  signal available for "this actually moved" (see storage.py; we can't
  distinguish sold from delisted-for-other-reasons without a working
  detail-page URL, a known limitation carried over from the car pipeline).
  `aged_out` means it just sat there past the window, unsold. This ratio
  is the core demand signal: high = this category's stock reliably turns
  over.
- **Speed** = median `days_listed` among `removed` listings. Two
  categories can have the same sell-through rate while one moves in a
  week and the other in six -- speed is what actually matters for
  inventory turnover/cash flow in an import-resale business, which is why
  the original car-tracking project was built around "sells fastest" in
  the first place.
- **Price firmness** = share of listings that never needed a price cut
  (`price_history` never shows a drop). Weak demand shows up as sellers
  discounting to move stock even when it eventually does sell -- firmness
  catches that even when sell-through rate looks fine.

Sell-through gets the most weight (0.5) because it's the most direct
"does this actually sell" signal; speed (0.3) and firmness (0.2) refine
that with *how well*. These weights are a first-pass judgment call, not
derived from anything -- expect to revisit them once there's enough
history to check whether they actually predict anything.

## Grouping granularity -- an honest gap

Cars are grouped by `brand`, which is a solid signal -- run.py tags it
authoritatively from which brand-specific search found the listing.
Every other vertical is grouped only by `subcategory` (e.g. "Rucni
Satovi", "Tene/Patike za zene") because there's no brand/model extraction
built for non-car listings yet -- so "watches" is one bucket covering
everything from Casio to Rolex, which is a much coarser signal than
cars' per-brand breakdown. Worth building real brand/model parsing per
vertical (title text matching, similar to parser.py's car `_guess_brand`)
before trusting cross-brand comparisons *within* a non-car vertical -- for
now this only supports comparing across subcategories/verticals, not
brands within one.

## Minimum sample size

A group's score is only computed once `removed + aged_out >= MIN_RESOLVED`
-- otherwise sell-through rate is noise (e.g. 1-for-1 looks identical to
a real 50% rate with 2 samples). Groups below that show up in the report
as `insufficient_data: true` with raw counts but no score, rather than
being silently dropped (a thin category is itself useful information --
it might just mean not enough days of tracking have passed yet).
"""
from __future__ import annotations

import json
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path

from . import config
from .categories import VERTICALS

MIN_RESOLVED = 5  # removed + aged_out needed before a sell-through rate means anything
MIN_GROUP_SIZE = 10  # total listings needed before a group is scored at all

SELL_THROUGH_WEIGHT = 0.5
SPEED_WEIGHT = 0.3
FIRMNESS_WEIGHT = 0.2

REPORT_PATH = config.DATA_DIR / "import_worthiness_report.json"


@dataclass
class GroupStats:
    group: str
    n: int
    active: int
    removed: int
    aged_out: int
    median_price_bam: float | None
    dealer_share: float | None
    sell_through_rate: float | None = None
    median_days_to_sell: float | None = None
    discount_rate: float | None = None
    insufficient_data: bool = False
    score: float | None = None


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def _had_price_drop(listing: dict) -> bool:
    history = listing.get("price_history") or []
    if len(history) < 2:
        return False
    prices = [h["price_bam"] for h in history if h.get("price_bam") is not None]
    return bool(prices) and min(prices) < prices[0]


def compute_group_stats(group: str, listings: list[dict]) -> GroupStats:
    n = len(listings)
    active = sum(1 for l in listings if l.get("status") == "active")
    removed = [l for l in listings if l.get("status") == "removed"]
    aged_out_count = sum(1 for l in listings if l.get("status") == "aged_out")

    prices = [l["price_bam"] for l in listings if l.get("price_bam") is not None]
    dealer_flags = [l.get("seller_type") == "dealer" for l in listings if l.get("seller_type")]

    stats = GroupStats(
        group=group,
        n=n,
        active=active,
        removed=len(removed),
        aged_out=aged_out_count,
        median_price_bam=_median(prices),
        dealer_share=(sum(dealer_flags) / len(dealer_flags)) if dealer_flags else None,
    )

    resolved = len(removed) + aged_out_count
    if n < MIN_GROUP_SIZE or resolved < MIN_RESOLVED:
        stats.insufficient_data = True
        return stats

    stats.sell_through_rate = len(removed) / resolved
    stats.median_days_to_sell = _median([l["days_listed"] for l in removed if l.get("days_listed") is not None])
    discount_flags = [_had_price_drop(l) for l in listings]
    stats.discount_rate = sum(discount_flags) / len(discount_flags) if discount_flags else None
    return stats


def _normalize(value: float, lo: float, hi: float) -> float:
    if hi == lo:
        return 0.5
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))


def score_groups(groups: list[GroupStats]) -> None:
    """Assigns `score` (0-100) in place, min-max normalized *within this
    list* -- see module docstring for why cross-vertical score comparisons
    are meaningful (it's a relative-to-peers score) but cross-vertical
    *brand* comparisons within non-car verticals are not (grouping is only
    by subcategory there)."""
    scoreable = [g for g in groups if not g.insufficient_data]
    if not scoreable:
        return

    sell_through_vals = [g.sell_through_rate for g in scoreable]
    # lower is better for speed, so invert after normalizing
    speed_vals = [g.median_days_to_sell for g in scoreable]
    firmness_vals = [1 - g.discount_rate for g in scoreable]

    st_lo, st_hi = min(sell_through_vals), max(sell_through_vals)
    sp_lo, sp_hi = min(speed_vals), max(speed_vals)
    fm_lo, fm_hi = min(firmness_vals), max(firmness_vals)

    for g in scoreable:
        st_norm = _normalize(g.sell_through_rate, st_lo, st_hi)
        sp_norm = 1 - _normalize(g.median_days_to_sell, sp_lo, sp_hi)  # faster = higher
        fm_norm = _normalize(1 - g.discount_rate, fm_lo, fm_hi)
        g.score = round(
            100 * (SELL_THROUGH_WEIGHT * st_norm + SPEED_WEIGHT * sp_norm + FIRMNESS_WEIGHT * fm_norm), 1
        )


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def analyze_cars() -> list[GroupStats]:
    state = _load_json(config.STATE_PATH)
    by_brand: dict[str, list[dict]] = {}
    for listing in state.values():
        brand = listing.get("brand") or "Unknown"
        by_brand.setdefault(brand, []).append(listing)
    groups = [compute_group_stats(brand, items) for brand, items in by_brand.items()]
    score_groups(groups)
    return sorted(groups, key=lambda g: (g.score is None, -(g.score or 0)))


def analyze_vertical(slug: str) -> list[GroupStats]:
    state_path = config.DATA_DIR / slug / "listings.json"
    state = _load_json(state_path)
    by_subcat: dict[str, list[dict]] = {}
    for listing in state.values():
        subcat = listing.get("subcategory") or "Unknown"
        by_subcat.setdefault(subcat, []).append(listing)
    groups = [compute_group_stats(subcat, items) for subcat, items in by_subcat.items()]
    score_groups(groups)
    return sorted(groups, key=lambda g: (g.score is None, -(g.score or 0)))


def generate_report() -> dict:
    report: dict = {"cars": [asdict(g) for g in analyze_cars()], "verticals": {}}

    vertical_summaries = []
    for vertical in VERTICALS:
        groups = analyze_vertical(vertical.slug)
        report["verticals"][vertical.slug] = {
            "name": vertical.name,
            "groups": [asdict(g) for g in groups],
        }
        scored = [g.score for g in groups if g.score is not None]
        if scored:
            vertical_summaries.append(
                {
                    "slug": vertical.slug,
                    "name": vertical.name,
                    "avg_score": round(statistics.mean(scored), 1),
                    "total_tracked": sum(g.n for g in groups),
                }
            )

    report["vertical_ranking"] = sorted(vertical_summaries, key=lambda v: -v["avg_score"])
    report["methodology_note"] = (
        "Scores rank domestic sell-through/speed/price-firmness -- a demand proxy, "
        "NOT a profit-margin calculation (no cross-border source-market price data "
        "exists in this pipeline). Cars are grouped by brand; every other vertical "
        "is grouped only by subcategory (no brand/model extraction built yet for "
        "non-car listings), so within-vertical brand comparisons aren't possible "
        "outside of cars. See scraper/analysis.py's module docstring for full detail."
    )
    return report


def save_report(report: dict) -> Path:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with REPORT_PATH.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, sort_keys=True)
    return REPORT_PATH


def main() -> None:
    report = generate_report()
    path = save_report(report)
    print(f"wrote {path}")
    print("Vertical ranking (avg score, higher = stronger domestic demand proxy):")
    for v in report["vertical_ranking"]:
        print(f"  {v['name']:<35} avg_score={v['avg_score']:>5.1f}  n={v['total_tracked']}")


if __name__ == "__main__":
    main()
