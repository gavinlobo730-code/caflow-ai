"""
Cash Flow Statement (AS-3 indirect) — engine tests over the shared reporting
infrastructure (InMemoryLedgerSource + ReportingService).

Guarantees verified:
  * Operating + Investing + Financing == net cash change   (double-entry)
  * Closing Cash − Opening Cash == net cash change           (balance tie-out)
  * Classification by account_type/subtype/system_key (never name)
  * Accrual vs cash basis behave consistently (same net cash; different working-
    capital composition)
  * Part-paid invoice reflects only ACTUAL cash movement
  * Integer paise throughout — never float

Companies Act 2013 Schedule III / AS-3. Cash basis is management reporting only
(IT Act §145) and never affects GST/ITR filings. All amounts integer paise.
"""
from domain.reporting import (
    Account, Invoice, JournalEntry, JournalLine, Receipt, ReceiptAllocation,
    InMemoryLedgerSource, ReportingService,
)

FIRM, CLIENT = "firm-cf", "client-cf"
START, END = "2026-04-01", "2027-03-31"

# Chart of accounts: production-style types/subtypes + system keys. Includes a
# Fixed Asset (investing), a Loan and Capital (financing) so every activity is
# exercised. Cash/bank carry system_key='bank'.
ACCOUNTS = [
    Account("bank",   "1000", "Bank — HDFC",        "Asset",     "Bank",              system_key="bank"),
    Account("ar",     "1100", "Trade Receivables",  "Asset",     "Receivable",        system_key="ar"),
    Account("gstout", "2200", "GST Output Payable", "Liability", "Tax",               system_key="gst_output"),
    Account("ap",     "2100", "Trade Payables",     "Liability", "Payable",           system_key="ap"),
    Account("rev",    "4000", "Professional Fees",  "Revenue",   "Professional Fees"),
    Account("exp",    "5000", "Office Rent",        "Expense",   "Operating Expense"),
    Account("fa",     "1500", "Office Equipment",   "Asset",     "Fixed Asset"),
    Account("loan",   "2500", "Term Loan",          "Liability", "Loan"),
    Account("cap",    "3000", "Capital Account",    "Equity",    "Capital"),
]


def je(jid, lines, date="2026-04-10", reversal_of=None):
    return JournalEntry(
        id=jid, entry_date=date, client_id=CLIENT, firm_id=FIRM,
        entry_type="x", lines=tuple(JournalLine(*l) for l in lines), reversal_of=reversal_of,
    )


def svc_for(entries=(), invoices=(), receipts=(), allocations=()):
    return ReportingService(InMemoryLedgerSource(
        accounts=ACCOUNTS, entries=list(entries), invoices=list(invoices),
        receipts=list(receipts), allocations=list(allocations),
    ))


def cf(svc, basis="accrual", start=START, end=END):
    return svc.cash_flow_statement(FIRM, CLIENT, start, end, basis=basis)


def line_for(section, aid):
    return next((l for l in section["lines"] if l["account_id"] == aid), None)


def all_ints(stmt) -> bool:
    keys = ("net_change_paise", "opening_cash_paise", "closing_cash_paise")
    if not all(isinstance(stmt[k], int) for k in keys):
        return False
    for sec in ("operating", "investing", "financing"):
        if not isinstance(stmt[sec]["total_paise"], int):
            return False
        if not all(isinstance(l["amount_paise"], int) for l in stmt[sec]["lines"]):
            return False
    return True


# ── Classification ────────────────────────────────────────────────────────────

