"""The task dashboard summary serves counts it counted, and no literal (POST-A-242).

THE DEFECT
    `TaskDomainService.get_dashboard_summary` returned `"documents_pending_review": 2` as a constant. No screen read the key,
    but the same payload feeds the AI copilot's context (`routers/ai_copilot.py` calls the function for both its routes), so
    an invented "2 documents are waiting for review" was one prompt away from being said to a CA about their own firm. An
    invented number on a payload is the defect this product's screens are held against, and it was found while reviewing
    POST-A-048. The key and its type are gone; the document review count belongs to the documents hub, which counts the
    `documents` table per client and is scoped to the caller's clients, and nothing here is asked for it.

WHAT IS HELD
    * the summary has no `documents_pending_review` key and the browser type does not declare it;
    * no value in the returned dict is a bare numeric literal (`"x": 2`), whatever its key: a figure in this payload is
      counted from rows or it is not served. A count that is genuinely zero is still `len([...])`, never `0`.
"""
from __future__ import annotations

import ast
from pathlib import Path

from domain.task_service import TaskDomainService

API = Path(__file__).resolve().parents[1]
WEB_TYPES = Path(__file__).resolve().parents[3] / "apps" / "web" / "lib" / "types" / "index.ts"


def _returned_dict() -> ast.Dict:
    tree = ast.parse((API / "domain" / "task_service.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "get_dashboard_summary")
    returns = [n for n in ast.walk(fn) if isinstance(n, ast.Return) and isinstance(n.value, ast.Dict)]
    assert len(returns) == 1, "the summary is expected to end in exactly one returned dict literal"
    return returns[0].value


def test_no_value_in_the_summary_is_a_numeric_literal():
    invented = [ast.literal_eval(k) for k, v in zip(_returned_dict().keys, _returned_dict().values, strict=True)
                if isinstance(v, ast.Constant) and isinstance(v.value, (int, float)) and not isinstance(v.value, bool)]
    assert invented == [], f"served figures that were never counted: {invented}"


def test_the_invented_key_is_gone_from_the_payload_and_the_type():
    keys = {ast.literal_eval(k) for k in _returned_dict().keys}
    assert "documents_pending_review" not in keys
    assert "documents_pending_review" not in WEB_TYPES.read_text(encoding="utf-8")


def test_negative_control_the_scan_finds_a_literal():
    tree = ast.parse('def f():\n    return {"a": len(x), "documents_pending_review": 2, "b": 0}\n')
    d = next(n for n in ast.walk(tree) if isinstance(n, ast.Dict))
    literals = [ast.literal_eval(k) for k, v in zip(d.keys, d.values, strict=True) if isinstance(v, ast.Constant)]
    assert literals == ["documents_pending_review", "b"]


def test_the_summary_still_serves_its_counted_keys(monkeypatch):
    import domain.task_service as ts

    class _Repo:
        def find_all(self, **_k): return []
        def find_open(self, **_k): return []
        def find_overdue(self, **_k): return []

    class _Records:
        def list_records(self, **_k): return []
        def score_from_records(self, _r, _today=None): return (100, None)

    monkeypatch.setattr(ts, "client_repo", _Repo())
    monkeypatch.setattr(ts, "task_repo", _Repo())
    import domain.compliance_record_service as crs
    monkeypatch.setattr(crs, "compliance_record_service", _Records())
    out = TaskDomainService().get_dashboard_summary(firm_id="F1")
    assert out["active_clients"] == 0 and out["total_open_tasks"] == 0 and out["overdue_tasks"] == 0
    assert "documents_pending_review" not in out
