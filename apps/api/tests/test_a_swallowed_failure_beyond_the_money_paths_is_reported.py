"""A broad handler beyond the money paths REPORTS what it swallows too (POST-A-021, the later slices).

WHAT WAS WRONG
    The first slice (`test_a_swallowed_failure_on_a_money_path_is_reported_not_silent.py`) left 123 handlers in the rest of the
    backend whose whole body was `pass`. The two largest files were the engagement-letter router (22) and the lifecycle router
    (18). Most of them are rightly fail-soft (an audit entry, a timeline line or a lifecycle event must not undo a letter that was
    sent or a lead that was converted), but several lost more than a log line and said nothing:

      * an engagement or proposal number that could not be parsed restarted the series at 0001, so the next insert collided on
        the unique index and failed every time, with no trace of why;
      * the client or lead read behind a letter's merge fields failed and the letter was generated with a blank client name, PAN
        and GSTIN, in a document the client signs;
      * the six default templates a new firm is given were returned as if saved when the insert had failed;
      * completing an onboarding checklist did not activate the client when the update failed;
      * a lead's stage did not follow its engagement letter when the sync failed.

WHAT IS HELD
    * in the files listed below no broad handler is only `pass` / `continue`; each reports through `capture_soft_failure` with a
      literal `operation` that no other report in these files (or on the money paths) shares;
    * driven for real: a forced failure in each kind of handler lets the action finish and is reported with its operation and
      firm (a lead-stage sync, an engagement event row, an unparseable number, a recipient read, the lifecycle's three audit
      surfaces);
    * a lead or client that is simply absent is NOT a failure: those reads are `.maybe_single()` now, so an absent row is
      `data=None` and nothing is reported.

WHAT IS NOT DONE
    No handler here was made to raise: what a screen sees is unchanged, and only the silence is gone.
"""
from __future__ import annotations

import ast
import logging
from pathlib import Path

import pytest

from tests.test_a_swallowed_failure_on_a_money_path_is_reported_not_silent import (
    MONEY_PATH_FILES,
    reporter_calls,
    silent_broad_handlers,
)

API_ROOT = Path(__file__).resolve().parents[1]

#: Files cleared by the later slices. Adding one is a statement that it has no silent broad handler.
CLEARED_FILES = (
    "routers/engagement_letters.py",
    "routers/lifecycle.py",
)


def _read(relative: str) -> str:
    return (API_ROOT / relative).read_text(encoding="utf-8")


@pytest.mark.parametrize("relative", CLEARED_FILES)
def test_no_broad_handler_in_a_cleared_file_is_silent(relative):
    silent = silent_broad_handlers(_read(relative))
    assert not silent, (
        f"{relative} swallows an exception without a word at lines {silent}. Report it with capture_soft_failure(exc, "
        "operation=...), or narrow the handler to the exception that is genuinely expected.")


def test_every_report_names_its_operation_literally_and_none_is_shared_with_another():
    seen: dict[str, str] = {}
    for relative in MONEY_PATH_FILES + CLEARED_FILES:
        for call in reporter_calls(_read(relative)):
            ops = [k.value for k in call.keywords if k.arg == "operation" and isinstance(k.value, ast.Constant)]
            assert ops and isinstance(ops[0].value, str), f"{relative}:{call.lineno} has no literal operation"
            operation = ops[0].value
            assert operation not in seen, f"{operation!r} is used at {seen[operation]} and {relative}:{call.lineno}"
            seen[operation] = f"{relative}:{call.lineno}"
    cleared = [v for v in seen.values() if v.split(":")[0] in CLEARED_FILES]
    assert len(cleared) >= 40, f"only {len(cleared)} reports in the cleared files: the wiring has regressed"


# ── driven for real ─────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def spy(monkeypatch):
    seen: list[tuple[str, dict]] = []

    def install(module):
        monkeypatch.setattr(module, "capture_soft_failure",
                            lambda exc, *, operation, **ctx: seen.append((operation, ctx)), raising=True)
        return seen
    return install


def _boom(*_a, **_k):
    raise RuntimeError("unreachable")


class _BrokenDb:
    """A client whose every table call fails, as a revoked grant or a dropped column would."""
    def table(self, *_a, **_k):
        raise RuntimeError("relation is unreachable")


def test_a_lead_stage_sync_that_fails_is_reported_and_the_letter_action_goes_on(monkeypatch, spy):
    import routers.engagement_letters as mod
    import routers.lifecycle as lifecycle
    seen = spy(mod)
    monkeypatch.setattr(lifecycle, "advance_lead_stage", _boom)
    monkeypatch.setattr(lifecycle, "revert_lead_after_engagement_closed", _boom)
    user = {"auth_user_id": "u1", "email": "a@b.in"}
    mod._advance_lead("lead-1", "firm-1", "Engaged", user)
    mod._revert_lead("lead-1", "firm-1", user)
    assert seen == [("engagement.lead_stage_advance", {"firm_id": "firm-1", "lead_id": "lead-1"}),
                    ("engagement.lead_stage_revert", {"firm_id": "firm-1", "lead_id": "lead-1"})]


