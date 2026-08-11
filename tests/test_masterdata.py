# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 benelog GmbH & Co. KG
"""The masterdata service: upsert semantics, bulk reporting, GPC mapping."""

import csv
import io
from typing import Any

import pytest

from benelog_client.core import gs1
from benelog_client.masterdata import InvalidKey, Masterdata
from benelog_client.masterdata import service as service_module

GTIN = gs1.with_check_digit("401234567890")
GTIN_2 = gs1.with_check_digit("401234567891")
GTIN_3 = gs1.with_check_digit("401234567892")
GLN = gs1.with_check_digit("401234500001")


class StubClient:
    """Records calls; answers post_file from a scripted sequence."""

    def __init__(self, bulk_answers: list[dict[str, Any]] | None = None) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        self.bulk_answers = bulk_answers or []

    def put(self, path: str, payload: Any) -> Any:
        self.calls.append(("PUT", path, payload))
        return {"ok": True}

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        self.calls.append(("GET", path, params))
        return []

    def post_file(self, path: str, filename: str, content: bytes, form: Any = None) -> Any:
        self.calls.append(("POST_FILE", path, content))
        return self.bulk_answers[min(len(self.calls) - 1, len(self.bulk_answers) - 1)]


def masterdata(client: StubClient) -> Masterdata:
    return Masterdata(client)  # type: ignore[arg-type]


def rows_sent(content: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(content.decode())))


class TestUpsert:
    def test_a_product_goes_to_its_key_path_with_the_key_term_set(self) -> None:
        client = StubClient()
        document = {"productName": {"en": "Chair"}}
        masterdata(client).upsert_product(f" {GTIN[:4]}-{GTIN[4:]} ", document)
        verb, path, payload = client.calls[0]
        assert (verb, path) == ("PUT", f"/products/{GTIN}")
        assert payload["gtin"] == GTIN
        assert payload["productName"] == {"en": "Chair"}
        assert "gtin" not in document  # the caller's document is not mutated

    def test_an_organization_carries_its_gln_term(self) -> None:
        client = StubClient()
        masterdata(client).upsert_organization(GLN, {})
        verb, path, payload = client.calls[0]
        assert (verb, path) == ("PUT", f"/organizations/{GLN}")
        assert payload["globalLocationNumber"] == GLN

    def test_an_invalid_key_never_reaches_the_wire(self) -> None:
        client = StubClient()
        with pytest.raises(InvalidKey) as caught:
            masterdata(client).upsert_product("4012345678", {})
        assert caught.value.problem.kind == "GTIN"
        assert client.calls == []


class TestBulk:
    def test_the_csv_carries_the_manifest_header_and_nothing_else(self) -> None:
        client = StubClient([{"total": 1, "successCount": 1, "errorCount": 0, "errors": []}])
        report = masterdata(client).bulk_products(
            [{"gtin": GTIN, "productName_en": "Chair", "unknownColumn": "dropped"}]
        )
        sent = rows_sent(client.calls[0][2])
        assert list(sent[0].keys()) == [
            "gtin",
            "productName_en",
            "gpcCategoryCode",
            "brandName",
            "countryOfOriginCode",
            "hasBatchLotNumber",
            "hasSerialNumber",
            "isAnonymousAccessAllowed",
        ]
        assert sent[0]["gtin"] == GTIN
        assert report.accepted == 1
        assert report.failures == ()

    def test_an_invalid_key_is_refused_here_not_sent(self) -> None:
        client = StubClient([{"successCount": 1, "errors": []}])
        report = masterdata(client).bulk_products(
            [{"gtin": "not-a-gtin"}, {"gtin": GTIN, "productName_en": "Chair"}]
        )
        assert len(rows_sent(client.calls[0][2])) == 1
        assert report.total == 2
        assert report.accepted == 1
        assert [(f.row, f.code) for f in report.failures] == [(1, "INVALID_KEY")]

    def test_a_duplicate_counts_as_present_not_failed(self) -> None:
        # Bulk loading only creates; a key the catalog already holds is the
        # state the load was aiming for.
        client = StubClient(
            [
                {
                    "successCount": 0,
                    "errors": [
                        {"rowNumber": 1, "errorCode": "DUPLICATE_GTIN", "errorMessage": "held"}
                    ],
                }
            ]
        )
        report = masterdata(client).bulk_products([{"gtin": GTIN}])
        assert report.duplicates == 1
        assert report.failures == ()

    def test_server_row_numbers_survive_chunking_and_local_skips(self) -> None:
        # Three rows: the first is refused here, the remaining two are sent in
        # two chunks of one. The server reports its failure as row 1 of the
        # second upload; the caller must read it as row 3 of the input.
        client = StubClient(
            [
                {"successCount": 1, "errors": []},
                {
                    "successCount": 0,
                    "errors": [{"rowNumber": 1, "errorCode": "MISSING_NAME", "errorMessage": "x"}],
                },
            ]
        )
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(service_module, "CHUNK_ROWS", 1)
            report = masterdata(client).bulk_products(
                [{"gtin": "bad"}, {"gtin": GTIN_2}, {"gtin": GTIN_3}]
            )
        assert [(f.row, f.code) for f in report.failures] == [
            (1, "INVALID_KEY"),
            (3, "MISSING_NAME"),
        ]
        assert report.accepted == 1

    def test_organizations_use_their_own_endpoint_and_key(self) -> None:
        client = StubClient([{"successCount": 1, "errors": []}])
        masterdata(client).bulk_organizations([{"globalLocationNumber": GLN}])
        assert client.calls[0][1] == "/bulk/organizations"
        assert rows_sent(client.calls[0][2])[0]["globalLocationNumber"] == GLN


class TestGpcSearch:
    def test_nodes_are_mapped_and_codeless_ones_dropped(self) -> None:
        client = StubClient()
        client.get = lambda path, params=None: [  # type: ignore[method-assign]
            {"code": "10003269", "title": "Chairs", "definition": "d", "path": "Furniture > ..."},
            {"title": "no code"},
        ]
        nodes = masterdata(client).search_gpc("  chair ")
        assert len(nodes) == 1
        assert nodes[0].code == "10003269"
        assert nodes[0].lineage == "Furniture > ..."
