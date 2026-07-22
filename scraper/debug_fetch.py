"""One-off diagnostic, NOT part of the daily pipeline.

Fetches a single olx.ba URL and reports what's actually there — status
code, whether known JS-framework/anti-bot markers are present, and a
chunk of the raw HTML — so parser.py can be fixed against reality instead
of guesses. Run via the "Debug fetch" GitHub Actions workflow (manual
dispatch only) or locally: `python -m scraper.debug_fetch [url]`.
"""
from __future__ import annotations

import re
import sys

from .config import BASE_URL
from .http_client import PoliteSession


def main() -> None:
    url = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else f"{BASE_URL}/pretraga?category_id=18"
    session = PoliteSession()
    response = session.get(url)
    text = response.text

    print(f"status_code={response.status_code}")
    print(f"final_url={response.url}")
    print(f"content_length={len(text)}")

    markers = [
        "__NEXT_DATA__",
        "__NUXT__",
        "/artikal/",
        "cloudflare",
        "captcha",
        "just a moment",
        "cf-browser-verification",
        "kategorija",
        "trazilica",
    ]
    for marker in markers:
        print(f"contains[{marker!r}]={marker.lower() in text.lower()}")

    title_match = re.search(r"<title>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
    print(f"title={title_match.group(1).strip() if title_match else None}")

    hrefs = set(re.findall(r'href="([^"]+)"', text))
    interesting = sorted(
        h
        for h in hrefs
        if h.startswith("/") and not h.startswith(("/_nuxt", "/js/", "/img/", "/favicon", "/css/"))
    )
    print(f"total_unique_hrefs={len(hrefs)}")
    print(f"interesting_hrefs_sample (of {len(interesting)}):")
    for h in interesting[:50]:
        print(f"  {h}")

    km_count = len(re.findall(r"\bKM\b", text))
    print(f"KM_occurrences={km_count}")
    for m in list(re.finditer(r".{80}KM.{20}", text))[:8]:
        print(f"KM_context: ...{m.group(0)}...")

    class_matches = sorted(
        set(re.findall(r'class="([^"]*(?:card|listing|oglas|item|result)[^"]*)"', text, re.IGNORECASE))
    )
    print(f"listing-like class names ({len(class_matches)} unique):")
    for c in class_matches[:30]:
        print(f"  {c}")

    print("--- first 3000 chars ---")
    print(text[:3000])


if __name__ == "__main__":
    main()
