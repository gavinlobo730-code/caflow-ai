"""
TDS API — 24Q/26Q return computation and filing preparation.

IT Act Section 192 (salary TDS), Section 194 (non-salary TDS).
All monetary amounts in integer paise.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to TRACES or any government portal.
"""
from domain.tds import vocabulary as tds_vocabulary
from fastapi import APIRouter, HTTPException, Query, status, Depends
from pydantic import BaseModel, Field
from typing import Optional
from core.permissions import rbac
from core.authz import assert_client_access
from domain.tds import TDSComputer
from domain.tds import deductor as tds_deductor
from core.observability import capture_soft_failure
from domain.tds.section_rates import tds_rates_for
from domain.tds.tds_computer import is_company_pan, has_pan as pan_on_file
from repositories.tds_repository import tds_repo
from models.fy import FYLabel, OptionalFYLabel

router = APIRouter(prefix="/api/tds", tags=["tds"])
computer = TDSComputer()


# ── Client-assignment scope (M2) ──────────────────────────────────────────────
# This router imported no authz at all. `/returns/{client_id}` and
# `/deductions/{client_id}` name a client in the PATH and returned that client's
# filed returns and every TDS deduction on their books to any member of the
# firm; the two `/from-books` endpoints read a client's posted purchase bills or
# finalized payroll runs out of the ledger.
#
# The two `/compute` endpoints are guarded too even though they are, today, pure
# functions over caller-supplied rows that never read `req.client_id`. An
# exemption would be true right now and silently false the first time somebody
# uses the field the request model already requires — and the sweep's honesty
# tests check that an exempted ROUTE still exists, not that its REASON still
# holds. One line is cheaper than that trap.
#
# `/compute-amount` and `/sections` are exempt and stay that way: neither has a
# client_id to check. `/sections` returns the statutory rate table itself.


# ── Request / Response Models ─────────────────────────────────────────────────

# Compute26QRequest / Compute24QRequest AND THEIR TWO ENDPOINTS ARE GONE.
#
# `POST /26q/compute` and `POST /24q/compute` took a whole deductee list, a
# challan list AND a deductor block from the caller, ran the engine over them
# and handed back a statement. That is the API-level shape of the defect this
# tranche closes at the screen: the only caller was
# `apps/web/app/tds/returns/page.tsx`, which read `tds_deductions` and
# `tds_challans` over PostgREST, mapped them into rows here, stamped every
# row's `tds_deposited_paise` with the amount DEDUCTED (so the engine's own
# shortfall check could not fire — TDS-29), and invented a TAN because it had
# nowhere to read one from.
#
# Every legitimate build now comes from the posted books, where the deductees
# are derived, the deposited column is filled from the challans that actually
# exist (`domain/tds/challan_mapping.py`), and the deductor is read and refused
# by name (`domain/tds/deductor.py`). An endpoint that trusts caller-supplied
# deductee rows is the hole still open behind that, so it goes with the screen
# rather than being left uncalled — the codebase's own rule, stated in
# `apps/web/scripts/tds-is-computed-by-the-engine-not-the-browser.test.ts`:
# delete the helper, do not just stop calling it.
#
# `TDSComputer.compute_26q` / `.compute_24q` — the DOMAIN methods — stay and
# are unchanged. They are what the from-books services call.


class FromBooksRequest(BaseModel):
    """A quarter to build, and optionally who to build it for.

    THE DEDUCTOR BLOCK IS NO LONGER REQUIRED, AND THAT CLOSES A HOLE.
        These four were mandatory because there was nowhere to read them
        from — which is what migration 325's own header says it was created
        to end. Nothing then read it, so `apps/web/app/tds/returns/page.tsx`
        went on inventing them: `const tan = "MUMB00000A"`, `deductor_pan:
        "AAAAA0000A"`, `deductor_address: "Address not configured"`. Both
        literals are the right SHAPE, so every validator passed and the
        return saved clean under a TAN belonging to nobody.

        Omitted now means "read it from the books" — `client_statutory_
        identity.tan`, the client's own PAN, legal name and postal address —
        and a value that is neither supplied nor recorded is REFUSED by name
        (`domain/tds/deductor.py`), never defaulted. A caller that supplies
        the block still wins, because the per-client compute form has always
        offered it and a client whose registrations are not yet recorded has
        no other way to compute a quarter.
    """
    client_id: str
    financial_year: FYLabel = Field(..., description="e.g. 2025-26")
    quarter: str = Field(..., description="Q1, Q2, Q3, Q4")
    tan: Optional[str] = None
    deductor_name: Optional[str] = None
    deductor_pan: Optional[str] = None
    deductor_address: Optional[str] = None


