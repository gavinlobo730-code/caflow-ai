"""The practice's own mail waits in an outbox, is retried, and a bounce marks the address (ops-21).

WHAT WAS WRONG
    `email_service._send` posted to Resend synchronously from the request with a 10-second timeout and
    nothing retried: a notice that met one provider hiccup was never sent, a slow provider held a worker
    thread for ten seconds per mail, and an address that hard-bounced was mailed again by every sweep.

WHAT IS ASSERTED, in mock mode with the provider stubbed at the HTTP boundary (`httpx.post`), so the JSON
that would have reached Resend is what is read and no mail goes to anybody. The real-Postgres half (the
claim function, the privileges, the constraints) is `test_472_..._pg.py`.

  QUEUEING     against a database `deliver` answers `queued` and posts NOTHING from the caller's thread; the
               message waits in the outbox and its log row is `sent` with the detail `queued for delivery`;
               in mock mode the mail is posted directly as before;
  THE VERIFY   with the provider answering 500, 500, 200 the message is delivered on the THIRD attempt, the
  LINE         row records three attempts, the backoff is 1 then 5 minutes, every attempt carries the row id
               as its idempotency key, and the body and subject are blanked once it is sent;
  FAILURE      a 4xx is final at once, a run of 5xx is final after six attempts, a provider's MESSAGE is never
               stored (only its error name), and a message that fails for good flips its log row to `failed`
               and clears the dedupe key, so the next sweep tries again instead of reading "already sent";
  THE SWITCH   asked at `deliver`, again at `enqueue`, and AGAIN when the row is drained: a mail queued before
               somebody turned the practice's mail off is cancelled, not sent; so are the person's own
               preference and their still being active;
  CLAIMING     two drainers get disjoint rows, a row whose drainer died is handed out again after its lease
               and a message that has used up its attempts is abandoned, not sent;
  BOUNCES      the signature scheme (checked against an independent computation in this file), a permanent
               bounce or a complaint marks the address, the message and the delivery rows, a soft bounce
               writes nothing, an unsigned request writes nothing and is throttled, an unset secret is a 503
               and never an open door, and a marked address is not mailed again;
  D27          the recipients an outbox row may have are staff and a client's own portal contact, `enqueue` is
               called from one place, and the sink that redirects `_send` is set from one place.
"""
from __future__ import annotations

import ast
import base64
import hashlib
import hmac
import re
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))

import services.email_outbox_service as outbox  # noqa: E402
import services.email_events_service as events_service  # noqa: E402
import services.email_service as es  # noqa: E402
import services.practice_mail_service as mail  # noqa: E402
from domain import email_events  # noqa: E402
from repositories.user_repository import user_repo  # noqa: E402
from routers import email_webhooks  # noqa: E402

API = Path(__file__).resolve().parents[1]
FIRM = "firm-outbox-1"
PERSON = {"id": "u-1", "firm_id": FIRM, "full_name": "Priya Preparer",
          "email": "Priya@Gupta-CA.in", "role": "Executive", "is_active": True}
CONTACT = {"email": "accounts@acme-traders.in", "name": "Anita Accounts"}
SECRET = "whsec_" + base64.b64encode(b"a-test-signing-key-of-some-length").decode()
START = datetime(2026, 10, 14, 4, 0, tzinfo=timezone.utc)


class _Clock:
    def __init__(self):
        self.t = START

    def __call__(self):
        return self.t

    def advance(self, **kw):
        self.t += timedelta(**kw)


class _Resp:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body
        self.text = str(body)

    def json(self):
        return self._body


@pytest.fixture
def provider(monkeypatch):
    """The HTTP boundary. `script` is consumed in order; an exhausted script answers 200."""
    import httpx
    calls: list[dict] = []
    script: list = []

    def post(url, headers=None, json=None, timeout=None):
        calls.append({"url": url, "headers": dict(headers or {}), "json": json})
        status, body = script.pop(0) if script else (200, {"id": f"msg-{len(calls)}"})
        if isinstance(status, Exception):
            raise status
        return _Resp(status, body)

    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr(es, "_RESEND_API_KEY", "test-key")
    return calls, script


@pytest.fixture
def box(monkeypatch):
    """A memory outbox on a clock the test moves, queueing switched on, nobody kicked."""
    clock = _Clock()
    store = outbox.MemoryOutboxStore(clock=clock)
    outbox.set_store(store)
    outbox.set_queueing(True)
    outbox.set_kick(False)
    mail.reset_mock_stores()
    monkeypatch.setattr(user_repo, "find_by_id",
                        lambda uid, *, firm_id: PERSON if str(uid) == PERSON["id"] else None)
    yield store, clock
    outbox.set_store(None)
    outbox.set_queueing(None)
    outbox.set_kick(None)
    mail.reset_mock_stores()


def _assign(person=PERSON, task="t-1", title="File TDS return"):
    """Queue an assignment notice through the one door, as `task_assigned` does."""
    return mail.deliver(
        FIRM, "task_assigned", person, [mail.Ref("task", task)],
        lambda _r: es.send_task_assigned(str(person["email"]), person["full_name"], title,
                                         "Acme Traders", "20 Oct 2026"),
        dedupe=False)


def _sweep(person=PERSON, ref="r-1"):
    """A deduplicated sweep mail, which is the one whose log row blocks a re-send."""
    return mail.deliver(
        FIRM, "compliance_deadline", person, [mail.Ref("compliance_record", ref, "due_7")],
        lambda _r: es.send_compliance_due_soon(str(person["email"]), "Acme Traders", "GSTR-3B",
                                               "20 Oct 2026"),
        day=START.date())


def _only_row(store):
    rows = list(store.rows.values())
    assert len(rows) == 1, rows
    return rows[0]


# ── queueing ─────────────────────────────────────────────────────────────────────

