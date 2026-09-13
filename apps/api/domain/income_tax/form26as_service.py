"""
Form 26AS Reconciliation Module.

IT Act 1961 s.285BB read with Rule 114-I — the Annual Information Statement,
under which Form 26AS is issued. (s.203AA, cited here until now, was OMITTED by
the Finance Act 2020 with effect from 01-06-2020.)

Matches the client's Form 26AS — tax that OTHERS deducted out of payments made
TO the client — against the TDS credits the client's own books record for the
same year. Those credits reach the ledger as the `Dr TDS Receivable` leg of a
receipt; see domain/income_tax/form26as_matcher for why that, and not
`tds_deductions`, is the population on the books side.

The matching itself is a pure function in form26as_matcher, so mock mode and
production run identical logic. This module is the I/O around it.

# CA REVIEW REQUIRED — Reconciliation output must be reviewed before filing
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
import os
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from uuid import uuid4

from domain.income_tax import claimable_credit as _claimable
from domain.income_tax import form26as_matcher as _m

_logger = logging.getLogger("caflow.form26as")
_USE_MOCK = not os.environ.get("SUPABASE_URL")

_MOCK_UPLOADS: dict[str, dict] = {}
_MOCK_RECORDS: dict[str, list] = {}
_MOCK_RECONS: dict[str, dict] = {}
# Mock mode's stand-in for the receipts table. Keyed (firm_id, client_id,
# financial_year) -> list of BookCredit-shaped dicts. It exists so mock mode
# runs the real matching engine: the previous mock branch returned a hardcoded
# "every 26AS row is missing from the books", which is not a simplification but
# a different answer from the one production gives.
_MOCK_BOOK_CREDITS: dict[tuple[str, str, str], list[dict]] = {}

# form_26as_uploads is shared with routers/tds_workspace.py, which writes a
# different kind of row (see migration 291). Every read and write here is
# stamped and filtered so neither feature shows the other's rows.
UPLOAD_SOURCE = "form_26as_pipeline"
# Mock mode's stand-in for the TDS Receivable control-account total.
_MOCK_GL_CONTROL: dict[tuple[str, str, str], int] = {}

# Which books population the reconciliation reads. Stored on every summary row
# so a row produced by the pre-291 comparison (against tds_deductions, the
# opposite direction of TDS) is distinguishable by its NULL.
BOOKS_SOURCE = "receipts.tds_paise"

# Mismatch threshold — an insight is raised when the variance exceeds 1% of the
# 26AS TDS total. Held as tenths of a percent so the comparison can be done by
# cross-multiplication in integers (project rule: never float for money).
MISMATCH_THRESHOLD_PCT = 1.0
_MISMATCH_THRESHOLD_PCT_X10 = 10


def _supabase():
    from core.supabase_client import get_supabase
    return get_supabase()


# ── Upload ─────────────────────────────────────────────────────────────────────

def create_upload(
    firm_id: str,
    client_id: str,
    financial_year: str,
    uploaded_by: str,
    document_id: str | None = None,
) -> dict:
    if _USE_MOCK:
        row = {
            "id": str(uuid4()),
            "firm_id": firm_id,
            "client_id": client_id,
            "financial_year": financial_year,
            "document_id": document_id,
            "parse_status": "pending",
            "total_records": 0,
            "parse_errors": [],
            "source": UPLOAD_SOURCE,
            # Both, mirroring the real insert below — see the comment there for
            # why this table needs two names for one person.
            "uploaded_by": uploaded_by,
            "created_by": uploaded_by,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
        }
        _MOCK_UPLOADS[row["id"]] = row
        _MOCK_RECORDS[row["id"]] = []
        return row

    sb = _supabase()
    row = {
        "firm_id": firm_id,
        "client_id": client_id,
        "financial_year": financial_year,
        "document_id": document_id,
        # BOTH, deliberately. This table's shape diverged between the CI
        # template and the live database: migration 052 declares created_by and
        # no uploaded_by, while production has uploaded_by NOT NULL and no
        # created_by. This insert previously named created_by alone, so on the
        # live database every 26AS upload violated a NOT NULL on a column the
        # code did not know existed — form_26as_uploads holds zero rows there.
        # Migration 291 adds whichever column each side is missing, nullable, so
        # naming both satisfies production's NOT NULL and the template alike.
        "created_by": uploaded_by,
        "uploaded_by": uploaded_by,
        "source": UPLOAD_SOURCE,
    }
    res = sb.table("form_26as_uploads").insert(row).execute()
    return res.data[0] if res.data else row


def get_upload(firm_id: str, upload_id: str) -> dict | None:
    """Read a single 26AS upload by id, scoped to the firm.

    Module 9.0: both row-addressed upload routes previously resolved the row
    on firm_id alone (and the mock branch of mark_26as_uploaded checked
    nothing at all), so neither could enforce client-assignment scope. This
    read gives the router the upload's client_id before it acts.
    """
    if _USE_MOCK:
        row = _MOCK_UPLOADS.get(upload_id)
        return row if row and row.get("firm_id") == firm_id else None

    sb = _supabase()
    res = sb.table("form_26as_uploads").select("*").eq("id", upload_id).eq(
        "firm_id", firm_id
    ).execute()
    return (res.data or [None])[0]


@dataclass(frozen=True)
class SkippedLine:
    """One line of the upload that produced no record, and why."""
    line_no: int          # 1-based, as a text editor counts
    text: str             # the first 120 characters, for recognition
    reason: str


@dataclass(frozen=True)
class Reading26AS:
    """What one 26AS text upload actually yielded.

    `records` alone was the old return value, and returning it alone is the
    defect (IT-24). Two paths in the loop below drop a line — a split that
    yields fewer than five columns, and a row whose date or amount will not
    parse — and both used to vanish: one into a bare `continue`, one into a
    DEBUG log nobody reads. The upload was then marked successful and the
    reconciliation ran against a register missing whatever it could not read,
    reporting the deductor as "not in 26AS" when 26AS had it all along.

    So the reading carries BOTH sides, and the caller must show the second.
    """
    records: list[dict]
    skipped: list[SkippedLine]
    data_lines_seen: int   # lines that were neither blank, a part header nor a column header

    @property
    def looks_unrecognised(self) -> bool:
        """True when there was content and none of it parsed.

        A zero-record read of a file with data in it is not an empty 26AS — it
        is a format this parser does not know (a PDF pasted with spaces rather
        than tabs is the common one, since the split below is tab/pipe only).
        Reporting that as a clean zero is the false-clean result this codebase
        keeps having to close.
        """
        return self.data_lines_seen > 0 and not self.records


def read_26as_text(raw_text: str) -> Reading26AS:
    """
    Parse Form 26AS plain text (downloaded from the TRACES portal).
    Handles Part A (TDS on salary), Part B (TDS other), Part C
    (advance/self-assessment).

    Returns a Reading26AS rather than a bare list, and there is deliberately NO
    convenience wrapper that hands back only the records: a lossy view of this
    answer is exactly what the caller reached for last time.

    The column split is tab or pipe only, and that is a real limit rather than
    an oversight — a 26AS pasted out of a PDF viewer arrives space-separated,
    and splitting on runs of spaces would cut deductor names in half. Such a
    file now reports every line as skipped and `looks_unrecognised`, instead
    of returning nothing and calling it an empty year.
    """
    records: list[dict] = []
    skipped: list[SkippedLine] = []
    data_lines = 0
    current_part = None
    lines = raw_text.strip().splitlines()

    for line_no, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line:
            continue

        # Detect part headers
        part_match = re.match(r"PART\s+([A-Z])", line, re.IGNORECASE)
        if part_match:
            current_part = part_match.group(1).upper()
            continue

        # Skip header rows
        if any(kw in line.upper() for kw in ("SR.", "S.NO", "DEDUCTOR", "NAME OF DEDUCTOR")):
            continue

        data_lines += 1

        # Try to parse data rows (tab/pipe delimited)
        cols = re.split(r"\t|\|", line)
        if len(cols) < 5:
            skipped.append(SkippedLine(
                line_no, line[:120],
                f"only {len(cols)} tab- or pipe-separated column(s); a 26AS row "
                f"needs at least 5. A file pasted out of a PDF viewer is "
                f"space-separated and will not parse — export the text file "
                f"from TRACES instead."))
            continue

        try:
            record: dict = {
                "part": current_part or "A",
                "record_type": _infer_record_type(current_part),
                "deductor_name": cols[1].strip() if len(cols) > 1 else "",
                "deductor_tan": cols[2].strip() if len(cols) > 2 else None,
                "transaction_date": _parse_date(cols[3].strip()) if len(cols) > 3 else None,
                "amount_credited_paise": _parse_amount(cols[4]) if len(cols) > 4 else 0,
                "tds_deposited_paise": _parse_amount(cols[5]) if len(cols) > 5 else 0,
                "booking_status": cols[6].strip() if len(cols) > 6 else None,
            }
            records.append(record)
        except (ValueError, IndexError) as e:
            # Was a DEBUG log. A tax credit dropped at DEBUG level is a tax
            # credit dropped.
            skipped.append(SkippedLine(
                line_no, line[:120],
                f"the date or amount could not be read ({type(e).__name__})"))

    return Reading26AS(records=records, skipped=skipped, data_lines_seen=data_lines)


#: What each part of Form 26AS actually holds, and whether it is a tax credit
#: the CLIENT may claim on their return.
#:
#: The old map said B was "tds_other", C "advance_tax", D "self_assessment" and
#: F "tds_other" — and NOTHING read it, so every row of every part was summed
#: into `total_26as_paise` and matched against the client's book TDS credits.
#: Two of those are not TDS at all and one is not the client's:
#:
#:   A / A1 / A2  TDS deducted FROM the client. A credit. (The regex that
#:                finds the part header keeps only the letter, so A1 and A2
#:                fold into A — harmless here, because all three are credits.)
#:   B            TCS COLLECTED from the client. A genuine credit (s.206C(4))
#:                and its own kind, not "tds_other".
#:   C            Tax the client PAID themselves — advance and self-assessment.
#:                Real, claimable, and NOT a TDS credit: counting it against
#:                the TDS register makes 26AS look larger than the books by
#:                exactly the advance tax.
#:   D            A REFUND already received. Not a credit in any direction.
#:   F            s.194-IA tax the client deducted as BUYER of property. Money
#:                the client PAID OVER, not withheld from them.
#:
#: ⚠️ A2 (seller of property) and F (buyer) point OPPOSITE ways and the audit
#: finding's own suggested fix lumped them together, which would drop a real
#: s.194-IA credit. They are kept apart here. What is NOT settled without a
#: real TRACES statement is whether this parser's part detection distinguishes
#: A2 from A at all — it does not, and that is safe only because both are
#: credits.
_PART_RECORD_TYPE = {
    "A": "tds_salary",
    "B": "tcs_collected",
    "C": "tax_paid_by_client",
    "D": "refund_received",
    "F": "tds_deducted_by_client_194ia",
}

#: The record types that are a credit the client may claim. Everything else is
#: still parsed, still stored and still shown — it is simply not added to the
#: 26AS side of a TDS reconciliation.
CREDIT_RECORD_TYPES = frozenset({"tds_salary", "tds_other", "tcs_collected"})


def _infer_record_type(part: str | None) -> str:
    return _PART_RECORD_TYPE.get(part or "A", "tds_other")


def _parse_date(s: str) -> str | None:
    """Parse DD/MM/YYYY or YYYY-MM-DD."""
    s = s.strip()
    if re.match(r"\d{2}/\d{2}/\d{4}", s):
        d, m, y = s.split("/")
        return f"{y}-{m}-{d}"
    if re.match(r"\d{4}-\d{2}-\d{2}", s):
        return s
    return None


def _parse_amount(s: str) -> int:
    """Parse amount string to paise (integer). Input is in rupees with commas.

    Decimal-based (never float, per project rule) -- a raw float() conversion
    is not guaranteed to round-trip exactly through *100 (IEEE-754 binary
    imprecision). A leading '-' (a correction/reversal row in 26AS) is
    preserved rather than being silently stripped by the digit/dot filter.
    """
    s = s.strip()
    negative = s.startswith("-")
    cleaned = re.sub(r"[^\d.]", "", s)
    if not cleaned:
        return 0
    try:
        paise = int((Decimal(cleaned) * 100).to_integral_value(rounding=ROUND_HALF_UP))
    except InvalidOperation as e:
        raise ValueError(f"Invalid amount: {s!r}") from e
    return -paise if negative else paise


def save_parsed_records(
    firm_id: str,
    upload_id: str,
    client_id: str,
    financial_year: str,
    records: list[dict],
) -> dict:
    """Save parsed 26AS records and update upload status."""
    if _USE_MOCK:
        saved = []
        for r in records:
            row = {
                "id": str(uuid4()),
                "firm_id": firm_id,
                "upload_id": upload_id,
                "client_id": client_id,
                "financial_year": financial_year,
                "reconciliation_status": "unmatched",
                "created_at": datetime.now(timezone.utc).isoformat(),
                **r,
            }
            saved.append(row)
        _MOCK_RECORDS[upload_id] = saved
        upload = _MOCK_UPLOADS.get(upload_id, {})
        upload.update({
            "parse_status": "parsed",
            "total_records": len(records),
            "parsed_at": datetime.now(timezone.utc).isoformat(),
        })
        return upload

    sb = _supabase()
    rows = [
        {
            "firm_id": firm_id,
            "upload_id": upload_id,
            "client_id": client_id,
            "financial_year": financial_year,
            "reconciliation_status": "unmatched",
            **r,
        }
        for r in records
    ]
    if rows:
        sb.table("form_26as_records").insert(rows).execute()

    update_res = sb.table("form_26as_uploads").update({
        "parse_status": "parsed",
        "total_records": len(records),
        "parsed_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", upload_id).execute()
    return update_res.data[0] if update_res.data else {}


# ── Reconciliation ─────────────────────────────────────────────────────────────

def _fy_window(financial_year: str) -> tuple[str, str]:
    """'2025-26' → ('2025-04-01', '2026-03-31'). Indian FY: 1 April to 31 March."""
    start_year = int(str(financial_year)[:4])
    return f"{start_year}-04-01", f"{start_year + 1}-03-31"


def _fy_month_firsts(financial_year: str) -> list[str]:
    """The FY's 12 period_month keys, in the form account_period_balances stores."""
    start_year = int(str(financial_year)[:4])
    months = [(start_year, m) for m in range(4, 13)] + [(start_year + 1, m) for m in range(1, 4)]
    return [f"{y:04d}-{m:02d}-01" for y, m in months]


