"""
GST Workspace router — filing dashboard, return management, GSTR-2B reconciliation.

CGST Act §37 (GSTR-1 outward supplies), §39 (GSTR-3B monthly return), §44 (GSTR-9 annual).
All monetary amounts in integer paise — never float.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to GSTN or any government portal.
"""
from __future__ import annotations

import os
import uuid
import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from models.common import api_response
from core.authz import assert_client_access, can_access_client
from core.permissions import rbac
from core.ist_clock import ist_today
from core.validators import validate_gstin
from services.audit_service import log_event
from services.timeline_service import timeline_service
from services.period_validation_service import period_validation_service
from services.compliance_engine import (
    gstr1_due_date, gstr3b_due_date, pmt06_due_date, iff_due_date,
    gst_state_category, gst_period_month_in_quarter, MONTHLY, QUARTERLY,
)
from services.gst_filing_record_service import (
    FILING_TYPE_GSTR1, FILING_TYPE_GSTR3B, record_filing, return_status_patch,
)

router = APIRouter(prefix="/api/gst-workspace", tags=["gst_workspace"])
_logger = logging.getLogger("caflow.gst_workspace")

_USE_MOCK = not os.environ.get("SUPABASE_URL")

# ── Mock stores ───────────────────────────────────────────────────────────────
_MOCK_GSTR1: dict[str, dict] = {}
_MOCK_GSTR3B: dict[str, dict] = {}
_MOCK_GSTR2B: dict[str, dict] = {}


# ── Helpers ───────────────────────────────────────────────────────────────────
# R3.1: these used to hand-roll the same CGST §37/§39 due-date arithmetic
# services/compliance_engine.py already computes canonically (and every other
# caller of due dates already uses) — now thin string<->date adapters over it.

def _gstr1_due_date(period: str, frequency: str = MONTHLY) -> str:
    """CGST Act §37 with Rule 59 — 11th of the following month, or the 13th of
    the month after the QUARTER for a QRMP filer."""
    mm, yyyy = int(period[:2]), int(period[2:])
    return gstr1_due_date(yyyy, mm, frequency).isoformat()


def _gstr3b_due_date(period: str, frequency: str = MONTHLY,
                     state_code: Optional[str] = None) -> str:
    """CGST Act §39 with Rule 61 — 20th of the following month, or the 22nd/24th
    of the month after the quarter for a QRMP filer, by state."""
    mm, yyyy = int(period[:2]), int(period[2:])
    return gstr3b_due_date(yyyy, mm, frequency, state_code).isoformat()


def _gst_regime(client_id: str, firm_id: str) -> dict:
    """What filing regime this client is on, and everything that follows from it.

    clients.gst_filing_frequency has existed since migration 001 and was
    settable on the client form, but no code read it: every client was quoted
    the monthly 11th and 20th. A QRMP filer's GSTR-1 is due the 13th of the
    month after the QUARTER and their GSTR-3B the 22nd or 24th by state, and
    they owe PMT-06 challans a monthly filer does not. §47 charges Rs 50 a day
    for filing late, so quoting the wrong date is not a display bug.

    `state_category` is null when the client has no state_code. That is not an
    error to swallow: the quarterly GSTR-3B date genuinely cannot be determined
    without it, so the date returned is the EARLIER of the two and the screen
    is told to present it as assumed.
    """
    from repositories.client_repository import client_repo
    try:
        c = client_repo.find_by_id(client_id, firm_id=firm_id) or {}
    except Exception:  # noqa: BLE001
        c = {}
    freq = (c.get("gst_filing_frequency") or MONTHLY).strip().lower()
    if freq not in (MONTHLY, QUARTERLY):
        freq = MONTHLY
    return {
        "frequency": freq,
        "state_code": c.get("state_code"),
        "state_category": gst_state_category(c.get("state_code")) if freq == QUARTERLY else None,
    }


# ── Request Models ─────────────────────────────────────────────────────────────

class SaveGSTR1Request(BaseModel):
    client_id: str
    period: str = Field(..., description="MMYYYY e.g. 042025")
    gstin: str
    payload_json: dict = Field(default_factory=dict)
    summary_json: dict = Field(default_factory=dict)
    total_taxable_paise: int = Field(default=0, description="Integer paise only")
    total_igst_paise: int = Field(default=0)
    total_cgst_paise: int = Field(default=0)
    total_sgst_paise: int = Field(default=0)
    total_cess_paise: int = Field(default=0)


class SaveGSTR3BRequest(BaseModel):
    client_id: str
    period: str = Field(..., description="MMYYYY e.g. 042025")
    gstin: str
    payload_json: dict = Field(default_factory=dict)
    summary_json: dict = Field(default_factory=dict)
    tax_liability_paise: int = Field(default=0)
    itc_claimed_paise: int = Field(default=0)
    net_tax_paise: int = Field(default=0)


class UpdateStatusRequest(BaseModel):
    status: str
    ca_approved: bool = False
    # The acknowledgement the portal returns. Optional because the CA files on
    # the GST portal and may not have it to hand when they mark it submitted
    # here; recorded on both the return and the filings row when supplied.
    arn: Optional[str] = None
    # When the return was actually filed, if that is not today — marking it in
    # this app can lag the portal by days, and the period lock keys on the real
    # filing date, not on when someone got round to recording it.
    filed_date: Optional[str] = None


class GSTR2BUploadRequest(BaseModel):
    client_id: str
    period: str
    file_url: Optional[str] = None
    raw_data: dict = Field(default_factory=dict, description="GSTR-2B JSON from portal")


# ── Client-assignment scope (M2) ──────────────────────────────────────────────
# Same shape as tds_workspace, and the same two answers. This router already
# called assert_client_access on its four POST bodies (task #231); every
# endpoint taking its client from a QUERY PARAMETER and every one addressed by
# a ROW id was unguarded.
#
#   * Endpoints that NAME a client get `assert_client_access` (404), placed
#     BEFORE the `try` — every handler here ends in a bare `except Exception:
#     return api_response(False, ...)` that would otherwise swallow the refusal
#     into a 200 and downgrade the guard to a log line.
#
#   * Endpoints addressed by a ROW id report a missing row as a 200 carrying
#     {"success": false, "error": "Not found"}. A 404 refusal there would make
#     the STATUS CODE the oracle, so they go through `_visible_or_none` and come
#     back down the router's own not-found path.

def _visible_or_none(current_user: dict, rec: Optional[dict]) -> Optional[dict]:
    """`rec` if the caller may see its client, otherwise None."""
    if rec is None:
        return None
    if not can_access_client(current_user, rec.get("client_id")):
        return None
    return rec


