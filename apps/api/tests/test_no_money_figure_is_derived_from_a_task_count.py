"""A field whose NAME says money may not be computed from how many tasks exist.

WHAT WAS WRONG. `domain/memory_pipeline.compute_client_profile` carried a block
headed "Financial patterns" whose own comment read "Derive from task activity
patterns by month". It set `seasonal_revenue_peak` to the month in which the
most TASKS had been created and `cash_flow_risk_months` to the two months with
the next highest counts, over a comment reading "Cash flow risk: months with
highest task load typically correlate with pressure". A task count is a fact
about the PRACTICE'S OWN workload — a client whose GST work all lands in July
has a July "revenue peak" whatever their revenue did.

It was not merely a stored field. `detect_cash_flow_warnings` read
`cash_flow_risk_months` back and raised a card headed "Cash Flow Pressure
Period: <month>" at 72% confidence, whose text asserted "elevated tax
obligations and operational costs" — a claim about the client's money with a
task count behind it. The same function also wrote `avg_year_end_duration_days`
as the literal 30, commented "default estimate", into a column whose name says
it was measured.

WHY THE GUARD IS ON THE MONEY WORDS AND NOT ON THE TWO KEYS. This file's
history is full of guards that stated one spelling of their own rule and went
blind the day somebody spelled it differently. The rule here is *no
money-named profile field is derived in this module*, so the guard derives the
offending keys from a list of MONEY WORDS applied to the profile schema, and a
money-named column added next year is covered the day it is added rather than
the day somebody remembers this file.

⚠️ THE ARITHMETIC ITSELF IS NOT THE DEFECT AND IS STILL HERE. The firm profile
does the identical month-bucketing for `peak_workload_months` and
`capacity_risk_months` — names that are TRUE of a task count — and
`test_the_same_arithmetic_survives_under_a_truthful_name` pins that, because a
guard that merely deleted the capability would be a worse product and an easier
test.
"""
from __future__ import annotations

import ast
import io
import pathlib
import re

import pytest

from domain.memory_pipeline import MemoryPipeline
from repositories.memory_repository import MemoryRepository

_API = pathlib.Path(__file__).resolve().parents[1]
_PIPELINE = _API / "domain" / "memory_pipeline.py"
_WEB = _API.parents[1] / "apps" / "web"

# A field naming one of these is about MONEY. The list is the rule; the keys it
# catches are derived from it against the profile schema below.
MONEY_WORDS = (
    "revenue", "cash_flow", "cashflow", "turnover", "profit",
    "debtor", "creditor", "paise", "income", "margin", "receivable", "payable",
)


def _money_named(key: str) -> bool:
    return any(w in key.lower() for w in MONEY_WORDS)


def _profile_schema_keys() -> set[str]:
    """Every key `upsert_profile` seeds a new profile row with.

    Read off the repository rather than listed here, so the guard cannot go
    stale against a column somebody adds."""
    repo = MemoryRepository()
    row = repo.upsert_profile("firm-schema-probe", "client-schema-probe", {})
    return set(row.keys())


def _assigned_profile_keys() -> list[str]:
    """Every literal key assigned as `profile_data[<key>] = ...` in the module."""
    tree = ast.parse(io.open(_PIPELINE, encoding="utf-8").read())
    keys: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (isinstance(target, ast.Subscript)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "profile_data"
                    and isinstance(target.slice, ast.Constant)
                    and isinstance(target.slice.value, str)):
                keys.append(target.slice.value)
    return keys


# ── The vacuity controls come first, because everything below is an absence ──

def test_the_walk_finds_the_assignments_it_is_judging():
    """An AST guard over assignments that found none would pass on anything."""
    keys = _assigned_profile_keys()
    assert len(keys) >= 8, f"expected the profile builder's assignments, found {keys}"
    assert "compliance_score" in keys, keys


