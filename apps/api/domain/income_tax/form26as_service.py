"""
Form 26AS Reconciliation Module.
IT Act 1961 Section 203AA — Annual Tax Statement (Form 26AS).
Matches 26AS TDS records against firm's TDS ledger entries.

# CA REVIEW REQUIRED — Reconciliation output must be reviewed before filing
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from uuid import uuid4

_logger = logging.getLogger("caflow.form26as")
_USE_MOCK = not os.environ.get("SUPABASE_URL")

_MOCK_UPLOADS: dict[str, dict] = {}
_MOCK_RECORDS: dict[str, list] = {}
_MOCK_RECONS: dict[str, dict] = {}

# Mismatch threshold — AI insight triggered if variance > 1% of 26AS TDS
MISMATCH_THRESHOLD_PCT = 1.0


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
        "uploaded_by": uploaded_by,
    }
    res = sb.table("form_26as_uploads").insert(row).execute()
    return res.data[0] if res.data else row


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
    """Parse amount string to paise (integer). Input is in rupees with commas."""
    cleaned = re.sub(r"[^\d.]", "", s.strip())
    if not cleaned:
        return 0
    rupees = float(cleaned)
    return round(rupees * 100)  # convert to paise


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

def run_reconciliation(
    firm_id: str,
    client_id: str,
    upload_id: str,
    financial_year: str,
    created_by: str,
) -> dict:
    """
    Match 26AS records against TDS ledger.
    Detects: missing credits, duplicates, ledger mismatches.
    Triggers AI insight if variance exceeds threshold.
    """
    if _USE_MOCK:
        records = _MOCK_RECORDS.get(upload_id, [])
        total_26as_paise = sum(r.get("tds_deposited_paise", 0) for r in records)
        # Mock: no books data, so all unmatched
        recon = {
            "id": str(uuid4()),
            "firm_id": firm_id,
            "client_id": client_id,
            "upload_id": upload_id,
            "financial_year": financial_year,
            "total_26as_records": len(records),
            "matched_count": 0,
            "mismatch_count": 0,
            "missing_in_books_count": len(records),
            "total_tds_26as_paise": total_26as_paise,
            "total_tds_books_paise": 0,
            "variance_paise": total_26as_paise,
            "ai_insight_triggered": False,
            "health_penalty_applied": False,
            "status": "completed",
            "created_by": created_by,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        _MOCK_RECONS[recon["id"]] = recon
        return recon

    sb = _supabase()

    # Load 26AS records
    recs_res = sb.table("form_26as_records").select("*").eq(
        "upload_id", upload_id
    ).eq("firm_id", firm_id).execute()
    records = recs_res.data or []

    # Load TDS deductions from books
    books_res = sb.table("tds_deductions").select("*").eq(
        "firm_id", firm_id
    ).eq("client_id", client_id).execute()
    books = books_res.data or []

    # Build lookup: (deductor_tan, period) → amount
    books_by_tan: dict[str, list[dict]] = {}
    for b in books:
        tan = (b.get("deductee_pan") or "").strip().upper()
        books_by_tan.setdefault(tan, []).append(b)

    matched = 0
    mismatch = 0
    missing = 0
    total_26as_paise = 0
    total_books_paise = 0

    for rec in records:
        total_26as_paise += rec.get("tds_deposited_paise", 0)
        tan = (rec.get("deductor_tan") or "").upper()
        book_matches = books_by_tan.get(tan, [])
        rec_id = rec["id"]

        if not book_matches:
            missing += 1
            sb.table("form_26as_records").update({
                "reconciliation_status": "unmatched",
                "mismatch_reason": "No matching TDS entry in books",
            }).eq("id", rec_id).execute()
            continue

        # Best match by amount proximity
        best = min(
            book_matches,
            key=lambda b: abs(b.get("tds_amount_paise", 0) - rec.get("tds_deposited_paise", 0)),
        )
        total_books_paise += best.get("tds_amount_paise", 0)
        variance = abs(best.get("tds_amount_paise", 0) - rec.get("tds_deposited_paise", 0))

        if variance == 0:
            matched += 1
            sb.table("form_26as_records").update({
                "reconciliation_status": "matched",
                "matched_tds_deduction_id": best["id"],
            }).eq("id", rec_id).execute()
        else:
            mismatch += 1
            sb.table("form_26as_records").update({
                "reconciliation_status": "mismatch",
                "matched_tds_deduction_id": best["id"],
                "mismatch_reason": f"Amount variance: ₹{variance / 100:.2f}",
            }).eq("id", rec_id).execute()

    variance_total = abs(total_26as_paise - total_books_paise)
    ai_triggered = (
        total_26as_paise > 0
        and (variance_total / total_26as_paise * 100) > MISMATCH_THRESHOLD_PCT
    )

    recon_row = {
        "firm_id": firm_id,
        "client_id": client_id,
        "upload_id": upload_id,
        "financial_year": financial_year,
        "total_26as_records": len(records),
        "matched_count": matched,
        "mismatch_count": mismatch,
        "missing_in_books_count": missing,
        "total_tds_26as_paise": total_26as_paise,
        "total_tds_books_paise": total_books_paise,
        "variance_paise": variance_total,
        "ai_insight_triggered": ai_triggered,
        "status": "completed",
        "completed_by": created_by,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "created_by": created_by,
    }
    res = sb.table("form_26as_reconciliations").insert(recon_row).execute()
    result = res.data[0] if res.data else recon_row

    # Trigger AI insight if variance exceeds threshold
    if ai_triggered:
        _trigger_26as_ai_insight(firm_id, client_id, financial_year, variance_total, result["id"])

    return result


def _trigger_26as_ai_insight(
    firm_id: str,
    client_id: str,
    financial_year: str,
    variance_paise: int,
    recon_id: str,
) -> None:
    """Create AI insight for significant 26AS mismatch."""
    try:
        from services.timeline_service import timeline_service
        timeline_service.log(
            client_id=client_id,
            category="tax",
            action="26as_reconciliation_mismatch",
            description=f"26AS reconciliation found ₹{variance_paise / 100:,.0f} variance — AI insight created",
            severity="warning",
            metadata={"recon_id": recon_id, "variance_paise": variance_paise},
        )
    except Exception:
        _logger.warning("Failed to log 26AS mismatch timeline event", exc_info=True)


def list_uploads(firm_id: str, client_id: str, financial_year: str | None = None) -> list[dict]:
    if _USE_MOCK:
        uploads = [u for u in _MOCK_UPLOADS.values()
                   if u["firm_id"] == firm_id and u["client_id"] == client_id]
        if financial_year:
            uploads = [u for u in uploads if u["financial_year"] == financial_year]
        return uploads

    sb = _supabase()
    q = sb.table("form_26as_uploads").select("*").eq("firm_id", firm_id).eq("client_id", client_id)
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
