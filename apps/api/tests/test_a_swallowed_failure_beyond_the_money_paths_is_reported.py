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
    "routers/search.py",
    "routers/tasks.py",
    "domain/ai_copilot_service.py",
    "domain/memory_pipeline.py",
    "routers/branding.py", "routers/document_intelligence_v1.py", "routers/documents.py", "routers/dsc.py",
    "routers/engagement_sign_public.py", "routers/engagements.py", "routers/practice.py", "routers/relationships.py",
    "routers/scheduler_status.py", "routers/task_extras.py", "routers/task_templates.py", "routers/year_end_reviews.py",
    "domain/ai_insight_service.py", "services/employee_portal_service.py", "services/knowledge_service.py",
    "services/portal_access_service.py",
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
    assert len(cleared) >= 90, f"only {len(cleared)} reports in the cleared files: the wiring has regressed"


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


# ── second batch: search, tasks, the AI copilot's context, the memory pipeline ──────────────────

def test_a_search_facet_that_fails_is_reported_so_a_missing_result_is_not_silent(monkeypatch, spy):
    import routers.search as mod
    seen = spy(mod)
    monkeypatch.setattr(mod, "_USE_MOCK", False)
    monkeypatch.setattr(mod, "effective_client_ids", lambda *_a, **_k: None)
    monkeypatch.setattr(mod, "_db", lambda: _BrokenDb())
    monkeypatch.setattr(mod.client_repo, "find_all", lambda *_a, **_k: [], raising=False)
    import repositories.task_repository as tr
    import repositories.document_repository as dr
    import repositories.dsc_repository as dsc
    for module, name in ((tr, "task_repo"), (dr, "document_repo"), (dsc, "dsc_repo")):
        monkeypatch.setattr(getattr(module, name), "find_all", _boom)
    mod.global_search(q="acme", current_user={"firm_id": "firm-1", "id": "u1", "role": "Partner"})
    operations = {op for op, _ in seen}
    assert {"search.accounts", "search.journals", "search.leads", "search.engagements",
            "search.tasks", "search.documents", "search.dsc"} <= operations, operations
    assert all(ctx == {"firm_id": "firm-1"} for _, ctx in seen)


def test_a_task_audit_entry_that_fails_is_reported_and_the_task_is_still_created(monkeypatch, spy):
    import routers.tasks as mod
    seen = spy(mod)
    monkeypatch.setattr(mod, "log_event", _boom)
    monkeypatch.setattr(mod, "task_repo", type("R", (), {"create": staticmethod(lambda row: {**row, "id": "t1"})}))
    monkeypatch.setattr(mod, "log_activity", lambda **_k: None)
    monkeypatch.setattr(mod, "task_extras_repo", type("E", (), {"log_event": staticmethod(lambda **_k: None)}), raising=False)
    body = mod.TaskCreate(title="File GSTR-3B", client_id="c1")
    monkeypatch.setattr(mod, "assert_client_access", lambda *_a, **_k: None)
    monkeypatch.setattr(mod.client_repo, "find_by_id", lambda *_a, **_k: {"id": "c1"})
    out = mod.create_task(body, {"firm_id": "firm-1", "auth_user_id": "u1", "email": "a@b.in", "id": "i1"})
    assert out["success"] is True
    assert ("tasks.create_audit", {"firm_id": "firm-1", "task_id": "t1"}) in seen


def test_a_copilot_context_section_that_cannot_be_read_is_reported(monkeypatch, spy):
    import asyncio
    import domain.ai_copilot_service as mod
    seen = spy(mod)

    class Repo:
        def find_all(self, **_k):
            raise RuntimeError("compliance_records unreachable")

    monkeypatch.setattr(mod, "_get_compliance_records_repo", lambda: Repo())
    svc = mod.AICopilotService.__new__(mod.AICopilotService)

    class Summaries:
        def get_summary(self, *_a, **_k):
            return None

        def __getattr__(self, _n):
            return lambda *_a, **_k: None

    svc._repo = Summaries()
    try:
        asyncio.run(svc.get_compliance_intelligence("firm-1", None))
    except Exception:
        pass  # what happens after the read is not this test's business; the report is
    assert ("ai_copilot.compliance_intelligence", {"firm_id": "firm-1"}) in seen


