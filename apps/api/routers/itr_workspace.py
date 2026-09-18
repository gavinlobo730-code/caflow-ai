"""
ITR Preparation Workspace — Filing workflow, computation snapshots, disallowances, deductions, losses.
IT Act 1961 — Sections 139, 140, 40A(3), 43B, 72, 74, 80C–80JJAA.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to Income Tax Portal
"""
from __future__ import annotations

import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from core.permissions import rbac
from core.authz import assert_client_access, can_access_client
from models.common import api_response
from services.timeline_service import timeline_service
from models.fy import AYLabel, FYLabel, OptionalAYLabel

router = APIRouter(prefix="/api/itr", tags=["itr_workspace"])
_logger = logging.getLogger("caflow.itr.router")


def _assert_snapshot_scope(current_user: dict, snapshot_id: str) -> dict:
    """Resolve a tax_computation_snapshots row and 404 unless the caller may
    access its client."""
    from domain.income_tax.computation_workspace import get_snapshot
    snap = get_snapshot(current_user["firm_id"], snapshot_id)
    if not snap or not can_access_client(current_user, snap.get("client_id")):
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return snap


def _challan_db():
    """The handle `services/self_assessment_service` reads §140A challans with.

    Guarded rather than unconditional: this router otherwise touches no table
    directly, and the keying sheet must still answer for a firm with no
    database configured (mock mode, local dev) — where the service returns no
    challans and the sheet says so.
    """
    import os
    if not os.environ.get("SUPABASE_URL"):
        return None
    from core.supabase_client import get_supabase
    return get_supabase()


def _assert_filing_scope(current_user: dict, filing_id: str) -> dict:
    """Resolve an itr_filings row and 404 unless the caller may access its
    client. Shared by every endpoint addressed by filing_id (transition,
    save_version, acknowledge) — they all act on the same row."""
    from domain.income_tax.itr_workflow import get_filing
    filing = get_filing(current_user["firm_id"], filing_id)
    if not filing or not can_access_client(current_user, filing.get("client_id")):
        raise HTTPException(status_code=404, detail="Filing not found")
    return filing


def _assert_disallowance_scope(current_user: dict, disallowance_id: str) -> dict:
    """Resolve a tax_disallowances row and 404 unless the caller may access
    its client."""
    from domain.income_tax.computation_workspace import get_disallowance
    dis = get_disallowance(current_user["firm_id"], disallowance_id)
    if not dis or not can_access_client(current_user, dis.get("client_id")):
        raise HTTPException(status_code=404, detail="Disallowance not found")
    return dis


def _assert_bf_loss_scope(current_user: dict, loss_id: str) -> dict:
    """Resolve a brought_forward_losses row and 404 unless the caller may
    access its client."""
    from domain.income_tax.computation_workspace import get_bf_loss
    loss = get_bf_loss(current_user["firm_id"], loss_id)
    if not loss or not can_access_client(current_user, loss.get("client_id")):
        raise HTTPException(status_code=404, detail="Loss record not found")
    return loss


# ── Request Models ─────────────────────────────────────────────────────────────

class CreateFilingRequest(BaseModel):
    client_id: str
    financial_year: FYLabel
    assessment_year: AYLabel
    # ALL SEVEN. The description used to name four, and so did the screen's
    # own list — so a salaried or presumptive client could not have a filing
    # record at all. `itr_workflow.validated_form` is the one place that
    # decides, off `itr_json.ITR_FORMS`; a Literal here would be a second copy
    # to keep in step.
    itr_form: str = Field(..., description="ITR-1 … ITR-7")
    computation_snapshot_id: Optional[str] = None
    notes: Optional[str] = None
    # WHICH KIND OF RETURN (IT-23, migration 381). Defaults to the original, so
    # every caller written before this keeps creating exactly what it created.
    # `return_type.validated_return_type` is the one place that decides; a
    # Literal here would be a second copy to keep in step, the same argument
    # `itr_form` above makes.
    return_type: str = Field("original", description="original | revised | updated")
    # The return this one supersedes, where it was prepared here. The receipt
    # is READ off it when the caller does not send one.
    original_filing_id: Optional[str] = None
    original_acknowledgement_number: Optional[str] = None
    original_filing_date: Optional[str] = None      # YYYY-MM-DD


