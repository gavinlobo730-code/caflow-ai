"""
Multi-Currency Phase 5 — reporting, financial statements & production validation.

Everything here is ADDITIVE and dormant unless multi-currency is enabled. The
guarantees under test:

  • The functional currency (INR) stays authoritative — every statement reads the
    base paise; foreign figures are display-only memo derived from posted data.
  • General Ledger gains OPTIONAL transaction-currency visibility (per foreign
    line); an INR-only ledger is byte-for-byte unchanged (no new keys).
  • Trial Balance / P&L / Balance Sheet / Cash Flow reconcile with the GL when
    foreign activity (incl. realized/unrealized FX) is present.

The full INR regression suite (unchanged) proves base behaviour; this file adds
the foreign-currency reporting behaviour on top.
"""
from __future__ import annotations

from domain.reporting import (
    Account, JournalEntry, JournalLine, InMemoryLedgerSource, ReportingService,
)

FIRM, CLIENT = "firm-p5", "client-p5"
FY_START, FY_END = "2025-04-01", "2026-03-31"

# A small INR-functional chart that also carries the two FX P&L accounts (as seeded
# by migration 149) so realized/unrealized differences flow into the statements.
ACCOUNTS = [
    Account("ar", "1100", "Trade Receivables", "Asset", "Trade Receivables", system_key="ar"),
    Account("ap", "2100", "Trade Payables", "Liability", "Trade Payables", system_key="ap"),
    Account("bank", "1000", "Bank — HDFC", "Asset", "Bank", system_key="bank"),
    Account("rev", "4000", "Export Revenue", "Revenue"),
    Account("cogs", "5000", "Imported Services", "Expense"),
    Account("cap", "3000", "Capital", "Equity"),
    Account("fx_r", "9910", "FX Gain/Loss (Realized)", "Expense", "Finance Costs", system_key="fx_realized"),
    Account("fx_u", "9920", "FX Gain/Loss (Unrealized)", "Expense", "Finance Costs", system_key="fx_unrealized"),
]


def je(jid, date, lines, *, created_at=None, ref=None, narr=None, reversal_of=None):
    """Build a posted entry. Each line tuple is
    (account_id, debit_paise, credit_paise[, txn_currency, txn_debit, txn_credit, rate])."""
    return JournalEntry(
        id=jid, entry_date=date, client_id=CLIENT, firm_id=FIRM, entry_type="x",
        lines=tuple(JournalLine(*l) for l in lines),
        created_at=created_at or f"{date}T00:00:00", reference_no=ref, narration=narr,
        reversal_of=reversal_of,
    )


def _svc(entries):
    return ReportingService(InMemoryLedgerSource(accounts=ACCOUNTS, entries=entries))


# ── Task 1: General Ledger — optional transaction-currency visibility ──────────

def test_general_ledger_shows_foreign_visibility_on_foreign_lines():
    # USD 1,000.00 export invoice @ 83.5 → ₹83,500 base.
    entries = [je("INV1", "2025-06-01", [
        ("ar", 8_350_000, 0, "USD", 100000, 0, "83.5"),
        ("rev", 0, 8_350_000, "USD", 0, 100000, "83.5"),
    ], ref="EXP-1")]
    ar = _svc(entries).ledger(FIRM, CLIENT, "ar", FY_START, FY_END)
    assert ar["has_foreign_lines"] is True
    row = ar["lines"][0]
    assert row["debit_paise"] == 8_350_000            # base stays authoritative
    assert row["txn_currency"] == "USD"
    assert row["txn_debit_minor"] == 100000           # foreign memo
    assert row["txn_credit_minor"] == 0
    assert row["exchange_rate"] == "83.5"


def test_inr_ledger_is_byte_for_byte_unchanged():
    # No foreign metadata → NO foreign keys, NO has_foreign_lines flag.
    entries = [je("J1", "2025-06-01", [("bank", 50000, 0), ("rev", 0, 50000)])]
    rep = _svc(entries).ledger(FIRM, CLIENT, "bank", FY_START, FY_END)
    assert "has_foreign_lines" not in rep
    row = rep["lines"][0]
    assert set(row.keys()) == {
        "entry_id", "entry_date", "reference_no", "narration",
        "debit_paise", "credit_paise", "running_balance_paise", "is_debit",
    }


def test_inr_line_on_a_foreign_currency_field_is_not_treated_as_foreign():
    # txn_currency 'INR' (identity) must never be shown as a foreign leg.
    entries = [je("J1", "2025-06-01", [
        ("bank", 50000, 0, "INR", 50000, 0, "1"),
        ("rev", 0, 50000, "INR", 0, 50000, "1"),
    ])]
    rep = _svc(entries).ledger(FIRM, CLIENT, "bank", FY_START, FY_END)
    assert "has_foreign_lines" not in rep
    assert "txn_currency" not in rep["lines"][0]


# ── Task 1: statements reconcile with the GL when FX is present ────────────────

