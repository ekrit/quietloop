import json

from scraper.nuxt_payload import extract_nuxt_data


def _html(values):
    return (
        '<script type="application/json" data-nuxt-data="nuxt-app" id="__NUXT_DATA__">'
        + json.dumps(values)
        + "</script>"
    )


def test_unwraps_wrappers_and_resolves_indices():
    values = [
        ["ShallowReactive", 1],
        {"data": 2, "n": 5},
        ["ShallowReactive", 3],
        {"k": 4},
        [6, 7],
        42,
        "a",
        "b",
    ]
    assert extract_nuxt_data(_html(values)) == {"data": {"k": ["a", "b"]}, "n": 42}


def test_negative_indices_become_none_and_cycles_do_not_hang():
    values = [{"x": -1, "self": 0}]
    root = extract_nuxt_data(_html(values))
    assert root["x"] is None
    assert root["self"] is root
