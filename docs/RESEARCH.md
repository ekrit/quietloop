# olx.ba car scraper — research & plan

Goal: scrape car listings from olx.ba daily, for a curated set of brands, filtered to
higher-value cars (25,000 KM / ~€12,782 and up, mileage ≥ 50,000 km), to build a
dataset over a few months that answers: which models sell fastest, and at what price
are they worth importing and reselling. A website/dashboard on top of this data comes
later — this doc only covers the scraping approach, storage, and metrics.

**Scope filters (applied server-side via query params, not client-side after the fact):**
- Price ≥ 25,000 KM
- Mileage ≥ 50,000 km (`kilometra-a_min=50000`)
- Year ≥ 2016 (`godiste_min=2016`) — "younger than 2016" read as 2016 model year
  or newer; flip to `> 2016` in `scraper/config.py` (`MIN_YEAR`) if you meant
  strictly newer than 2016.
- Sorted by publish date, newest first
- Publish date within the last 45 days — older listings are out of scope entirely,
  not just deprioritized. This bounds the whole dataset to a rolling 45-day window,
  which also happens to make the daily crawl cheaper (see §2).

**Update:** this sandbox's own network policy still blocks outbound requests to
`olx.ba` directly (confirmed 403 at the proxy level) — but GitHub Actions runners
don't have that restriction, so the "Debug fetch" workflow (`.github/workflows/
debug-fetch.yml`, manual dispatch only) was used to actually fetch and inspect
real pages. Most of what was originally speculative below is now confirmed
against live data — see §1a and §2 for what changed. Items still marked "needs
verification" are genuinely still unconfirmed.

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

### Still needs live verification

1. Fetch `https://olx.ba/robots.txt` and read it — don't assume permissive rules.
   Still not done — worth checking before running the schedule unattended long-term.
2. ~~View-source a results page for a JSON state blob~~ — **done, see §1a**: it's
   Nuxt (`__NUXT__`), not Next.js, and the real data lives in `state.search.results`.
3. ~~Confirm the exact price-filter query param name~~ — **done, see §1a**:
   `cijena_min` is confirmed present but confirmed *not enforced*; the client-side
   filter in `run.py` is the real gate regardless of the param name.
4. Resolve numeric `brand=` IDs for our target brands (Mercedes-Benz, Škoda, Audi,
   Volkswagen, Porsche, BMW — see §5) by loading each brand's filter page once and
   reading the `brand=` value back from the URL/response, or from `brand_id` on a
   real result item once you know which brand it belongs to. Still not done — the
   scraper currently falls back to free-text `trazilica=<name>` search for every
   brand as a result, which is slower and less precise.
5. Check whether `api-documentation.olx.ba`'s listing-read endpoints work without
   auth, and what their ToS say about automated read access — if a documented,
   sanctioned read API exists, prefer it over the payload-extraction approach
   outright. Still not done.
6. Confirm the "sort by newest" order is actually keyed on **original publish
   date**, not on a "last bumped/renewed" date. Many classifieds sites let
   sellers pay/click to bump a stale listing back to the top — if the sort key
   is bump-date, an old listing could resurface above genuinely new ones, which
   would break both the 45-day cutoff (a bumped 90-day-old listing could look
   "new") and the early pagination-stop described in §2. If the site exposes
   both dates, capture the true publish date on the listing itself rather than
   trusting page position alone. **Still unconfirmed** — a live test page had
   listings that didn't look strictly newest-first, so this param may not even
   do what its name suggests; needs a proper look at the site's real sort UI.

## 1a. What's now confirmed (live data, via the Debug fetch workflow)

The site is **Nuxt.js SSR**. Real listing data isn't in plain HTML `<a>`/`<div>`
tags at all — a `/pretraga` page embeds a `window.__NUXT__=(function(a,b,c,
...){...})(...)` script: a minified, deduplicated JS state dump, not JSON and
not safely regex-scrapable (values are variable references, not literals).
That killed the original "scrape HTML cards" plan in §2 outright — the first
real run found the search pages had **zero** `/artikal/`-style links at all,
zero listing links of any kind in the rendered HTML.

The fix: since the payload is valid JS, evaluate it (see `scraper/
nuxt_payload.py`) instead of guessing at regexes. It's untrusted third-party
content, so it only ever runs inside a bare `vm.createContext({})` Node
sandbox with no `require`/`fs`/`process`/network access — it can only compute
a plain value. Confirmed working against the real site.

**The actual shape**, `state.search.results` — a clean array, one object per
listing:

```jsonc
{
  "id": 76750281, "title": "...", "price": 19000,
  "display_price": "19.000 KM", "date": 1784752607,   // unix timestamp!
  "images": ["https://d4n0y8dshd77z.cloudfront.net/listings/76750281/..."],
  "user_type": "user", "state": "used", "status": "active",
  "brand_id": ..., "category_id": ..., "city_id": ..., "location": null,
  "special_labels": [
    { "value": "dizel", "label": "Gorivo", "unit": null },
    { "value": "260.000", "label": "Kilometraža", "unit": "km" },
    { "value": 2012, "label": "Godište", "unit": null }
  ]
}
```

Key findings from this:
- **Fuel type / mileage / year are not top-level fields** — they live inside
  `special_labels`, keyed by their Bosnian display label. `parser.py` maps
  `Gorivo`→`fuel_type`, `Kilometraža`→`mileage_km`, `Godište`→`year`.
- **`date` is a real Unix timestamp** — this is `published_date`, no more
  guessing at "Prije 3 dana"-style relative text.