class TransitionFilingRequest(BaseModel):
    new_status: str = Field(..., description="draft|review|partner_review|ready_for_filing|filed")
    notes: Optional[str] = None


class SaveVersionRequest(BaseModel):
    json_payload: dict


class AcknowledgementRequest(BaseModel):
    acknowledgement_number: str
    filing_date: str  # YYYY-MM-DD


class SnapshotRequest(BaseModel):
    client_id: str
    financial_year: FYLabel
    assessment_year: AYLabel
    regime: str = Field(..., description="new|old")
    income: dict = Field(default_factory=dict)
    computation_result: dict = Field(default_factory=dict)
    notes: Optional[str] = None


class DisallowanceRequest(BaseModel):
    client_id: str
    financial_year: FYLabel
    section: str = Field(..., description="40A(3)|43B_pf|43B_gst|43B_bonus|other")
    description: str
    amount_paise: int = Field(..., ge=0)
    evidence_document_id: Optional[str] = None
    journal_entry_id: Optional[str] = None
    notes: Optional[str] = None


#: The three states a recorded disallowance can be in. ONLY `accepted` reaches
#: the computation — the tax screen filters on it before sending the add-backs
#: — so a value outside this set is not a loud error, it is a disallowance
#: SILENTLY dropped from the return. `tax_disallowances.status` carries no
#: CHECK constraint (migration 156 records the three in a COMMENT), so the
#: database will store "Accepted" or "approve" quite happily and the filter
#: will then skip the row for ever.
DISALLOWANCE_STATUSES = ("pending", "accepted", "rejected")


class DisallowanceStatusRequest(BaseModel):
    status: str = Field(..., description="|".join(DISALLOWANCE_STATUSES))

    @field_validator("status")
    @classmethod
    def _known_status(cls, v: str) -> str:
        text = str(v or "").strip().lower()
        if text not in DISALLOWANCE_STATUSES:
            raise ValueError(
                f"Unknown status '{v}'. One of: "
                + ", ".join(DISALLOWANCE_STATUSES) + ".")
        return text


class DeductionClaimRequest(BaseModel):
    client_id: str
    financial_year: FYLabel
    section: str
    claimed_amount_paise: int = Field(..., ge=0)
    sub_head: Optional[str] = None
    evidence_document_id: Optional[str] = None
    notes: Optional[str] = None


class BFLossRequest(BaseModel):
    client_id: str
    assessment_year: AYLabel
    loss_type: str
    original_amount_paise: int = Field(..., ge=0)
    #: HOW LONG THE LOSS LIVES IS A STATUTORY FACT, AND IT WAS TYPED.
    #: §72(3) gives a business loss eight assessment years, §73(4) gives a
    #: SPECULATION loss four, §74(2) and §71B eight — so the one field in this
    #: row that the Act decides was whatever the caller sent. Optional now:
    #: `domain/income_tax/loss_carry_forward.expiry_for` derives it from the
    #: loss type and the year it was computed. A caller-supplied value still
    #: WINS where one is given — the shape domain/tds/deductor.resolve uses —
    #: because the derivation exists to spare the CA eight-year arithmetic,
    #: not to overrule them.
    expiry_assessment_year: OptionalAYLabel = None
    source_itr_ack: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("loss_type")
    @classmethod
    def _known_loss_type(cls, v: str) -> str:
        """Refuse a type the store does not hold, HERE rather than at the
        database. Without this the value reaches migration 319's CHECK, the
        insert raises, and create_bf_loss's `except Exception` turns it into a
        500 with the constraint name in it."""
        from domain.income_tax.loss_set_off import KNOWN_LOSS_TYPES
        text = str(v or "").strip().lower()
        if text not in KNOWN_LOSS_TYPES:
            raise ValueError(
                f"Unknown loss type '{v}'. One of: "
                + ", ".join(sorted(KNOWN_LOSS_TYPES)) + ".")
        return text


