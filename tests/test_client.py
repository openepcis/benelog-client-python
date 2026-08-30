# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 benelog GmbH & Co. KG
"""The request loop: retry policy, single re-auth, error mapping."""

from typing import Any

import pytest

from benelog_client.core import client as client_module
from benelog_client.core.client import Client
from benelog_client.core.config import ClientConfig
from benelog_client.core.errors import BenelogError

from .conftest import Answer, StubSession

CONFIG = ClientConfig(base_url="https://id.example.test")


class FixedAuth:
    """An AuthStrategy that counts invalidations and mints numbered bearers."""

    def __init__(self) -> None:
        self.minted = 0
        self.invalidated = 0

    def bearer(self) -> str:
        self.minted += 1
        return f"token-{self.minted}"

    def invalidate(self) -> None:
        self.invalidated += 1


class SequenceSession(StubSession):
    """Answers request() from a fixed sequence, ignoring the URL."""

    def __init__(self, answers: list[Answer]) -> None:
        super().__init__()
        self.answers = answers

    def request(self, method: str, url: str, **kw: Any) -> Answer:
        self.calls.append((method, url, kw))
        return self.answers[min(len(self.calls) - 1, len(self.answers) - 1)]


def make_client(answers: list[Answer]) -> tuple[Client, FixedAuth, SequenceSession]:
    auth = FixedAuth()
    session = SequenceSession(answers)
    return Client(CONFIG, auth, session=session), auth, session  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client_module, "BACKOFF_SECONDS", (0, 0))


class TestRetryPolicy:
    def test_a_gateway_wobble_on_get_is_retried(self) -> None:
        client, _, session = make_client([Answer(503), Answer(200, {"ok": True})])
        assert client.get("/products") == {"ok": True}
        assert len(session.calls) == 2

    def test_post_never_retries(self) -> None:
        # A retried POST could burn a GS1 key or publish twice.
        client, _, session = make_client([Answer(503), Answer(200, {})])
        with pytest.raises(BenelogError):
            client.post("/gs1de/keys/draw", {"ai": "01"})
        assert len(session.calls) == 1

    def test_a_validation_error_is_not_retried(self) -> None:
        client, _, session = make_client([Answer(400, {"detail": "gtin is required"})])
        with pytest.raises(BenelogError, match="gtin is required"):
            client.put("/products/1", {})
        assert len(session.calls) == 1

    def test_retries_are_bounded(self) -> None:
        client, _, session = make_client([Answer(503)])
        with pytest.raises(BenelogError):
            client.get("/products")
        assert len(session.calls) == client_module.MAX_ATTEMPTS


class TestReauth:
    def test_a_401_reauths_exactly_once_without_costing_a_retry(self) -> None:
        client, auth, session = make_client([Answer(401), Answer(200, {"ok": True})])
        assert client.get("/products") == {"ok": True}
        assert auth.invalidated == 1
        assert len(session.calls) == 2

    def test_a_second_401_is_the_answer(self) -> None:
        client, auth, _ = make_client([Answer(401), Answer(401)])
        with pytest.raises(BenelogError) as caught:
            client.get("/products")
        assert caught.value.status == 401
        assert auth.invalidated == 1

    def test_reauth_applies_to_post_as_well(self) -> None:
        # The refused call was never applied, so going again is safe even for
        # a verb that must not retry.
        client, _, session = make_client([Answer(401), Answer(200, {"ok": True})])
        assert client.post("/bulk/products") == {"ok": True}
        assert len(session.calls) == 2


class TestAnswers:
    def test_204_is_none(self) -> None:
        client, _, _ = make_client([Answer(204)])
        assert client.delete("/gs1de/keys/01/1") is None

    def test_a_login_page_is_named_for_what_it_is(self) -> None:
        client, _, _ = make_client([Answer(200, b"<html>login</html>", "text/html")])
        with pytest.raises(BenelogError, match="web page instead of data"):
            client.get("/products")

    def test_rfc7807_detail_is_preferred(self) -> None:
        client, _, _ = make_client(
            [Answer(422, {"title": "Unprocessable", "detail": "GTIN 1 is not verified by GS1"})]
        )
        with pytest.raises(BenelogError, match="not verified by GS1") as caught:
            client.put("/products/1", {})
        assert caught.value.problem["title"] == "Unprocessable"

    def test_the_bearer_travels_in_the_header(self) -> None:
        client, _, session = make_client([Answer(200, {})])
        client.get("/products")
        assert session.calls[0][2]["headers"]["Authorization"] == "Bearer token-1"


class TestAcceptHeader:
    """What this client says it can read back.

    The EPCIS capture endpoint produces ``application/ld+json`` and
    ``application/problem+json`` and nothing else. Asking for plain JSON is
    answered with 406 before the document is looked at — so a client that only
    accepts ``application/json`` never captures anything, and finds out at the
    first real repository rather than in any test.
    """

    def test_ld_json_is_accepted_or_capture_answers_406(self) -> None:
        client, _auth, session = make_client([Answer(202, {})])
        client.request("POST", "/capture", payload={"type": "EPCISDocument"})
        accept = session.calls[0][2]["headers"]["Accept"]
        assert "application/ld+json" in accept

    def test_plain_json_stays_accepted_for_the_catalog(self) -> None:
        # The catalog and registry answer application/json; dropping it would
        # trade one 406 for another.
        client, _auth, session = make_client([Answer(200, {})])
        client.request("GET", "/products/09520123456788")
        accept = session.calls[0][2]["headers"]["Accept"]
        assert "application/json" in accept
