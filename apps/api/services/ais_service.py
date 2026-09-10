"""The Annual Information Statement, kept — IT Act §285BB.

WHAT THIS REPLACED

    apps/web/app/income-tax/ais/page.tsx held the whole feature: a JSON
    parser, a transaction table and a books-comparison grid, in React state,
    with no call to anything. Refresh and it was gone. Its own footer said
    "stored locally in your browser only", which was not true either — it was
    not stored at all, not even in localStorage.

    §285BB is the department's statement of what OTHERS reported about the
    taxpayer. It is what a §143(1)(a) adjustment is raised from and what a
    §143(3) scrutiny starts with, so a CA's working against it is a working
    paper, and a working paper that cannot be re-read tomorrow is not one.

THE THREE REFUSALS THIS MODULE MAKES, AND WHY EACH IS A REFUSAL

    1. IT COMPUTES NO TAX. The screen this replaces showed "Est. Tax Impact
       (30%)" — undeclared amount times 30%. There is no basis for 30%: the
       client may be an individual on the §115BAC slabs paying 5%, a firm at
       30% plus surcharge and cess, a company at 22% under §115BAA, or the
       receipt may not be income at all (a maturity, a redemption of capital,
       a gift already taxed). It is the same fabrication as the 85% book
       income removed from detect_document_risks in the previous commit, and
       it was worse: it was displayed as a rupee figure in an orange box.

    2. AN UNREVIEWED LINE IS NOT A FINDING. The screen derived the status
       from a blank box: no books figure typed meant "Not in Books", which
       then went into "Est. Undeclared Amount" and lit a red "Discrepancies
       Found — CA Review Required" banner. So a statement uploaded and not
       yet worked through reported every line as undeclared income. NULL
       books_amount_paise is 'not_reviewed' here and is counted separately
       from everything else.

    3. A CONCLUSION CANNOT CONTRADICT ITS OWN WORKING. 'matched' against a
       differing figure, 'not_in_books' against a non-nil figure, and
       'explained' with no explanation are all refused rather than stored.

WHAT IT DOES DO THAT THE SCREEN COULD NOT

    Carries a CA's working forward when a fresh AIS is published mid-review —
    but ONLY where the line is identical. A line whose amount moved is a
    different line and its working is not reused. See _carry_forward.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from domain.income_tax.ais import (
    TRANSACTION_TYPES,
    AISRecord,
    ParsedAIS,
    classify,
    file_hash,
    parse,
)

_logger = logging.getLogger("caflow.ais")
_USE_MOCK = not os.environ.get("SUPABASE_URL")

# Mock-mode stores. Same shape as the tables migration 352 creates, so the
# service body below is one code path with two backends rather than two
# implementations of the feature.
_MOCK_UPLOADS: dict[str, dict] = {}
_MOCK_RECORDS: dict[str, dict] = {}
_MOCK_RECONS: dict[str, dict] = {}

STATUSES = ("not_reviewed", "matched", "amount_mismatch", "not_in_books",
            "explained")

# The identity of an AIS line for carry-forward. The AMOUNT is part of it on
# purpose: a line whose figure moved between two downloads is a different
# statement about the client, and a CA's earlier "agreed" was agreement with
# the earlier figure.
_LINE_KEY_FIELDS = ("information_source", "information_label", "payer",
                    "amount_paise", "tds_deducted_paise")


class AISRefused(Exception):
    """A refusal the CA needs to read, not a 500."""


def _supabase():
    from core.supabase_client import get_supabase
    return get_supabase()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _line_key(row: dict) -> tuple:
    return tuple(row.get(f) for f in _LINE_KEY_FIELDS)


# ── Upload ─────────────────────────────────────────────────────────────────

def upload_statement(
    *,
    firm_id: str,
    client_id: str,
    assessment_year: str,
    raw: str,
    file_name: Optional[str] = None,
    uploaded_by: Optional[str] = None,
) -> dict:
    """Parse one AIS JSON and keep it, with its lines.

    A re-upload of the SAME bytes for the same client and year returns the
    upload already held rather than making a second one — a CA re-downloading
    to check is the ordinary case, and two identical statements on the screen
    is a reconciliation that has to be done twice.

    A file that parsed with problems is STILL kept, with the problems on the
    row. The alternative — refusing the whole file because one line of twenty
    carried an unreadable amount — throws away the nineteen that read, and a
    CA cannot chase what they cannot see. What is not done is call it
    complete: `problems` is non-empty and every caller shows it.
    """
    parsed: ParsedAIS = parse(raw)
    if not parsed.records and parsed.problems:
        # Nothing at all was read. Persisting a zero-line statement would put
        # "this client had no reported transactions" on the screen, which is
        # the opposite of what happened.
        raise AISRefused(" ".join(parsed.problems))

    digest = file_hash(raw)
    existing = _find_upload_by_hash(firm_id, client_id, assessment_year, digest)
    if existing:
        return get_statement(firm_id=firm_id, client_id=client_id,
                             assessment_year=assessment_year,
                             upload_id=existing["id"])

    upload = {
        "firm_id": firm_id,
        "client_id": client_id,
        "assessment_year": assessment_year,
        "pan": parsed.pan,
        "taxpayer_name": parsed.taxpayer_name,
        "file_name": file_name,
        "file_hash": digest,
        "record_count": len(parsed.records),
        "total_amount_paise": parsed.total_amount_paise,
        "total_tds_paise": parsed.total_tds_paise,
        "problems": parsed.problems,
        "uploaded_by": uploaded_by,
    }
    upload_id = _insert_upload(upload)

    rows = [_record_row(firm_id, client_id, upload_id, assessment_year, r)
            for r in parsed.records]
    _insert_records(rows)
    _carry_forward(firm_id, client_id, assessment_year, upload_id)
    return get_statement(firm_id=firm_id, client_id=client_id,
                         assessment_year=assessment_year, upload_id=upload_id)


def _record_row(firm_id, client_id, upload_id, ay, r: AISRecord) -> dict:
    return {
        "firm_id": firm_id,
        "client_id": client_id,
        "upload_id": upload_id,
        "assessment_year": ay,
        "information_source": r.information_source,
        "information_label": r.information_label,
        "transaction_type": r.transaction_type,
        "payer": r.payer,
        "amount_paise": r.amount_paise,
        "tds_deducted_paise": r.tds_deducted_paise,
        "source": r.source,
    }


def _carry_forward(firm_id: str, client_id: str, ay: str, upload_id: str) -> None:
    """Move a half-done working onto the statement that superseded it.

    The migration's whole reason for three tables: a fresh AIS is published
    while the review is half done, and the earlier working must not vanish
    with the file it started from. What carries is an IDENTICAL line —
    identical source, wording, payer, amount and TDS. A line whose amount
    moved does NOT carry, because agreeing ₹4,50,000 to the books is not
    agreeing ₹5,20,000 to them, and silently re-badging it as agreed is how a
    reconciliation ends up asserting something nobody checked.
    """
    new_rows = _records_for_upload(firm_id, upload_id)
    if not new_rows:
        return
    prior = [r for r in _records_for_year(firm_id, client_id, ay)
             if r.get("upload_id") != upload_id]
    if not prior:
        return
    workings = {w["record_id"]: w
                for w in _recons_for_year(firm_id, client_id, ay)}
    by_key: dict[tuple, dict] = {}
    for row in prior:
        w = workings.get(row["id"])
        if w and w.get("status") != "not_reviewed":
            by_key.setdefault(_line_key(row), w)

    carried = []
    for row in new_rows:
        w = by_key.get(_line_key(row))
        if not w:
            continue
        carried.append({
            "firm_id": firm_id,
            "client_id": client_id,
            "record_id": row["id"],
            "assessment_year": ay,
            "books_amount_paise": w.get("books_amount_paise"),
            "status": w.get("status"),
            "note": w.get("note"),
            "reviewed_by": w.get("reviewed_by"),
            "reviewed_at": w.get("reviewed_at"),
        })
    if carried:
        _insert_recons(carried)


# ── The CA's working ───────────────────────────────────────────────────────

def save_working(
    *,
    firm_id: str,
    record_id: str,
    books_amount_paise: Optional[int],
    status: Optional[str] = None,
    note: Optional[str] = None,
    reviewed_by: Optional[str] = None,
) -> dict:
    """One line's working, checked against itself before it is stored.

    `books_amount_paise` NULL means nobody has looked. It is not nil, and the
    difference matters: nil is a finding (the payer reported income the books
    do not carry) and unreviewed is an absence of one.
    """
    record = _get_record(firm_id, record_id)
    if not record:
        raise AISRefused("Record not found")

    if status is not None and status not in STATUSES:
        raise AISRefused(
            f"{status!r} is not a reconciliation status. One of: "
            f"{', '.join(STATUSES)}.")

    if books_amount_paise is not None and not isinstance(books_amount_paise, int):
        raise AISRefused("The books figure must be integer paise.")
    if books_amount_paise is not None and books_amount_paise < 0:
        raise AISRefused(
            "A negative books figure is not a books figure. Where the books "
            "carry nothing for this line, mark it Not in books.")

    ais_amount = int(record.get("amount_paise") or 0)

    if books_amount_paise is None:
        # Two readings of "no figure": the CA has not looked (not_reviewed),
        # or the CA looked and the books hold nothing (not_in_books, which
        # IS a figure — nil — and is stored as one).
        if status in (None, "not_reviewed"):
            resolved, books = "not_reviewed", None
        elif status == "not_in_books":
            resolved, books = "not_in_books", 0
        else:
            raise AISRefused(
                f"{status} needs a books figure. Enter what the books carry "
                f"for this line, or mark it Not in books.")
    else:
        books = int(books_amount_paise)
        derived = "matched" if books == ais_amount else "amount_mismatch"
        if status in (None, "not_reviewed", "matched", "amount_mismatch"):
            # The status is DERIVED from the two figures, never asserted over
            # them. A CA who types 4,50,000 against an AIS 5,20,000 and picks
            # "Matched" from a dropdown has a working that contradicts its own
            # conclusion, and the conclusion is what the next reader believes.
            if status in ("matched", "amount_mismatch") and status != derived:
                raise AISRefused(
                    f"Those two figures are {'not ' if derived == 'amount_mismatch' else ''}"
                    f"the same, so this line is {derived.replace('_', ' ')}. "
                    f"To record why a difference is acceptable, mark it "
                    f"Explained and say why.")
            resolved = derived
        elif status == "not_in_books":
            if books != 0:
                raise AISRefused(
                    "Not in books means the books carry nothing for this "
                    "line. Clear the books figure, or pick another status.")
            resolved = "not_in_books"
        else:  # explained
            resolved = "explained"

    if resolved == "explained" and not (note or "").strip():
        raise AISRefused(
            "Explained needs the explanation. A difference marked resolved "
            "with no working is a conclusion the next reader cannot check — "
            "and this is the working paper a §143(1)(a) adjustment is "
            "answered from.")

    row = {
        "firm_id": firm_id,
        "client_id": record["client_id"],
        "record_id": record_id,
        "assessment_year": record["assessment_year"],
        "books_amount_paise": books,
        "status": resolved,
        "note": (note or None),
        "reviewed_by": reviewed_by if resolved != "not_reviewed" else None,
        "reviewed_at": _now() if resolved != "not_reviewed" else None,
    }
    return _upsert_recon(row)


# ── A line the file did not carry ──────────────────────────────────────────

def add_manual_record(
    *,
    firm_id: str,
    client_id: str,
    upload_id: str,
    transaction_type: str,
    payer: str,
    amount_paise: int,
    tds_deducted_paise: int = 0,
    information_label: Optional[str] = None,
) -> dict:
    """A line a CA knows about that the statement does not carry.

    Kept with source='manual' and never merged into the parsed lines, because
    the two are different evidence: one is what the department published and
    one is what a CA asserts. The screen labels them apart for the same
    reason.
    """
    upload = _get_upload(firm_id, upload_id)
    if not upload:
        raise AISRefused("Statement not found")
    if upload["client_id"] != client_id:
        raise AISRefused("Statement not found")
    if transaction_type not in TRANSACTION_TYPES:
        raise AISRefused(
            f"{transaction_type!r} is not a transaction type. One of: "
            f"{', '.join(TRANSACTION_TYPES)}.")
    if not str(payer or "").strip():
        raise AISRefused("A line needs the payer or deductor it came from.")
    for name, value in (("amount", amount_paise), ("TDS", tds_deducted_paise)):
        if not isinstance(value, int) or value < 0:
            raise AISRefused(f"The {name} must be integer paise, and not negative.")

    label = (information_label or "").strip() or transaction_type
    row = _record_row(firm_id, client_id, upload_id, upload["assessment_year"],
                      AISRecord(
                          information_source="Added by the firm",
                          information_label=label,
                          transaction_type=transaction_type,
                          payer=str(payer).strip(),
                          amount_paise=amount_paise,
                          tds_deducted_paise=tds_deducted_paise,
                          source="manual"))
    saved = _insert_records([row])[0]
    _restate_totals(firm_id, upload_id)
    return saved


def delete_record(*, firm_id: str, record_id: str) -> dict:
    """Only a line the firm added.

    A parsed line is what the Income-tax Department published about this
    client. Deleting it makes the statement on the screen disagree with the
    statement on the portal, which is the one the assessing officer holds.
    Where a parsed line is wrong, the remedy is the portal's own feedback
    facility, not a delete here.
    """
    record = _get_record(firm_id, record_id)
    if not record:
        raise AISRefused("Record not found")
    if record.get("source") != "manual":
        raise AISRefused(
            "This line came from the statement the department published "
            "(IT Act §285BB), so it cannot be removed here — the screen would "
            "then disagree with the portal. Submit feedback on the AIS at "
            "incometax.gov.in if the line is wrong.")
    _delete_record(firm_id, record_id)
    _restate_totals(firm_id, record["upload_id"])
    return {"deleted": record_id}


# ── Reading it back ────────────────────────────────────────────────────────

def get_record(firm_id: str, record_id: str) -> Optional[dict]:
    """One line, for a caller that holds only its id.

    The delete route is row-addressed and carries no client_id, so the mount
    guard cannot fire on it; it resolves the row here and scopes on the
    client the row names.
    """
    return _get_record(firm_id, record_id)


def list_uploads(firm_id: str, client_id: str,
                 assessment_year: Optional[str] = None) -> list[dict]:
    rows = _uploads_for(firm_id, client_id, assessment_year)
    return sorted(rows, key=lambda r: r.get("created_at") or "", reverse=True)


def get_statement(*, firm_id: str, client_id: str, assessment_year: str,
                  upload_id: Optional[str] = None) -> dict:
    """One statement, its lines, each line's working, and the summary."""
    uploads = list_uploads(firm_id, client_id, assessment_year)
    if upload_id:
        upload = next((u for u in uploads if u["id"] == upload_id), None)
    else:
        upload = uploads[0] if uploads else None
    if not upload:
        return {"upload": None, "records": [], "summary": summarise([]),
                "uploads": uploads}

    records = _records_for_upload(firm_id, upload["id"])
    workings = {w["record_id"]: w
                for w in _recons_for_year(firm_id, client_id, assessment_year)}
    lines = []
    for row in records:
        w = workings.get(row["id"]) or {}
        lines.append({
            **row,
            "books_amount_paise": w.get("books_amount_paise"),
            "status": w.get("status") or "not_reviewed",
            "note": w.get("note"),
            "reviewed_at": w.get("reviewed_at"),
        })
    lines.sort(key=lambda r: (r.get("transaction_type") or "",
                              -int(r.get("amount_paise") or 0)))
    return {"upload": upload, "records": lines, "summary": summarise(lines),
            "uploads": uploads}


