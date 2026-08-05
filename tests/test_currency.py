from scraper.currency import price_per_km


def test_price_per_km():
    assert price_per_km(24500, 100000) == 0.245


def test_price_per_km_zero_mileage():
    assert price_per_km(24500, 0) is None


def test_price_per_km_none_price():
    assert price_per_km(None, 100000) is None