def _foreign_book_with_realized_fx():
    """A full little foreign book: export invoice booked @80, settled @83 (realized
    gain), plus an unrealized period-end revaluation on an open import bill."""
    return [
        # Export: USD 1,000 @80 → ₹80,000 AR / Revenue.
        je("INV1", "2025-06-01", [
            ("ar", 8_000_000, 0, "USD", 100000, 0, "80"),
            ("rev", 0, 8_000_000, "USD", 0, 100000, "80"),
        ]),
        # Receipt @83: Dr Bank 8,300,000 / Cr AR 8,000,000 / Cr Realized FX 300,000 (gain).
        je("RCT1", "2025-07-01", [
            ("bank", 8_300_000, 0, "USD", 100000, 0, "83"),
            ("ar", 0, 8_000_000, "USD", 0, 100000, "80"),
            ("fx_r", 0, 300_000),
        ]),
        # Import bill still open: USD 500 @82 → ₹41,000 COGS / AP.
        je("BILL1", "2025-08-01", [
            ("cogs", 4_100_000, 0, "USD", 50000, 0, "82"),
            ("ap", 0, 4_100_000, "USD", 0, 50000, "82"),
        ]),
        # Unrealized revaluation of the open AP @84 (loss ₹1,000) + its auto-reversal
        # the next day — the overlay nets to zero across the FY (as designed).
        je("REVAL", "2026-03-31", [("fx_u", 100_000, 0), ("ap", 0, 100_000)]),
        je("REVAL-R", "2026-04-01", [("ap", 100_000, 0), ("fx_u", 0, 100_000)]),
    ]


def test_trial_balance_reconciles_with_foreign_activity():
    tb = _svc(_foreign_book_with_realized_fx()).trial_balance(FIRM, CLIENT, FY_END)
    assert tb["is_balanced"] is True
    assert tb["difference_paise"] == 0


def test_profit_loss_absorbs_realized_fx_and_reconciles():
    # Within the FY the unrealized reval reverses on 1-Apr (next FY), so as at FY-end
    # only the realized FX gain is in the P&L window.
    pl = _svc(_foreign_book_with_realized_fx()).profit_loss(FIRM, CLIENT, FY_START, FY_END)
    # Revenue ₹80,000; a realized FX GAIN is a credit to an expense account, so it
    # reduces total expense — the FX account is present in the expense section.
    codes = {row["account_code"] for row in pl["operating_expenses"]["lines"]}
    assert "9910" in codes                       # realized FX flows into the P&L
    assert pl["revenue"]["total_paise"] == 8_000_000


def test_balance_sheet_balances_with_open_foreign_ap():
    # As at 31-Mar the revaluation overlay is live (reverses 1-Apr): BS must still
    # balance (Assets = Liabilities + Equity incl. retained earnings).
    bs = _svc(_foreign_book_with_realized_fx()).balance_sheet(FIRM, CLIENT, FY_END)
    assert bs["is_balanced"] is True


def test_cash_flow_reconciles_with_foreign_settlement():
    cf = _svc(_foreign_book_with_realized_fx()).cash_flow_statement(FIRM, CLIENT, FY_START, FY_END)
    assert cf["reconciles"] is True
    # Only the USD receipt hit bank in base → closing cash = ₹83,000.
    assert cf["closing_cash_paise"] == 8_300_000


# ── Task 2: Customer/Vendor statements — dual-currency outstanding ─────────────

def test_customer_statement_splits_outstanding_by_currency():
    from services.customer_statement_service import build_statement as cust_stmt
    cust = {"id": "c1", "name": "US Buyer", "opening_balance_paise": 0}
    invoices = [{"invoice_no": "E1", "invoice_date": "2025-06-01", "total_paise": 8_350_000,
                 "status": "issued", "txn_currency": "USD", "exchange_rate": "83.5", "txn_total": 100000}]
    # Partial USD 400.00 receipt @83.5 → base ₹33,400.
    receipts = [{"receipt_no": "R1", "receipt_date": "2025-07-01", "amount_paise": 3_340_000,
                 "tds_paise": 0, "txn_currency": "USD", "exchange_rate": "83.5", "txn_amount": 40000}]
    s = cust_stmt(cust, FY_START, FY_END, invoices, receipts, [])
    assert s["base_currency"] == "INR"
    usd = next(r for r in s["outstanding_by_currency"] if r["currency"] == "USD")
    assert usd["outstanding_foreign_minor"] == 60000            # 100000 − 40000
    assert usd["outstanding_base_paise"] == 5_010_000           # 8,350,000 − 3,340,000
    # Σ base over currencies reconciles to the closing balance exactly.
    assert sum(r["outstanding_base_paise"] for r in s["outstanding_by_currency"]) == s["closing_balance_paise"]


def test_inr_customer_statement_has_no_currency_block():
    from services.customer_statement_service import build_statement as cust_stmt
    cust = {"id": "c1", "name": "Acme", "opening_balance_paise": 0}
    s = cust_stmt(cust, FY_START, FY_END,
                  [{"invoice_no": "I1", "invoice_date": "2025-06-01", "total_paise": 118000, "status": "issued"}],
                  [], [])
    assert "base_currency" not in s and "outstanding_by_currency" not in s


