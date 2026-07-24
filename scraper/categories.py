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

**Price thresholds** (2026-07-24: raised from the original first-pass
numbers per explicit feedback -- a 200 KM bike or 30 KM clothing item is
not what "worth importing" means here). Still judgment calls, not derived
from anything, same as before -- expect further tuning once more listing
volume has accumulated at these new floors.

**Brand/model extraction** (added 2026-07-24, see scraper/brand_matching.py):
none of these categories have a reliable structured brand field -- a live
check of the phones category's own filter-attribute schema
(`state.search.attributes`) turned up 27 real attributes (RAM, storage,
camera, color, etc.) but no brand/manufacturer field at all, and
`brand_id` on individual listings is only sometimes populated. So each
Vertical carries its own `known_brands` list, matched against listing
titles the same way cars' `_guess_brand` always has -- see
brand_matching.py's module docstring for the full reasoning and caveats.
`known_brands` lists below are a reasonable-effort pass at each category's
real, common brands in this market, not exhaustive.
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
    known_brands: list[str] = field(default_factory=list)
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
    # instead of fixing the truncation). Superseded in practice by the
    # incomplete_groups mechanism (storage.py) which makes the exact cap
    # value a runtime/completeness tradeoff rather than a correctness one --
    # see docs/RESEARCH.md §6b/§10.1.
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
        min_price_bam=1500,  # was 500
        subcategories=[SubCategory("Bicikli", 22)],
        known_brands=[
            "Specialized", "Trek", "Giant", "Scott", "Cannondale", "Cube",
            "Bianchi", "Cervelo", "Orbea", "Focus", "Ghost", "Merida",
            "BMC", "KTM", "Kona", "Bulls", "Haibike", "Capriolo", "Felt",
            "Cross", "Author", "Drag", "Ideal", "Rockrider", "Btwin",
        ],
    ),
    Vertical(
        name="PCs & Laptops",
        slug="computers",
        min_price_bam=1500,  # was 1000
        subcategories=[
            SubCategory("Laptopi", 39),
            SubCategory("Desktop Racunari", 38),
        ],
        known_brands=[
            "Lenovo", "Dell", "Hewlett Packard", "HP", "Asus", "Acer",
            "Apple", "MacBook", "MSI", "Toshiba", "Fujitsu", "Gigabyte",
            "Razer", "Alienware", "Microsoft", "Samsung", "NZXT", "Corsair",
        ],
    ),
    Vertical(
        name="Expensive Clothing",
        slug="clothing",
        min_price_bam=400,  # was 150
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
        known_brands=[
            "Michael Kors", "Louis Vuitton", "Ralph Lauren", "Tommy Hilfiger",
            "Calvin Klein", "Under Armour", "New Balance", "Valentino",
            "Balenciaga", "Alexander McQueen", "Salvatore Ferragamo",
            "Nike", "Adidas", "Puma", "Reebok", "Converse", "Vans",
            "Gucci", "Prada", "Versace", "Armani", "Hugo Boss", "Burberry",
            "Chanel", "Dior", "Fendi", "Zara", "Lacoste", "Guess", "ECCO",
            "Timberland", "Clarks", "Geox", "Diesel", "Levi's", "Levis",
        ],
    ),
    Vertical(
        name="Sports, Ski & Outdoor Equipment",
        slug="sports",
        min_price_bam=500,  # was 200
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
        known_brands=[
            "Salomon", "Atomic", "Head", "Rossignol", "Fischer", "Nordica",
            "Dynastar", "Elan", "Volkl", "The North Face", "Columbia",
            "Patagonia", "Arc'teryx", "Jack Wolfskin", "Quechua", "Decathlon",
            "Nike", "Adidas", "Puma", "Under Armour", "Wilson", "SportsArt",
            "Gym80", "Pure Kraft",
        ],
    ),
    Vertical(
        name="Mobile Phones",
        slug="phones",
        min_price_bam=800,  # was 500
        subcategories=[SubCategory("Mobiteli", 31)],
        known_brands=[
            "Samsung", "Apple", "iPhone", "Xiaomi", "Huawei", "Honor",
            "OnePlus", "Oppo", "Vivo", "Nokia", "Sony", "LG", "Motorola",
            "Google Pixel", "Realme", "ZTE", "Alcatel",
        ],
    ),
    Vertical(
        name="Watches",
        slug="watches",
        min_price_bam=600,  # was 300
        subcategories=[SubCategory("Rucni Satovi", 244)],
        known_brands=[
            "Rolex", "Omega", "Audemars Piguet", "Patek Philippe", "Cartier",
            "Tag Heuer", "Longines", "Hublot", "Breitling", "Casio", "Seiko",
            "Citizen", "Tissot", "IWC", "Swatch", "Fossil", "Timex",
        ],
    ),
    Vertical(
        name="Gaming Consoles",
        slug="consoles",
        min_price_bam=400,  # was 300
        subcategories=[SubCategory("Konzole", 292)],
        known_brands=["Sony", "PlayStation", "Microsoft", "Xbox", "Nintendo", "Sega", "Atari"],
    ),
    Vertical(
        name="Tablets",
        slug="tablets",
        min_price_bam=600,  # was 400
        subcategories=[SubCategory("Tablet PCs", 1495)],
        known_brands=["Apple", "iPad", "Samsung", "Huawei", "Lenovo", "Xiaomi", "Microsoft Surface", "Amazon Fire", "Asus"],
    ),
    Vertical(
        name="Smartwatches",
        slug="smartwatches",
        min_price_bam=400,  # was 300
        subcategories=[SubCategory("Smartwatch", 2076)],
        known_brands=["Apple", "Samsung", "Garmin", "Huawei", "Xiaomi", "Fitbit", "Amazfit", "Sigma", "Fossil", "Polar", "Suunto"],
    ),
    Vertical(
        name="Digital Cameras",
        slug="cameras",
        min_price_bam=600,  # was 300
        subcategories=[SubCategory("Digitalni fotoaparati", 112)],
        known_brands=["Canon", "Nikon", "Sony", "Fujifilm", "Panasonic", "Olympus", "Leica", "Pentax", "GoPro", "DJI", "Kodak"],
    ),
]