def test_against_a_database_deliver_queues_and_posts_nothing_from_the_callers_thread(box, provider):
    store, _ = box
    calls, _ = provider
    assert _assign() == "queued"
    assert calls == [], "the provider was called from the request thread"
    row = _only_row(store)
    assert (row["status"], row["attempts"], row["origin"], row["event_type"]) == (
        "pending", 0, "practice_notice", "task_assigned")
    assert row["to_address"] == PERSON["email"] and row["recipient_kind"] == "staff"
    assert row["recipient_user_id"] == "u-1" and row["firm_id"] == FIRM
    assert row["subject"] == "New task assigned: File TDS return" and "Acme Traders" in row["html"]


def test_a_queued_mail_is_recorded_as_sent_with_the_detail_that_says_it_is_only_queued(box, provider):
    store, _ = box
    assert _sweep() == "queued"
    log = [r for r in mail.MOCK_LOG if r["event_type"] == "compliance_deadline"]
    assert len(log) == 1 and log[0]["status"] == "sent"
    assert log[0]["detail"] == outbox.QUEUED_DETAIL and log[0]["dedupe_key"]
    assert _only_row(store)["log_ids"] == [log[0]["id"]], "the outbox row must point at its own log row"
    assert _sweep() == "duplicate", "a sweep run twice queues once"
    assert len(store.rows) == 1


def test_in_mock_mode_the_mail_is_still_posted_directly_as_before(provider, monkeypatch):
    calls, _ = provider
    mail.reset_mock_stores()
    outbox.set_queueing(None)
    assert outbox.queueing_enabled() is False, "mock mode (no database) must not queue"
    monkeypatch.setattr(user_repo, "find_by_id", lambda uid, *, firm_id: PERSON)
    assert _assign() == "sent"
    assert len(calls) == 1
    monkeypatch.setattr(outbox, "_USE_MOCK", False)
    assert outbox.queueing_enabled() is True, "against a database it must queue"


def test_a_callback_that_never_reaches_the_transport_is_not_reported_queued(box, provider):
    store, _ = box
    status = mail.deliver(FIRM, "task_assigned", PERSON, [mail.Ref("task", "t-9")],
                          lambda _r: True, dedupe=False)
    assert status == "sent" and store.rows == {}


def test_the_sink_redirects_send_only_inside_a_delivery(box, provider):
    calls, _ = provider
    store, _ = box
    assert es._OUTBOX_SINK.get() is None
    assert es._send("someone@x.test", "subject", "<p>hi</p>") is True
    assert len(calls) == 1 and store.rows == {}, "a send outside `deliver` posts, as it always did"
    _assign()
    assert es._OUTBOX_SINK.get() is None, "the redirect must not outlive the delivery"


def test_a_second_message_inside_one_delivery_is_refused(box, provider):
    store, _ = box

    def two(_refs):
        es.send_task_assigned("a@x.test", "A", "T", "C", None)
        return es.send_task_assigned("b@x.test", "B", "T", "C", None)

    status = mail.deliver(FIRM, "task_assigned", PERSON, [mail.Ref("task", "t-2")], two, dedupe=False)
    assert status == "failed"


# ── the finding's verify line ────────────────────────────────────────────────────

def test_500_500_then_200_delivers_on_the_third_attempt_and_records_three_attempts(box, provider):
    store, clock = box
    calls, script = provider
    script.extend([(500, {"name": "internal_server_error", "message": "boom for priya@gupta-ca.in"}),
                   (500, {"name": "internal_server_error", "message": "boom"}),
                   (200, {"id": "resend-msg-42"})])
    _assign()
    row_id = _only_row(store)["id"]

    assert outbox.drain(store=store) == {"retry": 1}                  # attempt 1 fails
    row = _only_row(store)
    assert (row["status"], row["attempts"]) == ("pending", 1)
    assert row["next_attempt_at"] == START + timedelta(minutes=1), "first backoff is one minute"
    assert outbox.drain(store=store) == {}, "not due yet: nothing is claimed, nothing is posted"
    assert len(calls) == 1

    clock.advance(minutes=1)
    assert outbox.drain(store=store) == {"retry": 1}                  # attempt 2 fails
    assert _only_row(store)["next_attempt_at"] == clock() + timedelta(minutes=5)

    clock.advance(minutes=5)
    assert outbox.drain(store=store) == {"sent": 1}                   # attempt 3 delivers
    row = _only_row(store)
    assert (row["status"], row["attempts"]) == ("sent", 3)
    assert row["provider_message_id"] == "resend-msg-42" and row["sent_at"] == clock()
    assert len(calls) == 3
    assert {c["headers"]["Idempotency-Key"] for c in calls} == {row_id}, (
        "every attempt of one message carries its id, so a retry after an ambiguous failure is not two mails")
    assert calls[2]["json"]["to"] == [PERSON["email"]]
    assert calls[2]["json"]["subject"] == "New task assigned: File TDS return"


def test_a_finished_message_holds_no_text_and_no_provider_message(box, provider):
    store, clock = box
    calls, script = provider
    script.append((500, {"name": "internal_server_error",
                         "message": "could not deliver to priya@gupta-ca.in"}))
    _assign()
    outbox.drain(store=store)
    clock.advance(minutes=1)
    outbox.drain(store=store)
    row = _only_row(store)
    assert row["status"] == "sent" and row["subject"] == "" and row["html"] == ""
    blob = " ".join(str(v) for v in row.values() if isinstance(v, str)).lower()
    assert "could not deliver" not in blob, "a provider's message can quote the recipient"
    assert row["last_error_code"] is None, "a later success clears the last error"


def test_a_retry_leaves_the_error_name_and_never_the_message(box, provider):
    store, _ = box
    calls, script = provider
    script.append((500, {"name": "internal_server_error", "message": "unique-provider-sentence-7f3a"}))
    _assign()
    outbox.drain(store=store)
    row = _only_row(store)
    assert row["last_error_code"] == "internal_server_error" and row["last_status_code"] == 500
    assert "unique-provider-sentence-7f3a" not in str(row), "only the error NAME is kept"


# ── failing for good ─────────────────────────────────────────────────────────────