def test_an_engagement_event_row_that_fails_is_reported(spy):
    import routers.engagement_letters as mod
    seen = spy(mod)
    mod._log_engagement_event(_BrokenDb(), "eng-1", "firm-1", "sent", "u1", {})
    assert seen == [("engagement.event_log", {"firm_id": "firm-1", "engagement_id": "eng-1", "event_type": "sent"})]


class _Rows:
    def __init__(self, rows):
        self.data = rows

    def __getattr__(self, _name):
        return lambda *_a, **_k: self

    def execute(self):
        return self


class _OneRowDb:
    def __init__(self, rows):
        self.rows = rows

    def table(self, *_a, **_k):
        return _Rows(self.rows)


def test_an_engagement_number_that_cannot_be_read_is_reported_rather_than_silently_restarting_the_series(spy):
    import routers.engagement_letters as mod
    seen = spy(mod)
    number = mod._next_engagement_no(_OneRowDb([{"engagement_number": "EL-2026-XYZ"}]), "firm-1")
    assert number.endswith("-0001")
    assert seen == [("engagement.number_parse", {"firm_id": "firm-1"})]


def test_a_readable_engagement_number_is_not_reported(spy):
    import routers.engagement_letters as mod
    seen = spy(mod)
    assert mod._next_engagement_no(_OneRowDb([{"engagement_number": "EL-2026-0041"}]), "firm-1").endswith("-0042")
    assert seen == []


def test_a_proposal_number_that_cannot_be_read_is_reported(spy, monkeypatch):
    import routers.lifecycle as mod
    seen = spy(mod)
    monkeypatch.setattr(mod.db_provider, "service_db_or_none", lambda: None)
    mod._next_proposal_no(_OneRowDb([{"proposal_no": None}]), "firm-1")
    assert seen == [("lifecycle.proposal_number_parse", {"firm_id": "firm-1"})]


def test_a_recipient_read_that_fails_is_reported_and_an_absent_one_is_not(spy):
    import routers.engagement_letters as mod
    seen = spy(mod)
    eng = {"id": "eng-1", "lead_id": "lead-1", "client_id": "c1"}
    assert mod._resolve_recipient_email(_BrokenDb(), eng, None) is None
    assert [op for op, _ in seen] == ["engagement.recipient_lead_read", "engagement.recipient_client_read"]
    seen.clear()
    assert mod._resolve_recipient_email(_OneRowDb(None), eng, None) is None
    assert seen == [], "a lead or client with no address is not a failure"


def test_the_recipient_and_merge_reads_ask_for_a_row_that_may_be_absent():
    """`.single()` RAISES on no row, so an absent row would be reported as a failure; these reads may find nothing."""
    tree = ast.parse(_read("routers/engagement_letters.py"))
    for fn in ("_resolve_recipient_email", "generate_engagement"):
        node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == fn)
        for call in ast.walk(node):
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == "single":
                chain = ast.unparse(call)
                assert '"leads"' not in chain and "'leads'" not in chain, f"{fn}: a lead read uses .single()"
                assert "client_name, pan, gstin" not in chain and '"email"' not in chain, f"{fn}: {chain}"


def test_the_lifecycle_audit_surfaces_each_report_what_they_lost(monkeypatch, spy):
    import routers.lifecycle as mod
    seen = spy(mod)
    monkeypatch.setattr(mod.timeline_service, "log", _boom)
    monkeypatch.setattr(mod, "log_event", _boom)
    mod._audit_auto_stage_change(_BrokenDb(), "lead-1", "firm-1", "Lead", "Engaged", "u1", "a@b.in", "2026-11-16T00:00:00Z")
    mod._audit_lead_stage_revert(_BrokenDb(), "lead-1", "firm-1", "Engaged", "Lead", "u1", "a@b.in", "2026-11-16T00:00:00Z")
    assert [op for op, _ in seen] == [
        "lifecycle.auto_advance_timeline", "lifecycle.auto_advance_audit", "lifecycle.auto_advance_event",
        "lifecycle.revert_timeline", "lifecycle.revert_audit", "lifecycle.revert_event",
    ]
    assert all(ctx == {"firm_id": "firm-1", "lead_id": "lead-1"} for _, ctx in seen)


def test_the_report_reaches_the_error_log_without_sentry(monkeypatch, caplog):
    import routers.engagement_letters as mod
    with caplog.at_level(logging.ERROR, logger="caflow.observability"):
        mod._log_engagement_event(_BrokenDb(), "eng-7", "firm-1", "signed", "u1", {})
    messages = [r.getMessage() for r in caplog.records]
    assert any("engagement.event_log" in m and "eng-7" in m for m in messages), messages
