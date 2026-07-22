from scraper.currency import bam_to_eur, price_per_km


def test_bam_to_eur():
    assert bam_to_eur(19558.3) == 10000.0


def test_bam_to_eur_none():
    assert bam_to_eur(None) is None


def test_price_per_km():
    assert price_per_km(24500, 100000) == 0.245


def test_price_per_km_zero_mileage():
    assert price_per_km(24500, 0) is None


def test_price_per_km_none_price():
    assert price_per_km(None, 100000) is None