def test_a_4xx_is_final_at_once_and_flips_its_log_row_so_the_sweep_can_try_again(box, provider):
    store, clock = box
    calls, script = provider
    script.append((422, {"name": "validation_error", "message": "invalid `to` priya@gupta-ca.in"}))
    assert _sweep() == "queued"
    assert outbox.drain(store=store) == {"failed": 1}
    row = _only_row(store)
    assert row["status"] == "failed" and row["attempts"] == 1
    assert row["final_reason"] == "validation_error" and row["subject"] == "" and row["html"] == ""
    log = [r for r in mail.MOCK_LOG if r["event_type"] == "compliance_deadline"][0]
    assert log["status"] == "failed" and log["dedupe_key"] is None
    assert "validation_error" in log["detail"]
    # The sweep that was blocked by `sent` is no longer blocked:
    assert _sweep() == "queued", "a message that never went must not read as 'already sent'"


def test_six_server_errors_end_in_a_final_failure_after_the_last_attempt(box, provider):
    store, clock = box
    calls, script = provider
    script.extend([(503, {"name": "service_unavailable"})] * 6)
    _assign()
    outcomes = []
    for _ in range(8):
        outcomes.append(outbox.drain(store=store))
        clock.advance(minutes=300)
    row = _only_row(store)
    assert (row["status"], row["attempts"]) == ("failed", 6) and len(calls) == 6
    assert row["final_reason"] == "service_unavailable"
    assert sum(o.get("retry", 0) for o in outcomes) == 5 and sum(o.get("failed", 0) for o in outcomes) == 1


def test_the_backoff_is_one_five_fifteen_sixty_then_two_hundred_and_forty_minutes():
    assert [outbox.backoff_for(n) for n in range(1, 8)] == [
        timedelta(minutes=m) for m in (1, 5, 15, 60, 240, 240, 240)]
    assert outbox.MAX_ATTEMPTS == 6 and len(outbox.BACKOFF_MINUTES) == outbox.MAX_ATTEMPTS - 1


@pytest.mark.parametrize("status,retryable", [
    (500, True), (502, True), (503, True), (429, True), (408, True),
    (401, True), (403, True),            # a person fixes the key or the domain in a dashboard
    (400, False), (404, False), (422, False),
])
def test_which_provider_answers_are_worth_trying_again(provider, status, retryable):
    calls, script = provider
    script.append((status, {"name": "x_error"}))
    got = es.transport("a@x.test", "s", "<p>h</p>")
    assert got.ok is False and got.retryable is retryable and got.status_code == status


def test_a_timeout_and_a_missing_key_are_worth_trying_again(provider, monkeypatch):
    calls, script = provider
    script.append((TimeoutError("timed out"), None))
    got = es.transport("a@x.test", "s", "<p>h</p>")
    assert got.ok is False and got.retryable is True and got.code == "TimeoutError"
    monkeypatch.setattr(es, "_RESEND_API_KEY", "")
    gone = es.transport("a@x.test", "s", "<p>h</p>")
    assert gone.ok is False and gone.retryable is True and gone.code == "not_configured"


def test_transport_sends_exactly_what_the_synchronous_send_always_sent(provider):
    calls, _ = provider
    es.transport("a@x.test", "s", "<p>h</p>", sender_name="Acme", reply_to="r@acme.test",
                 idempotency_key="row-1")
    es._send("a@x.test", "s", "<p>h</p>", sender_name="Acme", reply_to="r@acme.test")
    with_key, without = calls
    assert with_key["json"] == without["json"], "the same envelope"
    assert with_key["headers"]["Idempotency-Key"] == "row-1"
    assert "Idempotency-Key" not in without["headers"], "the synchronous path is unchanged"


# ── the switch, asked three times, and the person ────────────────────────────────

def test_a_mail_queued_before_the_switch_was_turned_off_is_cancelled_not_sent(box, provider, monkeypatch):
    store, _ = box
    calls, _ = provider
    assert _sweep() == "queued"
    monkeypatch.delenv("PRACTICE_MAIL_ENABLED", raising=False)       # somebody turns it off
    assert outbox.drain(store=store) == {"cancelled": 1}
    assert calls == [], "a mail was sent while the practice's mail was switched off"
    row = _only_row(store)
    assert row["status"] == "cancelled" and row["final_reason"] == "switched_off"
    assert row["subject"] == "" and row["html"] == ""
    log = [r for r in mail.MOCK_LOG if r["event_type"] == "compliance_deadline"][0]
    assert log["status"] == "failed" and log["dedupe_key"] is None


def test_enqueue_asks_the_switch_itself_so_nothing_can_go_round_deliver(box, monkeypatch):
    store, _ = box
    monkeypatch.delenv("PRACTICE_MAIL_ENABLED", raising=False)
    with pytest.raises(outbox.SwitchedOff):
        outbox.enqueue(firm_id=FIRM, to="a@x.test", subject="s", html="h",
                       origin=outbox.ORIGIN_PRACTICE_NOTICE, event_type="task_assigned",
                       recipient_kind="staff", recipient_user_id="u-1", store=store)
    assert store.rows == {}


def test_deliver_queues_nothing_while_the_switch_is_off(box, provider, monkeypatch):
    store, _ = box
    monkeypatch.delenv("PRACTICE_MAIL_ENABLED", raising=False)
    assert _assign() == "skipped_switched_off"
    assert store.rows == {} and mail.MOCK_LOG == []


def test_the_switch_turned_off_between_deliver_and_the_sink_sends_nothing(box, provider, monkeypatch):
    store, _ = box
    calls, _ = provider

    def turn_off_then_send(_refs):
        monkeypatch.delenv("PRACTICE_MAIL_ENABLED", raising=False)
        return es.send_task_assigned("a@x.test", "A", "T", "C", None)

    status = mail.deliver(FIRM, "task_assigned", PERSON, [mail.Ref("task", "t-3")],
                          turn_off_then_send, dedupe=False)
    assert status == "failed" and store.rows == {} and calls == []


def test_a_person_who_switched_the_event_off_after_it_was_queued_is_not_mailed(box, provider):
    store, _ = box
    calls, _ = provider
    assert _assign() == "queued"
    mail.set_preference(FIRM, "u-1", "task_assigned", False)
    assert outbox.drain(store=store) == {"cancelled": 1}
    assert calls == [] and _only_row(store)["final_reason"] == "preference_off"


