"""The issue routes ask a draft whether it adds up to its own lines before they post it (ledger POST-A-335).

`domain/accounting/draft_integrity.py` holds the rule and says why it is asked at issue; this is the part that reads the lines
and refuses. The six issue routes call `assert_draft_adds_up` after they have established that the document is a draft and
before they ask anything of the period or post anything, so a refused issue leaves the draft exactly as it was.

The lines are read with `core.db_paging.fetch_all`: PostgREST answers a request with at most a thousand rows and says nothing when
it cuts one short, and a figure checked against a truncated read would refuse a draft that adds up. One literal chain per table
so the firm-scope reader (`tests/test_every_query_on_a_firm_table_carries_its_firm_scope.py`) can read each of them; the lines are
keyed on a header the route has already read for the caller's firm.
"""
from __future__ import annotations

from fastapi import HTTPException

from core.db_paging import fetch_all
from domain.accounting import draft_integrity as rule
from domain.currency.document_currency import document_currency_from_row

_MONEY = "id, taxable_amount_paise, cgst_paise, sgst_paise, igst_paise"

_LINES = {
    rule.SALES_INVOICE: lambda db, doc: fetch_all(
        lambda: db.table("client_sales_invoice_lines")
        .select(f"{_MONEY}, cess_paise, discount_paise").eq("sales_invoice_id", doc), label="issue-check invoice lines"),
    rule.PURCHASE_BILL: lambda db, doc: fetch_all(
        lambda: db.table("purchase_bill_lines")
        .select(f"{_MONEY}, cess_paise, itc_eligible").eq("bill_id", doc), label="issue-check bill lines"),
    rule.CREDIT_NOTE: lambda db, doc: fetch_all(
        lambda: db.table("credit_note_lines").select(_MONEY).eq("credit_note_id", doc), label="issue-check credit note lines"),
    rule.DEBIT_NOTE: lambda db, doc: fetch_all(
        lambda: db.table("debit_note_lines").select(_MONEY).eq("debit_note_id", doc), label="issue-check debit note lines"),
    rule.PURCHASE_CREDIT_NOTE: lambda db, doc: fetch_all(
        lambda: db.table("purchase_credit_note_lines").select(_MONEY).eq("credit_note_id", doc),
        label="issue-check purchase credit note lines"),
    rule.SALES_DEBIT_NOTE: lambda db, doc: fetch_all(
        lambda: db.table("sales_debit_note_lines").select(_MONEY).eq("debit_note_id", doc),
        label="issue-check sales debit note lines"),
}


def assert_draft_adds_up(db, kind: str, header: dict) -> None:
    """Refuse (422, in words) a draft whose stored figures are not its lines' or whose carried-over flag is set."""
    doc_id = header.get("id")
    if not doc_id:
        raise ValueError("a draft is checked by its id")
    found = rule.problems(kind, header, _LINES[kind](db, str(doc_id)), to_base=_converter(db, kind, header))
    if found:
        raise HTTPException(status_code=422, detail=rule.refusal(kind, found))


def _converter(db, kind: str, header: dict):
    """What takes a line sum in the document's currency to rupees' paise: the document's own stored rate and its currency's minor
    unit, read the way the posting reads them (`document_currency_from_row`), so the check and the journal convert alike. Nothing
    for a document in rupees. A stored rate that is not a positive number is refused in words and not left to `to_base`."""
    if not rule.is_foreign(kind, header):
        return None
    currency = document_currency_from_row(db, header)
    if currency.rate <= 0:
        raise HTTPException(status_code=422, detail=(
            f"Cannot issue this {rule.NAME_OF[kind]}: the exchange rate recorded on it is not a positive number, so its rupee "
            "figures cannot be checked against its lines. Nothing was posted."))
    return currency.to_base


def assert_a_draft(header: dict, *, not_a_draft: str) -> None:
    """The status test every issue route carried, as one statement: the lint ratchet counts statements and `assert_draft_adds_up`
    (asked later, once the period locks have been, and before anything is written) is the statement this one makes room for."""
    if header.get("status") != "draft":
        raise HTTPException(status_code=422, detail=not_a_draft)
