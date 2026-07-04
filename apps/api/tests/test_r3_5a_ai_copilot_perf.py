"""
R3.5a — proves domain/ai_copilot_service.py's cross-tenant + unbounded-fetch
fixes.

Before this fix: `_get_task_repo().find_overdue()` scanned every firm's
tasks (no firm_id parameter existed on the repo method at all), then
filtered to the caller's firm in Python — the same cross-tenant-scan
pattern R3.15 closed for routers/health.py, just not exposed via a query
param this time. Separately, `_build_context`'s compliance branch and
`get_compliance_intelligence` each re-fetched the firm's entire
compliance_records history 2x/3x independently within a single request.
"""
import asyncio

import domain.ai_copilot_service as mod
from repositories.task_repository import task_repo


class _CountingComplianceRepo:
    """Records every find_all() call so tests can assert fetch count."""
    def __init__(self, records):
        self.records = records
        self.calls: list[dict] = []

    def find_all(self, firm_id=None, client_id=None, status=None, compliance_type=None):
        self.calls.append({"firm_id": firm_id, "client_id": client_id, "status": status})
        records = self.records
        if firm_id:
            records = [r for r in records if r.get("firm_id") == firm_id]
        if status:
            records = [r for r in records if r.get("status") == status]
        return records


def test_task_repo_find_overdue_scopes_to_firm():
    """repositories/task_repository.py: find_overdue(firm_id=...) must only
    return the caller's own firm's overdue tasks, not every firm's."""
    from mock_data import MOCK_TASKS
    original = list(MOCK_TASKS)
    try:
        MOCK_TASKS.clear()
        MOCK_TASKS.extend([
            {"id": "t1", "firm_id": "firm-A", "client_id": "c1", "status": "open", "due_date": "2020-01-01"},
            {"id": "t2", "firm_id": "firm-B", "client_id": "c2", "status": "open", "due_date": "2020-01-01"},
        ])
        result_a = task_repo.find_overdue(firm_id="firm-A")
        assert [t["id"] for t in result_a] == ["t1"]
        result_b = task_repo.find_overdue(firm_id="firm-B")
        assert [t["id"] for t in result_b] == ["t2"]
        # Backward-compatible default (no firm_id) still scans everything —
        # existing callers that haven't been migrated keep working.
        result_all = task_repo.find_overdue()
        assert {t["id"] for t in result_all} == {"t1", "t2"}
    finally:
        MOCK_TASKS.clear()
        MOCK_TASKS.extend(original)


def test_build_context_compliance_branch_fetches_once(monkeypatch):
    """_build_context's 'global'/'compliance' branch used to call find_all()
    twice (once via _overdue_compliance_records, once via
    _due_within_days_compliance_records) — now derives both from one fetch."""
    records = [
        {"id": "r1", "firm_id": "F1", "client_id": "c1", "status": "Overdue", "due_date": "2020-01-01"},
        {"id": "r2", "firm_id": "F1", "client_id": "c1", "status": "Not Started", "due_date": "2099-01-01"},
    ]
    fake_repo = _CountingComplianceRepo(records)
    monkeypatch.setattr(mod, "_get_compliance_records_repo", lambda: fake_repo)
    monkeypatch.setattr(mod, "_get_client_repo", lambda: type("R", (), {"find_all": lambda self, **kw: []})())
    monkeypatch.setattr(mod, "_get_task_repo", lambda: type("R", (), {"find_overdue": lambda self, **kw: []})())

    svc = mod.AICopilotService.__new__(mod.AICopilotService)
    ctx = svc._build_context("F1", "global", None, allowed_client_ids=None)

    assert "OVERDUE COMPLIANCE FILINGS: 1" in ctx
    assert len(fake_repo.calls) == 1, f"expected exactly 1 find_all() call, got {len(fake_repo.calls)}: {fake_repo.calls}"


def test_get_compliance_intelligence_fetches_once(monkeypatch):
    """get_compliance_intelligence used to call find_all() three times
    (all_tasks, overdue_tasks, due_soon_tasks) — now derives all three
    from one fetch."""
    records = [
        {"id": "r1", "firm_id": "F1", "client_id": "c1", "status": "Overdue",
         "due_date": "2020-01-01", "compliance_type": "GST"},
        {"id": "r2", "firm_id": "F1", "client_id": "c1", "status": "Not Started",
         "due_date": "2099-01-01", "compliance_type": "GST"},
    ]
    fake_repo = _CountingComplianceRepo(records)
    monkeypatch.setattr(mod, "_get_compliance_records_repo", lambda: fake_repo)

    svc = mod.AICopilotService.__new__(mod.AICopilotService)

    class _FakeAiRepo:
        def get_summary(self, *a, **kw):
            return None
        def upsert_summary(self, firm_id, kind, ctx_id, payload):
            return {"firm_id": firm_id, "kind": kind, **payload}

    svc._repo = _FakeAiRepo()

    async def _fake_call_groq(self, messages):
        return "fake analysis", 10
    monkeypatch.setattr(mod.AICopilotService, "_call_groq", _fake_call_groq)

    result = asyncio.run(svc.get_compliance_intelligence("F1"))

    assert "1 overdue filings" in result["key_points"][0]
    assert len(fake_repo.calls) == 1, f"expected exactly 1 find_all() call, got {len(fake_repo.calls)}: {fake_repo.calls}"
