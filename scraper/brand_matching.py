"""Generic title-based brand/model guessing, shared by cars (parser.py) and
the testing verticals (multi_run.py, categories.py).

No category has a reliable structured brand field to lean on: cars'
`brand_id` is only populated for a handful of confirmed IDs (config.py's
CONFIRMED_BRAND_IDS), and a live check of the phones category's own
`state.search.attributes` (its filter-attribute schema -- see
debug_fetch.py) turned up 27 real attributes (RAM, storage, camera,
color, etc.) but no brand/manufacturer attribute at all, and `brand_id`
on individual phone listings is only sometimes populated. So brand has to
come from matching a known-brand list against the listing title -- same
technique originally built for cars, generalized here so every vertical
can use it with its own brand list (scraper/categories.py's
Vertical.known_brands).

This is a heuristic, not a confirmed extraction: a title that doesn't
contain any known brand name returns None rather than a wrong guess, and
a title mentioning two brands (e.g. a Sony camera body described with a
"Zeiss" lens badge) resolves to whichever brand name is longest, which is
usually but not always the right one -- same caveat that's applied to
cars' brand matching from day one.

`model_hint` is deliberately named "hint", not "model": there's no
structured model field anywhere in the search payload for any category,
so this just captures the text immediately following the matched brand
name in the title, trimmed to a few words. It's frequently the real
model (e.g. "Samsung Galaxy S24" -> hint "Galaxy S24"), but it's raw
title text, not a validated model number -- expect noise (specs, seller
comments, condition words) mixed in.
"""
from __future__ import annotations

import re
import unicodedata

MODEL_HINT_MAX_WORDS = 4
MODEL_HINT_MAX_CHARS = 40


def strip_diacritics(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def fold_brands(brands: list[str]) -> list[tuple[str, str]]:
    """Returns (original_name, folded_name) pairs sorted longest-first, so
    e.g. "Land Rover" matches before the shorter, ambiguous "Rover"."""
    return sorted(
        ((name, strip_diacritics(name).lower()) for name in brands),
        key=lambda pair: len(pair[1]),
        reverse=True,
    )


def guess_brand_from_title(title: str | None, folded_brands: list[tuple[str, str]]) -> str | None:
    if not title:
        return None
    folded_title = strip_diacritics(title).lower()
    for name, folded_name in folded_brands:
        if folded_name in folded_title:
            return name
    return None


def guess_model_hint(title: str | None, brand: str | None) -> str | None:
    """Best-effort: the text right after the matched brand name in the
    title, not a validated model field -- see module docstring."""
    if not title or not brand:
        return None
    match = re.search(re.escape(brand), title, re.IGNORECASE)
    if not match:
        return None
    remainder = title[match.end():].strip(" -,/|:")
    if not remainder:
        return None
    words = remainder.split()[:MODEL_HINT_MAX_WORDS]
    hint = " ".join(words)[:MODEL_HINT_MAX_CHARS].strip()
    return hint or None