class UtilizeLossRequest(BaseModel):
    utilization_paise: int = Field(..., ge=0)


# ── Computation Snapshots ──────────────────────────────────────────────────────

@router.post("/snapshots")
def create_snapshot(
    req: SnapshotRequest,
    current_user: dict = Depends(rbac("income_tax", "compute")),
):
    """
    Save immutable versioned tax computation snapshot.
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    """
    assert_client_access(current_user, req.client_id)
    from domain.income_tax.computation_workspace import save_computation_snapshot
    try:
        snap = save_computation_snapshot(
            firm_id=current_user["firm_id"],
            client_id=req.client_id,
            financial_year=req.financial_year,
            assessment_year=req.assessment_year,
            regime=req.regime,
            income=req.income,
            computation_result=req.computation_result,
            created_by=current_user["id"],
            notes=req.notes,
        )
        timeline_service.log(
            client_id=req.client_id,
            category="tax",
            title="Tax computation snapshot generated",
            description=f"Tax computation snapshot v{snap.get('version',1)} created for FY {req.financial_year}",
            severity="info",
            firm_id=current_user["firm_id"],
            entity_type="tax_computation_snapshot", entity_id=snap.get("id"),
        )
        return api_response(True, snap)
    except Exception as e:
        _logger.exception("Failed to save snapshot")
        raise HTTPException(500, detail=str(e))


@router.get("/snapshots")
def list_snapshots(
    client_id: str,
    financial_year: FYLabel,
    current_user: dict = Depends(rbac("income_tax", "read")),
):
    # M2 audit finding: client_id was caller-supplied and never checked.
    assert_client_access(current_user, client_id)
    from domain.income_tax.computation_workspace import list_snapshots as _list
    return api_response(True, _list(current_user["firm_id"], client_id, financial_year))


@router.post("/snapshots/{snapshot_id}/review")
def review_snapshot(
    snapshot_id: str,
    current_user: dict = Depends(rbac("income_tax", "approve")),
):
    """
    Mark computation snapshot as CA-reviewed.
    # CA REVIEW REQUIRED
    """
    # M2 audit finding: row-addressed by snapshot_id, no client check at all.
    _assert_snapshot_scope(current_user, snapshot_id)
    from domain.income_tax.computation_workspace import review_snapshot as _review
    try:
        result = _review(current_user["firm_id"], snapshot_id, current_user["id"])
        timeline_service.log(
            client_id=result.get("client_id", ""),
            category="tax",
            title="Tax computation snapshot reviewed",
            description=f"Tax computation snapshot {snapshot_id} reviewed",
            severity="success",
            firm_id=current_user["firm_id"],
            entity_type="tax_computation_snapshot", entity_id=snapshot_id,
        )
        return api_response(True, result)
    except Exception as e:
        raise HTTPException(500, detail=str(e))


# ── ITR Filings ───────────────────────────────────────────────────────────────

