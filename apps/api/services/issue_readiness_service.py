"""The checks that stand between a draft sales invoice and its issue, asked once, in the order the issue route has always refused in
(POST-A-125).

`issue_invoice` used to carry these inline and answer the FIRST one that failed, as a sentence. A screen that wants to say "three
things are in the way" before the click cannot get that from a route that stops at one, and a second list written for the screen
would be a second place to say the same thing. So there is one list: the issue route asks `blockers_for_sales_invoice(first_only=True)`
and refuses with the first blocker (`refuse`), exactly as it always stopped at the first refusal, and
`GET /api/sales-invoices/{id}/issue-preflight` returns all of them.

Each check is the function the route already called, run under a catch of the 422 it raises, and its CODE is attached here at the call
site. The code is never read back out of the sentence, so rewording a sentence cannot change what a screen branches on.

THE ORDER IS THE ROUTE'S OLD ORDER: status, the locks (the firm's year, then the client's closures and a filed return: one blocker
for one cause), the number's two rules, the place of supply, whether the draft adds up to its own lines, the chart of accounts. A
draft that is not a draft has one blocker and nothing after it is asked: its lock and its accounts are a different question about a
document that is already issued.

THE CHART OF ACCOUNTS IS ASKED LAST AND ASKED OF THE POSTING'S OWN LOOKUPS (`phase2_journal_service.missing_accounts_for_sales_invoice`
resolves `domain/sales/issue_readiness.required_accounts` through the same `_find_account` the posting uses), so a pre-flight that
says "ready" cannot be refused by a missing account the posting then looks for.

It writes nothing. A pre-flight is a reading at one moment: a Partner locking the year a second later still refuses the issue, and the
issue route asks again.
"""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException

from domain.accounting import draft_integrity
from domain.gst import invoice_series
from domain.sales import issue_readiness as ir
from models.common import api_response
from services import draft_integrity_service, numbering, period_lock_service
from services.period_validation_service import period_validation_service

NOT_A_DRAFT_SENTENCE = "Only draft invoices can be issued"


def placeholder_number_problem(invoice_no: str) -> Optional[str]:
    """The sentence for a number an unattended process made up (POST-A-216), or None.

    Billing, recurring invoices and late-interest drafts carry `DRAFT-XXXXXXXXXX` "the CA must replace". That string is a legal Rule 46(b)
    number, so `invoice_series.format_violation` cannot refuse it; a draft may hold it and an invoice may not."""
    if not numbering.is_placeholder_invoice_no(invoice_no):
        return None
    return (
        f"This invoice still carries the placeholder number {invoice_no}. Replace it with the next number in your "
        "invoice series before issuing: once issued, the number is the one on the tax invoice.")


def _sentence(exc: HTTPException) -> str:
    """The words a refusal carried. The checks raise a string; a dict with a `message` is read the way the browser reads it."""
    detail = exc.detail
    if isinstance(detail, dict):
        detail = detail.get("message")
    return str(detail) if detail else "This invoice cannot be issued."


def _ask(found: list[ir.Blocker], code: str, check) -> None:
    try:
        check()
    except HTTPException as exc:
        found.append(ir.blocker(code, _sentence(exc)))


def _status(found: list[ir.Blocker], invoice: dict) -> None:
    _ask(found, ir.NOT_A_DRAFT, lambda: draft_integrity_service.assert_a_draft(invoice, not_a_draft=NOT_A_DRAFT_SENTENCE))


def _locks(found: list[ir.Blocker], db, firm_id: str, invoice: dict) -> None:
    """The date is the posting's, and a draft raised in June and issued in September is posted with its June date, so the locks are
    asked HERE and not only at create. The firm's year first, then the client's: `period_lock_service.assert_open` answers for the
    closures AND for a return covering the date that has been filed, so it repeats the firm's year when that is what is locked. One
    cause is one blocker: the second lock is asked only when the first did not refuse, and both are one code, `PERIOD_LOCKED`,
    because the second cannot tell a filed return from a finalised year by anything but its sentence."""
    date = invoice.get("invoice_date")
    if not date:
        return
    _ask(found, ir.PERIOD_LOCKED, lambda: period_validation_service.validate_posting_date(firm_id, date))
    if not found:
        _ask(found, ir.PERIOD_LOCKED, lambda: period_lock_service.assert_open(db, firm_id, invoice.get("client_id"), date))


