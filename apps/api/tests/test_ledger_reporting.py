"""
Phase 3.4 — Ledger consolidation tests.

Proves the per-account general ledger is computed by the single reporting engine
(ReportingService → builders.ledger → LedgerSource): opening balance carries
forward from prior periods (the old browser ledger wrongly restarted at zero),
running/closing are correct, ordering is deterministic (same-day + backdated),
reversals net out, posted-only + firm/client scoping hold at the Supabase source,
and the practice client and a normal client produce identical ledgers.
"""
import pytest

from domain.reporting import (
    Account, JournalEntry, JournalLine, InMemoryLedgerSource, ReportingService,
    SupabaseLedgerSource,
)

FIRM, CLIENT = "firm-1", "client-1"
START, END = "2025-04-01", "2026-03-31"

ACCOUNTS = [
    Account("bank", "1000", "Bank — HDFC", "Asset", "Bank", system_key="bank"),
    Account("rev", "4000", "Professional Fees", "Revenue"),
    Account("cap", "3000", "Capital Account", "Equity"),
    Account("exp", "5000", "Office Rent", "Expense"),
]


def je(jid, date, lines, *, created_at=None, ref=None, narr=None, reversal_of=None,
       client_id=CLIENT, firm_id=FIRM):
    return JournalEntry(
        id=jid, entry_date=date, client_id=client_id, firm_id=firm_id, entry_type="x",
        lines=tuple(JournalLine(*l) for l in lines),
        created_at=created_at or f"{date}T00:00:00", reference_no=ref, narration=narr,
        reversal_of=reversal_of,
    )


def ledger(entries, account_id, start=START, end=END, firm=FIRM, client=CLIENT):
    svc = ReportingService(InMemoryLedgerSource(accounts=ACCOUNTS, entries=entries))
    return svc.ledger(firm, client, account_id, start, end)


# ── Opening balance carries forward (the core correctness fix) ────────────────

def test_opening_balance_carries_forward_from_prior_period():
    entries = [
        je("j0", "2025-03-31", [("bank", 100000, 0), ("cap", 0, 100000)]),  # prior FY
        je("j1", "2025-04-10", [("bank", 50000, 0), ("rev", 0, 50000)]),    # in range
    ]
    rep = ledger(entries, "bank")
    assert rep["opening_balance_paise"] == 100000      # NOT zero — carried forward
    assert len(rep["lines"]) == 1                       # prior-FY entry excluded from rows
    assert rep["lines"][0]["running_balance_paise"] == 150000
    assert rep["closing_balance_paise"] == 150000
    assert rep["total_debit_paise"] == 50000 and rep["total_credit_paise"] == 0


def test_running_balance_and_totals():
    entries = [
        je("j1", "2025-04-10", [("bank", 50000, 0), ("rev", 0, 50000)]),
        je("j2", "2025-04-20", [("exp", 20000, 0), ("bank", 0, 20000)]),
    ]
    rep = ledger(entries, "bank")
    assert rep["opening_balance_paise"] == 0
    assert [l["running_balance_paise"] for l in rep["lines"]] == [50000, 30000]
    assert rep["closing_balance_paise"] == 30000
    assert rep["total_debit_paise"] == 50000 and rep["total_credit_paise"] == 20000


# ── Ordering: same-day (created_at tiebreak) + backdated ──────────────────────

def test_same_day_ordering_by_created_at():
    entries = [
        je("late", "2025-04-10", [("bank", 0, 4000), ("rev", 4000, 0)], created_at="2025-04-10T10:00"),
        je("early", "2025-04-10", [("bank", 10000, 0), ("cap", 0, 10000)], created_at="2025-04-10T09:00"),
    ]
    rep = ledger(entries, "bank")
    assert [l["entry_id"] for l in rep["lines"]] == ["early", "late"]
    assert [l["running_balance_paise"] for l in rep["lines"]] == [10000, 6000]


def test_backdated_entry_sorts_by_date():
    entries = [
        je("j2", "2025-05-01", [("bank", 5000, 0), ("rev", 0, 5000)], created_at="2025-05-02T00:00"),
        je("j1", "2025-04-15", [("bank", 8000, 0), ("rev", 0, 8000)], created_at="2025-05-03T00:00"),  # entered later, dated earlier
    ]
    rep = ledger(entries, "bank")
    assert [l["entry_id"] for l in rep["lines"]] == ["j1", "j2"]
    assert [l["running_balance_paise"] for l in rep["lines"]] == [8000, 13000]


# ── Reversals net out (both legs shown) ───────────────────────────────────────

def test_reversal_nets_out():
    entries = [
        je("orig", "2025-04-10", [("bank", 30000, 0), ("rev", 0, 30000)]),
        je("rev1", "2025-04-12", [("rev", 30000, 0), ("bank", 0, 30000)], reversal_of="orig"),
    ]
    rep = ledger(entries, "bank")
    assert len(rep["lines"]) == 2
    assert [l["running_balance_paise"] for l in rep["lines"]] == [30000, 0]
    assert rep["closing_balance_paise"] == 0


