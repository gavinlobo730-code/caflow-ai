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

import logging
import os
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from uuid import uuid4

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
            "uploaded_by": uploaded_by,
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
        # form_26as_uploads has no separate uploaded_by column — created_by
        # is the real column (migration 052) and means the same thing here.
        "created_by": uploaded_by,
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


def parse_26as_text(raw_text: str) -> list[dict]:
    """
    Parse Form 26AS plain text (downloaded from TRACES portal).
    Handles standard Part A (TDS on salary), Part B (TDS other), Part C (advance/self-assessment).
    Returns list of parsed record dicts.
    """
    records: list[dict] = []
    current_part = None
    lines = raw_text.strip().splitlines()

    for line in lines:
        line = line.strip()
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

        # Try to parse data rows (tab/pipe delimited)
        cols = re.split(r"\t|\|", line)
        if len(cols) < 5:
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
        except (ValueError, IndexError):
            _logger.debug("Skipping unparseable line: %s", line[:80])

    return records


def _infer_record_type(part: str | None) -> str:
    mapping = {
        "A": "tds_salary",
        "B": "tds_other",
        "C": "advance_tax",
        "D": "self_assessment",
        "F": "tds_other",
    }
    return mapping.get(part or "A", "tds_other")


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
    entries = _entries_from_records(records)
    credits = _load_book_credits(firm_id, client_id, financial_year)
    gl_control = _gl_control_paise(firm_id, client_id, financial_year)
    result, summary = summarise(entries, credits, gl_control)

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
        return recon

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
    return stored


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