def summarise(lines: list[dict]) -> dict:
    """What the statement says, what has been looked at, and what is open.

    NO TAX FIGURE. The screen this replaces multiplied the difference by 30%
    and headed it "Est. Tax Impact (30%)". Nothing here knows the client's
    regime, entity type, slab or whether the receipt is income at all, and a
    rupee figure in an orange box is read as an answer whatever the word
    "Est." in front of it says. `tax_impact` is deliberately absent, and
    `tax_impact_refused` says why in a sentence the screen prints.
    """
    total = sum(int(r.get("amount_paise") or 0) for r in lines)
    tds = sum(int(r.get("tds_deducted_paise") or 0) for r in lines)
    by_status: dict[str, int] = {s: 0 for s in STATUSES}
    for r in lines:
        by_status[r.get("status") or "not_reviewed"] = (
            by_status.get(r.get("status") or "not_reviewed", 0) + 1)

    # The two OPEN questions, kept apart. Neither is a tax figure and neither
    # includes an unreviewed line.
    not_in_books_paise = sum(
        int(r.get("amount_paise") or 0) for r in lines
        if r.get("status") == "not_in_books")
    shortfall_paise = sum(
        max(0, int(r.get("amount_paise") or 0) - int(r.get("books_amount_paise") or 0))
        for r in lines if r.get("status") == "amount_mismatch")

    return {
        "line_count": len(lines),
        "total_amount_paise": total,
        "total_tds_paise": tds,
        "by_status": by_status,
        "not_reviewed_count": by_status.get("not_reviewed", 0),
        "not_in_books_paise": not_in_books_paise,
        "shortfall_paise": shortfall_paise,
        "open_paise": not_in_books_paise + shortfall_paise,
        "tax_impact_refused": (
            "No tax figure is estimated here. What this difference costs "
            "depends on the client's regime, entity type and slab, and on "
            "whether the receipt is income at all — none of which this "
            "statement carries. Run the tax computation once the books are "
            "corrected."
        ),
        "by_type": _by_type(lines),
    }