def seed_mock_books(
    firm_id: str,
    client_id: str,
    financial_year: str,
    credits: list[dict],
    gl_control_paise: int | None = None,
) -> None:
    """Mock-mode stand-in for the receipts table and the TDS Receivable control.

    Mock mode is a real product mode (no SUPABASE_URL — local dev and demo), and
    the previous mock branch of run_reconciliation returned a hardcoded "every
    26AS row is missing from the books" regardless of input. That is not a
    simplification; it is a different answer from the one production gives, and
    it meant no test could exercise the matching at all. With this seeded, mock
    mode runs the identical engine.

    `credits` are BookCredit-shaped dicts: credit_id, tds_paise, deductor_name,
    deductor_tan, deductor_pan, credit_date, reference.
    """
    key = (firm_id, client_id, financial_year)
    _MOCK_BOOK_CREDITS[key] = [dict(c) for c in credits]
    _MOCK_GL_CONTROL[key] = (
        int(gl_control_paise) if gl_control_paise is not None
        else sum(int(c.get("tds_paise") or 0) for c in credits)
    )


def split_by_credit(records: list[dict]) -> tuple[list[dict], list[dict]]:
    """(rows that ARE a claimable credit, rows that are not).

    The second list is not discarded — a Part C advance-tax payment and a Part
    D refund are real facts about the client's year and the CA wants to see
    them. They are simply not TDS deducted from the client, so adding them to
    the 26AS side of a TDS reconciliation reports a variance against the book
    register that is exactly the advance tax, every year, for every client who
    paid any.
    """
    keep, aside = [], []
    for r in records:
        (keep if (r.get("record_type") or "tds_other") in CREDIT_RECORD_TYPES
         else aside).append(r)
    return keep, aside