def test_a_person_who_has_since_been_deactivated_is_not_mailed(box, provider, monkeypatch):
    store, _ = box
    calls, _ = provider
    assert _assign() == "queued"
    monkeypatch.setattr(user_repo, "find_by_id", lambda uid, *, firm_id: {**PERSON, "is_active": False})
    assert outbox.drain(store=store) == {"cancelled": 1}
    assert calls == [] and _only_row(store)["final_reason"] == "inactive_recipient"


def test_a_person_who_has_left_the_firm_is_not_mailed(box, provider, monkeypatch):
    store, _ = box
    assert _assign() == "queued"
    monkeypatch.setattr(user_repo, "find_by_id", lambda uid, *, firm_id: None)
    assert outbox.drain(store=store) == {"cancelled": 1}
    assert _only_row(store)["final_reason"] == "inactive_recipient"


def test_a_clients_portal_contact_has_no_staff_preference_to_ask(box, provider):
    store, _ = box
    calls, _ = provider
    status = mail.deliver(
        FIRM, "portal_message_notice", CONTACT, [mail.Ref("client", "c-1")],
        lambda _r: es.send_portal_message_notice(CONTACT["email"], CONTACT["name"], "Gupta & Co",
                                                 "https://app.test/portal",
                                                 sender_name="Gupta & Co", reply_to="partner@gupta-ca.in"),
        kind="client_contact", day=START.date())
    assert status == "queued"
    row = _only_row(store)
    assert row["recipient_kind"] == "client_contact" and row["recipient_user_id"] is None
    assert outbox.drain(store=store) == {"sent": 1}
    assert calls[0]["json"]["reply_to"] == "partner@gupta-ca.in"
    assert calls[0]["json"]["from"].startswith("Gupta & Co <")


# ── claiming ─────────────────────────────────────────────────────────────────────

def test_two_drainers_get_disjoint_rows(box):
    store, _ = box
    ids = {outbox.enqueue(firm_id=FIRM, to=f"u{i}@x.test", subject="s", html="h",
                          origin=outbox.ORIGIN_PRACTICE_NOTICE, event_type="task_assigned",
                          recipient_kind="staff", recipient_user_id="u-1", store=store)
           for i in range(12)}
    got: list[list[str]] = []
    barrier = threading.Barrier(3)

    def go():
        barrier.wait()
        got.append([r["id"] for r in store.claim_due(5, 300)])

    threads = [threading.Thread(target=go) for _ in range(3)]
    [t.start() for t in threads]
    [t.join(timeout=30) for t in threads]
    flat = [i for chunk in got for i in chunk]
    assert len(flat) == len(set(flat)) == 12 and set(flat) == ids


def test_a_row_whose_drainer_died_is_handed_out_again_after_its_lease_with_an_attempt_spent(box):
    store, clock = box
    oid = outbox.enqueue(firm_id=FIRM, to="a@x.test", subject="s", html="h",
                         origin=outbox.ORIGIN_PRACTICE_NOTICE, event_type="task_assigned",
                         recipient_kind="staff", recipient_user_id="u-1", store=store)
    first = store.claim_due(5, outbox.LEASE_SECONDS)
    assert [(r["id"], r["attempts"]) for r in first] == [(oid, 1)]
    assert store.claim_due(5, outbox.LEASE_SECONDS) == [], "a live lease is not handed out"
    clock.advance(seconds=outbox.LEASE_SECONDS + 1)
    again = store.claim_due(5, outbox.LEASE_SECONDS)
    assert [(r["id"], r["attempts"]) for r in again] == [(oid, 2)]


def test_a_message_that_keeps_killing_its_drainer_is_abandoned_not_sent(box, provider):
    store, clock = box
    calls, _ = provider
    _assign()
    row = _only_row(store)
    for _ in range(row["max_attempts"]):                       # six drainers die holding it
        store.claim_due(5, outbox.LEASE_SECONDS)
        clock.advance(seconds=outbox.LEASE_SECONDS + 1)
    assert outbox.drain(store=store) == {"failed": 1}
    assert calls == [], "the seventh claim must give up, not send"
    row = _only_row(store)
    assert row["status"] == "failed" and row["final_reason"] == "abandoned" and row["attempts"] == 7


def test_a_drainer_that_lost_its_lease_cannot_overwrite_the_new_holders_result(box):
    store, clock = box
    oid = outbox.enqueue(firm_id=FIRM, to="a@x.test", subject="s", html="h",
                         origin=outbox.ORIGIN_PRACTICE_NOTICE, event_type="task_assigned",
                         recipient_kind="staff", recipient_user_id="u-1", store=store)
    old = store.claim_due(5, outbox.LEASE_SECONDS)[0]
    clock.advance(seconds=outbox.LEASE_SECONDS + 1)
    new = store.claim_due(5, outbox.LEASE_SECONDS)[0]
    assert store.mark_sent(oid, old["attempts"], provider_message_id="stale", status_code=200) is False
    assert store.mark_sent(oid, new["attempts"], provider_message_id="fresh", status_code=200) is True
    assert _only_row(store)["provider_message_id"] == "fresh"


def test_drain_never_raises_and_says_so_when_the_claim_fails(box, caplog):
    class _Broken:
        def claim_due(self, *a):
            raise TimeoutError("database timed out")

        def prune(self, *a):
            return 0

    with caplog.at_level("ERROR", logger="caflow.email_outbox"):
        assert outbox.drain(store=_Broken()) == {}
    assert any("could not claim queued mail" in r.getMessage() for r in caplog.records)


def test_a_message_that_raises_while_being_delivered_does_not_stop_the_others(box, provider, monkeypatch):
    store, _ = box
    calls, _ = provider
    _assign(task="t-a")
    _assign(task="t-b")
    real = outbox._deliver_one
    seen: list[str] = []

    def flaky(s, row):
        seen.append(row["id"])
        if len(seen) == 1:
            raise RuntimeError("a bug in delivering the first message")
        return real(s, row)

    monkeypatch.setattr(outbox, "_deliver_one", flaky)
    got = outbox.drain(store=store)
    assert got == {"error": 1, "sent": 1} and len(calls) == 1