class TestClassification:
    def _statement(self):
        # Cash sale, fixed-asset purchase, loan drawdown, capital intro, rent paid.
        svc = svc_for(entries=[
            je("e1", [("bank", 1000, 0), ("rev", 0, 1000)], "2026-04-10"),   # operating in
            je("e2", [("fa", 500, 0), ("bank", 0, 500)], "2026-05-01"),       # investing out
            je("e3", [("bank", 2000, 0), ("loan", 0, 2000)], "2026-05-10"),   # financing in
            je("e4", [("bank", 3000, 0), ("cap", 0, 3000)], "2026-06-01"),    # financing in
            je("e5", [("exp", 200, 0), ("bank", 0, 200)], "2026-06-15"),      # operating out
        ])
        return cf(svc)

    def test_operating_holds_revenue_and_expense(self):
        s = self._statement()
        assert line_for(s["operating"], "rev")["amount_paise"] == 1000
        assert line_for(s["operating"], "exp")["amount_paise"] == -200
        assert s["operating"]["total_paise"] == 800
        # Fixed asset / loan / capital must NOT appear in operating.
        assert line_for(s["operating"], "fa") is None
        assert line_for(s["operating"], "loan") is None
        assert line_for(s["operating"], "cap") is None

    def test_investing_holds_fixed_assets(self):
        s = self._statement()
        assert line_for(s["investing"], "fa")["amount_paise"] == -500
        assert s["investing"]["total_paise"] == -500

    def test_financing_holds_loans_and_equity(self):
        s = self._statement()
        assert line_for(s["financing"], "loan")["amount_paise"] == 2000
        assert line_for(s["financing"], "cap")["amount_paise"] == 3000
        assert s["financing"]["total_paise"] == 5000

    def test_cash_account_excluded_from_activities(self):
        s = self._statement()
        for sec in ("operating", "investing", "financing"):
            assert line_for(s[sec], "bank") is None


# ── Reconciliation: O + I + F == net change ──────────────────────────────────

class TestReconciliation:
    def test_activities_sum_to_net_change(self):
        svc = svc_for(entries=[
            je("e1", [("bank", 1000, 0), ("rev", 0, 1000)], "2026-04-10"),
            je("e2", [("fa", 500, 0), ("bank", 0, 500)], "2026-05-01"),
            je("e3", [("bank", 2000, 0), ("loan", 0, 2000)], "2026-05-10"),
            je("e4", [("bank", 3000, 0), ("cap", 0, 3000)], "2026-06-01"),
            je("e5", [("exp", 200, 0), ("bank", 0, 200)], "2026-06-15"),
        ])
        s = cf(svc)
        total = s["operating"]["total_paise"] + s["investing"]["total_paise"] + s["financing"]["total_paise"]
        assert total == s["net_change_paise"] == 5300
        assert s["reconciles"] is True

    def test_empty_period_reconciles_to_zero(self):
        s = cf(svc_for(entries=[]))
        assert s["net_change_paise"] == 0
        assert s["operating"]["total_paise"] == 0
        assert s["reconciles"] is True


# ── Balance-sheet tie-out: closing − opening == net change ───────────────────

class TestBalanceSheetTieOut:
    def test_opening_and_closing_cash(self):
        svc = svc_for(entries=[
            # Capital introduced BEFORE the reporting window → opening cash.
            je("ob", [("bank", 10000, 0), ("cap", 0, 10000)], "2026-03-20"),
            # A cash sale inside the window.
            je("e1", [("bank", 1000, 0), ("rev", 0, 1000)], "2026-04-10"),
        ])
        s = cf(svc)
        assert s["opening_cash_paise"] == 10000          # prior capital, excluded from period
        assert s["net_change_paise"] == 1000             # only the in-window sale moved cash
        assert s["closing_cash_paise"] == 11000
        assert s["closing_cash_paise"] - s["opening_cash_paise"] == s["net_change_paise"]
        # The pre-window capital must NOT show in this period's financing section.
        assert line_for(s["financing"], "cap") is None
        assert s["reconciles"] is True


# ── Basis: accrual vs cash behave consistently ───────────────────────────────