def _entries_from_records(records: list[dict]) -> list[_m.Form26ASEntry]:
    return [
        _m.Form26ASEntry(
            entry_id=str(r["id"]),
            tds_paise=int(r.get("tds_deposited_paise") or 0),
            deductor_name=r.get("deductor_name") or "",
            deductor_tan=r.get("deductor_tan"),
            transaction_date=str(r.get("transaction_date") or "")[:10] or None,
            amount_credited_paise=int(r.get("amount_credited_paise") or 0),
            booking_status=r.get("booking_status"),
            part=r.get("part"),
            record_type=r.get("record_type"),
        )
        for r in records
    ]


def _load_book_credits(firm_id: str, client_id: str, financial_year: str) -> list[_m.BookCredit]:
    """The client's own record of TDS deducted FROM it, for the year.

    That is the `Dr TDS Receivable` leg of a receipt: the customer paid net of
    TDS and the withheld amount became a receivable claimable against the
    client's income tax. `receipts.customer_id` identifies the deductor, whose
    TAN (migration 291) is what 26AS names it by.

    NOT `tds_deductions` — that is tax the client deducted from its OWN vendors,
    which appears in each vendor's 26AS and never in the client's. The previous
    implementation read it, and additionally keyed the lookup on deductee_pan
    while reading it back by deductor_tan, so no row could ever match.
    """
    key = (firm_id, client_id, financial_year)
    if _USE_MOCK:
        return [
            _m.BookCredit(
                credit_id=str(c.get("credit_id") or c.get("id") or ""),
                tds_paise=int(c.get("tds_paise") or 0),
                deductor_name=c.get("deductor_name") or "",
                deductor_tan=c.get("deductor_tan"),
                deductor_pan=c.get("deductor_pan"),
                credit_date=c.get("credit_date"),
                source=c.get("source") or "receipt",
                reference=c.get("reference") or "",
            )
            for c in _MOCK_BOOK_CREDITS.get(key, [])
        ]

    sb = _supabase()
    start, end = _fy_window(financial_year)
    receipts = (
        sb.table("receipts")
        .select("id, receipt_no, receipt_date, tds_paise, customer_id")
        .eq("firm_id", firm_id)
        .eq("client_id", client_id)
        .gte("receipt_date", start)
        .lte("receipt_date", end)
        .gt("tds_paise", 0)
        .execute()
    ).data or []

    customer_ids = sorted({r["customer_id"] for r in receipts if r.get("customer_id")})
    customers: dict[str, dict] = {}
    if customer_ids:
        rows = (
            sb.table("customers")
            .select("id, name, pan, tan")
            .eq("firm_id", firm_id)
            .in_("id", customer_ids)
            .execute()
        ).data or []
        customers = {str(c["id"]): c for c in rows}

    credits: list[_m.BookCredit] = []
    for r in receipts:
        cust = customers.get(str(r.get("customer_id"))) or {}
        credits.append(_m.BookCredit(
            credit_id=str(r["id"]),
            tds_paise=int(r.get("tds_paise") or 0),
            deductor_name=cust.get("name") or "",
            deductor_tan=cust.get("tan"),
            deductor_pan=cust.get("pan"),
            credit_date=str(r.get("receipt_date") or "")[:10] or None,
            source="receipt",
            reference=str(r.get("receipt_no") or ""),
        ))
    return credits