class TDSAmountRequest(BaseModel):
    section: str
    payment_amount_paise: int = Field(gt=0)
    is_company: bool = False
    # Financial year to resolve thresholds/rates for (e.g. "2025-26");
    # omit for the current FY. See domain/tds/section_rates.py.
    fy: OptionalFYLabel = None
    # IT Act §206AA — set False to model a payee with no PAN on file (rate
    # floors at the registry's section_206aa_floor_rate_bps). Defaults to
    # True (has a PAN) so existing callers' behaviour is unchanged.
    has_pan: bool = True
    # Optional: when supplied, is_company/has_pan above are IGNORED and
    # instead derived from the PAN itself via is_company_pan()/has_pan() —
    # the same authoritative derivation the real purchase-bill TDS deduction
    # already uses (routers/purchase_bills.py), so a caller with a payee's
    # PAN on file never has to duplicate that rule itself.
    pan: Optional[str] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

def _deductor_sources(db, firm_id: str, client_id: str) -> tuple[dict, dict]:
    """The two rows `tds_deductor.resolve` reads: the client's statutory
    identity (migration 325, created for exactly this) and the client itself.

    A FAILED read produces gaps rather than an exception — the caller then sees
    "no TAN recorded", which is the safe direction. It is never treated as
    "the identifiers are fine".
    """
    identity: dict = {}
    client: dict = {}
    if db is None:
        return identity, client
    try:
        identity = (db.table("client_statutory_identity")
                    .select("tan")
                    .eq("firm_id", firm_id).eq("client_id", client_id)
                    .maybe_single().execute().data) or {}
    except Exception as exc:                                       # noqa: BLE001
        capture_soft_failure(exc, operation="tds_deductor_identity_read",
                             client_id=client_id)
    try:
        client = (db.table("clients")
                  .select("client_name, legal_name, pan, address_line1, "
                          "address_line2, city, state, pincode")
                  .eq("firm_id", firm_id).eq("id", client_id)
                  .maybe_single().execute().data) or {}
    except Exception as exc:                                       # noqa: BLE001
        capture_soft_failure(exc, operation="tds_deductor_client_read",
                             client_id=client_id)
    return identity, client


@router.get("/deductor")
def deductor_block(client_id: str = Query(...),
                   user: dict = Depends(rbac("tds", "read"))):
    """Who a TDS statement for this client would be filed under (TDS-28).

    The server has read this from `client_statutory_identity` and `clients`
    since the deductor block stopped being invented — but nothing SERVED it,
    so the compliance screen initialised four blank boxes and made the CA type
    the TAN, the legal name and the PAN every quarter, for every client. A
    figure the system holds and asks for anyway is a figure that will
    eventually be typed differently.

    Returns the resolved block where it is complete, and the NAMED GAPS where
    it is not — `resolved: false` with a sentence per missing identifier,
    which is the same answer the compute path refuses with. The screen can
    then say what to go and record rather than letting the CA discover it at
    the moment they press Compute.
    """
    assert_client_access(user, client_id)
    db = get_supabase()
    identity, client = _deductor_sources(db, user["firm_id"], client_id)
    block, codes = tds_deductor.resolve(identity, client)
    if block is None:
        return api_response(True, {
            "resolved": False, "tan": "", "deductor_name": "",
            "deductor_pan": "", "deductor_address": "",
            "statutory_gaps": tds_deductor.gaps_with_messages(codes),
        })
    return api_response(True, {
        "resolved": True,
        "tan": block.tan,
        "deductor_name": block.name,
        "deductor_pan": block.pan,
        "deductor_address": block.address,
        "statutory_gaps": [],
    })


