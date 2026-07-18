"""
Cash-basis vs accrual reporting — allocation-driven engine tests.

Cash basis is derived from document allocation links (receipt_allocations,
purchase_payments.purchase_bill_id, credit_notes) — NEVER by amount matching.
Every transformed entry must balance to the paise.

IT Act §145 / §44AA (method of accounting); Companies Act §128 (accrual for
companies). Cash basis is management reporting only and never affects GST
returns (CGST Act). All amounts integer paise.

Mandated coverage: multi-invoice allocation, duplicate amounts, partial
allocation, credit notes, receipt reversal, payment reversal, GST invoices,
rounding edge cases. Plus tenant isolation, accrual regression, invariants.
"""
import random

import pytest

from domain.reporting import (
    Account, Bill, CreditNote, Invoice, JournalEntry, JournalLine, Payment,
    Receipt, ReceiptAllocation, InMemoryLedgerSource, ReportingService, apportion,
)

FIRM = "firm-1"
CLIENT = "client-1"
FY_START, FY_END = "2026-04-01", "2027-03-31"

# ── Chart of accounts (production-style types; system keys for robustness) ──
ACCOUNTS = [
    Account("ar", "1100", "Trade Receivables", "Asset", system_key="ar"),
    Account("ap", "2100", "Trade Payables", "Liability", system_key="ap"),
    Account("bank", "1000", "Bank — HDFC", "Asset", "Bank", system_key="bank"),
    Account("tdsrecv", "1300", "TDS Receivable", "Asset"),
    Account("rev1", "4000", "Professional Fees", "Revenue"),
    Account("rev2", "4001", "Consulting Fees", "Revenue"),
    Account("gstout", "2200", "GST Output Tax Payable", "Liability", system_key="gst_output"),
    Account("gstin", "1400", "GST Input Tax Credit", "Asset", system_key="gst_input"),
    Account("exp1", "5000", "Office Rent", "Expense"),
    Account("cap", "3000", "Capital Account", "Equity"),
    Account("advc", "2300", "Advance from Customers", "Liability", system_key="advance_customer"),
    Account("advv", "1500", "Advance to Vendors", "Asset", system_key="advance_vendor"),
]


# ── builders ────────────────────────────────────────────────────────────────

def _je(jid, lines, date="2026-04-10", reversal_of=None):
    return JournalEntry(
        id=jid, entry_date=date, client_id=CLIENT, firm_id=FIRM,
        entry_type="x", lines=tuple(JournalLine(*l) for l in lines), reversal_of=reversal_of,
    )


def invoice(inv_id, je_id, rev_legs, gst=0, date="2026-04-10"):
    """rev_legs: list[(acct, amount)]. Builds Dr A/R total; Cr revenue (+ GST)."""
    total = sum(a for _, a in rev_legs) + gst
    lines = [("ar", total, 0)] + [(acc, 0, amt) for acc, amt in rev_legs]
    if gst:
        lines.append(("gstout", 0, gst))
    return Invoice(inv_id, total, je_id), _je(je_id, lines, date)


def receipt(rid, je_id, amount, allocs, tds=0, date="2026-04-20"):
    """allocs: list[(invoice_id, allocated_paise)] in settlement (amount+tds) terms."""
    settlement = amount + tds
    lines = [("bank", amount, 0)]
    if tds:
        lines.append(("tdsrecv", tds, 0))
    lines.append(("ar", 0, settlement))
    r = Receipt(rid, je_id, amount, tds)
    allocations = [ReceiptAllocation(rid, inv, amt) for inv, amt in allocs]
    return r, _je(je_id, lines, date), allocations


def credit_note(cid, je_id, inv_id, rev_legs, gst=0, date="2026-04-15"):
    total = sum(a for _, a in rev_legs) + gst
    lines = [(acc, amt, 0) for acc, amt in rev_legs]
    if gst:
        lines.append(("gstout", gst, 0))
    lines.append(("ar", 0, total))
    return CreditNote(cid, inv_id, je_id), _je(je_id, lines, date)