def _existing_return(current_user: dict, table: str, mock_store: dict,
                     client_id: str, period: str) -> Optional[dict]:
    """The return already on file for this (client, period), if any.

    Both save endpoints need it for the same two reasons: to revise a draft in
    place rather than colliding with the UNIQUE(client_id, period) constraint,
    and to refuse a change to one that has been filed.
    """
    if _USE_MOCK:
        for rec in mock_store.values():
            if rec.get("client_id") == client_id and rec.get("period") == period:
                return rec
        return None
    from core.supabase_client import get_supabase
    rows = (get_supabase().table(table).select("*")
            .eq("firm_id", current_user["firm_id"])
            .eq("client_id", client_id).eq("period", period)
            .limit(1).execute().data) or []
    return rows[0] if rows else None


def _load_return_or_none(current_user: dict, table: str, mock_store: dict,
                         return_id: str) -> Optional[dict]:
    """Read a GST return the caller may see, or None.

    The two status endpoints had NO read at all — they fired the UPDATE and used
    whatever came back. There is no way to check a client that way: by the time
    the row is in hand the return has already been moved to "submitted". So the
    read is added, and the refusal happens before the write.
    """
    if _USE_MOCK:
        rec = mock_store.get(return_id)
    else:
        from core.supabase_client import get_supabase
        rows = (get_supabase().table(table).select("*")
                .eq("id", return_id).eq("firm_id", current_user.get("firm_id"))
                .execute().data)
        rec = rows[0] if rows else None
    return _visible_or_none(current_user, rec)


# ── Filing simulation (demo only) ────────────────────────────────────────────
#
# WHAT THIS IS, AND WHAT IT IS EMPHATICALLY NOT
#   PracticeSync prepares GSTR-1 and GSTR-3B and produces the GSTN JSON. The CA
#   uploads that to gst.gov.in and signs it there with a DSC or EVC. There is no
#   API filing: that needs GSP registration, and CLAUDE.md's rule stands either
#   way — never auto-submit anything to a government portal.
#
#   This endpoint exists so the intended flow can be SHOWN — walked through in a
#   demo — before it exists. It transmits nothing, reaches no government system,
#   and changes no stored status. Every acknowledgement number it returns is
#   prefixed SIM- and every response carries simulated=true.
#
# WHY IT IS BUILT THIS WAY RATHER THAN JUST FAKING IT IN THE BROWSER
#   Because a screen that says "Filed" when nothing was filed is how a return
#   gets missed, and §47 charges Rs 50 a day from the real due date. The person
#   demoing knows it is a mock; the person who walks past the laptop afterwards,
#   or opens the same screen next week, does not. So:
#
#     * it is OFF unless ENABLE_FILING_SIMULATION is set, so it cannot appear
#       for a real user by accident;
#     * it never writes gstr3b_returns.status, never writes a gst_filings row,
#       and therefore never moves journal_period_lock_reason. The return's real
#       status is exactly what it was before;
#     * the disclaimer is part of the RESPONSE, not something the UI is trusted
#       to remember to render.
#
#   The genuine "this was filed on the portal" path already exists and is
#   untouched: PATCH /gstr3b/{id}/status with status=submitted, which records
#   the real ARN, the filing date and the filings row the period lock reads.

_SIMULATION_STEPS = [
    ("validate", "Validating return against GSTN schema"),
    ("authenticate", "Authenticating with GST portal"),
    ("upload", "Uploading return payload"),
    ("process", "Awaiting GSTN processing"),
    ("acknowledge", "Receiving acknowledgement"),
]


def filing_simulation_enabled() -> bool:
    return os.environ.get("ENABLE_FILING_SIMULATION", "false").strip().lower() in (
        "1", "true", "yes", "on")


def _simulated_ack(period: str, return_id: str) -> str:
    """Deliberately not ARN-shaped. A real ARN is 15 characters, AA<state><MMYYYY>
    then a serial; anything that pattern-matches could be pasted into a portal
    field or a client email and be believed. This cannot be mistaken for one."""
    return f"SIM-NOT-FILED-{period}-{return_id[:8]}"


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/")
def gst_dashboard(
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("gst", "read")),
):
    """GST filing dashboard with upcoming due dates."""
    assert_client_access(current_user, client_id)
    try:
        firm_id = current_user["firm_id"]
        today = ist_today()
        current_period = f"{today.month:02d}{today.year}"
        regime = _gst_regime(client_id, firm_id)

        if _USE_MOCK:
            gstr1_list = [r for r in _MOCK_GSTR1.values() if r["client_id"] == client_id]
            gstr3b_list = [r for r in _MOCK_GSTR3B.values() if r["client_id"] == client_id]
        else:
            from core.supabase_client import get_supabase
            sb = get_supabase()
            gstr1_list = sb.table("gstr1_returns").select("*").eq("firm_id", firm_id).eq("client_id", client_id).execute().data or []
            gstr3b_list = sb.table("gstr3b_returns").select("*").eq("firm_id", firm_id).eq("client_id", client_id).execute().data or []

        return api_response(True, {
            "gstr1_returns": gstr1_list,
            "gstr3b_returns": gstr3b_list,
            "regime": regime,
            # WHAT THIS BUILD CAN ACTUALLY DO.
            # The "Preview filing (demo)" button used to render unconditionally
            # and error on click when ENABLE_FILING_SIMULATION was off — a dead
            # control, which is exactly the fault the health badge was fixed for
            # a day earlier. A capability the server does not have should not be
            # offered by the screen; the server is the only thing that knows.
            "capabilities": {
                "filing_simulation": filing_simulation_enabled(),
                # Stated so no screen ever has to infer it. Real filing needs
                # GSP registration and does not exist; see CLAUDE.md.
                "real_filing": False,
            },
            "upcoming_due_dates": {
                "gstr1": _gstr1_due_date(current_period, regime["frequency"]),
                "gstr3b": _gstr3b_due_date(current_period, regime["frequency"],
                                           regime["state_code"]),
                # Rule 61A: a QRMP filer still pays monthly by challan for the
                # first two months of the quarter. Null in month 3, and for a
                # monthly filer, because nothing is due — not because it is
                # unknown.
                "pmt06": (pmt06_due_date(int(current_period[2:]), int(current_period[:2])).isoformat()
                          if regime["frequency"] == QUARTERLY
                          and pmt06_due_date(int(current_period[2:]), int(current_period[:2]))
                          else None),
                # Optional (Rule 59(2)), offered so the recipient's ITC does not
                # wait a quarter. Reported as a date, never as an obligation.
                "iff_optional": (iff_due_date(int(current_period[2:]), int(current_period[:2])).isoformat()
                                 if regime["frequency"] == QUARTERLY
                                 and iff_due_date(int(current_period[2:]), int(current_period[:2]))
                                 else None),
                "month_in_quarter": (gst_period_month_in_quarter(int(current_period[:2]))
                                     if regime["frequency"] == QUARTERLY else None),
                "current_period": current_period,
            },
        })
    except Exception as e:
        _logger.exception("gst_dashboard error")
        return api_response(False, None, "Unable to complete GST operation. Please try again.")