def _deductor_for(db, firm_id: str, req: "FromBooksRequest") -> tds_deductor.Deductor:
    """Who this statement is filed under — from the request, else from the books.

    REFUSES rather than substituting. A TDS statement carries the deductor's
    TAN, name, PAN and address; a blank or invented one files the quarter
    against no account, and the deductees get no credit for tax that was
    actually withheld from them. `domain/tds/deductor.py` holds the rule and
    the CA-facing sentences.

    The read is best-effort in the sense that a FAILED read produces gaps
    rather than an exception — the caller then sees "no TAN recorded", which
    is the safe direction. It is never treated as "the identifiers are fine".
    """
    identity, client = _deductor_sources(db, firm_id, req.client_id)
    block, codes = tds_deductor.resolve(
        identity, client,
        tan=req.tan, name=req.deductor_name,
        pan=req.deductor_pan, address=req.deductor_address,
    )
    if block is None:
        raise HTTPException(status_code=422,
                            detail=tds_deductor.refusal_detail(codes))
    return block


@router.post("/26q/from-books")
def compute_26q_from_books(req: FromBooksRequest, user: dict = Depends(rbac("tds", "compute"))):
    """
    Build Form 26Q (non-salary TDS) ENTIRELY from posted purchase bills and
    reconcile the total to the GL "TDS Payable" control account.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to TRACES or any government portal.
    """
    from core.supabase_client import get_supabase
    from services.tds_return_service import tds_26q_from_books
    assert_client_access(user, req.client_id)
    db = get_supabase()
    firm_id = user["firm_id"]
    who = _deductor_for(db, firm_id, req)
    try:
        data = tds_26q_from_books(
            db, firm_id, req.client_id, req.financial_year, req.quarter,
            who.tan, who.name, who.pan, who.address,
        )
    except ValueError as ve:
        raise HTTPException(status_code=422, detail=str(ve))
    return {"success": True, "data": data, "error": None}


@router.post("/27q/from-books")
def compute_27q_from_books(req: FromBooksRequest, user: dict = Depends(rbac("tds", "compute"))):
    """
    Build Form 27Q (payments to NON-RESIDENTS, Rule 31A(4)(b)) ENTIRELY from
    posted purchase bills and vendor advances, and reconcile the total to the
    GL "TDS Payable" control account — the same account 26Q reconciles to,
    because §195 credits one liability and one challan series (ITNS 281).

    26Q excludes these by name and always has (`excluded_non_resident`); until
    now nothing built the statement they belong on, so a CA rebuilt it by hand
    from the deduction list (TDS-09).

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to TRACES or any government portal.
    """
    from core.supabase_client import get_supabase
    from services.tds_return_service import tds_27q_from_books
    assert_client_access(user, req.client_id)
    db = get_supabase()
    firm_id = user["firm_id"]
    who = _deductor_for(db, firm_id, req)
    try:
        data = tds_27q_from_books(
            db, firm_id, req.client_id, req.financial_year, req.quarter,
            who.tan, who.name, who.pan, who.address,
        )
    except ValueError as ve:
        raise HTTPException(status_code=422, detail=str(ve))
    return {"success": True, "data": data, "error": None}


@router.post("/24q/from-books")
def compute_24q_from_books(req: FromBooksRequest, user: dict = Depends(rbac("tds", "compute"))):
    """
    Build Form 24Q (salary TDS) ENTIRELY from finalized payroll runs and
    reconcile the total to the GL "TDS Payable - Salary" control account.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to TRACES or any government portal.
    """
    from core.supabase_client import get_supabase
    from services.tds_return_service import tds_24q_from_books
    assert_client_access(user, req.client_id)
    db = get_supabase()
    firm_id = user["firm_id"]
    who = _deductor_for(db, firm_id, req)
    try:
        data = tds_24q_from_books(
            db, firm_id, req.client_id, req.financial_year, req.quarter,
            who.tan, who.name, who.pan, who.address,
        )
    except ValueError as ve:
        raise HTTPException(status_code=422, detail=str(ve))
    return {"success": True, "data": data, "error": None}


