"""The bill-wise breakup of an opening balance (ACC-14).

WHAT THIS IS FOR
    `opening_balance_service` brings a client's opening position into the ledger
    as three aggregates — Trade Receivables, Trade Payables and each bank. That
    is the right shape for the GENERAL LEDGER and the wrong shape for everything
    else a CA needs on day one, because ageing is per document: every AR/AP
    ageing screen and the Schedule III ageing note (MCA G.S.R. 207(E) of
    24-03-2021) bucket by the DUE DATE of each open document. A control-account
    total has no dates, so the whole opening receivable ages to nothing.

    An opening document supplies those dates. It is an ordinary row in
    `client_sales_invoices` / `purchase_bills` carrying the OLD system's own
    document number, so a receipt allocates against it, a statement lists it and
    the bank match queue offers it, all unchanged.

WHAT IT IS NOT
    It posts NO journal. `customers.opening_balance_paise` stays the single
    source of the ledger's AR leg — see migration 391's header for why moving
    that is a larger change than it looks. So the documents must ADD UP to the
    party's opening balance, and where they do not the difference is NAMED
    rather than absorbed (`reconcile` below). An ageing schedule that does not
    foot to its own control account is worse than either figure on its own.

    And it declares NO TAX. `taxable_amount_paise`, the three GST heads and
    `total_gst_paise` are all zero; `total_paise` is simply what is still owed.
    The tax on that supply was charged, collected and declared in the system the
    client is migrating from — writing it here would state a figure this
    client's own returns must never repeat, and the only figure ageing needs is
    what is outstanding.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

#: A sales opening document and a purchase one, named so a caller cannot pass
#: the wrong one by position.
RECEIVABLE = "receivable"
PAYABLE = "payable"
KINDS = (RECEIVABLE, PAYABLE)

#: What a document of each kind is called on screen, and which table it lives
#: in. Held here so the service and the router never spell either.
TABLES = {
    RECEIVABLE: "client_sales_invoices",
    PAYABLE: "purchase_bills",
}
PARTY_TABLE = {RECEIVABLE: "customers", PAYABLE: "vendors"}
PARTY_COLUMN = {RECEIVABLE: "customer_id", PAYABLE: "vendor_id"}
NUMBER_COLUMN = {RECEIVABLE: "invoice_no", PAYABLE: "bill_no"}
DATE_COLUMN = {RECEIVABLE: "invoice_date", PAYABLE: "bill_date"}

#: The status an opening document is created in. `issued` / `received` is what
#: every ageing reader's `NOT IN (dead statuses)` filter expects, and a `draft`
#: would be excluded from the very schedules this exists to populate.
OPEN_STATUS = {RECEIVABLE: "issued", PAYABLE: "received"}


@dataclass(frozen=True)
class Refusal:
    reasons: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.reasons


def _parse_date(value: Any) -> Optional[date]:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def problem_with(*, kind: str, party_id: Optional[str], document_no: Optional[str],
                 document_date: Any, due_date: Any,
                 outstanding_paise: Any) -> Refusal:
    """Whether this can be recorded as an opening document.

    Deliberately NOT a Rule 46(b) check on the number. The number belongs to the
    system the client is migrating from — it is a fact about a document somebody
    else issued, the same way `purchase_bills.bill_no` is the vendor's own. A
    series this product never generated is not ours to refuse, and refusing it
    would make a migration impossible for exactly the clients who most need one.
    """
    reasons: list[str] = []

    if kind not in KINDS:
        reasons.append(f"{kind!r} is not an opening document kind — "
                       f"{' or '.join(KINDS)}.")
        return Refusal(reasons)

    if not (party_id or "").strip():
        noun = "customer" if kind == RECEIVABLE else "vendor"
        reasons.append(f"An opening document belongs to a {noun}; that is what "
                       f"makes it age against one.")
    if not (document_no or "").strip():
        reasons.append("The document's own number is required — it is the "
                       "number the other system issued, and it is what the CA "
                       "and the party will both quote.")

    on = _parse_date(document_date)
    if on is None:
        reasons.append("The document's own date is required: it is what the "
                       "ageing buckets are measured from where no due date is "
                       "recorded (MCA G.S.R. 207(E) — from the due date of "
                       "payment, or from the transaction date where none is "
                       "specified).")
    due = _parse_date(due_date) if due_date else None
    if due_date and due is None:
        reasons.append("The due date is not a date.")
    if on and due and due < on:
        reasons.append(f"The due date {due.isoformat()} is before the document "
                       f"date {on.isoformat()}.")

    try:
        amount = int(outstanding_paise)
    except (TypeError, ValueError):
        amount = 0
        reasons.append("The outstanding amount is not a whole number of paise.")
    if amount <= 0:
        reasons.append("An opening document records what is STILL OWED at the "
                       "opening date. A document already settled there is not "
                       "part of the opening balance and is not carried over.")

    return Refusal(reasons)


def row_for(*, kind: str, firm_id: str, client_id: str, party_id: str,
            document_no: str, document_date: str, due_date: Optional[str],
            outstanding_paise: int, notes: Optional[str] = None) -> dict:
    """The document row, built ONCE here so the two kinds cannot drift.

    Every tax field is zero and `total_paise` is what is owed — see the module
    header. `paid_paise` is left at its column default of zero, which is what
    makes `outstanding_paise` (the generated column, migration 278) equal the
    whole amount.
    """
    row = {
        "firm_id": firm_id,
        "client_id": client_id,
        PARTY_COLUMN[kind]: party_id,
        NUMBER_COLUMN[kind]: document_no.strip(),
        DATE_COLUMN[kind]: document_date,
        "due_date": due_date or None,
        "taxable_amount_paise": 0,
        "cgst_paise": 0,
        "sgst_paise": 0,
        "igst_paise": 0,
        "total_gst_paise": 0,
        "total_paise": int(outstanding_paise),
        "status": OPEN_STATUS[kind],
        "is_opening": True,
    }
    if kind == PAYABLE:
        # An opening bill withholds nothing: any TDS on it was deducted,
        # deposited and reported on a statement filed from the old system, so a
        # figure here would be a second deduction against the same payment.
        row["tds_paise"] = 0
        row["tds_rate_bps"] = 0
        # LOAD-BEARING, and not symmetrical with the sales side. Migration 278
        # generates `purchase_bills.outstanding_paise` from **net_payable_paise**
        # (total less the TDS withheld), while the invoice's is generated from
        # `total_paise`. Setting only `total_paise` here would leave every
        # opening bill outstanding at ZERO — invisible to AP ageing and to the
        # Schedule III payables note, which is the whole feature.
        row["net_payable_paise"] = int(outstanding_paise)
        row["our_reference"] = notes or None
    else:
        row["notes"] = notes or None
        row["is_interstate"] = False
    return row


@dataclass(frozen=True)
class PartyReconciliation:
    """One party's typed opening balance against the documents behind it."""
    party_id: str
    party_name: Optional[str]
    opening_balance_paise: int
    documents_paise: int
    document_count: int

    @property
    def difference_paise(self) -> int:
        """Balance less documents. POSITIVE means part of the balance has no
        document behind it and will age to nothing; NEGATIVE means the documents
        claim more than the balance the ledger actually carries."""
        return self.opening_balance_paise - self.documents_paise

    @property
    def agrees(self) -> bool:
        return self.difference_paise == 0

    @property
    def sentence(self) -> Optional[str]:
        if self.agrees:
            return None
        who = self.party_name or self.party_id
        d = self.difference_paise
        if self.document_count == 0:
            return (f"{who}: the whole opening balance of ₹{_r(self.opening_balance_paise)} "
                    f"has no document behind it, so none of it appears in any "
                    f"ageing bucket.")
        if d > 0:
            return (f"{who}: ₹{_r(d)} of the ₹{_r(self.opening_balance_paise)} "
                    f"opening balance has no document behind it and will not age.")
        return (f"{who}: the opening documents come to ₹{_r(self.documents_paise)}, "
                f"which is ₹{_r(-d)} MORE than the ₹{_r(self.opening_balance_paise)} "
                f"opening balance the ledger carries.")


