# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 benelog GmbH & Co. KG
"""Event shape, identifier form, and what a capture receipt is worth."""

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from benelog_client.core.client import Client
from benelog_client.core.config import ClientConfig
from benelog_client.events import (
    Capture,
    Query,
    aggregation_event,
    cbv,
    document,
    event_id,
    instance_uri,
    object_event,
    quantity_element,
    sgln,
    sscc_uri,
)

from .conftest import Answer, StubSession

GTIN = "09521234000012"
NOON = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)


class TestIdentifiers:
    def test_a_bare_gtin_is_the_model(self) -> None:
        assert instance_uri(GTIN) == "https://id.gs1.org/01/" + GTIN

    def test_a_lot_makes_a_class_and_a_serial_an_instance(self) -> None:
        assert instance_uri(GTIN, lot="L1").endswith("/10/L1")
        assert instance_uri(GTIN, serial="S1").endswith("/21/S1")

    def test_qualifiers_keep_gs1_path_order_whatever_the_call_order(self) -> None:
        # A lot precedes a serial in the path. Reversed, it is a different
        # string for the same unit, which defeats a canonical identifier.
        assert instance_uri(GTIN, serial="S1", lot="L1") == (
            f"https://id.gs1.org/01/{GTIN}/10/L1/21/S1"
        )

    def test_a_serial_with_a_slash_stays_one_path_segment(self) -> None:
        assert instance_uri(GTIN, serial="A/B").endswith("/21/A%2FB")

    def test_a_location_is_an_sgln_and_a_pallet_an_sscc(self) -> None:
        assert sgln("4068194000009") == "https://id.gs1.org/414/4068194000009"
        assert sscc_uri("340681940000000018").startswith("https://id.gs1.org/00/")


class TestEventIdentity:
    def test_the_same_facts_give_the_same_id(self) -> None:
        assert event_id("odoo", "WH/IN/0001", cbv.RECEIVING) == event_id(
            "odoo", "WH/IN/0001", cbv.RECEIVING
        )

    def test_different_facts_give_different_ids(self) -> None:
        assert event_id("odoo", "WH/IN/0001", cbv.RECEIVING) != event_id(
            "odoo", "WH/IN/0002", cbv.RECEIVING
        )

    def test_it_is_a_uuid_uri(self) -> None:
        assert event_id("x").startswith("urn:uuid:")


class TestObjectEvent:
    def test_a_receipt_carries_what_where_and_why(self) -> None:
        event = object_event(
            action=cbv.OBSERVE,
            event_time=NOON,
            biz_step=cbv.RECEIVING,
            disposition=cbv.IN_PROGRESS,
            epcs=[instance_uri(GTIN, serial="S1")],
            read_point="4068194000009",
            biz_transactions=[(cbv.PO, "PO0001")],
        )
        assert event["type"] == "ObjectEvent"
        assert event["bizStep"] == "receiving"
        assert event["readPoint"] == {"id": "https://id.gs1.org/414/4068194000009"}
        assert event["bizTransactionList"] == [{"type": "po", "bizTransaction": "PO0001"}]

    def test_a_lot_goes_to_the_quantity_list_not_the_epc_list(self) -> None:
        event = object_event(
            action=cbv.OBSERVE,
            event_time=NOON,
            quantities=[quantity_element(instance_uri(GTIN, lot="L1"), 12)],
        )
        assert "epcList" not in event
        assert event["quantityList"] == [
            {"epcClass": f"https://id.gs1.org/01/{GTIN}/10/L1", "quantity": 12}
        ]

    def test_a_counted_quantity_carries_no_unit(self) -> None:
        assert "uom" not in quantity_element("x", 3)
        assert quantity_element("x", 3.5, "KGM")["uom"] == "KGM"

    def test_a_class_may_be_observed_without_a_quantity(self) -> None:
        assert quantity_element("x") == {"epcClass": "x"}

    def test_the_offset_is_the_observers_not_utc(self) -> None:
        berlin = timezone(timedelta(hours=2))
        event = object_event(action=cbv.OBSERVE, event_time=NOON.astimezone(berlin))
        assert event["eventTimeZoneOffset"] == "+02:00"
        # The instant itself stays UTC — offset and instant are separate facts.
        assert event["eventTime"] == "2026-08-27T12:00:00.000Z"

    def test_a_naive_time_is_read_as_utc_rather_than_guessed(self) -> None:
        naive = datetime(2026, 8, 27, 12, 0)  # noqa: DTZ001 — that is the case under test
        event = object_event(action=cbv.OBSERVE, event_time=naive)
        assert event["eventTime"] == "2026-08-27T12:00:00.000Z"
        assert event["eventTimeZoneOffset"] == "+00:00"


