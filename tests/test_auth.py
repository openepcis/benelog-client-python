# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 benelog GmbH & Co. KG
"""The offline-token exchange and the discovery that feeds it.

The properties worth defending: a rotated refresh token reaches the store the
moment it arrives, the realm is discovered from the resolver rather than
typed, and every failure names its own fix.
"""

import pytest

from benelog_client.core.auth import (
    InMemoryTokenStore,
    OfflineTokenAuth,
    token_subject,
    token_type,
)
from benelog_client.core.config import ClientConfig
from benelog_client.core.errors import BenelogError

from .conftest import Answer, StubSession, jwt_for

RESOLVER = "https://id.example.test"
ISSUER = "https://auth.example.test/realms/x"
CONFIG = ClientConfig(base_url=RESOLVER)


def make_auth(
    session: StubSession, issuer_override: str = "", secret: str = ""
) -> tuple[OfflineTokenAuth, InMemoryTokenStore]:
    store = InMemoryTokenStore("offline.token.value")
    auth = OfflineTokenAuth(
        CONFIG,
        store,
        client_id="test-connector",
        client_secret=secret,
        issuer_override=issuer_override,
        session=session,  # type: ignore[arg-type]
    )
    return auth, store


def wire_discovery(session: StubSession) -> None:
    session.answer(
        "/.well-known/oauth-protected-resource",
        Answer(200, {"authorization_servers": [ISSUER]}),
    )
    session.answer(
        "/.well-known/openid-configuration",
        Answer(200, {"token_endpoint": f"{ISSUER}/token"}),
    )


class TestDiscovery:
    def test_the_realm_is_discovered_from_the_resolver(self) -> None:
        session = StubSession()
        wire_discovery(session)
        auth, _ = make_auth(session)
        assert auth.issuer() == ISSUER
        assert any("/oauth-protected-resource" in url for _, url, _ in session.calls)

    def test_an_override_skips_discovery(self) -> None:
        session = StubSession()
        auth, _ = make_auth(session, issuer_override=ISSUER + "/")
        assert auth.issuer() == ISSUER
        assert session.calls == []

    def test_discovery_is_cached_per_resolver(self) -> None:
        session = StubSession()
        wire_discovery(session)
        auth, _ = make_auth(session)
        auth.issuer()
        auth.issuer()
        metadata_calls = [c for c in session.calls if "oauth-protected-resource" in c[1]]
        assert len(metadata_calls) == 1

    def test_a_resolver_without_metadata_names_the_fix(self) -> None:
        session = StubSession()
        session.answer("/.well-known/oauth-protected-resource", Answer(404, b"nope", "text/plain"))
        auth, _ = make_auth(session)
        with pytest.raises(BenelogError, match="does not publish OAuth metadata"):
            auth.issuer()

    def test_metadata_without_servers_is_refused(self) -> None:
        session = StubSession()
        session.answer("/.well-known/oauth-protected-resource", Answer(200, {"resource": RESOLVER}))
        auth, _ = make_auth(session)
        with pytest.raises(BenelogError, match="names no authorization server"):
            auth.issuer()


class TestTokenExchange:
    def test_an_access_token_is_minted_from_the_offline_token(self) -> None:
        session = StubSession()
        wire_discovery(session)
        session.answer("/token", Answer(200, {"access_token": "fresh", "expires_in": 300}))
        auth, _ = make_auth(session)
        assert auth.bearer() == "fresh"
        grant = next(kw for m, url, kw in session.calls if url.endswith("/token"))["data"]
        assert grant["grant_type"] == "refresh_token"
        assert grant["refresh_token"] == "offline.token.value"
        assert "client_secret" not in grant

    def test_the_bearer_is_cached_until_it_nears_expiry(self) -> None:
        session = StubSession()
        wire_discovery(session)
        session.answer("/token", Answer(200, {"access_token": "fresh", "expires_in": 300}))
        auth, _ = make_auth(session)
        auth.bearer()
        auth.bearer()
        assert len([1 for _, url, _ in session.calls if url.endswith("/token")]) == 1

    def test_invalidate_forces_a_new_mint(self) -> None:
        session = StubSession()
        wire_discovery(session)
        session.answer("/token", Answer(200, {"access_token": "fresh", "expires_in": 300}))
        auth, _ = make_auth(session)
        auth.bearer()
        auth.invalidate()
        auth.bearer()
        assert len([1 for _, url, _ in session.calls if url.endswith("/token")]) == 2

    def test_a_rotated_offline_token_reaches_the_store_at_once(self) -> None:
        # Keycloak with "Revoke Refresh Token" replaces the offline token on
        # every exchange. Losing the replacement locks the connector out with a
        # credential that still looks correct on screen.
        session = StubSession()
        wire_discovery(session)
        session.answer(
            "/token",
            Answer(200, {"access_token": "fresh", "expires_in": 300, "refresh_token": "rotated"}),
        )
        auth, store = make_auth(session)
        auth.bearer()
        assert store.offline_token == "rotated"

    def test_the_subject_is_recorded_from_the_access_token(self) -> None:
        session = StubSession()
        wire_discovery(session)
        access = jwt_for({"preferred_username": "svc-connector"})
        session.answer("/token", Answer(200, {"access_token": access, "expires_in": 300}))
        auth, store = make_auth(session)
        auth.bearer()
        assert store.subject == "svc-connector"

    def test_an_issuer_mismatch_is_not_reported_as_revoked(self) -> None:
        session = StubSession()
        wire_discovery(session)
        session.answer(
            "/token",
            Answer(
                400,
                {
                    "error": "invalid_grant",
                    "error_description": "Invalid token issuer. Expected 'https://other'",
                },
            ),
        )
        auth, _ = make_auth(session)
        with pytest.raises(BenelogError) as caught:
            auth.bearer()
        assert "issued by a different URL" in str(caught.value)
        assert "revoked" not in str(caught.value)

    def test_a_revoked_token_says_so(self) -> None:
        session = StubSession()
        wire_discovery(session)
        session.answer(
            "/token",
            Answer(400, {"error": "invalid_grant", "error_description": "Session not active"}),
        )
        auth, _ = make_auth(session)
        with pytest.raises(BenelogError, match="no longer accepted"):
            auth.bearer()


class TestTokenIntrospection:
    def test_type_and_subject_are_read_without_verification(self) -> None:
        token = jwt_for({"typ": "Offline", "preferred_username": "svc"})
        assert token_type(token) == "Offline"
        assert token_subject(token) == "svc"

    def test_an_opaque_token_answers_empty(self) -> None:
        assert token_type("opaque-value") == ""
        assert token_subject("opaque-value") == ""
