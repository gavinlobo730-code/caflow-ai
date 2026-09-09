"""
TDS Workspace router — challan management, returns, certificates, 26AS reconciliation.

IT Act §192-194Q (TDS sections), §203 (Form 16/16A certificates).
All monetary amounts in integer paise — never float.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to TRACES or any government portal.
"""
from __future__ import annotations

import os
import uuid
import logging
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from models.common import api_response
from core.permissions import rbac
from core.authz import assert_client_access, can_access_client
from domain.tds.tds_validator import TDSValidator
from services.audit_service import log_event
from services.timeline_service import timeline_service
from services.period_validation_service import period_validation_service
from models.fy import FYLabel

router = APIRouter(prefix="/api/tds-workspace", tags=["tds_workspace"])
_logger = logging.getLogger("caflow.tds_workspace")

_USE_MOCK = not os.environ.get("SUPABASE_URL")

# ── Mock stores ───────────────────────────────────────────────────────────────
_MOCK_CHALLANS: dict[str, dict] = {}
_MOCK_RETURNS: dict[str, dict] = {}
_MOCK_CERTIFICATES: dict[str, dict] = {}
_MOCK_FORM26AS: dict[str, dict] = {}
_MOCK_DEDUCTIONS: dict[str, dict] = {}


# ── Client-assignment scope (M2) ──────────────────────────────────────────────
# `core.authz` makes only the **Partner** firm-wide (`_FIRMWIDE_ROLES`); a
# Manager, Executive or Reviewer sees only the clients in
# `user_client_assignments`.
#
# This router already imported core.authz and already called
# assert_client_access -- on the four POST bodies. Every endpoint that took its
# client from a QUERY PARAMETER, and every one addressed by a row id, was
# unguarded. A guard on the input and none on the record reads as handled.
#
# TWO SHAPES, BECAUSE THIS ROUTER REPORTS "NOT FOUND" TWO DIFFERENT WAYS.
#
#   * Endpoints that NAME a client (`client_id` query param) get
#     `assert_client_access`, which raises 404 -- the same answer every other
#     audited router gives. It goes BEFORE the `try`, because every handler
#     here ends in a bare `except Exception: return api_response(False, ...)`
#     that would otherwise swallow the refusal into a 200.
#
#   * Endpoints addressed by a ROW id report a missing row as a 200 carrying
#     `{"success": false, "error": "Not found"}`, not a 404. Raising a 404 for
#     the refusal would make the STATUS CODE the oracle: 404 = the id is real
#     and belongs to someone else, 200 = it does not exist. So those go through
#     `_visible_or_none`, which sends the refusal down the router's own
#     not-found path byte for byte.

def _visible_or_none(current_user: dict, rec: Optional[dict]) -> Optional[dict]:
    """`rec` if the caller may see its client, otherwise None.

    Deliberately the boolean check rather than the raising one: the caller's
    existing not-found branch is the response we want, and re-implementing it
    at each call site is how the two answers drift apart.
    """
    if rec is None:
        return None
    if not can_access_client(current_user, rec.get("client_id")):
        return None
    return rec


# ── Helpers ───────────────────────────────────────────────────────────────────

def _tds_return_due_date(quarter: str, fy: str) -> str:
    """24Q/26Q filing due date per IT Rules Rule 31A: Q1 → 31 Jul, Q2 → 31 Oct,
    Q3 → 31 Jan, Q4 → 31 May. F17 fix: this used to compute Q4 as
    "{fy_start_year}-04-31" — a date that does not exist (April has 30 days),
    in the wrong month (Rule 31A gives Q4 until 31 May, not "the month after
    quarter end" like Q1-Q3) and the wrong year (the FY's START year instead
    of the year Q4 actually ends in). Delegates to the shared FY-aware
    calendar in domain/tds/section_rates.py."""
    from domain.tds.section_rates import quarter_dates
    try:
        return quarter_dates(fy, quarter)[2]
    except ValueError:
        return quarter_dates(fy, "Q1")[2]  # preserve old .get(quarter, Q1) fallback


def _certificate_display(certificate_type: str, fy: str) -> dict:
    """What this certificate is CALLED in its own period, and what else changed.

    The stored key stays the 1961-Act one — '16' / '16A' — because that is what
    migration 037's CHECK holds and because CLAUDE.md's rule is to translate at
    the boundary and never rekey a store. This is that boundary.

    `certificate_note` is not decoration. Form 131 is issued QUARTERLY where
    Form 16A was annual, and Form 130 has three parts where Form 16 had two, so
    a screen that swapped the number and kept the cadence would show one
    certificate where four are due. domain/tds/vocabulary.py holds both.

    16B and 16C (s. 194-IA / s. 194-IB property deductions) have no kind in the
    vocabulary module, so they are returned under their own name rather than
    guessed at — a wrong form number is worse than an unchanged one.
    """
    from domain.tds import vocabulary
    kind = _CERTIFICATE_KIND.get(certificate_type)
    if kind is None:
        return {"certificate_form": certificate_type, "certificate_note": None}
    try:
        return {"certificate_form": vocabulary.certificate_form(kind, fy_label=fy),
                "certificate_note": vocabulary.certificate_note(kind, fy_label=fy)}
    except vocabulary.VocabularyError:
        # An FY the vocabulary cannot place. Say the stored name rather than
        # inventing one; the row is still correct, only its label is unknown.
        return {"certificate_form": certificate_type, "certificate_note": None}


def _tds_quarter_end(quarter: str, fy: str) -> str:
    """The quarter's last day — 30 Jun, 30 Sep, 31 Dec, 31 Mar.

    tds_returns.quarter_end is DATE NOT NULL with no default (migration 037).
    create_return never wrote it, so the insert raised on every real database
    and the handler's `except Exception` turned that into an HTTP 200 carrying
    {success: false} that the screen did not inspect (TDS-03). Mock mode never
    saw it: a dict store has no NOT NULL.

    Same quarter_dates call the due date uses, and the same Q1 fallback, so an
    unrecognised quarter cannot give a row whose end and due date describe
    different periods.
    """
    from domain.tds.section_rates import quarter_dates
    try:
        return quarter_dates(fy, quarter)[1]
    except ValueError:
        return quarter_dates(fy, "Q1")[1]


