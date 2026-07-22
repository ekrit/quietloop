"""One-off diagnostic, NOT part of the daily pipeline.

Fetches a single olx.ba URL and reports what's actually there — the raw
HTML report, plus a dump of the deserialized __NUXT__ state (see
scraper/nuxt_payload.py and parser.py for what this led to).

Run via the "Debug fetch" GitHub Actions workflow (manual dispatch only)
or locally: `python -m scraper.debug_fetch [url]` (requires `node` on PATH
for the __NUXT__ dump; the plain-HTML report works without it).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from .config import BASE_URL
from .http_client import PoliteSession
from .nuxt_payload import NuxtPayloadError, extract_nuxt_state


def report_nuxt_state(html: str) -> None:
    try:
        data = extract_nuxt_state(html)
    except NuxtPayloadError as exc:
        print(f"extract_nuxt_state failed: {exc}")
        return

    print("Successfully deserialized the __NUXT__ payload (sandboxed).")
    print(f"top_level_type={type(data).__name__}")
    if not isinstance(data, dict):
        return
    print(f"top_level_keys={list(data.keys())}")

    def walk(obj, path="", depth=0):
        if depth > 5:
            return
        if isinstance(obj, list) and obj and isinstance(obj[0], dict):
            print(f"  candidate list at {path or '<root>'}: len={len(obj)}, item_keys={list(obj[0].keys())}")
        elif isinstance(obj, dict):
            for k, v in obj.items():
                walk(v, f"{path}.{k}" if path else k, depth + 1)

    walk(data)

    search = data.get("state", {}).get("search", {})
    results = search.get("results")
    if isinstance(results, list) and results:
        print("--- sample listing (state.search.results[0]) ---")
        print(json.dumps(results[0], ensure_ascii=False, indent=2))
        if len(results) > 1:
            print("--- sample listing (state.search.results[1]) ---")
            print(json.dumps(results[1], ensure_ascii=False, indent=2))

    categories = search.get("aggregations", {}).get("categories")
    if isinstance(categories, list):
        print("--- state.search.aggregations.categories ---")
        for cat in categories:
            print(f"  id={cat.get('id')} name={cat.get('name')!r} count={cat.get('count')}")

    out_path = Path("/tmp/nuxt_payload.json")
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2)[:200000])
    print(f"wrote (possibly truncated) payload to {out_path}")


def main() -> None:
    url = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else f"{BASE_URL}/pretraga?category_id=18"
    session = PoliteSession()
    response = session.get(url)
    text = response.text

    print(f"status_code={response.status_code}")
    print(f"final_url={response.url}")
    print(f"content_length={len(text)}")

    title_match = re.search(r"<title>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
    print(f"title={title_match.group(1).strip() if title_match else None}")

    print("--- NUXT payload ---")
    report_nuxt_state(text)


if __name__ == "__main__":
    main()
