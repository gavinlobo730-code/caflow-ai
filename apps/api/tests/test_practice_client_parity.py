"""
Phase 3 Foundation — Practice-as-Client parity.

Proves the firm's own books (the internal "practice" client) flow through the
EXACT same reporting engine as any normal client, with no special path: P&L,
Balance Sheet, Cash Flow and Trial Balance are byte-identical for two clients
with identical ledgers, whether one is the practice client or not. Also guards
that the accounting/banking/reconciliation engines contain zero `is_internal`
branching (the practice is just another client_id).
"""
import inspect

import pytest

from domain.reporting import (
    Account, Invoice, JournalEntry, JournalLine, Receipt, ReceiptAllocation,
    Bill, Payment, InMemoryLedgerSource, ReportingService,
)

FIRM = "firm-1"
NORMAL_CLIENT = "client-normal"
PRACTICE_CLIENT = "client-internal-practice"   # the is_internal=true row
FY_START, FY_END = "2026-04-01", "2027-03-31"

ACCOUNTS = [
    Account("ar", "1100", "Trade Receivables", "Asset", system_key="ar"),
    Account("ap", "2100", "Trade Payables", "Liability", system_key="ap"),
    Account("bank", "1000", "Bank — HDFC", "Asset", "Bank", system_key="bank"),
    Account("rev", "4000", "Professional Fees", "Revenue"),
    Account("gstout", "2200", "GST Output Tax Payable", "Liability", system_key="gst_output"),
    Account("exp", "5000", "Office Rent", "Expense"),
    Account("cap", "3000", "Capital Account", "Equity"),
]


def _je(jid, client_id, lines, date="2026-04-10"):
    return JournalEntry(
        id=jid, entry_date=date, client_id=client_id, firm_id=FIRM,
        entry_type="x", lines=tuple(JournalLine(*l) for l in lines),
    )


def build_for(client_id: str) -> ReportingService:
    """Identical ledger for the given client: capital, an invoice + receipt, and a
    bill + payment — enough to populate P&L, Balance Sheet and Cash Flow."""
    entries = [
        _je("je-cap", client_id, [("bank", 50000000, 0), ("cap", 0, 50000000)], "2026-04-01"),
        _je("je-inv", client_id, [("ar", 1180000, 0), ("rev", 0, 1000000), ("gstout", 0, 180000)], "2026-04-10"),
        _je("je-rcpt", client_id, [("bank", 1180000, 0), ("ar", 0, 1180000)], "2026-04-20"),
        _je("je-bill", client_id, [("exp", 300000, 0), ("ap", 0, 300000)], "2026-04-11"),
        _je("je-pay", client_id, [("ap", 300000, 0), ("bank", 0, 300000)], "2026-04-25"),
    ]
    invoices = [Invoice("inv-1", 1180000, "je-inv")]
    receipts = [Receipt("rcpt-1", "je-rcpt", 1180000, 0)]
    allocations = [ReceiptAllocation("rcpt-1", "inv-1", 1180000)]
    bills = [Bill("bill-1", 300000, "je-bill")]
    payments = [Payment("pay-1", "bill-1", "je-pay", 300000)]
    return ReportingService(InMemoryLedgerSource(
        accounts=ACCOUNTS, entries=entries, invoices=invoices, receipts=receipts,
        allocations=allocations, credit_notes=[], bills=bills, payments=payments,
    ))


def _strip_client(report: dict) -> dict:
    """Drop identifying fields so two clients' reports are comparable for parity."""
    return {k: v for k, v in report.items() if k not in ("client_id", "firm_id", "generated_at")}


@pytest.mark.parametrize("basis", ["accrual", "cash"])
def test_profit_loss_parity(basis):
    pl_normal = build_for(NORMAL_CLIENT).profit_loss(FIRM, NORMAL_CLIENT, FY_START, FY_END, basis=basis)
    pl_practice = build_for(PRACTICE_CLIENT).profit_loss(FIRM, PRACTICE_CLIENT, FY_START, FY_END, basis=basis)
    assert _strip_client(pl_normal) == _strip_client(pl_practice)
    # sanity: the ledger actually produced figures
    assert pl_normal["revenue"]["total_paise"] == 1000000


@pytest.mark.parametrize("basis", ["accrual", "cash"])
def test_balance_sheet_parity(basis):
    bs_normal = build_for(NORMAL_CLIENT).balance_sheet(FIRM, NORMAL_CLIENT, FY_END, basis=basis)
    bs_practice = build_for(PRACTICE_CLIENT).balance_sheet(FIRM, PRACTICE_CLIENT, FY_END, basis=basis)
    assert _strip_client(bs_normal) == _strip_client(bs_practice)


def test_cash_flow_parity():
    cf_normal = build_for(NORMAL_CLIENT).cash_flow_statement(FIRM, NORMAL_CLIENT, FY_START, FY_END)
    cf_practice = build_for(PRACTICE_CLIENT).cash_flow_statement(FIRM, PRACTICE_CLIENT, FY_START, FY_END)
    assert _strip_client(cf_normal) == _strip_client(cf_practice)


@pytest.mark.parametrize("basis", ["accrual", "cash"])
def test_trial_balance_parity_and_balances(basis):
    tb_normal = build_for(NORMAL_CLIENT).trial_balance(FIRM, NORMAL_CLIENT, FY_END, basis=basis)
    tb_practice = build_for(PRACTICE_CLIENT).trial_balance(FIRM, PRACTICE_CLIENT, FY_END, basis=basis)
    assert _strip_client(tb_normal) == _strip_client(tb_practice)
    assert tb_normal["is_balanced"] and tb_normal["difference_paise"] == 0
    assert tb_practice["is_balanced"] and tb_practice["difference_paise"] == 0


def test_no_special_practice_path_in_engines():
    """The practice must use the same code as any client — no is_internal branch in
    the reporting / posting / reconciliation engines."""
    import domain.reporting.service as rsvc
    import domain.reporting.builders as rbuild
    import services.bank_posting_service as bps
    import services.bank_reconciliation_service as brs
    for mod in (rsvc, rbuild, bps, brs):
        assert "is_internal" not in inspect.getsource(mod), f"{mod.__name__} branches on is_internal"