@router.get("/returns")
def list_returns(
    client_id: str = Query(...),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(rbac("gst", "read")),
):
    """List all GST returns (GSTR-1 + GSTR-3B) for a client."""
    assert_client_access(current_user, client_id)
    try:
        firm_id = current_user["firm_id"]
        if _USE_MOCK:
            g1 = [r for r in _MOCK_GSTR1.values() if r["client_id"] == client_id]
            g3b = [r for r in _MOCK_GSTR3B.values() if r["client_id"] == client_id]
            g1 = g1[offset:offset + limit]
            g3b = g3b[offset:offset + limit]
        else:
            from core.supabase_client import get_supabase
            sb = get_supabase()
            g1 = sb.table("gstr1_returns").select("*").eq("firm_id", firm_id).eq("client_id", client_id).range(offset, offset + limit - 1).execute().data or []
            g3b = sb.table("gstr3b_returns").select("*").eq("firm_id", firm_id).eq("client_id", client_id).range(offset, offset + limit - 1).execute().data or []

        return api_response(True, {"gstr1": g1, "gstr3b": g3b})
    except Exception as e:
        return api_response(False, None, "Unable to complete GST operation. Please try again.")


@router.post("/gstr1")
def save_gstr1(
    body: SaveGSTR1Request,
    current_user: dict = Depends(rbac("gst", "compute")),
):
    """Save GSTR-1 return as draft. CGST Act §37."""
    try:
        firm_id = current_user["firm_id"]
        # task #231 audit finding: client_id was never checked against the
        # caller's firm — unlike save_gstr9's existing "F4 fix" (which only
        # scoped the update-if-exists lookup by firm_id), this endpoint had
        # no ownership check at all, letting a caller plant a GSTR-1 draft
        # cross-referencing another firm's real client_id and tax figures.
        assert_client_access(current_user, body.client_id)
        gstin = body.gstin.strip().upper()
        err = validate_gstin(gstin)
        if err:
            raise HTTPException(status_code=422, detail=err)
        # Validate period date
        period_date = f"{body.period[2:]}-{body.period[:2]}-01"
        period_validation_service.validate_posting_date(firm_id, period_date)

        record = {
            "id": str(uuid.uuid4()),
            "firm_id": firm_id,
            "client_id": body.client_id,
            "period": body.period,
            "gstin": gstin,
            "payload_json": body.payload_json,
            "summary_json": body.summary_json,
            "total_taxable_paise": body.total_taxable_paise,
            "total_igst_paise": body.total_igst_paise,
            "total_cgst_paise": body.total_cgst_paise,
            "total_sgst_paise": body.total_sgst_paise,
            "total_cess_paise": body.total_cess_paise,
            "status": "draft",
            "created_at": datetime.utcnow().isoformat(),
        }

        # One return per (client, period) — the table says so (UNIQUE, migration
        # 036), and so does the law: there is one GSTR-1 for a month. So a second
        # save is a REVISION of the draft, not a new return, and the insert that
        # used to happen here failed the unique constraint and surfaced as
        # "Unable to complete GST operation. Please try again."
        #
        # Once submitted it freezes. A GST return cannot be revised (CGST §37);
        # corrections are declared in a later period's amendment tables. A
        # payload that could still change after filing would also make the
        # exception report compare the books against a moving target.
        existing = _existing_return(current_user, "gstr1_returns", _MOCK_GSTR1, body.client_id, body.period)
        if existing:
            if existing.get("status") == "submitted":
                raise HTTPException(
                    status_code=422,
                    detail=f"GSTR-1 for {body.period} has already been filed and cannot be "
                           "changed. Corrections are declared as an amendment in a later return.")
            record["id"] = existing["id"]
            record["status"] = existing.get("status") or "draft"
            record.pop("created_at", None)

        if _USE_MOCK:
            if existing:
                _MOCK_GSTR1[record["id"]].update(record)
                record = _MOCK_GSTR1[record["id"]]
            else:
                _MOCK_GSTR1[record["id"]] = record
        else:
            from core.supabase_client import get_supabase
            sb = get_supabase()
            if existing:
                sb.table("gstr1_returns").update(record).eq("id", record["id"]).eq("firm_id", firm_id).execute()
            else:
                sb.table("gstr1_returns").insert(record).execute()

        log_event(firm_id, "gstr1_return", record["id"], "create",
                  actor_id=current_user.get("id"), new_data=record)
        timeline_service.log_timeline_event(
            client_id=body.client_id, firm_id=firm_id,
            financial_year="", category="gst", event_type="gstr1_draft_saved",
            title=f"GSTR-1 draft saved for {body.period}",
        )
        return api_response(True, record)
    except HTTPException:
        # period_validation_service's locked-FY rejection (CGST §37) carries a real,
        # actionable message the CA needs — collapsing it into "Please try again" is
        # actively misleading, since retrying identical input will never succeed.
        raise
    except Exception as e:
        return api_response(False, None, "Unable to complete GST operation. Please try again.")


@router.get("/gstr1/{return_id}")
def get_gstr1(return_id: str, current_user: dict = Depends(rbac("gst", "read"))):
    """Get GSTR-1 return by ID."""
    try:
        firm_id = current_user["firm_id"]
        if _USE_MOCK:
            rec = _MOCK_GSTR1.get(return_id)
        else:
            from core.supabase_client import get_supabase
            rows = get_supabase().table("gstr1_returns").select("*").eq("id", return_id).eq("firm_id", firm_id).execute().data
            rec = rows[0] if rows else None
        rec = _visible_or_none(current_user, rec)
        if not rec:
            return api_response(False, None, "Not found")

        return api_response(True, rec)
    except Exception as e:
        return api_response(False, None, "Unable to complete GST operation. Please try again.")