# ── Request Models ─────────────────────────────────────────────────────────────

class CreateChallanRequest(BaseModel):
    client_id: str
    bsr_code: str = Field(..., description="7-digit BSR code of bank branch")
    challan_date: str = Field(..., description="YYYY-MM-DD")
    amount_paise: int = Field(..., description="Integer paise only")
    challan_no: str
    section: str = Field(..., description="e.g. 194A, 192, 194Q")
    financial_year: FYLabel = Field(..., description="e.g. 2025-26")
    quarter: str = Field(..., description="Q1, Q2, Q3, Q4")


class CreateDeductionRequest(BaseModel):
    """A deduction a CA types in, rather than one a purchase bill produced.

    NOTE WHAT IS ABSENT: there is no rate and no tax amount. Both are the
    ENGINE's answers. The /tds screen used to send its own, computed in the
    browser from a hardcoded table that had s.194D and s.194H at 5% where the
    statute says 2%, s.194C flat at the company rate, s.194Q charged on the
    whole sum instead of the excess, and no threshold on anything (TDS-05).
    Accepting a caller's rate here would keep that defect alive behind an
    endpoint that looks authoritative.
    """
    client_id: str
    deductee_name: str = Field(..., min_length=1)
    # The payee's PAN. Optional because a deduction genuinely can be made
    # without one — and when it is, IT Act s.206AA floors the rate at 20%,
    # which resolve_tds applies from this very field.
    deductee_pan: Optional[str] = None
    section: str = Field(..., description="e.g. 194C, 194J — must be one the engine holds")
    # The TAXABLE amount, excluding GST (CBDT Circular 23/2017) — the same
    # meaning services/tds_register_service.py gives the column it lands in.
    payment_amount_paise: int = Field(..., ge=0)
    transaction_date: str = Field(..., description="YYYY-MM-DD")
    nature_of_payment: Optional[str] = None
    challan_no: Optional[str] = None
    notes: Optional[str] = None


class UpdateDeductionRequest(BaseModel):
    """Every field optional; whatever is supplied is re-run through the engine.

    A hand-entered row has to be correctable — without this the only way to fix
    a typo would be a direct PostgREST write, which is the hole migration 345
    closed.
    """
    deductee_name: Optional[str] = None
    deductee_pan: Optional[str] = None
    section: Optional[str] = None
    payment_amount_paise: Optional[int] = Field(default=None, ge=0)
    transaction_date: Optional[str] = None
    nature_of_payment: Optional[str] = None
    challan_no: Optional[str] = None
    notes: Optional[str] = None


class CreateReturnRequest(BaseModel):
    client_id: str
    return_type: str = Field(..., description="24Q or 26Q")
    quarter: str
    financial_year: FYLabel
    deductee_details: list[dict] = Field(default_factory=list)
    # Populated when saving a "Compute from Books" result (services/
    # tds_return_service.py) — optional so the existing quick-create form
    # (which never supplies these) keeps working unchanged.
    total_deductions_paise: Optional[int] = None
    total_deposits_paise: Optional[int] = None
    deductee_count: Optional[int] = None
    validation_errors: Optional[list[str]] = None


class UpdateReturnStatusRequest(BaseModel):
    status: str
    ca_approved: bool = False
    # Government proof-of-filing — required to actually transition to "filed"
    # (migration 037: tds_returns.prn/ack_number/filed_at). Previously this
    # endpoint only ever wrote `status`, so a CA could mark a return "filed"
    # with no PRN/acknowledgement captured anywhere server-side.
    prn: Optional[str] = None
    ack_number: Optional[str] = None
    filing_date: Optional[str] = None


#: What the CHECK on tds_certificates.certificate_type accepts (migration 037),
#: keyed by every label a caller has ever sent. The screen sent "Form 16A" and
#: the constraint wanted "16A", so EVERY certificate insert was rejected by the
#: database — and the handler's `except Exception` turned that into an HTTP 200
#: carrying {success: false} that the screen never inspected (TDS-04).
#:
#: Normalising here rather than only fixing the screen, because the value is
#: what a HUMAN calls the form and there are several right spellings of it. The
#: 2025 Act numbers are accepted and map to the SAME stored key: CLAUDE.md's
#: rule is translate at the boundary and never rekey a store, so a certificate
#: for FY 2026-27 is stored '16A' and DISPLAYED as Form 131.
_CERTIFICATE_TYPES = {
    "16": "16", "form 16": "16", "130": "16", "form 130": "16",
    "16a": "16A", "form 16a": "16A", "131": "16A", "form 131": "16A",
    "16b": "16B", "form 16b": "16B",
    "16c": "16C", "form 16c": "16C",
}

#: The certificate KIND each stored key is, for domain/tds/vocabulary.py — the
#: single module that knows the 2025 Act renumbering. 16B and 16C (s. 194-IA
#: and s. 194-IB property deductions) have no kind there; they are stored and
#: displayed under their own name rather than guessed at.
_CERTIFICATE_KIND = {"16": "salary_certificate", "16A": "non_salary_certificate"}


class CreateCertificateRequest(BaseModel):
    client_id: str
    deductee_pan: str
    deductee_name: str
    financial_year: FYLabel
    certificate_type: str = Field(
        ..., description="16, 16A, 16B or 16C — 'Form 16A' and the 2025 Act's "
                         "130/131 are accepted and normalised")
    tds_amount_paise: int = Field(default=0, description="Integer paise only")
    section: str

    @field_validator("certificate_type")
    @classmethod
    def _known_certificate(cls, v: str) -> str:
        key = _CERTIFICATE_TYPES.get((v or "").strip().lower())
        if key is None:
            raise ValueError(
                f"{v!r} is not a TDS certificate. Expected 16 (salary), "
                "16A (non-salary), 16B or 16C — the values migration 037's "
                "CHECK accepts. 'Form 16A' and the 2025 Act's 130/131 are "
                "accepted too and stored under the 1961-Act key.")
        return key


class Form26ASUploadRequest(BaseModel):
    client_id: str
    financial_year: FYLabel
    file_url: Optional[str] = None
    raw_data: dict = Field(default_factory=dict)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/")
