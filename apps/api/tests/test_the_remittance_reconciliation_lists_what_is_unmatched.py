"""GET /clients/{id}/remittance-reconciliation — the month-end list (F4).

The pure ranking is tested in test_which_entry_paid_this_remittance.py. This
drives the real endpoint against a FakeDB, because what can only go wrong here
is the fetching: the right liability account for the scheme, a query bounded by
the answer rather than the ledger, and entries that never touched the account
kept out of the shortlist.
"""
from __future__ import annotations

import pytest

import routers.payroll as pay
from services import statutory_remittance_service as svc
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "id": "u1", "auth_user_id": "auth",
          "email": "ca@f.test", "role": "Partner"}
ESI_ACC, PT_ACC, BANK_ACC = "ACC-ESI", "ACC-PT", "ACC-BANK"


def _setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [pay])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "client_name": "Acme"})
    for aid, name in ((ESI_ACC, "ESI Payable"), (PT_ACC, "PT Payable"),
                      (BANK_ACC, "Bank - Current")):
        db.seed("chart_of_accounts", {
            "id": aid, "firm_id": FIRM, "client_id": "CLI",
            "account_name": name, "account_type": "Liability",
            "is_active": True})
    return db


def _entry(db, eid, on, lines, **over):
    db.seed("journal_entries", {
        "id": eid, "firm_id": FIRM, "client_id": "CLI", "entry_date": on,
        "reference_no": over.get("reference_no", f"PAY/{eid}"),
        "narration": over.get("narration", "statutory payment"),
        "deleted_at": None})
    for account_id, dr, cr in lines:
        db.seed("journal_lines", {
            "journal_entry_id": eid, "account_id": account_id,
            "debit_paise": dr, "credit_paise": cr})


def _remit(db, **over):
    args = dict(firm_id=FIRM, client_id="CLI", scheme=svc.ESIC,
                wage_month="2026-09", submitted_on="2026-10-14",
                status=svc.PAID, paid_on="2026-10-15", amount_paise=10_500_00)
    args.update(over)
    return svc.record(db, **args)


def _unmatched(monkeypatch_db):
    res = pay.remittance_reconciliation("CLI", CALLER)
    assert res["success"] is True, res
    return res["data"]["unmatched"]


# ── the list ────────────────────────────────────────────────────────────────

def test_a_paid_remittance_with_no_entry_is_listed_with_its_candidates(monkeypatch):
    db = _setup(monkeypatch)
    _remit(db)
    _entry(db, "JE1", "2026-10-15",
           [(ESI_ACC, 10_000_00, 0), ("ACC-INT", 500_00, 0), (BANK_ACC, 0, 10_500_00)])
    [row] = _unmatched(db)
    assert row["scheme"] == svc.ESIC
    assert [c["journal_entry_id"] for c in row["candidates"]] == ["JE1"]
    assert row["candidates"][0]["grade"] == "exact"


def test_a_remittance_already_linked_is_not_listed(monkeypatch):
    db = _setup(monkeypatch)
    row = _remit(db)
    _entry(db, "JE1", "2026-10-15", [(ESI_ACC, 10_500_00, 0), (BANK_ACC, 0, 10_500_00)])
    assert svc.link_payment(db, firm_id=FIRM, remittance_id=row["id"],
                            journal_entry_id="JE1")
    assert _unmatched(db) == []


def test_a_remittance_only_filed_is_not_listed(monkeypatch):
    """Unmatched means PAID with no entry. A return merely filed has no payment
    to match yet, and listing it would bury the real ones."""
    db = _setup(monkeypatch)
    _remit(db, status=svc.SUBMITTED, paid_on=None)
    assert _unmatched(db) == []


# ── what makes an entry a candidate ─────────────────────────────────────────

def test_an_entry_that_never_touched_the_liability_is_not_a_candidate(monkeypatch):
    """Right date, right amount, wrong account — a rent payment on the day the
    ESI challan was paid is not a candidate for paying it."""
    db = _setup(monkeypatch)
    _remit(db)
    _entry(db, "JE1", "2026-10-15", [("ACC-RENT", 10_500_00, 0), (BANK_ACC, 0, 10_500_00)])
    [row] = _unmatched(db)
    assert row["candidates"] == []