class TestBasis:
    def _credit_sale_partial_receipt(self):
        # Invoice ₹11.80 (rev 1000 + GST 180), then collect ₹5.90 (half).
        inv = Invoice("inv1", 1180, "jinv")
        jinv = je("jinv", [("ar", 1180, 0), ("rev", 0, 1000), ("gstout", 0, 180)], "2026-04-10")
        rcpt = Receipt("r1", "jrec", 590, 0)
        jrec = je("jrec", [("bank", 590, 0), ("ar", 0, 590)], "2026-04-20")
        alloc = ReceiptAllocation("r1", "inv1", 590)
        return svc_for(entries=[jinv, jrec], invoices=[inv], receipts=[rcpt], allocations=[alloc])

    def test_net_cash_same_on_both_bases(self):
        svc = self._credit_sale_partial_receipt()
        accrual = cf(svc, "accrual")
        cash = cf(svc, "cash")
        # Actual cash moved is identical regardless of basis.
        assert accrual["net_change_paise"] == cash["net_change_paise"] == 590
        assert accrual["reconciles"] and cash["reconciles"]

    def test_accrual_shows_working_capital_cash_does_not(self):
        svc = self._credit_sale_partial_receipt()
        accrual = cf(svc, "accrual")
        cash = cf(svc, "cash")
        # Accrual operating carries the A/R working-capital change…
        assert line_for(accrual["operating"], "ar") is not None
        assert line_for(accrual["operating"], "rev")["amount_paise"] == 1000
        # …cash operating recognises revenue only on collection, with no A/R line.
        assert line_for(cash["operating"], "ar") is None
        assert line_for(cash["operating"], "rev")["amount_paise"] == 500   # half of 1000
        # Both operating totals equal the cash collected.
        assert accrual["operating"]["total_paise"] == cash["operating"]["total_paise"] == 590

    def test_cash_basis_marks_basis(self):
        s = cf(self._credit_sale_partial_receipt(), "cash")
        assert s.get("basis") == "cash"


# ── Part-paid invoice reflects only actual cash ──────────────────────────────

class TestPartPaidInvoice:
    def test_only_received_cash_appears(self):
        inv = Invoice("inv1", 1180, "jinv")
        jinv = je("jinv", [("ar", 1180, 0), ("rev", 0, 1000), ("gstout", 0, 180)], "2026-04-10")
        rcpt = Receipt("r1", "jrec", 590, 0)
        jrec = je("jrec", [("bank", 590, 0), ("ar", 0, 590)], "2026-04-20")
        alloc = ReceiptAllocation("r1", "inv1", 590)
        svc = svc_for(entries=[jinv, jrec], invoices=[inv], receipts=[rcpt], allocations=[alloc])
        s = cf(svc, "accrual")
        # The invoice itself moved no cash; only the ₹5.90 receipt did.
        assert s["net_change_paise"] == 590
        assert s["closing_cash_paise"] == 590
        assert s["reconciles"] is True


# ── Integer paise / odd-amount apportionment ─────────────────────────────────

class TestIntegerPaise:
    def test_uneven_collection_stays_integer_and_reconciles(self):
        # Collect ₹3.33 against an ₹11.80 invoice — forces apportionment on cash basis.
        inv = Invoice("inv1", 1180, "jinv")
        jinv = je("jinv", [("ar", 1180, 0), ("rev", 0, 1000), ("gstout", 0, 180)], "2026-04-10")
        rcpt = Receipt("r1", "jrec", 333, 0)
        jrec = je("jrec", [("bank", 333, 0), ("ar", 0, 333)], "2026-04-20")
        alloc = ReceiptAllocation("r1", "inv1", 333)
        svc = svc_for(entries=[jinv, jrec], invoices=[inv], receipts=[rcpt], allocations=[alloc])
        for basis in ("accrual", "cash"):
            s = cf(svc, basis)
            assert all_ints(s), f"{basis}: non-integer paise found"
            assert s["net_change_paise"] == 333
            assert s["reconciles"] is True