def bill(bid, je_id, exp_legs, gst_input=0, tds=0, date="2026-04-11"):
    total = sum(a for _, a in exp_legs) + gst_input
    net_payable = total - tds
    lines = [(acc, amt, 0) for acc, amt in exp_legs]
    if gst_input:
        lines.append(("gstin", gst_input, 0))
    lines.append(("ap", 0, net_payable))
    if tds:
        lines.append(("tdspay", 0, tds))
    return Bill(bid, total, je_id), _je(je_id, lines, date)


def payment(pid, je_id, bill_id, amount, date="2026-04-25"):
    lines = [("ap", amount, 0), ("bank", 0, amount)]
    return Payment(pid, bill_id, je_id, amount), _je(je_id, lines, date)


def build(entries=(), invoices=(), receipts=(), allocations=(),
          credit_notes=(), bills=(), payments=()):
    return ReportingService(InMemoryLedgerSource(
        accounts=ACCOUNTS, entries=list(entries), invoices=list(invoices),
        receipts=list(receipts), allocations=list(allocations),
        credit_notes=list(credit_notes), bills=list(bills), payments=list(payments),
    ))


def rev_total(pl):
    return pl["revenue"]["total_paise"]


def rev_for(pl, name):
    return next((l["amount_paise"] for l in pl["revenue"]["lines"] if l["account_name"] == name), 0)


def exp_total(pl):
    return pl["operating_expenses"]["total_paise"]


def cash_pl(svc):
    return svc.profit_loss(FIRM, CLIENT, FY_START, FY_END, basis="cash")


def accrual_pl(svc):
    return svc.profit_loss(FIRM, CLIENT, FY_START, FY_END, basis="accrual")


def assert_tb_balances(svc, basis):
    tb = svc.trial_balance(FIRM, CLIENT, FY_END, basis=basis)
    assert tb["difference_paise"] == 0, f"{basis} TB drift: {tb['difference_paise']}"
    assert tb["is_balanced"]
    return tb


def assert_bs_balances(svc, basis):
    bs = svc.balance_sheet(FIRM, CLIENT, FY_END, basis=basis)
    assert bs["is_balanced"], (
        f"{basis} BS: assets={bs['total_assets_paise']} "
        f"L+E={bs['total_liabilities_equity_paise']}"
    )
    return bs


# ── 1. Multi-invoice allocation ───────────────────────────────────────────────

def test_multi_invoice_single_receipt():
    inv_a, je_a = invoice("A", "ja", [("rev1", 1000)])
    inv_b, je_b = invoice("B", "jb", [("rev1", 2000)])
    inv_c, je_c = invoice("C", "jc", [("rev2", 3000)])
    r, jr, allocs = receipt("R", "jr", 6000, [("A", 1000), ("B", 2000), ("C", 3000)])
    svc = build(entries=[je_a, je_b, je_c, jr], invoices=[inv_a, inv_b, inv_c],
                receipts=[r], allocations=allocs)
    pl = cash_pl(svc)
    assert rev_for(pl, "Professional Fees") == 3000
    assert rev_for(pl, "Consulting Fees") == 3000
    assert rev_total(pl) == 6000
    assert_tb_balances(svc, "cash")


# ── 2. Duplicate invoice amounts (proves linkage, not amount matching) ─────────

def test_duplicate_amounts_only_paid_invoice_recognised():
    inv_d, je_d = invoice("D", "jd", [("rev1", 5000)])   # same amount
    inv_e, je_e = invoice("E", "je", [("rev2", 5000)])   # same amount, diff account
    r, jr, allocs = receipt("R", "jr", 5000, [("D", 5000)])  # pays only D
    svc = build(entries=[je_d, je_e, jr], invoices=[inv_d, inv_e],
                receipts=[r], allocations=allocs)
    pl = cash_pl(svc)
    assert rev_for(pl, "Professional Fees") == 5000   # D's account
    assert rev_for(pl, "Consulting Fees") == 0        # E unpaid — not guessed by amount
    assert rev_total(pl) == 5000
    assert accrual_pl(svc)["revenue"]["total_paise"] == 10000
    assert_tb_balances(svc, "cash")


