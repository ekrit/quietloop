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

    print("--- first 4000 chars ---")
    print(text[:4000])
    print("--- last 1500 chars ---")
    print(text[-1500:])


if __name__ == "__main__":
    main()