def test_the_money_words_would_catch_the_fields_this_is_about():
    """The word list is only a rule if it matches the schema's money columns."""
    schema = _profile_schema_keys()
    caught = {k for k in schema if _money_named(k)}
    assert "seasonal_revenue_peak" in caught, caught
    assert "cash_flow_risk_months" in caught, caught
    assert "avg_debtor_days" in caught, caught
    # And it must not be a list that matches everything.
    assert "compliance_score" not in caught, caught
    assert "portal_engagement" not in caught, caught


# ── The rule ─────────────────────────────────────────────────────────────────

def test_no_money_named_profile_field_is_written_by_the_pipeline():
    offenders = sorted({k for k in _assigned_profile_keys() if _money_named(k)})
    assert offenders == [], (
        "domain/memory_pipeline.py assigns money-named profile fields "
        f"{offenders}. Nothing in that module measures money — it reads tasks, "
        "compliance records and workflow templates. If one of these is now "
        "genuinely derived from the ledger, move the derivation to where the "
        "ledger is read and delete it from the list in this guard with a note."
    )


def test_the_fabricated_year_end_duration_is_not_written():
    """`avg_year_end_duration_days = 30  # default estimate` on a column whose
    name says it was measured. Not money-named, so the rule above misses it;
    the same defect all the same."""
    assert "avg_year_end_duration_days" not in _assigned_profile_keys()


def test_the_detector_that_raised_a_money_claim_is_gone():
    assert not hasattr(MemoryPipeline, "detect_cash_flow_warnings")
    src = io.open(_PIPELINE, encoding="utf-8").read()
    body = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))
    assert 'trigger_type="cash_flow_warning"' not in body
    assert "Cash Flow Pressure Period" not in body


def test_the_sweep_does_not_call_it():
    src = io.open(_PIPELINE, encoding="utf-8").read()
    body = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))
    assert "self.detect_cash_flow_warnings" not in body


def test_the_detect_endpoint_serves_no_permanently_empty_key():
    """Serving `cash_flow_warnings: []` for ever would read as "we looked and
    found nothing", which is a different claim from not having looked."""
    router = io.open(_API / "routers" / "memory_intelligence.py", encoding="utf-8").read()
    body = "\n".join(ln for ln in router.splitlines() if not ln.lstrip().startswith("#"))
    assert '"cash_flow_warnings"' not in body


def test_a_historical_trigger_still_renders_under_its_own_name():
    """`ai_memory_triggers.trigger_type` is a bare TEXT column with no CHECK, so
    a deployment that already wrote one of these rows still has it. The browser
    keeps the label; dropping it would render an existing row as "undefined".
    Asserted from the Python side — a guard in apps/web would be asserting the
    browser against a copy of itself."""
    page = io.open(_WEB / "app" / "memory" / "page.tsx", encoding="utf-8").read()
    assert re.search(r"cash_flow_warning:\s*\"", page), (
        "the memory screen dropped its cash_flow_warning label"
    )


# ── Behaviour: the negative controls ─────────────────────────────────────────

_TASKS = [
    # Eight tasks in July and one in November: under the old code July was the
    # "seasonal revenue peak" and July/November the "cash flow risk months".
    *[{"id": f"t{i}", "client_id": "c-money", "status": "completed",
       "title": "GST return", "description": "",
       "created_at": "2026-07-0{}T06:00:00+00:00".format(i + 1),
       "updated_at": "2026-07-0{}T06:00:00+00:00".format(i + 2),
       "due_date": "2026-07-11"} for i in range(8)],
    {"id": "t-nov", "client_id": "c-money", "status": "completed",
     "title": "Year end audit provision", "description": "",
     "created_at": "2026-11-02T06:00:00+00:00",
     "updated_at": "2026-11-04T06:00:00+00:00", "due_date": "2026-11-30"},
    {"id": "t-nov2", "client_id": "c-money", "status": "completed",
     "title": "Annual closing checklist", "description": "",
     "created_at": "2026-11-03T06:00:00+00:00",
     "updated_at": "2026-11-05T06:00:00+00:00", "due_date": "2026-11-30"},
]