def test_drain_prunes_only_finished_rows_older_than_the_retention(box, provider):
    store, clock = box
    _assign(task="t-old")
    outbox.drain(store=store)                                   # sent now
    _assign(task="t-new")
    pending = [r for r in store.rows.values() if r["status"] == "pending"]
    clock.advance(days=outbox.RETENTION_DAYS + 1)
    assert store.prune(outbox.RETENTION_DAYS) == 1
    assert [r["id"] for r in store.rows.values()] == [pending[0]["id"]], "a waiting message is never pruned"


# ── the drain a queued mail starts, and the tick that backs it up ─────────────────

def test_a_queued_mail_starts_a_background_drain_that_delivers_it(box, provider):
    store, _ = box
    calls, _ = provider
    outbox.set_kick(True)
    assert _assign() == "queued"
    deadline = time.time() + 20
    while time.time() < deadline and not [r for r in store.rows.values() if r["status"] == "sent"]:
        time.sleep(0.05)
    assert [r["status"] for r in store.rows.values()] == ["sent"] and len(calls) == 1


def test_the_scheduler_registers_a_per_minute_drain_and_it_cannot_raise(monkeypatch):
    import jobs.scheduler as sched
    src = (API / "jobs" / "scheduler.py").read_text(encoding="utf-8")
    assert 'id="email_outbox"' in src and "drain_email_outbox, CronTrigger(minute=\"*\")" in src
    monkeypatch.setattr(outbox, "drain", lambda **k: (_ for _ in ()).throw(RuntimeError("boom")))
    sched.drain_email_outbox()                                  # must not raise


def test_the_external_trigger_also_drains_the_outbox_whether_or_not_any_job_was_pending(monkeypatch):
    import routers.scheduler_trigger as trig
    kicks: list[int] = []
    monkeypatch.setattr(outbox, "kick", lambda: kicks.append(1))
    monkeypatch.setenv("SCHEDULER_TRIGGER_TOKEN", "t" * 40)
    app = FastAPI()
    app.include_router(trig.router)
    client = TestClient(app)
    for outcome in ({"started": True, "reason": "started in background", "pending": 3},
                    {"started": False, "reason": "today's run is already complete", "pending": 0},
                    {"started": False, "reason": "before the scheduled hour (06:00 IST)", "pending": 0}):
        monkeypatch.setattr("jobs.scheduler.run_pending_now", lambda *, background=True, o=outcome: o)
        r = client.post("/api/internal/scheduler/run-pending", headers={"X-Scheduler-Token": "t" * 40})
        assert r.status_code == 200 and r.json()["data"] == outcome
    assert kicks == [1, 1, 1]
    wrong = client.post("/api/internal/scheduler/run-pending", headers={"X-Scheduler-Token": "w" * 40})
    assert wrong.status_code == 401 and kicks == [1, 1, 1], "a stranger must not start a drain"


# ── the outbox is not in this database yet ───────────────────────────────────────

class _Missing(Exception):
    code = "PGRST205"


class _NoOutbox:
    def insert(self, row):
        raise _Missing("Could not find the table 'public.email_outbox' in the schema cache")

    def is_suppressed(self, address):
        raise _Missing("no table")


def test_a_database_without_migration_472_posts_the_mail_directly_and_says_so_once(
        provider, monkeypatch, caplog):
    calls, _ = provider
    mail.reset_mock_stores()
    outbox._unavailable_warned = False
    outbox.set_store(_NoOutbox())
    outbox.set_queueing(True)
    monkeypatch.setattr(user_repo, "find_by_id", lambda uid, *, firm_id: PERSON)
    try:
        with caplog.at_level("ERROR", logger="caflow.email_outbox"):
            assert _assign(task="t-1") == "sent"
            assert _assign(task="t-2") == "sent"
    finally:
        outbox.set_store(None)
        outbox.set_queueing(None)
    assert len(calls) == 2, "the practice's mail must still go out when the outbox is absent"
    said = [r for r in caplog.records if "outbox is NOT in force" in r.getMessage()]
    assert len(said) == 1 and "migration 472" in said[0].getMessage()


def test_a_suppression_list_that_cannot_be_read_does_not_stop_the_mail(box, provider):
    store, _ = box
    assert outbox.is_suppressed("a@x.test", store=_NoOutbox()) is False


def test_any_other_queueing_failure_is_a_failed_mail_not_a_silent_one(provider, monkeypatch):
    class _Down:
        def insert(self, row):
            raise TimeoutError("database timed out")

        def is_suppressed(self, address):
            return False

    mail.reset_mock_stores()
    outbox.set_store(_Down())
    outbox.set_queueing(True)
    monkeypatch.setattr(user_repo, "find_by_id", lambda uid, *, firm_id: PERSON)
    try:
        assert _assign() == "failed"
    finally:
        outbox.set_store(None)
        outbox.set_queueing(None)
    assert provider[0] == []


# ── a portal notice counts a queued mail as a mail ───────────────────────────────

def test_a_queued_portal_notice_counts_as_emailed(monkeypatch):
    import services.portal_notice_service as notices
    monkeypatch.setattr(notices, "_active_contacts", lambda firm, client: [CONTACT])
    monkeypatch.setattr(mail, "practice_sender", lambda firm: ("Gupta & Co", "p@gupta.test"))
    monkeypatch.setattr(mail, "deliver", lambda *a, **k: "queued")
    out = notices.document_requested(FIRM, "c-1", {"id": "d-1", "title": "Bank statements"})
    assert out["emailed"] == 1 and out["reason"] is None


# ══════════════════════════════════════════════════════════════════════════════════
# THE WEBHOOK — who may say an address is bad, and what it does to the records
# ══════════════════════════════════════════════════════════════════════════════════

def _independent_signature(secret: str, svix_id: str, timestamp: str, body: bytes) -> str:
    """The Svix / Standard Webhooks scheme, computed here from its specification and NOT through
    `email_events.sign`, so the verifier is checked against something other than itself."""
    key = base64.b64decode(secret.removeprefix("whsec_"))
    digest = hmac.new(key, f"{svix_id}.{timestamp}.".encode() + body, hashlib.sha256).digest()
    return "v1," + base64.b64encode(digest).decode()


