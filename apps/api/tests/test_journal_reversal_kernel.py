"""
Phase 0.5 hardening — journal reversal goes through the SINGLE posting kernel.

Before: the reversal endpoint hand-built INSERTs (no kernel, no double-entry
re-validation, no firm scoping). Now it posts the equal-and-opposite entry via
phase2_journal_service._create_journal — same engine as every other workflow —
links reversal_of, keeps the original immutable, and stays firm-scoped.

Verifies: balanced opposite posted via the kernel; reversal_of linked; original
untouched; can't reverse an unposted entry, a reversal, or the same entry twice;
cross-firm entry is not found (tenant isolation).
"""
import pytest
from fastapi import HTTPException

import routers.accounting as acct
from models.accounting import JournalReversalIn
from tests.e2e_harness import FakeDB, wire_e2e, account_balance, trial_balance

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "id": "u-internal", "auth_user_id": "auth-sub",
          "email": "ca@firma.test", "role": "Partner"}


def _setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [acct])          # neutralises audit/timeline/FY-lock; kernel posts for real
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    return db


def _seed_posted(db, ref="JV1", amount=100000, client_id="CLI", firm_id=FIRM):
    e = db.seed("journal_entries", {
        "firm_id": firm_id, "client_id": client_id, "is_posted": True,
        "entry_type": "Journal", "reference_no": ref, "entry_date": "2025-06-01",
    })
    db.seed("journal_lines", {"journal_entry_id": e["id"], "account_id": "A",
                              "debit_paise": amount, "credit_paise": 0})
    db.seed("journal_lines", {"journal_entry_id": e["id"], "account_id": "B",
                              "debit_paise": 0, "credit_paise": amount})
    return e


def test_reversal_posts_balanced_opposite_via_kernel(monkeypatch):
    db = _setup(monkeypatch)
    e = _seed_posted(db)
    res = acct.reverse_journal_entry(e["id"], JournalReversalIn(reversal_date="2025-06-15"), CALLER)
    assert res["success"] is True
    rev_id = res["data"]["id"]

    rev = next(x for x in db.rows("journal_entries") if x["id"] == rev_id)
    assert rev["reversal_of"] == e["id"]              # linked for audit
    assert rev["is_posted"] is True and rev["status"] == "posted"
    assert rev["created_by"] == "u-internal"          # internal users.id, not auth id

    # Equal-and-opposite: each account nets to zero after reversal.
    assert account_balance(db, "A") == 0
    assert account_balance(db, "B") == 0
    tb = trial_balance(db, FIRM, "CLI")
    assert tb["total_debit_paise"] == tb["total_credit_paise"]


def test_original_entry_is_not_modified(monkeypatch):
    db = _setup(monkeypatch)
    e = _seed_posted(db, ref="JV-IMMUT")
    acct.reverse_journal_entry(e["id"], JournalReversalIn(reversal_date="2025-06-15"), CALLER)
    orig = next(x for x in db.rows("journal_entries") if x["id"] == e["id"])
    assert orig.get("reversal_of") in (None,)         # original never marked
    assert orig["is_posted"] is True                  # untouched


def test_cannot_reverse_unposted(monkeypatch):
    db = _setup(monkeypatch)
    e = db.seed("journal_entries", {"firm_id": FIRM, "client_id": "CLI", "is_posted": False,
                                    "entry_type": "Journal", "reference_no": "D1", "entry_date": "2025-06-01"})
    with pytest.raises(HTTPException) as ex:
        acct.reverse_journal_entry(e["id"], JournalReversalIn(reversal_date="2025-06-15"), CALLER)
    assert ex.value.status_code == 422


def test_cannot_reverse_a_reversal(monkeypatch):
    db = _setup(monkeypatch)
    e = db.seed("journal_entries", {"firm_id": FIRM, "client_id": "CLI", "is_posted": True,
                                    "entry_type": "Journal", "reference_no": "R", "entry_date": "2025-06-01",
                                    "reversal_of": "some-original-id"})
    db.seed("journal_lines", {"journal_entry_id": e["id"], "account_id": "A", "debit_paise": 0, "credit_paise": 100000})
    db.seed("journal_lines", {"journal_entry_id": e["id"], "account_id": "B", "debit_paise": 100000, "credit_paise": 0})
    with pytest.raises(HTTPException) as ex:
        acct.reverse_journal_entry(e["id"], JournalReversalIn(reversal_date="2025-06-15"), CALLER)
    assert ex.value.status_code == 409


def test_cannot_reverse_twice(monkeypatch):
    db = _setup(monkeypatch)
    e = _seed_posted(db, ref="JV2")
    acct.reverse_journal_entry(e["id"], JournalReversalIn(reversal_date="2025-06-15"), CALLER)
    with pytest.raises(HTTPException) as ex:
        acct.reverse_journal_entry(e["id"], JournalReversalIn(reversal_date="2025-06-16"), CALLER)
    assert ex.value.status_code == 409


def test_cannot_reverse_other_firms_entry(monkeypatch):
    db = _setup(monkeypatch)
    e = _seed_posted(db, ref="OTHER", firm_id="FIRM-B")   # different firm
    with pytest.raises(HTTPException) as ex:
        acct.reverse_journal_entry(e["id"], JournalReversalIn(reversal_date="2025-06-15"), CALLER)
    assert ex.value.status_code == 404                      # not found within caller's firm
