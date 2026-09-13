"""Employer PF and ESI stop hiding inside Salaries Expense (PAY-25).

Schedule III to the Companies Act 2013, Division I, Part II requires "Employee
Benefits Expense" to be presented as (a) salaries and wages, (b) contribution to
provident and other funds, (c) share based payments and (d) staff welfare. The
payroll accrual posted ONE debit for gross PLUS the employer's 12% PF, EDLI, the
administrative charge and the employer's 3.25% ESI — so (b) was nil on every
payroll client's note and (a) was overstated by exactly the contribution.

`tests/test_payroll_journal_balance.py` covers the pure line builder. These are
about the three things it cannot see:

  * the employer share is summed off the SLIPS, because `payroll_runs` has no
    column for either employer half — only the combined totals;
  * `journal_for_payroll` resolves the new ledger ONLY when there is a
    contribution, so a client with no PF or ESI is never asked to hold it;
  * both accounts land under the same Schedule III CAPTION, so the P&L total is
    unchanged by the split and only the note's sub-classification moves. That
    is what makes this safe to land against books that already hold one-line
    entries.
"""
from __future__ import annotations

import os
import sys
from unittest.mock import patch

import pytest

_API_ROOT = os.path.join(os.path.dirname(__file__), "..")
if _API_ROOT not in sys.path:
    sys.path.insert(0, _API_ROOT)

from services.phase2_journal_service import Phase2JournalService  # noqa: E402


# ── the employer share comes off the slips ──────────────────────────────────

class _SlipQuery:
    def __init__(self, rows, calls):
        self.rows, self.calls = rows, calls
        self.selected = ""
        self.cursor = None

    def select(self, cols="*", **k):
        self.selected = cols
        return self

    def eq(self, col, val):
        self.calls.append((col, val))
        return self

    def gt(self, col, val):
        self.cursor = val
        return self

    def order(self, *a, **k): return self
    def limit(self, n): self.page = n; return self

    def execute(self):
        rows = self.rows
        if self.cursor is not None:
            rows = [r for r in rows if r["id"] > self.cursor]
        rows = sorted(rows, key=lambda r: r["id"])[: getattr(self, "page", 1000)]
        if self.selected and self.selected != "*":
            keep = [c.strip() for c in self.selected.split(",")]
            rows = [{k: v for k, v in r.items() if k in keep} for r in rows]
        return type("R", (), {"data": rows})()


class _SlipDB:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def table(self, name):
        assert name == "payroll_slips", name
        return _SlipQuery(self.rows, self.calls)


def _slip(i, pf_er=0, esi_er=0):
    return {"id": f"s{i:04d}", "pf_employer_paise": pf_er,
            "esi_employer_paise": esi_er}


def test_the_employer_share_is_summed_off_the_slips():
    db = _SlipDB([_slip(1, 180_000, 32_500), _slip(2, 120_000, 0)])
    run = {"id": "run-1", "total_edli_paise": 0, "total_pf_admin_paise": 0}
    got = Phase2JournalService._payroll_employer_contribution(db, run)
    assert got == 180_000 + 32_500 + 120_000
    assert ("run_id", "run-1") in db.calls, "must be scoped to this run"


def test_edli_and_the_admin_charge_are_added_from_the_run():
    """Both are employer cost by definition, and the admin charge carries a
    per-ESTABLISHMENT floor settled on the run — three members at Rs.60 owe
    Rs.500, not Rs.180 — so it cannot be reconstructed by summing slips."""
    db = _SlipDB([_slip(1, 180_000)])
    run = {"id": "run-1", "total_edli_paise": 7_500, "total_pf_admin_paise": 50_000}
    assert (Phase2JournalService._payroll_employer_contribution(db, run)
            == 180_000 + 7_500 + 50_000)


def test_the_slip_read_is_paged():
    """PostgREST caps a response at ~1000 rows and reports nothing when it does.
    A large client's run legitimately exceeds that, and a truncated read here
    understates the contribution — which the identity check then refuses, so
    the whole finalisation fails with a baffling message rather than a wrong
    number. Both are bad; paging is the fix."""
    rows = [_slip(i, 1_000) for i in range(1, 2_501)]
    db = _SlipDB(rows)
    run = {"id": "run-1"}
    assert Phase2JournalService._payroll_employer_contribution(db, run) == 2_500_000