# ── 3. Partial allocation ──────────────────────────────────────────────────────

def test_partial_receipt_recognises_collected_portion():
    inv_f, je_f = invoice("F", "jf", [("rev1", 10000)])
    r, jr, allocs = receipt("R", "jr", 4000, [("F", 4000)])
    svc = build(entries=[je_f, jr], invoices=[inv_f], receipts=[r], allocations=allocs)
    assert rev_total(cash_pl(svc)) == 4000
    assert rev_total(accrual_pl(svc)) == 10000
    bs = assert_bs_balances(svc, "cash")
    # A/R is transformed away — no receivable on the cash balance sheet.
    assert all("Receivable" not in l["account_name"] for s in bs["assets"] for l in s["lines"])


# ── 4. Credit notes ─────────────────────────────────────────────────────────────

def test_credit_note_reduces_recognised_revenue():
    inv_g, je_g = invoice("G", "jg", [("rev1", 1000)], gst=180)        # total 1180
    cn_g, je_cn = credit_note("CN", "jcn", "G", [("rev1", 400)], gst=72)  # total 472
    r, jr, allocs = receipt("R", "jr", 708, [("G", 708)])             # 1180 - 472
    svc = build(entries=[je_g, je_cn, jr], invoices=[inv_g],
                credit_notes=[cn_g], receipts=[r], allocations=allocs)
    pl = cash_pl(svc)
    assert rev_for(pl, "Professional Fees") == 600   # 1000 - 400, never increased
    assert rev_total(pl) == 600
    assert_tb_balances(svc, "cash")


def test_credit_note_alone_recognises_no_revenue():
    inv_g, je_g = invoice("G", "jg", [("rev1", 1000)])
    cn_g, je_cn = credit_note("CN", "jcn", "G", [("rev1", 400)])
    svc = build(entries=[je_g, je_cn], invoices=[inv_g], credit_notes=[cn_g])
    assert rev_total(cash_pl(svc)) == 0  # nothing collected → no cash revenue
    assert_tb_balances(svc, "cash")


# ── 5. Receipt reversal (bounced cheque) ────────────────────────────────────────

def test_receipt_reversal_unwinds_revenue():
    inv_h, je_h = invoice("H", "jh", [("rev1", 5000)])
    r, jr, allocs = receipt("R", "jr", 5000, [("H", 5000)])
    rev = _je("jrr", [("ar", 5000, 0), ("bank", 0, 5000)], date="2026-04-22", reversal_of="jr")
    svc = build(entries=[je_h, jr, rev], invoices=[inv_h], receipts=[r], allocations=allocs)
    assert rev_total(cash_pl(svc)) == 0   # recognised then reversed
    assert_tb_balances(svc, "cash")


# ── 6. Payment reversal (vendor refund) ─────────────────────────────────────────

def test_payment_reversal_unwinds_expense():
    b, jb = bill("B", "jb", [("exp1", 5000)])
    p, jp = payment("P", "jp", "B", 5000)
    rev = _je("jpr", [("bank", 5000, 0), ("ap", 0, 5000)], date="2026-04-27", reversal_of="jp")
    svc = build(entries=[jb, jp, rev], bills=[b], payments=[p])
    assert exp_total(cash_pl(svc)) == 0
    assert_tb_balances(svc, "cash")


def test_paid_bill_recognises_expense():
    b, jb = bill("B", "jb", [("exp1", 5000)])
    p, jp = payment("P", "jp", "B", 5000)
    svc = build(entries=[jb, jp], bills=[b], payments=[p])
    assert exp_total(cash_pl(svc)) == 5000
    assert exp_total(accrual_pl(svc)) == 5000
    assert_tb_balances(svc, "cash")


