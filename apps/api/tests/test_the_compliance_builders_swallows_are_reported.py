"""The compliance builder's nine silent handlers report what they lose (POST-A-021, the sixth slice).

WHAT WAS WRONG
    `services/compliance_obligation_service.py` (7) and `domain/compliance_record_service.py` (2) were the last broad handlers outside
    the error-path ones whose whole body was `pass`, each marked `# pragma: no cover`: the audit row and the client timeline line of an
    obligation being generated, reassigned, escalated or moved between statuses, and the escalation's in-app notifications. They are
    rightly fail-soft (a lost log line must not stop the nightly sweep or undo a reassignment), but a failed audit write on a
    compliance record is a gap in the very edit log the Companies (Accounts) Rules 2014 Rule 3(1) proviso asks for, and a notification
    that was never created is a reminder nobody got. Both vanished without a trace.

WHAT IS HELD
    * in the two files no broad handler is only `pass` / `continue`;
    * every report in them names a literal operation of its own, shared with no report in the money-path files or the earlier slices
      (two existing reports in `domain/compliance_record_service.py` build their names from the event, for the two events that reach
      them, and are named below as the exceptions);
    * driven for real: a failing audit write, timeline write and notification each reports with its operation and the record, and the
      action itself still finishes with the answer it had before.

WHAT IS NOT DONE
    No handler was made to raise: what a screen or the nightly sweep sees is unchanged, and only the silence is gone. The seven handlers
    that run inside an error path by design stay (core/exceptions 3, the AI gateway's error-body parses 2, the mail transport 1, the
    request-token reset 1), and the budget in test_soft_failure_visibility falls from 16 to 7.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]

CLEARED_FILES = ("services/compliance_obligation_service.py", "domain/compliance_record_service.py")

#: the two reports whose operation is built from the event (`not_required`, `required_again`), which an earlier slice wrote and which
#: name their operations by construction.
BUILT_FROM_THE_EVENT = ("domain/compliance_record_service.py", ("f'compliance.{event}.audit'", "f'compliance.{event}.timeline'"))


def _read(relative: str) -> str:
    return (API_ROOT / relative).read_text(encoding="utf-8")


@pytest.mark.parametrize("relative", CLEARED_FILES)
def test_no_broad_handler_in_the_compliance_builder_is_silent(relative):
    from tests.test_a_swallowed_failure_on_a_money_path_is_reported_not_silent import silent_broad_handlers
    silent = silent_broad_handlers(_read(relative))
    assert not silent, f"{relative} swallows an exception without a word at lines {silent}: report it with capture_soft_failure."


def test_every_report_here_has_its_own_literal_operation():
    from tests.test_a_narrow_swallow_is_triaged import CLEARED_FILES as TRIAGED
    from tests.test_a_swallowed_failure_beyond_the_money_paths_is_reported import CLEARED_FILES as EARLIER
    from tests.test_a_swallowed_failure_on_a_money_path_is_reported_not_silent import MONEY_PATH_FILES, reporter_calls
    seen: dict[str, str] = {}
    mine = 0
    for relative in dict.fromkeys(MONEY_PATH_FILES + EARLIER + TRIAGED + CLEARED_FILES):
        for call in reporter_calls(_read(relative)):
            ops = [k.value for k in call.keywords if k.arg == "operation"]
            if relative == BUILT_FROM_THE_EVENT[0] and ops and ast.unparse(ops[0]) in BUILT_FROM_THE_EVENT[1]:
                continue
            assert ops and isinstance(ops[0], ast.Constant) and isinstance(ops[0].value, str), \
                f"{relative}:{call.lineno} has no literal operation"
            op = ops[0].value
            assert op not in seen, f"{op!r} at {seen[op]} and {relative}:{call.lineno}"
            seen[op] = f"{relative}:{call.lineno}"
            mine += relative in CLEARED_FILES
    assert mine >= 13, f"only {mine} reports in the compliance builder: the wiring has regressed"


# ── driven for real ────────────────────────────────────────────────────────────────────────────────────

def _boom(*_a, **_k):
    raise RuntimeError("unreachable")


@pytest.fixture
def spy(monkeypatch):
    seen: list[tuple[str, dict]] = []

    def install(module):
        monkeypatch.setattr(module, "capture_soft_failure",
                            lambda exc, *, operation, **ctx: seen.append((operation, ctx)), raising=True)
        return seen
    return install


@pytest.fixture
def broken_logs(monkeypatch):
    """The audit log and the client timeline both fail, as a revoked grant or a dropped column would."""
    import services.audit_service as audit
    from services.timeline_service import timeline_service
    monkeypatch.setattr(audit, "log_event", _boom)
    monkeypatch.setattr(timeline_service, "log", _boom)


REC = {"id": "rec-1", "firm_id": "firm-1", "client_id": "client-1", "obligation_type": "GSTR3B", "period_label": "GSTR-3B August 2026",
       "due_date": "2026-09-20", "engagement_id": "eng-1", "status": "Not Started"}


def test_a_generated_obligations_audit_and_timeline_that_fail_are_reported(spy, broken_logs):
    import services.compliance_obligation_service as mod
    seen = spy(mod)
    assert mod._audit_timeline_generate("firm-1", dict(REC), {"email": "a@b.c"}) is None
    assert [op for op, _ in seen] == ["compliance.generated.audit", "compliance.generated.timeline"]
    assert all(ctx == {"firm_id": "firm-1", "record_id": "rec-1"} for _, ctx in seen)


def test_a_reassignment_whose_audit_and_timeline_fail_is_reported_and_still_answers(monkeypatch, spy, broken_logs):
    import services.compliance_obligation_service as mod
    seen = spy(mod)
    monkeypatch.setattr(mod.compliance_records_repo, "find_by_id", lambda _id: dict(REC))
    monkeypatch.setattr(mod.compliance_records_repo, "update", lambda _id, updates, **_k: {**REC, **updates})
    out = mod.assign("firm-1", "rec-1", preparer_id="user-9", actor={"email": "a@b.c"})
    assert out["preparer_id"] == "user-9"  # the answer is what it was
    assert [op for op, _ in seen] == ["compliance.reassigned.audit", "compliance.reassigned.timeline"]
    assert all(ctx == {"firm_id": "firm-1", "record_id": "rec-1"} for _, ctx in seen)


def test_an_escalation_whose_timeline_audit_and_notifications_fail_is_reported_and_still_returns_its_recipients(monkeypatch, spy, broken_logs):
    import repositories.notifications_repository as notifications
    import services.compliance_obligation_service as mod
    seen = spy(mod)
    monkeypatch.setattr(mod, "_people_who_can_open", lambda *_a, **_k: {"user-9"})
    monkeypatch.setattr(notifications.notifications_repo, "create", _boom)
    out = mod._notify_internal("firm-1", {**REC, "preparer_id": "user-9"}, "due_3", {"email": "a@b.c"}, reach_cache={})
    assert out == {"user-9"}  # who was addressed does not depend on the notification being stored
    assert [op for op, _ in seen] == ["compliance.escalation.timeline", "compliance.escalation.audit", "compliance.escalation.notifications"]
    assert all(ctx == {"firm_id": "firm-1", "record_id": "rec-1"} for _, ctx in seen)


def test_a_status_change_whose_audit_and_timeline_fail_is_reported(spy, broken_logs):
    import domain.compliance_record_service as mod
    seen = spy(mod)
    assert mod._audit_transition(dict(REC), "Not Started", "In Progress", "firm-1", {"email": "a@b.c"}) is None
    assert [op for op, _ in seen] == ["compliance.status_change.audit", "compliance.status_change.timeline"]
    assert all(ctx == {"record_id": "rec-1"} for _, ctx in seen)


def test_nothing_is_reported_when_nothing_fails(monkeypatch, spy):
    """The reports are for a failure and not a habit: a working audit write and timeline write say nothing."""
    import domain.compliance_record_service as mod
    import services.audit_service as audit
    from services.timeline_service import timeline_service
    seen = spy(mod)
    monkeypatch.setattr(audit, "log_event", lambda *_a, **_k: None)
    monkeypatch.setattr(timeline_service, "log", lambda *_a, **_k: None)
    mod._audit_transition(dict(REC), "Not Started", "In Progress", "firm-1", {})
    assert seen == []