@router.patch("/gstr1/{return_id}/status")
def update_gstr1_status(
    return_id: str,
    body: UpdateStatusRequest,
    current_user: dict = Depends(rbac("gst", "compute")),
):
    """
    Update GSTR-1 status: draft → validated → ca_approved.
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to GSTN.
    """
    try:
        firm_id = current_user["firm_id"]
        allowed = {"draft", "validated", "ca_approved", "submitted"}
        if body.status not in allowed:
            return api_response(False, None, f"Invalid status. Allowed: {allowed}")

        # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
        if body.status in ("ca_approved", "submitted") and not body.ca_approved:
            return api_response(False, None,
                "Explicit ca_approved=true required for ca_approved/submitted status. CA must confirm.")

        # CGST Act §37: only Manager+ can approve/submit a GSTR-1 return —
        # ca_approved=true alone is a caller-supplied flag, not proof of role.
        if body.status in ("ca_approved", "submitted"):
            from core.permissions import can
            role = current_user.get("role", "executive")
            if not can(role, "gst", "approve"):
                return api_response(False, None,
                    "Only Manager or above can approve or submit a GST return.")

        # Read first. Moving a return to "submitted" is the write this router
        # exists to gate (CGST §37/§39) — a check that happens after it has
        # already moved is not a check.
        if _load_return_or_none(current_user, "gstr1_returns", _MOCK_GSTR1, return_id) is None:
            return api_response(False, None, "Not found")

        # Record WHAT was filed, not merely that the status moved. submitted_at,
        # the approver and the ARN are columns migration 036 created and nothing
        # had ever written; the exception report and the period lock both read
        # what lands here.
        patch = return_status_patch(
            body.status, actor_id=current_user.get("id"), arn=body.arn,
            now_iso=datetime.utcnow().isoformat(),
        )
        if _USE_MOCK:
            _MOCK_GSTR1[return_id].update(patch)
            rec = _MOCK_GSTR1[return_id]
        else:
            from core.supabase_client import get_supabase
            rows = get_supabase().table("gstr1_returns").update(patch).eq("id", return_id).eq("firm_id", firm_id).execute().data
            rec = rows[0] if rows else {}

        # The filings row. This is what journal_period_lock_reason (migration
        # 266) reads to refuse an edit inside a filed period — and until now
        # nothing anywhere wrote that table, so the lock could never fire.
        if body.status == "submitted" and not _USE_MOCK:
            from core.supabase_client import get_supabase
            try:
                record_filing(
                    get_supabase(), firm_id=firm_id,
                    client_id=rec.get("client_id") or "",
                    filing_type=FILING_TYPE_GSTR1, period=rec.get("period") or "",
                    filed_date=body.filed_date, arn=body.arn,
                    tax_payable_paise=rec.get("total_taxable_paise"),
                    summary=rec.get("summary_json"),
                )
            except Exception:
                # The return IS filed; the CA marked it so. Failing the request
                # now would leave them unable to record reality. Log loudly —
                # the missing row means the period lock will not bite for this
                # return until it is written.
                _logger.exception(
                    "filings row not written for %s %s/%s — the period lock will "
                    "not cover this return", FILING_TYPE_GSTR1, rec.get("client_id"), rec.get("period"))

        log_event(firm_id, "gstr1_return", return_id, "status_change",
                  actor_id=current_user.get("id"), new_data={"status": body.status})
        if body.status == "submitted":
            timeline_service.log_timeline_event(
                client_id=rec.get("client_id", ""), firm_id=firm_id,
                financial_year="", category="gst", event_type="gstr1_filed",
                title=f"GSTR-1 filed for {rec.get('period', '')}",
            )
        return api_response(True, rec)
    except Exception as e:
        return api_response(False, None, "Unable to complete GST operation. Please try again.")


@router.post("/gstr3b")
def save_gstr3b(
    body: SaveGSTR3BRequest,
    current_user: dict = Depends(rbac("gst", "compute")),
):
    """Save GSTR-3B return as draft. CGST Act §39."""
    try:
        firm_id = current_user["firm_id"]
        # task #231 audit finding: same client_id ownership gap as save_gstr1.
        assert_client_access(current_user, body.client_id)
        gstin = body.gstin.strip().upper()
        err = validate_gstin(gstin)
        if err:
            raise HTTPException(status_code=422, detail=err)
        period_date = f"{body.period[2:]}-{body.period[:2]}-01"
        period_validation_service.validate_posting_date(firm_id, period_date)

        record = {
            "id": str(uuid.uuid4()),
            "firm_id": firm_id,
            "client_id": body.client_id,
            "period": body.period,
            "gstin": gstin,
            "payload_json": body.payload_json,
            "summary_json": body.summary_json,
            "tax_liability_paise": body.tax_liability_paise,
            "itc_claimed_paise": body.itc_claimed_paise,
            "net_tax_paise": body.net_tax_paise,
            "status": "draft",
            "created_at": datetime.utcnow().isoformat(),
        }

        # One return per (client, period) — the table says so (UNIQUE, migration
        # 036), and so does the law: there is one GSTR-3B for a month. So a second
        # save is a REVISION of the draft, not a new return, and the insert that
        # used to happen here failed the unique constraint and surfaced as
        # "Unable to complete GST operation. Please try again."
        #
        # Once submitted it freezes. A GST return cannot be revised (CGST §37);
        # corrections are declared in a later period's amendment tables. A
        # payload that could still change after filing would also make the
        # exception report compare the books against a moving target.
        existing = _existing_return(current_user, "gstr3b_returns", _MOCK_GSTR3B, body.client_id, body.period)
        if existing:
            if existing.get("status") == "submitted":
                raise HTTPException(
                    status_code=422,
                    detail=f"GSTR-3B for {body.period} has already been filed and cannot be "
                           "changed. Corrections are declared as an amendment in a later return.")
            record["id"] = existing["id"]
            record["status"] = existing.get("status") or "draft"
            record.pop("created_at", None)

        if _USE_MOCK:
            if existing:
                _MOCK_GSTR3B[record["id"]].update(record)
                record = _MOCK_GSTR3B[record["id"]]
            else:
                _MOCK_GSTR3B[record["id"]] = record
        else:
            from core.supabase_client import get_supabase
            sb = get_supabase()
            if existing:
                sb.table("gstr3b_returns").update(record).eq("id", record["id"]).eq("firm_id", firm_id).execute()
            else:
                sb.table("gstr3b_returns").insert(record).execute()

        log_event(firm_id, "gstr3b_return", record["id"], "create",
                  actor_id=current_user.get("id"), new_data=record)
        return api_response(True, record)
    except HTTPException:
        # period_validation_service's locked-FY rejection (CGST §39) carries a real,
        # actionable message the CA needs — collapsing it into "Please try again" is
        # actively misleading, since retrying identical input will never succeed.
        raise
    except Exception as e:
        return api_response(False, None, "Unable to complete GST operation. Please try again.")


@router.get("/gstr3b/{return_id}")
def get_gstr3b(return_id: str, current_user: dict = Depends(rbac("gst", "read"))):
    """Get GSTR-3B return by ID."""
    try:
        firm_id = current_user["firm_id"]
        if _USE_MOCK:
            rec = _MOCK_GSTR3B.get(return_id)
        else:
            from core.supabase_client import get_supabase
            rows = get_supabase().table("gstr3b_returns").select("*").eq("id", return_id).eq("firm_id", firm_id).execute().data
            rec = rows[0] if rows else None
        rec = _visible_or_none(current_user, rec)
        if not rec:
            return api_response(False, None, "Not found")

        return api_response(True, rec)
    except Exception as e:
        return api_response(False, None, "Unable to complete GST operation. Please try again.")