def test_unpaid_bill_zero_cash_expense():
    b, jb = bill("B", "jb", [("exp1", 5000)])
    svc = build(entries=[jb], bills=[b])
    assert exp_total(cash_pl(svc)) == 0
    assert exp_total(accrual_pl(svc)) == 5000


# ── 7. GST invoices (revenue excludes GST; cash GST ≠ statutory) ────────────────

def test_gst_invoice_full_receipt_excludes_gst_from_revenue():
    inv_j, je_j = invoice("J", "jj", [("rev1", 10000)], gst=1800)  # total 11800
    r, jr, allocs = receipt("R", "jr", 11800, [("J", 11800)])
    svc = build(entries=[je_j, jr], invoices=[inv_j], receipts=[r], allocations=allocs)
    pl = cash_pl(svc)
    assert rev_total(pl) == 10000          # revenue is net of GST
    tb = assert_tb_balances(svc, "cash")
    gst = next(l for l in tb["lines"] if l["account_id"] == "gstout")
    assert gst["total_credit_paise"] == 1800


def test_gst_partial_receipt_cash_gst_differs_from_statutory():
    inv_j, je_j = invoice("J", "jj", [("rev1", 10000)], gst=1800)  # statutory GST = 1800
    r, jr, allocs = receipt("R", "jr", 5900, [("J", 5900)])        # half collected
    svc = build(entries=[je_j, jr], invoices=[inv_j], receipts=[r], allocations=allocs)
    pl = cash_pl(svc)
    assert rev_total(pl) == 5000
    tb = assert_tb_balances(svc, "cash")
    gst = next(l for l in tb["lines"] if l["account_id"] == "gstout")
    # Cash-view GST (900) is NOT the statutory invoice-based GST (1800).
    assert gst["total_credit_paise"] == 900


def test_receipt_with_tds_recognises_gross_income():
    # Decision D: TDS withheld is deemed received → gross professional receipts.
    inv_t, je_t = invoice("T", "jt", [("rev1", 10000)])
    r, jr, allocs = receipt("R", "jr", 9000, [("T", 10000)], tds=1000)  # settlement 10000
    svc = build(entries=[je_t, jr], invoices=[inv_t], receipts=[r], allocations=allocs)
    assert rev_total(cash_pl(svc)) == 10000
    assert_tb_balances(svc, "cash")


# ── 8. Rounding edge cases ──────────────────────────────────────────────────────

def test_indivisible_partial_keeps_tb_balanced():
    # Three legs that don't divide evenly; tiny and odd collections.
    inv_k, je_k = invoice("K", "jk", [("rev1", 334), ("rev2", 333)], gst=333)  # total 1000
    r1, jr1, a1 = receipt("R1", "jr1", 1, [("K", 1)])       # 1 paise
    svc = build(entries=[je_k, jr1], invoices=[inv_k], receipts=[r1], allocations=a1)
    pl = cash_pl(svc)
    assert rev_total(pl) + _gst_credit(svc, "cash") == 1    # every paise placed
    assert_tb_balances(svc, "cash")

    r2, jr2, a2 = receipt("R2", "jr2", 500, [("K", 500)])
    svc2 = build(entries=[je_k, jr2], invoices=[inv_k], receipts=[r2], allocations=a2)
    assert_tb_balances(svc2, "cash")


def _gst_credit(svc, basis):
    tb = svc.trial_balance(FIRM, CLIENT, FY_END, basis=basis)
    g = next((l for l in tb["lines"] if l["account_id"] == "gstout"), None)
    return g["total_credit_paise"] - g["total_debit_paise"] if g else 0


def test_apportion_property_sum_equals_total():
    rng = random.Random(42)
    for _ in range(2000):
        total = rng.randint(0, 1_000_000)
        weights = [rng.randint(0, 1000) for _ in range(rng.randint(1, 6))]
        parts = apportion(total, weights)
        assert all(p >= 0 for p in parts)
        if sum(weights) > 0:
            assert sum(parts) == total
        else:
            assert sum(parts) == 0