class TestAggregationEvent:
    def test_a_pallet_holds_its_children(self) -> None:
        event = aggregation_event(
            action=cbv.ADD,
            event_time=NOON,
            parent_id=sscc_uri("340681940000000018"),
            biz_step=cbv.PACKING,
            child_epcs=[instance_uri(GTIN, serial="S1")],
        )
        assert event["type"] == "AggregationEvent"
        assert event["parentID"].endswith("/00/340681940000000018")
        assert event["childEPCs"] == [f"https://id.gs1.org/01/{GTIN}/21/S1"]


class TestDocument:
    def test_the_context_sits_on_the_document_not_the_event(self) -> None:
        wrapped = document([object_event(action=cbv.OBSERVE, event_time=NOON)])
        assert wrapped["@context"] == [
            "https://ref.gs1.org/standards/epcis/2.0.0/epcis-context.jsonld"
        ]
        assert "@context" not in wrapped["epcisBody"]["eventList"][0]


class ScriptedSession(StubSession):
    """Answers by URL substring, so a POST and a GET can differ."""

    def __init__(self, answers: dict[str, Answer]) -> None:
        super().__init__()
        self.answers = answers

    def request(self, method: str, url: str, **kw: Any) -> Answer:
        self.calls.append((method, url, kw))
        for fragment, answer in self.answers.items():
            if fragment in url:
                return answer
        raise AssertionError("no answer scripted for " + url)


class FixedAuth:
    """Always the same bearer — the only credential this library knows."""

    def bearer(self) -> str:
        return "token"

    def invalidate(self) -> None:
        pass


def capture_with(answers: dict[str, Answer]) -> Capture:
    client = Client(
        ClientConfig(base_url="https://api.example.test"),
        FixedAuth(),  # type: ignore[arg-type]
        session=ScriptedSession(answers),
    )
    return Capture(client)


def accepted(location: str = "/capture/j1") -> Answer:
    answer = Answer(202)
    if location:
        answer.headers["Location"] = location
    return answer


class TestCapture:
    def test_the_job_comes_from_the_location_header(self) -> None:
        capture = capture_with({"/capture": accepted("/capture/abc-123")})
        receipt = capture.submit(document([object_event(action=cbv.OBSERVE, event_time=NOON)]))
        assert receipt.job == "abc-123"
        assert receipt.answerable

    def test_an_absolute_location_works_the_same(self) -> None:
        capture = capture_with({"/capture": accepted("https://api.example.test/capture/j9")})
        assert capture.submit(document([])).job == "j9"

    def test_the_minted_event_ids_travel_with_the_receipt(self) -> None:
        capture = capture_with({"/capture": accepted()})
        event = object_event(
            action=cbv.OBSERVE, event_time=NOON, event_identifier=event_id("a", "b")
        )
        assert capture.submit(document([event])).event_ids == (event_id("a", "b"),)

    def test_an_accepted_document_is_not_yet_a_stored_one(self) -> None:
        # The whole reason submit returns a receipt: 202 means custody, not
        # validity. A connector that reports success here reports a delivery
        # the repository may still refuse.
        capture = capture_with(
            {
                "/capture/j1": Answer(200, {"running": True, "success": False}),
                "/capture": accepted(),
            }
        )
        assert capture.outcome(capture.submit(document([]))).settled is False

    def test_a_rejection_keeps_the_repositorys_own_words(self) -> None:
        capture = capture_with(
            {
                "/capture/j1": Answer(
                    200,
                    {
                        "running": False,
                        "success": False,
                        "errors": [{"title": "epcList[0] is not a URI"}],
                    },
                )
            }
        )
        outcome = capture.outcome("j1")
        assert outcome.settled and not outcome.success
        assert outcome.errors == ("epcList[0] is not a URI",)

    def test_a_job_the_repository_does_not_know_is_unknown_not_stored(self) -> None:
        # A refusal and a forgotten job answer alike, so neither may be read as
        # a delivery.
        capture = capture_with({"/capture/j1": Answer(404, {"title": "not found"})})
        outcome = capture.outcome("j1")
        assert outcome.settled and not outcome.known and not outcome.success

    def test_a_receipt_without_a_job_cannot_be_asked_about(self) -> None:
        capture = capture_with({"/capture": accepted(location="")})
        receipt = capture.submit(document([]))
        assert not receipt.answerable
        with pytest.raises(ValueError):
            capture.outcome(receipt)