@router.post("/compute-amount")
def compute_tds_amount(req: TDSAmountRequest, user: dict = Depends(rbac("tds", "compute"))):
    """
    Calculate TDS for a single payment given section and amount.
    Returns applicable rate and TDS amount in paise, resolved for the
    requested FY (defaults to the current FY).
    IT Act Chapter XVII-B.
    """
    is_company = is_company_pan(req.pan) if req.pan is not None else req.is_company
    has_pan_on_file = pan_on_file(req.pan) if req.pan is not None else req.has_pan
    try:
        resolution = computer.resolve_tds(
            req.section, req.payment_amount_paise, is_company=is_company, fy=req.fy,
            has_pan=has_pan_on_file)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown TDS section: {req.section}")

    rates = tds_rates_for(req.fy)
    rule = rates.sections[resolution.section]
    return {
        "success": True,
        "data": {
            "section": resolution.section,
            "fy": rates.fy,
            "rates_verified": rates.verified,
            "payment_amount_paise": req.payment_amount_paise,
            "threshold_paise": rule.single_threshold_paise,
            "aggregate_threshold_paise": rule.aggregate_threshold_paise,
            "tds_applicable": resolution.applies,
            "applicable_rate_pct": resolution.rate_pct,
            "tds_paise": resolution.tds_paise,
        },
        "error": None,
    }


@router.get("/sections")
def list_tds_sections(fy: OptionalFYLabel = None, user: dict = Depends(rbac("tds", "read"))):
    """List all TDS sections with thresholds and rates for the given FY
    (defaults to the current FY)."""
    from domain.tds.lower_deduction import SECTIONS_197
    from domain.tds.residency import deduction_section_refusal
    rates = tds_rates_for(fy)
    sections = [
        {
            "section": sec,
            "threshold_paise": rule.single_threshold_paise,
            "aggregate_threshold_paise": rule.aggregate_threshold_paise,
            "rate_individual_pct": rule.individual_rate_bps / 100,
            "rate_company_pct": rule.company_rate_bps / 100,
            # IT Act §197(1) names the provisions a lower-deduction certificate
            # can be issued under. A screen offering one against a section the
            # RATE ENGINE cannot answer for would let a CA record a certificate
            # that can never be applied to a bill — the same failure
            # tests/test_a_section_the_engine_cannot_answer_for_is_refused.py
            # names for the vendor master. Both facts are decided here, where
            # the registry and the statute both live.
            "section_197_eligible": sec in SECTIONS_197,
            # AND WHETHER A VENDOR MAY CARRY IT AT ALL.
            #
            # This list is the supplier screen's section dropdown, served
            # straight from the registry — so it offered §192 and §206C, both
            # of which `residency.deduction_section_refusal` rejects at the
            # save. A dropdown whose options the save refuses is a dead
            # control, and §206C's was worse than dead: nothing refused it
            # until now, so picking it withheld 0.1% of every rupee (its
            # threshold is zero) and stamped the row 26Q, which is not where
            # TCS is reported.
            #
            # Decided HERE, from the one function that decides it, rather than
            # by the screen keeping its own exclusion list — which is how the
            # Schedule III caption list drifted in both directions at once.
            "vendor_eligible": deduction_section_refusal(sec) is None,
        }
        for sec, rule in rates.sections.items()
    ]
    return {
        "success": True,
        "data": {
            "fy": rates.fy, "rates_verified": rates.verified, "sections": sections,
            # WHAT §197 REACHES AND THIS ENGINE CANNOT PRICE, named rather than
            # silently absent from the list above. §195 is here for a second
            # reason as well as the first: even where a certificate is recorded
            # against it, resolve_withholding deliberately does not apply one —
            # the §195 figure is a §115A / Part II / DTAA comparison the statute
            # already defines, and a certified rate on top of it is a fourth
            # rate in that comparison.
            "section_197_not_priced": sorted(SECTIONS_197 - set(rates.sections)),
        },
        "error": None,
    }


