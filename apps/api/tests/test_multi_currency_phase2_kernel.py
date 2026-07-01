"""
Multi-Currency Phase 2 (Accounting Foundation) — posting-kernel tests.

The kernel is now currency-AWARE but behaviour is unchanged for INR: it still
balances in base (debit_paise/credit_paise), and every posted line carries INR
currency metadata (txn == base, rate 1, source "identity"). A non-INR posting is
REFUSED unless an active CurrencyPolicy is supplied (the authoritative gate, G2).
No foreign documents are implemented here — the foreign cases are kernel-capability
tests proving the kernel can carry/freeze the metadata for later phases.
"""
from decimal import Decimal
from datetime import date

import pytest

import services.phase2_journal_service as pjs
from domain.currency import CurrencyPolicy
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa, coa_id

FIRM = "FIRM-MC2"


def _setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [pjs])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    seed_standard_coa(db, FIRM, "CLI")
    return db


def _inr_lines(db):
    return [
        {"account_id": coa_id(db, FIRM, "ar"), "debit_paise": 1000, "credit_paise": 0},
        {"account_id": coa_id(db, FIRM, "revenue"), "debit_paise": 0, "credit_paise": 1000},
    ]


def _lines_of(db, eid):
    return db.table("journal_lines").select("*").eq("journal_entry_id", eid).execute().data


def _entry(db, eid):
    return db.table("journal_entries").select("*").eq("id", eid).execute().data[0]


# ── INR path: currency-aware but byte-for-byte in behaviour ───────────────────
def test_inr_posting_stamps_identity_currency_metadata(monkeypatch):
    db = _setup(monkeypatch)
    eid = pjs.phase2_journal_service._create_journal(
        db, firm_id=FIRM, client_id="CLI", entry_date="2025-06-01",
        reference_no="INR-1", narration="n", entry_type="Journal", lines=_inr_lines(db))
    lines = _lines_of(db, eid)
    assert len(lines) == 2
    for ln in lines:
        assert ln["txn_currency"] == "INR" and ln["base_currency"] == "INR"
        assert Decimal(ln["exchange_rate"]) == Decimal(1)
        assert ln["rate_type"] == "booking"
        assert ln["rate_source"] == "identity"
        assert ln["rate_date"] == "2025-06-01"
        # G4 dual storage: for INR the txn amount equals the base amount
        assert ln["txn_debit"] == ln["debit_paise"]
        assert ln["txn_credit"] == ln["credit_paise"]


def test_inr_entry_has_no_rate_selection_provenance(monkeypatch):
    db = _setup(monkeypatch)
    eid = pjs.phase2_journal_service._create_journal(
        db, firm_id=FIRM, client_id="CLI", entry_date="2025-06-01",
        reference_no="INR-2", narration="n", entry_type="Journal", lines=_inr_lines(db))
    entry = _entry(db, eid)
    # inert: no rate was "selected" for an auto INR posting
    assert entry.get("rate_overridden") in (None, False)
    assert entry.get("rate_selected_by") is None


def test_existing_invariants_unchanged(monkeypatch):
    db = _setup(monkeypatch)
    k = pjs.phase2_journal_service
    # Imbalance still rejected (base debit != base credit)
    with pytest.raises(ValueError, match="imbalance"):
        k._create_journal(db, firm_id=FIRM, client_id="CLI", entry_date="2025-06-01",
                          reference_no="BAD", narration="n", entry_type="Journal",
                          lines=[{"account_id": coa_id(db, FIRM, "ar"), "debit_paise": 1000, "credit_paise": 0},
                                 {"account_id": coa_id(db, FIRM, "revenue"), "debit_paise": 0, "credit_paise": 999}])
    # Balanced-but-zero still rejected (M8)
    with pytest.raises(ValueError):
        k._create_journal(db, firm_id=FIRM, client_id="CLI", entry_date="2025-06-01",
                          reference_no="ZERO", narration="n", entry_type="Journal",
                          lines=[{"account_id": coa_id(db, FIRM, "ar"), "debit_paise": 0, "credit_paise": 0},
                                 {"account_id": coa_id(db, FIRM, "revenue"), "debit_paise": 0, "credit_paise": 0}])