def _gl_control_paise(firm_id: str, client_id: str, financial_year: str) -> int:
    """Net debits to the TDS Receivable control account for the year.

    Read from account_period_balances — 12 pre-aggregated monthly buckets, not
    journal lines. The line-by-line population above is receipts; a manual
    journal straight to TDS Receivable is not in it, and without this tie-out
    such an entry would sit silently outside the reconciliation with the summary
    still claiming to cover the books.
    """
    key = (firm_id, client_id, financial_year)
    if _USE_MOCK:
        return _MOCK_GL_CONTROL.get(key, 0)

    sb = _supabase()
    accounts = (
        sb.table("chart_of_accounts")
        .select("id")
        .eq("firm_id", firm_id)
        .eq("system_account_key", "tds_receivable")
        .eq("is_active", True)
        .execute()
    ).data or []
    if not accounts:
        # No control account resolved — report 0 rather than guessing by name,
        # so unreconciled_gl_paise reads as "nothing to tie to" rather than as a
        # fabricated difference.
        return 0

    buckets = (
        sb.table("account_period_balances")
        .select("account_id, period_month, debit_paise, credit_paise")
        .eq("firm_id", firm_id)
        .eq("client_id", client_id)
        .in_("account_id", [str(a["id"]) for a in accounts])
        .in_("period_month", _fy_month_firsts(financial_year))
        .execute()
    ).data or []
    return sum(
        int(b.get("debit_paise") or 0) - int(b.get("credit_paise") or 0)
        for b in buckets
    )


