"""
TDS return service — derives Form 26Q (vendor/non-salary TDS, IT Act §194
series) and Form 24Q (salary TDS, IT Act §192) ENTIRELY from posted
accounting data, and reconciles the computed TDS to the GL TDS Payable
control accounts.

Single source of truth (mirrors services/gst_return_service.py's audit-H8
pattern): returns are NEVER computed from frontend payloads. The flow is:

    posted purchase bills (26Q) / finalized payroll runs (24Q)
            │  →  domain.tds.TDSComputer  →  26Q / 24Q payload
            │
            └── the SAME documents posted the journal entries, so the
                return's total TDS deducted must equal the credit movement
                on "TDS Payable" (26Q) / "TDS Payable - Salary" (24Q).
                Reconciliation is done against the SPECIFIC journal entries
                those documents posted (via their own journal_entry_id), not
                a calendar date-range scan — a payroll run's accrual journal
                is dated the day it was FINALIZED, not the payroll period
                (services/phase2_journal_service.py::journal_for_payroll),
                so a date-range query would wrongly miss a late-finalized
                run's journal (or wrongly catch an unrelated one dated the
                same day).

26Q IS RESIDENTS ONLY, AND 27Q IS WHERE THE REST GO. Rule 31A(4)(a) gives Form
26Q the non-salary payments to residents and (b) gives Form 27Q the payments to
non-residents, so a document whose vendor is recorded as a non-resident
(migration 308) is excluded from 26Q and REPORTED in `excluded_non_resident`
rather than dropped.

    This paragraph used to end "There is no 27Q counterpart to build it into:
    s.195 ... is not modelled anywhere in this codebase". Both halves stopped
    being true — domain/tds/section_195.py rates the remittance, and
    tds_27q_from_books below files it (TDS-09). Residency routes a row, not the
    section number: §194E, §194LB/§194LC and §196D all charge non-residents and
    all report on 27Q too. See domain/tds/residency.py.

BOTH VENDOR RETURNS READ TWO KINDS OF DOCUMENT. §194 and §195 charge at the
time of credit "or at the time of payment thereof, whichever is EARLIER", so a
vendor ADVANCE is a charging event in its own right (migration 358) and its
deduction posts to the same control account with the same challan obligation.
Reading only `purchase_bills` left a real deduction in the ledger and in the
register but off the statement — and then the reconciliation failed, because
the GL movement included it.

A PURCHASE RETURN AFTER THE TAX WAS WITHHELD IS REPORTED, NOT ADJUSTED. The
FIGURES still do not move — a note changes neither `payment_amount_paise` nor
`tds_paise` — because §194's charge on "the aggregate of the sums credited or
paid" and §199's credit to the deductee for tax already paid over point in
opposite directions, and which applies turns on when the challan went, which
the books do not record. What changed (PUR-23 ≡ TDS-32) is that it is no
longer SILENT: `_credit_moved_gaps` names every bill in the quarter whose
credit a note has moved since the deduction, in `statutory_gaps`, so the CA
assembling the return sees it before the vendor's 26AS shows income they did
not earn. `domain/tds/purchase_return.py` is the rule; both note routers now
resync the register on issue, which its own docstring always claimed happened
"on every transition".

THE REGISTER'S TYPED ROWS ARE ON A 26Q, OUTSIDE THE TIE-OUT (POST-A-078). A deduction a CA typed on the TDS screen is a register row that neither a bill nor an
advance wrote. It is a deduction the deductor made, so the statement of the quarter's deductions carries it: `tds_26q_from_books` makes it a deductee row like a
bill's, fills it from the quarter's challans by the same FIFO the register's own readers use (`deposit_due.mapping_from_register` has always put typed rows in that
fill, so a statement that left them out disagreed with them about which deduction a challan paid), and gives it its payment code. Nothing records which
journal, if any, carries it (one may have been passed by hand), so the tie-out with the TDS Payable account compares the bills and advances alone (`reconciliation.books_paise`) and the typed tax is reported beside it
(`reconciliation.typed_paise`, and `typed_on_statement`: how many, the tax, each row and a sentence that says so). A typed row recorded for another statement
(`return_type`, the register's routing key) is not carried and is named in `excluded_typed`. So is a typed row naming a supplier now recorded as non-resident, with
its own sentence: it is NOT put in `excluded_non_resident`, whose note sends the CA to the 27Q built from the books, because that statement reads bills and advances
only and the typed row would be on neither.

Integer paise throughout. # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT.
"""
from __future__ import annotations

import logging

from domain.tds import vocabulary as _vocabulary
from domain.tds import deductee_payment_code as _deductee_payment_code

from core.ist_clock import month_end_date
from core.observability import capture_soft_failure
from domain.tds import challan_mapping
from domain.tds import keying_sheet as _keying_sheet
from domain.tds import manual_register
from domain.tds.tds_computer import (
    TDSComputer, TDSDeducteeRecord, TDS27QDeducteeRecord,
)
from domain.tds.section_rates import quarter_dates
from domain.tds.residency import FORM_26Q, is_non_resident
from domain.tds.purchase_return import credit_moved_after_deduction, deposit_position
from core.db_paging import fetch_all
from core.db_provider import privileged_for

_logger = logging.getLogger("caflow.tds_return")

_computer = TDSComputer()

# Posted (on-books) statuses. Drafts are off-books — no TDS liability has
# actually posted to the GL yet (mirrors gst_return_service.py's
# _SALES_POSTED / _BILL_POSTED convention).
_BILL_POSTED = ("received", "partially_paid", "paid")
_PAYROLL_POSTED = ("finalized", "paid")


def _find_account_by_exact_name(db, firm_id: str, client_id: str, account_name: str) -> str | None:
    """Resolve a chart_of_accounts id by EXACT name match (firm-wide or this
    client's own account), not the ILIKE-substring pattern
    phase2_journal_service._find_account uses elsewhere.

    "TDS Payable" and "TDS Payable - Salary" are two distinct real accounts
    in the seeded chart (confirmed in the live DB), and the latter's name
    contains the former's as a substring — an ILIKE '%TDS Payable%' lookup
    with no ORDER BY before its .limit(1) can non-deterministically resolve
    to either one. That ambiguity already exists in
    phase2_journal_service.journal_for_purchase_bill's own account lookup;
    not fixed here (out of scope, and a live posting-path change deserves its
    own dedicated verification), but this reconciliation must not repeat it —
    an exact match can never be ambiguous between the two.
    """
    resp = (
        db.table("chart_of_accounts").select("id")
        .eq("firm_id", firm_id)
        .or_(f"client_id.eq.{client_id},client_id.is.null")
        .eq("account_name", account_name)
        .eq("is_active", True)
        .limit(1).execute()
    )
    return resp.data[0]["id"] if resp.data else None


def _salary_tds_account(db, firm_id: str, client_id: str) -> tuple[str | None, str | None, str | None]:
    """(id, name, note) of the account salary TDS is credited to, through the payroll resolver. No account is (None, None,
    None); two that could be it is (None, None, the sentence naming both), because a tie-out against a guessed account is a
    tie-out nobody can rely on."""
    from domain.payroll import ledger_accounts as PL
    from services.payroll_ledger_accounts import resolve
    try:
        found = resolve(db, firm_id=firm_id, client_id=client_id, ledger=PL.TDS_PAYABLE_SALARY, required=False)
    except PL.PayrollLedgerAmbiguous as exc:
        return None, None, exc.sentence
    return (found.id, found.account_name, None) if found else (None, None, None)


def _gl_movement_for_entries(db, firm_id: str, client_id: str, account_id: str | None, journal_entry_ids: list[str]) -> int:
    """Net CREDIT movement (credit - debit) on one account, restricted to a
    specific set of journal entries — see module docstring for why this is a
    journal_entry_id lookup rather than a calendar date-range scan."""
    if not account_id or not journal_entry_ids:
        return 0
    total = 0
    ids = list(dict.fromkeys(journal_entry_ids))  # de-dupe, preserve order
    for i in range(0, len(ids), 200):
        chunk = ids[i:i + 200]
        # journal_lines rows carry no firm_id of their own (confirmed against
        # services/phase2_journal_service.py's insert payload and mirrored by
        # gst_return_service.py's identical GL query) — the firm scope comes
        # entirely from journal_entry_ids already being firm-scoped documents'
        # own journal_entry_id references.
        rows = fetch_all(lambda chunk=chunk: db.table("journal_lines")
            .select("id, journal_entry_id, account_id, debit_paise, credit_paise")
            .eq("account_id", account_id)
            .in_("journal_entry_id", chunk))
        for r in rows:
            total += int(r.get("credit_paise") or 0) - int(r.get("debit_paise") or 0)
    return total


def _posted_vendor_tds_bills(db, firm_id: str, client_id: str, start: str, end: str) -> list[dict]:
    return fetch_all(lambda: db.table("purchase_bills").select("*")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .in_("status", list(_BILL_POSTED))
            .gt("tds_paise", 0)
            .gte("bill_date", start).lte("bill_date", end))


