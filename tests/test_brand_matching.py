from scraper.brand_matching import fold_brands, guess_brand_from_title, guess_model_hint, strip_diacritics


def test_strip_diacritics():
    assert strip_diacritics("Škoda") == "Skoda"
    assert strip_diacritics("Motörhead") == "Motorhead"


def test_fold_brands_sorts_longest_first():
    folded = fold_brands(["Rover", "Land Rover", "BMW"])
    names = [name for name, _ in folded]
    assert names[0] == "Land Rover"  # longer, more specific name must match first
    assert names.index("Land Rover") < names.index("Rover")


def test_guess_brand_from_title_matches_longer_name_over_substring():
    folded = fold_brands(["Rover", "Land Rover"])
    assert guess_brand_from_title("Land Rover Discovery 2019", folded) == "Land Rover"


def test_guess_brand_from_title_case_and_diacritic_insensitive():
    folded = fold_brands(["Škoda"])
    assert guess_brand_from_title("SKODA octavia extra clean", folded) == "Škoda"


def test_guess_brand_from_title_no_match_returns_none():
    folded = fold_brands(["Nike", "Adidas"])
    assert guess_brand_from_title("Generic running shoes size 42", folded) is None


def test_guess_brand_from_title_handles_none_title():
    folded = fold_brands(["Nike"])
    assert guess_brand_from_title(None, folded) is None


def test_guess_model_hint_captures_words_after_brand():
    assert guess_model_hint("Samsung Galaxy S24 Ultra 256GB crno", "Samsung") == "Galaxy S24 Ultra 256GB"


def test_guess_model_hint_strips_separators():
    assert guess_model_hint("Nike - Air Max 90 original", "Nike") == "Air Max 90 original"


def test_guess_model_hint_truncates_to_max_chars():
    hint = guess_model_hint("Nike ThisIsAVeryLongSingleWordThatExceedsFortyCharactersEasily", "Nike")
    assert hint is not None
    assert len(hint) <= 40


def test_guess_model_hint_none_when_nothing_follows_brand():
    assert guess_model_hint("Samsung", "Samsung") is None


def test_guess_model_hint_none_without_brand_or_title():
    assert guess_model_hint(None, "Nike") is None
    assert guess_model_hint("Nike shoes", None) is None