def test_vendor_statement_splits_payable_by_currency():
    from services.vendor_statement_service import build_statement as vend_stmt
    vend = {"id": "v1", "name": "US Vendor", "opening_balance_paise": 0}
    bills = [{"bill_no": "B1", "bill_date": "2025-06-01", "net_payable_paise": 4_100_000,
              "status": "received", "txn_currency": "USD", "exchange_rate": "82", "txn_net_payable": 50000}]
    s = vend_stmt(vend, FY_START, FY_END, bills, [], [])
    usd = next(r for r in s["outstanding_by_currency"] if r["currency"] == "USD")
    assert usd["outstanding_foreign_minor"] == 50000
    assert usd["outstanding_base_paise"] == 4_100_000
    assert sum(r["outstanding_base_paise"] for r in s["outstanding_by_currency"]) == s["closing_balance_paise"]


# ── Task 2: AR/AP aging — dual-currency (service over a tiny fake DB) ──────────

class _AgingQ:
    def __init__(self, rows):
        self.rows, self.f, self.nf = rows, [], []
    def select(self, *_a, **_k): return self
    def eq(self, k, v): self.f.append((k, v)); return self
    def neq(self, k, v): self.nf.append((k, v)); return self
    def is_(self, k, _v): self.f.append((k, None)); return self
    def execute(self):
        out = [r for r in self.rows
               if all((r.get(k) is None) if v is None else (r.get(k) == v) for k, v in self.f)
               and all(r.get(k) != v for k, v in self.nf)]
        return type("R", (), {"data": out})()


class _AgingDB:
    def __init__(self, tables): self.tables = tables
    def table(self, n): return _AgingQ(self.tables.get(n, []))


def test_ar_aging_reports_foreign_and_base_outstanding():
    from services.customer_statement_service import customer_statement_service as CS
    db = _AgingDB({
        "customers": [{"id": "cu1", "firm_id": FIRM, "client_id": CLIENT, "name": "US Buyer"}],
        "client_sales_invoices": [
            {"id": "i1", "firm_id": FIRM, "client_id": CLIENT, "customer_id": "cu1", "invoice_no": "E1",
             "invoice_date": "2025-06-01", "due_date": "2025-06-01", "total_paise": 8_350_000,
             "paid_paise": 0, "credited_paise": 0, "status": "issued", "deleted_at": None,
             "txn_currency": "USD", "exchange_rate": "83.5", "txn_total": 100000, "paid_txn": 0},
            {"id": "i2", "firm_id": FIRM, "client_id": CLIENT, "customer_id": "cu1", "invoice_no": "D1",
             "invoice_date": "2025-06-01", "due_date": "2025-06-01", "total_paise": 118000,
             "paid_paise": 0, "credited_paise": 0, "status": "issued", "deleted_at": None},  # INR
        ],
    })
    ag = CS.ar_aging(db, FIRM, CLIENT, as_of="2025-07-01")
    assert ag["total_outstanding_paise"] == 8_468_000                # 8,350,000 + 118,000
    usd = next(r for r in ag["by_currency"] if r["currency"] == "USD")
    assert usd["outstanding_foreign_minor"] == 100000 and usd["outstanding_base_paise"] == 8_350_000
    inr = next(r for r in ag["by_currency"] if r["currency"] == "INR")
    assert inr["outstanding_base_paise"] == 118000
    # per-foreign-invoice detail present; INR invoice carries none.
    row_usd = next(r for r in ag["invoices"] if r["invoice_no"] == "E1")
    assert row_usd["txn_currency"] == "USD" and row_usd["outstanding_foreign_minor"] == 100000
    row_inr = next(r for r in ag["invoices"] if r["invoice_no"] == "D1")
    assert "txn_currency" not in row_inr


def test_inr_only_ar_aging_has_no_currency_block():
    from services.customer_statement_service import customer_statement_service as CS
    db = _AgingDB({
        "customers": [{"id": "cu1", "firm_id": FIRM, "client_id": CLIENT, "name": "Acme"}],
        "client_sales_invoices": [
            {"id": "i1", "firm_id": FIRM, "client_id": CLIENT, "customer_id": "cu1", "invoice_no": "I1",
             "invoice_date": "2025-06-01", "due_date": "2025-06-01", "total_paise": 118000,
             "paid_paise": 0, "credited_paise": 0, "status": "issued", "deleted_at": None},
        ],
    })
    ag = CS.ar_aging(db, FIRM, CLIENT, as_of="2025-07-01")
    assert "by_currency" not in ag and "base_currency" not in ag
    assert ag["invoices"][0].keys() == {
        "invoice_id", "invoice_no", "customer_id", "customer_name",
        "invoice_date", "outstanding_paise", "days_overdue", "aging_bucket"}