def _posted_vendor_tds_bills_including_nil_195(
        db, firm_id: str, client_id: str, start: str, end: str) -> list[dict]:
    """26Q's bill source PLUS the §195 remittances that withheld nothing.

    Two narrow queries rather than one wide one. A quarter's purchase bills are
    proportional to transaction volume, so fetching them all and filtering in
    Python would break CLAUDE.md's reporting rule; `.gt("tds_paise", 0)` and
    `.eq("tds_section", "195")` each stay selective, and the ids are merged.
    """
    withheld = _posted_vendor_tds_bills(db, firm_id, client_id, start, end)
    nil_195 = fetch_all(lambda: db.table("purchase_bills").select("*")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .in_("status", list(_BILL_POSTED))
            .eq("tds_section", "195")
            .gte("bill_date", start).lte("bill_date", end))
    by_id = {r["id"]: r for r in withheld}
    for r in nil_195:
        by_id.setdefault(r["id"], r)
    return list(by_id.values())


def _withholding_advances(db, firm_id: str, client_id: str, start: str, end: str) -> list[dict]:
    """Vendor payments that withheld — the OTHER half of the charging event.

    §194 and §195 charge at credit or payment, whichever is EARLIER, and
    migration 358 made an advance withhold. Those deductions post to the same
    TDS Payable control account and carry the same challan obligation, so a
    return that read only `purchase_bills` would leave a real deduction off the
    statement it belongs on while the GL and the register both hold it.

    `tds_base_paise` rather than `tds_paise` is the filter, because a §195
    remittance that withheld NIL is still reported on 27Q with a reason —
    26Q's own resident filter is applied by the caller.
    """
    rows = fetch_all(lambda: db.table("purchase_payments").select("*")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .gt("tds_base_paise", 0)
            .gte("payment_date", start).lte("payment_date", end))
    return [r for r in rows if not r.get("is_reversed")]


def _typed_deductions_in_quarter(db, firm_id: str, client_id: str, start: str, end: str) -> list[dict]:
    """The deductions a CA TYPED on the TDS screen for this quarter that withheld tax: `tds_deductions` rows that neither a purchase bill nor a vendor advance wrote
    (`manual_register.written_by_a_document`), except salary (a typed section 192 is refused at the door and belongs to 24Q).

    They are deductions the deductor made, so the 26Q carries them as deductee rows (POST-A-078). Nothing records which journal, if any, carries them (the typed
    register is a book of its own, and a journal passed by hand names no row of it), so the statement keeps them out of the tie-out with the TDS Payable control account that `reconciliation` reports and says so.

    A row that withheld nothing is not one: a statement reports DEDUCTIONS (bills are read with `tds_paise > 0` and advances are dropped when they withheld nothing),
    and a payment recorded below its section's limit is a register entry that counts toward the year's total, not tax to key.

    NOT GUARDED, ON PURPOSE. If this read fails the statement fails with it, as it does when any of its other reads fail. The one way to build the statement
    without it is to build one that says nothing about the register, and silence is the failure this read exists to remove.
    """
    # The rows a document wrote are told apart in Python, as `manual_register.prior_manual_aggregate` does: the quarter's document-written rows are one per bill or
    # advance this function already reads whole, so the read stays the size of the quarter's documents, and no query here depends on a filter the stand-ins for the
    # database in the statement tests do not have.
    rows = fetch_all(lambda: db.table("tds_deductions")
            .select("id, deductee_name, deductee_pan, section, transaction_date, payment_amount_paise, tds_paise, tds_rate_pct, "
                    "is_lower_deduction, lower_deduction_cert, nature_of_payment, vendor_id, return_type, purchase_bill_id, purchase_payment_id")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .gte("transaction_date", start).lte("transaction_date", end))
    return [r for r in rows
            if not manual_register.written_by_a_document(r)
            and int(r.get("tds_paise") or 0) > 0
            and (r.get("section") or "") != "192"]


#: The sentence the two return screens show after the count and the tax of the typed deductions the statement LEAVES OUT (the drive's copy of it is compared
#: with this by a test). It does not repeat the lead, which the screen writes from the count and the tax: that these are the deductions typed on the TDS screen,
#: and that they are not on the statement. Since POST-A-078 carried the typed rows, this is the sentence for the ones whose register row names another statement;
#: a typed row whose supplier is now recorded as non-resident is left out too, and `_excluded_typed_reason` words that one.
EXCLUDED_TYPED_REASON = (
    "Their register rows are recorded for another statement, so they are not in this one's totals. Key them on the statement they are "
    "recorded for, or correct the register row if they belong on this one."
)

#: The sentence the two return screens show after the count and the tax of the typed deductions the statement CARRIES (POST-A-078). The lead, from the count and
#: the tax, says they are on the statement; this says what is different about them.
TYPED_ON_STATEMENT_REASON = (
    "Each is a deductee row under the challan that paid it, like a bill's. Nothing records which journal, if any, carries a deduction typed on the TDS screen, so "
    "the tie-out with the TDS Payable account compares the purchase bills and advances alone, and these are outside it, as is any journal passed by hand for them."
)


def _excluded_typed_reason(other_statement: list[dict], non_resident: list[dict], fy: str) -> str:
    """The sentence after the lead of `excluded_typed`, for the two reasons a typed deduction is left off the 26Q: its register row is recorded for another
    statement (`EXCLUDED_TYPED_REASON`, unchanged where it is the only reason), or the supplier it names is NOW recorded as non-resident.

    THE SECOND IS NOT THE NON-RESIDENT NOTE'S (the review of POST-A-078). That note tells the CA to build the 27Q for the same quarter, and `tds_27q_from_books`
    reads purchase bills and advances only, so a typed row moved there would be on neither statement while the screen said it was on the other. This says so: the
    payment belongs on the non-resident statement under Rule 31A(4)(b), the one built from the books does not carry it, and the CA keys it there from the register
    or corrects the supplier's record."""
    if not non_resident:
        return EXCLUDED_TYPED_REASON
    form = _vocabulary.statement_form(_vocabulary.NON_RESIDENT, fy_label=fy)
    one = len(non_resident) == 1
    tail = (
        f" now recorded as non-resident, so {'it belongs' if one else 'they belong'} on Form {form} under Rule 31A(4)(b) and not on this statement, and the "
        f"Form {form} built from the books carries purchase bills and advances only, not deductions typed on the TDS screen. Key {'it' if one else 'them'} on "
        f"Form {form} from the TDS register, or correct the supplier's record where the supplier is a resident.")
    if not other_statement:
        return ("The supplier it names is" if one else "The suppliers they name are") + tail
    alone = len(other_statement) == 1
    return (
        f"{'One of them is' if alone else f'{len(other_statement)} of them are'} recorded for another statement: key "
        f"{'it on the statement it is' if alone else 'them on the statement they are'} recorded for, or correct the register row if "
        f"{'it belongs' if alone else 'they belong'} on this one. "
        + ("One of them names a supplier that is" if one else f"{len(non_resident)} of them name suppliers that are") + tail)


def _on_this_statement(row: dict) -> bool:
    """Whether a typed row belongs on the 26Q: its `return_type` is the register's routing key (migration 037, '26Q' by default, and the typed door never sets
    another), so a row recorded for another statement is left to it and named, never carried here."""
    return (str(row.get("return_type") or "").strip() or FORM_26Q) == FORM_26Q


def _typed_rate_bps(rate_pct) -> int:
    """The rate a typed row stored as a percentage (`tds_rate_pct`, NUMERIC), as basis points, the unit a bill's rate travels in."""
    from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
    try:
        return int((Decimal(str(rate_pct or 0)) * 100).to_integral_value(rounding=ROUND_HALF_UP))
    except InvalidOperation as unreadable:
        # A stored rate that cannot be read becomes 0%, which is a TDS row that deducted nothing, so it is reported (POST-A-505).
        capture_soft_failure(unreadable, operation="tds_return.typed_rate_unreadable", rate=str(rate_pct)[:40])
        return 0