@router.post("/filings")
def create_filing(
    req: CreateFilingRequest,
    current_user: dict = Depends(rbac("income_tax", "compute")),
):
    """Create ITR filing in draft state."""
    assert_client_access(current_user, req.client_id)
    from domain.income_tax.itr_workflow import create_itr_filing
    try:
        filing = create_itr_filing(
            firm_id=current_user["firm_id"],
            client_id=req.client_id,
            financial_year=req.financial_year,
            assessment_year=req.assessment_year,
            itr_form=req.itr_form,
            created_by=current_user["id"],
            computation_snapshot_id=req.computation_snapshot_id,
            notes=req.notes,
            return_type=req.return_type,
            original_filing_id=req.original_filing_id,
            original_acknowledgement_number=req.original_acknowledgement_number,
            original_filing_date=req.original_filing_date,
        )
        kind = filing.get("return_type") or "original"
        # s. 139(8A) bars a SECOND updated return for an assessment year. A
        # warning on the created row rather than a refusal — see
        # `already_furnished_updated_return` for why the bar is not a
        # constraint — and it travels in the response so the screen can show it.
        if kind == "updated":
            from domain.income_tax.itr_workflow import already_furnished_updated_return
            warning = already_furnished_updated_return(
                current_user["firm_id"], req.client_id, req.financial_year,
                exclude_filing_id=filing.get("id"))
            if warning:
                filing = {**filing, "statutory_warnings": [warning]}
        timeline_service.log(
            client_id=req.client_id,
            category="tax",
            title="ITR filing created",
            description=(f"{req.itr_form} {kind} filing created "
                         f"for FY {req.financial_year}"),
            severity="info",
            firm_id=current_user["firm_id"],
            entity_type="itr_filing", entity_id=filing.get("id"),
        )
        return api_response(True, filing)
    except ValueError as e:
        # `validated_form` refuses an unknown form with a sentence naming the
        # seven. A 500 would hide it behind "something went wrong".
        raise HTTPException(400, detail=str(e))
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@router.get("/forms")
def list_itr_forms(current_user: dict = Depends(rbac("income_tax", "read"))):
    """The ITR forms a filing may be created for, SERVED rather than copied.

    The filing screen held its own list of four while `itr_json` carried field
    mappings and a committed Department schema for seven (IT-23) — the same
    shape as the Schedule III captions the mapping screen used to hardcode.
    Each entry says whether a JSON schema is held, so a screen can show the CA
    what preparing that form will and will not produce.
    """
    from domain.income_tax.itr_schema import SCHEMA_FILES
    from domain.income_tax.itr_json import FIELD_MAPPINGS
    from domain.income_tax.itr_workflow import supported_forms
    return api_response(True, {
        "forms": [
            {
                "form": f,
                "schema_file": SCHEMA_FILES.get(f),
                "field_mapping_verified": bool(
                    getattr(FIELD_MAPPINGS.get(f), "verified", False)),
            }
            for f in supported_forms()
        ]
    })


@router.get("/return-kinds")
def list_return_kinds(
    assessment_year: Annotated[AYLabel, Query(...)],
    furnished_on: Optional[str] = Query(None, description="YYYY-MM-DD"),
    tax_paise: int = Query(0, ge=0),
    interest_paise: int = Query(0, ge=0),
    current_user: dict = Depends(rbac("income_tax", "read")),
):
    """The three kinds of return for an assessment year, with each window and
    its caveats — and, where a date and the figures are given, s. 140B's
    additional tax on an updated return.

    SERVED rather than derived in the browser, the same rule the ITR form list
    above follows: the windows are statute, and `domain/income_tax/return_type`
    is the one place that reads them. Two of the three are `[S]`-graded, so
    every entry carries the caveats and the s. 139(8A) one carries BOTH dates
    where the two readings disagree — a CA who files on the strength of the
    later date and is wrong has filed nothing.

    s. 140B is answered only when asked for: the charge is a percentage of the
    aggregate of TAX AND INTEREST, which this endpoint cannot compute and does
    not guess. Given no figures it reports the band that would apply and
    nothing more.
    """
    from datetime import date as _date

    from domain.income_tax import return_type as RT

    kinds = []
    for kind in RT.RETURN_TYPES:
        window = RT.window_for(kind, assessment_year)
        kinds.append({
            "return_type": kind,
            "section": RT.SECTION_FOR_TYPE[kind],
            "needs_the_earlier_receipt": kind in RT.NEEDS_THE_EARLIER_RECEIPT,
            "window": None if window is None else {
                "is_open": window.is_open,
                "closes_on": window.closes_on,
                "alternative_closes_on": window.alternative_closes_on,
                "caveats": list(window.caveats),
                "gaps": list(window.gaps),
            },
        })

    additional_tax = None
    if furnished_on:
        try:
            when = _date.fromisoformat(str(furnished_on)[:10])
        except ValueError:
            raise HTTPException(422, detail="furnished_on must be YYYY-MM-DD.")
        result = RT.additional_tax(assessment_year, when, tax_paise, interest_paise)
        additional_tax = {
            "furnished_on": result.furnished_on,
            "months_from_ay_end": result.months_from_ay_end,
            "percent": result.percent,
            "base_paise": result.base_paise,
            "additional_tax_paise": result.additional_tax_paise,
            "refusal": result.refusal,
            "caveats": list(result.caveats),
        }

    return api_response(True, {
        "assessment_year": assessment_year,
        "kinds": kinds,
        "additional_tax": additional_tax,
        # Named on every answer, not only where a band is missing: no year in
        # the s. 140B table has been confirmed against a Finance Act.
        "additional_tax_verified_through_ay": RT.LATEST_VERIFIED_AY,
    })