def test_ap_aging_reports_foreign_and_base_outstanding():
    from services.vendor_statement_service import vendor_statement_service as VS
    db = _AgingDB({
        "vendors": [{"id": "v1", "firm_id": FIRM, "client_id": CLIENT, "name": "US Vendor"}],
        "purchase_bills": [
            {"id": "b1", "firm_id": FIRM, "client_id": CLIENT, "vendor_id": "v1", "bill_no": "B1",
             "bill_date": "2025-06-01", "due_date": "2025-06-01", "net_payable_paise": 4_100_000,
             "paid_paise": 0, "debited_paise": 0, "status": "received",
             "txn_currency": "USD", "exchange_rate": "82", "txn_net_payable": 50000, "paid_txn": 0},
        ],
    })
    ag = VS.ap_aging(db, FIRM, CLIENT, as_of="2025-07-01")
    usd = next(r for r in ag["by_currency"] if r["currency"] == "USD")
    assert usd["outstanding_foreign_minor"] == 50000 and usd["outstanding_base_paise"] == 4_100_000


# ── Task 3: FX reports (service over a tiny fake DB) ───────────────────────────

from services.fx_reporting_service import fx_reporting_service as FXR


def test_realized_fx_report_aggregates_gain_and_loss():
    db = _AgingDB({"fx_adjustments": [
        {"firm_id": FIRM, "client_id": CLIENT, "kind": "realized", "document_type": "receipt",
         "document_id": "r1", "currency": "USD", "settlement_rate": "83", "base_delta_paise": 300_000,
         "journal_entry_id": "j1", "rate_source": "settlement", "created_at": "2025-07-01T00:00:00"},
        {"firm_id": FIRM, "client_id": CLIENT, "kind": "realized", "document_type": "purchase_payment",
         "document_id": "p1", "currency": "USD", "settlement_rate": "78", "base_delta_paise": -200_000,
         "journal_entry_id": "j2", "rate_source": "settlement", "created_at": "2025-08-01T00:00:00"},
        # A realized row from another firm must never leak in.
        {"firm_id": "other", "client_id": CLIENT, "kind": "realized", "currency": "USD",
         "base_delta_paise": 999_999, "created_at": "2025-08-01T00:00:00"},
    ]})
    rep = FXR.realized_fx(db, FIRM, CLIENT, "2025-04-01", "2026-03-31")
    assert rep["gain_paise"] == 300_000 and rep["loss_paise"] == 200_000 and rep["net_paise"] == 100_000
    usd = rep["by_currency"][0]
    assert usd["currency"] == "USD" and usd["net_paise"] == 100_000
    assert len(rep["lines"]) == 2                       # cross-firm row excluded


def test_unrealized_fx_report_shows_cumulative_delta_across_runs():
    db = _AgingDB({"fx_revaluations": [
        {"firm_id": FIRM, "client_id": CLIENT, "period_end": "2026-03-31", "currency": "USD",
         "item_type": "receivable", "closing_rate": "84", "target_adjustment_paise": 400_000,
         "delta_paise": 400_000, "journal_entry_id": "j1", "reversal_entry_id": "jr1", "run_at": "2026-04-01T00:00"},
        {"firm_id": FIRM, "client_id": CLIENT, "period_end": "2026-03-31", "currency": "USD",
         "item_type": "receivable", "closing_rate": "86", "target_adjustment_paise": 600_000,
         "delta_paise": 200_000, "journal_entry_id": "j2", "reversal_entry_id": "jr2", "run_at": "2026-04-02T00:00"},
    ]})
    rep = FXR.unrealized_fx(db, FIRM, CLIENT, "2026-03-31")
    line = rep["lines"][0]
    assert line["cumulative_delta_paise"] == 600_000 and line["runs"] == 2
    assert line["closing_rate"] == "86" and line["target_adjustment_paise"] == 600_000
    assert rep["net_paise"] == 600_000


def _exposure_db():
    return _AgingDB({
        "client_sales_invoices": [
            {"id": "i1", "firm_id": FIRM, "client_id": CLIENT, "customer_id": "cu1", "invoice_no": "E1",
             "invoice_date": "2025-06-01", "status": "issued", "total_paise": 8_000_000, "paid_paise": 0,
             "credited_paise": 0, "txn_currency": "USD", "exchange_rate": "80", "txn_total": 100000, "paid_txn": 0},
        ],
        "purchase_bills": [
            {"id": "b1", "firm_id": FIRM, "client_id": CLIENT, "vendor_id": "v1", "bill_no": "B1",
             "bill_date": "2025-06-01", "status": "received", "net_payable_paise": 4_100_000, "paid_paise": 0,
             "debited_paise": 0, "txn_currency": "USD", "exchange_rate": "82", "txn_net_payable": 50000, "paid_txn": 0},
        ],
    })