def _typed_on_statement_reason(events: list[dict], fy: str) -> str:
    """The carried note's sentence: the fixed part, then what applies to these rows: how many name no supplier (their tax was worked out on the typed rows for
    their PAN alone), how many sit under a section that also reaches a non-resident with no supplier to record the payee's residence, and how many have the same
    day and amount as a bill or an advance on this statement."""
    parts = [TYPED_ON_STATEMENT_REASON]
    no_supplier = [e for e in events if not e.get("vendor_id")]
    if no_supplier:
        n = len(no_supplier)
        parts.append(
            f"{'One of them names' if n == 1 else f'{n} of them name'} no supplier, so the tax on {'it' if n == 1 else 'each'} was worked out on the "
            "deductions typed for its PAN alone, without any supplier's bills.")
    residence = _residence_not_recorded(events)
    if residence:
        n = len(residence)
        parts.append(
            f"{'One' if n == 1 else n} under section {', '.join(sorted({e['section'] for e in residence}))} {'names' if n == 1 else 'name'} no supplier, "
            "so the payee's residence is not recorded: it is carried here as a payment to a resident, and a payment to a non-resident goes on Form "
            f"{_vocabulary.statement_form(_vocabulary.NON_RESIDENT, fy_label=fy)} (Rule 31A(4)(b)).")
    mirrored = [e for e in events if e.get("mirrors")]
    if mirrored:
        n = len(mirrored)
        parts.append(
            f"{'One has' if n == 1 else f'{n} have'} the same day and amount as a bill or an advance on this statement and may be the same payment "
            "reported twice; the statement's gaps name them.")
    return " ".join(parts)


def _residence_not_recorded(events: list[dict]) -> list[dict]:
    """Typed rows that name no supplier under a section whose charge also reaches a non-resident (`residency.SECTIONS_REACHING_NON_RESIDENTS` and
    `SECTIONS_UNSETTLED_FOR_A_NON_RESIDENT`): the register holds no fact about the payee's residence, so whether the row belongs on 26Q is not known."""
    from domain.tds.residency import SECTIONS_REACHING_NON_RESIDENTS, SECTIONS_UNSETTLED_FOR_A_NON_RESIDENT
    from domain.tds.section_rates import parent_of
    reaching = set(SECTIONS_REACHING_NON_RESIDENTS) | set(SECTIONS_UNSETTLED_FOR_A_NON_RESIDENT)
    return [e for e in events if not e.get("vendor_id") and parent_of(str(e.get("section") or "")) in reaching]


def _mark_mirrors(typed: list[dict], documents: list[dict], vendors: dict[str, dict]) -> list[str]:
    """A typed row that names a supplier and has the same day and amount as a bill or an advance of that supplier on this statement: the door named it when the
    row was recorded (`tds_deduction_mirrors_a_document`) and kept it, and on the statement the two would report one payment twice. Marked on the event and
    named in the statement's gaps, never dropped: whether they are one payment is the CA's to say. The amount is matched the way the door matches it, a bill's
    taxable value or its total, an advance's base or the sum paid. The supplier is named as the deductee row names it (its current record), not by the
    snapshot the typed row kept."""
    from domain.money_sentence import rupee_text
    out: list[str] = []
    for t in typed:
        if not t.get("vendor_id"):
            continue
        twins = [d for d in documents
                 if d.get("vendor_id") == t.get("vendor_id") and d.get("on_date") == t.get("on_date")
                 and t["base_paise"] in (int(d.get("base_paise") or 0), int(d.get("total_paise") or 0))]
        if not twins:
            continue
        t["mirrors"] = True
        twin = twins[0]
        out.append(
            f"The deduction typed on the TDS screen on {t['on_date']} for "
            f"{(vendors.get(t.get('vendor_id')) or {}).get('name') or t.get('deductee_name') or 'this supplier'} ({rupee_text(t['base_paise'])} paid, "
            f"{rupee_text(t['tds_paise'])} withheld) has the same day and amount as {'bill' if twin.get('kind') == 'bill' else 'advance'} {twin.get('doc_no')} on "
            "this statement. If they are the same payment it is reported twice: remove the typed deduction from the register before filing.")
    return out


def _typed_note(rows: list[dict], section_labels: dict[str, str], reason: str) -> dict:
    """A note of typed deductions: how many, the payments and the tax, each one, and the server's sentence. The same shape for the ones the statement carries
    (`typed_on_statement`) and the ones it leaves out (`excluded_typed`), so one reader reads both.

    A row's section goes out the way a deductee's does (TDS-17): the label the PERIOD's own Act uses as `section`, the stored routing key beside it as
    `section_1961`, translated here at the emission and never in the store.
    """
    return {
        "count": len(rows),
        "payment_paise": sum(int(r.get("payment_amount_paise") or 0) for r in rows),
        "tds_paise": sum(int(r.get("tds_paise") or 0) for r in rows),
        "reason": reason,
        "deductions": [
            {"id": r.get("id"), "deductee_name": r.get("deductee_name"), "deductee_pan": r.get("deductee_pan"),
             "section": section_labels.get(str(r.get("section") or "").strip(), r.get("section")), "section_1961": r.get("section"),
             "transaction_date": str(r.get("transaction_date") or "")[:10], "payment_amount_paise": int(r.get("payment_amount_paise") or 0),
             "tds_paise": int(r.get("tds_paise") or 0)}
            for r in sorted(rows, key=lambda r: (str(r.get("transaction_date") or ""), str(r.get("id") or "")))
        ],
    }


def _as_deduction_event(row: dict, *, kind: str) -> dict:
    """One shape for a bill and for an advance, so the return builders branch once.

    A bill's base is its taxable value excluding GST (CBDT Circular 23/2017);
    an advance's is `tds_base_paise`, the unallocated part alone — the allocated
    part settled bills that were charged when they were credited.

    `certificate_no` is the §197 lower-deduction certificate the deduction was
    made under (migration 359, written by routers/purchase_bills.py on BOTH the
    bill and the advance). It has to travel on the EVENT rather than be fetched
    again at payload time, because the two kinds hold it in the same column but
    are read by two different queries, and the statement needs it per ROW: §197
    authorises a rate below the section's own, so a 26Q line certified under a
    certificate and one that simply withheld too little are indistinguishable
    on the figures alone. Without it the statement understates nothing and
    EXPLAINS nothing — TRACES reads the row as a short deduction and raises a
    §201(1)/§201(1A) demand against a deductor who did exactly what the
    Assessing Officer's certificate told them to.
    """
    if kind == "typed":
        # A deduction typed on the TDS screen (POST-A-078): its own row is the document. The base is the payment typed, the taxable value excluding GST as on the
        # bill path; the rate is the one the door stored; a resident section carries neither surcharge nor cess; the s.197 certificate travels as a bill's does.
        nature = str(row.get("nature_of_payment") or "").strip()
        return {
            "id": row["id"], "kind": "typed", "vendor_id": row.get("vendor_id"),
            "section": row.get("section") or "",
            "on_date": str(row.get("transaction_date") or "")[:10],
            # Named by its day: the register row has no number of its own, and a bill's number is what a list of exclusions prints.
            "doc_no": f"TDS register entry of {str(row.get('transaction_date') or '')[:10]}",
            "narration": nature or "Payment recorded on the TDS register",
            "base_paise": int(row.get("payment_amount_paise") or 0),
            "total_paise": int(row.get("payment_amount_paise") or 0),
            "tds_paise": int(row.get("tds_paise") or 0),
            "rate_bps": _typed_rate_bps(row.get("tds_rate_pct")),
            "surcharge_paise": 0,
            "cess_paise": 0,
            "nature": nature or None,
            "basis": None,
            "form_15ca_ack_no": None,
            "certificate_no": (row.get("lower_deduction_cert") or None) if row.get("is_lower_deduction") else None,
            "journal_entry_id": None,
            "deductee_name": row.get("deductee_name"),
            "deductee_pan": row.get("deductee_pan"),
        }
    if kind == "bill":
        return {
            "id": row["id"], "kind": "bill", "vendor_id": row.get("vendor_id"),
            "section": row.get("tds_section") or "",
            "on_date": str(row.get("bill_date") or ""),
            "doc_no": row.get("bill_no") or row["id"],
            "narration": f"Vendor payment — Bill {row.get('bill_no') or row['id']}",
            "base_paise": int(row.get("taxable_amount_paise") or 0),
            # The bill's total, read only to say whether a typed deduction of the same day and amount may be this bill (`_mark_mirrors`).
            "total_paise": int(row.get("total_paise") or 0),
            "tds_paise": int(row.get("tds_paise") or 0),
            "rate_bps": int(row.get("tds_rate_bps") or 0),
            "surcharge_paise": int(row.get("tds_surcharge_paise") or 0),
            "cess_paise": int(row.get("tds_cess_paise") or 0),
            "nature": row.get("tds_nature_of_income"),
            "basis": row.get("tds_basis"),
            "form_15ca_ack_no": row.get("form_15ca_ack_no"),
            # §197. `or None` rather than `or ""`: an empty string is a
            # certificate number nobody holds, and `is_lower_deduction` is
            # exactly "a number is present" — the same reading
            # services/tds_register_service.py has taken since migration 359.
            "certificate_no": row.get("tds_certificate_no") or None,
            "journal_entry_id": row.get("journal_entry_id"),
        }
    return {
        "id": row["id"], "kind": "advance", "vendor_id": row.get("vendor_id"),
        "section": row.get("tds_section") or "",
        "on_date": str(row.get("payment_date") or ""),
        "doc_no": row.get("payment_no") or row["id"],
        "narration": f"Advance to vendor — Payment {row.get('payment_no') or row['id']}",
        "base_paise": int(row.get("tds_base_paise") or 0),
        "total_paise": int(row.get("amount_paise") or 0),
        "tds_paise": int(row.get("tds_paise") or 0),
        "rate_bps": int(row.get("tds_rate_bps") or 0),
        "surcharge_paise": int(row.get("tds_surcharge_paise") or 0),
        "cess_paise": int(row.get("tds_cess_paise") or 0),
        "nature": row.get("tds_nature_of_income"),
        "basis": row.get("tds_basis"),
        "form_15ca_ack_no": None,
        "certificate_no": row.get("tds_certificate_no") or None,
        "journal_entry_id": row.get("journal_entry_id"),
    }