# ── Sign / side + empty account + account meta ────────────────────────────────

def test_credit_balance_account_is_credit_side():
    entries = [je("j1", "2025-04-10", [("bank", 50000, 0), ("rev", 0, 50000)])]
    rep = ledger(entries, "rev")
    assert rep["closing_balance_paise"] == -50000
    assert rep["closing_is_debit"] is False
    assert rep["lines"][0]["is_debit"] is False


def test_empty_account_returns_zero_balances():
    rep = ledger([je("j1", "2025-04-10", [("bank", 50000, 0), ("rev", 0, 50000)])], "exp")
    assert rep["opening_balance_paise"] == 0 and rep["closing_balance_paise"] == 0
    assert rep["lines"] == []
    assert rep["account_code"] == "5000" and rep["account_name"] == "Office Rent"


# ── Practice-as-client parity ─────────────────────────────────────────────────

def test_practice_vs_normal_client_ledger_parity():
    def entries_for(cid):
        return [
            je("j0", "2025-03-31", [("bank", 100000, 0), ("cap", 0, 100000)], client_id=cid),
            je("j1", "2025-04-10", [("bank", 50000, 0), ("rev", 0, 50000)], client_id=cid),
            je("j2", "2025-04-20", [("exp", 20000, 0), ("bank", 0, 20000)], client_id=cid),
        ]
    normal = ledger(entries_for("client-normal"), "bank", client="client-normal")
    practice = ledger(entries_for("client-internal"), "bank", client="client-internal")
    assert normal == practice


# ── Supabase source: posted-only + firm/client scoping (filter-honoring fake) ─

class _Resp:
    def __init__(self, data): self.data = data


class _Q:
    def __init__(self, rows): self.rows = rows; self.f = []
    def select(self, *_a, **_k): return self
    def eq(self, k, v): self.f.append((k, v)); return self
    def or_(self, *_a, **_k): return self
    def in_(self, *_a, **_k): self.f.append(("__none__", object())); return self
    def is_(self, k, _v): self.f.append((k, None)); return self   # deleted_at IS NULL
    def gt(self, *_a, **_k): return self
    def order(self, *_a, **_k): return self
    def range(self, *_a, **_k): return self
    def limit(self, *_a, **_k): return self
    def execute(self):
        out = []
        for r in self.rows:
            if all((r.get(k) is None) if v is None else (r.get(k) == v) for k, v in self.f):
                out.append(r)
        return _Resp(out)


class _FakeDB:
    def __init__(self, entries_rows):
        self.tables = {
            "chart_of_accounts": [
                {"id": "bank", "account_code": "1000", "account_name": "Bank", "account_type": "Asset", "account_subtype": "Bank", "system_account_key": "bank"},
            ],
            "journal_entries": entries_rows,
            "client_sales_invoices": [], "receipts": [], "receipt_allocations": [],
            "credit_notes": [], "purchase_bills": [], "purchase_payments": [],
        }
    def table(self, name): return _Q(self.tables.get(name, []))


def _entry_row(jid, date, lines, *, is_posted=True, deleted_at=None, client_id=CLIENT, firm_id=FIRM):
    return {
        "id": jid, "entry_date": date, "client_id": client_id, "firm_id": firm_id,
        "entry_type": "x", "reference_no": jid.upper(), "narration": f"n-{jid}",
        "created_at": f"{date}T00:00", "is_posted": is_posted, "deleted_at": deleted_at,
        "reversal_of": None,
        "journal_lines": [{"account_id": a, "debit_paise": d, "credit_paise": c} for a, d, c in lines],
    }


def test_supabase_source_posted_only_and_scoping():
    rows = [
        _entry_row("posted", "2025-04-10", [("bank", 50000, 0)]),
        _entry_row("draft", "2025-04-11", [("bank", 999999, 0)], is_posted=False),
        _entry_row("deleted", "2025-04-12", [("bank", 888888, 0)], deleted_at="2025-04-13T00:00"),
        _entry_row("other-client", "2025-04-14", [("bank", 777777, 0)], client_id="client-2"),
        _entry_row("other-firm", "2025-04-15", [("bank", 666666, 0)], firm_id="firm-2"),
    ]
    svc = ReportingService(SupabaseLedgerSource(_FakeDB(rows)))
    rep = svc.ledger(FIRM, CLIENT, "bank", START, END)
    ids = [l["entry_id"] for l in rep["lines"]]
    assert ids == ["posted"]                      # draft, deleted, cross-client, cross-firm all excluded
    assert rep["closing_balance_paise"] == 50000
    assert rep["lines"][0]["reference_no"] == "POSTED" and rep["lines"][0]["narration"] == "n-posted"
