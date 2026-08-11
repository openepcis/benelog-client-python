# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 benelog GmbH & Co. KG
"""The registry service: key pool, channels, credentials, verify, sync."""

from typing import Any, ClassVar

from benelog_client.registry import Registry
from benelog_client.registry.service import DRAW_TIMEOUT


class StubClient:
    """Records calls, answers each verb from a per-path script."""

    def __init__(self, answers: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        self.answers = answers or {}

    def _answer(self, verb: str, path: str, detail: Any) -> Any:
        self.calls.append((verb, path, detail))
        for part, answer in self.answers.items():
            if part in path:
                return answer
        return None

    def request(self, method: str, path: str, payload: Any = None, **kw: Any) -> Any:
        return self._answer(method, path, {"payload": payload, **kw})

    def get(self, path: str, params: Any = None) -> Any:
        return self._answer("GET", path, params)

    def put(self, path: str, payload: Any) -> Any:
        return self._answer("PUT", path, payload)

    def post(self, path: str, payload: Any = None) -> Any:
        return self._answer("POST", path, payload)

    def delete(self, path: str) -> Any:
        return self._answer("DELETE", path, None)


def registry(client: StubClient) -> Registry:
    return Registry(client)  # type: ignore[arg-type]


class TestKeyPool:
    def test_draw_posts_the_ai_with_the_long_timeout(self) -> None:
        client = StubClient({"/gs1de/keys/draw": {"key": "09521000000015", "ai": "01"}})
        assert registry(client).draw_key("01") == "09521000000015"
        verb, path, detail = client.calls[0]
        assert (verb, path) == ("POST", "/gs1de/keys/draw")
        assert detail["payload"] == {"ai": "01"}
        assert detail["timeout"] == DRAW_TIMEOUT

    def test_confirm_and_release_address_the_key(self) -> None:
        client = StubClient()
        registry(client).confirm_key("01", "09521000000015")
        registry(client).release_key("01", "09521000000015")
        assert client.calls[0][:2] == ("POST", "/gs1de/keys/01/09521000000015/confirm")
        assert client.calls[1][:2] == ("DELETE", "/gs1de/keys/01/09521000000015")


class TestChannels:
    def test_channels_are_mapped_with_their_required_terms(self) -> None:
        client = StubClient(
            {
                "/sync/channels": [
                    {
                        "id": "gs1de",
                        "displayName": "GS1 Germany",
                        "enabled": True,
                        "dryRun": False,
                        "configured": True,
                        "requiredTerms": {"PRODUCT": ["gs1:productName", "gs1:gpcCategoryCode"]},
                    },
                    {"displayName": "no id, dropped"},
                ]
            }
        )
        channels = registry(client).channels()
        assert len(channels) == 1
        assert channels[0].display_name == "GS1 Germany"
        assert channels[0].required_terms == {"PRODUCT": ("gs1:productName", "gs1:gpcCategoryCode")}


class TestCredentials:
    SLOT: ClassVar[dict[str, Any]] = {
        "label": "default",
        "credential": {
            "tokenStatus": "VALID",
            "licenceType": "GCP",
            "allowedGcps": ["4012345"],
            "primaryGcp": "4012345",
            "tokenValidatedAt": "2026-08-11T10:00:00Z",
            "authToken": "****abcd",
        },
    }

    def test_deposit_sends_the_token_and_answers_the_licensed_prefixes(self) -> None:
        client = StubClient({"/gs1de/my-credentials": self.SLOT})
        slot = registry(client).deposit_gs1_credential("the-token")
        verb, path, payload = client.calls[0]
        assert (verb, path) == ("PUT", "/gs1de/my-credentials")
        assert payload == {"authToken": "the-token"}
        assert slot.allowed_gcps == ("4012345",)
        assert slot.token_status == "VALID"
        assert slot.raw["authToken"] == "****abcd"  # masked by the platform

    def test_a_labelled_slot_has_its_own_path(self) -> None:
        client = StubClient({"/gs1de/my-credentials": self.SLOT})
        registry(client).deposit_gs1_credential("t", label="range-two")
        assert client.calls[0][1] == "/gs1de/my-credentials/range-two"

    def test_listing_maps_every_slot(self) -> None:
        client = StubClient({"/gs1de/my-credentials": [self.SLOT]})
        slots = registry(client).gs1_credentials()
        assert [s.label for s in slots] == ["default"]

    def test_revalidate_reads_the_bare_descriptor(self) -> None:
        # validate answers the masked descriptor without a label wrapper.
        client = StubClient({"/validate": self.SLOT["credential"]})
        slot = registry(client).revalidate_gs1_credential()
        assert client.calls[0][:2] == ("POST", "/gs1de/my-credentials/validate")
        assert slot.label == "default"
        assert slot.token_status == "VALID"

    def test_withdraw_deletes_the_slot(self) -> None:
        client = StubClient()
        registry(client).withdraw_gs1_credential("range-two")
        assert client.calls[0][:2] == ("DELETE", "/gs1de/my-credentials/range-two")


class TestVerify:
    def test_a_verified_key_carries_its_licensee(self) -> None:
        client = StubClient(
            {
                "/masterdata/verify/": {
                    "key": "09521000000015",
                    "verified": True,
                    "type": "GTIN",
                    "licenseeName": "Example GmbH",
                    "licenseeGln": "9521000000005",
                    "licenceKey": "9521000",
                    "licenceType": "GCP",
                }
            }
        )
        verification = registry(client).verified_by_gs1("09521000000015")
        assert verification.verified is True
        assert verification.licensee_name == "Example GmbH"

    def test_an_unverified_key_answers_false_without_licensee(self) -> None:
        client = StubClient({"/masterdata/verify/": {"key": "1", "verified": False}})
        verification = registry(client).verified_by_gs1("1")
        assert verification.verified is False
        assert verification.licensee_name == ""


class TestSync:
    def test_status_history_and_trigger_address_the_record(self) -> None:
        client = StubClient({"/sync/history/": [{"channel": "gs1de"}]})
        service = registry(client)
        service.sync_status("01", "09521000000015")
        history = service.sync_history("01", "09521000000015", channel="gs1de", size=5)
        service.trigger_sync("01", "09521000000015", "gs1de")
        assert client.calls[0][:2] == ("GET", "/sync/status/01/09521000000015")
        assert client.calls[1][2] == {"size": 5, "channel": "gs1de"}
        assert history == [{"channel": "gs1de"}]
        assert client.calls[2][2] == {"channel": "gs1de", "mode": "MANUAL"}