@router.get("/filings")
def list_filings(
    client_id: str,
    current_user: dict = Depends(rbac("income_tax", "read")),
):
    # M2 audit finding: client_id was caller-supplied and never checked.
    assert_client_access(current_user, client_id)
    from domain.income_tax.itr_workflow import list_itr_filings
    return api_response(True, list_itr_filings(current_user["firm_id"], client_id))


@router.get("/filings/{filing_id}/keying-sheet")
def filing_keying_sheet(
    filing_id: str,
    current_user: dict = Depends(rbac("income_tax", "read")),
):
    """Every computed figure and the box on the form it goes in (IT-17).

    `itr_field_placements` has said where each figure belongs since IT-17's
    first half, checked against the Department's own committed schemas — and no
    screen reached it, so a CA transcribing into the offline utility did it
    from memory. This is the door.

    IT IS BUILT OVER THE FILING'S PINNED SNAPSHOT, not over a request body.
    That is what makes it a keying sheet rather than a calculator: what the CA
    keys is the computation that was reviewed, and the form on the sheet is the
    form the filing is for. A filing pinning no snapshot is REFUSED with the
    sentence naming what to do, because a sheet of zeros reads as a computed
    return.

    Reads and writes nothing. It does NOT produce a file — see
    domain/income_tax/itr_json.generate_itr_json, which refuses for two named
    reasons and is deliberately not reachable from here.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to Income Tax Portal
    """
    from domain.income_tax.keying_sheet import NO_SNAPSHOT_PINNED, keying_sheet
    from services import self_assessment_service

    filing = _assert_filing_scope(current_user, filing_id)
    snapshot_id = filing.get("computation_snapshot_id")
    if not snapshot_id:
        return api_response(False, None, NO_SNAPSHOT_PINNED)
    # Scoped like every other snapshot read here — a filing_id the caller may
    # see does not by itself authorise the snapshot it names.
    snapshot = _assert_snapshot_scope(current_user, str(snapshot_id))
    # §140A (IT-13). Read off the FILING's own client and financial year, never
    # the snapshot's: the filing is what is being furnished, and a challan is
    # proof of payment for that return. The total is computed in the service —
    # `keying_sheet` derives nothing and a test walks its AST to keep it so.
    challans = self_assessment_service.list_challans(
        _challan_db(), firm_id=current_user["firm_id"],
        client_id=str(filing.get("client_id") or ""),
        financial_year=str(filing.get("financial_year") or ""))
    sheet = keying_sheet(
        form=str(filing.get("itr_form") or ""),
        # The filing's own AY, never the snapshot's: the filing is what is
        # being furnished, and a snapshot computed for one year and pinned to
        # another is a mistake this sheet must show rather than smooth over.
        assessment_year=str(filing.get("assessment_year") or ""),
        computation=snapshot.get("computation_json"),
        snapshot=snapshot,
        self_assessment_tax_paise=self_assessment_service.total_paise_of(challans),
        self_assessment_challan_count=len(challans),
    )
    snapshot_ay = str(snapshot.get("assessment_year") or "")
    if snapshot_ay and snapshot_ay != sheet["assessment_year"]:
        sheet["gaps"].insert(0, (
            f"The pinned snapshot was computed for AY {snapshot_ay} and this "
            f"filing is for AY {sheet['assessment_year']}. The figures below "
            f"are the snapshot's."))
    sheet["filing_id"] = filing_id
    sheet["return_type"] = filing.get("return_type")
    sheet["status"] = filing.get("status")
    sheet["snapshot_id"] = snapshot_id
    # Whether the computation on this sheet was REVIEWED (IT-30). A draft
    # snapshot is still keyable — a CA may be checking the figures against the
    # utility as part of the review — so this is reported, not refused.
    sheet["snapshot_status"] = snapshot.get("status")
    return api_response(True, sheet)