def _by_type(lines: list[dict]) -> list[dict]:
    out: dict[str, dict] = {}
    for r in lines:
        t = r.get("transaction_type") or "Other"
        b = out.setdefault(t, {"transaction_type": t, "line_count": 0,
                               "amount_paise": 0, "tds_paise": 0})
        b["line_count"] += 1
        b["amount_paise"] += int(r.get("amount_paise") or 0)
        b["tds_paise"] += int(r.get("tds_deducted_paise") or 0)
    return sorted(out.values(), key=lambda b: -b["amount_paise"])


# ── I/O, both backends ─────────────────────────────────────────────────────

def _insert_upload(row: dict) -> str:
    if _USE_MOCK:
        row = {"id": str(uuid4()), "created_at": _now(), **row}
        _MOCK_UPLOADS[row["id"]] = row
        return row["id"]
    res = _supabase().table("ais_uploads").insert(row).execute()
    return (res.data or [{}])[0].get("id")


def _find_upload_by_hash(firm_id, client_id, ay, digest) -> Optional[dict]:
    if _USE_MOCK:
        for u in _MOCK_UPLOADS.values():
            if (u["firm_id"] == firm_id and u["client_id"] == client_id
                    and u["assessment_year"] == ay and u.get("file_hash") == digest):
                return u
        return None
    res = (_supabase().table("ais_uploads")
           .select("*")
           .eq("firm_id", firm_id).eq("client_id", client_id)
           .eq("assessment_year", ay).eq("file_hash", digest)
           .limit(1).execute())
    return (res.data or [None])[0]