def _vendors_by_id(db, firm_id: str, vendor_ids: set[str]) -> dict[str, dict]:
    if not vendor_ids:
        return {}
    # residential_status decides whether a deduction belongs in 26Q at all —
    # Rule 31A(4), migration 308.
    # country_of_residence and tax_identification_number are 27Q's own
    # identifiers for a payee with no Indian PAN (migration 308) — read here
    # rather than joined at filing time, so one query serves both returns.
    rows = (db.table("vendors")
            .select("id, name, pan, residential_status, country_of_residence, "
                    "tax_identification_number")
            .eq("firm_id", firm_id).in_("id", list(vendor_ids)).execute().data) or []
    return {v["id"]: v for v in rows}


def _deposited_challans(db, firm_id: str, client_id: str, fy: str, quarter: str) -> list[dict]:
    return fetch_all(lambda: db.table("tds_challans").select("*")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("financial_year", fy).eq("quarter", quarter))


def _section_labels(fy: str, sections) -> tuple[dict[str, str], list[str]]:
    """{stored 1961 code -> the code the PERIOD's own Act names}, and the gaps.

    THE FORM NUMBER WAS TRANSLATED AND THE SECTIONS WERE NOT (TDS-17). A FY
    2026-27 26Q came back as `"form": "140"` — right, because the Income-tax
    Act 2025 renumbered the statements — with every deductee line still citing
    `194J`, which that Act does not contain. `domain/tds/vocabulary.py:312`
    says in as many words that it exists to prevent exactly this.

    TRANSLATED AT THE EMISSION DICT, NOWHERE ELSE. `d.section` is the stored
    ROUTING key: it came off `tds_deductions.tds_section`, it groups the
    challan match (`challan_mapping.parent_of`), and it is what
    `section_rates` is keyed on. Rekeying any of those is the thing CLAUDE.md
    forbids — and it would break the challan match outright, because a challan
    records what somebody typed and says "194J" in every period.

    The 1961 code travels WITH the label as `section_1961` on each deductee,
    because §393(1) has no reverse: the whole 194-series collapses into it, so
    a reader given only the label cannot get back to the section that produced
    it. Anything reading the payload back to route or reconcile must use that
    field. (`lib/data/tds.ts` writes the payload into `tds_returns.fvu_json`,
    so both land in a JSONB snapshot; the routing keys beside the labels are
    what keep it usable.)

    A section the 2025 Act has no recorded code for is NOT guessed: the stored
    code is kept and the omission is named in `statutory_gaps`, beside the
    payment-code gap the vocabulary already reports.
    """
    vocab = _vocabulary.vocabulary_for(fy)
    labels: dict[str, str] = {}
    gaps: list[str] = []
    seen = {str(c or "").strip() for c in sections}
    for code in sorted(c for c in seen if c):
        try:
            labels[code] = vocab.section(code)
        except _vocabulary.VocabularyError:
            labels[code] = code
            gaps.append(
                f"No {vocab.act_name} section code is recorded for {code}. The "
                f"line is shown under its Income-tax Act 1961 section; check it "
                f"against the notified correspondence before filing.")
    return labels, gaps


def _payment_codes(fy: str, deductees) -> tuple[list[dict], list[str]]:
    """The s.393 payment code for each deductee row, and what the statement
    must say about the rows that have none (TDS-31).

    ONE ANSWER PER ROW, in row order, as the three keys the emission dict
    carries: `payment_code`, `payment_code_gap` and `payment_code_assumption`.
    ALWAYS PRESENT AND NULL WHERE NOTHING APPLIES — a 1961-Act period carries
    no payment code at all, and an absent key and a null key read the same to
    a screen and are different bugs (`journal_source`'s discipline): null is
    "this period asks for none", absent would be "this build did not say".

    `d.section` is the STORED routing key and is what the code is asked of,
    never the label the row is printed under — s.393(1) has no reverse, so a
    code keyed on the label could not tell 194C from 194J. The deductee's PAN
    travels with it because s.194C's two rows split on the contractor's class.
    See `domain/tds/deductee_payment_code.py`.
    """
    answers = [_deductee_payment_code.for_line(fy, d.section,
                                               deductee_pan=d.deductee_pan)
               for d in deductees]
    per_row = [{"payment_code": a.code,
                "payment_code_gap": a.gap,
                "payment_code_assumption": a.assumption} for a in answers]
    notes = _deductee_payment_code.statement_notes(
        [(d.section, a) for d, a in zip(deductees, answers, strict=False)])
    return per_row, notes


def _accumulate_note_totals(rows, bucket: dict) -> None:
    """Sum the ISSUED, undeleted notes' taxable value per bill.

    The one place the "which notes count" rule lives for both note kinds — a
    draft note has reversed nothing and a soft-deleted one was a mistake, and
    spelling that twice is how the two sides come to disagree about a draft.
    """
    for r in rows:
        if (r.get("status") or "") != "issued" or r.get("deleted_at"):
            continue
        k = r.get("purchase_bill_id")
        bucket[k] = bucket.get(k, 0) + int(r.get("taxable_amount_paise") or 0)


def _credit_moved_gaps(db, firm_id: str, events: list[dict], mapping: challan_mapping.Mapping) -> list[str]:
    """A purchase return, or a §34(3) undercharge note, against a bill in this
    quarter that already withheld (PUR-23 ≡ TDS-32).

    The module docstring used to end "purchase debit/credit notes never adjust
    tds_paise in this codebase ... so a purchase return after TDS was already
    deducted and deposited is not modelled here either". That is still true of
    the FIGURES and deliberately so — domain/tds/purchase_return sets out why
    the statute leaves two lawful answers, and which applies turns on whether
    the tax has been paid over, which this return's own challan match says
    (POST-A-271). What was not acceptable is that it was also
    SILENT: the deductee row reported a credit that had been partly reversed,
    the vendor's 26AS showed income they did not earn, and the CA assembling
    the quarter had no way to know.

    Read by BILL ID rather than by date. The note that matters most is the one
    raised in a LATER quarter against this quarter's bill, and a date-ranged
    query is exactly the one that misses it. What crosses the wire is
    proportional to the notes, not to the ledger.

    An advance carries no notes — a note is raised against a BILL — so only
    bill events are asked about.
    """
    bills = {e["id"]: e for e in events
             if e.get("kind") == "bill" and int(e.get("tds_paise") or 0) > 0}
    if not bills:
        return []
    ids = list(bills)
    returned: dict[str, int] = {}
    increased: dict[str, int] = {}
    # THE TABLE NAME IS A LITERAL AT EACH READ, and that is not style.
    # `tests/test_backend_columns_exist_pg.py` can only check a column against
    # the real schema when it can READ the table name — `db.table(table)` with
    # a variable is invisible to it, and the first draft of this function put
    # both reads inside one `for table, bucket in (...)` loop, which took ten
    # column references out of that check's coverage and tripped its
    # unreadable-reference budget. Two spellings of the same three lines is the
    # price of keeping the coverage; the SHAPE is shared in `_note_totals`
    # below, so the rule itself still exists once.
    for i in range(0, len(ids), 200):
        chunk = ids[i:i + 200]
        try:
            rows = fetch_all(lambda chunk=chunk: db.table("debit_notes")
                    .select("id, purchase_bill_id, taxable_amount_paise, status, deleted_at")
                    .eq("firm_id", firm_id).in_("purchase_bill_id", chunk))
        except Exception as e:                                  # noqa: BLE001
            # A gap that cannot be measured is reported as absent rather than
            # failing the whole return build. The quarter still assembles; what
            # is lost is one warning, and the log says so.
            _logger.error("could not read debit_notes against this quarter's bills: %s", e)
            rows = []
        _accumulate_note_totals(rows, returned)

        try:
            rows = fetch_all(lambda chunk=chunk: db.table("purchase_credit_notes")
                    .select("id, purchase_bill_id, taxable_amount_paise, status, deleted_at")
                    .eq("firm_id", firm_id).in_("purchase_bill_id", chunk))
        except Exception as e:                                  # noqa: BLE001
            _logger.error("could not read purchase_credit_notes against this "
                          "quarter's bills: %s", e)
            rows = []
        _accumulate_note_totals(rows, increased)

    out: list[str] = []
    for bill_id, e in bills.items():
        # WHETHER THE TAX HAS GONE IS THE STATEMENT'S OWN CHALLAN MATCH, which this return has already made: the note
        # used to be handed no deposit fact at all and so always read "not yet deposited" (POST-A-271), the recompute
        # answer on a bill whose tax the quarter's challans had paid.
        deducted_on = challan_mapping.as_date(e.get("on_date"))
        position = None
        if deducted_on is not None:
            parts, refused = challan_mapping.dated_parts(mapping.for_deduction(bill_id), deducted_on)
            position = deposit_position(int(e.get("tds_paise") or 0), parts, refused)
        moved = credit_moved_after_deduction(
            bill_no=e.get("doc_no"), section=e.get("section"),
            credited_paise=int(e.get("base_paise") or 0),
            tds_paise=int(e.get("tds_paise") or 0),
            returned_taxable_paise=returned.get(bill_id, 0),
            increased_taxable_paise=increased.get(bill_id, 0),
            position=position)
        if moved:
            out.append(moved.sentence)
    return sorted(out)