class _TaskRepo:
    def find_all(self, firm_id=None, client_id=None, **kw):
        return list(_TASKS)


class _ClientRepo:
    def find_by_id(self, client_id):
        return {"id": client_id, "firm_id": "firm-money", "client_name": "Acme",
                "health_score": 80}

    def find_all(self, firm_id=None, **kw):
        return [{"id": "c-money", "firm_id": "firm-money", "health_score": 80}]


class _ComplianceRepo:
    def find_all(self, firm_id=None, **kw):
        return []


class _WorkflowRepo:
    def list_templates(self, firm_id):
        return []


@pytest.fixture
def wired(monkeypatch):
    import domain.memory_pipeline as mp
    monkeypatch.setattr(mp, "_get_task_repo", lambda: _TaskRepo())
    monkeypatch.setattr(mp, "_get_client_repo", lambda: _ClientRepo())
    monkeypatch.setattr(mp, "_get_compliance_records_repo", lambda: _ComplianceRepo())
    monkeypatch.setattr(mp, "_get_workflow_repo", lambda: _WorkflowRepo())
    return MemoryPipeline()


def test_a_client_with_a_heavy_month_gets_no_revenue_peak(wired):
    profile = wired.compute_client_profile("firm-money", "c-money")
    assert profile.get("seasonal_revenue_peak") is None
    assert profile.get("cash_flow_risk_months") in (None, [])
    assert profile.get("avg_year_end_duration_days") is None


def test_the_year_end_branch_still_runs(wired):
    """Otherwise the absence above is vacuous — the whole block could be dead."""
    profile = wired.compute_client_profile("firm-money", "c-money")
    assert profile["common_auditor_requests"] == [
        "Annual closing checklist", "Year end audit provision"]


def test_what_it_records_does_not_change_between_runs(wired):
    """`list({...})[:5]` took five members out of a set, whose iteration order
    varies between PROCESSES under hash randomisation — so the stored list
    changed from one nightly sweep to the next for no reason.

    ⚠️ This is the one assertion here that does not reliably fail against the
    previous code, and saying so is the point: a set's order is stable WITHIN a
    process, so `first == second` held there too and only `sorted` catches it,
    by luck, on some seeds. Deterministic against the current code either way."""
    first = wired.compute_client_profile("firm-money", "c-money")["common_auditor_requests"]
    second = wired.compute_client_profile("firm-money", "c-money")["common_auditor_requests"]
    assert first == second == sorted(first)


def test_the_same_arithmetic_survives_under_a_truthful_name(wired):
    """Nothing was lost. A task count IS workload; it is not revenue."""
    firm = wired.compute_firm_profile("firm-money")
    assert firm["peak_workload_months"][0] == "July"
    assert "July" in firm["capacity_risk_months"]


def test_a_task_created_after_half_past_eleven_at_night_is_in_the_indian_month(monkeypatch):
    """`created_at` is a timestamptz and comes back in UTC. 20:00 UTC on 31
    March is 01:30 IST on 1 April, so counting the UTC month puts the task in
    the wrong month — and at a month boundary that is a whole month out."""
    import domain.memory_pipeline as mp

    class _Boundary:
        def find_all(self, firm_id=None, client_id=None, **kw):
            return [{"id": "t-late", "client_id": "c-money", "status": "open",
                     "title": "", "description": "",
                     "created_at": "2026-03-31T20:00:00+00:00",
                     "updated_at": "2026-03-31T20:00:00+00:00"}]

    monkeypatch.setattr(mp, "_get_task_repo", lambda: _Boundary())
    monkeypatch.setattr(mp, "_get_client_repo", lambda: _ClientRepo())
    monkeypatch.setattr(mp, "_get_compliance_records_repo", lambda: _ComplianceRepo())
    monkeypatch.setattr(mp, "_get_workflow_repo", lambda: _WorkflowRepo())

    firm = MemoryPipeline().compute_firm_profile("firm-money")
    assert firm["peak_workload_months"] == ["April"], (
        "the month was taken in UTC, not IST"
    )