@router.post("/filings/{filing_id}/transition")
def transition_filing(
    filing_id: str,
    req: TransitionFilingRequest,
    current_user: dict = Depends(rbac("income_tax", "approve")),
):
    """
    Advance ITR filing through workflow.
    # CA REVIEW REQUIRED — Partner review required before ready_for_filing.
    """
    # M2 audit finding: row-addressed by filing_id, no client check at all.
    _assert_filing_scope(current_user, filing_id)
    from domain.income_tax.itr_workflow import transition_itr_status
    try:
        result = transition_itr_status(
            firm_id=current_user["firm_id"],
            filing_id=filing_id,
            new_status=req.new_status,
            actor_id=current_user["id"],
            notes=req.notes,
        )
        event_map = {
            "ready_for_filing": ("ITR ready for filing", "warning"),
            "filed": ("ITR filed", "success"),
        }
        if req.new_status in event_map:
            title, sev = event_map[req.new_status]
            timeline_service.log(
                client_id=result.get("client_id", ""),
                category="tax",
                title=title,
                description=f"Filing {filing_id} status changed to {req.new_status}",
                severity=sev,
                firm_id=current_user["firm_id"],
                entity_type="itr_filing", entity_id=filing_id,
            )
        return api_response(True, result)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@router.post("/filings/{filing_id}/versions")
def save_version(
    filing_id: str,
    req: SaveVersionRequest,
    current_user: dict = Depends(rbac("income_tax", "compute")),
):
    # M2 audit finding: row-addressed by filing_id, no client check at all.
    _assert_filing_scope(current_user, filing_id)
    from domain.income_tax.itr_workflow import save_itr_version
    try:
        ver = save_itr_version(
            firm_id=current_user["firm_id"],
            filing_id=filing_id,
            json_payload=req.json_payload,
            created_by=current_user["id"],
        )
        return api_response(True, ver)
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@router.post("/filings/{filing_id}/acknowledge")
def record_acknowledgement(
    filing_id: str,
    req: AcknowledgementRequest,
    current_user: dict = Depends(rbac("income_tax", "approve")),
):
    """
    Record ITR acknowledgement after CA files on Income Tax Portal.
    # CA REVIEW REQUIRED — CA must manually file on portal before calling this
    """
    # M2 audit finding: row-addressed by filing_id, no client check at all.
    _assert_filing_scope(current_user, filing_id)
    from domain.income_tax.itr_workflow import record_filing_acknowledgement
    try:
        result = record_filing_acknowledgement(
            firm_id=current_user["firm_id"],
            filing_id=filing_id,
            acknowledgement_number=req.acknowledgement_number,
            filing_date=req.filing_date,
            actor_id=current_user["id"],
        )
        timeline_service.log(
            client_id=result.get("client_id", ""),
            category="tax",
            title="ITR filed",
            description=f"ITR filed — Ack: {req.acknowledgement_number}",
            severity="success",
            firm_id=current_user["firm_id"],
            entity_type="itr_filing", entity_id=filing_id,
        )
        return api_response(True, result)
    except ValueError as e:
        # The state-machine refusal (IT-23): a draft cannot be marked filed,
        # and an already-filed return cannot be silently re-acknowledged. Both
        # are the CA's to see, not a 500.
        raise HTTPException(400, detail=str(e))
    except Exception as e:
        raise HTTPException(500, detail=str(e))