def tds_dashboard(
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("tds", "read")),
):
    """TDS filing dashboard — summary of deductions, challans, returns."""
    assert_client_access(current_user, client_id)
    try:
        firm_id = current_user["firm_id"]
        if _USE_MOCK:
            challans = [c for c in _MOCK_CHALLANS.values() if c["client_id"] == client_id]
            returns = [r for r in _MOCK_RETURNS.values() if r["client_id"] == client_id]
            certs = [c for c in _MOCK_CERTIFICATES.values() if c["client_id"] == client_id]
        else:
            from core.supabase_client import get_supabase
            sb = get_supabase()
            challans = sb.table("tds_challans").select("*").eq("firm_id", firm_id).eq("client_id", client_id).execute().data or []
            returns = sb.table("tds_returns").select("*").eq("firm_id", firm_id).eq("client_id", client_id).execute().data or []
            certs = sb.table("tds_certificates").select("*").eq("firm_id", firm_id).eq("client_id", client_id).execute().data or []

        # tds_challans has no amount_paise column (migration 037) — total_paise
        # is the real grand-total column.
        total_deposited_paise = sum(c.get("total_paise", 0) for c in challans)
        return api_response(True, {
            "challans": challans,
            "returns": returns,
            "certificates": certs,
            "summary": {
                "total_challans": len(challans),
                "total_returns": len(returns),
                "total_certificates": len(certs),
                "total_deposited_paise": total_deposited_paise,
            },
        })
    except Exception as e:
        _logger.exception("tds_dashboard error")
        return api_response(False, None, str(e))


@router.get("/deductions")
def list_deductions(
    client_id: str = Query(...),
    quarter: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(rbac("tds", "read")),
):
    """List TDS deductions for client. IT Act §192-194Q."""
    assert_client_access(current_user, client_id)
    try:
        firm_id = current_user["firm_id"]
        if _USE_MOCK:
            rows = [d for d in _MOCK_DEDUCTIONS.values() if d["client_id"] == client_id]
            if quarter:
                rows = [d for d in rows if d.get("quarter") == quarter]
            rows = rows[offset:offset + limit]
        else:
            from core.supabase_client import get_supabase
            sb = get_supabase()
            q = sb.table("tds_deductions").select("*").eq("firm_id", firm_id).eq("client_id", client_id)
            if quarter:
                q = q.eq("quarter", quarter)
            rows = q.range(offset, offset + limit - 1).execute().data or []

        return api_response(True, rows)
    except Exception as e:
        return api_response(False, None, str(e))


# ── Deductions a CA types in ─────────────────────────────────────────────────
#
# TDS-05. Until these existed there was NO endpoint anywhere in apps/api that
# created a tds_deductions row — the only writer was sync_for_bill, off the
# purchase-bill path. So the /tds screen did the only thing left to it: it
# computed the tax in the browser from a hardcoded table and inserted straight
# over PostgREST, where rbac() does not run and the engine is never consulted.
#
# The engine decides everything here. The request carries facts (who, how much,
# which section, what date); the rate, the threshold test, the s.206AA floor and
# the FY aggregate are all resolve_tds's answers.


def _resolve_manual_deduction(db, firm_id: str, client_id: str, body: dict,
                              exclude_id: Optional[str] = None) -> dict:
    """Run one hand-entered deduction through the engine and return the row to
    store, plus what the CA needs told about it.

    Raises HTTPException(422) with the engine's own words when the section is
    one it does not hold — s.194IA is the live example, offered by the old
    screen's dropdown and absent from domain/tds/section_rates.py, so every
    such row was a number no backend path could reproduce.
    """
    from datetime import date as _date
    from domain.tds import manual_register
    from domain.tds.tds_computer import TDSComputer, is_company_pan, has_pan
    from services.tds_register_service import fy_quarter

    section = (body.get("section") or "").upper().strip()
    pan = (body.get("deductee_pan") or "").upper().strip() or None
    try:
        when = _date.fromisoformat(str(body.get("transaction_date"))[:10])
    except ValueError:
        raise HTTPException(status_code=422,
                            detail="transaction_date must be YYYY-MM-DD")
    taxable = int(body.get("payment_amount_paise") or 0)

    prior_taxable, prior_tds = (0, 0)
    if not _USE_MOCK and db is not None:
        prior_taxable, prior_tds = manual_register.prior_manual_aggregate(
            db, firm_id=firm_id, client_id=client_id, section=section,
            deductee_pan=pan, on=when, exclude_id=exclude_id)

    try:
        res = TDSComputer().resolve_tds(
            section=section,
            taxable_paise=taxable,
            # BOTH limbs or neither. CLAUDE.md: a caller passing the first
            # without the second re-charges the growing aggregate on every
            # later entry.
            fy_prior_taxable_paise=prior_taxable,
            fy_prior_tds_paise=prior_tds,
            # Individual or company is read off the PAN's 4th character, not
            # asked. s.194C is 1% for an individual and 2% for a company, and
            # the old screen charged everyone 2%.
            is_company=is_company_pan(pan),
            # The FY the PAYMENT falls in, not today's — a deduction entered
            # late for a prior year must use that year's law.
            fy=manual_register.fy_label(when),
            # IT Act s.206AA — no PAN floors the rate at 20%.
            has_pan=has_pan(pan),
        )
    except ValueError as ve:
        raise HTTPException(status_code=422, detail=str(ve))

    # Named on EVERY row, not only where it currently bites. The CA cannot tell
    # from the number whether the register this aggregate does not see would
    # have changed it, and a gap that appears only sometimes reads as a fault
    # in the data rather than a known limit of the calculation.
    gaps = [manual_register.GAP_REGISTERS_NOT_UNIFIED]

    row = {
        "firm_id": firm_id,
        "client_id": client_id,
        "deductee_name": (body.get("deductee_name") or "").strip(),
        "deductee_pan": pan,
        "section": section,
        "nature_of_payment": body.get("nature_of_payment") or None,
        "transaction_date": when.isoformat(),
        # The TAXABLE amount, excluding GST (CBDT Circular 23/2017) — the same
        # meaning tds_register_service gives this column on the bill path.
        "payment_amount_paise": taxable,
        # The rate ACTUALLY applied: 0 when below the threshold, so a s.203
        # certificate cannot later claim a rate was used when nothing was
        # deducted. Same rule as routers/purchase_bills.py.
        "tds_rate_pct": (res.rate_bps / 100) if res.applies else 0,
        "tds_paise": res.tds_paise,
        # A resident section deducts at the bare rate and carries neither.
        # s.195 is not reachable here: it needs chargeability, a treaty and a
        # nature of income, which is the purchase-bill path's job.
        "surcharge_paise": 0,
        "cess_paise": 0,
        # ONE quarter vocabulary, and it is now the schema's own:
        # services/tds_register_service.fy_quarter returns the bare "Q3" and
        # the year goes in financial_year, matching tds_returns, tds_challans
        # and tds_certificates and the CHECK migration 347 adds. It is imported
        # rather than spelt again here. The /tds screen used to write
        # "Q1 (Apr-Jun)" and the bill path "Q3 2025-26" — three spellings on a
        # column that had no CHECK, which is why no reader matched any of them.
        "quarter": fy_quarter(when),
        "financial_year": manual_register.fy_label(when),
        "challan_no": body.get("challan_no") or None,
        "notes": body.get("notes") or None,
    }
    explain = {
        "applies": res.applies,
        "reason": getattr(res, "reason", None),
        "rate_pct": res.rate_bps / 100,
        "tds_paise": res.tds_paise,
        "fy_prior_taxable_paise": prior_taxable,
        "fy_prior_tds_paise": prior_tds,
        "gaps": gaps,
        "gap_messages": [manual_register.GAP_MESSAGES[g] for g in gaps
                         if g in manual_register.GAP_MESSAGES],
    }
    return {"row": row, "explain": explain}