def _get_upload(firm_id: str, upload_id: str) -> Optional[dict]:
    if _USE_MOCK:
        u = _MOCK_UPLOADS.get(upload_id)
        return u if u and u["firm_id"] == firm_id else None
    res = (_supabase().table("ais_uploads").select("*")
           .eq("id", upload_id).eq("firm_id", firm_id).limit(1).execute())
    return (res.data or [None])[0]


def _uploads_for(firm_id, client_id, ay) -> list[dict]:
    if _USE_MOCK:
        return [dict(u) for u in _MOCK_UPLOADS.values()
                if u["firm_id"] == firm_id and u["client_id"] == client_id
                and (ay is None or u["assessment_year"] == ay)]
    q = (_supabase().table("ais_uploads").select("*")
         .eq("firm_id", firm_id).eq("client_id", client_id))
    if ay:
        q = q.eq("assessment_year", ay)
    return q.order("created_at", desc=True).execute().data or []


def _insert_records(rows: list[dict]) -> list[dict]:
    if not rows:
        return []
    if _USE_MOCK:
        saved = []
        for r in rows:
            r = {"id": str(uuid4()), "created_at": _now(), **r}
            _MOCK_RECORDS[r["id"]] = r
            saved.append(r)
        return saved
    return _supabase().table("ais_records").insert(rows).execute().data or []