def _number(found: list[ir.Blocker], invoice: dict) -> None:
    invoice_no = invoice.get("invoice_no") or ""
    illegal = invoice_series.format_violation(invoice_no)
    if illegal:
        found.append(ir.blocker(ir.INVOICE_NO_NOT_ALLOWED, illegal))
    placeholder = placeholder_number_problem(invoice_no)
    if placeholder:
        found.append(ir.blocker(ir.INVOICE_NO_PLACEHOLDER, placeholder))


def _place(found: list[ir.Blocker], invoice: dict) -> None:
    place = ir.place_of_supply_problem(invoice.get("supply_state_code"))
    if place:
        found.append(ir.blocker(*place))


def blockers_for_sales_invoice(db, firm_id: str, invoice: dict, *, first_only: bool = False) -> list[ir.Blocker]:
    """Every reason the draft `invoice` cannot be issued now, in the order the route refuses in. Empty means ready.

    `first_only` stops at the first reason, which is what the ISSUE does: it used to end at the first refusal, so a bad number never
    reached the reads that follow it (the draft's lines, the currency master, the chart of accounts), and an error in one of those reads
    could not turn a plain refusal into a generic failure. The pre-flight asks for them all."""
    found: list[ir.Blocker] = []
    _status(found, invoice)
    if found:
        return found
    _locks(found, db, firm_id, invoice)
    if first_only and found:
        return found
    _number(found, invoice)
    if first_only and found:
        return found
    _place(found, invoice)
    if first_only and found:
        return found
    _ask(found, ir.DRAFT_DOES_NOT_ADD_UP,
         lambda: draft_integrity_service.assert_draft_adds_up(db, draft_integrity.SALES_INVOICE, invoice))
    if first_only and found:
        return found

    from services.phase2_journal_service import phase2_journal_service
    missing = phase2_journal_service.missing_accounts_for_sales_invoice(
        db, firm_id, invoice.get("client_id") or "", invoice)
    if missing:
        found.append(ir.blocker(ir.COA_MISSING, ir.missing_accounts_sentence(missing)))
        return found
    # Asked last, because it builds the lines the posting would write and so needs the accounts. An earlier issue that posted and then
    # failed leaves an entry; one the draft still matches is simply linked at the click, and only one it no longer matches is a blocker.
    left_behind = phase2_journal_service.entry_left_behind_problem(db, firm_id, invoice.get("client_id") or "", invoice)
    if left_behind:
        found.append(ir.blocker(ir.ENTRY_ALREADY_IN_LEDGER, left_behind))
    return found


def blockers_without_database(invoice: dict) -> list[ir.Blocker]:
    """The checks that need no database, for the in-memory mode that has none: the status, the number's two rules and the place of
    supply. It says so by name; a mock-mode pre-flight is not a claim about locks or accounts it did not look at."""
    found: list[ir.Blocker] = []
    _status(found, invoice)
    if found:
        return found
    _number(found, invoice)
    _place(found, invoice)
    return found


def refuse(blocker: ir.Blocker):
    """The refusal the issue route answers with for its first blocker.

    Every blocker but one is a 422 whose `detail` is `{message, code, action}`: the browser already reads a `detail` object's `message`
    (lib/api `errorMessage`), so an old screen shows the same sentence. A missing chart of accounts keeps the answer it has always had,
    HTTP 200 with `success: false`, because the editor and the bulk callers branch on that; the code and action ride in `data`."""
    body = {"code": blocker.code, "action": blocker.action}
    if blocker.code == ir.COA_MISSING:
        return api_response(False, body, blocker.message)
    raise HTTPException(status_code=422, detail={"message": blocker.message, **body})