@router.get("/rate-coverage")
def tds_rate_coverage(user: dict = Depends(rbac("tds", "read"))):
    """Which financial years the rate registries hold, and whether each was
    CONFIRMED against that year's Finance Act.

    Exists because the alternative is reading a docstring in a Python module,
    and the trap CLAUDE.md names is that a missing year is NOT an error — every
    registry here falls back to the last held year and returns it confidently.
    A firm withholding in a year marked unverified should be able to see that
    without asking an engineer.

    Section 195's registry is currently unverified for EVERY year: those
    figures were reconciled, not checked line by line against Part II of the
    First Schedule. Confirming a year is a pure data change.
    """
    from domain.tds.section_195_rates import coverage as s195_coverage
    from domain.tds.section_rates import TDS_RATES_BY_FY, LATEST_VERIFIED_TDS_FY
    resident = [
        {"fy": fy, "verified": getattr(TDS_RATES_BY_FY[fy], "verified", False)}
        for fy in sorted(TDS_RATES_BY_FY)
    ]
    s195 = s195_coverage()
    return {
        "success": True,
        "data": {
            "resident_sections": {
                "years": resident,
                "latest_verified_fy": LATEST_VERIFIED_TDS_FY,
            },
            "section_195": {
                "years": s195,
                "any_verified": any(y["verified"] for y in s195),
                "note": "Reconciled against s.115A and Part II of the First "
                        "Schedule, NOT confirmed line by line. Confirm the year "
                        "you are withholding in before relying on it.",
            },
        },
        "error": None,
    }


@router.get("/returns/{client_id}")
def get_tds_returns(client_id: str, user: dict = Depends(rbac("tds", "read"))):
    """Fetch all TDS returns for a client."""
    assert_client_access(user, client_id)
    firm_id = user["firm_id"]
    data = tds_repo.get_returns(client_id=client_id, firm_id=firm_id)
    return {"success": True, "data": data, "error": None}


@router.get("/deductions/{client_id}")
def get_tds_deductions(
    client_id: str,
    financial_year: OptionalFYLabel = None,
    quarter: Optional[str] = None,
    return_type: Optional[str] = Query(
        None, description="Filter to one quarterly statement — '26Q' (payments "
                          "to residents) or '27Q' (payments to non-residents), "
                          "which Rule 31A(4) keeps apart. Omit for both."),
    user: dict = Depends(rbac("tds", "read")),
):
    """Fetch TDS deductions for a client, optionally filtered by FY/quarter.

    The register holds 26Q and 27Q rows together, because they come from the
    same purchase bills and the same deduction event. They are FILED apart, so
    a caller assembling either one has to say which — Rule 31A(4)(a) and (b).
    """
    # An omitted parameter reaches a DIRECT call as FastAPI's Query default
    # object, not None — truthy, and not a valid return_type, so the validation
    # below would 422 every caller that never asked for a filter. Normalised the
    # same way routers/gst_workspace.py's return_type filter already is; its
    # comment records the same trap.
    if not isinstance(return_type, str):
        return_type = None
    assert_client_access(user, client_id)
    firm_id = user["firm_id"]
    if return_type is not None and return_type not in ("24Q", "26Q", "27Q", "27EQ"):
        raise HTTPException(
            status_code=422,
            detail="return_type must be one of 24Q, 26Q, 27Q or 27EQ "
                   "(migration 014's CHECK on tds_deductions.return_type).")
    data = tds_repo.get_deductions(
        client_id=client_id,
        firm_id=firm_id,
        financial_year=financial_year,
        quarter=quarter,
        return_type=return_type,
    )
    return {"success": True, "data": data, "error": None}


# ── The firm's DTAA readings (migration 310) ─────────────────────────────────
# Firm-scoped, not client-scoped: a treaty rate is the firm's reading of an
# agreement, and every client paying into that country withholds on it.

class TreatyRateIn(BaseModel):
    country_code: str = Field(..., description="ISO 3166-1 alpha-2, e.g. AE")
    nature: str = Field(..., description="One of domain/tds/section_195_rates.ALL_NATURES")
    rate_bps: Optional[int] = Field(
        None, description="Rate in basis points; 10% is 1000. Omit when the "
                          "agreement has no article for this nature.")
    no_article: bool = Field(
        False, description="The agreement has no article for this nature at all "
                           "— several, including the UAE and Singapore, have no "
                           "fees-for-technical-services article. That makes the "
                           "income Article 7 business profits, not taxable in "
                           "India without a permanent establishment.")
    article_ref: Optional[str] = None
    notes: Optional[str] = None


