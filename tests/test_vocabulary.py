# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 benelog GmbH & Co. KG
"""The pinned vocabulary manifest: structure, lookups, and the CSV headers.

The bulk column assertions are deliberately literal. The server-side CSV
parser matches column names and silently drops what it does not recognise, so
a renamed column produces a run where every row fails for no visible reason.
A red test here is the early warning.
"""

import pytest

from benelog_client.masterdata import vocabulary


class TestKinds:
    def test_product(self) -> None:
        kind = vocabulary.kind("PRODUCT")
        assert kind.key_term == "gtin"
        assert kind.key_type == "GTIN"
        assert kind.endpoint == "/products"
        assert kind.bulk_endpoint == "/bulk/products"
        assert "productName" in kind.required_terms

    def test_organization(self) -> None:
        kind = vocabulary.kind("ORGANIZATION")
        assert kind.key_term == "globalLocationNumber"
        assert kind.key_type == "GLN"
        assert kind.endpoint == "/organizations"

    def test_an_unknown_kind_is_a_key_error(self) -> None:
        with pytest.raises(KeyError):
            vocabulary.kind("PLACE")


class TestTerms:
    def test_every_term_names_a_known_kind_and_shape(self) -> None:
        shapes = {"text", "localized", "quantity", "boolean_text", "integer", "float", "date"}
        for entry in vocabulary.terms_for("PRODUCT") + vocabulary.terms_for("ORGANIZATION"):
            assert entry.kind in ("PRODUCT", "ORGANIZATION")
            assert entry.shape in shapes
            assert entry.scope in ("record", "bulk", "both")

    def test_a_bulk_scoped_term_always_names_its_column(self) -> None:
        for entry in vocabulary.terms_for("PRODUCT") + vocabulary.terms_for("ORGANIZATION"):
            if entry.scope in ("bulk", "both"):
                assert entry.bulk_column, entry.path

    def test_record_scope_excludes_bulk_only_terms(self) -> None:
        record_paths = {t.path for t in vocabulary.terms_for("PRODUCT", "record")}
        assert "netWeight" in record_paths
        assert "hasBatchLotNumber" not in record_paths

    def test_lookup_by_path(self) -> None:
        assert vocabulary.term("brand.brandName").bulk_column == "brandName"
        with pytest.raises(KeyError):
            vocabulary.term("no.such.term")


class TestBulkColumns:
    def test_the_product_header_matches_the_server_parser(self) -> None:
        assert vocabulary.bulk_columns("PRODUCT") == (
            "gtin",
            "productName_en",
            "gpcCategoryCode",
            "brandName",
            "countryOfOriginCode",
            "hasBatchLotNumber",
            "hasSerialNumber",
            "isAnonymousAccessAllowed",
        )

    def test_the_organization_header_matches_the_server_parser(self) -> None:
        assert vocabulary.bulk_columns("ORGANIZATION") == (
            "globalLocationNumber",
            "organizationName_en",
            "glnType",
            "organizationRole",
            "partyGLN",
            "department_en",
        )