def _r(paise: int) -> str:
    """Rupees, for a sentence a CA reads. Money crosses the API in paise; this
    is the one place a figure is spelled, because the sentence is the answer."""
    return f"{paise / 100:,.2f}"


def reconcile(parties: list[dict], documents: list[dict], *,
              kind: str) -> list[PartyReconciliation]:
    """Every party that has an opening balance OR an opening document.

    A party with neither is not reported: it has nothing to reconcile. A party
    with documents and no balance IS reported, because that is the direction
    that puts an amount in the ageing schedule which the control account does
    not carry.
    """
    by_party: dict[str, int] = {}
    counts: dict[str, int] = {}
    for d in documents:
        pid = d.get(PARTY_COLUMN[kind])
        if not pid:
            continue
        by_party[pid] = by_party.get(pid, 0) + int(d.get("outstanding_paise") or 0)
        counts[pid] = counts.get(pid, 0) + 1

    out: list[PartyReconciliation] = []
    seen: set[str] = set()
    for p in parties:
        pid = p.get("id")
        opening = int(p.get("opening_balance_paise") or 0)
        if not pid or (opening == 0 and pid not in by_party):
            continue
        seen.add(pid)
        out.append(PartyReconciliation(
            party_id=pid, party_name=p.get("name"),
            opening_balance_paise=opening,
            documents_paise=by_party.get(pid, 0),
            document_count=counts.get(pid, 0)))
    for pid, total in by_party.items():
        if pid in seen:
            continue
        # A document against a party the caller did not hand us — a party
        # deleted after its documents were entered, say. Reported rather than
        # dropped: the amount is in the ageing schedule either way.
        out.append(PartyReconciliation(
            party_id=pid, party_name=None, opening_balance_paise=0,
            documents_paise=total, document_count=counts.get(pid, 0)))
    out.sort(key=lambda r: (r.agrees, (r.party_name or "").lower(), r.party_id))
    return out