@router.patch("/gstr3b/{return_id}/status")
def update_gstr3b_status(
    return_id: str,
    body: UpdateStatusRequest,
    current_user: dict = Depends(rbac("gst", "compute")),
):
    """
    Update GSTR-3B status: draft → validated → ca_approved.
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to GSTN.
    """
    try:
        firm_id = current_user["firm_id"]
        allowed = {"draft", "validated", "ca_approved", "submitted"}
        if body.status not in allowed:
            return api_response(False, None, f"Invalid status. Allowed: {allowed}")

        # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
        if body.status in ("ca_approved", "submitted") and not body.ca_approved:
            return api_response(False, None,
                "Explicit ca_approved=true required for ca_approved/submitted status. CA must confirm.")

        # CGST Act §39: only Manager+ can approve/submit a GSTR-3B return —
        # ca_approved=true alone is a caller-supplied flag, not proof of role.
        if body.status in ("ca_approved", "submitted"):
            from core.permissions import can
            role = current_user.get("role", "executive")
            if not can(role, "gst", "approve"):
                return api_response(False, None,
                    "Only Manager or above can approve or submit a GST return.")

        # Read first. Moving a return to "submitted" is the write this router
        # exists to gate (CGST §37/§39) — a check that happens after it has
        # already moved is not a check.
        if _load_return_or_none(current_user, "gstr3b_returns", _MOCK_GSTR3B, return_id) is None:
            return api_response(False, None, "Not found")

        # Record WHAT was filed, not merely that the status moved. submitted_at,
        # the approver and the ARN are columns migration 036 created and nothing
        # had ever written; the exception report and the period lock both read
        # what lands here.
        patch = return_status_patch(
            body.status, actor_id=current_user.get("id"), arn=body.arn,
            now_iso=datetime.utcnow().isoformat(),
        )
        if _USE_MOCK:
            _MOCK_GSTR3B[return_id].update(patch)
            rec = _MOCK_GSTR3B[return_id]
        else:
            from core.supabase_client import get_supabase
            rows = get_supabase().table("gstr3b_returns").update(patch).eq("id", return_id).eq("firm_id", firm_id).execute().data
            rec = rows[0] if rows else {}

        # The filings row. This is what journal_period_lock_reason (migration
        # 266) reads to refuse an edit inside a filed period — and until now
        # nothing anywhere wrote that table, so the lock could never fire.
        if body.status == "submitted" and not _USE_MOCK:
            from core.supabase_client import get_supabase
            try:
                record_filing(
                    get_supabase(), firm_id=firm_id,
                    client_id=rec.get("client_id") or "",
                    filing_type=FILING_TYPE_GSTR3B, period=rec.get("period") or "",
                    filed_date=body.filed_date, arn=body.arn,
                    tax_payable_paise=rec.get("net_tax_paise"),
                    summary=rec.get("summary_json"),
                )
            except Exception:
                # The return IS filed; the CA marked it so. Failing the request
                # now would leave them unable to record reality. Log loudly —
                # the missing row means the period lock will not bite for this
                # return until it is written.
                _logger.exception(
                    "filings row not written for %s %s/%s — the period lock will "
                    "not cover this return", FILING_TYPE_GSTR3B, rec.get("client_id"), rec.get("period"))

        log_event(firm_id, "gstr3b_return", return_id, "status_change",
                  actor_id=current_user.get("id"), new_data={"status": body.status})
        if body.status == "submitted":
            timeline_service.log_timeline_event(
                client_id=rec.get("client_id", ""), firm_id=firm_id,
                financial_year="", category="gst", event_type="gstr3b_filed",
                title=f"GSTR-3B filed for {rec.get('period', '')}",
            )
        return api_response(True, rec)
    except Exception as e:
        return api_response(False, None, "Unable to complete GST operation. Please try again.")


@router.get("/filing-history")
def filing_history(
    client_id: str = Query(...),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(rbac("gst", "read")),
):
    """List filed returns (status=submitted) with ARN and filing date."""
    assert_client_access(current_user, client_id)
    try:
        firm_id = current_user["firm_id"]
        if _USE_MOCK:
            g1 = [r for r in _MOCK_GSTR1.values()
                  if r["client_id"] == client_id and r.get("status") == "submitted"]
            g3b = [r for r in _MOCK_GSTR3B.values()
                   if r["client_id"] == client_id and r.get("status") == "submitted"]
            g1 = g1[offset:offset + limit]
            g3b = g3b[offset:offset + limit]
        else:
            from core.supabase_client import get_supabase
            sb = get_supabase()
            g1 = sb.table("gstr1_returns").select("*").eq("firm_id", firm_id).eq("client_id", client_id).eq("status", "submitted").range(offset, offset + limit - 1).execute().data or []
            g3b = sb.table("gstr3b_returns").select("*").eq("firm_id", firm_id).eq("client_id", client_id).eq("status", "submitted").range(offset, offset + limit - 1).execute().data or []

        return api_response(True, {"gstr1_filed": g1, "gstr3b_filed": g3b})
    except Exception as e:
        return api_response(False, None, "Unable to complete GST operation. Please try again.")


def _txval_to_paise(txval) -> int:
    """GSTR-2B JSON txval is portal-supplied rupees (a JSON number, often with
    a fractional part) -- Decimal(str(...)) never float(...) * 100, per
    project rule (a raw float multiply is not guaranteed to round-trip
    exactly through IEEE-754 binary imprecision)."""
    try:
        return int((Decimal(str(txval or 0)) * 100).to_integral_value(rounding=ROUND_HALF_UP))
    except InvalidOperation:
        return 0