def test_currency_exposure_nets_ar_and_ap():
    rep = FXR.currency_exposure(_exposure_db(), FIRM, CLIENT, as_of="2025-12-31")
    usd = next(r for r in rep["by_currency"] if r["currency"] == "USD")
    assert usd["receivable_foreign_minor"] == 100000 and usd["receivable_base_paise"] == 8_000_000
    assert usd["payable_foreign_minor"] == 50000 and usd["payable_base_paise"] == 4_100_000
    assert usd["net_foreign_minor"] == 50000            # 100000 AR − 50000 AP
    assert usd["net_base_paise"] == 3_900_000           # 8,000,000 − 4,100,000


def test_open_foreign_balances_lists_documents():
    rep = FXR.open_foreign_balances(_exposure_db(), FIRM, CLIENT, as_of="2025-12-31")
    assert len(rep["receivables"]) == 1 and rep["receivables"][0]["document_type"] == "sales_invoice"
    assert rep["receivables"][0]["foreign_outstanding_minor"] == 100000
    assert len(rep["payables"]) == 1 and rep["payables"][0]["foreign_outstanding_minor"] == 50000


def test_exchange_rate_audit_flags_overrides():
    db = _AgingDB({
        "client_sales_invoices": [
            {"id": "i1", "firm_id": FIRM, "client_id": CLIENT, "invoice_no": "E1", "invoice_date": "2025-06-01",
             "txn_currency": "USD", "exchange_rate": "83.5", "rate_source": "manual-override", "rate_type": "booking",
             "rate_date": "2025-06-01", "rate_selected_by": "u1", "rate_overridden": True},
        ],
        "purchase_bills": [],
        "fx_adjustments": [
            {"firm_id": FIRM, "client_id": CLIENT, "kind": "realized", "currency": "USD", "document_type": "receipt",
             "document_id": "r1", "settlement_rate": "84", "base_delta_paise": 50_000, "rate_source": "settlement",
             "created_by": "u1", "created_at": "2025-07-01T00:00:00"},
        ],
    })
    rep = FXR.exchange_rate_audit(db, FIRM, CLIENT, "2025-04-01", "2026-03-31")
    assert rep["overridden_count"] == 1
    assert rep["documents"][0]["rate_overridden"] is True and rep["documents"][0]["exchange_rate"] == "83.5"
    assert rep["adjustments"][0]["settlement_rate"] == "84"


# ── Task 5: Foreign-currency bank accounts + revaluation ──────────────────────

def _bank_reval_setup(monkeypatch):
    """A USD bank account holding $1,000.00 booked at ₹80 (₹80,000 carrying)."""
    from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa
    import routers.customers as cu, routers.sales_invoices as si, routers.receipts as rc
    import routers.purchase_bills as pb, routers.purchase_payments as pp, routers.vendors as ve
    import services.receipt_service as rs
    db = FakeDB()
    wire_e2e(monkeypatch, db, [cu, si, rc, pb, pp, ve, rs])
    monkeypatch.setenv("MULTI_CURRENCY_ENABLED", "true")
    bfirm = "FIRM-MC5B"
    db.seed("firms", {"id": bfirm, "multi_currency_entitled": True})
    db.seed("clients", {"id": "CLI", "firm_id": bfirm, "functional_currency": "INR", "multi_currency_enabled": True})
    db.seed("currencies", {"code": "USD", "symbol": "$", "display_name": "US Dollar", "minor_unit": 2, "is_active": True})
    db.seed("currencies", {"code": "INR", "symbol": "₹", "display_name": "Indian Rupee", "minor_unit": 2, "is_active": True})
    ids = seed_standard_coa(db, bfirm, "CLI")
    bank_coa = ids["bank"]
    db.seed("bank_accounts", {"id": "bank-usd", "firm_id": bfirm, "client_id": "CLI",
                              "currency": "USD", "coa_account_id": bank_coa})
    db.seed("journal_entries", {"id": "je-bank", "firm_id": bfirm, "client_id": "CLI",
                                "entry_date": "2025-06-01", "is_posted": True, "deleted_at": None})
    db.seed("journal_lines", {"journal_entry_id": "je-bank", "account_id": bank_coa,
                              "debit_paise": 8_000_000, "credit_paise": 0, "txn_debit": 100000, "txn_credit": 0,
                              "txn_currency": "USD"})
    db.seed("journal_lines", {"journal_entry_id": "je-bank", "account_id": ids["revenue"],
                              "debit_paise": 0, "credit_paise": 8_000_000, "txn_debit": 0, "txn_credit": 100000,
                              "txn_currency": "USD"})
    return db, bfirm, bank_coa