def _records_for_upload(firm_id: str, upload_id: str) -> list[dict]:
    if _USE_MOCK:
        return [dict(r) for r in _MOCK_RECORDS.values()
                if r["firm_id"] == firm_id and r["upload_id"] == upload_id]
    return (_supabase().table("ais_records").select("*")
            .eq("firm_id", firm_id).eq("upload_id", upload_id)
            .execute().data) or []


def _records_for_year(firm_id: str, client_id: str, ay: str) -> list[dict]:
    if _USE_MOCK:
        return [dict(r) for r in _MOCK_RECORDS.values()
                if r["firm_id"] == firm_id and r["client_id"] == client_id
                and r["assessment_year"] == ay]
    return (_supabase().table("ais_records").select("*")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("assessment_year", ay).execute().data) or []


def _get_record(firm_id: str, record_id: str) -> Optional[dict]:
    if _USE_MOCK:
        r = _MOCK_RECORDS.get(record_id)
        return dict(r) if r and r["firm_id"] == firm_id else None
    res = (_supabase().table("ais_records").select("*")
           .eq("id", record_id).eq("firm_id", firm_id).limit(1).execute())
    return (res.data or [None])[0]


def _delete_record(firm_id: str, record_id: str) -> None:
    if _USE_MOCK:
        _MOCK_RECORDS.pop(record_id, None)
        for key, w in list(_MOCK_RECONS.items()):
            if w["record_id"] == record_id:
                _MOCK_RECONS.pop(key, None)
        return
    (_supabase().table("ais_records").delete()
     .eq("id", record_id).eq("firm_id", firm_id).execute())


