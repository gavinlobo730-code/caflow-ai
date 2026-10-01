"""A swallowed posting failure reaches Sentry WITH the tags an alert rule is built on, and nothing else (ops-10).

THE FINDING ASKED FOR ALERT RULES, AND THE FIRST THING THAT HAD TO BE TRUE IS THAT THEY CAN MATCH.
    "Any new issue with tag `posting_operation` pages a person" was the rule. Run against the real SDK, the
    tag was never on the event. `_capture` logged at ERROR with `exc_info` and THEN reported; Sentry's default
    logging integration turned the log record into an event first — no tags, no fingerprint — and the explicit
    capture that carried them was dropped as a duplicate of the same exception. Measured on 30-09-2026:

        1 event, logger caflow.observability, tags None, fingerprint None

    so every posting failure would have grouped by stack trace and no rule on `posting_operation`,
    `soft_operation`, `firm_id` or `source_id` would ever have fired. `test_observability.py` and
    `test_soft_failure_visibility.py` did not catch it and could not: both replace `sentry_sdk.capture_exception`
    and `new_scope` with fakes, which tests that the code CALLS the SDK and says nothing about what the SDK then
    sends. These tests use the real client with a capturing transport and read the event that would have left.

THE SECOND HALF IS WHAT ELSE LEAVES.
    main.py said "No request bodies, headers or user records", and that was false of two things the real SDK
    sends regardless of `send_default_pii=False`: the request's JSON body (a 500 from a deductee or payroll
    endpoint sent `{"pan": ..., "amount_paise": ...}`) and every stack frame's local variables. Headers were
    already filtered. `init_error_reporting` turns both off and these tests hold it.

WHAT CANNOT BE TESTED HERE
    That Sentry's server then groups by the fingerprint, applies an alert rule or delivers a notification.
    Those are the human steps in docs/operations/error-tracking.md, and `scripts/sentry_verify.py` exists to
    trigger the test event they are checked with.
"""
from __future__ import annotations

import logging

import pytest
import sentry_sdk
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core import observability as obs

DSN = "https://publickey@o123.ingest.sentry.io/456"


@pytest.fixture()
def sent():
    """Start the REAL client with a transport that keeps what would have left, and stop it afterwards."""
    events: list[dict] = []
    assert obs.init_error_reporting(DSN, environment="test", transport=events.append) is True
    try:
        yield events
    finally:
        sentry_sdk.flush()
        sentry_sdk.init()          # no DSN: a disabled client, so no later test sends anything


# Built at run time, never written as literals: a stack frame carries its SOURCE LINES (the SDK's
# `context_line`), so a value spelled out in this file would be found in the event for a reason that has
# nothing to do with the local variables being tested.
PAN = "ABCDE" + str(1234) + "F"
CUSTOMER = " ".join(["Acme", "Traders", "Pvt", "Ltd"])


def _post_cogs(pan: str, amount_paise: int):
    customer_name = CUSTOMER          # noqa: F841 — a local a frame would carry
    raise ValueError("journal did not balance")


def _fail_and_report(report, operation="post_cogs_journal_entry", **context):
    try:
        _post_cogs(PAN, 12500000)
    except Exception as exc:          # exactly how a fail-soft call site uses it
        report(exc, operation=operation, **context)
    sentry_sdk.flush()


# ── the tags ───────────────────────────────────────────────────────────────────

def test_a_swallowed_posting_failure_reaches_sentry_as_one_event_with_its_tags(sent):
    _fail_and_report(obs.capture_posting_failure, firm_id="F1", client_id="C1",
                     source_type="sales_invoice", source_id="INV-7")
    assert len(sent) == 1, [e.get("logger") for e in sent]
    event = sent[0]
    assert event["tags"]["posting_operation"] == "post_cogs_journal_entry"
    assert event["tags"]["firm_id"] == "F1"
    assert event["tags"]["source_type"] == "sales_invoice"
    assert event["tags"]["source_id"] == "INV-7"
    assert event["fingerprint"] == ["posting-failure", "post_cogs_journal_entry"]
    assert event.get("logger") != "caflow.observability", "the untagged log-record event is the one that arrived"


def test_a_swallowed_soft_failure_carries_its_own_tag_and_fingerprint(sent):
    _fail_and_report(obs.capture_soft_failure, operation="health_score_dimension", firm_id="F1", client_id="C1")
    assert len(sent) == 1
    event = sent[0]
    assert event["tags"]["soft_operation"] == "health_score_dimension"
    assert "posting_operation" not in event["tags"], "a broken health dimension must not page like a missing journal"
    assert event["fingerprint"] == ["soft-failure", "health_score_dimension"]


def test_one_operation_is_one_issue_and_two_operations_are_two(sent):
    _fail_and_report(obs.capture_posting_failure, operation="post_cogs_journal_entry", source_id="A")
    _fail_and_report(obs.capture_posting_failure, operation="post_cogs_journal_entry", source_id="B")
    _fail_and_report(obs.capture_posting_failure, operation="post_inventory_receipt_journal_entry", source_id="C")
    fingerprints = [tuple(e["fingerprint"]) for e in sent]
    assert len(sent) == 3
    assert fingerprints[0] == fingerprints[1] != fingerprints[2]