# ── Unallocated receipts → advance liability (Decision C) ──────────────────────

def test_unallocated_receipt_parks_as_advance_not_revenue():
    r, jr, _ = receipt("R", "jr", 5000, [])  # money in, not applied to any invoice
    svc = build(entries=[jr], receipts=[r])
    assert rev_total(cash_pl(svc)) == 0          # not income (Decision C)
    bs = assert_bs_balances(svc, "cash")
    liab = [l["account_name"] for s in bs["liabilities"] for l in s["lines"]]
    assert any("Advance from Customers" in n for n in liab)


# ── Tenant isolation ────────────────────────────────────────────────────────────

def test_tenant_isolation_excludes_other_client():
    inv_a, je_a = invoice("A", "ja", [("rev1", 1000)])
    r, jr, allocs = receipt("R", "jr", 1000, [("A", 1000)])
    # Another client's entry must never appear for CLIENT.
    other = JournalEntry(id="jx", entry_date="2026-04-10", client_id="client-2",
                         firm_id=FIRM, entry_type="x",
                         lines=(JournalLine("bank", 99999, 0), JournalLine("rev1", 0, 99999)))
    svc = build(entries=[je_a, jr, other], invoices=[inv_a], receipts=[r], allocations=allocs)
    assert rev_total(cash_pl(svc)) == 1000        # not 1000 + 99999
    assert rev_total(accrual_pl(svc)) == 1000


# ── Accrual regression + invariants ─────────────────────────────────────────────

def test_accrual_revenue_independent_of_collection():
    inv_f, je_f = invoice("F", "jf", [("rev1", 10000)])
    r, jr, allocs = receipt("R", "jr", 3000, [("F", 3000)])
    svc = build(entries=[je_f, jr], invoices=[inv_f], receipts=[r], allocations=allocs)
    assert rev_total(accrual_pl(svc)) == 10000   # full, regardless of payment
    assert rev_total(cash_pl(svc)) == 3000       # only collected
    assert_tb_balances(svc, "accrual")
    assert_tb_balances(svc, "cash")


def test_cash_never_exceeds_accrual():
    inv_f, je_f = invoice("F", "jf", [("rev1", 10000)])
    r, jr, allocs = receipt("R", "jr", 3000, [("F", 3000)])
    b, jb = bill("B", "jb", [("exp1", 8000)])
    p, jp = payment("P", "jp", "B", 2000)
    svc = build(entries=[je_f, jr, jb, jp], invoices=[inv_f], receipts=[r],
                allocations=allocs, bills=[b], payments=[p])
    c, a = cash_pl(svc), accrual_pl(svc)
    assert c["revenue"]["total_paise"] <= a["revenue"]["total_paise"]
    assert c["operating_expenses"]["total_paise"] <= a["operating_expenses"]["total_paise"]


def test_basis_markers():
    svc = build(entries=[_je("j", [("bank", 100, 0), ("cap", 0, 100)])])
    assert svc.trial_balance(FIRM, CLIENT, FY_END, basis="cash").get("basis") == "cash"
    assert svc.profit_loss(FIRM, CLIENT, FY_START, FY_END, basis="cash").get("basis") == "cash"
    assert svc.balance_sheet(FIRM, CLIENT, FY_END, basis="cash").get("basis") == "cash"
    assert "basis" not in svc.trial_balance(FIRM, CLIENT, FY_END, basis="accrual")


# ── Mock/demo source still works end-to-end ──────────────────────────────────────

