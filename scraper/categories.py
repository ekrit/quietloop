"""Config for the multi-category testing expansion (2026-07-23 -> 2026-08-01).

Cars (config.py/run.py) are the proven, production pipeline and are left
untouched. This module is a *separate*, explicitly-labeled-as-testing
extension covering more verticals the user wants data on before deciding
whether any of them are worth pursuing for real: bicycles, PCs/laptops,
expensive clothing, sports/ski/outdoor equipment, mobile phones, watches,
gaming consoles, tablets, smartwatches, and digital cameras.

Real category IDs below came from a live "Debug fetch" run against
https://olx.ba/pretraga (state.search.aggregations.categories, including
one level of sub_categories) -- not guessed. See docs/RESEARCH.md §10.

Two of these four (clothing, sports) are each individually *larger* than
the entire "Vozila" (vehicles) category that forced cars into per-brand
querying in the first place (see docs/RESEARCH.md §6's postmortem: a
brand-agnostic sweep of ~78k vehicle listings hit an 800-page cap without
finishing). Odjeca i obuca alone is ~213k listings, Sportska oprema ~170k.
A flat sweep of either would almost certainly hit the same wall, so both
use a *subcategory watchlist* (same shape as BRAND_WATCHLIST) instead of
sweeping their whole parent tree -- narrowed to the subcategories that
actually carry expensive/premium items, skipping high-volume-but-cheap
ones (t-shirts, generic toys, phone cases, etc).

Price thresholds below are first-pass judgment calls, NOT user-specified
(unlike cars' 25,000 KM, which came directly from the user). They exist so
this testing period produces data at all; expect to tune them once real
numbers come back, the same way the car thresholds moved 20k -> 25k KM
after seeing real listing volume.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .config import BASE_URL, DATA_DIR, REPO_ROOT, SEARCH_PATH  # noqa: F401 (BASE_URL/SEARCH_PATH used by multi_run)

TESTING_END_DATE = "2026-08-01"  # inclusive last day this is meant to run; see docs/RESEARCH.md §10


@dataclass
class SubCategory:
    name: str
    category_id: int


@dataclass
class Vertical:
    name: str
    slug: str  # data/<slug>/...
    min_price_bam: int
    subcategories: list[SubCategory] = field(default_factory=list)
    # CONFIRMED BUG 2026-07-24 (same mechanism as config.py's
    # MAX_PAGES_PER_BRAND incident, see docs/RESEARCH.md §6b): the second-
    # ever verticals run (run #4) showed 21 of 27 subcategories hitting
    # exactly page 40 -- this cap -- with no "stopping" log line, i.e.
    # truncated mid-scan rather than reaching their own 45-day-window stop.
    # "Kopacke" (football boots) went from 179 tracked to 179 REMOVED (100%)
    # as a result -- every previously-seen listing shifted past page 40
    # between the two scrapes and got wrongly marked gone. Raised 40 -> 120
    # as a first, moderate increase (not as large a multiple as the car
    # fix's 60->250, since here ~21 subcategories could all need more pages
    # *simultaneously* in one job run, unlike cars where only 1-2 brands
    # were affected -- a too-generous cap risks blowing the job timeout
    # instead of fixing the truncation). Needs re-validating against a real
    # run same as the car fix was; may need another iteration if many
    # subcategories still hit 120.
    max_pages_per_subcategory: int = 120
    consecutive_empty_pages_to_stop: int = 2

    @property
    def state_path(self) -> Path:
        return DATA_DIR / self.slug / "listings.json"

    @property
    def raw_dir(self) -> Path:
        return DATA_DIR / self.slug / "raw"


VERTICALS: list[Vertical] = [
    Vertical(
        name="Bicycles",
        slug="bicycles",
        min_price_bam=500,
        subcategories=[SubCategory("Bicikli", 22)],
    ),
    Vertical(
        name="PCs & Laptops",
        slug="computers",
        min_price_bam=1000,
        subcategories=[
            SubCategory("Laptopi", 39),
            SubCategory("Desktop Racunari", 38),
        ],
    ),
    Vertical(
        name="Expensive Clothing",
        slug="clothing",
        min_price_bam=150,
        subcategories=[
            SubCategory("Tene/Patike za muskarce", 526),  # men's sneakers
            SubCategory("Tene/Patike za zene", 490),  # women's sneakers
            SubCategory("Jakne kaputi i mantili za zene", 474),  # women's coats/jackets
            SubCategory("Jakne kaputi i mantili za muskarce", 511),  # men's coats/jackets
            SubCategory("Torbe i ruksaci za zene", 542),  # women's bags/backpacks
            SubCategory("Muske torbe i torbice", 621),  # men's bags
            SubCategory("Cizme za zene", 488),  # women's boots
            SubCategory("Cipele i Gleznjace za zene", 486),  # women's shoes/ankle boots
            SubCategory("Stikle za zene", 1892),  # women's heels
        ],
    ),
    Vertical(
        name="Sports, Ski & Outdoor Equipment",
        slug="sports",
        min_price_bam=200,
        subcategories=[
            SubCategory("Skije", 1810),  # skis
            SubCategory("Ski pancerice", 1927),  # ski boots
            SubCategory("Jakne za planinu", 1830),  # mountain/ski jackets
            SubCategory("Tegovi i bucice", 1291),  # weights/dumbbells
            SubCategory("Ostala oprema za trening", 1295),  # training equipment
            SubCategory("Ostale sprave za trening", 1301),  # training machines
            SubCategory("Kopacke", 1349),  # football boots
            SubCategory("Fudbalski dresovi", 1347),  # football jerseys
            SubCategory("Ostala kamp oprema", 1278),  # hiking/camping gear -- closest real subcategory to "hiking gear"
        ],
    ),
    Vertical(
        name="Mobile Phones",
        slug="phones",
        min_price_bam=500,
        subcategories=[SubCategory("Mobiteli", 31)],
    ),
    Vertical(
        name="Watches",
        slug="watches",
        min_price_bam=300,
        subcategories=[SubCategory("Rucni Satovi", 244)],
    ),
    Vertical(
        name="Gaming Consoles",
        slug="consoles",
        min_price_bam=300,
        subcategories=[SubCategory("Konzole", 292)],
    ),
    Vertical(
        name="Tablets",
        slug="tablets",
        min_price_bam=400,
        subcategories=[SubCategory("Tablet PCs", 1495)],
    ),
    Vertical(
        name="Smartwatches",
        slug="smartwatches",
        min_price_bam=300,
        subcategories=[SubCategory("Smartwatch", 2076)],
    ),
    Vertical(
        name="Digital Cameras",
        slug="cameras",
        min_price_bam=300,
        subcategories=[SubCategory("Digitalni fotoaparati", 112)],
    ),
]