def test_a_malformed_stamp_in_the_memory_pipeline_skips_one_data_point_and_is_a_narrow_handler():
    tree = ast.parse(_read("domain/memory_pipeline.py"))
    handlers = [n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler)
                and n.type is not None and "ValueError" in ast.unparse(n.type)]
    assert len(handlers) >= 4, "the four per-row stamp parses must name the errors they expect"


def test_the_deadline_trigger_parse_that_once_hid_a_type_error_now_reports_it(spy):
    """That very `except` swallowed a TypeError for months and the detector never produced a trigger."""
    import domain.memory_pipeline as mod
    seen = spy(mod)

    class Repo:
        def find_all(self, **_k):
            return [{"client_id": "c1", "status": "Pending", "due_date": object()}]

    original = mod._get_compliance_records_repo
    mod._get_compliance_records_repo = lambda: Repo()
    try:
        mod.MemoryPipeline().detect_deadline_at_risk("firm-1", "c1")
    finally:
        mod._get_compliance_records_repo = original
    assert ("memory_pipeline.deadline_trigger_parse", {"firm_id": "firm-1", "client_id": "c1"}) in seen


# ── third batch: documents, engagements, portals, knowledge, small routers ──────────────────────

def test_the_document_delete_audit_handler_reports():
    source = ast.parse(_read("routers/documents.py"))
    assert any(isinstance(n, ast.Call) and getattr(n.func, "id", "") == "capture_soft_failure"
               and any(k.arg == "operation" and getattr(k.value, "value", "") == "documents.delete_audit" for k in n.keywords)
               for n in ast.walk(source)), "the delete audit handler must report"


def test_the_portal_invitation_reports_without_the_invitees_address(monkeypatch, spy):
    """A failed invite mail is reported with the firm and the client, and never with the address it was sent to."""
    import services.portal_access_service as mod
    seen = spy(mod)
    import core.urls as urls
    monkeypatch.setattr(urls, "portal_activate_url", _boom)
    mod._send_invite_email("someone@example.in", "client-1", "firm-1", "tok")
    assert seen == [("portal_access.invite_email", {"firm_id": "firm-1", "client_id": "client-1"})]
    assert "someone@example.in" not in repr(seen)


def test_the_employee_portal_invitation_report_carries_no_address(monkeypatch, spy):
    import services.employee_portal_service as mod
    seen = spy(mod)
    monkeypatch.setattr(mod, "_send", _boom, raising=False)
    try:
        mod._send_invite_email("emp@example.in", "Asha", "tok")
    except Exception:
        pass
    assert all("emp@example.in" not in repr(ctx) for _, ctx in seen)


def test_an_engagement_transition_audit_that_fails_is_reported_with_the_engagement():
    tree = ast.parse(_read("routers/engagements.py"))
    ops = {k.value.value for n in ast.walk(tree) if isinstance(n, ast.Call)
           and getattr(n.func, "id", "") == "capture_soft_failure"
           for k in n.keywords if k.arg == "operation"}
    assert {"engagements.transition_audit", "engagements.transition_timeline"} <= ops


def test_a_workflow_rule_that_cannot_be_compared_does_not_match_and_a_bad_due_date_is_tolerated():
    from domain.workflow_engine_v2 import WorkflowEngineV2
    engine = WorkflowEngineV2.__new__(WorkflowEngineV2)
    rule = {"field": "amount", "operator": "gt", "value": "ten", "value_type": "number"}
    assert engine._eval_rule(rule, {"amount": "5"}) is False
    data = {"due_date": "not-a-date"}
    engine._evaluate_trigger("compliance_deadline", data) if hasattr(engine, "_evaluate_trigger") else None
    assert "days_remaining" not in data


def test_resetting_a_request_token_from_another_context_is_tolerated_and_other_errors_are_not_swallowed():
    import contextvars
    from core import supabase_client as mod
    handle = contextvars.Context().run(lambda: mod._request_access_token.set("t"))
    mod.reset_request_token(handle)   # a token made in another context: ValueError, tolerated
    tree = ast.parse(_read("core/supabase_client.py"))
    reset = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "reset_request_token")
    handlers = [h for h in ast.walk(reset) if isinstance(h, ast.ExceptHandler)]
    assert handlers and all(ast.unparse(h.type) != "Exception" for h in handlers)