def test_the_failure_is_still_logged_at_error_for_renders_log_stream(sent, caplog):
    """Ignoring the logger for SENTRY must not silence it for Render, where it is the only trace if Sentry is off."""
    with caplog.at_level(logging.ERROR, logger="caflow.observability"):
        _fail_and_report(obs.capture_posting_failure, firm_id="F1")
    assert any(r.levelno == logging.ERROR and "post_cogs_journal_entry" in r.getMessage() for r in caplog.records)


# ── what else leaves ───────────────────────────────────────────────────────────

def test_no_stack_frame_carries_its_local_variables(sent):
    _fail_and_report(obs.capture_posting_failure, firm_id="F1")
    frames = sent[0]["exception"]["values"][0]["stacktrace"]["frames"]
    assert any(f["function"] == "_post_cogs" for f in frames), "the stack is the point and is kept"
    for f in frames:
        assert "vars" not in f, f"frame {f['function']} sent its locals: {f.get('vars')}"
    assert PAN not in str(sent[0])
    assert CUSTOMER not in str(sent[0])


def test_a_500_from_an_endpoint_does_not_send_the_request_body_or_its_secrets(sent):
    app = FastAPI()

    @app.post("/api/deductees")
    def create(payload: dict):
        raise RuntimeError(f"could not save a deductee ({len(payload['pan'])} characters)")

    token = "secret" + "token"
    cookie = "sb=" + "abc"
    amount = 12_500_000
    client = TestClient(app, raise_server_exceptions=False)
    response = client.post(
        "/api/deductees",
        json={"pan": PAN, "amount_paise": amount},
        headers={"Authorization": f"Bearer {token}", "Cookie": cookie},
    )
    sentry_sdk.flush()
    assert response.status_code == 500
    assert len(sent) == 1, "the unhandled exception itself must still be reported"
    text = str(sent[0])
    for secret in (PAN, str(amount), token, cookie):
        assert secret not in text, f"{secret!r} left the process: {sent[0].get('request')}"
    assert "data" not in sent[0].get("request", {}) or not sent[0]["request"]["data"]
    assert sent[0]["request"]["url"].endswith("/api/deductees"), "the route is kept: it is what a developer needs"


# ── starting it, and saying whether it started ─────────────────────────────────

def test_with_no_dsn_nothing_starts():
    # A client built with NO DSN reports itself active and drops everything, which is the state every
    # earlier test's teardown leaves behind — so this is asked of exactly that client.
    sentry_sdk.init()
    assert obs.init_error_reporting(None) is False
    assert obs.init_error_reporting("") is False
    assert obs.error_reporting_enabled() is False


def test_error_reporting_enabled_follows_a_live_client(sent):
    assert obs.error_reporting_enabled() is True


def test_tracing_is_off_unless_somebody_asks_for_it(sent):
    """This is an error-reporting install, not an APM one; an exhausted quota drops the errors it exists for."""
    assert sentry_sdk.get_client().options["traces_sample_rate"] == 0.0


def test_the_options_that_keep_bodies_and_locals_out_are_the_ones_set():
    events: list[dict] = []
    obs.init_error_reporting(DSN, transport=events.append)
    try:
        opts = sentry_sdk.get_client().options
        assert opts["send_default_pii"] is False
        assert opts["max_request_body_size"] == "never"
        assert opts["include_local_variables"] is False
    finally:
        sentry_sdk.init()


@pytest.mark.parametrize(
    "dsn, app_env, level, fragment",
    [
        ("https://k@o1.ingest.sentry.io/1", "production", logging.INFO, "is ON"),
        (None, "production", logging.WARNING, "nobody is alerted"),
        (None, None, logging.WARNING, "nobody is alerted"),          # APP_ENV defaults to production
        (None, "development", logging.INFO, "APP_ENV=development"),
        ("", "production", logging.WARNING, "SENTRY_DSN is not set"),
    ],
)
def test_the_boot_log_says_whether_error_reporting_is_on(dsn, app_env, level, fragment):
    got_level, sentence = obs.boot_notice(dsn, app_env)
    assert got_level == level
    assert fragment in sentence


# ── /health, where it is confirmed ─────────────────────────────────────────────

def test_health_says_whether_error_reporting_is_on(monkeypatch):
    import main as main_module

    before = dict(main_module._SCHEMA_DRIFT)
    main_module._SCHEMA_DRIFT = {"checked": True, "missing": []}
    try:
        monkeypatch.setattr(main_module, "error_reporting_enabled", lambda: False)
        off = TestClient(main_module.app).get("/health")
        monkeypatch.setattr(main_module, "error_reporting_enabled", lambda: True)
        on = TestClient(main_module.app).get("/health")
    finally:
        main_module._SCHEMA_DRIFT = before
    assert off.status_code == on.status_code == 200
    assert off.json()["data"]["error_reporting"] == "off"
    assert on.json()["data"]["error_reporting"] == "on"
    assert on.json()["data"]["schema"] == "ok", "the field is added beside the existing ones, not instead of them"