# ── Disallowances ─────────────────────────────────────────────────────────────

@router.post("/disallowances")
def create_disallowance(
    req: DisallowanceRequest,
    current_user: dict = Depends(rbac("income_tax", "compute")),
):
    """
    Record tax disallowance (IT Act 40A(3), 43B etc.) with evidence.
    All amounts in paise — never float.
    """
    assert_client_access(current_user, req.client_id)
    from domain.income_tax.computation_workspace import create_disallowance as _create
    try:
        result = _create(
            firm_id=current_user["firm_id"],
            client_id=req.client_id,
            financial_year=req.financial_year,
            section=req.section,
            description=req.description,
            amount_paise=req.amount_paise,
            created_by=current_user["id"],
            evidence_document_id=req.evidence_document_id,
            journal_entry_id=req.journal_entry_id,
            notes=req.notes,
        )
        return api_response(True, result)
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@router.get("/disallowances")
def list_disallowances(
    client_id: str,
    financial_year: FYLabel,
    current_user: dict = Depends(rbac("income_tax", "read")),
):
    # M2 audit finding: client_id was caller-supplied and never checked.
    assert_client_access(current_user, client_id)
    from domain.income_tax.computation_workspace import list_disallowances as _list
    return api_response(True, _list(current_user["firm_id"], client_id, financial_year))


@router.patch("/disallowances/{disallowance_id}/status")
def update_disallowance_status(
    disallowance_id: str,
    req: DisallowanceStatusRequest,
    current_user: dict = Depends(rbac("income_tax", "approve")),
):
    # M2 audit finding: row-addressed by disallowance_id, no client check at all.
    _assert_disallowance_scope(current_user, disallowance_id)
    from domain.income_tax.computation_workspace import update_disallowance_status as _update
    result = _update(current_user["firm_id"], disallowance_id, req.status)
    return api_response(True, result)


@router.post("/disallowances/auto-detect-40a3")
def auto_detect_40a3(
    client_id: str,
    financial_year: FYLabel,
    current_user: dict = Depends(rbac("income_tax", "compute")),
):
    """
    Auto-detect Section 40A(3) cash payments >₹10,000 from ledger.
    IT Act Section 40A(3) — Disallowance of cash payments exceeding ₹10,000.
    """
    assert_client_access(current_user, client_id)
    from domain.income_tax.computation_workspace import auto_detect_40a3 as _detect
    detected = _detect(current_user["firm_id"], client_id, financial_year, current_user["id"])
    return api_response(True, {"detected": len(detected), "items": detected})


# ── Deduction Claims ──────────────────────────────────────────────────────────

@router.post("/deductions")
def create_deduction(
    req: DeductionClaimRequest,
    current_user: dict = Depends(rbac("income_tax", "compute")),
):
    assert_client_access(current_user, req.client_id)
    from domain.income_tax.computation_workspace import create_deduction_claim
    try:
        result = create_deduction_claim(
            firm_id=current_user["firm_id"],
            client_id=req.client_id,
            financial_year=req.financial_year,
            section=req.section,
            claimed_amount_paise=req.claimed_amount_paise,
            created_by=current_user["id"],
            sub_head=req.sub_head,
            evidence_document_id=req.evidence_document_id,
            notes=req.notes,
        )
        return api_response(True, result)
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@router.get("/deductions")
def list_deductions(
    client_id: str,
    financial_year: FYLabel,
    current_user: dict = Depends(rbac("income_tax", "read")),
):
    # M2 audit finding: client_id was caller-supplied and never checked.
    assert_client_access(current_user, client_id)
    from domain.income_tax.computation_workspace import list_deduction_claims
    return api_response(True, list_deduction_claims(current_user["firm_id"], client_id, financial_year))