@router.post("/deductions")
def create_deduction(
    body: CreateDeductionRequest,
    current_user: dict = Depends(rbac("tds", "compute")),
):
    """Record a deduction, with the ENGINE deciding the tax.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT. Nothing here reaches TRACES or
    # any portal; this is the firm's own register.
    """
    assert_client_access(current_user, body.client_id)
    firm_id = current_user["firm_id"]
    payload = body.model_dump()
    try:
        if _USE_MOCK:
            resolved = _resolve_manual_deduction(None, firm_id, body.client_id, payload)
            rec = {"id": str(uuid.uuid4()), **resolved["row"]}
            _MOCK_DEDUCTIONS[rec["id"]] = rec
            return api_response(True, {**rec, "explain": resolved["explain"]})

        from core.supabase_client import get_supabase
        db = get_supabase()
        resolved = _resolve_manual_deduction(db, firm_id, body.client_id, payload)
        row = resolved["row"]
        # Keys spelt INLINE. tests/test_backend_columns_exist_pg.py can only
        # read a payload whose keys are string constants; .insert(a_variable) is
        # counted as an unreadable reference and its columns stop being checked
        # against the real schema. Same reason the year-end and compliance
        # writes are spelt out.
        ins = db.table("tds_deductions").insert({
            "firm_id": row["firm_id"],
            "client_id": row["client_id"],
            "deductee_name": row["deductee_name"],
            "deductee_pan": row["deductee_pan"],
            "section": row["section"],
            "nature_of_payment": row["nature_of_payment"],
            "transaction_date": row["transaction_date"],
            "payment_amount_paise": row["payment_amount_paise"],
            "tds_rate_pct": row["tds_rate_pct"],
            "tds_paise": row["tds_paise"],
            "surcharge_paise": row["surcharge_paise"],
            "cess_paise": row["cess_paise"],
            "quarter": row["quarter"],
            "financial_year": row["financial_year"],
            "challan_no": row["challan_no"],
            "notes": row["notes"],
        }).execute().data or []
        rec = ins[0] if ins else row
        log_event(firm_id, "tds_deduction", rec.get("id", ""), "create",
                  actor_id=current_user.get("auth_user_id"),
                  actor_email=current_user.get("email"),
                  new_data={"section": row["section"],
                            "tds_paise": row["tds_paise"]})
        return api_response(True, {**rec, "explain": resolved["explain"]})
    except HTTPException:
        raise
    except Exception as e:                                        # noqa: BLE001
        _logger.error("create_deduction failed: %s", e)
        return api_response(False, None, "Could not record the deduction.")


@router.post("/deductions/preview")
def preview_deduction(
    body: CreateDeductionRequest,
    current_user: dict = Depends(rbac("tds", "compute")),
):
    """What WOULD be deducted, without recording anything.

    THE SAME FUNCTION AS THE SAVE, deliberately. A preview computed by a
    different route than the write is the defect TDS-14 describes on the
    purchase-bill side — the editor shows a browser-side rate x base and the
    server then applies a threshold, a s.206AA floor and an FY aggregate, so
    the figure a CA approved is not the figure that lands.

    POST /api/tds/compute-amount is close but NOT sufficient here: its request
    model has no fy_prior_taxable_paise / fy_prior_tds_paise, so it always
    answers as though this were the payee's first payment of the year. On the
    bill that crosses an aggregate threshold that is the whole difference.
    """
    assert_client_access(current_user, body.client_id)
    firm_id = current_user["firm_id"]
    db = None
    if not _USE_MOCK:
        from core.supabase_client import get_supabase
        db = get_supabase()
    resolved = _resolve_manual_deduction(db, firm_id, body.client_id, body.model_dump())
    return api_response(True, {
        # Everything the CA needs to see BEFORE committing, and nothing stored.
        "section": resolved["row"]["section"],
        "payment_amount_paise": resolved["row"]["payment_amount_paise"],
        "tds_rate_pct": resolved["row"]["tds_rate_pct"],
        "tds_paise": resolved["row"]["tds_paise"],
        "quarter": resolved["row"]["quarter"],
        "financial_year": resolved["row"]["financial_year"],
        "explain": resolved["explain"],
    })