def _ai_insight_due(total_26as_paise: int, variance_paise: int, unsupported_paise: int) -> bool:
    """Whether the variance warrants an insight.

    Cross-multiplied rather than divided: integer paise arithmetic, never
    floating point (project rule), and no division by zero to guard separately.
    Any unsupported credit at all triggers regardless of size — a credit the
    deductor never reported is not claimable under Rule 37BA(1) whatever its
    value, so it is not a threshold question.
    """
    if unsupported_paise > 0:
        return True
    return variance_paise * 1000 > total_26as_paise * _MISMATCH_THRESHOLD_PCT_X10


def summarise(
    entries: list[_m.Form26ASEntry],
    credits: list[_m.BookCredit],
    gl_control_paise: int,
    tolerance_paise: int = 0,
) -> tuple[_m.ReconciliationResult, dict]:
    """Run the engine and shape its result into the summary row's columns.

    Pure — no I/O — so the whole summary is unit-testable without a database.
    """
    result = _m.reconcile(entries, credits, tolerance_paise=tolerance_paise)
    unsupported = _m.unsupported_credit_paise(result, credits)
    provisional_entries = [e for e in entries if not e.is_final]

    summary = {
        "total_26as_records": len(entries),
        "matched_count": result.matched_count,
        "mismatch_count": result.mismatch_count,
        "missing_in_books_count": result.missing_in_books_count,
        "not_in_26as_count": result.not_in_26as_count,
        "needs_confirmation_count": result.needs_confirmation_count,
        "unsupported_credit_paise": unsupported,
        "provisional_credit_count": len(provisional_entries),
        "provisional_credit_paise": _m.provisional_credit_paise(entries),
        "total_tds_26as_paise": result.total_26as_paise,
        # Over EVERY book credit, not just the matched ones. Summing only the
        # matched subset made the variance agree with itself by construction.
        "total_tds_books_paise": result.total_books_paise,
        "variance_paise": result.variance_paise,
        "net_variance_paise": result.net_variance_paise,
        "gl_control_paise": gl_control_paise,
        "unreconciled_gl_paise": gl_control_paise - result.total_books_paise,
        "books_source": BOOKS_SOURCE,
        "deductor_summary": [
            {
                "label": d.label, "tan": d.tan,
                "entry_count": d.entry_count, "credit_count": d.credit_count,
                "total_26as_paise": d.total_26as_paise,
                "total_books_paise": d.total_books_paise,
                "variance_paise": d.variance_paise,
            }
            for d in result.by_deductor
        ],
    }
    summary["ai_insight_triggered"] = _ai_insight_due(
        result.total_26as_paise, result.variance_paise, unsupported
    )
    return result, summary


