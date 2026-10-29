"""Recording a §197 lower-deduction certificate (POST-A-293).

WHY THIS IS A SERVICE AND NOT A LINE IN THE BROWSER
    The client's Compliance -> TDS tab used to insert the certificate straight into `tds_lower_deduction_certificates` over PostgREST,
    where `rbac()` and the caller's client assignment never run and the table's three CHECKs and one policy were the only checks. A
    certificate LOWERS what is withheld from a real supplier: an invented one under-deducts and makes the deductor an assessee in
    default under §201(1) (migration 359). So the record is made here, after the route has asked the tier and the client, and says no
    in words:

      * the section is one the section list marks as eligible (`domain.tds.lower_deduction.section_refusal`, the same test), so a
        hand-made request cannot record a certificate against §194Q or against text;
      * the supplier is a supplier of THIS client (`named_row_ownership.vendor_is_the_clients`, a 404 in the words a missing row gets);
      * the rate is a reduction (0 to 10,000 basis points; nil is 0), the ceiling is a positive amount of paise and the period runs
        forwards, which are the table's own CHECKs said before the database says them;
      * one certificate number per supplier per section (the table's unique index), a 409 with a sentence. The pre-check is a
        convenience; the index is the guarantee, and a race is caught below as the same 409.

    What is NOT here: Rule 28AA(4)'s cap of the period at the financial year. The screen says it; the table does not enforce it and
    no primary text was read for this change, so the server does not invent the refusal.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from fastapi import HTTPException

from core.db_provider import privileged_for
from core.ist_clock import ist_fy_label
from domain.tds import lower_deduction
from services.named_row_ownership import vendor_is_the_clients

DUPLICATE = "That certificate number is already recorded for this vendor and section."


def _refuse(detail: str) -> HTTPException:
    return HTTPException(status_code=422, detail=detail)


def problems(*, section: str, certificate_no: str, rate_bps: int, valid_from: date, valid_to: date, ceiling_paise: int) -> list[str]:
    """Every reason the certificate cannot be recorded, in sentences; empty when it can. Pure."""
    found: list[str] = []
    refusal = lower_deduction.section_refusal(section, ist_fy_label(valid_from))
    if refusal:
        found.append(refusal)
    if not (certificate_no or "").strip():
        found.append("The certificate number is what Form 26Q reports: it is required.")
    if rate_bps < 0 or rate_bps > 10000:
        found.append("The certified rate is a reduction: between 0% (a nil certificate) and 100%.")
    if ceiling_paise <= 0:
        found.append("Rule 28AA(4) issues a certificate for a specified amount: the amount it applies up to must be more than nothing.")
    if valid_to < valid_from:
        found.append("The certificate cannot end before it starts.")
    return found


def record(db, *, firm_id: str, client_id: str, actor: dict, vendor_id: str, section: str, certificate_no: str, rate_bps: int,
           valid_from: date, valid_to: date, ceiling_paise: int, notes: str | None = None, store: dict | None = None) -> dict:
    """Record one certificate and return the row. `store` is the in-memory table of mock mode (no database to ask)."""
    number = (certificate_no or "").strip()
    # Upper-cased, as the reader does (`lower_deduction.certificate_from_row`): the registry's keys are upper case ("194I(A)").
    section = (section or "").strip().upper()
    found = problems(section=section, certificate_no=number, rate_bps=rate_bps, valid_from=valid_from, valid_to=valid_to,
                     ceiling_paise=ceiling_paise)
    if found:
        raise _refuse(" ".join(found))
    row = {
        "id": str(uuid.uuid4()), "firm_id": firm_id, "client_id": client_id, "vendor_id": vendor_id, "section": section,
        "certificate_no": number, "rate_bps": rate_bps, "valid_from": valid_from.isoformat(), "valid_to": valid_to.isoformat(),
        "ceiling_paise": ceiling_paise, "notes": (notes or "").strip() or None, "created_by": actor.get("id"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if store is not None:
        if any(r["firm_id"] == firm_id and r["vendor_id"] == vendor_id and r["section"] == section and r["certificate_no"] == number
               for r in store.values()):
            raise HTTPException(status_code=409, detail=DUPLICATE)
        store[row["id"]] = row
        return row
    vendor_is_the_clients(db, firm_id, client_id, vendor_id)
    taken = (db.table("tds_lower_deduction_certificates").select("id").eq("firm_id", firm_id).eq("vendor_id", vendor_id)
             .eq("section", section).eq("certificate_no", number).limit(1).execute().data or [])
    if taken:
        raise HTTPException(status_code=409, detail=DUPLICATE)
    try:
        privileged_for(db).table("tds_lower_deduction_certificates").insert(row).execute()
    except Exception as exc:                                                # noqa: BLE001
        if "23505" in str(exc) or "uq_tds_ldc" in str(exc) or "duplicate key" in str(exc).lower():
            raise HTTPException(status_code=409, detail=DUPLICATE) from exc
        raise
    return row