def tds_26q_from_books(
    db, firm_id: str, client_id: str, fy: str, quarter: str,
    tan: str, deductor_name: str, deductor_pan: str, deductor_address: str,
) -> dict:
    """Build Form 26Q (non-salary TDS) from posted books, and reconcile the
    total TDS deducted to the "TDS Payable" GL account.

    TWO KINDS OF POSTED DOCUMENT WITHHOLD, not one. §194 charges at the time of
    credit "or at the time of payment thereof, whichever is EARLIER", so a
    vendor ADVANCE is a charging event in its own right (migration 358) and its
    deduction posts to the same control account and carries the same challan
    obligation. Reading only `purchase_bills` left a real deduction off the
    statement it belongs on while the GL and the register both held it — and
    then the reconciliation failed, because the GL movement included it.
    """
    start, end, due_date = quarter_dates(fy, quarter)

    # THE DEDUCTIONS TYPED ON THE TDS SCREEN ARE DEDUCTIONS TOO (POST-A-078), and the ones recorded for this statement are carried as deductee rows.
    typed_rows = _typed_deductions_in_quarter(db, firm_id, client_id, start, end)
    typed_left = [r for r in typed_rows if not _on_this_statement(r)]

    events = (
        [_as_deduction_event(b, kind="bill")
         for b in _posted_vendor_tds_bills(db, firm_id, client_id, start, end)]
        + [_as_deduction_event(p, kind="advance")
           for p in _withholding_advances(db, firm_id, client_id, start, end)
           # 26Q reports DEDUCTIONS. An advance below its section's threshold
           # counts toward the year's aggregate and is not one — the same
           # asymmetry the register applies (services/tds_register_service.py).
           if int(p.get("tds_paise") or 0) > 0]
        + [_as_deduction_event(r, kind="typed") for r in typed_rows if _on_this_statement(r)]
    )
    vendors = _vendors_by_id(db, firm_id, {e["vendor_id"] for e in events if e.get("vendor_id")})

    # A NON-RESIDENT PAYEE IS NOT A 26Q DEDUCTEE. Rule 31A(4)(a) gives 26Q the
    # non-salary payments to residents; (b) gives 27Q the payments to
    # non-residents. Before migration 308 nothing recorded the difference, so
    # every deduction swept into 26Q — including a foreign remittance, which is
    # a wrong return rather than a missing one.
    #
    # Excluded BEFORE the challan mapping and the journal-id list, not filtered
    # out of the deductees afterwards, so the mapping, the books total and the
    # GL movement are all computed over the same set of bills and the
    # reconciliation still means what it says.
    #
    # Reported, never silent: a total that quietly drops between one quarter
    # and the next is exactly the kind of thing nobody notices until a notice
    # arrives.
    #
    # BILLS AND ADVANCES ONLY in that note. It sends the CA to the 27Q built
    # from the books, which reads bills and advances and nothing else, so a
    # typed row whose supplier is now recorded as non-resident is left out with
    # the typed deductions instead (`excluded_typed`), in a sentence that says
    # the 27Q built from the books does not carry it.
    def _now_non_resident(e: dict) -> bool:
        return is_non_resident((vendors.get(e.get("vendor_id")) or {}).get("residential_status"))

    excluded_non_resident = [e for e in events if e["kind"] != "typed" and _now_non_resident(e)]
    typed_non_resident_ids = {e["id"] for e in events if e["kind"] == "typed" and _now_non_resident(e)}
    typed_non_resident = [r for r in typed_rows if r["id"] in typed_non_resident_ids]
    excluded_ids = {e["id"] for e in excluded_non_resident} | typed_non_resident_ids
    if excluded_ids:
        events = [e for e in events if e["id"] not in excluded_ids]

    # Non-salary challans only — a firm's TDS Payable challan for section 192
    # (salary) belongs to 24Q, not 26Q; excluded by section, defensively, even
    # though no current UI path creates a 192 challan via this table's normal
    # 26Q-facing flow.
    challans = [c for c in _deposited_challans(db, firm_id, client_id, fy, quarter) if (c.get("section") or "") != "192"]

    # WHICH CHALLAN PAID WHICH DEDUCTION — domain/tds/challan_mapping.py, which
    # carries the reasoning and the citations.
    #
    # This used to be two separate wrong answers. The CIN on a deductee row was
    # `next(c for c in challans if section matches)` — the FIRST challan for the
    # section, in an id order arbitrary with respect to time — and Rule 30(2)
    # gives a quarter THREE monthly deposits all under the same section, so
    # every June deductee carried April's BSR code and serial. And the deposited
    # column was the section's whole quarterly deposit apportioned across the
    # section's bills by weight, so a bill fully deposited on 7 May read as
    # partly deposited whenever the QUARTER was short. A proportion is not an
    # answer to "has this vendor's tax been paid".
    #
    # It is filled FIFO by date, and grouped by PARENT section because a challan
    # records what somebody typed and a CA types "194J" whichever limb the bill
    # was under — the rule CLAUDE.md states for the 2025-Act fork, applied to a
    # clause key.
    mapping = challan_mapping.assign(events, challans, fy=fy)

    # A typed row that names a supplier with a bill or an advance of the same day and amount on this statement is named (POST-A-078).
    typed_events = [e for e in events if e["kind"] == "typed"]
    mirror_gaps = _mark_mirrors(typed_events, [e for e in events if e["kind"] != "typed"], vendors)

    deductees: list[TDSDeducteeRecord] = []
    recorded_by: list[str] = []
    for e in events:
        vendor = vendors.get(e.get("vendor_id"), {})
        assigned = mapping.for_deduction(e["id"])
        matching_challan = assigned.challan
        if e["section"] != "192":
            recorded_by.append({"bill": "purchase_bill", "advance": "advance", "typed": "tds_register"}[e["kind"]])
        deductees.append(TDSDeducteeRecord(
            # A supplier's own name and PAN, as for its bills; a typed row that names none is the payee it recorded (POST-A-078).
            deductee_name=vendor.get("name") or e.get("deductee_name") or "Unknown Vendor",
            deductee_pan=(vendor.get("pan") or e.get("deductee_pan") or "PANNOTAVBL").strip().upper() or "PANNOTAVBL",
            section=e["section"],
            nature_of_payment=e["narration"],
            payment_date=e["on_date"],
            payment_amount_paise=e["base_paise"],
            tds_rate_pct=e["rate_bps"] / 100,
            tds_deducted_paise=e["tds_paise"],
            tds_deposited_paise=assigned.deposited_paise,
            challan_no=(matching_challan or {}).get("challan_no") or "",
            bsr_code=(matching_challan or {}).get("bsr_code") or "",
            challan_date=str((matching_challan or {}).get("payment_date") or ""),
            # The two fields TDSDeducteeRecord has carried since migration 037
            # and nothing ever set (PUR-07).
            is_lower_deduction=bool(e.get("certificate_no")),
            lower_deduction_cert=e.get("certificate_no"),
        ))

    payload = _computer.compute_26q(
        tan=tan, deductor_name=deductor_name, deductor_pan=deductor_pan,
        deductor_address=deductor_address, financial_year=fy, quarter=quarter,
        deductees=deductees, challans=[dict(c) for c in challans],
    )
    # The typed deductions this statement leaves out (POST-A-078) are labelled by the same call as the deductees', so a section the period's Act has no code for is
    # named once, in the same gap.
    _sec_labels, _sec_gaps = _section_labels(fy, [d.section for d in deductees] + [r.get("section") for r in typed_left + typed_non_resident])
    # TDS-31: the numeric payment code each row of a 2025-Act statement
    # carries, asked of the rows the PAYLOAD holds (26Q drops §192 rows).
    _pay_rows, _pay_notes = _payment_codes(fy, payload.deductees)

    tds_payable_id = _find_account_by_exact_name(db, firm_id, client_id, "TDS Payable")
    journal_ids = [e["journal_entry_id"] for e in events if e.get("journal_entry_id")]
    gl_paise = _gl_movement_for_entries(db, firm_id, client_id, tds_payable_id, journal_ids)
    # THE TIE-OUT IS THE DOCUMENTS' (POST-A-078). Nothing records which journal, if any, carries a typed deduction, so the books side of the tie-out is the bills and
    # advances on the statement, and the typed tax is reported beside it. Adding it in would compare it with journals this reads none of (a journal passed by hand
    # for a typed row is not among `journal_ids`), so the typed tax would read as a difference whether or not a journal carries it.
    typed_paise = sum(e["tds_paise"] for e in typed_events if e["section"] != "192")
    books_paise = payload.total_tds_deducted_paise - typed_paise
    matched = tds_payable_id is not None and books_paise == gl_paise

    result = {
        "period": {"financial_year": fy, "quarter": quarter, "start": start, "end": end, "due_date": due_date},
        # Form 140 from FY 2026-27, still 26Q for earlier periods — including a
        # belated or revised one filed today. See domain/tds/vocabulary.py.
        "form": _vocabulary.statement_form(_vocabulary.RESIDENT_NON_SALARY, fy_label=fy),
        "act": _vocabulary.vocabulary_for(fy).act_name,
        "statutory_gaps": ([g.note for g in _vocabulary.vocabulary_for(fy).gaps()]
                           + _pay_notes + _sec_gaps
                           + _credit_moved_gaps(db, firm_id, events, mapping)
                           + mirror_gaps),
        "source": "posted_purchase_bills_and_advances_and_typed_deductions",
        "tan": payload.tan,
        "deductor_name": payload.deductor_name,
        "deductor_pan": payload.deductor_pan,
        "deductor_address": payload.deductor_address,
        "financial_year": payload.financial_year,
        "quarter": payload.quarter,
        "quarter_end_date": payload.quarter_end_date,
        "total_payment_paise": payload.total_payment_paise,
        "total_tds_deducted_paise": payload.total_tds_deducted_paise,
        "total_tds_deposited_paise": payload.total_tds_deposited_paise,
        "deductee_count": len(payload.deductees),
        "deductees": [
            {
                "deductee_name": d.deductee_name, "deductee_pan": d.deductee_pan,
                # The section the PERIOD's own Act names, with the stored 1961
                # routing key beside it — see _section_labels (TDS-17).
                "section": _sec_labels.get(d.section, d.section),
                "section_1961": d.section,
                # TDS-31: the s.393 payment code (Form 138/140/144 rows),
                # `payment_code` / `payment_code_gap` / `payment_code_assumption`
                # — always present, null where a 1961-Act period asks for none.
                **_pc,
                "nature_of_payment": d.nature_of_payment,
                "payment_date": d.payment_date, "payment_amount_paise": d.payment_amount_paise,
                "tds_rate_pct": d.tds_rate_pct, "tds_deducted_paise": d.tds_deducted_paise,
                "tds_deposited_paise": d.tds_deposited_paise, "challan_no": d.challan_no,
                "bsr_code": d.bsr_code, "challan_date": d.challan_date,
                # §197. The certificate number travels with the row rather
                # than only the lowered rate, because a rate below the
                # section's has two lawful explanations and the figures cannot
                # tell them apart — TRACES reads an unexplained one as a short
                # deduction and raises a §201(1)/§201(1A) demand.
                "is_lower_deduction": d.is_lower_deduction,
                "lower_deduction_cert": d.lower_deduction_cert,
                # What recorded the deduction: a purchase bill, an advance, or the TDS register (typed on the TDS screen, carried by no journal the product records; POST-A-078).
                "recorded_by": _by,
            }
            for d, _pc, _by in zip(payload.deductees, _pay_rows, recorded_by, strict=True)
        ],
        "challans": payload.challans,
        # WHAT THE CHALLAN MAPPING COULD NOT SETTLE. Not a validation error —
        # the return is assembled and the figures are right — but a deductee
        # left without a challan is a 26AS entry that will read 'U' (unmatched)
        # and a §201(1A) exposure the CA has to see BEFORE filing, not after a
        # notice. domain/tds/challan_mapping.py words them.
        "challan_gaps": mapping.gaps,
        # What was deliberately left out of this return, and where it went.
        # This used to end "…this codebase does not compute the s.195 rate they
        # would need", which stopped being true when domain/tds/section_195.py
        # was written and stopped being an excuse when tds_27q_from_books was
        # (TDS-09). The exclusion is still reported: a total that quietly drops
        # between one quarter and the next is what nobody notices until a
        # notice arrives.
        "excluded_non_resident": {
            "bill_count": len(excluded_non_resident),
            "tds_paise": sum(int(e.get("tds_paise") or 0) for e in excluded_non_resident),
            "reason": "Payments to a non-resident are reported on Form 27Q "
                      "under Rule 31A(4)(b), not on 26Q. Build 27Q for the same "
                      "quarter to file them.",
            "bills": [
                {"id": e.get("id"), "bill_no": e.get("doc_no"), "kind": e.get("kind"),
                 "vendor_name": (vendors.get(e.get("vendor_id")) or {}).get("name"),
                 "section": e.get("section"),
                 "tds_paise": int(e.get("tds_paise") or 0)}
                for e in excluded_non_resident
            ],
        },
        # THE DEDUCTIONS TYPED ON THE TDS SCREEN THAT THE STATEMENT CARRIES (POST-A-078): their count, tax and each row, with a sentence that says they are
        # outside the tie-out below, because a screen saying "reconciled" over a total that holds them would read as a claim about all of it.
        "typed_on_statement": _typed_note(
            [{"id": e["id"], "deductee_name": d.deductee_name, "deductee_pan": d.deductee_pan, "section": e["section"],
              "transaction_date": e["on_date"], "payment_amount_paise": e["base_paise"], "tds_paise": e["tds_paise"]}
             for e, d in zip(events, deductees, strict=True) if e["kind"] == "typed" and e["section"] != "192"],
            _sec_labels, _typed_on_statement_reason(typed_events, fy)),
        # WHAT THE STATEMENT LEAVES OUT THAT THE REGISTER HOLDS: the typed deductions recorded for another statement, and those naming a supplier now recorded as
        # non-resident (which the 27Q built from the books does not carry either, and the sentence says so). Named with their count, tax and each row, like the
        # non-resident payments above, because a statement that is silent about them reads as a complete one.
        "excluded_typed": _typed_note(typed_left + typed_non_resident, _sec_labels,
                                      _excluded_typed_reason(typed_left, typed_non_resident, fy)),
        "validation_errors": payload.validation_errors,
        "warnings": payload.warnings,
        "reconciliation": {
            "books_paise": books_paise,
            "ledger_paise": gl_paise,
            "difference_paise": books_paise - gl_paise,
            "matched": matched,
            "account_found": tds_payable_id is not None,
            # The tax of the typed deductions on the statement, which no journal holds and the tie-out does not compare (POST-A-078).
            "typed_paise": typed_paise,
        },
        "ca_review_required": True,
    }
    result["keying_sheet"] = _keying_sheet.build(result)
    return result


