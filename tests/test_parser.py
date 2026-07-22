from datetime import date

from scraper.parser import parse_detail_page, parse_search_results

# NOTE: this fixture HTML is hand-written to approximate a plausible
# olx.ba-style listing card — it has not been captured from the real site
# (see docs/RESEARCH.md caveat). It exists to prove the regex-based parser
# behaves sensibly on *a* reasonable structure, not to prove it matches the
# real one. Re-validate against real HTML before trusting this in production.
SEARCH_RESULTS_HTML = """
<html><body>
<div class="results">
  <div class="card">
    <a href="/artikal/volkswagen-passat-20-tdi-12345678" title="Volkswagen Passat 2.0 TDI">
      Volkswagen Passat 2.0 TDI 2018
    </a>
    <div class="meta">
      <span class="price">24.500 KM</span>
      <span class="km">185.000 km</span>
      <span class="location">Sarajevo</span>
      <span class="posted">Prije 3 dana</span>
    </div>
  </div>
  <div class="card">
    <a href="/artikal/skoda-superb-20-tdi-87654321" title="Skoda Superb 2.0 TDI">
      Skoda Superb 2.0 TDI 2020
    </a>
    <div class="meta">
      <span class="price">32.000 KM</span>
      <span class="km">95.000 km</span>
      <span class="location">Banja Luka</span>
      <span class="posted">Danas</span>
    </div>
  </div>
</div>
</body></html>
"""

DETAIL_PAGE_HTML = """
<html><body>
<h1>Volkswagen Passat 2.0 TDI</h1>
<div class="attributes">
  <div>Godiste: 2018.</div>
  <div>Kilometraza: 185.000 km</div>
  <div>Gorivo: Dizel</div>
  <div>Karoserija: Limuzina</div>
  <div>Boja: Siva</div>
</div>
<p>Auto je ocarinjen, prvi vlasnik, nije havarisan.</p>
<img src="https://olx.ba/img/1.jpg" />
<img src="https://olx.ba/img/2.jpg" />
</body></html>
"""


def test_parse_search_results_extracts_both_cards():
    reference = date(2026, 7, 22)
    listings = parse_search_results(SEARCH_RESULTS_HTML, reference_date=reference)

    assert len(listings) == 2

    passat, superb = listings
    assert passat["id"] == "12345678"
    assert passat["price_bam"] == 24500
    assert passat["mileage_km"] == 185000
    assert passat["year"] == 2018
    assert passat["published_date"] == "2026-07-19"  # 3 days before reference

    assert superb["id"] == "87654321"
    assert superb["price_bam"] == 32000
    assert superb["mileage_km"] == 95000
    assert superb["year"] == 2020
    assert superb["published_date"] == "2026-07-22"  # "Danas"


def test_parse_detail_page_extracts_attributes_and_keywords():
    result = parse_detail_page(DETAIL_PAGE_HTML)

    assert result["fuel_type"].strip() == "dizel"
    assert result["body_type"].strip() == "limuzina"
    assert result["color"].strip() == "siva"
    assert result["customs_paid"] is True
    assert result["first_owner"] is True
    assert result["damage_flag"] is False
    assert result["photo_count"] == 2