class TestCheck:
    def test_a_missing_capture_role_is_named_as_such(self) -> None:
        capture = capture_with({"/capture": Answer(403, {"title": "forbidden"})})
        assert "capture" in capture.check()

    def test_the_resolvers_host_is_diagnosed_rather_than_reported_as_broken(self) -> None:
        capture = capture_with({"/capture": Answer(404, {"title": "not found"})})
        assert "resolver" in capture.check()

    def test_silence_means_it_works(self) -> None:
        capture = capture_with({"/capture": Answer(200, {"eventList": []})})
        assert capture.check() == ""


def query_with(answers: dict[str, Answer]) -> Query:
    client = Client(
        ClientConfig(base_url="https://api.example.test"),
        FixedAuth(),  # type: ignore[arg-type]
        session=ScriptedSession(answers),
    )
    return Query(client)


def page(events: list[dict[str, Any]], next_token: str = "") -> Answer:
    body: dict[str, Any] = {"epcisBody": {"eventList": events}}
    if next_token:
        body["nextPageToken"] = next_token
    return Answer(200, body)


class TestQuery:
    def test_a_watermark_is_sent_as_ge_record_time(self) -> None:
        query = query_with({"/events": page([])})
        list(query.since("2026-08-27T22:13:29Z"))
        _, _, kw = query._client._session.calls[0]  # type: ignore[attr-defined]
        assert kw["params"]["GE_recordTime"] == "2026-08-27T22:13:29Z"

    def test_it_walks_pages_until_the_token_runs_out(self) -> None:
        session = ScriptedSession({})
        pages = [page([{"eventID": "a"}], "t1"), page([{"eventID": "b"}])]

        def answer(method: str, url: str, **kw: Any) -> Answer:
            session.calls.append((method, url, kw))
            return pages[len(session.calls) - 1]

        session.request = answer  # type: ignore[method-assign]
        client = Client(
            ClientConfig(base_url="https://api.example.test"),
            FixedAuth(),  # type: ignore[arg-type]
            session=session,
        )
        assert [e["eventID"] for e in Query(client).since("2026-08-27T22:13:29Z")] == ["a", "b"]
        # The second call continues the first rather than starting over.
        assert session.calls[1][2]["params"]["nextPageToken"] == "t1"
        assert "GE_recordTime" not in session.calls[1][2]["params"]

    def test_a_repository_that_never_stops_paging_does_not_run_forever(self) -> None:
        query = query_with({"/events": page([{"eventID": "a"}], "always")})
        assert len(list(query.since("2026-08-27T22:13:29Z", pages=3))) == 3

    def test_an_identifier_is_one_path_segment(self) -> None:
        query = query_with({"/epcs/": page([])})
        query.for_epc("https://id.gs1.org/01/09521234000012/21/1")
        _, url, _ = query._client._session.calls[0]  # type: ignore[attr-defined]
        assert "/epcs/https%3A%2F%2Fid.gs1.org%2F01%2F09521234000012%2F21%2F1/events" in url

    def test_missing_the_query_role_is_named_not_swallowed(self) -> None:
        query = query_with({"/events": Answer(403)})
        assert "'query' role" in query.check()

    def test_a_repository_that_answers_is_no_complaint(self) -> None:
        assert query_with({"/events": page([])}).check() == ""