_RECORD_STATUS = {
    _m.STATUS_MATCHED: "matched",
    _m.STATUS_VARIANCE: "mismatch",
    _m.STATUS_MISSING_IN_BOOKS: "unmatched",
}


def _record_patch(outcome: _m.EntryOutcome) -> dict:
    """The columns one 26AS record row gets from its outcome.

    Mock mode only — the real writes in _write_record_outcomes spell the same
    columns out inline so the backend column checker can read them.
    """
    return {
        "reconciliation_status": _RECORD_STATUS[outcome.status],
        "matched_receipt_id": outcome.matched_credit_id,
        "match_basis": outcome.basis,
        "variance_paise": outcome.variance_paise,
        "mismatch_reason": outcome.reason if outcome.status != _m.STATUS_MATCHED else None,
    }


def claimable_credit(firm_id: str, client_id: str, financial_year: str) -> dict:
    """What the client may claim off 26AS for the year — IT-31.

    Read straight from the latest PARSED upload rather than from a stored
    reconciliation, so the computation screen can prefill the moment the
    statement is in, without a reconciliation having been run first. The
    reconciliation is the check on the claim (Rule 37BA(1) — see
    domain/income_tax/claimable_credit), not its source.

    A year with no parsed 26AS reports `available: false` with a reason. NOT a
    zero: nobody having uploaded the statement and the client having no credit
    are opposite facts, and a prefilled 0 would quietly become a filed 0.
    """
    uploads = [u for u in list_uploads(firm_id, client_id, financial_year)
               if u.get("parse_status") == "parsed"]
    if not uploads:
        return {
            "available": False,
            "financial_year": financial_year,
            "reason": (f"No parsed Form 26AS for FY {financial_year}. Download it "
                       f"from TRACES and upload it here — the claim follows the "
                       f"deductor's statement (Rule 37BA(1)), so there is nothing "
                       f"to prefill until it is in."),
        }
    upload = uploads[0]
    records = _load_records(firm_id, upload["id"])
    out = _claimable.claimable_from_records(records).as_dict()
    out.update({
        "available": True,
        "financial_year": financial_year,
        "upload_id": upload["id"],
        "record_count": len(records),
        # The screen must be able to say WHICH statement the figure came off:
        # a prefilled number whose provenance is invisible is one a reviewer
        # cannot check.
        "uploaded_at": upload.get("created_at"),
    })
    return out