# ── The one question every statutory reader has to ask ───────────────────────

def carried_over(row: dict) -> bool:
    """True where this document was raised in the system the client migrated
    FROM, so its revenue, its tax and any withholding on it were dealt with
    there.

    Read with `.get`, deliberately: a row that predates migration 391, or an
    in-memory double that never carried the column, reads as an ORDINARY
    document. That is the direction that cannot silently drop a real supply
    from a return — the opposite mistake (an opening document declared twice)
    needs the flag to be present and true, which only this module's own writer
    does.
    """
    return bool(row.get("is_opening"))


def without_carried_over(rows: list[dict]) -> list[dict]:
    """The documents a statutory return may declare.

    Filtered in PYTHON rather than as a `.eq("is_opening", False)` predicate,
    for the reason `purchase_payment_service` filters `is_voided` the same way:
    a source that does not carry the column at all — mock mode, the in-memory
    doubles — must not be read as "everything matched nothing".
    """
    return [r for r in (rows or []) if not carried_over(r)]


#: ⚠️ WHAT AN OPENING DOCUMENT CANNOT TELL A §194 AGGREGATE, and why nothing
#: here tries. Most of the §194 series charges on "the aggregate of the amounts
#: ... credited or paid during the financial year" (§194C(5) and the same limb
#: in §§194A/194D/194G/194H/194J), and that aggregate is a fact about the YEAR,
#: not about which software recorded it: a bill credited in April under the old
#: system counts toward the limit tested on an August bill here.
#:
#: An opening document cannot supply it, and could not however it were shaped.
#: It records what is still OWED at the opening date, so a bill credited in
#: April and PAID before the migration is not carried over at all — and it
#: counts toward the aggregate just the same. The figure needed is
#: year-to-date CREDITED, which an opening BALANCE by definition does not hold.
#:
#: So `row_for` writes `taxable_amount_paise = 0` and the aggregate reads it as
#: nothing, which is the truthful answer to a question it was never asked.
#: `resolve_tds` already takes `fy_prior_taxable_paise` and
#: `fy_prior_tds_paise` from its caller for exactly this reason — a client
#: migrating mid-year needs the CA to state them, and that is a separate piece
#: of work from this one.
SECTION_194_AGGREGATE_IS_NOT_CARRIED = (
    "An opening bill contributes nothing to the section 194 financial-year "
    "aggregate. The aggregate is measured on what was credited or paid during "
    "the year, and an opening balance records only what is still owed — a bill "
    "credited and settled before the migration counts toward the limit and is "
    "not carried over at all. State the year-to-date figures on the bill that "
    "needs them."
)