def _finalized_payroll_runs(db, firm_id: str, client_id: str, start: str, end: str) -> list[dict]:
    # month is stored "YYYY-MM"; a quarter never spans a partial month, so a
    # plain string range on "YYYY-MM" (lexicographically monotonic) is exact.
    return fetch_all(lambda: privileged_for(db).table("payroll_runs").select("*")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .in_("status", list(_PAYROLL_POSTED))
            .gte("month", start[:7]).lte("month", end[:7]))


def _payroll_slips_for_runs(db, firm_id: str, run_ids: list[str]) -> list[dict]:
    if not run_ids:
        return []
    out: list[dict] = []
    for i in range(0, len(run_ids), 200):
        chunk = run_ids[i:i + 200]
        out.extend(fetch_all(lambda chunk=chunk: privileged_for(db).table("payroll_slips").select("*")
            .in_("run_id", chunk)))
    return out


def _employees_by_id(db, firm_id: str, employee_ids: set[str]) -> dict[str, dict]:
    if not employee_ids:
        return {}
    rows = (privileged_for(db).table("payroll_employees").select("id, name, pan")
            .eq("firm_id", firm_id).in_("id", list(employee_ids)).execute().data) or []
    return {e["id"]: e for e in rows}


def tds_27q_from_books(
    db, firm_id: str, client_id: str, fy: str, quarter: str,
    tan: str, deductor_name: str, deductor_pan: str, deductor_address: str,
) -> dict:
    """Build Form 27Q — payments to NON-RESIDENTS, Rule 31A(4)(b).

    WHY THIS EXISTS (TDS-09)

    §195 deductions were computed by domain/tds/section_195.py, registered in
    full — country, TIN, surcharge, cess, non-deduction reason — excluded from
    26Q BY NAME with a reason, and given a deadline on the compliance calendar.
    There was nothing to file them on. A client pays a Singapore consultant,
    the platform gets every part of it right, and then the CA rebuilds the
    statement by hand from the deduction list.

    THE SAME BOOKS AS 26Q, SPLIT ON RESIDENCY AND NOT ON SECTION. Rule 31A(4)
    routes by who the payee is, not by which provision charges: §195 is the
    ordinary case, but §194E (non-resident sportsmen), §194LB/§194LC (interest)
    and §196D (FII income) also charge non-residents and also report here.
    Reading the same posted documents 26Q reads — bills AND advances, since
    §195 charges at credit or payment whichever is earlier — is what keeps the
    two returns from disagreeing about a quarter.

    A NIL REMITTANCE IS A ROW, which is the shape difference from 26Q. An
    ordinary import from a supplier with no permanent establishment is business
    profits and not chargeable under §195 at all (*GE India Technology Centre
    (P) Ltd v. CIT* (2010) 327 ITR 456), so the right withholding is nil — and
    the remittance is still reported, with the basis the engine resolved on.
    `_withholding_advances` filters on `tds_base_paise` rather than `tds_paise`
    precisely so a nil advance survives to here.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    """
    start, end, due_date = quarter_dates(fy, quarter)

    events = (
        [_as_deduction_event(b, kind="bill")
         for b in _posted_vendor_tds_bills_including_nil_195(db, firm_id, client_id, start, end)]
        + [_as_deduction_event(p, kind="advance")
           for p in _withholding_advances(db, firm_id, client_id, start, end)]
    )
    vendors = _vendors_by_id(db, firm_id, {e["vendor_id"] for e in events if e.get("vendor_id")})
    events = [
        e for e in events
        if is_non_resident((vendors.get(e.get("vendor_id")) or {}).get("residential_status"))
    ]

    # §192 is salary and belongs on 24Q whoever the employee is; everything else
    # recorded for this quarter is available to this return. Excluded by section
    # defensively, exactly as 26Q does.
    challans = [c for c in _deposited_challans(db, firm_id, client_id, fy, quarter)
                if (c.get("section") or "") != "192"]

    mapping = challan_mapping.assign(events, challans, fy=fy)

    deductees: list[TDS27QDeducteeRecord] = []
    for e in events:
        vendor = vendors.get(e.get("vendor_id"), {})
        assigned = mapping.for_deduction(e["id"])
        c = assigned.challan or {}
        # Why nothing was withheld, where nothing was — the engine's own
        # sentence. `tds_basis` is what section_195.py resolved on
        # (not_chargeable / treaty / act / 206aa_floor), persisted on the
        # document precisely so a NIL can be told apart from an absence months
        # later. Worded the same way services/tds_register_service.py words it,
        # because two places describing one fact is how they start to differ.
        reason = None
        if e["tds_paise"] == 0:
            reason = (f"Nil withheld under section {e['section'] or '195'} — basis "
                      f"'{e.get('basis') or 'not recorded'}'.")
        deductees.append(TDS27QDeducteeRecord(
            deductee_name=vendor.get("name") or "Unknown Vendor",
            deductee_pan=(vendor.get("pan") or "PANNOTAVBL").strip().upper() or "PANNOTAVBL",
            section=e["section"],
            # The NATURE of the income, which is what §115A and Part II rate on
            # — not the kind of work, which is what the resident series asks.
            nature_of_payment=e.get("nature") or e["narration"],
            payment_date=e["on_date"],
            payment_amount_paise=e["base_paise"],
            tds_rate_pct=e["rate_bps"] / 100,
            tds_deducted_paise=e["tds_paise"],
            tds_deposited_paise=assigned.deposited_paise,
            challan_no=c.get("challan_no") or "",
            bsr_code=c.get("bsr_code") or "",
            challan_date=str(c.get("payment_date") or ""),
            country_of_residence=vendor.get("country_of_residence") or None,
            deductee_tin=vendor.get("tax_identification_number") or None,
            surcharge_paise=e["surcharge_paise"],
            cess_paise=e["cess_paise"],
            non_deduction_reason=reason,
            # NO §197 pair here, deliberately — TDS27QDeducteeRecord has no
            # columns for one and says why. `vendor_tds.resolve_withholding`
            # refuses to apply a certificate to a §195 payee and reports the
            # refusal, so `e["certificate_no"]` is None on every non-resident
            # bill by construction; reporting it would be a permanent False.
        ))

    payload = _computer.compute_27q(
        tan=tan, deductor_name=deductor_name, deductor_pan=deductor_pan,
        deductor_address=deductor_address, financial_year=fy, quarter=quarter,
        deductees=deductees, challans=[dict(c) for c in challans],
    )
    _sec_labels, _sec_gaps = _section_labels(fy, [d.section for d in deductees])
    # TDS-31: the numeric payment code each row of a 2025-Act statement
    # carries, asked of the rows the PAYLOAD holds (26Q drops §192 rows).
    _pay_rows, _pay_notes = _payment_codes(fy, payload.deductees)

    # THE SAME CONTROL ACCOUNT AS 26Q, and that is not an oversight. §195 tax
    # credits "TDS Payable" like every §194-series deduction — one liability,
    # one challan series (ITNS 281), two statements. So the reconciliation is
    # over THIS return's own documents' journals, which is what makes it mean
    # something when both returns exist for one quarter.
    tds_payable_id = _find_account_by_exact_name(db, firm_id, client_id, "TDS Payable")
    journal_ids = [e["journal_entry_id"] for e in events if e.get("journal_entry_id")]
    gl_paise = _gl_movement_for_entries(db, firm_id, client_id, tds_payable_id, journal_ids)
    books_paise = payload.total_tds_deducted_paise
    # A NIL REMITTANCE MOVES NO LEDGER, so a quarter of nothing but nils
    # reconciles at zero against zero and that is correct, not a coincidence.
    matched = tds_payable_id is not None and books_paise == gl_paise

    result = {
        "period": {"financial_year": fy, "quarter": quarter, "start": start, "end": end, "due_date": due_date},
        # Form 144 from FY 2026-27, still 27Q for earlier periods — including a
        # belated or revised one filed today. See domain/tds/vocabulary.py.
        "form": _vocabulary.statement_form(_vocabulary.NON_RESIDENT, fy_label=fy),
        "act": _vocabulary.vocabulary_for(fy).act_name,
        "statutory_gaps": ([g.note for g in _vocabulary.vocabulary_for(fy).gaps()]
                           + _pay_notes + _sec_gaps
                           + _credit_moved_gaps(db, firm_id, events, mapping)),
        "source": "posted_purchase_bills_and_advances",
        "tan": payload.tan,
        "deductor_name": payload.deductor_name,
        "deductor_pan": payload.deductor_pan,
        "deductor_address": payload.deductor_address,
        "financial_year": payload.financial_year,
        "quarter": payload.quarter,
        "quarter_end_date": payload.quarter_end_date,
        "total_payment_paise": payload.total_payment_paise,
        "total_tds_deducted_paise": payload.total_tds_deducted_paise,
        "total_tds_deposited_paise": payload.total_tds_deposited_paise,
        "total_surcharge_paise": payload.total_surcharge_paise,
        "total_cess_paise": payload.total_cess_paise,
        "nil_deduction_count": payload.nil_deduction_count,
        "deductee_count": len(payload.deductees),
        "deductees": [
            {
                "deductee_name": d.deductee_name, "deductee_pan": d.deductee_pan,
                # The section the PERIOD's own Act names, with the stored 1961
                # routing key beside it — see _section_labels (TDS-17).
                "section": _sec_labels.get(d.section, d.section),
                "section_1961": d.section,
                # TDS-31: the s.393 payment code (Form 138/140/144 rows),
                # `payment_code` / `payment_code_gap` / `payment_code_assumption`
                # — always present, null where a 1961-Act period asks for none.
                **_pc,
                "nature_of_payment": d.nature_of_payment,
                "payment_date": d.payment_date, "payment_amount_paise": d.payment_amount_paise,
                "tds_rate_pct": d.tds_rate_pct, "tds_deducted_paise": d.tds_deducted_paise,
                "tds_deposited_paise": d.tds_deposited_paise, "challan_no": d.challan_no,
                "bsr_code": d.bsr_code, "challan_date": d.challan_date,
                "country_of_residence": d.country_of_residence,
                "deductee_tin": d.deductee_tin,
                "surcharge_paise": d.surcharge_paise, "cess_paise": d.cess_paise,
                "non_deduction_reason": d.non_deduction_reason,
            }
            for d, _pc in zip(payload.deductees, _pay_rows, strict=False)
        ],
        "challans": payload.challans,
        "challan_gaps": mapping.gaps,
        "validation_errors": payload.validation_errors,
        "warnings": payload.warnings,
        "reconciliation": {
            "books_paise": books_paise,
            "ledger_paise": gl_paise,
            "difference_paise": books_paise - gl_paise,
            "account_found": tds_payable_id is not None,
            "matched": matched,
            "journal_entry_count": len(set(journal_ids)),
        },
    }
    result["keying_sheet"] = _keying_sheet.build(result)
    return result