# ── Brought Forward Losses ────────────────────────────────────────────────────

@router.post("/bf-losses")
def create_bf_loss(
    req: BFLossRequest,
    current_user: dict = Depends(rbac("income_tax", "compute")),
):
    """
    Record brought-forward loss.
    IT Act Section 72 (business loss, 8 years), Section 74 (capital loss, 8 years).
    """
    assert_client_access(current_user, req.client_id)
    from domain.income_tax import loss_carry_forward
    from domain.income_tax.computation_workspace import create_bf_loss as _create

    # THE EXPIRY IS DERIVED WHERE THE CALLER DID NOT STATE ONE, and refused
    # rather than guessed where no section fixes a period — `other`, whose head
    # is not identified. Defaulting that to eight years would silently end a
    # loss the Act may not end, and there is no direction that fails safe here:
    # a period too short expires relief the client is entitled to, one too long
    # claims relief they are not.
    expiry = req.expiry_assessment_year
    derivation = None
    if not expiry:
        expiry, derivation = loss_carry_forward.expiry_for(
            req.loss_type, req.assessment_year)
        if not expiry:
            raise HTTPException(status_code=422, detail=derivation)
    try:
        result = _create(
            firm_id=current_user["firm_id"],
            client_id=req.client_id,
            assessment_year=req.assessment_year,
            loss_type=req.loss_type,
            original_amount_paise=req.original_amount_paise,
            expiry_assessment_year=expiry,
            created_by=current_user["id"],
            source_itr_ack=req.source_itr_ack,
            notes=req.notes,
        )
        # The working travels with the row so the screen can SAY which section
        # fixed the date rather than showing a year with no provenance.
        if derivation and isinstance(result, dict):
            result = {**result, "expiry_derivation": derivation}
        return api_response(True, result)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@router.get("/loss-types")
def loss_types(
    current_user: dict = Depends(rbac("income_tax", "read")),
):
    """The loss types a brought-forward loss may carry, each with the section
    that fixes its carry-forward period and how long that is.

    Served so the FORM holds no vocabulary and no period. §73(4)'s four years
    against everything else's eight is exactly the kind of difference a
    hardcoded dropdown gets wrong, and `loss_carry_forward` is the one place
    that knows it. `not_modelled` is part of the answer: §32(2) unabsorbed
    depreciation and §73A both carry forward indefinitely and have no row here,
    so the screen says why instead of inviting one under `other`.
    """
    from domain.income_tax import loss_carry_forward as lcf
    return api_response(True, {
        "types": [
            {"loss_type": r.loss_type, "section": r.section,
             "years": r.years, "note": r.note}
            for r in lcf.known_types()
        ],
        "not_modelled": [{"what": k, "why": v} for k, v in lcf.NOT_MODELLED.items()],
        "verified": lcf.VERIFIED,
    })


@router.get("/bf-losses")
def list_bf_losses(
    client_id: str,
    current_user: dict = Depends(rbac("income_tax", "read")),
):
    # M2 audit finding: client_id was caller-supplied and never checked.
    assert_client_access(current_user, client_id)
    from domain.income_tax.computation_workspace import list_bf_losses as _list
    return api_response(True, _list(current_user["firm_id"], client_id))


@router.post("/bf-losses/{loss_id}/utilize")
def utilize_loss(
    loss_id: str,
    req: UtilizeLossRequest,
    current_user: dict = Depends(rbac("income_tax", "compute")),
):
    # M2 audit finding: row-addressed by loss_id, no client check at all.
    _assert_bf_loss_scope(current_user, loss_id)
    from domain.income_tax.computation_workspace import utilize_bf_loss
    try:
        result = utilize_bf_loss(current_user["firm_id"], loss_id, req.utilization_paise)
        return api_response(True, result)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