#: An opening document withholds nothing and declares nothing. Asserted in the
#: tests against `row_for`'s output rather than left as prose, because the TDS
#: statement's own reads are `.gt("tds_paise", 0)` and `.eq("tds_section",
#: "195")` — they exclude an opening bill only for as long as this stays true.
NO_TAX_FIELDS = (
    "taxable_amount_paise", "cgst_paise", "sgst_paise", "igst_paise",
    "total_gst_paise",
)


def note_refusal(kind: str) -> str:
    """Why a CGST §34 note cannot be raised against a carried-over document.

    One sentence for all four note routes — sales credit, sales debit, purchase
    credit, purchase debit — because it is one reason: §34 adjusts the tax
    charged on the ORIGINAL supply, and that tax was charged, collected and
    declared in the system the client migrated from. A note here would move
    this client's own output tax or input credit by an amount its returns never
    carried.
    """
    noun = "invoice" if kind == RECEIVABLE else "bill"
    return (
        f"That {noun} was carried over from the system this client migrated "
        f"from, so its GST was charged and declared there. A section 34 note "
        f"here would adjust tax this client's own returns never carried. Raise "
        f"the note in the system that issued the {noun}, or correct the opening "
        f"balance instead."
    )


# ── The OTHER double count: two mechanisms, one opening position ─────────────
#
# `opening_balance_service` posts the masters' opening AR, AP and bank under
# `source_type = 'Opening'`. `trial_balance_import_service` posts an imported
# trial balance under `source_type = 'TrialBalance'`, deliberately in a separate
# journal family — that separation is right and its own header explains why
# (the opening delta engine reverses anything in ITS family the masters do not
# justify, so a trial balance posted there would be silently backed out on the
# next customer edit).
#
# What neither of them does is COMPARE. A CA migrating a client enters the bank
# opening balance on the bank master AND imports a trial balance that has a Bank
# row on it, and both post: the account is opened twice, the balance sheet is
# out by exactly the bank balance, and nothing says so. The two families are
# append-only and neither will ever correct the other.
#
# This is the comparison. It reads, decides nothing and posts nothing — the CA
# reverses whichever they meant not to.

#: The two journal families that carry an opening position.
MASTER_SOURCE = "Opening"
TRIAL_BALANCE_SOURCE = "TrialBalance"


@dataclass(frozen=True)
class DoubleOpening:
    """One account opened by BOTH mechanisms."""
    account_id: str
    account_name: Optional[str]
    master_paise: int
    trial_balance_paise: int

    @property
    def sentence(self) -> str:
        who = self.account_name or self.account_id
        return (f"{who} was opened twice: ₹{_r(abs(self.master_paise))} from the "
                f"party and bank master records, and ₹{_r(abs(self.trial_balance_paise))} "
                f"from the imported trial balance. Both are posted, so this "
                f"account is out by one of them.")


def double_openings(master_net: dict[str, int],
                    trial_balance_net: dict[str, int],
                    names: Optional[dict[str, Optional[str]]] = None,
                    ) -> list[DoubleOpening]:
    """Accounts carrying a non-zero opening position in BOTH families.

    NON-ZERO on both sides, not merely present: a delta engine legitimately
    leaves a net-zero pair behind on an account whose master balance went to
    zero, and reporting that as a double count would cry wolf on the commonest
    correction there is.

    The two figures are NOT netted and no difference is offered. Which one is
    the mistake is the CA's answer — the same reason this module reports the
    party reconciliation rather than adjusting it — and a single "difference"
    would read as a figure to post.
    """
    names = names or {}
    out: list[DoubleOpening] = []
    for account_id, master in master_net.items():
        tb = trial_balance_net.get(account_id, 0)
        if master == 0 or tb == 0:
            continue
        out.append(DoubleOpening(
            account_id=account_id, account_name=names.get(account_id),
            master_paise=master, trial_balance_paise=tb))
    out.sort(key=lambda d: ((d.account_name or "").lower(), d.account_id))
    return out