def test_the_projection_carries_the_paging_key():
    """`fetch_all` keysets on `id` and reads the next cursor off the last row —
    a projection that omits it works to the thousandth row and then cannot
    advance."""
    db = _SlipDB([_slip(1, 100)])
    Phase2JournalService._payroll_employer_contribution(db, {"id": "run-1"})
    import inspect
    src = inspect.getsource(Phase2JournalService._payroll_employer_contribution)
    assert '"id, pf_employer_paise, esi_employer_paise"' in src


def test_a_run_with_no_id_contributes_nothing_rather_than_reading_every_slip():
    """A run dict with no id (mock mode, a fixture) must not fan out to the
    whole table — an unfiltered read would sum every slip in the database."""
    db = _SlipDB([_slip(1, 999_999)])
    assert Phase2JournalService._payroll_employer_contribution(db, {}) == 0
    assert db.calls == []


# ── the posting path ────────────────────────────────────────────────────────

_LEDGERS = {
    "%Salaries Expense%": "A-SALARIES",
    "%Contribution to Provident%": "A-CONTRIB",
    "%Net Salary Payable%": "A-NET",
    "%PF Payable%": "A-PF",
    "%ESI Payable%": "A-ESI",
    "%PT Payable%": "A-PT",
    "%TDS Payable - Salary%": "A-TDS-SAL",
    "%Employee Loans%": "A-LOANS",
}


class _PostingDB:
    """Resolves the chart by ILIKE pattern, serves the slips, and captures what
    the kernel handed to `post_journal_atomic`."""

    def __init__(self, slips, missing=()):
        self.slips = slips
        self.missing = set(missing)
        self.posted: list[dict] = []
        self.resolved: list[str] = []

    def table(self, name):
        return _PostingQuery(name, self)

    def rpc(self, fn, params=None):
        if fn == "post_journal_atomic" and params:
            self.posted.extend(params.get("p_lines") or [])
            return type("R", (), {"execute": lambda _s: type("D", (), {"data": "JNL-1"})()})()
        return type("R", (), {"execute": lambda _s: type("D", (), {"data": None})()})()


class _PostingQuery:
    def __init__(self, table, db):
        self.table_name, self.db = table, db
        self.op, self.payload, self.pattern, self.cursor = "select", None, None, None
        self.selected = ""

    def select(self, cols="*", **k): self.selected = cols; return self
    def insert(self, payload): self.op, self.payload = "insert", payload; return self
    def update(self, payload): self.op, self.payload = "update", payload; return self
    def eq(self, col, val): self.filter = (col, val); return self
    def ilike(self, col, pattern): self.pattern = pattern; return self
    def gt(self, col, val): self.cursor = val; return self
    def or_(self, *a, **k): return self
    def is_(self, *a, **k): return self
    def in_(self, *a, **k): return self
    def order(self, *a, **k): return self
    def limit(self, n): self.page = n; return self
    def maybe_single(self): return self

    def execute(self):
        if self.table_name == "chart_of_accounts":
            if self.pattern:
                self.db.resolved.append(self.pattern)
                acc = (None if self.pattern in self.db.missing
                       else _LEDGERS.get(self.pattern))
                return type("R", (), {"data": [{"id": acc}] if acc else []})()
            return type("R", (), {"data": []})()
        if self.table_name == "payroll_slips":
            rows = self.db.slips
            if self.cursor is not None:
                rows = [r for r in rows if r["id"] > self.cursor]
            rows = sorted(rows, key=lambda r: r["id"])[: getattr(self, "page", 1000)]
            return type("R", (), {"data": rows})()
        return type("R", (), {"data": []})()


def _service():
    with patch.dict(os.environ, {"SUPABASE_URL": "https://mock.supabase.co"}):
        import importlib
        import services.phase2_journal_service as mod
        importlib.reload(mod)
        return mod.Phase2JournalService()


def teardown_module(_module):
    import importlib
    import services.phase2_journal_service as mod
    importlib.reload(mod)


def _run(**kw):
    """One member at the PF ceiling: gross Rs.50,000, employee and employer PF
    Rs.1,800 each, EDLI Rs.75, the Rs.500 establishment admin floor."""
    base = {
        "id": "run-1", "month": "2026-06",
        "total_gross_paise": 5_000_000,
        "total_net_paise": 4_820_000,          # gross less the employee's own PF
        "total_pf_paise": 360_000,
        "total_esi_paise": 0, "total_pt_paise": 0, "total_tds_paise": 0,
        "total_loan_recovery_paise": 0,
        "total_edli_paise": 7_500, "total_pf_admin_paise": 50_000,
    }
    base.update(kw)
    return base


