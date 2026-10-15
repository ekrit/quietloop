from unittest.mock import patch

import pytest

from scraper import http_client
from scraper.http_client import CircuitOpenError, PoliteSession


class _Resp:
    def __init__(self, status):
        self.status_code = status
        self.ok = status < 400
        self.text = ""

    def raise_for_status(self):
        raise AssertionError("should have been handled as hostile before raise_for_status")


def test_repeated_500s_trip_the_circuit_breaker():
    # The site rate-limits with HTTP 500 rather than 403/429.
    session = PoliteSession()
    with patch.object(session._session, "get", return_value=_Resp(500)), patch.object(http_client.time, "sleep"):
        with pytest.raises(CircuitOpenError):
            session.get("https://example.com/pretraga")


def test_single_500_is_retried_then_succeeds():
    session = PoliteSession()
    responses = iter([_Resp(500), _Resp(200)])
    with patch.object(session._session, "get", side_effect=lambda *a, **k: next(responses)), patch.object(
        http_client.time, "sleep"
    ):
        assert session.get("https://example.com/pretraga").status_code == 200