@router.post("/gstr2b/upload")
def upload_gstr2b(
    body: GSTR2BUploadRequest,
    current_user: dict = Depends(rbac("gst", "compute")),
):
    """
    Save GSTR-2B JSON and reconcile against books.
    Matches invoices by invoice_no + GSTIN. CGST Act §38.
    """
    try:
        firm_id = current_user["firm_id"]
        # task #231 audit finding: same client_id ownership gap as save_gstr1/3b.
        assert_client_access(current_user, body.client_id)
        raw = body.raw_data
        # Reconcile: extract invoices from GSTR-2B and match against books
        b2b_invoices = raw.get("data", {}).get("docDetails", []) or raw.get("invoices", [])
        matched = []
        mismatched = []
        missing_in_2b = []

        book_invoices = raw.get("book_invoices", [])  # caller provides book invoices for matching
        b2b_keys = {(inv.get("inum", ""), inv.get("sgstin", "")): inv for inv in b2b_invoices}

        for book_inv in book_invoices:
            key = (book_inv.get("invoice_no", ""), book_inv.get("gstin", ""))
            if key in b2b_keys:
                b2b_inv = b2b_keys[key]
                # Compare amounts in integer paise
                book_taxable = book_inv.get("taxable_paise", 0)
                b2b_taxable = _txval_to_paise(b2b_inv.get("txval", 0))
                if book_taxable == b2b_taxable:
                    matched.append({"key": key, "status": "matched"})
                else:
                    mismatched.append({
                        "key": key, "status": "amount_mismatch",
                        "book_paise": book_taxable, "gstr2b_paise": b2b_taxable,
                    })
            else:
                missing_in_2b.append({"key": key, "status": "missing_in_2b"})

        reconciliation_result = {
            "matched": matched,
            "mismatched": mismatched,
            "missing_in_2b": missing_in_2b,
            "summary": {
                "total_book": len(book_invoices),
                "matched_count": len(matched),
                "mismatch_count": len(mismatched),
                "missing_count": len(missing_in_2b),
            },
        }

        record = {
            "id": str(uuid.uuid4()),
            "firm_id": firm_id,
            "client_id": body.client_id,
            "period": body.period,
            "file_url": body.file_url,
            "raw_data": body.raw_data,
            "reconciliation_result": reconciliation_result,
            "status": "reconciled",
            "created_by": current_user.get("id"),
            "uploaded_at": datetime.utcnow().isoformat(),
        }

        if _USE_MOCK:
            _MOCK_GSTR2B[record["id"]] = record
        else:
            from core.supabase_client import get_supabase
            get_supabase().table("gstr2b_uploads").insert(record).execute()

        if mismatched or missing_in_2b:
            timeline_service.log_timeline_event(
                client_id=body.client_id, firm_id=firm_id,
                financial_year="", category="gst", event_type="gst_mismatch_detected",
                title=f"GSTR-2B mismatch for {body.period}: {len(mismatched)} mismatches, {len(missing_in_2b)} missing",
                severity="warning",
            )
        return api_response(True, record)
    except HTTPException:
        # task #231 audit finding: this endpoint had no `except HTTPException:
        # raise` (unlike save_gstr1/save_gstr3b right above it), so the
        # client_id ownership guard's HTTPException(404) — or any other real,
        # actionable rejection — was being silently swallowed into a generic
        # "Please try again" (the task #97 anti-pattern).
        raise
    except Exception as e:
        return api_response(False, None, "Unable to complete GST operation. Please try again.")


class GSTR9In(BaseModel):
    client_id: str
    financial_year: str  # e.g. "2025-26"
    gstin: str
    payload_json: dict = Field(default_factory=dict)
    summary_json: dict = Field(default_factory=dict)
    total_taxable_paise: int = 0
    total_igst_paise: int = 0
    total_cgst_paise: int = 0
    total_sgst_paise: int = 0
    total_tax_paise: int = 0


@router.post("/gstr9")
def save_gstr9(
    data: GSTR9In,
    current_user: dict = Depends(rbac("gst", "compute")),
):
    """
    Save GSTR-9 annual return draft.
    CGST Act §44: Annual return to be filed by 31st December following FY end.
    All amounts in integer paise.
    """
    try:
        firm_id   = current_user.get("firm_id")
        client_id = data.client_id
        # task #231 audit finding: the existing "F4 fix" below only scoped
        # the update-if-exists lookup by firm_id — it stopped a cross-firm
        # OVERWRITE of an existing draft, but a first-time save for another
        # firm's client_id still inserted unchecked. Close that too.
        assert_client_access(current_user, client_id)
        fy        = data.financial_year  # e.g. "2025-26"
        gstin     = data.gstin.strip().upper()
        err = validate_gstin(gstin)
        if err:
            raise HTTPException(status_code=422, detail=err)

        # CGST Act §44 — GSTR-9 is annual; use April 1 of the FY for period validation
        fy_start_year = int(fy.split("-")[0]) if fy else ist_today().year
        period_validation_service.validate_posting_date(firm_id or "", f"{fy_start_year}-04-01")

        payload = {
            "firm_id":              firm_id,
            "client_id":            client_id,
            "financial_year":       fy,
            "period":               f"FY{fy}",
            "return_type":          "gstr9",
            "gstin":                gstin,
            "status":               "draft",
            "payload_json":         data.payload_json,
            "summary_json":         data.summary_json,
            "total_taxable_paise":  data.total_taxable_paise,
            "total_igst_paise":     data.total_igst_paise,
            "total_cgst_paise":     data.total_cgst_paise,
            "total_sgst_paise":     data.total_sgst_paise,
            "total_tax_paise":      data.total_tax_paise,
            "created_at":           datetime.utcnow().isoformat(),
        }

        if _USE_MOCK:
            rec = {**payload, "id": str(uuid.uuid4())}
            _MOCK_GSTR1[rec["id"]] = rec  # reuse same mock store
            return api_response(True, rec)

        from core.supabase_client import get_supabase
        db = get_supabase()
        # CGST Act §44: GSTR-9 unique per client per FY. F4 fix: also scope by
        # firm_id -- without it, a firm that merely knew/guessed another
        # firm's client_id could overwrite that firm's existing annual return
        # draft via this same "update if exists" path.
        existing = (db.table("gstr1_returns").select("id").eq("client_id", client_id)
                    .eq("financial_year", fy).eq("return_type", "gstr9")
                    .eq("firm_id", firm_id).limit(1).execute())
        if existing.data:
            # Update existing draft
            upd = db.table("gstr1_returns").update(payload).eq("id", existing.data[0]["id"]).execute()
            rec = upd.data[0] if upd.data else {**payload, "id": existing.data[0]["id"]}
        else:
            ins = db.table("gstr1_returns").insert(payload).execute()
            rec = ins.data[0] if ins.data else payload

        log_event(
            firm_id or "", "gstr9_return", rec.get("id", ""),
            "create", actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"), new_data=rec,
        )
        timeline_service.log(
            client_id, "gst", "GSTR-9 Draft Saved",
            f"Annual return draft for FY {fy} saved",
            "info", firm_id=firm_id or "",
            entity_type="gstr9_return", entity_id=rec.get("id", ""),
            actor_id=current_user.get("auth_user_id"),
        )
        return api_response(True, rec)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("save_gstr9: %s", e)
        return api_response(False, None, "Unable to complete GST operation. Please try again.")