def _assert_report_consistency(svc, basis):
    """Backend totals must reconcile with their own line sums, for any surface
    (on-screen footer, XLSX export, share) that either reads totals or sums lines."""
    tb = svc.trial_balance(FIRM, CLIENT, FY_END, basis=basis)
    assert tb["total_debit_paise"] == sum(l["total_debit_paise"] for l in tb["lines"])
    assert tb["total_credit_paise"] == sum(l["total_credit_paise"] for l in tb["lines"])
    assert tb["is_balanced"] == (tb["total_debit_paise"] == tb["total_credit_paise"])

    pl = svc.profit_loss(FIRM, CLIENT, FY_START, FY_END, basis=basis)
    assert pl["revenue"]["total_paise"] == sum(l["amount_paise"] for l in pl["revenue"]["lines"])
    assert pl["operating_expenses"]["total_paise"] == sum(l["amount_paise"] for l in pl["operating_expenses"]["lines"])
    assert pl["net_profit_paise"] == pl["revenue"]["total_paise"] - pl["operating_expenses"]["total_paise"]

    bs = svc.balance_sheet(FIRM, CLIENT, FY_END, basis=basis)
    assets = sum(l["balance_paise"] for s in bs["assets"] for l in s["lines"])
    liab = sum(l["balance_paise"] for s in bs["liabilities"] for l in s["lines"])
    eq = sum(l["balance_paise"] for s in bs["equity"] for l in s["lines"])
    assert bs["total_assets_paise"] == assets
    assert bs["total_liabilities_equity_paise"] == liab + eq
    assert bs["is_balanced"] == (assets == liab + eq)


def test_report_totals_reconcile_with_lines_both_bases():
    inv_f, je_f = invoice("F", "jf", [("rev1", 10000)], gst=1800)
    r, jr, allocs = receipt("R", "jr", 5900, [("F", 5900)])
    b, jb = bill("B", "jb", [("exp1", 8000)], gst_input=1440)
    p, jp = payment("P", "jp", "B", 4000)
    svc = build(entries=[je_f, jr, jb, jp], invoices=[inv_f], receipts=[r],
                allocations=allocs, bills=[b], payments=[p])
    for basis in ("accrual", "cash"):
        _assert_report_consistency(svc, basis)


def test_mock_ledger_source_runs_and_balances():
    from domain.reporting import mock_ledger_source
    svc = ReportingService(mock_ledger_source())
    for basis in ("accrual", "cash"):
        tb = svc.trial_balance("firm-001", "c-001", "2025-12-31", basis=basis)
        assert tb["is_balanced"]


# ── Migration tolerance: system_account_key may or may not exist yet ───────────
# SupabaseLedgerSource must work whether or not migration 092 has been applied,
# so deployment order between the migration and the backend no longer matters.

class _FakeExec:
    def __init__(self, data): self.data = data


class _FakeAccountsQuery:
    """Minimal PostgREST chain for a chart_of_accounts select."""
    def __init__(self, rows_with_key, rows_without_key, key_error: Exception | None):
        self._rows_with = rows_with_key
        self._rows_without = rows_without_key
        self._key_error = key_error
        self._cols = ""

    def select(self, cols): self._cols = cols; return self
    def eq(self, *a, **k): return self
    def or_(self, *a, **k): return self
    def is_(self, *a, **k): return self
    def in_(self, *a, **k): return self

    def execute(self):
        if "system_account_key" in self._cols:
            if self._key_error is not None:
                raise self._key_error
            return _FakeExec(self._rows_with)
        return _FakeExec(self._rows_without)


class _FakeDB:
    def __init__(self, rows_with_key, rows_without_key, key_error=None):
        self._args = (rows_with_key, rows_without_key, key_error)

    def table(self, _name):
        return _FakeAccountsQuery(*self._args)


_AR_WITH_KEY = [{"id": "ar", "account_code": "1100", "account_name": "Trade Receivables",
                 "account_type": "Asset", "account_subtype": None, "system_account_key": "ar"}]
_AR_NO_KEY = [{"id": "ar", "account_code": "1100", "account_name": "Trade Receivables",
               "account_type": "Asset", "account_subtype": None}]