@router.patch("/deductions/{deduction_id}")
def update_deduction(
    deduction_id: str,
    body: UpdateDeductionRequest,
    current_user: dict = Depends(rbac("tds", "compute")),
):
    """Correct a hand-entered deduction. Re-resolved through the engine.

    A row that came from a purchase bill is REFUSED: it is owned by
    sync_for_bill and would be overwritten on the next receive, so editing it
    here would look like it worked and silently revert.
    """
    firm_id = current_user["firm_id"]
    try:
        if _USE_MOCK:
            rec = _visible_or_none(current_user, _MOCK_DEDUCTIONS.get(deduction_id))
            if rec is None:
                return api_response(False, None, "Not found")
            merged = {**rec, **{k: v for k, v in body.model_dump().items() if v is not None}}
            resolved = _resolve_manual_deduction(None, firm_id, rec["client_id"], merged,
                                                 exclude_id=deduction_id)
            rec.update(resolved["row"])
            return api_response(True, {**rec, "explain": resolved["explain"]})

        from core.supabase_client import get_supabase
        db = get_supabase()
        got = (db.table("tds_deductions").select("*")
               .eq("id", deduction_id).eq("firm_id", firm_id).limit(1).execute().data) or []
        rec = _visible_or_none(current_user, got[0] if got else None)
        if rec is None:
            return api_response(False, None, "Not found")
        if rec.get("purchase_bill_id"):
            return api_response(False, None,
                                "This deduction came from a purchase bill. Edit the bill "
                                "instead — the register is rebuilt from it on every receive.")
        merged = {**rec, **{k: v for k, v in body.model_dump().items() if v is not None}}
        resolved = _resolve_manual_deduction(db, firm_id, rec["client_id"], merged,
                                             exclude_id=deduction_id)
        row = resolved["row"]
        # Inline again, and only the columns an edit may move — firm_id and
        # client_id are the row's identity, not its content.
        upd = (db.table("tds_deductions").update({
            "deductee_name": row["deductee_name"],
            "deductee_pan": row["deductee_pan"],
            "section": row["section"],
            "nature_of_payment": row["nature_of_payment"],
            "transaction_date": row["transaction_date"],
            "payment_amount_paise": row["payment_amount_paise"],
            "tds_rate_pct": row["tds_rate_pct"],
            "tds_paise": row["tds_paise"],
            "surcharge_paise": row["surcharge_paise"],
            "cess_paise": row["cess_paise"],
            "quarter": row["quarter"],
            "financial_year": row["financial_year"],
            "challan_no": row["challan_no"],
            "notes": row["notes"],
        }).eq("id", deduction_id).eq("firm_id", firm_id).execute().data) or []
        log_event(firm_id, "tds_deduction", deduction_id, "update",
                  actor_id=current_user.get("auth_user_id"),
                  actor_email=current_user.get("email"),
                  new_data={"tds_paise": row["tds_paise"]})
        return api_response(True, {**(upd[0] if upd else row),
                                   "explain": resolved["explain"]})
    except HTTPException:
        raise
    except Exception as e:                                        # noqa: BLE001
        _logger.error("update_deduction failed: %s", e)
        return api_response(False, None, "Could not update the deduction.")


@router.delete("/deductions/{deduction_id}")
def delete_deduction(
    deduction_id: str,
    current_user: dict = Depends(rbac("tds", "write")),
):
    """Remove a hand-entered deduction.

    tds:write (Manager+), NOT tds:compute — the same tier migration 345 gives
    DELETE on this table, because removing a statutory register row is not data
    entry. A bill-sourced row is refused for the same reason as the edit.
    """
    firm_id = current_user["firm_id"]
    try:
        if _USE_MOCK:
            rec = _visible_or_none(current_user, _MOCK_DEDUCTIONS.get(deduction_id))
            if rec is None:
                return api_response(False, None, "Not found")
            _MOCK_DEDUCTIONS.pop(deduction_id, None)
            return api_response(True, {"deleted": deduction_id})

        from core.supabase_client import get_supabase
        db = get_supabase()
        got = (db.table("tds_deductions").select("*")
               .eq("id", deduction_id).eq("firm_id", firm_id).limit(1).execute().data) or []
        rec = _visible_or_none(current_user, got[0] if got else None)
        if rec is None:
            return api_response(False, None, "Not found")
        if rec.get("purchase_bill_id"):
            return api_response(False, None,
                                "This deduction came from a purchase bill. Cancel or edit "
                                "the bill instead.")
        db.table("tds_deductions").delete().eq("id", deduction_id).eq("firm_id", firm_id).execute()
        log_event(firm_id, "tds_deduction", deduction_id, "delete",
                  actor_id=current_user.get("auth_user_id"),
                  actor_email=current_user.get("email"), new_data=dict(rec))
        return api_response(True, {"deleted": deduction_id})
    except HTTPException:
        raise
    except Exception as e:                                        # noqa: BLE001
        _logger.error("delete_deduction failed: %s", e)
        return api_response(False, None, "Could not delete the deduction.")


