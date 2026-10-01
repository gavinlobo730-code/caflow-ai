"""scripts/sentry_verify.py sends what a real swallowed failure looks like, and nothing until asked (ops-10).

The script is the human step's instrument: after somebody sets SENTRY_DSN in Render and builds the alert rules,
this is how they find out the rules can match. So it is held to two things — it must be a DRY RUN until `--send`
(the event is indistinguishable from a real one and is meant to trip a rule, so a page is possible), and what it
sends must carry the tags and fingerprint the rules are built on.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sentry_sdk

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "sentry_verify.py"
DSN = "https://secretpublickey@o123.ingest.sentry.io/456"


def _load():
    spec = importlib.util.spec_from_file_location("sentry_verify", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def _no_client_left_behind():
    yield
    sentry_sdk.init()


def test_without_send_it_is_a_dry_run_and_sends_nothing(capsys):
    sent: list = []
    code = _load().main([], env={"SENTRY_DSN": DSN}, transport=sent.append)
    out = capsys.readouterr().out
    assert code == 0
    assert sent == []
    assert "Dry run" in out and "--send" in out


def test_the_key_in_the_dsn_is_never_printed(capsys):
    _load().main([], env={"SENTRY_DSN": DSN})
    out = capsys.readouterr().out
    assert "secretpublickey" not in out
    assert "o123.ingest.sentry.io/456" in out, "which project a run will hit is the point of printing it"


def test_with_no_dsn_it_says_so_and_fails(capsys):
    assert _load().main(["--send"], env={}) == 2
    assert "SENTRY_DSN is not set" in capsys.readouterr().out
    assert _load().main(["--send"], env={"SENTRY_DSN": "   "}) == 2


def test_send_reports_one_posting_and_one_soft_failure_with_the_tags_rules_match_on():
    sent: list[dict] = []
    assert _load().main(["--send", "--environment", "staging"], env={"SENTRY_DSN": DSN}, transport=sent.append) == 0
    assert len(sent) == 2, [e.get("logger") for e in sent]
    by_tag = {("posting_operation" if "posting_operation" in e["tags"] else "soft_operation"): e for e in sent}
    assert set(by_tag) == {"posting_operation", "soft_operation"}
    for tag, event in by_tag.items():
        assert event["tags"][tag] == "sentry_verification"
        assert event["tags"]["firm_id"] == "verification"
        assert event["tags"]["source_type"] == "verification"
        assert event["tags"]["source_id"]
        assert event["environment"] == "staging"
        assert event["fingerprint"][1] == "sentry_verification"
    assert by_tag["posting_operation"]["fingerprint"][0] == "posting-failure"
    assert by_tag["soft_operation"]["fingerprint"][0] == "soft-failure"


def test_the_environment_defaults_to_what_render_runs():
    sent: list[dict] = []
    _load().main(["--send"], env={"SENTRY_DSN": DSN}, transport=sent.append)
    assert {e["environment"] for e in sent} == {"production"}
    sent.clear()
    _load().main(["--send"], env={"SENTRY_DSN": DSN, "ENVIRONMENT": "staging"}, transport=sent.append)
    assert {e["environment"] for e in sent} == {"staging"}
