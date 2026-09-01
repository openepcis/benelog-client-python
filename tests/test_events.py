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
    error_declaration,
    gtin14,
    idempotency_key,
    instance_uri,
    object_event,
    quantity_element,
    sgln,
    sscc_uri,
    stamp_event_ids,
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


class TestIdempotencyKey:
    """The sender's own handle on a movement — no longer the event's name."""

    def test_the_same_facts_give_the_same_key(self) -> None:
        assert idempotency_key("odoo", "WH/IN/0001", cbv.RECEIVING) == idempotency_key(
            "odoo", "WH/IN/0001", cbv.RECEIVING
        )

    def test_different_facts_give_different_keys(self) -> None:
        assert idempotency_key("odoo", "WH/IN/0001", cbv.RECEIVING) != idempotency_key(
            "odoo", "WH/IN/0002", cbv.RECEIVING
        )

    def test_it_is_a_uuid_uri(self) -> None:
        assert idempotency_key("x").startswith("urn:uuid:")


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
            action=cbv.OBSERVE, event_time=NOON, event_identifier=idempotency_key("a", "b")
        )
        assert capture.submit(document([event])).event_ids == (idempotency_key("a", "b"),)

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


class TestEventHashIdentity:
    """The eventID as a property of the event, and where that still holds.

    The two implementations of the canonicalisation — this one (Python 1.9.3,
    RalphTro/EECC) and the platform's Java module — agree on the plain event
    shapes and disagree on several richer ones. That is measured, not assumed:
    over the 37 capture documents in ``openepcis-test-resources`` they agree on
    12 and differ on 22 (3 the Python side cannot parse at all). The known
    causes are ordering ones — ``sourceList``/``destinationList`` come out in
    the opposite order, ``parentID`` lands in a different place, and Java leaves
    ``certificationInfo`` out of the pre-hash while Python hashes it.

    So these tests pin the shapes we actually mint, and say which they are.
    """

    def test_a_commissioning_event_hashes_to_the_same_value_as_the_java_side(self) -> None:
        # The measured cross-language vector: byte-identical to what
        # CommissioningEventsTest.goldenValues pins in openepcis-connectors.
        stamped = stamp_event_ids(
            document(
                [
                    object_event(
                        action="ADD",
                        event_time=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc),
                        biz_step="commissioning",
                        disposition="active",
                        quantities=[
                            quantity_element("https://id.gs1.org/01/09520123456788/10/CHARGE-1")
                        ],
                        read_point="9520999999990",
                    )
                ],
                creation_time=datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc),
            )
        )
        assert stamped["epcisBody"]["eventList"][0]["eventID"] == (
            "ni:///sha-256;"
            "f895a478db42352042ceb07ac96a607765697ca0a8e6c3fe76cbdefc537d185a?ver=CBV2.0"
        )

    def test_the_same_statement_stamps_the_same_identifier(self) -> None:
        def build(creation: datetime) -> str:
            stamped = stamp_event_ids(
                document(
                    [
                        object_event(
                            action="ADD",
                            event_time=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc),
                            biz_step="commissioning",
                            epcs=["https://id.gs1.org/01/09520123456788/21/SN-1"],
                        )
                    ],
                    creation_time=creation,
                )
            )
            return str(stamped["epcisBody"]["eventList"][0]["eventID"])

        # The document's creationDate differs; the event's identity does not,
        # because creationDate is not part of the event.
        assert build(datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)) == build(
            datetime(2026, 9, 1, 6, 30, tzinfo=timezone.utc)
        )

    def test_every_event_in_a_document_gets_its_own_identifier_in_order(self) -> None:
        first = object_event(
            action="ADD",
            event_time=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc),
            epcs=["https://id.gs1.org/01/09520123456788/21/SN-1"],
        )
        second = object_event(
            action="ADD",
            event_time=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc),
            epcs=["https://id.gs1.org/01/09520123456788/21/SN-2"],
        )
        events = stamp_event_ids(document([first, second]))["epcisBody"]["eventList"]

        assert events[0]["epcList"] == first["epcList"]
        assert events[1]["epcList"] == second["epcList"]
        assert events[0]["eventID"] != events[1]["eventID"]
        assert all(str(event["eventID"]).startswith("ni:///sha-256;") for event in events)

    def test_a_prefix_from_an_earlier_document_does_not_leak_into_the_next(self) -> None:
        # The library keeps its namespace table in a module global and never
        # resets it. In a long-lived worker serving several tenants, a prefix
        # bound in one document would otherwise change how the next one
        # canonicalises — weeks later, in production only.
        with_prefix = {
            "@context": [
                "https://ref.gs1.org/standards/epcis/2.0.0/epcis-context.jsonld",
                {"ex": "https://one.example.test/ns/"},
            ],
            "type": "EPCISDocument",
            "schemaVersion": "2.0",
            "creationDate": "2026-08-23T12:00:00.000Z",
            "epcisBody": {
                "eventList": [
                    {
                        "type": "ObjectEvent",
                        "eventTime": "2026-08-10T09:00:00.000Z",
                        "eventTimeZoneOffset": "+00:00",
                        "action": "ADD",
                        "epcList": ["https://id.gs1.org/01/09520123456788/21/SN-1"],
                        "ex:note": "first",
                    }
                ]
            },
        }
        plain = document(
            [
                object_event(
                    action="ADD",
                    event_time=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc),
                    epcs=["https://id.gs1.org/01/09520123456788/21/SN-1"],
                )
            ],
            creation_time=datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc),
        )

        alone = stamp_event_ids(plain)["epcisBody"]["eventList"][0]["eventID"]
        stamp_event_ids(with_prefix)
        after = stamp_event_ids(plain)["epcisBody"]["eventList"][0]["eventID"]

        assert alone == after

    def test_a_document_without_events_is_left_alone(self) -> None:
        empty = document([])
        assert stamp_event_ids(empty) == empty


