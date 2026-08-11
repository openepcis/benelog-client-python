# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 benelog GmbH & Co. KG
"""Placing values at GS1 term paths, and the value shapes the catalog wants."""

import pytest

from benelog_client.masterdata.payload import boolean_text, localized, place, quantity


class TestPlace:
    def test_a_plain_key(self) -> None:
        document: dict = {}
        place(document, "productName", {"en": "Chair"})
        assert document == {"productName": {"en": "Chair"}}

    def test_a_nested_path_builds_its_containers(self) -> None:
        document: dict = {}
        place(document, "brand.brandName", "Acme")
        place(document, "countryOfOrigin.countryCode", "DE")
        assert document == {
            "brand": {"brandName": "Acme"},
            "countryOfOrigin": {"countryCode": "DE"},
        }

    def test_a_list_segment_builds_a_single_element_list(self) -> None:
        document: dict = {}
        place(document, "targetMarket[].targetMarketCountries.countryCode", "DE")
        assert document == {"targetMarket": [{"targetMarketCountries": {"countryCode": "DE"}}]}

    def test_two_paths_through_the_same_list_share_the_element(self) -> None:
        document: dict = {}
        place(document, "contactPoint[].email", "a@example.test")
        place(document, "contactPoint[].telephone", "+49 1")
        assert document == {"contactPoint": [{"email": "a@example.test", "telephone": "+49 1"}]}

    def test_a_trailing_list_segment_wraps_the_value(self) -> None:
        document: dict = {}
        place(document, "referencedFileURL[]", "https://x.test/f.pdf")
        assert document == {"referencedFileURL": ["https://x.test/f.pdf"]}

    def test_a_scalar_in_the_way_is_replaced_by_the_container(self) -> None:
        document: dict = {"brand": "Acme"}
        place(document, "brand.brandName", "Acme")
        assert document == {"brand": {"brandName": "Acme"}}

    @pytest.mark.parametrize("path", ["", ".", "a..b", ".a", "a."])
    def test_an_unusable_path_is_a_configuration_error(self, path: str) -> None:
        with pytest.raises(ValueError, match="not a usable"):
            place({}, path, "x")


class TestShapes:
    def test_a_quantity_carries_value_and_unit(self) -> None:
        assert quantity(0.75, "KGM") == {"value": 0.75, "unitCode": "KGM"}

    def test_zero_is_not_a_measurement(self) -> None:
        # Zero is the ERP default for "not filled in"; sending it would
        # satisfy a requirement falsely.
        assert quantity(0, "KGM") is None

    def test_a_quantity_without_a_unit_is_dropped(self) -> None:
        assert quantity(0.75, "") is None

    def test_boolean_text_is_a_string(self) -> None:
        assert boolean_text(True) == "true"
        assert boolean_text(0) == "false"

    def test_localized_drops_empty_entries(self) -> None:
        assert localized({"de": "Stuhl", "en": "  ", "fr": ""}) == {"de": "Stuhl"}

    def test_localized_with_nothing_left_is_none(self) -> None:
        assert localized({"de": ""}) is None