def run_reconciliation(
    firm_id: str,
    client_id: str,
    upload_id: str,
    financial_year: str,
    created_by: str,
) -> dict:
    """Reconcile one parsed 26AS upload against the client's books, both ways.

    26AS → books surfaces credits the deductor reported that the books do not
    show. books → 26AS surfaces credits the books claim that the deductor never
    reported — not claimable under Rule 37BA(1), and the direction the previous
    implementation could not report at all because it only iterated 26AS.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT. Nothing here files anything; the
    # output is a working paper for the CA to review before the return is filed.
    """
    records = _load_records(firm_id, upload_id)
    # TDS-19. Only the parts that ARE a credit to this client go into a TDS
    # reconciliation. Part C is tax the client paid themselves and Part D is a
    # refund already received; both used to be summed into the 26AS side and
    # matched against the book TDS register, so every client who paid any
    # advance tax showed a variance of exactly that amount, every year. The
    # rest are reported beside the result rather than dropped — see
    # split_by_credit.
    credit_records, other_records = split_by_credit(records)
    entries = _entries_from_records(credit_records)
    credits = _load_book_credits(firm_id, client_id, financial_year)
    gl_control = _gl_control_paise(firm_id, client_id, financial_year)
    result, summary = summarise(entries, credits, gl_control)
    # Reported BESIDE the summary, never inside it: `summary` is spread
    # straight into the form_26as_reconciliations INSERT below, so a key that
    # is not a column of that table makes the whole reconciliation fail on the
    # live database while passing in mock mode — the exact shape of the bug
    # migration 291 was written to repair on this same table.
    aside = {
        "not_a_tds_credit": [
            {"part": r.get("part"), "record_type": r.get("record_type"),
             "amount_paise": int(r.get("tds_deposited_paise") or 0),
             "deductor_name": r.get("deductor_name") or ""}
            for r in other_records
        ],
        "not_a_tds_credit_paise": sum(
            int(r.get("tds_deposited_paise") or 0) for r in other_records),
        # WHAT THE RETURN MAY CLAIM (IT-31), computed from the SAME records and
        # returned beside the summary for the same reason as the block above:
        # `summary` is spread into the form_26as_reconciliations INSERT, so a
        # key that is not a column of that table fails the whole reconciliation
        # on the live database while passing in mock mode.
        #
        # From ALL the records, not `credit_records`: three of the four figures
        # come from the parts the matcher never sees — Part C is the client's
        # own advance tax and Part D a refund already received.
        "claimable": _claimable.claimable_from_records(records).as_dict(),
    }

    recon_row = {
        "firm_id": firm_id,
        "client_id": client_id,
        "upload_id": upload_id,
        "financial_year": financial_year,
        "status": "completed",
        "completed_by": created_by,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "created_by": created_by,
        **summary,
    }

    if _USE_MOCK:
        for outcome in result.entry_outcomes:
            for row in _MOCK_RECORDS.get(upload_id, []):
                if str(row.get("id")) == outcome.entry_id:
                    row.update(_record_patch(outcome))
        recon = {"id": str(uuid4()),
                 "created_at": datetime.now(timezone.utc).isoformat(),
                 **recon_row}
        _MOCK_RECONS[recon["id"]] = recon
        return {**recon, **aside}

    sb = _supabase()
    _write_record_outcomes(sb, result.entry_outcomes)
    res = sb.table("form_26as_reconciliations").insert(recon_row).execute()
    stored = res.data[0] if res.data else recon_row

    if summary["ai_insight_triggered"]:
        _trigger_26as_ai_insight(
            firm_id, client_id, financial_year,
            summary["variance_paise"], stored.get("id", ""),
            summary["unsupported_credit_paise"],
        )
    return {**stored, **aside}


def _load_records(firm_id: str, upload_id: str) -> list[dict]:
    if _USE_MOCK:
        return [r for r in _MOCK_RECORDS.get(upload_id, []) if r.get("firm_id") == firm_id]
    sb = _supabase()
    return (
        sb.table("form_26as_records")
        .select("*")
        .eq("upload_id", upload_id)
        .eq("firm_id", firm_id)
        .execute()
    ).data or []


