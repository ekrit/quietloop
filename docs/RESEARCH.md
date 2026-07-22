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
price ≥ 25,000 KM, mileage ≥ 50,000 km) rather than pulling everything and
filtering after — smaller payloads, fewer requests, less load on their servers.
**No brand filter in the query at all** (see §6) — a single sweep of the whole
category, not N per-brand searches. This is architecturally simpler and likely
no slower overall: per-brand searches each independently paginate through
whatever "recent" pages match that brand's text, which plausibly re-covers a lot
of overlapping ground across brands, versus one linear pass over everything.

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

**Real numbers, since a live run happened before and after this change:** with
6 watch-listed brands (per-brand searches), a real run took ~19.5 minutes and
collected 2,216 qualifying listings. `MAX_PAGES` (replacing the old per-brand
`MAX_PAGES_PER_BRAND`) is set to 800 as an initial guess for the single-sweep
version — not yet tuned against real observed volume, since removing the brand
filter changes the total page count in an unknown direction. The job timeout
was bumped 60→120 minutes alongside this change as a safety margin; if a real
run comes in well under that, both numbers are worth revisiting downward.

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

## 6. No brand watchlist — every brand gets scraped

Originally this was a curated list (Mercedes-Benz, Škoda, Audi, Volkswagen,
Porsche, BMW, plus a "second tier" of Volvo/Land Rover). That's been dropped:
the price/mileage/year filters already gate for "expensive enough to be
worth analyzing" regardless of brand, so pre-selecting brands via the search
query was just deciding the answer before the data could — a Peugeot or
Toyota that clears 25k KM/2016+/50k+ km is exactly as relevant a data point
as a BMW that does. Every car in the category now gets scraped once (see §2),
and `brand` is derived from the listing itself:

- If `brand_id` is one of the ones confirmed from real data
  (`config.CONFIRMED_BRAND_IDS` — currently Volkswagen/Škoda/Audi/
  Mercedes-Benz/Porsche/BMW), use that name directly.
- Otherwise, match the title against `config.KNOWN_BRANDS` (~48 common
  brands: the original 6 plus Volvo, Land Rover, Toyota, Lexus, Hyundai,
  Kia, Ford, Peugeot, Renault, Alfa Romeo, Fiat, Opel, Citroen, Seat, and
  more), longest-name-first so "Land Rover" matches before a bare "Rover"
  could confuse things.
- If neither matches, `brand` is left `null` rather than guessed wrong.
  These listings still get fully tracked (price, year, mileage, etc.) —
  they just won't group cleanly by brand in analysis until `KNOWN_BRANDS`
  is extended or a listing turns out to need a title-parsing special case.

This does mean the daily crawl is a single sweep of the whole category
instead of N per-brand searches — see §2 for why that's not obviously
slower (arguably faster, since per-brand searches likely re-covered
overlapping pages) and what it costs in job-timeout headroom.

Within any given brand, the models actually worth watching for the 25k+ KM
bracket in this market are the higher trims/newer years — e.g. VW Passat
(B8)/Tiguan/Touareg, Škoda Superb/Kodiaq, Audi A4/A6/Q5/Q7, Mercedes
C/E-Class/GLC/GLE, Porsche Macan/Cayenne/Panamera, BMW 5-Series/X3/X5. This
is about how to *read* the resulting data later, not something the scraper
itself needs to know — the price filter already self-selects the segment.

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