class TestErrorDeclaration:
    """Correcting by declaration rather than by edit."""

    def test_a_correction_carries_the_identity_of_what_it_corrects(self) -> None:
        # The declaration fields are outside the canonical hash, so the same
        # event with an error declaration attached hashes to the same value.
        # That is the whole mechanism: a correction does not have to look the
        # erroneous event's identifier up, it arrives at it.
        def build(declaration: dict[str, Any] | None) -> str:
            events = stamp_event_ids(
                document(
                    [
                        object_event(
                            action="OBSERVE",
                            event_time=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc),
                            biz_step="shipping",
                            epcs=["https://id.gs1.org/01/09520123456788/21/SN-1"],
                            error_declaration=declaration,
                        )
                    ],
                    creation_time=datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc),
                )
            )["epcisBody"]["eventList"][0]
            return str(events["eventID"])

        assert build(None) == build(
            error_declaration(
                reason=cbv.DID_NOT_OCCUR,
                declaration_time=datetime(2026, 8, 29, 10, 0, tzinfo=timezone.utc),
            )
        )

    def test_the_declaration_says_when_and_why(self) -> None:
        declaration = error_declaration(
            reason=cbv.INCORRECT_DATA,
            declaration_time=datetime(2026, 8, 29, 10, 0, tzinfo=timezone.utc),
            corrective_event_ids=["ni:///sha-256;abc?ver=CBV2.0"],
        )
        assert declaration == {
            "declarationTime": "2026-08-29T10:00:00.000Z",
            "reason": "incorrect_data",
            "correctiveEventIDs": ["ni:///sha-256;abc?ver=CBV2.0"],
        }

    def test_a_withdrawn_event_has_nothing_to_correct(self) -> None:
        with pytest.raises(ValueError, match="did_not_occur"):
            error_declaration(
                reason=cbv.DID_NOT_OCCUR,
                declaration_time=datetime(2026, 8, 29, 10, 0, tzinfo=timezone.utc),
                corrective_event_ids=["ni:///sha-256;abc?ver=CBV2.0"],
            )

    def test_an_invented_reason_is_refused_here_rather_than_by_the_repository(self) -> None:
        with pytest.raises(ValueError, match="not a CBV error reason"):
            error_declaration(
                reason="wrong_data",
                declaration_time=datetime(2026, 8, 29, 10, 0, tzinfo=timezone.utc),
            )

    def test_an_aggregation_can_be_withdrawn_too(self) -> None:
        event = aggregation_event(
            action="ADD",
            event_time=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc),
            parent_id="https://id.gs1.org/00/095212340000000012",
            child_epcs=["https://id.gs1.org/01/09520123456788/21/SN-1"],
            error_declaration=error_declaration(
                reason=cbv.DID_NOT_OCCUR,
                declaration_time=datetime(2026, 8, 29, 10, 0, tzinfo=timezone.utc),
            ),
        )
        assert event["errorDeclaration"]["reason"] == "did_not_occur"


class TestDigitalLinkGtin:
    """AI 01 is fourteen digits, whatever the barcode says.

    An event carrying `/01/9521234000013` — thirteen digits, straight out of
    `product.barcode` — is accepted with a 202 and then rejected by the
    repository's validation with "Translation failed". Measured against
    api.dev.epcis.cloud on 2026-08-30, from a running Odoo.

    The older tests could not catch this: they built the expected identifier out
    of the same barcode field, so they asserted whatever the code produced.
    """

    def test_an_ean_is_padded_to_fourteen(self) -> None:
        assert instance_uri("9521234000013") == "https://id.gs1.org/01/09521234000013"
        assert instance_uri("9521234000013", lot="CHARGE-1") == (
            "https://id.gs1.org/01/09521234000013/10/CHARGE-1"
        )

    def test_shorter_gtins_are_padded_too(self) -> None:
        assert instance_uri("952000000002") == "https://id.gs1.org/01/00952000000002"
        assert instance_uri("95200007") == "https://id.gs1.org/01/00000095200007"

    def test_a_gtin14_is_left_as_it_is(self) -> None:
        assert instance_uri("09521234000013") == "https://id.gs1.org/01/09521234000013"

    def test_something_that_is_not_a_gtin_is_not_padded(self) -> None:
        # Cleaned like any key, but no digits invented in front of it.
        assert gtin14("ABC-123") == "ABC123"
        assert gtin14("123456789012345") == "123456789012345"