# ── Authoritative gate (G2): non-INR refused unless an active policy is given ──
def test_foreign_refused_without_policy(monkeypatch):
    db = _setup(monkeypatch)
    with pytest.raises(ValueError, match="active currency policy"):
        pjs.phase2_journal_service._create_journal(
            db, firm_id=FIRM, client_id="CLI", entry_date="2025-06-01",
            reference_no="USD-1", narration="n", entry_type="Journal", lines=_inr_lines(db),
            txn_currency="USD", exchange_rate=Decimal("83.5"))


def test_foreign_refused_with_inactive_policy(monkeypatch):
    db = _setup(monkeypatch)
    with pytest.raises(ValueError):
        pjs.phase2_journal_service._create_journal(
            db, firm_id=FIRM, client_id="CLI", entry_date="2025-06-01",
            reference_no="USD-2", narration="n", entry_type="Journal", lines=_inr_lines(db),
            txn_currency="USD", exchange_rate=Decimal("83.5"),
            currency_policy=CurrencyPolicy(active=False, functional_currency="INR"))


def test_invalid_rate_type_refused_for_foreign(monkeypatch):
    db = _setup(monkeypatch)
    with pytest.raises(ValueError, match="rate_type"):
        pjs.phase2_journal_service._create_journal(
            db, firm_id=FIRM, client_id="CLI", entry_date="2025-06-01",
            reference_no="USD-3", narration="n", entry_type="Journal", lines=_inr_lines(db),
            txn_currency="USD", exchange_rate=Decimal("83.5"), rate_type="spot",
            currency_policy=CurrencyPolicy(active=True, functional_currency="INR"))


def test_kernel_capable_of_freezing_foreign_metadata(monkeypatch):
    # Capability only (NOT a foreign-document feature): with an active policy the
    # kernel accepts and freezes foreign metadata while base still balances.
    db = _setup(monkeypatch)
    active = CurrencyPolicy(active=True, functional_currency="INR")
    lines = [
        {"account_id": coa_id(db, FIRM, "ar"), "debit_paise": 83500, "credit_paise": 0,
         "txn_currency": "USD", "txn_debit": 1000, "txn_credit": 0, "exchange_rate": Decimal("83.5")},
        {"account_id": coa_id(db, FIRM, "revenue"), "debit_paise": 0, "credit_paise": 83500,
         "txn_currency": "USD", "txn_debit": 0, "txn_credit": 1000, "exchange_rate": Decimal("83.5")},
    ]
    eid = pjs.phase2_journal_service._create_journal(
        db, firm_id=FIRM, client_id="CLI", entry_date="2025-06-01",
        reference_no="USD-4", narration="n", entry_type="Journal", lines=lines,
        txn_currency="USD", exchange_rate=Decimal("83.5"), rate_source="manual",
        rate_selected_by="user-1", rate_overridden=True, currency_policy=active)
    rows = _lines_of(db, eid)
    for ln in rows:
        assert ln["txn_currency"] == "USD" and Decimal(ln["exchange_rate"]) == Decimal("83.5")
        assert ln["rate_source"] == "manual"
    # base balances (authoritative); foreign amounts preserved in parallel
    assert sum(int(r["debit_paise"]) for r in rows) == sum(int(r["credit_paise"]) for r in rows) == 83500
    assert sum(int(r["txn_debit"]) for r in rows) == sum(int(r["txn_credit"]) for r in rows) == 1000
    entry = _entry(db, eid)
    assert entry["rate_overridden"] is True and entry["rate_selected_by"] == "user-1"
    assert entry.get("rate_selected_at") is not None


# ── ExchangeRateService seam is available to the posting engine (Task 3) ──────
def test_exchange_rate_service_seam_available(monkeypatch):
    db = _setup(monkeypatch)
    svc = pjs.phase2_journal_service.exchange_rate_service(db)
    q = svc.get_quote("INR", "INR", date(2026, 7, 1))
    assert q.rate == Decimal(1) and q.source == "identity"
