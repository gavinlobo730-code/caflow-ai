"""Bringing a bookkeeper's spreadsheet of journals, payments, receipts and contras
into the books, voucher by voucher (accounting-17).

WHAT WAS MISSING
    Bulk import existed for sales invoices, receipts, purchase bills and notes,
    for the catalogue and for payroll — and not for the vouchers a bookkeeper
    most often HAS in a spreadsheet: manual journals, vendor payments, contra and
    cash vouchers. Many small clients send the CA an Excel of payments and
    journals, and every line was typed again; a client coming from Busy or Excel
    brings exactly this file.

THIS MODULE IS THE RULE AND IT IS A PLAN
    `plan` takes the legs as typed, the client's chart of accounts and the entries
    that already carry a voucher number, and says what each VOUCHER is: new,
    already recorded, or rejected with every reason at once. It reads nothing and
    writes nothing. `services/voucher_import_service` fetches the inputs and posts
    what was called new — through `manual_journal_service.create`, which is
    `phase2_journal_service._create_journal`, the ONE posting kernel. There is no
    second write path here, and a guard asserts the service never touches
    `journal_entries` or `journal_lines` itself.

ONE LAYOUT, AND WHY THE SIMPLE ONE IS THE BROWSER'S EXPANSION
    A voucher is a set of LEGS that share a voucher number: one row per ledger
    line, a debit or a credit on each. A payment of ₹5,000 to a vendor from the
    bank is two legs. Bookkeepers also keep one-row-per-voucher sheets
    ("Dr account, Cr account, amount"); the browser turns each such row into its
    two legs before sending, so this module has ONE shape to judge, and a row of
    either layout is reported under the number the person sees.

WHAT IS CHECKED, AND NONE OF IT IS NEW
    Every leg has an account that is THIS client's (or the firm's, shared) and is
    active; exactly one of debit and credit; an amount that is an amount. Every
    voucher has at least two legs, balances to the paisa, and is for something.
    The date is read by `domain/spreadsheet_cells` — day first, and a two-digit
    year refused. The period is asked through the SAME two questions
    `manual_journal_service.create` asks (the firm's locked year, and a return
    covering the date having been filed), passed in as a callable so this module
    holds no database handle; it is asked only for a voucher going on the books
    now, because a draft is off-books and is checked when it is posted.

    Balance is the kernel's own rule, stated first so the CA reads "short by
    ₹250" beside the voucher rather than a database error: the kernel asserts it
    again and refuses an unbalanced entry whatever this said.

WHAT IT REFUSES BY NAME
    Sales, Purchase and Opening are not vouchers a spreadsheet can hand-make. A
    sales or purchase entry is a DOCUMENT — it carries the GST the return
    declares — and one typed here would put revenue or a cost in the ledger with
    nothing behind it; an opening balance has its own path and its own
    reconciliation. Each is refused with the sentence saying where it belongs.

A RE-UPLOAD POSTS NOTHING, AND THE KEY IS THE VOUCHER NUMBER
    The voucher number is the entry's `reference_no`, so it is what a CA cites and
    what the kernel dedupes on with the date. A voucher whose number is already on
    an entry of the same date, type and total is ALREADY RECORDED — skipped, not an
    error. The same number on anything else is REJECTED and says what it clashes
    with: the kernel would otherwise collapse an entry with the same date into the
    existing one without a word (it answers with the old entry's id), or post a
    second voucher under a number a CA believes is unique. A voucher that was
    posted and then REVERSED still holds its number — reposting it is a decision,
    and "use a new number" is how to say so.

WHAT IT DOES NOT DO
    It does not infer the type from the accounts (a Contra between a bank and a
    non-bank ledger is what the CA typed), does not touch cost centres or
    attachments (the editor takes those), and does not number anything: the number
    is the file's. Sequential voucher numbers are a separate piece of work.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Optional

from domain.money_text import rupees_paise
from domain.spreadsheet_cells import DATE_FORMAT_SENTENCE, fold_name, parse_cell_date

#: The legs one request may carry. A bigger file is split by the browser into
#: requests of a few vouchers each, so this is a ceiling on a stranger and not on
#: a CA.
MAX_LEGS = 5000

#: And the vouchers one request may post. Each posting is several database round
#: trips and the browser gives up on a request at 45 seconds without retrying, so
#: a request that posts hundreds would outlive its own caller halfway through and
#: leave the CA not knowing which half landed.
MAX_VOUCHERS = 100

NEW = "new"
ALREADY_RECORDED = "already_recorded"
REJECTED = "rejected"

#: What a spreadsheet may hand-make → the `entry_type` the kernel stores.
ALLOWED_TYPES = {
    "journal": "Journal", "payment": "Payment", "receipt": "Receipt", "contra": "Contra",
}

#: What it may not, and where it belongs. Said once.
REFUSED_TYPES = {
    "sales": ("A sales entry is a document, not a voucher: it carries the GST the "
              "return declares. Import it with the sales invoice importer."),
    "purchase": ("A purchase entry is a document, not a voucher: it carries the "
                 "input credit the return claims. Import it with the purchase bill "
                 "importer."),
    "opening": ("An opening balance has its own path and its own reconciliation — "
                "see the Opening Balances tab."),
}


@dataclass(frozen=True)
class Leg:
    """One spreadsheet line, as typed.

    `debit_paise` / `credit_paise`: 0 where the cell is blank, None where it holds
    something that is not an amount (so the row still arrives and is refused BY
    NUMBER, rather than vanishing on the way). `row` is the number the person saw.
    """
    row: int
    voucher_no: str = ""
    date: str = ""
    voucher_type: str = ""
    account: str = ""
    debit_paise: Optional[int] = 0
    credit_paise: Optional[int] = 0
    narration: Optional[str] = None
    line_narration: Optional[str] = None


@dataclass(frozen=True)
class VoucherVerdict:
    voucher_no: str
    rows: tuple[int, ...]
    status: str
    problems: tuple[str, ...] = ()
    entry_date: Optional[str] = None
    entry_type: Optional[str] = None
    narration: str = ""
    lines: tuple[dict, ...] = ()
    total_paise: int = 0
    existing_id: Optional[str] = None

    @property
    def sentence(self) -> str:
        rows = ", ".join(str(r) for r in self.rows)
        noun = "Row" if len(self.rows) == 1 else "Rows"
        who = f"Voucher {self.voucher_no}" if self.voucher_no else "Voucher"
        return f"{who} ({noun} {rows}): " + " ".join(self.problems)


def _r(paise: int) -> str:
    return f"₹{rupees_paise(paise)}"


def _index_accounts(accounts: Iterable[dict]):
    by_code: dict[str, list[dict]] = {}
    by_name: dict[str, list[dict]] = {}
    for a in accounts:
        code = (a.get("account_code") or "").strip().casefold()
        if code:
            by_code.setdefault(code, []).append(a)
        name = fold_name(a.get("account_name"))
        if name:
            by_name.setdefault(name, []).append(a)
    return by_code, by_name


def resolve_account(cell: str, by_code: dict, by_name: dict) -> tuple[Optional[dict], Optional[str]]:
    """The one ledger a cell names, or the reason it names none or several.

    A CODE wins over a name: a code is a deliberate identifier and a name is what
    a person calls it. If the cell is the code of one account and the exact name
    of another, the code is what was meant. A name that two accounts share is
    reported and never picked — posting to the wrong one of two "Bank" ledgers
    balances and is invisible until the bank reconciliation.
    """
    text = (cell or "").strip()
    if not text:
        return None, "The account is blank."
    hits = by_code.get(text.casefold(), [])
    if len(hits) > 1:
        return None, (f"More than one account has the code \"{text}\"; "
                      f"use the account's full name instead.")
    if not hits:
        hits = by_name.get(fold_name(text), [])
        if len(hits) > 1:
            return None, (f"\"{text}\" is the name of {len(hits)} accounts of this "
                          f"client's chart. Use the account's code to say which.")
    if not hits:
        return None, (f"\"{text}\" is not an account of this client's chart. Add the "
                      f"ledger first (the Chart of Accounts), then upload again — "
                      f"vouchers already recorded are skipped.")
    acct = hits[0]
    if acct.get("is_active") is False:
        return None, f"\"{text}\" is an inactive account; a voucher cannot post to it."
    return acct, None


def _normalise_type(raw: str) -> tuple[Optional[str], Optional[str]]:
    key = fold_name(raw)
    if key in ALLOWED_TYPES:
        return ALLOWED_TYPES[key], None
    if key in REFUSED_TYPES:
        return None, REFUSED_TYPES[key]
    if not key:
        return None, None
    return None, (f"\"{raw.strip()}\" is not a voucher type this import takes — "
                  f"Journal, Payment, Receipt or Contra.")


def plan(legs: Iterable[Leg], accounts: Iterable[dict],
         existing_by_reference: dict[str, list[dict]],
         *, period_problem: Optional[Callable[[str], Optional[str]]] = None,
         ) -> list[VoucherVerdict]:
    """What each voucher is, in order of first appearance.

    `accounts` — this client's chart plus the firm-level accounts it shares:
    `id`, `account_code`, `account_name`, `is_active`.
    `existing_by_reference` — reference_no → the live entries carrying it:
    `id`, `entry_date`, `entry_type`, `is_reversed`, `total_paise`.
    `period_problem` — ISO date → the sentence for a closed period, or None.
    Pass None for a DRAFT import: nothing goes on the books, so nothing is asked.
    """
    by_code, by_name = _index_accounts(accounts)

    groups: dict[str, list[Leg]] = {}
    for leg in legs:
        groups.setdefault((leg.voucher_no or "").strip(), []).append(leg)

    out: list[VoucherVerdict] = []
    for vno, group in groups.items():
        # Two legs expanded from ONE spreadsheet row share its number.
        rows = tuple(dict.fromkeys(l.row for l in group))
        problems: list[str] = []

        if not vno:
            out.append(VoucherVerdict(
                voucher_no="", rows=rows, status=REJECTED,
                problems=("The voucher number is blank. It is what ties the lines "
                          "of one voucher together and what a re-upload is "
                          "recognised by.",)))
            continue

        # ── date ──────────────────────────────────────────────────────────
        dates: dict[str, int] = {}
        for l in group:
            text = (l.date or "").strip()
            d = parse_cell_date(text)
            if d is None:
                problems.append(
                    f"Row {l.row}: the date \"{text}\" is not a date — "
                    f"{DATE_FORMAT_SENTENCE}." if text
                    else f"Row {l.row}: the date is blank.")
            else:
                dates.setdefault(d.isoformat(), l.row)
        if len(dates) > 1:
            problems.append("The lines of one voucher carry different dates ("
                            + ", ".join(sorted(dates)) + ") — a voucher is dated once.")
        entry_date = next(iter(dates)) if len(dates) == 1 else None

        # ── type ──────────────────────────────────────────────────────────
        # A line may leave the type blank when another line of the voucher states
        # it (a one-row-per-voucher sheet expands to two legs, but a journal sheet
        # often names the type once); a voucher no line gives a type to is refused.
        types: dict[str, int] = {}
        for l in group:
            raw = (l.voucher_type or "").strip()
            if not raw:
                continue
            t, why = _normalise_type(raw)
            if why:
                problems.append(f"Row {l.row}: {why}")
            else:
                types.setdefault(t, l.row)
        if len(types) > 1:
            problems.append("The lines of one voucher carry different types ("
                            + ", ".join(sorted(types)) + ").")
        elif not types and not any((l.voucher_type or "").strip() for l in group):
            problems.append("The voucher type is blank — Journal, Payment, "
                            "Receipt or Contra.")
        entry_type = next(iter(types)) if len(types) == 1 else None

        # ── legs ──────────────────────────────────────────────────────────
        lines: list[dict] = []
        debit = credit = 0
        for l in group:
            acct, why = resolve_account(l.account, by_code, by_name)
            if why:
                problems.append(f"Row {l.row}: {why}")
            d, c = l.debit_paise, l.credit_paise
            if d is None:
                problems.append(f"Row {l.row}: the debit is not an amount.")
            if c is None:
                problems.append(f"Row {l.row}: the credit is not an amount.")
            if d is None or c is None:
                continue
            if d < 0 or c < 0:
                problems.append(f"Row {l.row}: an amount cannot be negative — put "
                                f"it on the other side instead.")
                continue
            if d > 0 and c > 0:
                problems.append(f"Row {l.row}: a line is a debit or a credit, not both.")
                continue
            if d == 0 and c == 0:
                problems.append(f"Row {l.row}: the line has no amount.")
                continue
            debit += d
            credit += c
            if acct is not None:
                lines.append({
                    "account_id": acct["id"],
                    "debit_paise": d, "credit_paise": c,
                    "narration": (l.line_narration or "").strip(),
                })

        if len(group) < 2:
            problems.append("A voucher needs at least two lines — a debit and a credit.")
        elif debit != credit:
            short = abs(debit - credit)
            problems.append(
                f"The voucher does not balance: debits {_r(debit)}, credits "
                f"{_r(credit)} — {'credits' if debit > credit else 'debits'} are "
                f"short by {_r(short)}.")

        narration = next(((l.narration or "").strip() for l in group
                          if (l.narration or "").strip()), "")

        # ── period ────────────────────────────────────────────────────────
        if entry_date and period_problem is not None:
            why = period_problem(entry_date)
            if why:
                problems.append(f"{entry_date} is in a closed period: {why}")

        # ── already on the books? ─────────────────────────────────────────
        status, existing_id = NEW, None
        if not problems:
            for e in existing_by_reference.get(vno, []):
                existing_id = e.get("id")
                if e.get("is_reversed"):
                    problems.append(
                        f"{vno} was posted and then reversed, and a reversed voucher "
                        f"still holds its number. Use a new number to post it again.")
                elif (str(e.get("entry_date") or "")[:10] == entry_date
                      and e.get("entry_type") == entry_type
                      and int(e.get("total_paise") or 0) == debit):
                    status = ALREADY_RECORDED
                else:
                    problems.append(
                        f"{vno} is already on an entry dated "
                        f"{str(e.get('entry_date') or '')[:10]} "
                        f"({e.get('entry_type')}, {_r(int(e.get('total_paise') or 0))}); "
                        f"this voucher is dated {entry_date} "
                        f"({entry_type}, {_r(debit)}). Nothing is overwritten — use "
                        f"a different voucher number.")
                break

        # A one-row-per-voucher sheet is expanded to two legs that share a row, so
        # a bad cell on it is found on both; said once.
        problems = list(dict.fromkeys(problems))
        if problems:
            out.append(VoucherVerdict(voucher_no=vno, rows=rows, status=REJECTED,
                                      problems=tuple(problems), existing_id=existing_id))
            continue
        out.append(VoucherVerdict(
            voucher_no=vno, rows=rows, status=status, entry_date=entry_date,
            entry_type=entry_type, narration=narration, lines=tuple(lines),
            total_paise=debit, existing_id=existing_id))
    return out


@dataclass(frozen=True)
class Summary:
    vouchers: int
    new: int
    already_recorded: int
    rejected: int
    new_paise: int


def summarise(verdicts: Iterable[VoucherVerdict]) -> Summary:
    vs = list(verdicts)
    return Summary(
        vouchers=len(vs),
        new=sum(1 for v in vs if v.status == NEW),
        already_recorded=sum(1 for v in vs if v.status == ALREADY_RECORDED),
        rejected=sum(1 for v in vs if v.status == REJECTED),
        new_paise=sum(v.total_paise for v in vs if v.status == NEW))
