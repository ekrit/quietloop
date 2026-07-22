# olx.ba car scraper — research & plan

Goal: scrape car listings from olx.ba daily, for a curated set of brands, filtered to
higher-value cars (20,000 KM / ~€10,225 and up, mileage ≥ 50,000 km), to build a
dataset over a few months that answers: which models sell fastest, and at what price
are they worth importing and reselling. A website/dashboard on top of this data comes
later — this doc only covers the scraping approach, storage, and metrics.

**Scope filters (applied server-side via query params, not client-side after the fact):**
- Price ≥ 20,000 KM
- Mileage ≥ 50,000 km (`kilometra-a_min=50000`)
- Sorted by publish date, newest first
- Publish date within the last 45 days — older listings are out of scope entirely,
  not just deprioritized. This bounds the whole dataset to a rolling 45-day window,
  which also happens to make the daily crawl cheaper (see §2).

**Caveat up front:** this sandbox's network policy blocks outbound requests to
`olx.ba` entirely (confirmed 403 at the proxy level, not a site anti-bot response) —
I could not browse the live site or view its HTML/DOM directly. Everything below about
URL structure and IDs comes from public search-engine results (cached OLX search-result
URLs) plus general knowledge of how OLX Group sites are typically built. The items
under "Needs live verification" must be checked by actually running requests against
the site (from your machine, or a future session with network access) before relying
on them.

## 1. What we know about the site

Confirmed via search-indexed URLs (real olx.ba search links that Google/Bing had
crawled):

- Cars live under `category_id=18` (top-level "Automobili"): `olx.ba/pretraga?category_id=18`
- Brand/model filtering uses numeric IDs, e.g. `brand=64` = Opel, `brand=57` = MG,
  combined with `models=<id>` for a specific model.
- The full filter set on `/pretraga` includes (params seen in real URLs):
  - `godiste_min` / `godiste_max` — year range
  - `kilometra-a_min` / `kilometra-a_max` — mileage range (km)
  - `kubikaza_min` / `kubikaza_max` — engine displacement (cc)
  - `konjskih-snaga_min` / `konjskih-snaga_max` — power (HP)
  - `kilovata-kw_min` / `kilovata-kw_max` (also seen as `kw-kilovata-_min/max`) — power (kW)
  - `gorivo_select` — fuel type
  - `transmisija_select` — transmission
  - `pogon_select` — drivetrain
  - `boja_select` — color
  - `broj-vrata_select` — door count
  - `stanje` — condition
  - `registrovan-do_select` — registered-until
  - `kanton` / `mjesto` — canton / city/location
  - `trazilica` — free-text search
  - there's also a price filter param in the query string (not fully confirmed by
    label — likely `v_m`/`v_b` min/max or a `cijena_min/max` pair; **needs live
    verification**, but worth using directly instead of fetching everything and
    filtering client-side)
  - a sort param almost certainly exists (results pages need some default order) —
    **needs live verification**: the exact param/value for "newest published first"
    (e.g. `sort=newest` / `orderby=datum_desc` — guessing the shape, not the name)
- There is a separate, apparently newer/related listing surface at `olx.ba/vozila`
  ("PIK.ba" branded — new/used vehicles, cars, motorcycles, trucks) — worth checking
  whether this is the same backend as `/pretraga?category_id=18` or a distinct
  vertical with its own structure.