@router.get("/treaty-rates")
def list_treaty_rates(user: dict = Depends(rbac("tds", "read"))):
    """Every DTAA position this firm has recorded.

    Ships EMPTY on a new firm and is never seeded — India has agreements with
    over ninety countries, their articles differ, MFN clauses need their own
    s.90(1) notification (AO v. Nestle SA, 2023), and a wrong rate too low
    disallows the whole expenditure under s.40(a)(i).
    """
    from core.supabase_client import get_supabase
    from domain.tds.section_195_rates import ALL_NATURES
    try:
        db = get_supabase()
        rows = (db.table("dtaa_treaty_rates")
                .select("id, country_code, nature, rate_bps, no_article, "
                        "article_ref, notes, verified_on")
                .eq("firm_id", user["firm_id"])
                .order("country_code").order("nature").execute().data) or []
    except Exception:                                           # noqa: BLE001
        rows = []
    return {"success": True,
            "data": {"rates": rows, "natures": list(ALL_NATURES)},
            "error": None}


@router.put("/treaty-rates")
def upsert_treaty_rate(body: TreatyRateIn,
                       user: dict = Depends(rbac("tds", "write"))):
    """Record or replace this firm's reading for one (country, nature).

    A row must say ONE thing: a rate, or that the agreement has no article for
    this nature. Neither is a half-finished thought the engine would have to
    guess at, and both is a contradiction.
    """
    from core.supabase_client import get_supabase
    from core.exceptions import document_failure_detail
    from domain.tds.section_195_rates import ALL_NATURES

    country = (body.country_code or "").strip().upper()
    nature = (body.nature or "").strip().lower()
    if not (len(country) == 2 and country.isalpha()):
        raise HTTPException(
            status_code=422,
            detail="country_code must be a 2-letter ISO 3166-1 alpha-2 code, "
                   f"e.g. AE, SG or CH (got '{body.country_code}').")
    if nature not in ALL_NATURES:
        raise HTTPException(
            status_code=422,
            detail="nature must be one of: " + ", ".join(ALL_NATURES))
    if body.no_article and body.rate_bps is not None:
        raise HTTPException(
            status_code=422,
            detail="A row says one thing or the other: either the agreement "
                   "has no article for this nature, or it has a rate.")
    if not body.no_article:
        if body.rate_bps is None:
            raise HTTPException(
                status_code=422,
                detail="Record the rate you read off the agreement, or tick "
                       "'no article' if it has none for this nature. A row with "
                       "neither cannot be withheld on.")
        if not (0 <= body.rate_bps <= 10000):
            raise HTTPException(
                status_code=422,
                detail="rate_bps is a rate in basis points, 0 to 10000 "
                       f"(10% is 1000). Got {body.rate_bps}.")
    try:
        db = get_supabase()
        # Payload inline with literal keys so tests/test_backend_columns_
        # exist_pg.py can check every column against the real schema.
        got = (db.table("dtaa_treaty_rates").upsert({
            "firm_id": user["firm_id"],
            "country_code": country,
            "nature": nature,
            "rate_bps": (None if body.no_article else body.rate_bps),
            "no_article": bool(body.no_article),
            "article_ref": (body.article_ref or None),
            "notes": (body.notes or None),
            "verified_by": user.get("id"),
        }, on_conflict="firm_id,country_code,nature").execute().data) or []
    except Exception as e:                                      # noqa: BLE001
        raise HTTPException(status_code=400, detail=document_failure_detail(
            e, action="save this treaty rate"))
    return {"success": True, "data": (got[0] if got else None), "error": None}


@router.delete("/treaty-rates/{rate_id}")
def delete_treaty_rate(rate_id: str, user: dict = Depends(rbac("tds", "write"))):
    """Remove one reading. Bills already booked keep what they withheld — the
    deduction row records what was true at the time, not what the table says
    today."""
    from core.supabase_client import get_supabase
    from core.exceptions import document_failure_detail
    try:
        get_supabase().table("dtaa_treaty_rates").delete().eq(
            "id", rate_id).eq("firm_id", user["firm_id"]).execute()
    except Exception as e:                                      # noqa: BLE001
        raise HTTPException(status_code=400, detail=document_failure_detail(
            e, action="delete this treaty rate"))
    return {"success": True, "data": {"deleted": rate_id}, "error": None}