def test_accounts_use_system_key_when_present():
    from domain.reporting import SupabaseLedgerSource, AccountResolver
    src = SupabaseLedgerSource(_FakeDB(_AR_WITH_KEY, _AR_NO_KEY, key_error=None))
    accounts = src._accounts(FIRM, CLIENT)
    assert src._has_system_key is True
    assert accounts["ar"].system_key == "ar"
    assert AccountResolver(accounts).is_ar("ar")  # resolves via key


def test_accounts_fall_back_when_column_missing():
    from domain.reporting import SupabaseLedgerSource, AccountResolver
    # Pre-migration: selecting the column raises a PostgREST "does not exist" error.
    err = RuntimeError('column chart_of_accounts.system_account_key does not exist (42703)')
    src = SupabaseLedgerSource(_FakeDB(_AR_WITH_KEY, _AR_NO_KEY, key_error=err))
    accounts = src._accounts(FIRM, CLIENT)
    assert src._has_system_key is False
    assert accounts["ar"].system_key is None
    # Name-based resolution still identifies the A/R control account.
    assert AccountResolver(accounts).is_ar("ar")


def test_accounts_unrelated_error_propagates():
    from domain.reporting import SupabaseLedgerSource
    # A non-column error (e.g. network/auth) must NOT be swallowed as a fallback.
    err = RuntimeError("connection reset by peer")
    src = SupabaseLedgerSource(_FakeDB(_AR_WITH_KEY, _AR_NO_KEY, key_error=err))
    with pytest.raises(RuntimeError, match="connection reset"):
        src._accounts(FIRM, CLIENT)


# ── Migration tolerance: journal_entries.reversal_of (migration 055) ───────────
# Production hotfix — the prod schema is missing reversal_of, which 500'd every
# report. _entries() must tolerate its absence exactly like _accounts() does for
# system_account_key.

class _FakeEntriesQuery:
    """Minimal PostgREST chain for a journal_entries select."""
    def __init__(self, rows_with, rows_without, key_error: Exception | None):
        self._rows_with = rows_with
        self._rows_without = rows_without
        self._key_error = key_error
        self._cols = ""

    def select(self, cols): self._cols = cols; return self
    def eq(self, *a, **k): return self
    def is_(self, *a, **k): return self
    def gt(self, *a, **k): return self
    def order(self, *a, **k): return self
    def range(self, *a, **k): return self
    def limit(self, *a, **k): return self

    def execute(self):
        if "reversal_of" in self._cols:
            if self._key_error is not None:
                raise self._key_error
            return _FakeExec(self._rows_with)
        return _FakeExec(self._rows_without)


class _FakeEntriesDB:
    def __init__(self, rows_with, rows_without, key_error=None):
        self._args = (rows_with, rows_without, key_error)

    def table(self, _name):
        return _FakeEntriesQuery(*self._args)


_JE_WITH = [{"id": "je1", "entry_date": "2026-04-10", "client_id": CLIENT, "firm_id": FIRM,
             "entry_type": "x", "reversal_of": "je0",
             "journal_lines": [{"account_id": "bank", "debit_paise": 100, "credit_paise": 0}]}]
_JE_NO = [{"id": "je1", "entry_date": "2026-04-10", "client_id": CLIENT, "firm_id": FIRM,
           "entry_type": "x",
           "journal_lines": [{"account_id": "bank", "debit_paise": 100, "credit_paise": 0}]}]


def test_entries_use_reversal_of_when_present():
    from domain.reporting import SupabaseLedgerSource
    src = SupabaseLedgerSource(_FakeEntriesDB(_JE_WITH, _JE_NO, key_error=None))
    entries = src._entries(FIRM, CLIENT)
    assert src._has_reversal_of is True
    assert entries["je1"].reversal_of == "je0"


