"""Bringing a client's open bills over from a spreadsheet, in bulk (accounting-05).

WHAT WAS MISSING
    `routers/opening_documents` took ONE document per request, so a trading
    client with two hundred open invoices — which is a client with a Busy, Marg or
    Excel history and the commonest migration there is — was a week of typing, and
    most CAs would simply have skipped it and lost the dated ageing the whole
    breakup exists to give. The trial-balance import cannot help: it has no dates.

THIS MODULE IS THE RULE, AND IT IS A PLAN, NOT A WRITE
    `plan` takes the rows as typed, the client's parties and the documents that
    already exist, and says what each row IS: new, already recorded, or rejected
    with every reason at once. It reads nothing and writes nothing. The service
    fetches its inputs and writes what it said was new; the screen decides
    nothing. Everything about what an opening DOCUMENT may be is still
    `opening_documents.problem_with`, which this CALLS rather than restates — a
    second copy of "the amount must be what is still owed" is how an importer and
    the form beside it come to accept different things.

EVERY ROW IS JUDGED, AND A BAD ROW NAMES ITSELF
    All rows are validated before any is written, each bad row is returned with
    its row number and ALL of its problems (a file corrected one error at a time
    is a file uploaded nineteen times), and the good rows still land: a migration
    of three hundred documents must not fail because row 212 has a typo. That is
    "commit by named row" — the alternative, all or nothing, makes one bad
    customer name in a Busy export block the whole client.

A RE-UPLOAD CREATES NOTHING, AND THE KEY IS THE ONE THE DATABASE USES
    The same file uploaded twice is the normal way a CA fixes a missing customer:
    add the customer, upload again. So a document already recorded is reported as
    ALREADY RECORDED and skipped, never inserted again and never an error. What
    counts as "the same document" is exactly what each table's unique index says,
    because anything looser lets a duplicate through and anything stricter
    refuses a document the database would have taken:

      * a SALES invoice is one per (client, invoice number), exact — migration 209;
      * a PURCHASE bill is one per (client, vendor, number) compared without case
        or surrounding space — migration 313.

    The comparison is on the TOTAL the import wrote, never on what is outstanding
    now: a receipt allocated against an opening invoice since the first upload
    lowers `outstanding_paise` and must not turn the same file into a conflict.

    The same number with a DIFFERENT amount is rejected and says so, never
    overwritten: which of the two is right is the CA's answer, and "remove the
    recorded one first" is the way to make the file the correction. A number that
    is already an ORDINARY invoice or bill is rejected too, because an opening
    document is the breakup of a balance carried over from another system and an
    invoice raised here is a different thing that happens to share a number.

WHAT IT STILL DOES NOT DO
    It does not post, declare tax or withhold anything (`row_for` writes every tax
    field as nil), does not create a customer or a vendor that is missing — a
    party with no opening balance would make the reconciliation report the
    documents as MORE than the ledger carries, which is true and is named, not
    absorbed — and does not check the number against Rule 46(b): it is the other
    system's number.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable, Optional

from domain.accounting import opening_documents as od
from domain.money_text import rupees_paise
from domain.spreadsheet_cells import fold_name, parse_cell_date, why_not_a_date

#: A ceiling on one request. Bulk inserts are chunked below it, but a request that
#: carries tens of thousands of rows is a different job (an ERP migration), and
#: refusing it beats a request that outlives the proxy's patience halfway through
#: writing — which leaves exactly the half-imported client this exists to avoid.
MAX_ROWS = 5000

#: Said once for a row whose amount arrived as nothing. The rule behind it
#: (`opening_documents.problem_with`, "still owed") is about an amount that WAS
#: read and is nil or negative, and is deliberately not restated here.
AMOUNT_UNREADABLE_SENTENCE = (
    "The outstanding amount is blank or is not a rupee figure — write digits "
    "with an optional decimal point, for example 1,25,000.00, with no letters.")

NEW = "new"
ALREADY_RECORDED = "already_recorded"
REJECTED = "rejected"


@dataclass(frozen=True)
class ImportRow:
    """One row as the spreadsheet carried it.

    `row` is the number the person sees (the preview's own, so a sentence
    naming it can be found). Dates stay TEXT here: reading them is this module's
    job, and doing it in the browser would be a second implementation of it.
    """
    row: int
    party: str = ""
    party_gstin: Optional[str] = None
    document_no: str = ""
    document_date: str = ""
    due_date: Optional[str] = None
    outstanding_paise: Optional[int] = None
    notes: Optional[str] = None


@dataclass(frozen=True)
class Verdict:
    row: int
    document_no: str
    status: str
    problems: tuple[str, ...] = ()
    party_id: Optional[str] = None
    party_name: Optional[str] = None
    document_date: Optional[str] = None
    due_date: Optional[str] = None
    outstanding_paise: int = 0
    notes: Optional[str] = None
    #: The recorded document this row matched, when it matched one.
    existing_id: Optional[str] = None

    @property
    def sentence(self) -> str:
        who = f"Row {self.row}" + (f" ({self.document_no})" if self.document_no else "")
        return f"{who}: " + " ".join(self.problems)


def _r(paise: int) -> str:
    return f"₹{rupees_paise(paise)}"


def _read_dates(row: ImportRow) -> tuple[Optional[date], Optional[date], bool, list[str]]:
    """(document date, due date, whether the document date was present but unreadable,
    the sentences for whatever could not be read).

    Each sentence says which part was wrong: a two-digit year, a day that is not
    on the calendar, or text that is not a date (`why_not_a_date`).
    """
    problems: list[str] = []
    on = parse_cell_date(row.document_date)
    due_text = (row.due_date or "").strip()
    due = parse_cell_date(due_text) if due_text else None
    unreadable = bool((row.document_date or "").strip()) and on is None
    if unreadable:
        problems.append(f"The document date \"{row.document_date.strip()}\" is not "
                        f"a date: {why_not_a_date(row.document_date)}.")
    if due_text and due is None:
        problems.append(f"The due date \"{due_text}\" is not a date: "
                        f"{why_not_a_date(due_text)}.")
    return on, due, unreadable, problems


def _resolve_party(row: ImportRow, kind: str, parties: list[dict],
                   by_name: dict[str, list[dict]],
                   by_gstin: dict[str, list[dict]]) -> tuple[Optional[dict], Optional[str]]:
    """The one party this row names, or the reason it names none or several."""
    noun = "customer" if kind == od.RECEIVABLE else "vendor"
    name = (row.party or "").strip()
    gstin = (row.party_gstin or "").strip().upper()

    by_g: Optional[dict] = None
    if gstin:
        hits = by_gstin.get(gstin, [])
        if len(hits) > 1:
            return None, (f"More than one {noun} carries GSTIN {gstin}; "
                          f"record which one in the master first.")
        if not hits:
            return None, (f"No {noun} of this client has GSTIN {gstin}. Add the "
                          f"{noun}, or correct the GSTIN.")
        by_g = hits[0]

    if name:
        hits = by_name.get(fold_name(name), [])
        if len(hits) > 1:
            if by_g and any(h.get("id") == by_g.get("id") for h in hits):
                return by_g, None     # the GSTIN settles what the name could not
            return None, (f"\"{name}\" matches {len(hits)} {noun}s of this client "
                          f"with the same name. Give the party's GSTIN to say which.")
        if hits:
            if by_g and hits[0].get("id") != by_g.get("id"):
                return None, (f"\"{name}\" and GSTIN {gstin} belong to two different "
                              f"{noun}s. One of them is wrong.")
            return hits[0], None
        if by_g:
            return by_g, None         # the GSTIN is the stronger identifier
        return None, (f"No {noun} named \"{name}\" is recorded against this "
                      f"client. Add it first (with its opening balance), then "
                      f"upload the file again — the documents already recorded "
                      f"are skipped.")
    if by_g:
        return by_g, None
    return None, f"The {noun}'s name is required — it is what ties the document to a party."


def _key(kind: str, party_id: Optional[str], number: str) -> tuple:
    """What the database calls "the same document" — see the module docstring."""
    n = (number or "").strip()
    return (n,) if kind == od.RECEIVABLE else (party_id, n.lower())


def plan(kind: str, rows: Iterable[ImportRow], parties: list[dict],
         existing: list[dict]) -> list[Verdict]:
    """What each row is, in the order given.

    `parties` are the client's customers (or vendors): `id`, `name`, `gstin`.
    `existing` are the LIVE documents of that kind that could collide —
    `id`, the number column, the party column, `is_opening`, `total_paise` — and
    must include every document whose number appears in the file, opening or not.
    """
    rows = list(rows)
    if kind not in od.KINDS:
        raise ValueError(f"{kind!r} is not an opening document kind.")

    by_name: dict[str, list[dict]] = {}
    by_gstin: dict[str, list[dict]] = {}
    names: dict[str, str] = {}
    for p in parties:
        pid = p.get("id")
        if not pid:
            continue
        names[pid] = p.get("name") or pid
        if (p.get("name") or "").strip():
            by_name.setdefault(fold_name(p["name"]), []).append(p)
        g = (p.get("gstin") or "").strip().upper()
        if g:
            by_gstin.setdefault(g, []).append(p)

    number_col, party_col = od.NUMBER_COLUMN[kind], od.PARTY_COLUMN[kind]
    on_file: dict[tuple, dict] = {}
    for d in existing:
        on_file.setdefault(_key(kind, d.get(party_col), d.get(number_col) or ""), d)

    seen: dict[tuple, int] = {}
    out: list[Verdict] = []
    for r in rows:
        problems: list[str] = []
        number = (r.document_no or "").strip()

        party, party_problem = _resolve_party(r, kind, parties, by_name, by_gstin)
        if party_problem:
            problems.append(party_problem)

        # Dates are read HERE, once. A cell that is present and unreadable gets
        # its own sentence; the rule in `problem_with` is then asked with a
        # stand-in for that one field, so it does not say the same thing a
        # second time — the sentence already said it.
        on, due, date_unreadable, date_problems = _read_dates(r)
        problems.extend(date_problems)

        # An amount the browser could not read as a rupee figure arrives as None
        # (a cell reading "Rs. 1,234.50", a blank one from a caller that sent no
        # amount). It is NOT an amount of nil, and `problem_with` would read it
        # as one — "already settled, not carried over" — which sends a CA to a
        # document that was never settled. It has its own sentence, and the rule
        # is then asked with a stand-in for the field, as the date's is.
        amount_unreadable = r.outstanding_paise is None
        if amount_unreadable:
            problems.append(AMOUNT_UNREADABLE_SENTENCE)

        refusal = od.problem_with(
            kind=kind,
            party_id=(party or {}).get("id") or ("-" if party_problem else ""),
            document_no=number,
            document_date=(on.isoformat() if on else "2000-01-01" if date_unreadable else None),
            due_date=(due.isoformat() if due else None),
            outstanding_paise=(1 if amount_unreadable else r.outstanding_paise))
        problems.extend(refusal.reasons)

        pid = (party or {}).get("id")
        key = _key(kind, pid, number)
        status, existing_id = NEW, None
        if not problems and number:
            if key in seen:
                problems.append(f"The same document appears again in this file "
                                f"(already on row {seen[key]}). A document is one "
                                f"row; remove the repeat.")
            else:
                seen[key] = r.row

        if not problems:
            clash = on_file.get(key)
            if clash is not None:
                existing_id = clash.get("id")
                recorded = int(clash.get("total_paise") or 0)
                if not clash.get("is_opening"):
                    noun = "invoice" if kind == od.RECEIVABLE else "bill"
                    problems.append(
                        f"{number} is already an ordinary {noun} raised in this "
                        f"product, not an opening document. An opening document is "
                        f"the breakup of a balance carried over from another system "
                        f"and cannot share a number with one.")
                elif clash.get(party_col) != pid:
                    problems.append(
                        f"{number} is already recorded against "
                        f"{names.get(clash.get(party_col), 'another party')}. An "
                        f"invoice number is one per client.")
                elif recorded != int(r.outstanding_paise or 0):
                    problems.append(
                        f"{number} is already recorded with {_r(recorded)} open; the "
                        f"file says {_r(int(r.outstanding_paise or 0))}. Nothing is "
                        f"overwritten — remove the recorded document first if the "
                        f"file is the correction.")
                else:
                    status = ALREADY_RECORDED

        if problems:
            out.append(Verdict(row=r.row, document_no=number, status=REJECTED,
                               problems=tuple(problems), existing_id=existing_id))
            continue
        out.append(Verdict(
            row=r.row, document_no=number, status=status,
            party_id=pid, party_name=names.get(pid),
            document_date=on.isoformat() if on else None,
            due_date=due.isoformat() if due else None,
            outstanding_paise=int(r.outstanding_paise or 0),
            notes=(r.notes or "").strip() or None, existing_id=existing_id))
    return out


@dataclass(frozen=True)
class Summary:
    received: int
    new: int
    already_recorded: int
    rejected: int
    new_paise: int


def summarise(verdicts: Iterable[Verdict]) -> Summary:
    vs = list(verdicts)
    return Summary(
        received=len(vs),
        new=sum(1 for v in vs if v.status == NEW),
        already_recorded=sum(1 for v in vs if v.status == ALREADY_RECORDED),
        rejected=sum(1 for v in vs if v.status == REJECTED),
        new_paise=sum(v.outstanding_paise for v in vs if v.status == NEW))