def test_foreign_bank_balance_revaluation_posts_and_reverses(monkeypatch):
    from domain.currency.fx_revaluation_service import fx_revaluation_service as REVAL
    from tests.e2e_harness import account_balance, coa_id
    db, bfirm, bank_coa = _bank_reval_setup(monkeypatch)
    caller = {"firm_id": bfirm, "id": "u1", "auth_user_id": "u1", "email": "ca@f.test", "role": "Partner"}

    # Closing rate 84 → revalued $1,000 = ₹84,000; carrying ₹80,000 → +₹4,000 gain.
    r = REVAL.revalue(db, bfirm, "CLI", "2026-03-31", {"USD": "84.0"}, caller)
    bank_adj = [a for a in r["adjustments"] if a["item_type"] == "bank"]
    assert len(bank_adj) == 1
    assert bank_adj[0]["delta_paise"] == 400_000 and bank_adj[0]["item_ref"] == bank_coa

    # The revaluation is keyed by the bank's GL account (item_ref) in the run log.
    reval = [x for x in db.rows("fx_revaluations") if x.get("item_type") == "bank"]
    assert len(reval) == 1 and reval[0]["item_ref"] == bank_coa and reval[0]["delta_paise"] == 400_000

    # Overlay auto-reverses on day 1 of the next period → net effect on the bank GL is
    # zero (carrying stays ₹80,000) and Unrealized FX nets to zero across the two dates.
    assert account_balance(db, bank_coa) == 8_000_000
    assert account_balance(db, coa_id(db, bfirm, "fx_unrealized")) == 0
    # GL balances in base throughout.
    td = sum(int(l.get("debit_paise", 0)) for l in db.rows("journal_lines"))
    tc = sum(int(l.get("credit_paise", 0)) for l in db.rows("journal_lines"))
    assert td == tc


def test_foreign_bank_revaluation_is_idempotent(monkeypatch):
    from domain.currency.fx_revaluation_service import fx_revaluation_service as REVAL
    db, bfirm, bank_coa = _bank_reval_setup(monkeypatch)
    caller = {"firm_id": bfirm, "id": "u1", "auth_user_id": "u1", "email": "ca@f.test", "role": "Partner"}
    REVAL.revalue(db, bfirm, "CLI", "2026-03-31", {"USD": "84.0"}, caller)
    r2 = REVAL.revalue(db, bfirm, "CLI", "2026-03-31", {"USD": "84.0"}, caller)  # same rate ⇒ no-op
    bank_adj = [a for a in r2["adjustments"] if a["item_type"] == "bank"]
    assert bank_adj and bank_adj[0]["delta_paise"] == 0


def test_currency_exposure_includes_foreign_bank(monkeypatch):
    from services.fx_reporting_service import fx_reporting_service as FXRS
    db, bfirm, bank_coa = _bank_reval_setup(monkeypatch)
    rep = FXRS.currency_exposure(db, bfirm, "CLI", as_of="2026-03-31")
    usd = next(r for r in rep["by_currency"] if r["currency"] == "USD")
    assert usd["bank_foreign_minor"] == 100000 and usd["bank_base_paise"] == 8_000_000
    assert usd["net_foreign_minor"] == 100000            # bank asset, no AR/AP


def test_foreign_bank_account_guard(monkeypatch):
    """A non-INR bank account is allowed only when multi-currency is active AND the
    currency is in the master; otherwise it is rejected (fail-safe to INR-only)."""
    import routers.banking as bk
    from tests.e2e_harness import FakeDB
    import pytest
    from fastapi import HTTPException
    db = FakeDB()
    db.seed("firms", {"id": "F", "multi_currency_entitled": True})
    db.seed("clients", {"id": "CLI", "firm_id": "F", "functional_currency": "INR", "multi_currency_enabled": True})
    db.seed("currencies", {"code": "USD", "symbol": "$", "display_name": "US Dollar", "minor_unit": 2, "is_active": True})

    # L1 kill switch OFF ⇒ rejected.
    monkeypatch.delenv("MULTI_CURRENCY_ENABLED", raising=False)
    with pytest.raises(HTTPException) as ex:
        bk._guard_foreign_bank_currency(db, "F", "CLI", "USD")
    assert ex.value.status_code == 422 and "multi-currency" in ex.value.detail.lower()

    # Policy ON but unsupported currency ⇒ rejected.
    monkeypatch.setenv("MULTI_CURRENCY_ENABLED", "true")
    with pytest.raises(HTTPException) as ex2:
        bk._guard_foreign_bank_currency(db, "F", "CLI", "ZZZ")
    assert ex2.value.status_code == 422 and "unsupported currency" in ex2.value.detail.lower()

    # Policy ON + supported currency ⇒ allowed (no raise).
    bk._guard_foreign_bank_currency(db, "F", "CLI", "USD")


# ══ Task 6: Production validation — end-to-end through the REAL routers ═════════
# Create documents via the production endpoints against one FakeDB, then run the
# Phase-5 report services over the SAME posted data. Proves the reports reconcile
# with the GL for INR-only, mixed, multi-currency, multi-year and cross-tenant
# scenarios.

from models.parties import CustomerIn
from models.invoices import SalesInvoiceIn, InvoiceLineIn, ReceiptIn, ReceiptAllocationIn


