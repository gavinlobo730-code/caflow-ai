"""THE FIRM-WIDE RISK REGISTER, AND WHY IT IS HERE RATHER THAN IN THE BROWSER.

`apps/web/app/risks/page.tsx` derived nine kinds of statutory risk in 856 lines
of TypeScript, from six PostgREST reads, and the register it built is the one
screen a partner opens to decide what the practice does next. Every part of
that was business logic in the frontend, which this repository's first code
rule forbids — and it was not an abstract violation:

  * **A STATUTORY FIGURE WAS STATED THAT NOTHING HERE CAN ESTABLISH.** The
    FD-maturity row advised *"TDS applicable u/s 194A if interest > ₹40,000"* —
    a literal typed into TypeScript, and wrong twice over. §194A(3)(i) sets a
    DIFFERENT limit for interest paid by a banking company from the section's
    general one, and a further one again for a senior citizen; the Finance Act
    2025 moved the bank limb. `domain/tds/section_rates` holds **one** figure
    for §194A and its own docstring says which limb that is — *"₹10,000 is the
    'any other payer' threshold"* — so the registry cannot supply the bank
    limb either. The section is NAMED here and no figure is quoted, which is
    this product's standing discipline for a statutory number it does not hold.

    ⚠️ **The first draft of this module quoted the registry's ₹10,000 as though
    it were the bank limb**, having misread 1000000 paise as ₹1,00,000. It is
    ₹10,000. The mistake is recorded because it is the third miscount of an
    Indian figure in this run, and because a wrong threshold on a screen a CA
    acts from is exactly what this module exists to stop.
  * **THE ADVANCE-TAX DATES WERE FOUR HARDCODED STRINGS** (`${year}-06-15` and
    so on) against `compliance_engine.advance_tax_due_dates`, which CLAUDE.md
    names as the single source for every due date in this product. A CBDT
    extension would move one and not the other.
  * **`rbac()` NEVER RAN**, and neither did `core.authz`'s assignment scope. The
    six reads were the browser's own, so an Executive who cannot see a client
    still read that client's compliance calendar, loans and fixed deposits.

**THIS MODULE DECIDES; IT DOES NOT FETCH.** Every function takes rows somebody
else read, so the rule can be tested without a database and so the service can
page, scope and bound the reads in one place.

── WHAT IS NOT MERGED INTO `domain/risk_engine` ────────────────────────────

`domain/risk_engine.py` reads `document_risks` — risks a human or the document
intelligence recorded against a document — and derives one more from an overdue
compliance RECORD. This module derives from the compliance CALENDAR, the client
master, the DSC register, loans and fixed deposits. They are different
populations answering the same question, and folding one into the other would
make a caller unable to say which it asked for. `GET /api/risks/register` is a
separate endpoint beside `GET /api/risks` for the same reason.

── THE SEVERITY LADDER IS A JUDGEMENT AND IT IS WRITTEN DOWN ──────────────

An overdue filing is `high` past thirty days, `medium` from fifteen, `low`
below. That is a practice convention rather than a statutory rule — no section
grades lateness — so it is NAMED as one (`OVERDUE_LADDER`) rather than left as
two magic numbers, and the sentence saying it is a convention travels on the
answer. Everything else carries a fixed severity whose reason is in its own
builder.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable, Optional

from core.ist_clock import ist_today
from domain.gst.gstin import problem_with as gstin_problem

# ── Vocabulary ─────────────────────────────────────────────────────────────

# The quarterly TDS statements, scored under §200A rather than as ordinary
# overdue filings. ONE list, read twice — once to hold these OUT of the general
# bucket and once to select them INTO the TDS one — because two copies is how
# 27Q lands in the wrong bucket instead of failing visibly.
#
# 27Q is the payments-to-non-residents statement (Rule 31A(4)(b)); §200A's
# late-filing fee does not care which form it is, so it belongs with the other
# two. **27EQ is deliberately absent**: it is TCS under §206C, which
# `domain/tds/section_rates` records as reference data this product does not
# implement, so nothing here generates one to be late with.
TDS_STATEMENT_TYPES: tuple[str, ...] = ("TDS24Q", "TDS26Q", "TDS27Q")

# A practice convention, not a statutory grading. See the module docstring.
OVERDUE_LADDER_HIGH_DAYS = 30
OVERDUE_LADDER_MEDIUM_DAYS = 15
OVERDUE_LADDER_NOTE = (
    "How lateness is graded is a practice convention: no section grades a "
    f"delay. Over {OVERDUE_LADDER_HIGH_DAYS} days is treated as high and "
    f"{OVERDUE_LADDER_MEDIUM_DAYS} days or more as medium."
)

# A client with no compliance entry inside this window is reported as inactive.
# Also a convention, and it is REPORTED rather than acted on: the CA decides
# whether the engagement ended or the calendar was never filled in.
INACTIVE_AFTER_DAYS = 90

# CBDT does not set a renewal window; sixty days is the practice's own notice
# period, long enough to order a new token and have it delivered.
DSC_NOTICE_DAYS = 60
DSC_URGENT_DAYS = 15

# A maturing deposit is worth raising while there is still time to advise on
# renewal or withdrawal.
FD_NOTICE_DAYS = 30

SEVERITIES = ("critical", "high", "medium", "low")


@dataclass(frozen=True)
class RiskRow:
    """One line of the register. `client_id` is empty for a firm-level risk —
    a DSC is held by a PERSON and registered to the firm, and `dsc_records`
    carries no client_id, so there is no client to attribute one to."""

    client_id: str
    client_name: str
    risk_type: str
    description: str
    severity: str
    action: str
    days_overdue: Optional[int] = None
    amount_paise: Optional[int] = None
    on_date: Optional[str] = None
    #: The particulars this KIND of risk is read by, in the order they should be
    #: shown — "Filing Type" for an overdue return, "DSC Holder" for a
    #: certificate, "Lender" and "Loan Type" for a loan.
    #:
    #: THE SERVER DECIDES THE COLUMNS AND THE BROWSER RENDERS WHATEVER ARRIVES.
    #: The screen this replaced held nine hand-written tables, one per kind,
    #: each naming its own columns — so every particular was a fact about the
    #: risk that only the browser knew, and adding a kind meant writing a tenth
    #: table. One generic renderer over this map means the browser holds no
    #: per-kind knowledge at all, which is the whole point of moving the
    #: derivation. A dict preserves insertion order, which is the display order.
    particulars: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        assert self.severity in SEVERITIES, f"unknown severity {self.severity!r}"


@dataclass
class RiskRegister:
    rows: list[RiskRow] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        out = {s: 0 for s in SEVERITIES}
        for r in self.rows:
            out[r.severity] += 1
        out["total"] = len(self.rows)
        return out


# ── Helpers ────────────────────────────────────────────────────────────────

def _as_date(value: Any) -> Optional[date]:
    """A date column may come back as a date or as an ISO string, and a
    TIMESTAMPTZ string carries a time. Only the first ten characters are the
    calendar day, and the caller has already decided which day it wants."""
    if isinstance(value, date):
        return value
    if isinstance(value, str) and len(value) >= 10:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def overdue_severity(days: int) -> str:
    if days > OVERDUE_LADDER_HIGH_DAYS:
        return "high"
    if days >= OVERDUE_LADDER_MEDIUM_DAYS:
        return "medium"
    return "low"


def _name(client_map: dict[str, str], client_id: str) -> str:
    return client_map.get(client_id) or "Unknown client"


# ── The nine derivations ───────────────────────────────────────────────────

def overdue_filings(
    calendar: Iterable[dict],
    client_map: dict[str, str],
    *,
    as_at: date,
) -> list[RiskRow]:
    """A compliance obligation past its due date and not filed.

    The TDS statements are held out and scored by `tds_defaults` below, under a
    different section and at a fixed severity."""
    rows: list[RiskRow] = []
    for entry in calendar:
        if (entry.get("filing_status") or "") == "filed":
            continue
        if (entry.get("compliance_type") or "") in TDS_STATEMENT_TYPES:
            continue
        due = _as_date(entry.get("due_date"))
        if due is None or due >= as_at:
            continue
        days = (as_at - due).days
        kind = entry.get("compliance_type") or "Filing"
        rows.append(RiskRow(
            client_id=entry.get("client_id") or "",
            client_name=_name(client_map, entry.get("client_id") or ""),
            risk_type="Overdue Filing",
            description=f"{kind} overdue by {days} days (due {due.isoformat()})",
            severity=overdue_severity(days),
            action="File and pay the late fee. CGST Act §47 for a GST return; "
                   "the fee and interest depend on which return it is.",
            days_overdue=days,
            on_date=due.isoformat(),
            particulars={
                "Filing Type": str(kind),
                "Due Date": due.isoformat(),
                "Days Overdue": str(days),
            },
        ))
    return sorted(rows, key=lambda r: -(r.days_overdue or 0))


def tds_defaults(
    calendar: Iterable[dict],
    client_map: dict[str, str],
    *,
    as_at: date,
) -> list[RiskRow]:
    """A quarterly TDS statement past its due date.

    ALWAYS HIGH, and not on the ordinary ladder: §234E charges ₹200 a DAY from
    the due date, capped at the statement's own tax, and it is payable BEFORE
    the statement can be delivered (§234E(4)). A one-day-late statement is
    already a real exposure, so grading it `low` would be wrong."""
    rows: list[RiskRow] = []
    for entry in calendar:
        if (entry.get("compliance_type") or "") not in TDS_STATEMENT_TYPES:
            continue
        if (entry.get("filing_status") or "") == "filed":
            continue
        due = _as_date(entry.get("due_date"))
        if due is None or due >= as_at:
            continue
        days = (as_at - due).days
        rows.append(RiskRow(
            client_id=entry.get("client_id") or "",
            client_name=_name(client_map, entry.get("client_id") or ""),
            risk_type="TDS Default",
            description=f"{entry.get('compliance_type')} overdue by {days} days",
            severity="high",
            action="File the statement. §234E charges ₹200 a day from the due "
                   "date, capped at the statement's own tax and payable before "
                   "it can be delivered; §201(1A) interest runs separately on "
                   "any tax deducted and not deposited.",
            days_overdue=days,
            on_date=due.isoformat(),
            particulars={
                "Return Type": str(entry.get("compliance_type")),
                "Due Date": due.isoformat(),
                "Days Overdue": str(days),
            },
        ))
    return sorted(rows, key=lambda r: -(r.days_overdue or 0))


def invalid_gstins(clients: Iterable[dict]) -> list[RiskRow]:
    """A client GSTIN this product's own authority refuses.

    THIS IS THE ROW THE WHOLE SECTION EXISTS FOR, and in the browser it was
    decided by a bare shape regex, which accepts every transposition inside the
    PAN — the commonest wrong GSTIN, and the only kind a CA needs a screen to
    find. `domain/gst/gstin.problem_with` tests the state code and the check
    digit, and names the character to look at."""
    rows: list[RiskRow] = []
    for client in clients:
        gstin = (client.get("gstin") or "").strip()
        if not gstin:
            continue  # unregistered is not wrong
        problem = gstin_problem(gstin)
        if not problem:
            continue
        rows.append(RiskRow(
            client_id=client.get("id") or "",
            client_name=client.get("client_name") or "Unknown client",
            risk_type="GSTIN Mismatch",
            description=f"GSTIN {gstin} is invalid: {problem}",
            severity="medium",
            action="Verify the GSTIN on the GST portal and correct the client "
                   "record. CGST Act §16(2)(aa) sends the recipient's credit to "
                   "whoever the GSTIN names.",
            particulars={"GSTIN": gstin, "Issue": problem},
        ))
    return rows


def missing_pans(clients: Iterable[dict]) -> list[RiskRow]:
    return [
        RiskRow(
            client_id=c.get("id") or "",
            client_name=c.get("client_name") or "Unknown client",
            risk_type="Missing PAN",
            description="No PAN on record for this client",
            severity="medium",
            action="Obtain the PAN. IT Act §139A — it is required to file a "
                   "return, and §206AA charges a higher rate where a deductee "
                   "has not furnished one.",
            particulars={"Client": c.get("client_name") or "Unknown client"},
        )
        for c in clients
        if not (c.get("pan") or "").strip()
    ]


def inactive_clients(
    clients: Iterable[dict],
    client_ids_with_recent_entries: set[str],
) -> list[RiskRow]:
    """A client the compliance calendar has said nothing about for ninety days.

    REPORTED, NEVER ACTED ON, and the description says which two things it
    cannot tell apart: an engagement that ended and a calendar nobody filled
    in look identical from here."""
    return [
        RiskRow(
            client_id=c.get("id") or "",
            client_name=c.get("client_name") or "Unknown client",
            risk_type="Inactive Client",
            description=f"No compliance entry in the last {INACTIVE_AFTER_DAYS} days",
            severity="low",
            action="Confirm whether the engagement is live. An ended engagement "
                   "and an unfilled calendar look the same from here.",
            particulars={"Days Inactive": f"{INACTIVE_AFTER_DAYS}+"},
        )
        for c in clients
        if (c.get("id") or "") not in client_ids_with_recent_entries
    ]


def advance_tax_defaults(
    clients_tracked: Iterable[dict],
    installments: Iterable[dict],
    filed_keys: set[str],
    client_map: dict[str, str],
    *,
    as_at: date,
) -> list[RiskRow]:
    """A §208 instalment past its date with nothing recorded as filed.

    THE DATES ARE `compliance_engine.advance_tax_due_dates`, NOT FOUR LITERALS.
    CLAUDE.md makes that module the single source for every due date in this
    product precisely so a CBDT extension moves one thing.

    Only clients the calendar ALREADY TRACKS for advance tax are considered: a
    client with no advance-tax obligation recorded has no instalment to miss,
    and inventing one for every client would bury the real ones."""
    rows: list[RiskRow] = []
    for client in clients_tracked:
        cid = client.get("id") or ""
        for inst in installments:
            due = _as_date(inst.get("due_date"))
            if due is None or due >= as_at:
                continue
            if f"{cid}|{due.isoformat()}" in filed_keys:
                continue
            days = (as_at - due).days
            rows.append(RiskRow(
                client_id=cid,
                client_name=_name(client_map, cid),
                risk_type="Advance Tax Default",
                description=(
                    f"{inst.get('installment')} not recorded as paid — due "
                    f"{due.isoformat()}, {days} days ago"
                ),
                severity="high",
                action="Pay with interest. IT Act §234C charges on a shortfall "
                       "in an instalment and §234B on the year's shortfall from "
                       "1 April of the assessment year.",
                days_overdue=days,
                on_date=due.isoformat(),
                particulars={
                    "Installment": str(inst.get("installment")),
                    "Due Date": due.isoformat(),
                    "Days Overdue": str(days),
                },
            ))
    return sorted(rows, key=lambda r: -(r.days_overdue or 0))


def expiring_dscs(dsc_rows: Iterable[dict], *, as_at: date) -> list[RiskRow]:
    """A digital signature certificate inside its notice window.

    FIRM-LEVEL, not client-level: a DSC is held by a PERSON and registered to
    the firm, and `dsc_records` carries no client_id. The holder's name is the
    identifying fact, so `client_id` is empty and the register says "Firm-wide"
    rather than attributing the certificate to a client that did not buy it."""
    rows: list[RiskRow] = []
    for row in dsc_rows:
        expiry = _as_date(row.get("expiry_date"))
        if expiry is None:
            continue
        days_left = (expiry - as_at).days
        if days_left < 0 or days_left > DSC_NOTICE_DAYS:
            continue
        holder = row.get("holder_name") or "an unnamed holder"
        rows.append(RiskRow(
            client_id="",
            client_name="Firm-wide",
            risk_type="DSC Expiry",
            description=f"DSC of {holder} expires on {expiry.isoformat()} "
                        f"({days_left} days left)",
            severity="high" if days_left <= DSC_URGENT_DAYS else "medium",
            action="Renew before it expires. Every e-filing this firm signs "
                   "stops the day it lapses, and a replacement token takes days "
                   "to arrive.",
            on_date=expiry.isoformat(),
            particulars={
                "DSC Holder": str(holder),
                "Expiry Date": expiry.isoformat(),
                "Days Left": str(days_left),
            },
        ))
    return sorted(rows, key=lambda r: r.on_date or "")


def overdue_loans(loans: Iterable[dict], client_map: dict[str, str]) -> list[RiskRow]:
    rows: list[RiskRow] = []
    for loan in loans:
        cid = loan.get("client_id") or ""
        outstanding = int(loan.get("outstanding_paise") or 0)
        rows.append(RiskRow(
            client_id=cid,
            client_name=_name(client_map, cid),
            risk_type="Loan Overdue",
            description=(
                f"{loan.get('loan_type') or 'Loan'} from "
                f"{loan.get('lender_name') or 'an unnamed lender'} is overdue"
            ),
            severity="high",
            action="Contact the lender. An overdue account attracts penal "
                   "interest and is reported to the credit bureaus.",
            amount_paise=outstanding,
            particulars={
                "Lender": str(loan.get("lender_name") or "—"),
                "Loan Type": str(loan.get("loan_type") or "—"),
            },
        ))
    return sorted(rows, key=lambda r: -(r.amount_paise or 0))


def maturing_deposits(
    deposits: Iterable[dict],
    client_map: dict[str, str],
    *,
    as_at: date,
) -> list[RiskRow]:
    """A fixed deposit maturing inside the notice window.

    **§194A IS NAMED AND NO THRESHOLD IS QUOTED.** See the module docstring:
    §194A(3)(i) sets one limit for interest from a banking company, another as
    the section's general rule and another again for a senior citizen, and
    `domain/tds/section_rates` deliberately holds only the general one. The
    browser's version of this row stated ₹40,000 — the bank limb as it stood
    before the Finance Act 2025 — which is both stale and a figure no module
    here can confirm. A section a CA can look up beats a number they cannot
    trust.
    """
    rows: list[RiskRow] = []
    for fd in deposits:
        maturity = _as_date(fd.get("maturity_date"))
        if maturity is None:
            continue
        days_left = (maturity - as_at).days
        if days_left < 0 or days_left > FD_NOTICE_DAYS:
            continue
        cid = fd.get("client_id") or ""
        rows.append(RiskRow(
            client_id=cid,
            client_name=_name(client_map, cid),
            risk_type="FD Maturing Soon",
            description=(
                f"Deposit at {fd.get('bank_name') or 'an unnamed bank'} matures "
                f"on {maturity.isoformat()} ({days_left} days)"
            ),
            severity="low",
            action=(
                "Advise on renewal or withdrawal, and check the interest "
                "against IT Act §194A. Its threshold differs for a banking "
                "company, for any other payer and for a senior citizen "
                "(§194A(3)(i)), and this product holds only the general one — "
                "so no figure is quoted here."
            ),
            amount_paise=int(fd.get("maturity_amount_paise") or 0),
            on_date=maturity.isoformat(),
            particulars={
                "Bank": str(fd.get("bank_name") or "—"),
                "Maturity Date": maturity.isoformat(),
                "Days Left": str(days_left),
            },
        ))
    return sorted(rows, key=lambda r: r.on_date or "")


# ── The register ───────────────────────────────────────────────────────────

def build(
    *,
    calendar: Iterable[dict],
    clients: Iterable[dict],
    client_ids_with_recent_entries: set[str],
    advance_tax_installments: Iterable[dict],
    advance_tax_tracked_client_ids: set[str],
    advance_tax_filed_keys: set[str],
    dsc_rows: Iterable[dict],
    loans: Iterable[dict],
    deposits: Iterable[dict],
    as_at: Optional[date] = None,
) -> RiskRegister:
    """Assemble the register from rows somebody else read."""
    as_at = as_at or ist_today()
    clients = list(clients)
    calendar = list(calendar)
    client_map = {
        (c.get("id") or ""): (c.get("client_name") or "")
        for c in clients
    }
    tracked = [c for c in clients if (c.get("id") or "") in advance_tax_tracked_client_ids]

    reg = RiskRegister()
    reg.rows.extend(overdue_filings(calendar, client_map, as_at=as_at))
    reg.rows.extend(tds_defaults(calendar, client_map, as_at=as_at))
    reg.rows.extend(invalid_gstins(clients))
    reg.rows.extend(inactive_clients(clients, client_ids_with_recent_entries))
    reg.rows.extend(advance_tax_defaults(
        tracked, advance_tax_installments, advance_tax_filed_keys,
        client_map, as_at=as_at,
    ))
    reg.rows.extend(expiring_dscs(dsc_rows, as_at=as_at))
    reg.rows.extend(overdue_loans(loans, client_map))
    reg.rows.extend(maturing_deposits(deposits, client_map, as_at=as_at))
    reg.rows.extend(missing_pans(clients))

    reg.notes.append(OVERDUE_LADDER_NOTE)
    reg.notes.append(
        "A DSC is held by a person and registered to the firm, so those rows "
        "carry no client."
    )
    return reg