def _write_record_outcomes(sb, outcomes: list[_m.EntryOutcome]) -> None:
    """Write each 26AS row's outcome back, batching the rows that share a payload.

    Unmatched rows all carry the identical patch, so they go in one call; matched
    and variance rows carry a per-row receipt id and variance and cannot be
    batched that way. apps/api runs in Singapore and Postgres is in Mumbai, so
    each call is a cross-region round trip and the unmatched batch is the case
    that grows (a client whose customers have no TAN recorded yet).
    """
    unmatched = [o for o in outcomes if o.status == _m.STATUS_MISSING_IN_BOOKS]
    if unmatched:
        # Written out column by column rather than through _record_patch:
        # tests/test_backend_columns_exist_pg.py parses these calls statically
        # and cannot see through a helper's return value, so a payload built
        # elsewhere is a column reference nothing checks.
        sb.table("form_26as_records").update({
            "reconciliation_status": "unmatched",
            "matched_receipt_id": None,
            "match_basis": None,
            "variance_paise": 0,
            "mismatch_reason": unmatched[0].reason,
        }).in_("id", [o.entry_id for o in unmatched]).execute()

    for outcome in outcomes:
        if outcome.status == _m.STATUS_MISSING_IN_BOOKS:
            continue
        sb.table("form_26as_records").update({
            "reconciliation_status": _RECORD_STATUS[outcome.status],
            "matched_receipt_id": outcome.matched_credit_id,
            "match_basis": outcome.basis,
            "variance_paise": outcome.variance_paise,
            "mismatch_reason": (
                None if outcome.status == _m.STATUS_MATCHED else outcome.reason
            ),
        }).eq("id", outcome.entry_id).execute()


def _trigger_26as_ai_insight(
    firm_id: str,
    client_id: str,
    financial_year: str,
    variance_paise: int,
    recon_id: str,
    unsupported_credit_paise: int = 0,
) -> None:
    """Create AI insight for a significant 26AS mismatch.

    Unsupported credit is named separately because it is a different problem
    from a variance: it is credit the books claim that the deductor never
    reported, so under Rule 37BA(1) it cannot be claimed in the return until the
    deductor files a correction. A CA acts on that by chasing the deductor, not
    by adjusting the books.
    """
    detail = f"₹{variance_paise // 100:,} variance"
    if unsupported_credit_paise > 0:
        detail += (f", of which ₹{unsupported_credit_paise // 100:,} is credit in the "
                   f"books that 26AS does not report")
    try:
        from services.timeline_service import timeline_service
        timeline_service.log(
            client_id=client_id,
            category="tax",
            action="26as_reconciliation_mismatch",
            description=f"26AS reconciliation FY {financial_year}: {detail} — review before filing",
            severity="warning",
            metadata={
                "recon_id": recon_id,
                "variance_paise": variance_paise,
                "unsupported_credit_paise": unsupported_credit_paise,
            },
        )
    except Exception:
        _logger.warning("Failed to log 26AS mismatch timeline event", exc_info=True)


def list_uploads(firm_id: str, client_id: str, financial_year: str | None = None) -> list[dict]:
    if _USE_MOCK:
        uploads = [u for u in _MOCK_UPLOADS.values()
                   if u["firm_id"] == firm_id and u["client_id"] == client_id
                   and u.get("source", UPLOAD_SOURCE) == UPLOAD_SOURCE]
        if financial_year:
            uploads = [u for u in uploads if u["financial_year"] == financial_year]
        return uploads

    sb = _supabase()
    q = (sb.table("form_26as_uploads").select("*")
           .eq("firm_id", firm_id).eq("client_id", client_id)
           .eq("source", UPLOAD_SOURCE))
    if financial_year:
        q = q.eq("financial_year", financial_year)
    res = q.order("uploaded_at", desc=True).execute()
    return res.data or []


def get_reconciliation(firm_id: str, client_id: str, financial_year: str) -> dict | None:
    if _USE_MOCK:
        for r in _MOCK_RECONS.values():
            if (r["firm_id"] == firm_id and r["client_id"] == client_id
                    and r["financial_year"] == financial_year):
                return r
        return None

    sb = _supabase()
    res = sb.table("form_26as_reconciliations").select("*").eq("firm_id", firm_id).eq(
        "client_id", client_id
    ).eq("financial_year", financial_year).order("created_at", desc=True).limit(1).execute()
    return res.data[0] if res.data else None