def tds_24q_from_books(
    db, firm_id: str, client_id: str, fy: str, quarter: str,
    tan: str, deductor_name: str, deductor_pan: str, deductor_address: str,
) -> dict:
    """Build Form 24Q (salary TDS) from finalized payroll runs, and reconcile
    the total TDS deducted to the "TDS Payable - Salary" GL account."""
    start, end, due_date = quarter_dates(fy, quarter)

    runs = _finalized_payroll_runs(db, firm_id, client_id, start, end)
    run_ids = [r["id"] for r in runs]
    runs_by_id = {r["id"]: r for r in runs}
    slips = [s for s in _payroll_slips_for_runs(db, firm_id, run_ids) if int(s.get("tds_paise") or 0) > 0]
    employees = _employees_by_id(db, firm_id, {s["employee_id"] for s in slips if s.get("employee_id")})

    # Section 192 challans for the quarter (deposited salary TDS).
    challans = [c for c in _deposited_challans(db, firm_id, client_id, fy, quarter) if (c.get("section") or "") == "192"]

    # THE SAME DEFECT AS 26Q, IN ITS SALARY MIRROR, AND FIXED THE SAME WAY.
    # `matching_challan = challans[0]` stamped every slip in the quarter with
    # whichever §192 challan came back first, and the deposited column was the
    # quarter's whole deposit apportioned by weight — so April's fully-paid
    # employees read as partly paid whenever June was short. A quarter carries
    # three monthly deposits under Rule 30(2); the payroll MONTH is what says
    # which one paid a slip. See domain/tds/challan_mapping.py.
    slip_months = {}
    for s in slips:
        run = runs_by_id.get(s.get("run_id"), {})
        month = str(run.get("month") or "")
        # Representative payment date — last day of the payroll month; the run
        # header carries no per-slip payment date, and this is descriptive
        # only (the FY/quarter driving the return is the caller's own input).
        month_end = month or ""
        try:
            month_end = month_end_date(month)
        except (ValueError, IndexError) as unreadable:
            # A run's month that does not read keeps the raw month as its descriptive date (it drives no figure), and is reported (POST-A-021).
            capture_soft_failure(unreadable, operation="tds_return.run_month_unreadable", run_id=run.get("id"), slip_id=s.get("id"))
        slip_months[s["id"]] = (month, month_end)

    mapping = challan_mapping.assign(
        [{"id": s["id"], "section": "192",
          "on_date": slip_months[s["id"]][1],
          "doc_no": str(s.get("employee_id") or ""),
          "tds_paise": int(s.get("tds_paise") or 0)}
         for s in slips],
        challans, fy=fy)

    deductees: list[TDSDeducteeRecord] = []
    for s in slips:
        emp = employees.get(s.get("employee_id"), {})
        month, month_end = slip_months[s["id"]]
        gross = int(s.get("gross_paise") or 0)
        tds = int(s.get("tds_paise") or 0)
        assigned = mapping.for_deduction(s["id"])
        matching_challan = assigned.challan
        deductees.append(TDSDeducteeRecord(
            deductee_name=emp.get("name") or "Unknown Employee",
            deductee_pan=(emp.get("pan") or "PANNOTAVBL").strip().upper() or "PANNOTAVBL",
            section="192",
            nature_of_payment=f"Salary — {month}",
            payment_date=month_end,
            payment_amount_paise=gross,
            tds_rate_pct=round(tds * 100 / gross, 4) if gross > 0 else 0.0,
            tds_deducted_paise=tds,
            tds_deposited_paise=assigned.deposited_paise,
            challan_no=(matching_challan or {}).get("challan_no") or "",
            bsr_code=(matching_challan or {}).get("bsr_code") or "",
            challan_date=str((matching_challan or {}).get("payment_date") or ""),
            # DELIBERATELY NOT is_lower_deduction / lower_deduction_cert.
            # A 24Q row is an EMPLOYEE, built from payroll slips, and this
            # product holds no §197 certificate against §192 — the section is
            # absent from domain/tds/lower_deduction.SECTIONS_197, so a
            # certificate recorded against it would be refused rather than
            # applied. Setting the pair here would emit a hard False on every
            # salary row, which asserts "no certificate" where the truth is
            # "nobody asked". The fields keep their dataclass defaults and the
            # 24Q payload below does not carry them.
        ))

    payload = _computer.compute_24q(
        tan=tan, deductor_name=deductor_name, deductor_pan=deductor_pan,
        deductor_address=deductor_address, financial_year=fy, quarter=quarter,
        deductees=deductees, challans=[dict(c) for c in challans],
    )
    _sec_labels, _sec_gaps = _section_labels(fy, [d.section for d in deductees])
    # TDS-31: the numeric payment code each row of a 2025-Act statement
    # carries, asked of the rows the PAYLOAD holds (26Q drops §192 rows).
    _pay_rows, _pay_notes = _payment_codes(fy, payload.deductees)

    # The account the payroll accrual credited, found by the accrual's own resolver (POST-A-083): the exact name this read
    # used could not see a renamed account the accrual still found by its key, and the tie-out then said "no account".
    tds_salary_id, salary_account_name, salary_account_note = _salary_tds_account(db, firm_id, client_id)
    journal_ids = [r["journal_entry_id"] for r in runs if r.get("journal_entry_id")]
    gl_paise = _gl_movement_for_entries(db, firm_id, client_id, tds_salary_id, journal_ids)
    books_paise = payload.total_tds_deducted_paise
    matched = tds_salary_id is not None and books_paise == gl_paise

    result = {
        "period": {"financial_year": fy, "quarter": quarter, "start": start, "end": end, "due_date": due_date},
        # The PERIOD names the form, not a literal. FY 2026-27 onward this is
        # Form 138 under the Income-tax Act 2025; a belated FY 2025-26 return is
        # still 24Q, for ever. domain/tds/vocabulary.py carries both.
        "form": _vocabulary.statement_form(_vocabulary.SALARY, fy_label=fy),
        "act": _vocabulary.vocabulary_for(fy).act_name,
        # As on 26Q — see its own comment. A §192 deposit short by one month
        # leaves the employees of that month showing 'U' in their 26AS, and
        # they are the people most likely to ask about it.
        "challan_gaps": mapping.gaps,
        "statutory_gaps": ([g.note for g in _vocabulary.vocabulary_for(fy).gaps()]
                           + _pay_notes
                           # NOT _credit_moved_gaps: 24Q is SALARY (§192), built
                           # from payroll runs. A purchase note cannot reach it,
                           # and this builder has no bill events to ask about.
                           + _sec_gaps),
        "source": "finalized_payroll_runs",
        "tan": payload.tan,
        "deductor_name": payload.deductor_name,
        "deductor_pan": payload.deductor_pan,
        "deductor_address": payload.deductor_address,
        "financial_year": payload.financial_year,
        "quarter": payload.quarter,
        "quarter_end_date": payload.quarter_end_date,
        "total_salary_paise": payload.total_salary_paise,
        "total_tds_deducted_paise": payload.total_tds_deducted_paise,
        "total_tds_deposited_paise": payload.total_tds_deposited_paise,
        "deductee_count": len(payload.deductees),
        "deductees": [
            {
                "deductee_name": d.deductee_name, "deductee_pan": d.deductee_pan,
                # The section the PERIOD's own Act names, with the stored 1961
                # routing key beside it — see _section_labels (TDS-17).
                "section": _sec_labels.get(d.section, d.section),
                "section_1961": d.section,
                # TDS-31: the s.393 payment code (Form 138/140/144 rows),
                # `payment_code` / `payment_code_gap` / `payment_code_assumption`
                # — always present, null where a 1961-Act period asks for none.
                **_pc,
                "nature_of_payment": d.nature_of_payment,
                "payment_date": d.payment_date, "payment_amount_paise": d.payment_amount_paise,
                "tds_rate_pct": d.tds_rate_pct, "tds_deducted_paise": d.tds_deducted_paise,
                "tds_deposited_paise": d.tds_deposited_paise, "challan_no": d.challan_no,
                "bsr_code": d.bsr_code, "challan_date": d.challan_date,
            }
            for d, _pc in zip(payload.deductees, _pay_rows, strict=False)
        ],
        "challans": payload.challans,
        "validation_errors": payload.validation_errors,
        "warnings": payload.warnings,
        "reconciliation": {
            "books_paise": books_paise,
            "ledger_paise": gl_paise,
            "difference_paise": books_paise - gl_paise,
            "matched": matched,
            "account_found": tds_salary_id is not None,
            "account_name": salary_account_name,
            "account_note": salary_account_note,
        },
        "ca_review_required": True,
    }
    result["keying_sheet"] = _keying_sheet.build(result)
    return result
