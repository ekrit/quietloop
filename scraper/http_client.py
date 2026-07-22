"""Rate-limited HTTP client with retries and a circuit breaker.

See docs/RESEARCH.md "Politeness / risk-reduction": single-threaded,
randomized delay between requests, back off and stop on repeated hostile
responses rather than retrying aggressively.
"""
from __future__ import annotations

import logging
import random
import time

import requests

from .config import MAX_RETRIES, REQUEST_DELAY_SECONDS, REQUEST_TIMEOUT_SECONDS, USER_AGENT

logger = logging.getLogger(__name__)


class CircuitOpenError(RuntimeError):
    """Raised when too many hostile responses have been seen in a row."""


class PoliteSession:
    def __init__(self, max_consecutive_failures: int = 3) -> None:
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": USER_AGENT})
        self._consecutive_failures = 0
        self._max_consecutive_failures = max_consecutive_failures
        self._first_request_done = False

    def get(self, url: str, **kwargs) -> requests.Response:
        if self._first_request_done:
            time.sleep(random.uniform(*REQUEST_DELAY_SECONDS))
        self._first_request_done = True

        last_exc: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = self._session.get(url, timeout=REQUEST_TIMEOUT_SECONDS, **kwargs)
            except requests.RequestException as exc:
                last_exc = exc
                logger.warning("request error (attempt %d/%d) for %s: %s", attempt, MAX_RETRIES, url, exc)
                time.sleep(2**attempt)
                continue

            if response.status_code in (403, 429):
                self._consecutive_failures += 1
                logger.warning(
                    "hostile status %s for %s (consecutive=%d)",
                    response.status_code,
                    url,
                    self._consecutive_failures,
                )
                if self._consecutive_failures >= self._max_consecutive_failures:
                    raise CircuitOpenError(
                        f"{self._consecutive_failures} consecutive hostile responses "
                        f"(last: {response.status_code} on {url}) — stopping rather than "
                        f"retrying aggressively."
                    )
                time.sleep(2**attempt)
                continue

            if response.ok:
                self._consecutive_failures = 0
                return response

            response.raise_for_status()

        raise last_exc or RuntimeError(f"failed to fetch {url} after {MAX_RETRIES} attempts")