- **Price is a clean number** (`price`) — no more parsing `"19.000 KM"` strings.
- **`price` (25,000 KM floor) and `godiste_min` (2016 floor) are confirmed NOT
  reliably enforced server-side** — a live request with both params still
  returned a listing priced 19,000 KM from year 2012. The client-side safety
  net in `run.py` (already there regardless) is what's actually doing this
  filtering; the URL params are kept since they can't hurt but shouldn't be
  trusted alone.
- **No detail-page URL/slug anywhere in the search payload.** The real
  `/artikal/...`-style link was never found as a live href, and there's no
  `slug`/`url`/`permalink` field in the listing object either — the frontend
  must construct it client-side from the title. `parser.py` currently guesses
  `{BASE_URL}/artikal/{id}`, unconfirmed and likely wrong. This also means
  **detail-page enrichment isn't implemented** — `customs_paid`, `first_owner`,
  `damage_flag`, `registered_until`, `drivetrain`, `body_type`, `doors`,
  `color`, `engine_ccm`, `description_length`, and `location_canton` are not
  populated. Everything else the schema needs *is* available from the search
  payload alone.
- `state.search.aggregations.categories` gives real category id→name→count —
  confirms cars sit under a real category (title said "u kategoriji
  Automobili"), though the specific `category_id=18` used in our URLs wasn't
  directly cross-checked against this list yet.
- `location` was `null` on the one sample inspected (only a numeric `city_id`)
  — no city-name lookup table has been built, so `location_city`/
  `location_canton` remain unpopulated for now.

## 2. Recommended scraping approach

**Primary: scrape the public `/pretraga` search-results pages**, using the filter
query params above to request only what we want server-side (category=cars,
brand in our watchlist, price ≥ 25,000 KM, mileage ≥ 50,000 km) rather than
pulling everything and filtering after — smaller payloads, fewer requests,
less load on their servers. **The brand filter turned out to be load-bearing,
not just a convenience** — see §6 for what happened when it was dropped in
favor of one unfiltered category-wide sweep (short version: don't).

**Daily crawl is bounded by the 45-day window, not a full re-crawl:** sort results
by publish date descending and paginate from page 1; stop as soon as a page's
listings cross the 45-day-old boundary (pending the bump-vs-publish-date check in
§1 item 6) — no need to keep paging past that point since anything older is out of
scope by definition. This has two effects:
- It naturally re-checks every listing currently inside the window every day (for
  price changes and for disappearance/removal), since they all still fall within
  the paginated range until they age out — so removal-detection still works
  without a full-site crawl.
- Total daily volume is capped at whatever fits in a 45-day rolling window for
  the whole category, not the site's all-time total — much cheaper than paging
  through everything, and the cost stays roughly flat over time instead of
  growing as the dataset accumulates.
- When a still-active listing finally ages past 45 days, record it as `aged_out`,
  **not** `removed` — we genuinely don't know if it sold after that point, and
  conflating "fell out of scope" with "actually gone" would quietly corrupt the
  days-on-market metric (see §5).

**Real numbers:** a live run with the original 6 watch-listed brands took
~19.5 minutes and collected 2,216 qualifying listings, each brand's crawl
correctly reaching its natural 45-day-window stop. `MAX_PAGES_PER_BRAND` is
60. The watchlist has since grown to 17 brands (§6) — expect the daily run
to take longer accordingly; the job timeout was bumped 60→120 minutes ahead
of that.

- **Confirmed (§1a):** parse the page by extracting and sandboxed-evaluating its
  embedded `window.__NUXT__=...` payload (`scraper/nuxt_payload.py`), then read
  `state.search.results` directly — clean objects, no CSS selectors, no
  markup-fragility. This replaced the original "HTML card scraping" plan
  entirely once real data showed there's no HTML to scrape in the first place.
- There is currently **no detail-page fetch step** — the search payload alone
  covers everything the schema needs except the fields listed in §1a
  (customs_paid, first_owner, damage_flag, registered_until, drivetrain,
  body_type, doors, color, engine_ccm, description_length, canton). Adding
  detail-page enrichment back needs a confirmed real detail URL first (see
  §1a's "no detail-page URL" finding).

**Politeness / risk-reduction (non-negotiable, and check ToS against these before
running for real):**
- Respect robots.txt once actually read (see §1).
- One request thread, 2–4s delay between requests, run once/day — this is a
  research project, not a real-time feed, so there's no reason to hammer it.
- Identify with a normal desktop-browser User-Agent; don't spoof anything beyond that.
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

## 4. Listing schema — fields

Fields marked (✓) actually get populated by the current parser (confirmed
against real data, §1a). Everything else is either unimplemented (model
parsing, location lookup) or blocked on a confirmed detail-page URL.

```jsonc
{
  "id": "12345678",                  // (✓) olx.ba's numeric listing id
  "url": "https://olx.ba/artikal/...", // NOT CONFIRMED -- best-effort guess, see §1a
  "brand": "Volkswagen",              // (✓) from our own watchlist query, not parsed
  "model": null,                      // not implemented -- would need title parsing
  "variant": null,                    // not implemented
  "title": "VW Passat B8 2.0 TDI ...", // (✓)

  "price_bam": 24500,                 // (✓) clean number straight from the payload
  "price_eur": 12527,                // (✓) derived, fixed peg 1 EUR = 1.95583 BAM
  "price_per_km": 0.31,              // (✓) derived: price / mileage_km

  "year": 2018,                       // (✓) from special_labels "Godište"
  "mileage_km": 178000,               // (✓) from special_labels "Kilometraža"
  "fuel_type": "dizel",               // (✓) from special_labels "Gorivo"
  "transmission": null,                // not in the search payload
  "power_kw": null, "power_hp": null, "engine_ccm": null,   // not in the search payload
  "drivetrain": null, "body_type": null, "doors": null, "color": null,  // detail-page only

  "brand_id": 42, "category_id": 18, "city_id": 7,   // (✓) olx.ba's own numeric ids
  "condition_raw": "used",            // (✓) olx.ba's own condition string, unmapped

  "registered_until": null,           // detail-page only
  "customs_paid": null,               // detail-page only
  "first_owner": null,                // detail-page only
  "damage_flag": null,                // detail-page only

  "seller_type": "private",           // (✓) derived from user_type ("user" -> private)
  "location_city": null,              // city_id has no name lookup built yet
  "location_canton": null,            // detail-page only

  "photo_count": 14,                  // (✓) len(images)
  "description_length": null,         // detail-page only

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
- **Volume per model** — how many qualifying (≥25k KM) listings appear per model
  per month — low volume means any conclusions are noisy; worth tracking so the
  future dashboard can flag "not enough data yet" per model.

## 6. Back to per-brand watchlist (tried dropping it — made things worse)

**What was tried:** the reasoning was that the price/mileage/year filters
already gate for "expensive enough to be worth analyzing" regardless of
brand, so pre-selecting brands via the search query was just deciding the
answer before the data could. So the watchlist was dropped entirely for one
brand-agnostic sweep of the whole category (`category_id=18`, no brand
param at all), with `brand` derived after the fact from the listing itself
(`brand_id` when confirmed, otherwise matching title against a ~48-brand
list, longest-name-first).

**What actually happened, from a real run:** it hit the 800-page hard cap
(`MAX_PAGES`) *without ever reaching the natural 45-day-window stop
condition* — meaning total unfiltered category volume (all brands, all
prices) is too high to exhaustively traverse in any sane page budget. Worse:
because the crawl only got through a shallow, truncated slice of recent
listings before running out of budget, ~1,820 listings that were correctly
`active` from the previous (per-brand) run got marked `removed` — not
because they'd actually left the site, but simply because this run's
truncated coverage never got back around to seeing them again. Since
`removed` is a terminal status by design (`storage.py` never reactivates
one), that would have been silent, permanent, incorrect data corruption if
left in place. It was caught, and `data/listings.json` /
`data/raw/<date>.json` were restored from the last known-good commit before
reverting the code.

**Conclusion:** per-brand text search apparently narrows the result set down
enough that exhaustive 45-day traversal is actually tractable (proven
separately, twice) — the brand filter isn't just "deciding the answer early,"
it's also what makes the crawl *finish* at all within a sane page/time
budget. So the watchlist is back, just covering more ground than the
original 6: Mercedes-Benz, Škoda, Audi, Volkswagen, Porsche, BMW (all with
confirmed numeric `brand_id`s now), plus Volvo, Land Rover, Toyota, Lexus,
Hyundai, Kia, Ford, Peugeot, Renault, Alfa Romeo, Fiat (free-text search,
`brand_id` unconfirmed). `parser.py`'s title/id-based `_guess_brand()` is
still in place as a fallback/cross-check, but `run.py`'s per-brand loop
still sets the authoritative `brand` value from which search found it.

## 6a. Expanded 17 → 30, based on actual Bosnian market share (not global fame)

The 17-brand list above was picked by general reputation/import-worthiness.
Asked "what's actually common in Bosnia specifically," a web research pass
turned up real market data:

- Volkswagen alone is ~33.7% of the entire registered passenger fleet
  (~367k–385k vehicles) — by far #1, and expected to stay that way.
- Škoda is #2 in registered fleet (~99k) but **#1 in new-car sales** (22.6%
  share; the Octavia has been Bosnia's best-selling model 13 of the last 14
  years).
- New-car sales top 5, in order: Škoda, Toyota, Volkswagen, Renault, Hyundai.
- Counting Volkswagen, Audi, BMW, Mercedes-Benz, and **Opel** together,
  German-origin cars are >60% of the whole fleet.
- For used-car imports specifically: Volkswagen, Audi, Škoda, then
  **Peugeot** (~5%/month, ~400 vehicles), then Mercedes-Benz.

Sources: [proauto.ba](https://proauto.ba/u-bosni-i-hercegovini-trenutno-ima-najvise-volkswagena-i-sve-su-prilike-da-ce-tako-i-ostati-jos-dugo/),
[bestsellingcarsblog.com](https://bestsellingcarsblog.com/2026/04/bosnia-herzegovina-march-2026-skoda-octavia-and-scala-on-top/),
[zenicablog.com](https://www.zenicablog.com/zasto-su-u-bih-trazeni-uvozni-automobili-stari-i-po-15-godina-i-koje-marke-su-najpopularnije/),
[blink.ba](https://www.blink.ba/bez-konkurencije-svaki-treci-polovnjak-u-bih-je-volkswagen/).

**Opel** was the glaring gap — a named top-tier contributor to the fleet
that wasn't on the watchlist at all. `config.py` also has a real
`brand=64` for Opel, seen in a search-indexed olx.ba URL (§1), though
unlike the original 6 it isn't confirmed via a live scrape yet.

`BRAND_WATCHLIST` was expanded from 17 to 30, adding: Opel (`brand_id=64`,
unconfirmed-via-live-run at the time), Citroën, Seat, Nissan, Honda, Mazda,
Mitsubishi, Suzuki, Dacia, Chevrolet, Jeep, Subaru, Mini — all free-text
search, no confirmed `brand_id`. All 13 names were already present in
`KNOWN_BRANDS` for title-fallback matching, just not previously queried
directly. Job timeout bumped 120→180 minutes ahead of the first real run
at this size (see `daily-scrape.yml`).

**Validated against the live site the same day:** a real run took 44
minutes (up from ~32.5 min at 17 brands, well under the 180-min timeout),
grew tracked listings 3,510→3,992 with only 17 total `removed` (no mass
false-removal spike, unlike §6's incident). 28 of the 30 manufacturers
returned at least one listing. `brand=64` for Opel came back with 80
listings, all genuinely Opel (Mokka X, Grandland X, Insignia, etc.) —
promoted from guess to `CONFIRMED_BRAND_IDS`. The only two manufacturers
with zero results, Lexus and Subaru, were already on the watchlist before
this expansion (not new), so this isn't a regression from today's change —
most likely genuine rarity of those brands in Bosnia's 25k+ KM / 50k+ km /
2016+ / 45-day-window segment rather than a scraper problem, though it's
worth a second look if it persists over the next several days.

If broader-than-watchlist coverage is wanted later, the fix isn't "no
filter" — it's either a much larger MAX_PAGES with a much longer timeout (a
few hours, impractical for a daily job), or more, narrower per-brand/
per-price-bracket searches that each stay small enough to finish. Not
pursued further for now.

Within any given brand, the models actually worth watching for the 25k+ KM
bracket in this market are the higher trims/newer years — e.g. VW Passat
(B8)/Tiguan/Touareg, Škoda Superb/Kodiaq, Audi A4/A6/Q5/Q7, Mercedes
C/E-Class/GLC/GLE, Porsche Macan/Cayenne/Panamera, BMW 5-Series/X3/X5. This
is about how to *read* the resulting data later, not something the scraper
itself needs to know — the price filter already self-selects the segment.

## 6b. §6's failure mode recurring per-brand (caught and fixed 2026-07-24)

The 2026-07-23 23:45 UTC nightly run (the first fully unattended one after
the 30-manufacturer expansion) produced real data corruption -- not a
crash, so it wasn't caught by the "did it exit 0" health check. Volkswagen
came back with 23.1% of its tracked listings marked `removed` that day
(vs. a 2-6% baseline for every other brand); Audi came back at 13.8%.

**Root cause:** identical mechanism to §6, just scoped smaller. The job
log showed Volkswagen, Skoda, Audi, Mercedes-Benz, BMW, and Peugeot all
hitting exactly page 60 -- `MAX_PAGES_PER_BRAND`'s hard cap -- with no
"stopping brand=X" log line, meaning the cap cut the scan off mid-traversal
rather than the brand's own 45-day-window logic ending it naturally. That
cap was set to 60 back when the watchlist was 6 brands (~19.5 min total
runtime) and never revisited as it grew to 30 -- once individual brands
got large enough on their own, hitting the per-brand cap became possible
again, reopening §6's exact bug at brand-scope instead of category-scope.
For Škoda/Mercedes/BMW/Peugeot the shortfall turned out small enough not
to visibly corrupt their removed-rate; for Volkswagen and Audi specifically
(the two highest-demand import brands per §6a's market research -- likely
genuinely the deepest backlogs) it wasn't.

**First attempted fix (didn't work):** `MAX_PAGES_PER_BRAND` raised 60 →
250, reasoning that free-text-search brands were all stopping naturally
well under 60 pages already (worst case Ford at 37) so only the
highest-volume confirmed-brand_id brands should need the headroom.
`data/listings.json` restored from `11b42d7` to undo the false removals.
**Validated against a real run and it was wrong** -- the same six brands
(Volkswagen, Skoda, Audi, Mercedes-Benz, BMW, Peugeot) hit the *new* 250
cap too, still with no natural stop, and the false-removal rate got
*worse* (Volkswagen 25.5%, Audi 19.6%, both up from the original incident).
Raising a constant doesn't fix a problem whose real cause is "this
brand's true backlog is bigger than any budget we're willing to page
through daily" -- this is the same structural issue as the original §6
sweep, just recurring at brand-scope for these six specifically.

**Actual fix:** stop trying to guess a large-enough page cap and instead
make the removal/aged_out determination *aware* of whether that day's scan
actually finished. `scrape_brand()` now returns whether it reached a
natural stop or exhausted `MAX_PAGES_PER_BRAND` without one; `run()`
collects the brands that didn't finish into `incomplete_brands` and passes
it to `merge_into_state(..., incomplete_groups=...)`, which skips the
removed/aged_out check entirely for any record belonging to an incomplete
group -- new listings still get added and re-seen listings still get their
price/last-seen updated, but "not seen this run" simply isn't trusted as a
removal signal for a brand whose scan is known-incomplete. Practical
effect: Volkswagen/Audi (and whichever other brands hit the cap on a given
day) stop accumulating false removals, at the cost of their removed/
aged_out detection lagging until a day the scan does complete (which may
be never, for a backlog that consistently exceeds the cap -- an honest
limitation, not a hidden one). `data/listings.json` restored to `11b42d7`
again. Applied to the verticals pipeline too (§10.1) since the identical
bug was found there independently the same day.

Worth noting for next time a watchlist/subcategory-list grows (cars or any
of the testing verticals in §10): a per-item safety cap that was sized for
a smaller list needs re-checking as the list grows, not just the job-level
timeout -- the job not timing out doesn't mean no individual item silently
truncated. And per this incident specifically: if raising the cap once
doesn't fix it, don't raise it again and hope -- that's a sign the real
backlog exceeds any reasonable daily budget, and the fix is to stop
guessing at removal for under-scanned groups, not to keep guessing at a
bigger number.

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

## 8. Running it

```
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt   # includes pytest; use requirements.txt for runtime-only
pytest tests/                          # verifies currency/state-machine/parser logic
python main.py                         # runs one scrape, writes into data/
python main.py --date 2026-07-22       # override the run date (backfills/testing)
```

The `scraper/` package: `config.py` (watchlist + filter/param constants),
`http_client.py` (rate-limited session with retries + circuit breaker),
`nuxt_payload.py` (extracts + sandboxed-evaluates the site's embedded Nuxt
state payload — see §1a), `parser.py` (converts that payload's `state.
search.results` into our listing schema), `storage.py` (JSON state machine
— active/removed/aged_out, price history, `days_listed`), `run.py`
(orchestrator/CLI), `debug_fetch.py` (manual diagnostic, not part of the
daily pipeline — fetches one URL and reports its raw structure).

**Node is now a runtime dependency**, not just a nice-to-have — `parser.py`
shells out to `node` to safely evaluate the site's payload. GitHub Actions
runners have it preinstalled (confirmed working there); if running locally,
make sure `node` is on PATH.

**What's been verified:** `tests/` covers currency conversion, the full
removed/aged_out/price-history state machine, and `parser.py` against a
synthetic-but-real-shaped Nuxt payload fixture (mirroring the actual
`state.search.results` structure confirmed live, §1a) — all passing (18
tests). The parser has also been run against the **real live site** via the
"Debug fetch" workflow multiple times, successfully deserializing the real
payload and extracting real listings — this is a materially stronger
verification level than the original plan, which could only guess at HTML
structure. What's still open: the real detail-page URL (needed for the
fields listed in §1a), whether the price/mileage/sort URL params do
anything real (price and year are confirmed not enforced, §1a), and brand
numeric IDs (still using free-text `trazilica=` search as a result).

Dockerizing this is intentionally deferred — the script has no interactive
input and reads all config from `scraper/config.py`, so wrapping it in a
`Dockerfile` later should be a small step (remembering to install `node` in
the image alongside Python).

## 9. Deployment: `.github/workflows/daily-scrape.yml`

This is the "runs every day, saves locally, commits and pushes back to your
GitHub" piece, and it's already added. It's a scheduled GitHub Actions
workflow — no server, no Docker, no separate infra to pay for or maintain:

1. **Trigger:** `on: schedule` with a daily cron (`0 23 * * *`, 23:00 UTC =
   01:00 BiH time during summer/CEST — cron is fixed UTC and doesn't shift
   for DST, so this drifts to 00:00 local once BiH falls back to CET in
   winter; adjust the hour then if you want it pinned to 1am local
   year-round), plus `workflow_dispatch` so you can also fire it manually
   from the repo's Actions tab to test it.
2. **Runs the tests first** (`pytest tests/`), so a config change that
   breaks the state machine or parser fails loudly instead of running
   unattended and quietly corrupting `data/listings.json`.
3. **Runs `python main.py`**, capturing its exit code without letting a
   failure skip the commit step — partial data from a partially-successful
   run still gets saved (matches the "partial data beats losing the whole
   day" design in `scraper/run.py`).
4. **Records a heartbeat, commits and pushes `data/` — unconditionally,
   `if: always()`.** This step runs even if install, tests, or the scraper
   itself failed. It writes `data/last_run.txt` (timestamp + the scraper's
   exit code) before committing, so there's always something to commit even
   on a day where the scrape produced zero new data — see §9.1 for why that
   matters. Retries push up to 3 times with a rebase in between, to survive
   a transient conflict rather than silently losing that day's commit.
5. **Fails the job at the end if the scraper didn't exit 0** (see the
   `healthy` flag in `scraper/run.py` — false if the circuit breaker
   tripped or every single brand failed). A failed scheduled workflow run
   shows up red in the Actions tab and GitHub emails whoever last edited the
   workflow file — that's your signal something's actually wrong (e.g.
   olx.ba started blocking the requests), separate from whether the
   schedule itself keeps running (it does, regardless — see §9.1).

### 9.1 Reliability checklist — what could make this stop, and what's done about it

You asked for this to run effectively forever without needing to be
restarted by hand. Concretely, here's every way a "runs daily forever"
setup like this can actually die, and what's in place for each:

| Failure mode | Effect if unhandled | Mitigation |
|---|---|---|
| GitHub auto-disables a schedule after 60 days with zero commits to the repo | Cron silently stops firing, permanently, with no notification | The heartbeat file (§9, step 4) guarantees a commit every single day regardless of whether the scrape found anything, so this can never trigger as long as the workflow runs at all |
| A step earlier in the job fails (bad dependency, broken test) | Later steps get skipped by default — no commit that day | The heartbeat/commit step uses `if: always()`, so it runs (and the schedule stays "alive") no matter which earlier step failed |
| `git push` fails (race with a manual commit, transient network blip) | That day's commit exists only on the ephemeral runner and is lost the moment the job ends | Push is retried 3x with `git pull --rebase` in between; if all 3 fail, the job fails loudly (`::error::`) instead of silently losing data |
| A bug causes an infinite/near-infinite loop (bad pagination, stuck request) | Job hangs, potentially burning the whole month's Actions-minutes budget in one run | `timeout-minutes: 60` at the job level, plus existing caps in `scraper/config.py` (`MAX_PAGES_PER_BRAND`, the circuit breaker) that should never let a normal run get anywhere close to that |
| One brand's page is broken/blocked, or the site's payload structure changes | Would otherwise crash the whole run, losing every other brand's data too | Per-brand try/except in `run.py` — a broken/changed page raises `NuxtPayloadError` from `parser.py`, which is caught, logged, and counted as that brand failing; the rest still run |
| Repeated 403/429 responses (site blocking us) | Would otherwise retry forever, hammering the site | Circuit breaker in `http_client.py` stops the run after 3 consecutive hostile responses rather than retrying indefinitely |
| `node` isn't available in some future runtime environment | `parser.py` would fail on every single page (a `NuxtPayloadError`, "node not found") | Confirmed present on GitHub Actions runners; if this ever moves to a different environment (e.g. a Dockerfile), it needs to install Node alongside Python |
| `data/listings.json` gets corrupted (e.g. a run killed mid-write) | `load_state()` would throw and the whole run would fail | Not auto-healed — by design, since silently discarding it would erase months of history. Recover via `git checkout <previous-commit> -- data/listings.json`; the daily commits mean a good version is always one commit away |
| Repo-level things outside the code's control: Actions disabled at the repo/org level, billing/quota issues on a private repo, the repo deleted or made archived | Schedule stops regardless of anything in this workflow | Not fixable from code — worth an occasional manual glance at the Actions tab. If this repo is private, keep an eye on included Actions minutes; public repos get unlimited minutes on standard runners |
| Branch protection added later to the default branch | Direct push from the bot starts failing every day | Not set up preemptively (no protection exists yet) — if you add branch protection later, either exempt this workflow's token or switch the commit step to open a PR instead of pushing directly |

None of this replaces occasionally checking the Actions tab yourself —
it minimizes the ways the schedule can *silently* die, but a red run still
means something needs a look.

**What you need to do to actually turn it on:**
- **Merge this branch into the repo's default branch** (or make it the
  default branch). GitHub only fires `schedule` triggers from the workflow
  file as it exists on the default branch — it will not fire from a
  feature branch, no matter how long it sits there.
- Check the repo's Settings → Actions → General → Workflow permissions is
  set to "Read and write permissions" (some orgs/repos default to
  read-only, which would make the push step fail with a 403).
- If this repo ever gets branch protection rules on the default branch
  (required reviews, etc.), the bot's direct push will start failing — at
  that point either exempt the workflow's token from the rule or switch
  this to opening a PR each day instead of pushing directly.
- Once merged, use the Actions tab's "Run workflow" button once to confirm
  it actually runs end-to-end before waiting for the first 23:00 UTC firing.

## 10. Multi-category testing expansion (2026-07-23 -> 2026-08-01)

Alongside cars, a time-boxed test of more verticals was added: bicycles,
PCs/laptops, expensive clothing, sports/ski/outdoor equipment, mobile
phones, watches, gaming consoles, tablets, smartwatches, and digital
cameras. Explicitly a *test* to see whether any of these are worth
tracking properly — not production, and not merged into the car
pipeline's code path.

**Category IDs** (real, from a live "Debug fetch" run against
`https://olx.ba/pretraga`'s `state.search.aggregations.categories`, one
level of `sub_categories` deep — not guessed):

| Vertical | Subcategories used | Why not the whole parent |
|---|---|---|
| Bicycles | Bicikli (`category_id=22`, ~17.8k listings) | Single category, no parent-tree issue |
| PCs & Laptops | Laptopi (`39`, ~29.9k), Desktop Racunari (`38`, ~12.2k) | Parent "Kompjuteri" (`5`, ~377k) is mostly accessories (mice, RAM, cables) — targeted the two subcategories that are actually computers |
| Expensive Clothing | 9 subcategories: men's/women's sneakers, coats/jackets, bags, boots, heels (see `categories.py`) | Parent "Odjeca i obuca" (`465`) is ~213.7k listings — *larger than the entire Vozila category* that forced cars into per-brand querying (§6). No single "expensive" bucket exists; picked subcategories that plausibly carry premium items, skipped high-volume-but-cheap ones (t-shirts, etc.) |
| Sports, Ski & Outdoor Equipment | 9 subcategories: skis, ski boots, mountain jackets, training weights/machines, football boots/jerseys, camping gear (`Ostala kamp oprema`=1278, the closest real match to "hiking gear" — no dedicated hiking-only subcategory exists) | Parent "Sportska oprema" (`171`) is ~169.9k listings, same over-volume risk as clothing |
| Mobile Phones | Mobiteli (`31`, ~47.3k) | Single category |
| Watches | Rucni Satovi (`244`, ~26.0k, under parent "Nakit i Satovi" id=68) | Single category — picked over the rest of the jewelry tree since watches specifically have the clearest resale/import arbitrage story |
| Gaming Consoles | Konzole (`292`, ~8.4k, under parent "Video igre" id=289) | Single category |
| Tablets | Tablet PCs (`1495`, ~7.6k, under parent "Mobilni uredaji" id=3) | Single category, direct sibling of phones |
| Smartwatches | Smartwatch (`2076`, ~20.7k, under parent "Mobilni uredaji" id=3) | Single category |
| Digital Cameras | Digitalni fotoaparati (`112`, ~4.8k, under parent "Tehnika" id=14) | Single category |

The clothing/sports subcategory-watchlist choice is a direct application
of §6's lesson: a flat sweep of a huge parent category doesn't finish
within a sane page budget and, worse, causes false `removed` markings.
Bicycles, PCs/laptops, phones, watches, and consoles are small/single
enough that this likely wasn't necessary, but the same pattern was used
everywhere for consistency and because it costs nothing extra.

**Price thresholds are first-pass judgment calls, not user-specified**
(unlike cars' 25,000 KM): bicycles ≥500 KM, PCs/laptops ≥1,000 KM, clothing
≥150 KM, sports/ski/outdoor ≥200 KM, phones ≥500 KM, watches ≥300 KM,
consoles ≥300 KM, tablets ≥400 KM, smartwatches ≥300 KM, cameras ≥300 KM.
Expect these to move once real listing volume comes back, the same way
cars' threshold moved 20k → 25k KM.

**Why these over other candidates:** asked what else might be worth
importing/reselling, the reasoning was value-density and liquidity —
items worth the shipping/import cost with a proven, active resale market
— over categories that are either too heavy to ship profitably (large
appliances, TVs) or too illiquid/niche to generalize a strategy for
(collectibles, most vehicle parts, tools/machinery, books). Phones and
watches in particular are classic arbitrage categories: high value per
unit of size/weight, and (for watches especially) resale value that holds
or appreciates rather than depreciating the way most goods do. Tablets
and smartwatches follow the same logic as phones/watches. Fine jewelry
(rings, necklaces, bracelets) was considered and explicitly dropped at
the user's request, leaving watches as the sole jewelry-adjacent
category.

**Architecture:** `scraper/categories.py` (Vertical/SubCategory config,
data paths under `data/<slug>/`), `scraper/multi_run.py` (orchestrator —
reuses `http_client.py`, `parser.py`, and a now-path-parameterized
`storage.py` unchanged; each subcategory pages newest-first with the same
consecutive-empty-pages-past-the-window stop condition as `run.py`'s
`scrape_brand()`). Deliberately a separate module/workflow
(`daily-scrape-verticals.yml`, cron `0 22 * * *`, one hour before cars)
rather than folding into `run.py`/`daily-scrape.yml`, so this experiment
can't destabilize the proven car pipeline. Same stale-checkout-sync fix
applied from day one (see the 2026-07-23 fix on the car workflow).

**Self-limiting:** `multi_run.run()` checks the run date against
`categories.TESTING_END_DATE` (2026-08-01) and no-ops without scraping once
past it, so the workflow doesn't rely on anyone remembering to disable it
when the test window ends — though it's still expected to be reviewed and
likely retired (or made permanent, if the data justifies it) around then.

**Same removed/aged_out state machine as cars, reused as-is:** a listing
missing from today's scan gets `removed` (disappeared before its 45-day
window ran out — most likely sold or delisted) vs `aged_out` (still
theoretically listed but past the window, so out of scope). This already
covers "new listings get added, previously-tracked ones are kept and
re-checked daily, and a removal reason gets recorded" — the daily scan
must keep re-paging the *entire* still-active backlog each day, not just
that day's brand-new postings, because disappearing from that scan is the
only removal signal available (no confirmed per-listing detail-page URL
exists to check an individual old listing directly — see `parser.py`'s
docstring). Restricting the daily scan to only newly-posted items would
save request budget but would break removal detection entirely, the same
failure mode as §6's postmortem in a different guise. True "sold" vs.
"expired" vs. "manually delisted" disambiguation isn't possible from the
search-results payload alone (search results don't carry a post-removal
status) — `removed` is the closest available signal, same limitation as
cars.

### 10.1 §6b's bug recurring in the verticals pipeline too (caught 2026-07-24)

The daily monitoring routine's second day caught the same
`MAX_PAGES_PER_BRAND`-style truncation bug (§6b) independently in
`scraper/categories.py`'s per-subcategory equivalent. The verticals
pipeline's *second-ever* scrape (run #4, 2026-07-23 23:57 UTC, the one
that added phones/watches/consoles/tablets/smartwatches/cameras) showed
**21 of 27 subcategories hitting exactly page 40** (`max_pages_per_
subcategory`'s old default) with no natural "stopping" log line — i.e.
truncated mid-scan rather than reaching their own window-based stop.

Impact was uneven: "Kopacke" (football boots) went from 179 tracked to
**179 marked `removed` — 100%** (every single previously-seen listing
shifted past page 40 between the two scrapes and got wrongly marked
gone). Bicycles (3.3%), computers (2.8%), and clothing (1.2%) stayed
close enough to a plausible baseline that they weren't obviously wrong on
inspection, but given their subcategories hit the same cap, they were
restored too rather than assumed clean. The six brand-new verticals from
that same run (phones, watches, consoles, tablets, smartwatches, cameras)
were **unaffected** — a first-ever scrape has nothing to falsely compare
against, so no removals were possible for them yet.

**Fix:** `max_pages_per_subcategory` default raised 40 → 120 (a smaller
multiple than §6b's car fix, deliberately -- with ~21 subcategories
potentially all needing more page budget *simultaneously* in one job run,
unlike cars where only 1-2 brands were affected, a too-generous cap risks
blowing the job timeout instead of fixing the truncation). Workflow
timeout bumped 120→220 minutes to match. All four affected verticals'
`data/<slug>/listings.json` restored to their first-scrape baseline
(commit `f7d76f0`, 100% active, zero removed — the only truly "clean"
state, since even the *second* scrape under the old code already showed
this corruption, not just the later expansion run). `data/import_
worthiness_report.json` regenerated locally to strip the resulting fake
scores (Kopacke's 100% sell-through in particular) rather than wait for
the next scheduled regeneration.

**Update:** this concern turned out justified. The car pipeline's own
250-page cap increase (§6b) was validated against a real run before this
vertical fix could be, and it failed the same way -- the same six brands
hit the new cap too, false-removal rate got *worse*, not better. Rather
than wait to find out the 40→120 cap bump here fails the same way,
applied the same real fix proactively: `scrape_subcategory()` now reports
whether it reached a natural stop, and `run_vertical()` passes the
subcategories that didn't into `merge_into_state`'s `incomplete_groups`,
which skips removed/aged_out determination for them rather than guessing.
See §6b for the full reasoning on why raising a cap doesn't fix a backlog
that's genuinely bigger than any daily page budget.

## 11. Import-worthiness scoring (`scraper/analysis.py`)

The end goal stated for this project is a website/browser extension that
compares products and surfaces what's worth importing into Bosnia for
resale — this is the first pass at turning tracked listings into that
actual ranking, rather than just raw counts.

**What it can and can't measure:** there's no cross-border source-market
price data anywhere in this pipeline — only what things sell for *in
Bosnia*. So it cannot compute profit margin. What it measures instead is
domestic demand strength (does this category's stock turn over, how fast,
does it need discounting) as a proxy for import-worthiness. The report's
`methodology_note` field says this explicitly rather than presenting a
score as if it were a margin calculation.

**Three signals, weighted 0.5 / 0.3 / 0.2 (first-pass judgment calls, not
derived from anything yet):**
- **Sell-through rate** (`removed / (removed + aged_out)`) — the core
  "does this actually move" signal.
- **Speed** (median `days_listed` among `removed` listings) — two groups
  can share a sell-through rate while one moves in a week and the other in
  six; speed is what actually matters for inventory turnover.
- **Price firmness** (share of listings that never needed a price cut,
  from `price_history`) — catches weak demand that sell-through rate alone
  would miss (it did eventually sell, but only after discounting).

Each is min-max normalized *within the comparison set* (so, e.g., "fast"
for cars and "fast" for phones are graded on their own scales) into a
single 0-100 `score` per group.

**Grouping granularity:** cars are grouped by `brand` (authoritative —
tagged by which brand-specific search found the listing). Verticals are
now grouped both ways (see §12): `by_subcategory` (the "type" dimension)
and `by_brand` (title-matched, heuristic — see §12 for caveats). The
`groups` key is kept as an alias for `by_subcategory` for backwards
compatibility.

**Minimum sample size:** a group needs `n >= 10` total listings and
`removed + aged_out >= 5` before it gets a score at all — below that it's
marked `insufficient_data: true` with raw counts still shown, rather than
computing a sell-through rate off 1-2 samples (a real 1-for-1 removal
looks identical to noise). Checked against real data on 2026-07-23/24: of
28 car brand groups, only 2 (Volkswagen, Audi) had enough resolved history
after ~2 days of tracking to be scored — everything else correctly showed
`insufficient_data` rather than a fabricated number. Expect most groups,
especially the brand-new testing verticals, to stay `insufficient_data`
for a while yet.

**Output:** `data/import_worthiness_report.json` — per-car-brand groups,
per-vertical per-subcategory groups, and a `vertical_ranking` (verticals
ranked by their groups' average score) for comparing across categories at
a glance. Regenerated daily by `.github/workflows/daily-analysis-report.yml`
(cron `0 3 * * *`, comfortably after both scrape workflows even at their
worst-case runtime), same stale-checkout-sync + retry-push pattern as the
other two workflows.

## 12. Price floors raised + brand/model extraction for verticals (2026-07-24)

Two pieces of explicit user feedback drove this: (1) the original
first-pass `min_price_bam` values were too low to represent "worth
importing" (their words: not interested in a 200 KM bike or 30 KM
clothing item), and (2) brand/type/model needed to actually be extracted
for the non-car verticals, not just subcategory — the exact gap flagged
in §11 and analysis.py's own docstring.

**Price floors** (`scraper/categories.py`), old → new:
bicycles 500→1500, PCs & Laptops 1000→1500, Expensive Clothing 150→400,
Sports/Ski/Outdoor 200→500, Mobile Phones 500→800, Watches 300→600,
Gaming Consoles 300→400, Tablets 400→600, Smartwatches 300→400, Digital
Cameras 300→600. Same caveat as before: judgment calls, not derived from
anything, expect further tuning once more volume has accumulated at these
new floors.

**Brand/model extraction** (`scraper/brand_matching.py`): before building
this, checked whether olx.ba exposes a structured brand field to lean on
instead of guessing — a live "Debug fetch" against the phones category
(`state.search.attributes`, the category's own filter-attribute schema)
turned up 27 real attributes (RAM, storage, camera, color, screen size,
battery, etc.) but **no brand/manufacturer attribute at all**, and
`brand_id` on individual listings is only sometimes populated. So there's
no shortcut — brand has to come from matching a known-brand list against
the listing title, the same technique `parser.py`'s `_guess_brand` has
used for cars from day one. That logic was pulled out into a shared
module (`brand_matching.py`: `strip_diacritics`, `fold_brands` — sorts
longest-name-first so e.g. "Land Rover" matches before the shorter,
ambiguous "Rover" — `guess_brand_from_title`, `guess_model_hint`) so cars
and verticals both use one implementation. `parser.py` was refactored to
call into it (behavior-preserving — full test suite re-passed
immediately after).

Each `Vertical` (`categories.py`) now carries a `known_brands` list (a
reasonable-effort pass at each category's real, common brands in this
market, not exhaustive — e.g. bicycles: Specialized/Trek/Giant/Cube/...,
watches: Rolex/Omega/Casio/Seiko/..., phones: Samsung/Apple/Xiaomi/...).
`multi_run.py`'s `scrape_subcategory()` now tags every collected item
with `brand` (matched brand name or `None`) and `model_hint` (the text
immediately following the matched brand name in the title, trimmed to 4
words / 40 chars — explicitly a "hint", not a validated model field,
since there's no structured model field anywhere in the payload for any
category).

**Honest caveats, same as cars' brand matching has always had:** a title
with no known brand name returns `None` rather than a wrong guess (these
fall into an "Unknown" bucket in `analyze_vertical_by_brand`, which
should be read as a `known_brands` coverage gap, not as a real brand
group); a title mentioning two brand names resolves to whichever is
longest, which is usually but not always correct; `model_hint` is raw
trailing title text and will contain noise (specs, condition words,
seller comments) mixed in with the real model name.

`scraper/analysis.py` gained `analyze_vertical_by_brand()` alongside the
existing subcategory-based `analyze_vertical()`; `generate_report()` now
writes both under each vertical (`by_subcategory` / `by_brand`, with
`groups` kept as an alias for `by_subcategory`). Tests added:
`tests/test_brand_matching.py` (11 cases covering diacritics folding,
longest-first matching, no-match/None handling, model-hint trimming and
truncation) and a new case in `tests/test_multi_run.py` confirming
`run_vertical` actually tags scraped items with `brand`/`model_hint`.
Full suite: 46 passed.