def _post(svc, run, db, monkeypatch):
    import services.phase2_journal_service as mod
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: db)
    monkeypatch.setattr(mod, "_USE_MOCK", False)
    return svc.journal_for_payroll(run, "F1", "C1")


def _debit_on(db, account):
    return sum(int(l["debit_paise"]) for l in db.posted if l["account_id"] == account)


def test_the_accrual_splits_the_two_heads_and_foots(monkeypatch):
    svc = _service()
    db = _PostingDB([_slip(1, 180_000, 0)])
    _post(svc, _run(), db, monkeypatch)

    assert db.posted, "nothing posted"
    debits = sum(int(l["debit_paise"]) for l in db.posted)
    credits = sum(int(l["credit_paise"]) for l in db.posted)
    assert debits == credits, "the accrual must foot"

    # (a) salaries and wages is GROSS — IT Act s.17(1).
    assert _debit_on(db, "A-SALARIES") == 5_000_000
    # (b) contribution to provident and other funds: employer 12% + EDLI + admin.
    assert _debit_on(db, "A-CONTRIB") == 180_000 + 7_500 + 50_000
    # And nothing of the employer's contribution is left on salaries.
    assert debits == 5_000_000 + 237_500


def test_a_client_with_no_pf_or_esi_never_resolves_the_contribution_ledger(monkeypatch):
    """`_find_account` RAISES on a missing account, so resolving it
    unconditionally would refuse finalisation for every firm whose chart
    predates migration 375 — including one that will never post to it."""
    svc = _service()
    db = _PostingDB([_slip(1, 0, 0)])
    run = _run(total_net_paise=5_000_000, total_pf_paise=0,
               total_edli_paise=0, total_pf_admin_paise=0)
    _post(svc, run, db, monkeypatch)

    assert "%Contribution to Provident%" not in db.resolved
    assert _debit_on(db, "A-CONTRIB") == 0
    assert _debit_on(db, "A-SALARIES") == 5_000_000


def test_a_chart_without_the_ledger_refuses_rather_than_posting_it_to_salaries(monkeypatch):
    """The other direction. A firm that DOES owe a contribution and has no
    account for it must not silently fall back to the old single-line entry —
    that is the defect, and it would be undetectable afterwards."""
    svc = _service()
    db = _PostingDB([_slip(1, 180_000, 0)], missing={"%Contribution to Provident%"})
    with pytest.raises(ValueError):
        _post(svc, _run(), db, monkeypatch)
    assert not db.posted, "nothing may be posted when the head cannot be resolved"


# ── the presentation is unchanged at caption level ──────────────────────────

def test_both_accounts_land_under_one_schedule_iii_caption():
    """Schedule III Part II presents the split in the NOTE, under one caption on
    the face. So the P&L total for Employee Benefits Expense is the same before
    and after PAY-25, and a book holding both the old one-line entries and the
    new two-line ones still foots to the same caption — which is what makes
    this safe to land without touching a posted journal."""
    from domain.reporting.schedule_iii import classify
    # `classify` returns (caption, how_it_was_decided).
    for subtype in ("Salary", "Employee Benefits"):
        caption, _how = classify("Expense", subtype, None)
        assert caption == "Employee Benefits Expense", subtype


def test_the_seeded_chart_carries_the_contribution_head():
    from services.coa_seed_service import STANDARD_COA
    rows = [r for r in STANDARD_COA if "Contribution to Provident" in r[1]]
    assert len(rows) == 1, "exactly one contribution head"
    code, name, atype, asub = rows[0]
    assert atype == "Expense"
    # The subtype is load-bearing: schedule_iii buckets on it, and one that does
    # not contain employee/salary/wages/staff would silently relocate the whole
    # employer contribution to another caption.
    assert "Employee" in asub


def test_the_name_collides_with_no_posting_pattern():
    """`_find_account` resolves payroll accounts by ILIKE alone with `.limit(1)`
    and no ordering, so a new account matching an existing pattern could be
    returned for a lookup that means something else."""
    import re
    src = open(os.path.join(_API_ROOT, "services", "phase2_journal_service.py")).read()
    patterns = set(re.findall(r'"(%[^"]*%)"', src))
    name = "Contribution to Provident and Other Funds".lower()
    for p in patterns:
        if p == "%Contribution to Provident%":
            continue
        needle = p.strip("%").lower()
        assert needle not in name, f"{name!r} would also match {p}"