def _headers(body: bytes, *, secret=SECRET, svix_id="msg_2abc", now=None, signature=None):
    ts = str(int(now if now is not None else time.time()))
    return {"svix-id": svix_id, "svix-timestamp": ts,
            "svix-signature": signature or _independent_signature(secret, svix_id, ts, body)}


BOUNCE = (b'{"type":"email.bounced","created_at":"2026-10-14T04:00:00.000Z","data":{"email_id":"resend-msg-42",'
          b'"from":"PracticeSync <noreply@caflow.ai>","to":["Priya@Gupta-CA.in"],"subject":"x",'
          b'"bounce":{"type":"Permanent","subType":"General","message":"mailbox does not exist"}}}')
SOFT = BOUNCE.replace(b'"Permanent"', b'"Transient"')
COMPLAINT = b'{"type":"email.complained","data":{"email_id":"resend-msg-42","to":["priya@gupta-ca.in"]}}'
DELIVERED = b'{"type":"email.delivered","data":{"email_id":"resend-msg-42","to":["priya@gupta-ca.in"]}}'


def test_a_signature_made_the_documented_way_verifies():
    h = _headers(BOUNCE)
    assert email_events.verify(SECRET, h, BOUNCE).ok is True
    assert email_events.sign(SECRET, h["svix-id"], h["svix-timestamp"], BOUNCE) == h["svix-signature"], (
        "`sign` and the specification must agree, or the verifier is checked against itself")


@pytest.mark.parametrize("what", ["wrong_secret", "altered_body", "wrong_id", "stale", "future",
                                  "no_signature", "no_timestamp", "no_id", "bad_timestamp",
                                  "only_v2", "garbled_signature", "empty_signature"])
def test_anything_but_a_fresh_correct_signature_is_refused(what):
    other = "whsec_" + base64.b64encode(b"some-other-signing-key-entirely").decode()
    now = time.time()
    h = _headers(BOUNCE)
    body = BOUNCE
    if what == "wrong_secret":
        h = _headers(BOUNCE, secret=other)
    elif what == "altered_body":
        body = BOUNCE.replace(b"Permanent", b"Transient")
    elif what == "wrong_id":
        h["svix-id"] = "msg_other"
    elif what == "stale":
        h = _headers(BOUNCE, now=now - email_events.SIGNATURE_TOLERANCE_SECONDS - 5)
    elif what == "future":
        h = _headers(BOUNCE, now=now + email_events.SIGNATURE_TOLERANCE_SECONDS + 5)
    elif what == "no_signature":
        del h["svix-signature"]
    elif what == "no_timestamp":
        del h["svix-timestamp"]
    elif what == "no_id":
        del h["svix-id"]
    elif what == "bad_timestamp":
        h["svix-timestamp"] = "yesterday"
    elif what == "only_v2":
        h["svix-signature"] = h["svix-signature"].replace("v1,", "v2,")
    elif what == "garbled_signature":
        h["svix-signature"] = "v1,not-the-signature"
    elif what == "empty_signature":
        h["svix-signature"] = "v1,"
    assert email_events.verify(SECRET, h, body).ok is False


def test_the_list_of_signatures_a_rotating_secret_sends_is_accepted_if_any_one_matches():
    good = _headers(BOUNCE)["svix-signature"]
    h = _headers(BOUNCE, signature=f"v1,bm90LXRoZS1vbmU= {good}")
    assert email_events.verify(SECRET, h, BOUNCE).ok is True


def test_a_secret_that_is_not_a_signing_secret_verifies_nothing():
    for bad in ("", "whsec_", "whsec_!!!not base64!!!", "   "):
        assert email_events.verify(bad, _headers(BOUNCE), BOUNCE).ok is False
        assert email_events.decode_secret(bad) is None


