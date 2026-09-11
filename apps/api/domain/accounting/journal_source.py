"""
What DOCUMENT a journal entry came from — the vocabulary, in one place.

`journal_entries.source_type` / `source_id` have existed since migration 104,
and migration 104 created `idx_je_source (source_type, source_id)` for the
lookup they enable. But only twelve of the twenty-six posting paths ever filled
them in. The fourteen that did not include every sales invoice, every purchase
bill, all four §34 note paths, payroll, the settlement, all four fixed-asset
paths and the bank-transaction journal — that is, most of the general ledger of
a real practice. So the index was there and the answer was not.

WHY IT MATTERS, beyond navigation
    A general ledger whose entries cannot name the document behind them is a
    ledger you have to take on trust. A CA reading "Trade Receivables 1,18,000
    Dr" wants the invoice, and Tally has trained them to expect one keystroke
    to it. More than convenience: when the GL and a sub-ledger disagree, the
    link is how you find WHICH document drifted, and `reverse_entry` already
    propagates source_type/source_id onto a reversal precisely so the document
    can be found from either.

WHAT THIS IS NOT
    Not a second opinion about what an entry IS. `entry_type` (Sales, Purchase,
    Payment, Receipt, Journal, Contra, Opening — CHECK-constrained by migration
    003) says what KIND of entry it is, and the posting kernel already sets it.
    This says which ROW of which table produced it, which is a different fact
    and the only one you can navigate to.

TWO SPELLINGS ALREADY EXIST AND ARE KEPT
    The twelve paths that stamped a source used lowercase snake_case for
    documents (`receipt`, `purchase_payment`, `bank_transaction`) and
    CamelCase for two of the opening paths (`Opening`, `TrialBalance`). The new
    fourteen all take the snake_case form, because it is the dominant one and
    because it matches the table each document lives in — which is what lets a
    reader resolve one without a translation table. The two CamelCase values
    are NOT renamed: they are in production data, and a rename would strand
    every entry already carrying them for no gain (neither names a row a CA can
    open — an opening balance and a trial-balance import are events, not
    documents).

NULL IS STILL MEANINGFUL, and stamping does not change what it means
    Every guard that reads source_type treats NULL as NOT manual —
    `manual_journal_service._is_manual` is `(source_type or "") == "manual"`,
    and migrations 275 and 338 use `COALESCE(source_type, '') <> 'manual'`. So
    an entry that gains a real source is refused by the edit and discard paths
    exactly as it was when it had none. What changes is only that the refusal
    can now say WHICH document to go and correct, instead of "a source
    document".
"""
from __future__ import annotations

#: A person typed it. The one value the edit and discard paths allow.
MANUAL = "manual"

#: Sales cycle.
SALES_INVOICE = "sales_invoice"
CREDIT_NOTE = "credit_note"                 # §34(1) — sales value/tax DECREASE
SALES_DEBIT_NOTE = "sales_debit_note"       # §34(3) — sales value/tax INCREASE
RECEIPT = "receipt"

#: Purchase cycle.
PURCHASE_BILL = "purchase_bill"
DEBIT_NOTE = "debit_note"                   # purchase return — AP DECREASE
PURCHASE_CREDIT_NOTE = "purchase_credit_note"   # purchase value/tax INCREASE
PURCHASE_PAYMENT = "purchase_payment"

#: Payroll.
PAYROLL_RUN = "payroll_run"
PAYROLL_DISBURSEMENT = "payroll_disbursement"
SETTLEMENT = "settlement"

#: Fixed assets. All four point at the ASSET, because that is the row a CA
#: opens — a depreciation charge has no document of its own, and its asset is
#: what explains it.
FIXED_ASSET = "fixed_asset"
DEPRECIATION = "depreciation"
ASSET_DISPOSAL = "asset_disposal"

#: Banking.
BANK_TRANSACTION = "bank_transaction"
BANK_OVERPAYMENT = "bank_overpayment"

#: Events rather than documents — kept in their original spelling, see above.
OPENING = "Opening"
TRIAL_BALANCE_IMPORT = "TrialBalance"
YEAR_END_ADJUSTMENT = "year_end_adjustment"

#: Every value this codebase writes. A test asserts that nothing is stamped
#: that is not in here, so a fifteenth spelling cannot appear quietly.
ALL_SOURCES = frozenset({
    MANUAL,
    SALES_INVOICE, CREDIT_NOTE, SALES_DEBIT_NOTE, RECEIPT,
    PURCHASE_BILL, DEBIT_NOTE, PURCHASE_CREDIT_NOTE, PURCHASE_PAYMENT,
    PAYROLL_RUN, PAYROLL_DISBURSEMENT, SETTLEMENT,
    FIXED_ASSET, DEPRECIATION, ASSET_DISPOSAL,
    BANK_TRANSACTION, BANK_OVERPAYMENT,
    OPENING, TRIAL_BALANCE_IMPORT, YEAR_END_ADJUSTMENT,
})

#: The sources where the ENTRY IS THE RECORD — there is no separate row to
#: open, so they carry no source_id and must not be made to.
#:
#: A manual journal is typed directly into the ledger; its "document" is the
#: entry. An opening balance and a trial-balance import are EVENTS that
#: produced an entry, and the thing a CA would want to see for either is the
#: entry itself. Stamping a source_id on these would mean inventing a row id
#: that points at nothing, which is worse than the honest absence: a
#: drill-through would offer a link and then fail to resolve it.
#:
#: Every OTHER source names a row — an invoice, a bill, a note, a payroll run,
#: an asset, a bank line — and a source_type without its source_id there is a
#: breadcrumb leading nowhere, which is what the guard test refuses.
ENTRY_IS_THE_RECORD = frozenset({MANUAL, OPENING, TRIAL_BALANCE_IMPORT})

#: What to call each one when telling a CA where to go. Used by the refusal in
#: manual_journal_service, so the sentence names the document rather than
#: echoing a column value at them.
SOURCE_LABEL = {
    MANUAL: "manual journal",
    SALES_INVOICE: "sales invoice",
    CREDIT_NOTE: "credit note",
    SALES_DEBIT_NOTE: "debit note",
    RECEIPT: "receipt",
    PURCHASE_BILL: "purchase bill",
    DEBIT_NOTE: "debit note",
    PURCHASE_CREDIT_NOTE: "credit note",
    PURCHASE_PAYMENT: "payment",
    PAYROLL_RUN: "payroll run",
    PAYROLL_DISBURSEMENT: "salary disbursement",
    SETTLEMENT: "full and final settlement",
    FIXED_ASSET: "fixed asset",
    DEPRECIATION: "depreciation charge",
    ASSET_DISPOSAL: "asset disposal",
    BANK_TRANSACTION: "bank entry",
    BANK_OVERPAYMENT: "bank entry",
    OPENING: "opening balance",
    TRIAL_BALANCE_IMPORT: "trial balance import",
    YEAR_END_ADJUSTMENT: "year-end adjustment",
}


def label_for(source_type: str | None) -> str:
    """What to call this entry's origin in a sentence, or a safe generic.

    Deliberately falls back rather than raising: an entry posted before its
    path stamped a source has NULL here, and the sentence it appears in is a
    refusal the CA needs to read — failing to render it would turn a clear
    "correct the document" into a 500.
    """
    return SOURCE_LABEL.get((source_type or "").strip(), "source document")
