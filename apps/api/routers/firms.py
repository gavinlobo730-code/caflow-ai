"""The CA practice's own profile — the one door that writes it.

WHY THIS EXISTS AND WHY IT IS NOT IN routers/onboarding.py

The firm's own identity is not onboarding: a practice edits it for years after
signing up, and until 17-09-2026 there was no endpoint for that at all. Both
screens that edit it — Settings and the onboarding wizard's update step — wrote
`public.firms` STRAIGHT OVER PostgREST, so `rbac()` never ran and no validator
did either. They wrote `gst_number`; every backend reader reads `gstin`.
`domain/firm/identity.py` is the authority for that split and records what it
cost.

WHAT THIS DOOR ADDS THAT THE COLUMN CHECK CANNOT

`firms_gstin_format` (migrations 112/316) is a shape regex. A GSTIN also carries
a CHECK DIGIT, and `domain/gst/gstin.problem_with` is the only thing in this
product that tests it — the same function GST-29 put on every other door a human
types a GSTIN through. The firm's own GSTIN goes on every fee invoice it raises
(CGST Rule 46(a)) and nothing downstream re-checks it, so a transposition here
is simply wrong on every document from day one.

Partner-only (`firm` write). This is the practice's own legal identity, not a
per-client setting.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from core.permissions import rbac
from domain.firm import identity as firm_identity
from domain.gst.gstin import problem_with as gstin_problem
from models.common import api_response

router = APIRouter(prefix="/api/firms", tags=["firms"])
_logger = logging.getLogger("caflow.firms")

#: IT Act shape. A PAN carries no check digit this product can verify, which is
#: why `models/client.py` stops here too.
_PAN = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
#: `firms_pincode_format`, restated so the refusal is a sentence rather than a
#: Postgres constraint violation surfacing as a 500.
_PINCODE = re.compile(r"^[1-9][0-9]{5}$")

#: Everything the Settings screen and the onboarding wizard between them edit.
#: `email` and `name` are NOT NULL on the table, so they are refused empty
#: rather than written as an empty string.
_TEXT_FIELDS = ("phone", "website", "icai_mrn", "address_line1", "address_line2",
                "city", "state", "address")


class FirmProfileIn(BaseModel):
    """Every field optional: this is a PATCH, and a screen that edits one box
    must not blank the eleven it did not send."""
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    gstin: Optional[str] = None
    pan: Optional[str] = None
    icai_mrn: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    address: Optional[str] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None


# THE PROJECTION IS WRITTEN OUT AT BOTH CALL SITES BELOW, not shared through a
# constant and not built from `firm_identity.COLUMNS`. Repeating it looks like
# the thing to factor out and is not, for three reasons:
#
#   * `tests/test_backend_columns_exist_pg.py` reads every `.select()` in
#     `apps/api` as a STRING and checks each column against the real schema. A
#     projection reached through a name — a `", ".join(...)` or a module
#     constant — is invisible to it and counts as an "unreadable reference".
#     That file's own budget comment records the same decision being taken
#     twice before, for `services/sales_cycle_service` and
#     `services/purchase_cycle_service`: remove the unreadability rather than
#     budget it wherever a literal will do.
#   * `test_a_narrow_projection_names_both_columns`, this feature's OWN guard,
#     matches a literal `.select("…gstin…")`. Behind a constant it never fired
#     on the two reads it was written for — the guard was vacuous here.
#   * both must name BOTH gstin columns, because `firm_identity.gstin_of` falls
#     back to `gst_number` and a row fetched without it makes that fallback a
#     silent no-op. Two literals that a guard checks beat one constant no guard
#     can see; a test also asserts the two are identical.


def _served(firm: dict) -> dict:
    """The row as a screen should render it — one `gstin`, resolved.

    `gst_number` is deliberately NOT in the answer. A screen that could see both
    would have to decide between them, and deciding is this module's job.
    """
    out = {k: v for k, v in firm.items() if k not in firm_identity.COLUMNS}
    out["gstin"] = firm_identity.gstin_of(firm)
    return out


@router.get("/profile")
def get_firm_profile(current_user: dict = Depends(rbac("firm", "read"))):
    """The caller's own firm. There is no firm_id in the request, so a Manager
    or Partner can only ever read their own."""
    firm_id = current_user.get("firm_id")
    if not firm_id:
        raise HTTPException(status_code=404, detail="This user does not belong to a firm.")
    from core.supabase_client import get_service_supabase

    rows = (get_service_supabase().table("firms")
            .select("id, name, email, phone, website, icai_mrn, pan, address, "
                    "address_line1, address_line2, city, state, pincode, "
                    "gstin, gst_number")
            .eq("id", firm_id).limit(1).execute().data or [])
    if not rows:
        raise HTTPException(status_code=404, detail="Firm not found.")
    return api_response(True, _served(rows[0]))


@router.patch("/profile")
def update_firm_profile(
    body: FirmProfileIn,
    current_user: dict = Depends(rbac("firm", "write")),
):
    """Save the firm's own profile.

    Scoped to the caller's own firm and to nothing else — there is no firm_id in
    the request, so a Partner can only ever change theirs.
    """
    firm_id = current_user.get("firm_id")
    if not firm_id:
        raise HTTPException(status_code=404, detail="This user does not belong to a firm.")

    update: dict = {}

    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="A firm must have a name.")
        update["name"] = name

    if body.email is not None:
        update["email"] = str(body.email)

    if body.gstin is not None:
        gstin = body.gstin.strip().upper()
        if gstin:
            # Shape AND check digit. This is the whole reason the write moved
            # off PostgREST — see the module docstring.
            problem = gstin_problem(gstin)
            if problem:
                raise HTTPException(status_code=400, detail=problem)
        update.update(firm_identity.writes(gstin or None))

    if body.pan is not None:
        pan = body.pan.strip().upper()
        if pan and not _PAN.match(pan):
            raise HTTPException(status_code=400,
                                detail="Invalid PAN format. Expected: AAAAA9999A")
        update["pan"] = pan or None

    if body.pincode is not None:
        pincode = body.pincode.strip()
        if pincode and not _PINCODE.match(pincode):
            raise HTTPException(status_code=400,
                                detail="A PIN code is six digits and cannot start with 0.")
        update["pincode"] = pincode or None

    for field in _TEXT_FIELDS:
        value = getattr(body, field, None)
        if value is not None:
            update[field] = value.strip() or None

    if not update:
        raise HTTPException(status_code=400, detail="Nothing to update.")

    from core.supabase_client import get_service_supabase

    db = get_service_supabase()
    res = db.table("firms").update(update).eq("id", firm_id).execute()
    if not (getattr(res, "data", None) or []):
        raise HTTPException(status_code=404, detail="Firm not found.")
    _logger.info("caflow.firms firm %s profile updated: %s",
                 firm_id, sorted(update))

    rows = (db.table("firms")
            .select("id, name, email, phone, website, icai_mrn, pan, address, "
                    "address_line1, address_line2, city, state, pincode, "
                    "gstin, gst_number")
            .eq("id", firm_id).limit(1).execute().data or [])
    return api_response(True, _served(rows[0] if rows else {"id": firm_id}))