- An **official OLX API** exists at `api-documentation.olx.ba`, with `Listings`,
  `Categories`, and `Users` resources. From indexed doc snippets: listings expose
  `id, type, title, slug, description, price, display_price, location (coords),
  status, attributes[]` where attributes are `{id, value}` pairs like Year, Fuel
  type, Mileage, Power, Cubic Capacity; categories expose `show_price`,
  `show_brand`, `show_condition`, `show_map` flags. Auth is Bearer-token based.
  This reads like a **partner/seller integration API** (for pushing your own
  listings into OLX, e.g. from a dealer's inventory system) rather than a public
  search API for arbitrary third-party queries — but this needs direct
  confirmation (sign up for a key, check if a GET on listings-by-category works
  without a token, check ToS on what a key permits).

### Needs live verification (do this first, from a machine with real access)

1. Fetch `https://olx.ba/robots.txt` and read it — don't assume permissive rules.
2. View-source a `/pretraga?category_id=18` results page: is it plain server-rendered
   HTML, or does it embed a JSON state blob (`__NEXT_DATA__`, Nuxt `__NUXT__`, or
   similar)? If a JSON blob is present, parsing that is far more robust than
   scraping DOM/CSS, and survives markup redesigns.
3. Confirm the exact price-filter query param name and units (KM, presumably).
4. Resolve numeric `brand=` IDs for our target brands (Mercedes-Benz, Škoda, Audi,
   Volkswagen, Porsche, BMW — see §5) by loading each brand's filter page once and
   reading the `brand=` value back from the URL/response.
5. Check whether `api-documentation.olx.ba`'s listing-read endpoints work without
   auth, and what their ToS say about automated read access — if a documented,
   sanctioned read API exists, prefer it over HTML scraping outright.
6. Confirm the "sort by newest" order is actually keyed on **original publish
   date**, not on a "last bumped/renewed" date. Many classifieds sites let
   sellers pay/click to bump a stale listing back to the top — if the sort key
   is bump-date, an old listing could resurface above genuinely new ones, which
   would break both the 45-day cutoff (a bumped 90-day-old listing could look
   "new") and the early pagination-stop described in §2. If the site exposes
   both dates, capture the true publish date on the listing itself rather than
   trusting page position alone.

## 2. Recommended scraping approach

**Primary: scrape the public `/pretraga` search-results pages**, using the filter
query params above to request only what we want server-side (category=cars, brand
in our watchlist, price ≥ 20,000 KM, mileage ≥ 50,000 km) rather than pulling
everything and filtering after — smaller payloads, fewer requests, less load on
their servers.

**Daily crawl is bounded by the 45-day window, not a full re-crawl:** sort results
by publish date descending and paginate from page 1; stop as soon as a page's
listings cross the 45-day-old boundary (pending the bump-vs-publish-date check in
§1 item 6) — no need to keep paging past that point since anything older is out of
scope by definition. This has two effects:
- It naturally re-checks every listing currently inside the window every day (for
  price changes and for disappearance/removal), since they all still fall within
  the paginated range until they age out — so removal-detection still works
  without a full-site crawl.
- Total daily volume is capped at whatever fits in a 45-day rolling window for our
  brand+price+mileage filter, not the site's all-time total — much cheaper than
  paging through everything, and the cost stays roughly flat over time instead of
  growing as the dataset accumulates.
- When a still-active listing finally ages past 45 days, record it as `aged_out`,
  **not** `removed` — we genuinely don't know if it sold after that point, and
  conflating "fell out of scope" with "actually gone" would quietly corrupt the
  days-on-market metric (see §5).

- If the results page embeds a JSON blob (likely, per most modern OLX-family sites),
  parse that directly — one clean object per listing, no brittle CSS selectors.
- If it's pure server HTML, fall back to a targeted HTML parser (BeautifulSoup/lxml)
  built around the listing-card structure, isolated in its own module so it's the
  one thing to fix when the site's markup changes.
- Only hit individual listing *detail* pages when something changed (new listing,
  or a price move detected in the search-results summary) — the summary card
  already carries most of the metrics we care about (title, price, year, mileage,
  location, thumbnail count), so full detail fetches should be the minority of
  requests.

**Politeness / risk-reduction (non-negotiable, and check ToS against these before
running for real):**
- Respect robots.txt once actually read (see §1).
- One request thread, 2–4s delay between requests, run once/day — this is a
  research project, not a real-time feed, so there's no reason to hammer it.
- Identify with a normal desktop-browser User-Agent; don't spoof anything beyond that.
- Cache aggressively: never re-fetch a detail page for a listing whose price and
  status haven't changed since yesterday.
- Build in a circuit-breaker: if response codes turn hostile (403/429 spike), stop
  and back off rather than retry aggressively.

**Scheduling:** run as a scheduled **GitHub Actions workflow** in this repo
(`schedule: cron`), committing each day's output back to `data/`. This fits a
few-months research project well — free, versioned (every day's dataset is a diff
in git history, so no separate backup story), and needs no server. Alternative is a
local cron job if you'd rather run it on your own machine and just sync results —
happy to set up either, but GitHub Actions is the lower-maintenance default.

## 3. Storage design (local JSON, DB comes later)

Two kinds of files, both plain JSON — no DB needed yet at this volume (a few
hundred qualifying listings/month across ~6 brands):

```
data/
  raw/
    2026-07-22.json      # full daily snapshot, exactly what was scraped that day
    2026-07-23.json
    ...
  listings.json           # one record per unique listing_id, the "state" table
```

- `data/raw/YYYY-MM-DD.json` — append-only audit trail, one file per day, never
  mutated after the fact. Useful for replaying/debugging and for recomputing
  metrics later if the schema evolves.
- `data/listings.json` — keyed by listing id, updated in place every day:
  lifecycle fields (`first_seen_date`, `last_seen_date`, `status`) get updated,
  and a `price_history` array gets a new entry only when price actually changes.
  This is the file the future website/dashboard would actually read.

This is intentionally simple (no SQLite yet, per your "that's for later") — plain
JSON is easy to `git diff`, easy to load into pandas, and migrating to a real DB
later is a separate, independent step that won't require touching the scraper.

## 4. Listing schema — proposed fields

```jsonc
{
  "id": "olx-12345678",              // olx.ba listing id, stable identity
  "url": "https://olx.ba/artikal/...",
  "brand": "Volkswagen",
  "model": "Passat",                 // parsed from title/attributes
  "variant": "2.0 TDI Highline",      // best-effort free text, unstructured
  "title": "VW Passat B8 2.0 TDI ...",

  "price_bam": 24500,
  "price_eur": 12527,                // derived, fixed peg 1 EUR = 1.95583 BAM
  "price_per_km": 0.31,              // derived: price / mileage_km

  "year": 2018,
  "mileage_km": 178000,
  "fuel_type": "Diesel",
  "transmission": "Manual",
  "power_kw": 110,
  "power_hp": 150,
  "engine_ccm": 1968,
  "drivetrain": "FWD",
  "body_type": "Sedan",
  "doors": 4,
  "color": "Grey",

  "registered_until": "2027-03",     // BiH-specific: registration validity
  "customs_paid": true,               // "carina placena" — critical for import math
  "first_owner": false,
  "damage_flag": false,               // parsed from title/description keywords

  "seller_type": "private",           // private vs dealer/salon
  "location_city": "Sarajevo",
  "location_canton": "KS",

  "photo_count": 14,
  "description_length": 320,

  "published_date": "2026-07-20",     // olx.ba's own publish date — the true
                                       // start of the clock for days_listed
  "first_seen_date": "2026-07-22",    // when WE first scraped it (bookkeeping only)
  "last_seen_date": "2026-07-30",
  "days_listed": 10,                   // (removed_date or today) - published_date
  "status": "active",                 // active | removed | aged_out
  "price_history": [
    { "date": "2026-07-22", "price_bam": 25500 },
    { "date": "2026-07-28", "price_bam": 24500 }
  ],

  "scraped_at": "2026-07-22T06:00:00Z"
}
```

## 5. Metrics that actually matter for "what sells fastest / what's worth importing"

The core question is liquidity vs. price, per brand+model+price-bracket:

- **Days on market (`days_listed`)** — the headline metric. Computed from
  `published_date` (olx.ba's own timestamp, not our scrape date) to the day the
  listing disappeared from search results. Two caveats:
  - A disappearance isn't proof of a sale (could be a manual pull, expiry, or a
    repost) — flag this as a proxy, not ground truth.
  - **`aged_out` is out of scope, not a data problem to solve:** a listing still
    active after 45 days simply didn't sell fast enough to be a candidate worth
    importing — that's the whole point of the cutoff. Record it as `aged_out`
    (distinct from `removed`) purely so it doesn't get miscounted as a fast sale;
    beyond that, drop it from consideration entirely. No survival-analysis
    treatment needed — slow movers aren't part of what this dataset is for.
- **Repost detection** — same seller + near-identical title/price reappearing
  within days of "disappearing" biases days-on-market downward-then-upward; worth
  a simple heuristic (match on seller + model + mileage±small delta) to exclude
  reposts from the "sold" bucket rather than double counting.
- **Sell-through rate per model/bracket** — % of listings in a given
  brand+model+price-bracket that disappear within N days (e.g. 14/30/60) — a
  cleaner cross-model comparison than raw days-on-market once you have enough
  volume.
- **Price drop behavior** (`price_history`) — how often and how much sellers
  discount before a listing disappears; a model that routinely sells with no
  discounting is a stronger "worth importing at asking price" signal than one that
  always drops 10%+ first.
- **Price vs. mileage vs. year** — per model, this is what tells you if a specific
  listing is under- or over-priced relative to comparable ones — the core signal
  for "what to buy to resell."
  `price_per_km` and a simple year/mileage-adjusted price band per model are
  enough to start; a regression can come later once there's more data.
- **Volume per model** — how many qualifying (≥20k KM) listings appear per model
  per month — low volume means any conclusions are noisy; worth tracking so the
  future dashboard can flag "not enough data yet" per model.

## 6. Suggested initial watchlist

Your list (Mercedes-Benz, Škoda, Audi, Volkswagen, Porsche) plus:

- **BMW** — directly cross-shopped against Mercedes/Audi in this price segment in
  the Balkans; leaving it out would create a blind spot in the core comparison.
- Optional second tier, add only if volume looks thin on the core list:
  **Volvo** (XC60/XC90) and **Land Rover/Range Rover** — common higher-end imports
  in BiH, smaller volume but relevant if you're specifically hunting luxury SUVs.

Within each brand, the models actually worth watching for the 20k+ KM bracket in
this market are the higher trims/newer years — e.g. VW Passat (B8)/Tiguan/Touareg,
Škoda Superb/Kodiaq, Audi A4/A6/Q5/Q7, Mercedes C/E-Class/GLC/GLE, Porsche
Macan/Cayenne/Panamera, BMW 5-Series/X3/X5. Base-trim older cars from these brands
mostly won't clear 20k KM, so the brand+price filter largely self-selects the
right segment — no need for a separate model-tier whitelist up front.

## 7. Repo layout for this stage

```
data/
  raw/            # daily snapshots (created)
  listings.json   # state table (created on first run)
schema/
  car_listing.schema.json   # JSON Schema for the record shape in §4 (added)
docs/
  RESEARCH.md     # this file
```

No scraper code yet — deliberately, since I can't validate selectors/JSON-blob
structure against the live site from this sandbox. Next step once the approach
above is confirmed: implement `scraper.py` + the GitHub Actions workflow, ideally
in a session/environment that can actually reach olx.ba to verify parsing against
real pages before it runs unattended on a schedule.