def _recons_for_year(firm_id: str, client_id: str, ay: str) -> list[dict]:
    if _USE_MOCK:
        return [dict(w) for w in _MOCK_RECONS.values()
                if w["firm_id"] == firm_id and w["client_id"] == client_id
                and w["assessment_year"] == ay]
    return (_supabase().table("ais_reconciliations").select("*")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("assessment_year", ay).execute().data) or []


def _insert_recons(rows: list[dict]) -> None:
    if not rows:
        return
    if _USE_MOCK:
        for r in rows:
            r = {"id": str(uuid4()), "created_at": _now(), "updated_at": _now(), **r}
            _MOCK_RECONS[r["record_id"]] = r
        return
    _supabase().table("ais_reconciliations").insert(rows).execute()


def _upsert_recon(row: dict) -> dict:
    if _USE_MOCK:
        prior = _MOCK_RECONS.get(row["record_id"]) or {}
        saved = {"id": prior.get("id") or str(uuid4()),
                 "created_at": prior.get("created_at") or _now(),
                 **row, "updated_at": _now()}
        _MOCK_RECONS[row["record_id"]] = saved
        return saved
    res = (_supabase().table("ais_reconciliations")
           .upsert({**row, "updated_at": _now()}, on_conflict="record_id")
           .execute())
    return (res.data or [row])[0]


def _restate_totals(firm_id: str, upload_id: str) -> None:
    """Keep the upload's stored totals in step with the lines it now has.

    They exist so a list of statements can be shown without reading every
    line, and a stale total on that list is a figure a CA compares against
    the portal.
    """
    rows = _records_for_upload(firm_id, upload_id)
    patch = {
        "record_count": len(rows),
        "total_amount_paise": sum(int(r.get("amount_paise") or 0) for r in rows),
        "total_tds_paise": sum(int(r.get("tds_deducted_paise") or 0) for r in rows),
    }
    if _USE_MOCK:
        if upload_id in _MOCK_UPLOADS:
            _MOCK_UPLOADS[upload_id].update(patch)
        return
    (_supabase().table("ais_uploads").update(patch)
     .eq("id", upload_id).eq("firm_id", firm_id).execute())


def _reset_mock_state() -> None:
    """Tests only."""
    _MOCK_UPLOADS.clear()
    _MOCK_RECORDS.clear()
    _MOCK_RECONS.clear()


__all__ = [
    "AISRefused", "STATUSES", "TRANSACTION_TYPES", "add_manual_record",
    "classify", "delete_record", "get_record", "get_statement",
    "list_uploads",
    "save_working", "summarise", "upload_statement",
]