def _e2e(monkeypatch, firm, *, mc=True):
    from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa
    import routers.customers as cu, routers.sales_invoices as si, routers.receipts as rc
    import routers.purchase_bills as pb, routers.purchase_payments as pp, routers.vendors as ve
    import services.receipt_service as rs
    db = FakeDB()
    wire_e2e(monkeypatch, db, [cu, si, rc, pb, pp, ve, rs])
    if mc:
        monkeypatch.setenv("MULTI_CURRENCY_ENABLED", "true")
    else:
        monkeypatch.delenv("MULTI_CURRENCY_ENABLED", raising=False)
    db.seed("firms", {"id": firm, "multi_currency_entitled": mc})
    db.seed("clients", {"id": "CLI", "firm_id": firm, "gstin": "27ABCDE1234F1Z5",
                        "functional_currency": "INR", "multi_currency_enabled": mc})
    for code, sym, name in (("INR", "₹", "Indian Rupee"), ("USD", "$", "US Dollar"), ("EUR", "€", "Euro")):
        db.seed("currencies", {"code": code, "symbol": sym, "display_name": name, "minor_unit": 2, "is_active": True})
    seed_standard_coa(db, firm, "CLI")
    return cu, si, rc, db


def _caller(firm):
    return {"firm_id": firm, "id": "u1", "auth_user_id": "u1", "email": "ca@f.test", "role": "Partner"}


def _invoice(si, caller, cust_id, *, date="2025-06-01", currency=None, rate=None, cents=100000,
             invoice_no="INV-001"):
    kw = {}
    if currency:
        kw = {"currency": currency, "exchange_rate": str(rate)}
    inv = si.create_invoice(SalesInvoiceIn(
        client_id="CLI", customer_id=cust_id, invoice_date=date, invoice_no=invoice_no,
        lines=[InvoiceLineIn(description="x", hsn_sac="9982", quantity=1, rate_paise=cents, gst_rate_percent=0.0)],
        **kw), caller)["data"]
    si.issue_invoice(inv["id"], caller)
    return inv


def test_mixed_inr_and_foreign_client_reconciles(monkeypatch):
    from services.customer_statement_service import customer_statement_service as CS
    from services.fx_reporting_service import fx_reporting_service as FXR
    from tests.e2e_harness import trial_balance
    FIRM = "FIRM-P5V1"
    cu, si, rc, db = _e2e(monkeypatch, FIRM)
    caller = _caller(FIRM)
    inr_cust = cu.create_customer(CustomerIn(client_id="CLI", name="INR Buyer", state_code="27"), caller)["data"]
    usd_cust = cu.create_customer(CustomerIn(client_id="CLI", name="US Buyer", state_code="27"), caller)["data"]
    _invoice(si, caller, inr_cust["id"], cents=100000, invoice_no="INV-INR-1")                       # ₹1,000 INR
    _invoice(si, caller, usd_cust["id"], currency="USD", rate="83", cents=100000, invoice_no="INV-USD-1")   # $1,000 @83 = ₹83,000

    # GL balances entirely in base.
    tb = trial_balance(db, FIRM, "CLI")
    assert tb["total_debit_paise"] == tb["total_credit_paise"]

    # AR aging: base total reconciles; the currency split carries both.
    ag = CS.ar_aging(db, FIRM, "CLI", as_of="2025-07-01")
    assert ag["total_outstanding_paise"] == 100000 + 8_300_000
    cur = {r["currency"]: r for r in ag["by_currency"]}
    assert cur["INR"]["outstanding_base_paise"] == 100000
    assert cur["USD"]["outstanding_foreign_minor"] == 100000 and cur["USD"]["outstanding_base_paise"] == 8_300_000

    # Exposure shows ONLY the foreign currency; open balances lists the USD invoice.
    exp = FXR.currency_exposure(db, FIRM, "CLI", as_of="2025-07-01")
    assert [r["currency"] for r in exp["by_currency"]] == ["USD"]
    ofb = FXR.open_foreign_balances(db, FIRM, "CLI", as_of="2025-07-01")
    assert len(ofb["receivables"]) == 1 and ofb["receivables"][0]["foreign_outstanding_minor"] == 100000


def test_multiple_currencies_realized_fx(monkeypatch):
    from services.fx_reporting_service import fx_reporting_service as FXR
    from tests.e2e_harness import trial_balance
    FIRM = "FIRM-P5V2"
    cu, si, rc, db = _e2e(monkeypatch, FIRM)
    caller = _caller(FIRM)
    usd_c = cu.create_customer(CustomerIn(client_id="CLI", name="US", state_code="27"), caller)["data"]
    eur_c = cu.create_customer(CustomerIn(client_id="CLI", name="EU", state_code="27"), caller)["data"]
    usd_inv = _invoice(si, caller, usd_c["id"], currency="USD", rate="80", cents=100000, invoice_no="INV-USD-1")   # $1,000 @80
    eur_inv = _invoice(si, caller, eur_c["id"], currency="EUR", rate="90", cents=100000, invoice_no="INV-EUR-1")   # €1,000 @90

    # Settle in FOREIGN minor units (foreign receipts settle in the txn currency):
    # USD @83 (gain ₹3,000) and EUR @88 (loss ₹2,000).
    rc.create_receipt(ReceiptIn(client_id="CLI", customer_id=usd_c["id"], receipt_date="2025-08-01",
        amount_paise=100000, currency="USD", exchange_rate="83",
        allocations=[ReceiptAllocationIn(sales_invoice_id=usd_inv["id"], allocated_paise=100000)]), caller)
    rc.create_receipt(ReceiptIn(client_id="CLI", customer_id=eur_c["id"], receipt_date="2025-08-01",
        amount_paise=100000, currency="EUR", exchange_rate="88",
        allocations=[ReceiptAllocationIn(sales_invoice_id=eur_inv["id"], allocated_paise=100000)]), caller)

    tb = trial_balance(db, FIRM, "CLI")
    assert tb["total_debit_paise"] == tb["total_credit_paise"]
    rep = FXR.realized_fx(db, FIRM, "CLI", "2025-04-01", "2026-03-31")
    by = {r["currency"]: r for r in rep["by_currency"]}
    assert by["USD"]["net_paise"] == 300_000        # $1,000 × (83−80)
    assert by["EUR"]["net_paise"] == -200_000       # €1,000 × (88−90)
    assert rep["net_paise"] == 100_000              # +3,000 − 2,000