def test_the_comparison_is_constant_time_on_bytes():
    src = (API / "domain" / "email_events.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "compare_digest"]
    assert len(calls) == 1
    eq = [n for n in ast.walk(tree) if isinstance(n, ast.Compare) and any(isinstance(o, ast.Eq) for o in n.ops)
          and {"candidate", "expected"} <= {x.id for x in ast.walk(n) if isinstance(x, ast.Name)}]
    assert eq == [], "the signature must not be compared with =="


@pytest.mark.parametrize("payload,kind,addresses", [
    (BOUNCE, "hard_bounce", ("priya@gupta-ca.in",)),
    (SOFT, "soft_bounce", ("priya@gupta-ca.in",)),
    (COMPLAINT, "complaint", ("priya@gupta-ca.in",)),
    (DELIVERED, "ignored", ()),
])
def test_what_each_event_means(payload, kind, addresses):
    import json
    got = email_events.classify(json.loads(payload))
    assert (got.kind, got.addresses) == (kind, addresses)


def test_a_bounce_that_does_not_say_what_kind_is_not_grounds_to_mark_an_address():
    for bounce in ({}, {"type": ""}, {"type": "Undetermined"}, {"type": "Transient"}, None):
        data = {"email_id": "m", "to": ["a@x.test"]}
        if bounce is not None:
            data["bounce"] = bounce
        got = email_events.classify({"type": "email.bounced", "data": data})
        assert got.kind == email_events.SOFT_BOUNCE, bounce


def test_garbage_is_ignored_and_never_marks_an_address():
    for junk in (None, [], "email.bounced", 7, {"type": "email.bounced"}, {"type": "email.bounced", "data": "x"},
                 {"type": "email.complained", "data": {"to": ["not an address"]}}):
        got = email_events.classify(junk)
        assert got.addresses == () or got.kind == email_events.IGNORED, junk


def test_a_display_form_address_is_reduced_to_the_address():
    got = email_events.classify({"type": "email.complained",
                                 "data": {"email_id": "m", "to": ["Priya P <Priya@Gupta-CA.in>", "dup@x.test", "DUP@x.test"]}})
    assert got.addresses == ("priya@gupta-ca.in", "dup@x.test")


# ── the route ────────────────────────────────────────────────────────────────────

class _Rows:
    def __init__(self):
        self.updates: list[tuple] = []

    def table(self, name):
        outer = self

        class _T:
            def update(self, values):
                self.values, self.filters = values, []
                return self

            def eq(self, col, val):
                self.filters.append((col, val))
                return self

            def execute(self):
                outer.updates.append((name, self.values, tuple(self.filters)))

                class _R:
                    data = [{"id": "d1"}]
                return _R()
        return _T()


@pytest.fixture
def hook(monkeypatch):
    monkeypatch.setenv("RESEND_WEBHOOK_SECRET", SECRET)
    store = outbox.MemoryOutboxStore()
    outbox.set_store(store)
    events_service._reset_unsigned_state()
    db = _Rows()
    monkeypatch.setattr(email_webhooks, "_db", lambda: db)
    app = FastAPI()
    app.include_router(email_webhooks.router)
    client = TestClient(app, raise_server_exceptions=False)
    yield client, store, db
    outbox.set_store(None)
    events_service._reset_unsigned_state()


URL = "/api/email/webhook/resend"


def _post(client, body, **kw):
    return client.post(URL, content=body, headers={**_headers(body, **kw), "content-type": "application/json"})


def _a_sent_message(store, message_id="resend-msg-42"):
    row = store.insert({"firm_id": FIRM, "origin": "practice_notice", "event_type": "task_assigned",
                        "recipient_kind": "staff", "recipient_user_id": "u-1",
                        "to_address": PERSON["email"], "subject": "", "html": "", "log_ids": []})
    store.rows[row["id"]].update(status="sent", provider_message_id=message_id)
    return row["id"]


def test_with_no_secret_configured_the_webhook_is_a_503_and_writes_nothing(hook, monkeypatch):
    client, store, db = hook
    monkeypatch.delenv("RESEND_WEBHOOK_SECRET", raising=False)
    assert _post(client, BOUNCE).status_code == 503
    monkeypatch.setenv("RESEND_WEBHOOK_SECRET", "not-a-signing-secret!!")
    assert _post(client, BOUNCE).status_code == 503
    assert store.suppressions == {} and db.updates == []


def test_an_unsigned_request_is_a_400_and_writes_nothing_durable(hook):
    client, store, db = hook
    mid = _a_sent_message(store)
    r = client.post(URL, content=BOUNCE, headers={"content-type": "application/json"})
    assert r.status_code == 400 and "bounce" not in r.text.lower() and "signature" not in r.text.lower()
    forged = _post(client, BOUNCE, secret="whsec_" + base64.b64encode(b"a-different-key-of-same-size!").decode())
    assert forged.status_code == 400
    assert store.suppressions == {} and db.updates == []
    assert store.rows[mid].get("delivery_event") is None
    assert events_service.unsigned_total() == 2


def test_unsigned_requests_from_one_address_are_throttled(hook):
    client, store, db = hook
    codes = [client.post(URL, content=BOUNCE).status_code
             for _ in range(events_service.UNSIGNED_PER_IP_MAX + 5)]
    assert set(codes[: events_service.UNSIGNED_PER_IP_MAX]) == {400}
    assert set(codes[events_service.UNSIGNED_PER_IP_MAX:]) == {429}
    # ...and a SIGNED one is not throttled by what a stranger does:
    assert _post(client, DELIVERED).status_code == 200


def test_an_oversized_body_is_refused_before_it_is_read(hook):
    client, _, _ = hook
    big = b"x" * (email_webhooks.MAX_WEBHOOK_BODY_BYTES + 1)
    assert client.post(URL, content=big).status_code == 413


def test_a_permanent_bounce_marks_the_address_the_message_and_the_delivery_rows(hook):
    client, store, db = hook
    mid = _a_sent_message(store)
    r = _post(client, BOUNCE)
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["kind"] == "hard_bounce" and body["suppressed"] == 1 and body["messages_marked"] == 1
    assert store.suppressions["priya@gupta-ca.in"]["reason"] == "hard_bounce"
    assert store.rows[mid]["delivery_event"] == "bounced"
    tables = {name for name, *_ in db.updates}
    assert tables == {"invoice_deliveries", "customer_statement_deliveries"}
    for _name, values, filters in db.updates:
        assert values["status"] == "bounced" and "mailbox" not in values["error_message"].lower()
        assert ("provider_message_id", "resend-msg-42") in filters and ("status", "sent") in filters, (
            "only a delivery that was SENT, and only this provider message, may become bounced")


def test_a_complaint_marks_the_address_and_message_but_not_the_delivery_rows(hook):
    client, store, db = hook
    mid = _a_sent_message(store)
    assert _post(client, COMPLAINT).status_code == 200
    assert store.suppressions["priya@gupta-ca.in"]["reason"] == "complaint"
    assert store.rows[mid]["delivery_event"] == "complained"
    assert db.updates == [], "the mail WAS delivered; a complaint is not a bounce"


def test_a_complaint_outranks_an_earlier_bounce_and_not_the_other_way(hook):
    client, store, _ = hook
    _post(client, BOUNCE)
    _post(client, COMPLAINT, svix_id="msg_second")
    assert store.suppressions["priya@gupta-ca.in"]["reason"] == "complaint"
    _post(client, BOUNCE, svix_id="msg_third")
    assert store.suppressions["priya@gupta-ca.in"]["reason"] == "complaint"


def test_a_soft_bounce_and_an_ordinary_event_write_nothing(hook):
    client, store, db = hook
    mid = _a_sent_message(store)
    assert _post(client, SOFT).status_code == 200
    assert _post(client, DELIVERED, svix_id="msg_d").status_code == 200
    assert store.suppressions == {} and db.updates == []
    assert store.rows[mid].get("delivery_event") is None


def test_a_replayed_event_changes_nothing_more(hook):
    client, store, db = hook
    _a_sent_message(store)
    assert _post(client, BOUNCE).status_code == 200
    assert _post(client, BOUNCE).status_code == 200
    assert list(store.suppressions) == ["priya@gupta-ca.in"]


def test_a_signed_body_that_is_not_json_is_refused_without_writing(hook):
    client, store, db = hook
    junk = b"this is not json"
    assert _post(client, junk).status_code == 400
    assert store.suppressions == {} and db.updates == []


def test_the_webhook_is_mounted_public_and_declared_in_the_manifest():
    from main import app
    matches = [r for r in app.routes if getattr(r, "path", "") == URL]
    assert len(matches) == 1 and "POST" in matches[0].methods
    names = set()

    def walk(dep):
        names.add(getattr(dep.call, "__name__", ""))
        [walk(d) for d in dep.dependencies]
    walk(matches[0].dependant)
    assert not names & {"get_current_user", "get_jwt_user", "mfa_guard", "require_client_access"}, names
    lines = (API.parents[1] / "render.yaml").read_text(encoding="utf-8").splitlines()
    i = next(n for n, line in enumerate(lines) if line.strip() == "- key: RESEND_WEBHOOK_SECRET")
    assert lines[i + 1].strip() == "sync: false"


# ── a bounce marks the address, end to end ───────────────────────────────────────

def test_after_a_permanent_bounce_the_practice_does_not_mail_that_address_again(box, provider, hook):
    client, store, _ = hook
    calls, _ = provider
    assert _assign() == "queued"
    assert outbox.drain(store=store) == {"sent": 1}
    message_id = _only_row(store)["provider_message_id"]
    body = BOUNCE.replace(b"resend-msg-42", message_id.encode())
    assert _post(client, body).status_code == 200
    sent_so_far = len(calls)
    assert _assign(task="t-2") == "skipped_suppressed"
    assert len(calls) == sent_so_far and len(store.rows) == 1, "a suppressed address is not even queued"


def test_a_message_queued_before_the_bounce_is_suppressed_at_drain_not_sent(box, provider):
    store, _ = box
    calls, _ = provider
    assert _sweep() == "queued"
    store.suppress("priya@gupta-ca.in", "hard_bounce", "earlier")
    assert outbox.drain(store=store) == {"suppressed": 1}
    assert calls == []
    row = _only_row(store)
    assert row["status"] == "suppressed" and row["final_reason"] == "suppressed"
    log = [r for r in mail.MOCK_LOG if r["event_type"] == "compliance_deadline"][0]
    assert log["status"] == "failed" and log["dedupe_key"] is None


def test_an_address_is_compared_without_regard_to_case_or_spaces(box):
    store, _ = box
    store.suppress("priya@gupta-ca.in", "hard_bounce", None)
    assert outbox.is_suppressed("  PRIYA@Gupta-CA.in ", store=store) is True
    assert outbox.is_suppressed("someone-else@gupta-ca.in", store=store) is False


# ══════════════════════════════════════════════════════════════════════════════════
# D27, AND WHO MAY SET WHAT — rules over the whole tree, not a list of today's callers
# ══════════════════════════════════════════════════════════════════════════════════

def _py_files():
    for path in API.rglob("*.py"):
        if {"tests", "migrations", "scripts", "__pycache__", ".venv"} & set(path.parts):
            continue
        yield path


def test_a_clients_customer_cannot_be_queued_mail(box):
    store, _ = box
    for kind in ("client_customer", "customer", "other", ""):
        with pytest.raises(ValueError):
            outbox.enqueue(firm_id=FIRM, to="buyer@x.test", subject="s", html="h",
                           origin=outbox.ORIGIN_PRACTICE_NOTICE, event_type="task_assigned",
                           recipient_kind=kind, store=store)
    with pytest.raises(ValueError):
        outbox.enqueue(firm_id=FIRM, to="a@x.test", subject="s", html="h", origin="invoice",
                       event_type="task_assigned", recipient_kind="staff", store=store)
    assert store.rows == {}
    assert outbox.RECIPIENT_KINDS == ("staff", "client_contact")


def test_enqueue_is_called_from_one_place_and_the_sink_is_set_from_one_place():
    enqueue_calls: dict[str, int] = {}
    sink_sets: dict[str, int] = {}
    capturing_calls: dict[str, int] = {}
    for path in _py_files():
        text = path.read_text(encoding="utf-8")
        if "enqueue" not in text and "_OUTBOX_SINK" not in text and "capturing" not in text:
            continue
        rel = path.relative_to(API).as_posix()
        for node in ast.walk(ast.parse(text)):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            owner = ast.unparse(f.value) if isinstance(f, ast.Attribute) else ""
            if name == "enqueue":
                enqueue_calls[rel] = enqueue_calls.get(rel, 0) + 1
            if name == "set" and "_OUTBOX_SINK" in owner:
                sink_sets[rel] = sink_sets.get(rel, 0) + 1
            if name == "capturing":
                capturing_calls[rel] = capturing_calls.get(rel, 0) + 1
    assert set(enqueue_calls) == {"services/email_outbox_service.py"}, (
        f"enqueue is called from {sorted(enqueue_calls)}: a sweep must not grow a second way onto the "
        "queue (D27: a client's customers are mailed by a person pressing Send, never automatically)")
    assert set(sink_sets) == {"services/email_outbox_service.py"} and sum(sink_sets.values()) == 1
    assert set(capturing_calls) == {"services/practice_mail_service.py"}, capturing_calls


def test_no_sweep_or_job_module_imports_the_outbox():
    for path in (API / "jobs").glob("*.py"):
        if path.name == "scheduler.py":
            continue            # it imports `drain` only, lazily, inside the tick
        assert "email_outbox_service" not in path.read_text(encoding="utf-8"), path.name
    for name in ("collections_service.py", "recurring_invoice_service.py",
                 "customer_statement_service.py", "invoice_lifecycle_service.py"):
        text = (API / "services" / name).read_text(encoding="utf-8")
        assert "email_outbox_service" not in text, name


def test_the_outbox_module_is_the_only_writer_of_the_two_tables():
    writers: set[str] = set()
    for path in _py_files():
        text = path.read_text(encoding="utf-8")
        if re.search(r'\.table\(\s*"email_(outbox|suppressions)"', text):
            writers.add(path.relative_to(API).as_posix())
    assert writers == {"services/email_outbox_service.py"}, writers