@router.get("/gstr9")
def get_gstr9(
    client_id: str = Query(...),
    financial_year: str = Query(..., description="FY string e.g. '2025-26'"),
    current_user: dict = Depends(rbac("gst", "read")),
):
    """
    Retrieve saved GSTR-9 draft for a client and financial year.
    CGST Act §44: Annual return filed by 31st December following FY end.
    """
    assert_client_access(current_user, client_id)
    try:
        if _USE_MOCK:
            rec = next(
                (v for v in _MOCK_GSTR1.values()
                 if v.get("client_id") == client_id
                 and v.get("financial_year") == financial_year
                 and v.get("return_type") == "gstr9"),
                None,
            )
            return api_response(True, rec)

        from core.supabase_client import get_supabase
        db = get_supabase()
        # F4 fix: scope by firm_id too -- otherwise any firm that knew/guessed
        # another firm's client_id could read that firm's annual return draft.
        res = (
            db.table("gstr1_returns")
            .select("*")
            .eq("client_id", client_id)
            .eq("financial_year", financial_year)
            .eq("return_type", "gstr9")
            .eq("firm_id", current_user.get("firm_id"))
            .limit(1)
            .execute()
        )
        return api_response(True, res.data[0] if res.data else None)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("get_gstr9: %s", e)
        return api_response(False, None, "Unable to complete GST operation. Please try again.")


@router.get("/gstr2b/{upload_id}")
def get_gstr2b(upload_id: str, current_user: dict = Depends(rbac("gst", "read"))):
    """Get GSTR-2B reconciliation result."""
    try:
        firm_id = current_user["firm_id"]
        if _USE_MOCK:
            rec = _MOCK_GSTR2B.get(upload_id)
        else:
            from core.supabase_client import get_supabase
            rows = get_supabase().table("gstr2b_uploads").select("*").eq("id", upload_id).eq("firm_id", firm_id).execute().data
            rec = rows[0] if rows else None
        rec = _visible_or_none(current_user, rec)
        if not rec:
            return api_response(False, None, "Not found")

        return api_response(True, rec)
    except Exception as e:
        return api_response(False, None, "Unable to complete GST operation. Please try again.")


@router.get("/gstr1/amendments")
def gstr1_outstanding_amendments(
    client_id: str = Query(..., description="Client whose filed periods to check"),
    period: str = Query(..., description="MMYYYY of the return being prepared"),
    current_user: dict = Depends(rbac("gst", "read")),
):
    """What this period's GSTR-1 must carry from earlier periods already filed.

    CGST Act §37: a filed GSTR-1 cannot be revised, so a correction to it is
    declared in a LATER return's amendment tables — 9A for invoices, 9C for
    credit and debit notes, 10 for B2C-others. Every amended entry names the
    original document (or, for B2C-others, the original month) so GSTN knows
    which entry it supersedes.

    Two things here are deliberately NOT amendments. An invoice raised after its
    period was filed was never declared, so there is nothing to supersede — it
    belongs in this period's ordinary table, and it is listed separately because
    the date-range read would otherwise miss it entirely. A document cancelled
    after filing has no single right answer (amend to nil, or raise a credit
    note) and is surfaced for the CA rather than resolved.

    The 30 November window (§37(3), Finance Act 2022) is not applied here —
    dropping an out-of-time amendment silently would hide exactly what the CA
    most needs to see.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT. This proposes; nothing reaches a
    # return until the CA confirms it.
    """
    assert_client_access(current_user, client_id)
    if _USE_MOCK:
        return api_response(True, {
            "period": period, "source_periods": [], "proposals": [], "sections": {},
            "carry_forward": [], "needs_decision": [],
            "counts": {"amendments": 0, "carry_forward": 0, "needs_decision": 0,
                       "source_periods": 0},
            "ca_review_required": True,
        })
    from core.supabase_client import get_supabase
    from services.gst_amendment_service import outstanding_amendments
    return api_response(True, outstanding_amendments(
        get_supabase(), current_user["firm_id"], client_id, period))


@router.get("/gstr1/exceptions")
def gstr1_exception_report(
    client_id: str = Query(..., description="Client whose filed period to check"),
    period: str = Query(..., description="MMYYYY, e.g. 062025"),
    current_user: dict = Depends(rbac("gst", "read")),
):
    """What the books say now, against what the GSTR-1 actually said.

    A filed GSTR-1 can never be revised (CGST Act §37). If an invoice in a filed
    period is edited, raised late or cancelled, the books move and the return
    cannot — and nothing connected the two until this. Each finding names the
    amendment table the correction has to be declared in: 9A for an invoice, 9C
    for a credit or debit note, 10 for B2C-others.

    B2C-others is compared as totals rather than per invoice because that is all
    GSTR-1 declares for it — no invoice number appears in table 7, and amendment
    table 10 corrects it at the same aggregate grain.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT. This reports drift; it drafts no
    # amendment, touches no invoice and alters no return.
    """
    assert_client_access(current_user, client_id)
    if _USE_MOCK:
        return api_response(True, {
            "status": "not_filed", "period": period,
            "message": "This period's GSTR-1 has not been filed, so there is nothing "
                       "to compare the books against.",
        })
    from core.supabase_client import get_supabase
    from services.gst_exception_service import gstr1_exceptions
    return api_response(True, gstr1_exceptions(
        get_supabase(), current_user["firm_id"], client_id, period))


class ITCReversalIn(BaseModel):
    client_id: str
    journal_entry_id: str
    period: str = Field(..., description="MMYYYY of the GSTR-3B this is declared in")
    reason_code: str = Field(..., description="rule_37 | rule_37a | section_16_2b | section_16_2c | other")
    igst_paise: int = Field(default=0, ge=0)
    cgst_paise: int = Field(default=0, ge=0)
    sgst_paise: int = Field(default=0, ge=0)
    cess_paise: int = Field(default=0, ge=0)
    purchase_bill_id: Optional[str] = None
    notes: Optional[str] = None


class ITCReclaimIn(BaseModel):
    client_id: str
    journal_entry_id: str
    period: str
    reverses_id: str
    igst_paise: int = Field(default=0, ge=0)
    cgst_paise: int = Field(default=0, ge=0)
    sgst_paise: int = Field(default=0, ge=0)
    cess_paise: int = Field(default=0, ge=0)
    notes: Optional[str] = None


@router.get("/itc/register")
def itc_register_for_period(
    client_id: str = Query(...),
    period: str = Query(..., description="MMYYYY"),
    current_user: dict = Depends(rbac("gst", "read")),
):
    """What this period's GSTR-3B declares in Table 4(B)(2) and Table 4(D)(1)."""
    assert_client_access(current_user, client_id)
    if _USE_MOCK:
        return api_response(True, {
            "period": period, "reversals": [], "reclaims": [],
            "reversal_totals": {}, "reclaim_totals": {}, "ca_review_required": True})
    from core.supabase_client import get_supabase
    from services.itc_register_service import for_period
    return api_response(True, for_period(
        get_supabase(), current_user["firm_id"], client_id, period))