def test_inr_only_client_has_empty_fx_reports(monkeypatch):
    from services.fx_reporting_service import fx_reporting_service as FXR
    FIRM = "FIRM-P5V3"
    cu, si, rc, db = _e2e(monkeypatch, FIRM, mc=False)
    caller = _caller(FIRM)
    c = cu.create_customer(CustomerIn(client_id="CLI", name="Acme", state_code="27"), caller)["data"]
    _invoice(si, caller, c["id"], cents=118000)     # plain INR invoice
    assert FXR.realized_fx(db, FIRM, "CLI")["lines"] == []
    assert FXR.unrealized_fx(db, FIRM, "CLI")["lines"] == []
    assert FXR.currency_exposure(db, FIRM, "CLI")["by_currency"] == []
    ofb = FXR.open_foreign_balances(db, FIRM, "CLI")
    assert ofb["receivables"] == [] and ofb["payables"] == []
    audit = FXR.exchange_rate_audit(db, FIRM, "CLI")
    assert audit["documents"] == [] and audit["adjustments"] == []


def test_multi_year_realized_fx_is_scoped_to_settlement_year(monkeypatch):
    from services.fx_reporting_service import fx_reporting_service as FXR
    FIRM = "FIRM-P5V4"
    cu, si, rc, db = _e2e(monkeypatch, FIRM)
    caller = _caller(FIRM)
    c = cu.create_customer(CustomerIn(client_id="CLI", name="US", state_code="27"), caller)["data"]
    inv = _invoice(si, caller, c["id"], date="2025-06-01", currency="USD", rate="80", cents=100000)
    # Settled in the NEXT financial year @85 (foreign minor units).
    rc.create_receipt(ReceiptIn(client_id="CLI", customer_id=c["id"], receipt_date="2026-05-01",
        amount_paise=100000, currency="USD", exchange_rate="85",
        allocations=[ReceiptAllocationIn(sales_invoice_id=inv["id"], allocated_paise=100000)]), caller)
    # FY 2025-26 window: no realized FX yet (still open at 31-Mar-2026).
    assert FXR.realized_fx(db, FIRM, "CLI", "2025-04-01", "2026-03-31")["net_paise"] == 0
    # FY 2026-27 window: the ₹5,000 gain is recognised on settlement.
    assert FXR.realized_fx(db, FIRM, "CLI", "2026-04-01", "2027-03-31")["net_paise"] == 500_000


def test_fx_reports_are_tenant_isolated(monkeypatch):
    """Firm A's FX reports never surface Firm B's foreign activity (same FakeDB)."""
    from services.fx_reporting_service import fx_reporting_service as FXR
    FIRM_A = "FIRM-P5A"
    cu, si, rc, db = _e2e(monkeypatch, FIRM_A)
    # Firm B shares the DB but is a separate tenant.
    db.seed("firms", {"id": "FIRM-P5B", "multi_currency_entitled": True})
    db.seed("clients", {"id": "CLI-B", "firm_id": "FIRM-P5B", "gstin": "27ZZZZZ9999Z1Z5",
                        "functional_currency": "INR", "multi_currency_enabled": True})
    from tests.e2e_harness import seed_standard_coa
    seed_standard_coa(db, "FIRM-P5B", "CLI-B")
    a = cu.create_customer(CustomerIn(client_id="CLI", name="US", state_code="27"), _caller(FIRM_A))["data"]
    _invoice(si, _caller(FIRM_A), a["id"], currency="USD", rate="83", cents=100000)
    # Firm B's exposure/open-balances see nothing from Firm A.
    assert FXR.currency_exposure(db, "FIRM-P5B", "CLI-B")["by_currency"] == []
    assert FXR.open_foreign_balances(db, "FIRM-P5B", "CLI-B")["receivables"] == []
    # Firm A does see its own.
    assert [r["currency"] for r in FXR.currency_exposure(db, FIRM_A, "CLI")["by_currency"]] == ["USD"]
