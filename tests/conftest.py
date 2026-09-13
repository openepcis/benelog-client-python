# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 benelog GmbH & Co. KG
"""Shared stubs: a session that answers from a script, never the network."""

import base64
import json
from typing import Any

import pytest

from openepcis_client.core import auth as auth_module


class Answer:
    """The little of a requests.Response the client actually reads."""

    def __init__(
        self, status_code: int, body: Any = None, content_type: str = "application/json"
    ) -> None:
        self.status_code = status_code
        if isinstance(body, (bytes, bytearray)):
            self.content = bytes(body)
        elif body is None:
            self.content = b""
        else:
            self.content = json.dumps(body).encode()
        self.text = self.content.decode(errors="replace")
        self.headers = {"Content-Type": content_type}

    def json(self) -> Any:
        return json.loads(self.content)


class StubSession:
    """Answers GET/POST/request from per-URL-substring scripts, records calls."""

    def __init__(self) -> None:
        self.rules: list[tuple[str, Answer | Exception]] = []
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def answer(self, url_part: str, answer: Answer | Exception) -> None:
        self.rules.append((url_part, answer))

    def _match(self, url: str) -> Answer:
        for part, answer in self.rules:
            if part in url:
                if isinstance(answer, Exception):
                    raise answer
                return answer
        raise AssertionError(f"no scripted answer for {url}")

    def get(self, url: str, **kw: Any) -> Answer:
        self.calls.append(("GET", url, kw))
        return self._match(url)

    def post(self, url: str, **kw: Any) -> Answer:
        self.calls.append(("POST", url, kw))
        return self._match(url)

    def request(self, method: str, url: str, **kw: Any) -> Answer:
        self.calls.append((method, url, kw))
        return self._match(url)


def jwt_for(claims: dict[str, Any]) -> str:
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


@pytest.fixture(autouse=True)
def clean_discovery_caches() -> Any:
    auth_module._PROTECTED_RESOURCE.clear()
    auth_module._OIDC_CONFIG.clear()
    yield
    auth_module._PROTECTED_RESOURCE.clear()
    auth_module._OIDC_CONFIG.clear()