def test_entries_fall_back_when_reversal_of_missing():
    from domain.reporting import SupabaseLedgerSource
    # Exactly the production failure: 42703 column does not exist.
    err = RuntimeError('column journal_entries.reversal_of does not exist (42703)')
    src = SupabaseLedgerSource(_FakeEntriesDB(_JE_WITH, _JE_NO, key_error=err))
    entries = src._entries(FIRM, CLIENT)
    assert src._has_reversal_of is False
    assert entries["je1"].reversal_of is None  # treated as non-reversal


def test_entries_unrelated_error_propagates():
    from domain.reporting import SupabaseLedgerSource
    err = RuntimeError("connection reset by peer")
    src = SupabaseLedgerSource(_FakeEntriesDB(_JE_WITH, _JE_NO, key_error=err))
    with pytest.raises(RuntimeError, match="connection reset"):
        src._entries(FIRM, CLIENT)


# ── End-to-end: reports load on the exact production schema (both cols missing) ─

class _GenericQuery:
    def __init__(self, resolver, table):
        self._resolver = resolver
        self._table = table
        self._cols = ""

    def select(self, cols): self._cols = cols; return self
    def eq(self, *a, **k): return self
    def or_(self, *a, **k): return self
    def is_(self, *a, **k): return self
    def in_(self, *a, **k): return self
    def gt(self, *a, **k): return self
    def order(self, *a, **k): return self
    def range(self, *a, **k): return self
    def limit(self, *a, **k): return self

    def execute(self):
        return _FakeExec(self._resolver(self._table, self._cols))


class _ProdLikeDB:
    """
    Reproduces production caflow-ai: chart_of_accounts has NO system_account_key
    (migration 092 not applied) AND journal_entries has NO reversal_of (055 not
    applied) — both raise 42703 on those column selects.
    """
    def __init__(self, accounts, entries):
        self._accounts = accounts
        self._entries = entries

    def table(self, name):
        return _GenericQuery(self._resolve, name)

    def _resolve(self, table, cols):
        if table == "chart_of_accounts":
            if "system_account_key" in cols:
                raise RuntimeError('column chart_of_accounts.system_account_key does not exist (42703)')
            return self._accounts
        if table == "journal_entries":
            if "reversal_of" in cols:
                raise RuntimeError('column journal_entries.reversal_of does not exist (42703)')
            return self._entries
        return []  # invoices / receipts / allocations / credit_notes / bills / payments


def test_all_reports_load_on_prod_schema_missing_both_columns():
    from domain.reporting import SupabaseLedgerSource
    accounts = [
        {"id": "bank", "account_code": "1000", "account_name": "Bank", "account_type": "Asset", "account_subtype": "Bank"},
        {"id": "cap", "account_code": "3000", "account_name": "Capital", "account_type": "Equity", "account_subtype": None},
        {"id": "rev1", "account_code": "4000", "account_name": "Professional Fees", "account_type": "Revenue", "account_subtype": None},
    ]
    entries = [{
        "id": "je1", "entry_date": "2026-04-10", "client_id": CLIENT, "firm_id": FIRM, "entry_type": "Receipt",
        "journal_lines": [
            {"account_id": "bank", "debit_paise": 1000, "credit_paise": 0},
            {"account_id": "rev1", "debit_paise": 0, "credit_paise": 1000},
        ],
    }]
    src = SupabaseLedgerSource(_ProdLikeDB(accounts, entries))
    svc = ReportingService(src)
    for basis in ("accrual", "cash"):
        tb = svc.trial_balance(FIRM, CLIENT, FY_END, basis=basis)
        assert tb["is_balanced"], f"{basis} TB must load and balance"
        assert tb["total_debit_paise"] == 1000
        pl = svc.profit_loss(FIRM, CLIENT, FY_START, FY_END, basis=basis)
        assert pl["revenue"]["total_paise"] == 1000, f"{basis} P&L must load"
        bs = svc.balance_sheet(FIRM, CLIENT, FY_END, basis=basis)
        assert bs["is_balanced"], f"{basis} BS must load and balance"
    # Both missing columns were detected and tolerated (no 500).
    assert src._has_system_key is False
    assert src._has_reversal_of is False