def test_a_professional_tax_remittance_looks_at_the_pt_ledger(monkeypatch):
    """Each scheme settles its own account. A matcher reading the wrong one
    finds nothing and reports every remittance as unmatched, which is worse
    than no matcher."""
    db = _setup(monkeypatch)
    _remit(db, scheme=svc.PROFESSIONAL_TAX, state="Maharashtra", amount_paise=20_000)
    _entry(db, "ESI-PAYMENT", "2026-10-15", [(ESI_ACC, 20_000, 0), (BANK_ACC, 0, 20_000)])
    _entry(db, "PT-PAYMENT", "2026-10-15", [(PT_ACC, 20_000, 0), (BANK_ACC, 0, 20_000)])
    [row] = _unmatched(db)
    assert [c["journal_entry_id"] for c in row["candidates"]] == ["PT-PAYMENT"]


def test_an_entry_outside_the_window_is_not_fetched_at_all(monkeypatch):
    db = _setup(monkeypatch)
    _remit(db)
    _entry(db, "JE1", "2026-11-20", [(ESI_ACC, 10_500_00, 0), (BANK_ACC, 0, 10_500_00)])
    [row] = _unmatched(db)
    assert row["candidates"] == []


def test_the_entry_total_is_what_left_the_bank_not_the_liability_debit(monkeypatch):
    """A late challan carries interest under ESI Act s.39(5), which is an
    expense and not a reduction of the payable. The challan is 10,500 and the
    payable moved by 10,000 — matching on the liability debit would miss it."""
    db = _setup(monkeypatch)
    _remit(db)
    _entry(db, "JE1", "2026-10-15",
           [(ESI_ACC, 10_000_00, 0), ("ACC-INT", 500_00, 0), (BANK_ACC, 0, 10_500_00)])
    [row] = _unmatched(db)
    c = row["candidates"][0]
    assert c["grade"] == "exact"
    assert c["entry_total_paise"] == 10_500_00
    assert c["liability_debit_paise"] == 10_000_00


# ── scope and refusals ──────────────────────────────────────────────────────

def test_the_endpoint_goes_through_the_scope_helper(monkeypatch):
    """`core.authz` reads its own `_USE_MOCK` at import and short-circuits
    `can_access_client` to True, so the real 404 cannot be exercised from this
    harness. What IS pinned is that the endpoint asks — the same shape
    test_a_mis_imported_statement_can_be_undone uses for the same reason."""
    from fastapi import HTTPException
    db = _setup(monkeypatch)
    _remit(db)

    def _refuse(user, client_id):
        raise HTTPException(status_code=404, detail="Not found")
    monkeypatch.setattr(pay, "assert_client_access", _refuse)

    with pytest.raises(HTTPException) as exc:
        pay.remittance_reconciliation("CLI", CALLER)
    assert exc.value.status_code == 404


def test_no_remittance_crosses_a_firm_boundary(monkeypatch):
    """The isolation that does not depend on the authz mode at all: every query
    behind this endpoint carries .eq("firm_id", ...), which is the primary
    control because the service-role key bypasses RLS."""
    db = _setup(monkeypatch)
    _remit(db)
    _entry(db, "JE1", "2026-10-15", [(ESI_ACC, 10_500_00, 0), (BANK_ACC, 0, 10_500_00)])
    assert _unmatched(db), "the owning firm sees its own remittance"

    res = pay.remittance_reconciliation("CLI", {**CALLER, "firm_id": "FIRM-B"})
    assert res["data"]["unmatched"] == []


def test_a_client_with_no_liability_account_reports_no_candidates(monkeypatch):
    """A chart with no ESI Payable has never accrued ESI. Nothing to reconcile
    is an answer; a 500 on a month-end screen is not."""
    db = FakeDB()
    wire_e2e(monkeypatch, db, [pay])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "client_name": "Acme"})
    _remit(db)
    [row] = _unmatched(db)
    assert row["candidates"] == []


def test_mock_mode_answers_the_shape(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    assert pay.remittance_reconciliation("CLI", CALLER)["data"]["unmatched"] == []


def test_the_endpoint_reads_and_never_links(monkeypatch):
    """The link is written by PATCH .../payment and nowhere else, and it is a
    LINK — bank_posting_service.post is the one path for money movement, so a
    posting here would debit the statutory liability twice."""
    db = _setup(monkeypatch)
    row = _remit(db)
    _entry(db, "JE1", "2026-10-15", [(ESI_ACC, 10_500_00, 0), (BANK_ACC, 0, 10_500_00)])
    _unmatched(db)
    stored = svc.read(db, firm_id=FIRM, client_id="CLI")[0]
    assert stored.get("journal_entry_id") in (None, ""), (
        "reading the reconciliation must not tie anything to anything")
    assert row["id"] == stored["id"]