@router.get("/challans")
def list_challans(
    client_id: str = Query(...),
    from_date: Optional[str] = Query(None, description="Filter by payment_date >= from_date (YYYY-MM-DD)"),
    to_date: Optional[str] = Query(None, description="Filter by payment_date <= to_date (YYYY-MM-DD)"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(rbac("tds", "read")),
):
    """List TDS challans for client."""
    assert_client_access(current_user, client_id)
    try:
        firm_id = current_user["firm_id"]
        if _USE_MOCK:
            rows = [c for c in _MOCK_CHALLANS.values() if c["client_id"] == client_id]
            if from_date:
                rows = [r for r in rows if r.get("payment_date", "") >= from_date]
            if to_date:
                rows = [r for r in rows if r.get("payment_date", "") <= to_date]
            rows = rows[offset:offset + limit]
        else:
            from core.supabase_client import get_supabase
            # tds_challans has no challan_date column (migration 037) — payment_date
            # is the real date column.
            q = get_supabase().table("tds_challans").select("*").eq("firm_id", firm_id).eq("client_id", client_id)
            if from_date:
                q = q.gte("payment_date", from_date)
            if to_date:
                q = q.lte("payment_date", to_date)
            rows = q.range(offset, offset + limit - 1).execute().data or []
        return api_response(True, rows)
    except Exception as e:
        return api_response(False, None, str(e))


@router.post("/challans")
def create_challan(
    body: CreateChallanRequest,
    current_user: dict = Depends(rbac("tds", "compute")),
):
    """Create TDS challan record. IT Act §200."""
    try:
        assert_client_access(current_user, body.client_id)
        firm_id = current_user["firm_id"]
        # Period validation — prevent posting to locked financial years (migration 020)
        period_validation_service.validate_posting_date(firm_id or "", body.challan_date)
        record = {
            "id": str(uuid.uuid4()),
            "firm_id": firm_id,
            "client_id": body.client_id,
            "bsr_code": body.bsr_code,
            # tds_challans has no challan_date/amount_paise columns (migration
            # 037) — payment_date is the real date column, and with no
            # surcharge/interest/penalty breakout on this quick-create form
            # the full amount is booked as pure TDS (tds_paise == total_paise).
            "payment_date": body.challan_date,
            "tds_paise": body.amount_paise,
            "total_paise": body.amount_paise,
            "challan_no": body.challan_no,
            "section": body.section,
            "financial_year": body.financial_year,
            "quarter": body.quarter,
            "status": "deposited",
            "created_at": datetime.utcnow().isoformat(),
        }

        if _USE_MOCK:
            _MOCK_CHALLANS[record["id"]] = record
        else:
            from core.supabase_client import get_supabase
            get_supabase().table("tds_challans").insert(record).execute()

        log_event(firm_id, "tds_challan", record["id"], "create",
                  actor_id=current_user.get("id"), new_data=record)
        timeline_service.log_timeline_event(
            client_id=body.client_id, firm_id=firm_id,
            financial_year=body.financial_year, category="tds",
            event_type="tds_challan_deposited",
            title=f"TDS Challan deposited: ₹{body.amount_paise // 100} under {body.section}",
        )
        return api_response(True, record)
    except HTTPException:
        raise
    except Exception as e:
        return api_response(False, None, str(e))


@router.get("/challans/{challan_id}")
def get_challan(challan_id: str, current_user: dict = Depends(rbac("tds", "read"))):
    """Get TDS challan by ID."""
    try:
        firm_id = current_user["firm_id"]
        if _USE_MOCK:
            rec = _MOCK_CHALLANS.get(challan_id)
        else:
            from core.supabase_client import get_supabase
            rows = get_supabase().table("tds_challans").select("*").eq("id", challan_id).eq("firm_id", firm_id).execute().data
            rec = rows[0] if rows else None
        rec = _visible_or_none(current_user, rec)
        if not rec:
            return api_response(False, None, "Not found")
        return api_response(True, rec)
    except Exception as e:
        return api_response(False, None, str(e))


@router.get("/returns")
def list_returns(
    client_id: str = Query(...),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(rbac("tds", "read")),
):
    """List TDS returns for client."""
    assert_client_access(current_user, client_id)
    try:
        firm_id = current_user["firm_id"]
        if _USE_MOCK:
            rows = [r for r in _MOCK_RETURNS.values() if r["client_id"] == client_id]
            rows = rows[offset:offset + limit]
        else:
            from core.supabase_client import get_supabase
            rows = get_supabase().table("tds_returns").select("*").eq("firm_id", firm_id).eq("client_id", client_id).range(offset, offset + limit - 1).execute().data or []
        return api_response(True, rows)
    except Exception as e:
        return api_response(False, None, str(e))


@router.post("/returns")
def create_return(
    body: CreateReturnRequest,
    current_user: dict = Depends(rbac("tds", "compute")),
):
    """Create/save TDS return (24Q/26Q). IT Act §200."""
    try:
        assert_client_access(current_user, body.client_id)
        firm_id = current_user["firm_id"]
        # Validate that the FY is not locked — use April 1 of the FY start year
        fy_str = body.financial_year or ""
        if fy_str and len(fy_str) >= 4:
            fy_start_year = int(fy_str[:4])
            fy_start_date = f"{fy_start_year}-04-01"
            period_validation_service.validate_posting_date(firm_id or "", fy_start_date)
        # IT Act §206AA: PAN sentinels ("PANNOTAVBL"/"PANAPPLIED") are valid —
        # same rule domain/tds/tds_computer.py enforces for return computation.
        for d in body.deductee_details:
            pan = d.get("deductee_pan")
            if pan and not TDSValidator.validate_pan(str(pan).strip().upper()):
                raise HTTPException(status_code=422,
                                    detail=f"Invalid deductee PAN format: '{pan}'. "
                                           "Expected: AAAAA9999A, or PANNOTAVBL/PANAPPLIED if unavailable.")
        record = {
            "id": str(uuid.uuid4()),
            "firm_id": firm_id,
            "client_id": body.client_id,
            "return_type": body.return_type,
            "quarter": body.quarter,
            "financial_year": body.financial_year,
            "status": "pending",
            # quarter_end is DATE NOT NULL with no default (migration 037) and
            # nothing ever supplied it, so this insert failed outright on any
            # real database while every mock-mode test passed — the dict store
            # has no NOT NULL. Same source as the due date, so the two cannot
            # disagree about which quarter this is.
            "quarter_end": _tds_quarter_end(body.quarter, body.financial_year),
            "due_date": _tds_return_due_date(body.quarter, body.financial_year),
            "created_at": datetime.utcnow().isoformat(),
        }
        # tds_returns has no deductee_details column (migration 037) — fvu_json
        # is the real holder for deductee-level detail. Only set it when the
        # caller actually supplied rows (this quick-create form never does).
        if body.deductee_details:
            record["fvu_json"] = {"deductees": body.deductee_details}
        # Only ever set by the "Compute from Books" flow (services/
        # tds_return_service.py) — the quick-create form leaves these columns
        # at their DB default (0/NULL) since it has no computed figures yet.
        if body.total_deductions_paise is not None:
            record["total_deductions_paise"] = body.total_deductions_paise
        if body.total_deposits_paise is not None:
            record["total_deposits_paise"] = body.total_deposits_paise
        if body.deductee_count is not None:
            record["deductee_count"] = body.deductee_count
        if body.validation_errors is not None:
            record["validation_errors"] = body.validation_errors

        if _USE_MOCK:
            _MOCK_RETURNS[record["id"]] = record
        else:
            from core.supabase_client import get_supabase
            get_supabase().table("tds_returns").insert(record).execute()

        log_event(firm_id, "tds_return", record["id"], "create",
                  actor_id=current_user.get("id"), new_data=record)
        return api_response(True, record)
    except HTTPException:
        raise
    except Exception as e:
        return api_response(False, None, str(e))


@router.patch("/returns/{return_id}/status")
def update_return_status(
    return_id: str,
    body: UpdateReturnStatusRequest,
    current_user: dict = Depends(rbac("tds", "compute")),
):
    """
    Update TDS return status: pending → prepared → ca_approved → filed.
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to TRACES.
    """
    try:
        firm_id = current_user["firm_id"]
        allowed = {"pending", "prepared", "ca_approved", "filed"}
        if body.status not in allowed:
            return api_response(False, None, f"Invalid status. Allowed: {allowed}")

        # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
        if body.status in ("ca_approved", "filed") and not body.ca_approved:
            return api_response(False, None,
                "Explicit ca_approved=true required for ca_approved/filed status. CA must confirm.")

        # IT Act §200/§203: only Manager+ can approve/file a TDS return —
        # ca_approved=true alone is a caller-supplied flag, not proof of role.
        if body.status in ("ca_approved", "filed"):
            from core.permissions import can
            role = current_user.get("role", "executive")
            if not can(role, "tds", "approve"):
                return api_response(False, None,
                    "Only Manager or above can approve or file a TDS return.")

        if body.status == "filed" and not (body.prn or "").strip():
            return api_response(False, None,
                "PRN (Provisional Receipt Number) is required to mark a return as filed.")

        if _USE_MOCK:
            current = _MOCK_RETURNS.get(return_id)
        else:
            from core.supabase_client import get_supabase
            existing = (
                # client_id is selected purely so the scope check below has
                # something to check -- the status is what this handler reads.
                get_supabase().table("tds_returns").select("status, client_id")
                .eq("id", return_id).eq("firm_id", firm_id).limit(1).execute().data
            )
            current = existing[0] if existing else None
        # Before the update, not after: this endpoint writes the PRN that marks a
        # statutory return FILED. A refusal that arrives afterwards is not one.
        current = _visible_or_none(current_user, current)
        if current is None:
            return api_response(False, None, "Not found")
        current_status = current.get("status")

        # A return can only be filed once — a repeated/duplicate "mark filed"
        # request (double-click, retry) must not silently overwrite the
        # original PRN/acknowledgement with a second one.
        if body.status == "filed" and current_status == "filed":
            return api_response(False, None, "This return has already been filed.")

        now_iso = datetime.utcnow().isoformat()
        update_payload: dict = {"status": body.status}
        if body.status == "ca_approved":
            update_payload["ca_approved_by"] = current_user.get("id")
            update_payload["ca_approved_at"] = now_iso
        if body.status == "filed":
            update_payload["prn"] = body.prn
            update_payload["ack_number"] = body.ack_number
            update_payload["filed_at"] = body.filing_date or now_iso

        if _USE_MOCK:
            _MOCK_RETURNS[return_id].update(update_payload)
            rec = _MOCK_RETURNS[return_id]
        else:
            from core.supabase_client import get_supabase
            rows = get_supabase().table("tds_returns").update(update_payload).eq("id", return_id).eq("firm_id", firm_id).execute().data
            rec = rows[0] if rows else {}

        log_event(firm_id, "tds_return", return_id, "status_change",
                  actor_id=current_user.get("id"), new_data={"status": body.status})
        if body.status == "filed":
            timeline_service.log_timeline_event(
                client_id=rec.get("client_id", ""), firm_id=firm_id,
                financial_year=rec.get("financial_year", ""), category="tds",
                event_type="tds_return_filed",
                title=f"TDS Return {rec.get('return_type', '')} filed for {rec.get('quarter', '')} {rec.get('financial_year', '')}",
                description=f"PRN: {body.prn}" + (f" | Ack: {body.ack_number}" if body.ack_number else ""),
            )
        return api_response(True, rec)
    except Exception as e:
        return api_response(False, None, str(e))


@router.get("/certificates")
def list_certificates(
    client_id: str = Query(...),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(rbac("tds", "read")),
):
    """List TDS certificates (Form 16/16A) for client. IT Act §203."""
    assert_client_access(current_user, client_id)
    try:
        firm_id = current_user["firm_id"]
        if _USE_MOCK:
            rows = [c for c in _MOCK_CERTIFICATES.values() if c["client_id"] == client_id]
            rows = rows[offset:offset + limit]
        else:
            from core.supabase_client import get_supabase
            rows = get_supabase().table("tds_certificates").select("*").eq("firm_id", firm_id).eq("client_id", client_id).range(offset, offset + limit - 1).execute().data or []
        # Every row labelled in ITS OWN period's vocabulary, not the current
        # one: a register holds certificates from several years at once, and
        # the same stored '16A' is Form 16A for FY 2025-26 and Form 131 for
        # 2026-27. Derived per row for that reason.
        rows = [{**r, **_certificate_display(str(r.get("certificate_type") or ""),
                                             str(r.get("financial_year") or ""))}
                for r in rows]
        return api_response(True, rows)
    except Exception as e:
        return api_response(False, None, str(e))


@router.post("/certificates")
def create_certificate(
    body: CreateCertificateRequest,
    current_user: dict = Depends(rbac("tds", "compute")),
):
    """
    Generate Form 16/16A DRAFT certificate. IT Act §203.
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to TRACES or deductee.
    Draft only — CA must review and sign before issuance.
    """
    try:
        assert_client_access(current_user, body.client_id)
        firm_id = current_user["firm_id"]
        deductee_pan = body.deductee_pan.strip().upper()
        # IT Act §206AA: PAN sentinels ("PANNOTAVBL"/"PANAPPLIED") are valid —
        # same rule domain/tds/tds_computer.py enforces for return computation.
        if not TDSValidator.validate_pan(deductee_pan):
            raise HTTPException(status_code=422,
                                detail=f"Invalid deductee PAN format: '{deductee_pan}'. "
                                       "Expected: AAAAA9999A, or PANNOTAVBL/PANAPPLIED if unavailable.")
        # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
        record = {
            "id": str(uuid.uuid4()),
            "firm_id": firm_id,
            "client_id": body.client_id,
            "deductee_pan": deductee_pan,
            "deductee_name": body.deductee_name,
            "financial_year": body.financial_year,
            "certificate_type": body.certificate_type,
            # tds_certificates has no tds_amount_paise/ca_review_required
            # columns (migration 037) — tds_deducted_paise is the real amount
            # column. status must be one of the real CHECK values ('pending',
            # 'generated', 'issued', 'downloaded') — "pending" is also the
            # column's own DEFAULT and matches "freshly generated, CA review
            # required before issuance" (the frontend badge that already
            # renders regardless of the stored value). section is genuinely
            # missing (migration 232).
            "tds_deducted_paise": body.tds_amount_paise,
            "section": body.section,
            "status": "pending",
            "created_at": datetime.utcnow().isoformat(),
        }
        # THE FORM'S NAME IN ITS OWN PERIOD, derived rather than stored — the
        # same posture the register takes with return_type. From 01-04-2026
        # Form 16 is 130 and Form 16A is 131 (CBDT Notification 22/2026), and
        # 131 is issued QUARTERLY where 16A was annual, which is a change of
        # SHAPE and not just of number. domain/tds/vocabulary.py is the one
        # module that knows this; certificate_note is what stops a caller
        # renumbering and issuing one certificate where four are due.
        display = _certificate_display(record["certificate_type"], body.financial_year)

        if _USE_MOCK:
            _MOCK_CERTIFICATES[record["id"]] = record
        else:
            from core.supabase_client import get_supabase
            get_supabase().table("tds_certificates").insert(record).execute()

        log_event(firm_id, "tds_certificate", record["id"], "create",
                  actor_id=current_user.get("id"), new_data=record)
        return api_response(True, {**record, **display})
    except HTTPException:
        raise
    except Exception as e:
        return api_response(False, None, str(e))


@router.post("/form26as/upload")
def upload_form26as(
    body: Form26ASUploadRequest,
    current_user: dict = Depends(rbac("tds", "compute")),
):
    """
    Save a Form 26AS extract the caller has already paired with its book side,
    and record the comparison. IT Act s.285BB with Rule 114-I (s.203AA, cited
    here until now, was omitted by the Finance Act 2020 w.e.f. 01-06-2020).

    Both sides arrive in `raw_data` — `tds_entries` and `book_deductions` — and
    are matched on (PAN, section) plus amount. NOTHING is read from the
    database: despite what this docstring said, it does not reconcile against
    `tds_deductions`, and it never has.

    This is the CLIENT-AS-DEDUCTOR direction — a self-check on the TDS the
    client withheld from its own vendors, which appears in each vendor's 26AS.
    The client's OWN 26AS, listing tax others withheld from it, is reconciled by
    domain/income_tax/form26as_service.py, which reads both sides itself.
    """
    try:
        assert_client_access(current_user, body.client_id)
        firm_id = current_user["firm_id"]
        raw = body.raw_data
        # Reconcile 26AS TDS entries against book deductions
        form26as_entries = raw.get("tds_entries", [])  # [{pan, section, amount_paise, deductor_tan}]
        book_deductions = raw.get("book_deductions", [])

        matched = []
        mismatched = []
        missing_in_26as = []

        form26as_keys = {
            (e.get("pan", ""), e.get("section", "")): e for e in form26as_entries
        }

        for book_ded in book_deductions:
            key = (book_ded.get("deductee_pan", ""), book_ded.get("section", ""))
            if key in form26as_keys:
                f26_entry = form26as_keys[key]
                # Amounts must agree exactly; integer paise, never float
                book_amt = book_ded.get("amount_paise", 0)
                f26_amt = f26_entry.get("amount_paise", 0)
                if book_amt == f26_amt:
                    matched.append({"key": key, "status": "matched"})
                else:
                    mismatched.append({
                        "key": key, "status": "amount_mismatch",
                        "book_paise": book_amt, "form26as_paise": f26_amt,
                        "diff_paise": abs(book_amt - f26_amt),
                    })
            else:
                missing_in_26as.append({"key": key, "status": "missing_in_26as"})

        reconciliation_result = {
            "matched": matched,
            "mismatched": mismatched,
            "missing_in_26as": missing_in_26as,
            "summary": {
                "total_book": len(book_deductions),
                "matched_count": len(matched),
                "mismatch_count": len(mismatched),
                "missing_count": len(missing_in_26as),
            },
        }

        # form_26as_uploads' shape diverged between migration 052 and the live
        # database (see migration 291): 052 declares created_by and no
        # uploaded_by, production has uploaded_by NOT NULL and none of
        # status/file_url/raw_data/reconciliation_result. This record named only
        # the 052 side, so on the live database every insert here failed — first
        # on the missing columns, then on that NOT NULL. 291 adds whichever
        # column each side lacks; naming both identity keys satisfies both.
        record = {
            "id": str(uuid.uuid4()),
            "firm_id": firm_id,
            "client_id": body.client_id,
            "financial_year": body.financial_year,
            "file_url": body.file_url,
            "raw_data": body.raw_data,
            "reconciliation_result": reconciliation_result,
            "status": "reconciled",
            "created_by": current_user.get("id"),
            "uploaded_by": current_user.get("id"),
            "uploaded_at": datetime.utcnow().isoformat(),
            # Shared table, different feature (migration 291). Without this the
            # row lands in the 26AS page's Upload History as a spinner that
            # never resolves — parse_status defaults to 'pending' and this path
            # has no parse step to move it on.
            "source": "tds_workspace",
        }

        if _USE_MOCK:
            _MOCK_FORM26AS[record["id"]] = record
        else:
            from core.supabase_client import get_supabase
            get_supabase().table("form_26as_uploads").insert(record).execute()

        log_event(firm_id, "form_26as_upload", record["id"], "create",
                  actor_id=current_user.get("id"))
        return api_response(True, record)
    except HTTPException:
        raise
    except Exception as e:
        return api_response(False, None, str(e))


@router.get("/form26as/{upload_id}")
def get_form26as(upload_id: str, current_user: dict = Depends(rbac("tds", "read"))):
    """Get Form 26AS reconciliation result."""
    try:
        firm_id = current_user["firm_id"]
        if _USE_MOCK:
            rec = _MOCK_FORM26AS.get(upload_id)
        else:
            from core.supabase_client import get_supabase
            rows = get_supabase().table("form_26as_uploads").select("*").eq("id", upload_id).eq("firm_id", firm_id).execute().data
            rec = rows[0] if rows else None
        rec = _visible_or_none(current_user, rec)
        if not rec:
            return api_response(False, None, "Not found")
        return api_response(True, rec)
    except Exception as e:
        return api_response(False, None, str(e))