@router.post("/itc/register/reversal")
def itc_register_reversal(
    body: ITCReversalIn,
    current_user: dict = Depends(rbac("gst", "compute")),
):
    """Classify an already-posted journal as a Table 4(B)(2) reversal.

    This does NOT post anything. Giving credit back is a real movement and it
    goes through the one posting kernel like every other entry — the CA raises
    the journal, and this says what it was, so the return can declare it.
    Registering a row that claims more than its journal actually moved is
    refused: a return figure the ledger cannot support is the failure this
    exists to prevent.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT.
    """
    assert_client_access(current_user, body.client_id)
    from core.supabase_client import get_supabase
    from services.itc_register_service import ITCRegisterError, record_reversal
    try:
        return api_response(True, record_reversal(
            get_supabase(), current_user["firm_id"], body.client_id,
            journal_entry_id=body.journal_entry_id, period=body.period,
            reason_code=body.reason_code,
            amounts=body.model_dump(),
            purchase_bill_id=body.purchase_bill_id, notes=body.notes,
            actor_id=current_user.get("id")))
    except ITCRegisterError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/itc/register/reclaim")
def itc_register_reclaim(
    body: ITCReclaimIn,
    current_user: dict = Depends(rbac("gst", "compute")),
):
    """Classify an already-posted journal as a Table 4(D)(1) reclaim.

    Refused if it would reclaim more than the reversal it names still has
    outstanding — credit can only come back once.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT.
    """
    assert_client_access(current_user, body.client_id)
    from core.supabase_client import get_supabase
    from services.itc_register_service import ITCRegisterError, record_reclaim
    try:
        return api_response(True, record_reclaim(
            get_supabase(), current_user["firm_id"], body.client_id,
            journal_entry_id=body.journal_entry_id, period=body.period,
            reverses_id=body.reverses_id, amounts=body.model_dump(),
            notes=body.notes, actor_id=current_user.get("id")))
    except ITCRegisterError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/gstr1/advances")
def gstr1_advances(
    client_id: str = Query(..., description="Client whose receipts to check"),
    period: str = Query(..., description="MMYYYY of the return being prepared"),
    current_user: dict = Depends(rbac("gst", "read")),
):
    """Advances received against no invoice — GSTR-1 Table 11.

    Table 11A declares an advance on which tax is payable and no invoice has
    been issued. A row needs the place of supply and the RATE of a supply that
    has not happened yet; a receipt in this system records an amount, a
    customer and a date. So this NAMES the advances and computes no tax —
    inventing a rate would invent a liability on a filed return.

    Which advances are even taxable is a fact about the client's business:
    CGST Act §13(2) makes an advance for SERVICES taxable on receipt, and
    Notification 66/2017-Central Tax removed the charge for GOODS, where the
    liability arises at the invoice instead.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT. This reports; it computes no
    # tax, writes nothing and files nothing.
    """
    assert_client_access(current_user, client_id)
    if _USE_MOCK:
        return api_response(True, {
            "period": period, "unadjusted_advances": [], "count": 0,
            "total_unadjusted_paise": 0, "table_11_computed": False,
            "ca_review_required": True,
        })
    from core.supabase_client import get_supabase
    from services.gst_advance_service import advances_report
    return api_response(True, advances_report(
        get_supabase(), current_user["firm_id"], client_id, period))


@router.get("/itc/rule37")
def rule37_itc_reversal(
    client_id: str = Query(..., description="Client whose purchase ledger to check"),
    as_of: Optional[str] = Query(None, description="YYYY-MM-DD; defaults to today (IST)"),
    current_user: dict = Depends(rbac("gst", "read")),
):
    """Purchase bills 180 days unpaid, and the input tax credit that reverses.

    CGST Act §16(2) second proviso and Rule 37: credit taken on an inward supply
    is reversed, proportionate to the amount not paid, when the supplier goes
    unpaid for 180 days from the invoice date. It is not optional and it is not
    a warning — the credit stops being available whether or not anyone noticed,
    and interest under §50 runs from the date it was availed.

    `as_of` because the CA asks this at a period end, not on the day they open
    the screen: the reversal belongs in one specific return (Rule 37(1) — the
    period immediately following the one the 180 days expired in).

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT. This reports; it posts no journal
    # and files nothing.
    """
    assert_client_access(current_user, client_id)
    if _USE_MOCK:
        return api_response(True, {
            "as_of": as_of or "", "rule": "CGST Act §16(2) second proviso; CGST Rule 37",
            "bills": [], "bill_count": 0,
            "totals": {"cgst_paise": 0, "sgst_paise": 0, "igst_paise": 0, "total_paise": 0},
            "ca_review_required": True,
        })
    from core.supabase_client import get_supabase
    from services.itc_reversal_service import rule37_report
    return api_response(True, rule37_report(
        get_supabase(), current_user["firm_id"], client_id, as_of=as_of))


@router.post("/gstr3b/{return_id}/simulate-filing")
def simulate_gstr3b_filing(
    return_id: str,
    current_user: dict = Depends(rbac("gst", "compute")),
):
    """Play back what filing WILL look like. Files nothing. See the block above.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    Nothing here contacts any government system. When real filing is built it
    will be a different endpoint, behind GSP registration and an explicit CA
    confirmation click, and this one should be deleted rather than pointed at it.
    """
    if not filing_simulation_enabled():
        return api_response(False, None,
            "Filing simulation is not enabled. This build cannot file returns; "
            "download the JSON and upload it on gst.gov.in.")

    rec = _load_return_or_none(current_user, "gstr3b_returns", _MOCK_GSTR3B, return_id)
    if rec is None:
        return api_response(False, None, "Not found")

    period = rec.get("period") or ""
    # The walk-through shows this return's OWN figures. A demo over invented
    # numbers teaches a CA nothing about their client, and the figures are
    # already here — reading them costs nothing and transmits nothing.
    liability = int(rec.get("tax_liability_paise") or 0)
    itc = int(rec.get("itc_claimed_paise") or 0)
    net = int(rec.get("net_tax_paise") or 0)
    return api_response(True, {
        "simulated": True,
        "filed": False,
        "return_id": return_id,
        "period": period,
        "gstin": rec.get("gstin") or "",
        "figures": {
            "tax_liability_paise": liability,
            "itc_claimed_paise": itc,
            "net_tax_paise": net,
        },
        "steps": [{"key": k, "label": l} for k, l in _SIMULATION_STEPS],
        "acknowledgement": _simulated_ack(period, return_id),
        # Carried in the payload rather than left to the UI: a caller that
        # forgets to render a disclaimer still cannot claim this was filed.
        "disclaimer": (
            "SIMULATION — nothing was sent to GSTN and this return has NOT been "
            "filed. PracticeSync prepares the return; the CA files it on "
            "gst.gov.in. The status of this return is unchanged."
        ),
        "status_unchanged": rec.get("status"),
    })
