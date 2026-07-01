"""
Phase 0.5 hardening — Manual Journal posts through the SINGLE posting kernel.

The manual journal was previously mock-only (in-memory, never the DB). It now
posts via manual_journal_service → phase2_journal_service._create_journal — the
same engine as invoices/receipts/bank/opening balances — with draft/posted
status, unlimited balanced lines, narration, attachments, and audit.

Verifies: draft stays off-books; posted hits the GL balanced; unbalanced/too-few
lines rejected; unlimited lines + attachments persisted; a posted manual journal
can be reversed (round-trips to zero) through the same kernel.
"""
import pytest
import pydantic

import routers.accounting as acct
from models.accounting import JournalEntryIn, JournalReversalIn
from tests.e2e_harness import FakeDB, wire_e2e, account_balance, trial_balance

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "id": "u-internal", "auth_user_id": "auth-sub",
          "email": "ca@firma.test", "role": "Partner"}


def _setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [acct])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    return db


def _je(**over):
    base = dict(
        client_id="CLI", entry_date="2025-06-01",
        lines=[{"account_id": "A", "debit_paise": 150000, "credit_paise": 0},
               {"account_id": "B", "debit_paise": 0, "credit_paise": 150000}],
    )
    base.update(over)
    return JournalEntryIn(**base)


def test_manual_journal_draft_is_off_books(monkeypatch):
    db = _setup(monkeypatch)
    res = acct.create_journal_entry(_je(), CALLER)          # default status = draft
    assert res["success"] is True
    entry = next(e for e in db.rows("journal_entries") if e["id"] == res["data"]["id"])
    assert entry["is_posted"] is False and entry["status"] == "draft"
    assert entry["source_type"] == "manual"
    assert entry["created_by"] == "u-internal"              # internal users.id, not auth id
    # Draft never reaches the posted ledger.
    tb = trial_balance(db, FIRM, "CLI")
    assert tb["total_debit_paise"] == 0


def test_manual_journal_posted_hits_gl(monkeypatch):
    db = _setup(monkeypatch)
    res = acct.create_journal_entry(_je(status="posted"), CALLER)
    assert res["success"] is True
    assert account_balance(db, "A") == 150000
    assert account_balance(db, "B") == -150000
    tb = trial_balance(db, FIRM, "CLI")
    assert tb["total_debit_paise"] == tb["total_credit_paise"] == 150000


def test_manual_journal_unbalanced_rejected_by_model(monkeypatch):
    # The model enforces balance before it can even reach the kernel.
    with pytest.raises(pydantic.ValidationError):
        _je(lines=[{"account_id": "A", "debit_paise": 100000, "credit_paise": 0},
                   {"account_id": "B", "debit_paise": 0, "credit_paise": 50000}])


def test_manual_journal_requires_two_lines(monkeypatch):
    with pytest.raises(pydantic.ValidationError):
        _je(lines=[{"account_id": "A", "debit_paise": 100000, "credit_paise": 0}])


def test_manual_journal_unlimited_lines_and_attachments(monkeypatch):
    db = _setup(monkeypatch)
    lines = [{"account_id": f"A{i}", "debit_paise": 10000, "credit_paise": 0} for i in range(5)]
    lines.append({"account_id": "CASH", "debit_paise": 0, "credit_paise": 50000})
    atts = [{"name": "voucher.pdf", "url": "https://files/x/voucher.pdf"}]
    res = acct.create_journal_entry(
        _je(status="posted", entry_type="Contra", lines=lines, attachments=atts), CALLER)
    assert res["success"] is True
    entry = next(e for e in db.rows("journal_entries") if e["id"] == res["data"]["id"])
    assert entry["attachments"] == atts
    assert entry["entry_type"] == "Contra"
    assert sum(1 for l in db.rows("journal_lines") if l["journal_entry_id"] == entry["id"]) == 6
    tb = trial_balance(db, FIRM, "CLI")
    assert tb["total_debit_paise"] == tb["total_credit_paise"] == 50000


def test_manual_journal_invalid_entry_type_rejected(monkeypatch):
    with pytest.raises(pydantic.ValidationError):
        _je(entry_type="Nonsense")


def test_manual_journal_then_reverse_round_trips(monkeypatch):
    db = _setup(monkeypatch)
    res = acct.create_journal_entry(_je(status="posted"), CALLER)
    rev = acct.reverse_journal_entry(res["data"]["id"], JournalReversalIn(reversal_date="2025-06-20"), CALLER)
    assert rev["success"] is True
    # Original + reversal net to zero on every account.
    assert account_balance(db, "A") == 0
    assert account_balance(db, "B") == 0
