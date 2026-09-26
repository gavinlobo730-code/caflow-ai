"""A composition dealer's inward supplies for the year (GST-25, GSTR-4 Annual).

`domain/gst/gstr4_annual.py` is the rule; this fetches and writes the four
tables migration 422 created, and builds the whole statement — Tables 4A-4D
plus Table 5 (four already-computed CMP-08 statements, summed).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException

from core.db_paging import fetch_all


def _first(rows) -> Optional[dict]:
    rows = rows or []
    return rows[0] if rows else None


# ── Table 4A — registered supplier, non-RCM ─────────────────────────────────

def list_b2b_supplies(db, firm_id: str, client_id: str, gstin: str,
                      financial_year: str) -> list[dict]:
    return fetch_all(
        lambda: db.table("gstr4_annual_b2b_supplies").select(
            "id, firm_id, client_id, gstin, financial_year, supplier_gstin, "
            "place_of_supply, rate_bps, taxable_value_paise, igst_paise, "
            "cgst_paise, sgst_paise, cess_paise, notes, created_at, updated_at")
        .eq("firm_id", firm_id).eq("client_id", client_id)
        .eq("gstin", gstin).eq("financial_year", financial_year)
        .is_("deleted_at", "null"),
        key="id", label="gstr4_annual_b2b_supplies")


def _existing_b2b_supply(db, firm_id: str, client_id: str, gstin: str,
                         financial_year: str, supplier_gstin: str,
                         place_of_supply: str, rate_bps: int) -> Optional[dict]:
    return _first(db.table("gstr4_annual_b2b_supplies").select("id")
                  .eq("firm_id", firm_id).eq("client_id", client_id)
                  .eq("gstin", gstin).eq("financial_year", financial_year)
                  .eq("supplier_gstin", supplier_gstin)
                  .eq("place_of_supply", place_of_supply).eq("rate_bps", rate_bps)
                  .is_("deleted_at", "null").limit(1).execute().data)


def record_b2b_supply(db, firm_id: str, client_id: str, *, gstin: str,
                      financial_year: str, supplier_gstin: str,
                      place_of_supply: str, rate_bps: int = 0,
                      taxable_value_paise: int = 0, igst_paise: int = 0,
                      cgst_paise: int = 0, sgst_paise: int = 0, cess_paise: int = 0,
                      notes: Optional[str] = None,
                      actor_id: Optional[str] = None) -> dict:
    """Record or correct one registered supplier's Table 4A line for the year.

    Same upsert-by-natural-key shape as `ecommerce_operator_service
    .record_supply`: a second call for the same (client, operator GSTIN,
    year, supplier GSTIN, place of supply, rate) UPDATES rather than
    duplicates. The two dicts below repeat every key literally rather than
    spreading a shared payload dict — a `**payload` spread is a computed key
    `test_backend_columns_exist_pg.py`'s AST scan cannot read at all, which
    would take every column named here out of the schema check.
    """
    existing = _existing_b2b_supply(db, firm_id, client_id, gstin, financial_year,
                                    supplier_gstin, place_of_supply, rate_bps)
    if existing:
        rows = (db.table("gstr4_annual_b2b_supplies")
                .update({
                    "taxable_value_paise": taxable_value_paise,
                    "igst_paise": igst_paise,
                    "cgst_paise": cgst_paise,
                    "sgst_paise": sgst_paise,
                    "cess_paise": cess_paise,
                    "notes": notes,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
                .eq("id", existing["id"]).eq("firm_id", firm_id)
                .execute().data) or []
        return rows[0] if rows else existing
    rows = db.table("gstr4_annual_b2b_supplies").insert({
        "firm_id": firm_id,
        "client_id": client_id,
        "gstin": gstin,
        "financial_year": financial_year,
        "supplier_gstin": supplier_gstin,
        "place_of_supply": place_of_supply,
        "rate_bps": rate_bps,
        "taxable_value_paise": taxable_value_paise,
        "igst_paise": igst_paise,
        "cgst_paise": cgst_paise,
        "sgst_paise": sgst_paise,
        "cess_paise": cess_paise,
        "notes": notes,
        "created_by": actor_id,
    }).execute().data or []
    return rows[0] if rows else {}


def delete_b2b_supply(db, firm_id: str, supply_id: str) -> dict:
    rows = (db.table("gstr4_annual_b2b_supplies")
            .update({"deleted_at": datetime.now(timezone.utc).isoformat()})
            .eq("id", supply_id).eq("firm_id", firm_id)
            .execute().data) or []
    if not rows:
        raise HTTPException(status_code=404, detail="Entry not found.")
    return rows[0]


# ── Table 4B — registered supplier, reverse charge ──────────────────────────

def list_b2b_rc_supplies(db, firm_id: str, client_id: str, gstin: str,
                         financial_year: str) -> list[dict]:
    return fetch_all(
        lambda: db.table("gstr4_annual_b2b_rc_supplies").select(
            "id, firm_id, client_id, gstin, financial_year, supplier_gstin, "
            "place_of_supply, rate_bps, taxable_value_paise, igst_paise, "
            "cgst_paise, sgst_paise, cess_paise, notes, created_at, updated_at")
        .eq("firm_id", firm_id).eq("client_id", client_id)
        .eq("gstin", gstin).eq("financial_year", financial_year)
        .is_("deleted_at", "null"),
        key="id", label="gstr4_annual_b2b_rc_supplies")


def _existing_b2b_rc_supply(db, firm_id: str, client_id: str, gstin: str,
                            financial_year: str, supplier_gstin: str,
                            place_of_supply: str, rate_bps: int) -> Optional[dict]:
    return _first(db.table("gstr4_annual_b2b_rc_supplies").select("id")
                  .eq("firm_id", firm_id).eq("client_id", client_id)
                  .eq("gstin", gstin).eq("financial_year", financial_year)
                  .eq("supplier_gstin", supplier_gstin)
                  .eq("place_of_supply", place_of_supply).eq("rate_bps", rate_bps)
                  .is_("deleted_at", "null").limit(1).execute().data)


def record_b2b_rc_supply(db, firm_id: str, client_id: str, *, gstin: str,
                         financial_year: str, supplier_gstin: str,
                         place_of_supply: str, rate_bps: int = 0,
                         taxable_value_paise: int = 0, igst_paise: int = 0,
                         cgst_paise: int = 0, sgst_paise: int = 0, cess_paise: int = 0,
                         notes: Optional[str] = None,
                         actor_id: Optional[str] = None) -> dict:
    """Same upsert-by-natural-key shape as `record_b2b_supply` — see its
    docstring for why the two dicts below repeat their keys literally."""
    existing = _existing_b2b_rc_supply(db, firm_id, client_id, gstin, financial_year,
                                       supplier_gstin, place_of_supply, rate_bps)
    if existing:
        rows = (db.table("gstr4_annual_b2b_rc_supplies")
                .update({
                    "taxable_value_paise": taxable_value_paise,
                    "igst_paise": igst_paise,
                    "cgst_paise": cgst_paise,
                    "sgst_paise": sgst_paise,
                    "cess_paise": cess_paise,
                    "notes": notes,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
                .eq("id", existing["id"]).eq("firm_id", firm_id)
                .execute().data) or []
        return rows[0] if rows else existing
    rows = db.table("gstr4_annual_b2b_rc_supplies").insert({
        "firm_id": firm_id,
        "client_id": client_id,
        "gstin": gstin,
        "financial_year": financial_year,
        "supplier_gstin": supplier_gstin,
        "place_of_supply": place_of_supply,
        "rate_bps": rate_bps,
        "taxable_value_paise": taxable_value_paise,
        "igst_paise": igst_paise,
        "cgst_paise": cgst_paise,
        "sgst_paise": sgst_paise,
        "cess_paise": cess_paise,
        "notes": notes,
        "created_by": actor_id,
    }).execute().data or []
    return rows[0] if rows else {}


def delete_b2b_rc_supply(db, firm_id: str, supply_id: str) -> dict:
    rows = (db.table("gstr4_annual_b2b_rc_supplies")
            .update({"deleted_at": datetime.now(timezone.utc).isoformat()})
            .eq("id", supply_id).eq("firm_id", firm_id)
            .execute().data) or []
    if not rows:
        raise HTTPException(status_code=404, detail="Entry not found.")
    return rows[0]


# ── Table 4C — unregistered person ──────────────────────────────────────────

def list_urp_supplies(db, firm_id: str, client_id: str, gstin: str,
                      financial_year: str) -> list[dict]:
    return fetch_all(
        lambda: db.table("gstr4_annual_urp_supplies").select(
            "id, firm_id, client_id, gstin, financial_year, counterparty_pan, "
            "reverse_charge, place_of_supply, supply_type, rate_bps, "
            "taxable_value_paise, igst_paise, cgst_paise, sgst_paise, "
            "cess_paise, notes, created_at, updated_at")
        .eq("firm_id", firm_id).eq("client_id", client_id)
        .eq("gstin", gstin).eq("financial_year", financial_year)
        .is_("deleted_at", "null"),
        key="id", label="gstr4_annual_urp_supplies")


def _existing_urp_supply(db, firm_id: str, client_id: str, gstin: str,
                         financial_year: str, counterparty_pan: Optional[str],
                         place_of_supply: str, rate_bps: Optional[int]) -> Optional[dict]:
    # The unique index keys on COALESCE(counterparty_pan, '') and
    # COALESCE(rate_bps, -1) (migration 422's own reasoning, applied here
    # since these two fields may legitimately be absent) — mirrored here so
    # a second call for the SAME nulls still finds the row it should update.
    query = (db.table("gstr4_annual_urp_supplies").select("id")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("gstin", gstin).eq("financial_year", financial_year)
            .eq("place_of_supply", place_of_supply)
            .is_("deleted_at", "null"))
    if counterparty_pan:
        query = query.eq("counterparty_pan", counterparty_pan)
    else:
        query = query.is_("counterparty_pan", "null")
    if rate_bps is not None:
        query = query.eq("rate_bps", rate_bps)
    else:
        query = query.is_("rate_bps", "null")
    return _first(query.limit(1).execute().data)


def record_urp_supply(db, firm_id: str, client_id: str, *, gstin: str,
                      financial_year: str, counterparty_pan: Optional[str] = None,
                      reverse_charge: bool = False, place_of_supply: str,
                      supply_type: Optional[str] = None,
                      rate_bps: Optional[int] = None,
                      taxable_value_paise: int = 0, igst_paise: int = 0,
                      cgst_paise: int = 0, sgst_paise: int = 0, cess_paise: int = 0,
                      notes: Optional[str] = None,
                      actor_id: Optional[str] = None) -> dict:
    """Record or correct one unregistered supplier's Table 4C line."""
    existing = _existing_urp_supply(db, firm_id, client_id, gstin, financial_year,
                                    counterparty_pan, place_of_supply, rate_bps)
    if existing:
        rows = (db.table("gstr4_annual_urp_supplies")
                .update({
                    "reverse_charge": reverse_charge,
                    "supply_type": supply_type,
                    "taxable_value_paise": taxable_value_paise,
                    "igst_paise": igst_paise,
                    "cgst_paise": cgst_paise,
                    "sgst_paise": sgst_paise,
                    "cess_paise": cess_paise,
                    "notes": notes,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
                .eq("id", existing["id"]).eq("firm_id", firm_id)
                .execute().data) or []
        return rows[0] if rows else existing
    rows = db.table("gstr4_annual_urp_supplies").insert({
        "firm_id": firm_id,
        "client_id": client_id,
        "gstin": gstin,
        "financial_year": financial_year,
        "counterparty_pan": counterparty_pan,
        "reverse_charge": reverse_charge,
        "place_of_supply": place_of_supply,
        "supply_type": supply_type,
        "rate_bps": rate_bps,
        "taxable_value_paise": taxable_value_paise,
        "igst_paise": igst_paise,
        "cgst_paise": cgst_paise,
        "sgst_paise": sgst_paise,
        "cess_paise": cess_paise,
        "notes": notes,
        "created_by": actor_id,
    }).execute().data or []
    return rows[0] if rows else {}


def delete_urp_supply(db, firm_id: str, supply_id: str) -> dict:
    rows = (db.table("gstr4_annual_urp_supplies")
            .update({"deleted_at": datetime.now(timezone.utc).isoformat()})
            .eq("id", supply_id).eq("firm_id", firm_id)
            .execute().data) or []
    if not rows:
        raise HTTPException(status_code=404, detail="Entry not found.")
    return rows[0]


# ── Table 4D — import of services ───────────────────────────────────────────

def list_import_of_services(db, firm_id: str, client_id: str, gstin: str,
                            financial_year: str) -> list[dict]:
    return fetch_all(
        lambda: db.table("gstr4_annual_import_of_services").select(
            "id, firm_id, client_id, gstin, financial_year, place_of_supply, "
            "rate_bps, taxable_value_paise, igst_paise, cess_paise, notes, "
            "created_at, updated_at")
        .eq("firm_id", firm_id).eq("client_id", client_id)
        .eq("gstin", gstin).eq("financial_year", financial_year)
        .is_("deleted_at", "null"),
        key="id", label="gstr4_annual_import_of_services")


def _existing_import_of_service(db, firm_id: str, client_id: str, gstin: str,
                                financial_year: str, rate_bps: int) -> Optional[dict]:
    return _first(db.table("gstr4_annual_import_of_services").select("id")
                  .eq("firm_id", firm_id).eq("client_id", client_id)
                  .eq("gstin", gstin).eq("financial_year", financial_year)
                  .eq("rate_bps", rate_bps)
                  .is_("deleted_at", "null").limit(1).execute().data)


def record_import_of_service(db, firm_id: str, client_id: str, *, gstin: str,
                             financial_year: str, place_of_supply: str,
                             rate_bps: int = 0, taxable_value_paise: int = 0,
                             igst_paise: int = 0, cess_paise: int = 0,
                             notes: Optional[str] = None,
                             actor_id: Optional[str] = None) -> dict:
    """Record or correct one Table 4D line, keyed on rate alone — see
    migration 422's own note on why the sheet carries no other key."""
    existing = _existing_import_of_service(db, firm_id, client_id, gstin,
                                           financial_year, rate_bps)
    if existing:
        rows = (db.table("gstr4_annual_import_of_services")
                .update({
                    "place_of_supply": place_of_supply,
                    "taxable_value_paise": taxable_value_paise,
                    "igst_paise": igst_paise,
                    "cess_paise": cess_paise,
                    "notes": notes,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
                .eq("id", existing["id"]).eq("firm_id", firm_id)
                .execute().data) or []
        return rows[0] if rows else existing
    rows = db.table("gstr4_annual_import_of_services").insert({
        "firm_id": firm_id,
        "client_id": client_id,
        "gstin": gstin,
        "financial_year": financial_year,
        "place_of_supply": place_of_supply,
        "rate_bps": rate_bps,
        "taxable_value_paise": taxable_value_paise,
        "igst_paise": igst_paise,
        "cess_paise": cess_paise,
        "notes": notes,
        "created_by": actor_id,
    }).execute().data or []
    return rows[0] if rows else {}


def delete_import_of_service(db, firm_id: str, supply_id: str) -> dict:
    rows = (db.table("gstr4_annual_import_of_services")
            .update({"deleted_at": datetime.now(timezone.utc).isoformat()})
            .eq("id", supply_id).eq("firm_id", firm_id)
            .execute().data) or []
    if not rows:
        raise HTTPException(status_code=404, detail="Entry not found.")
    return rows[0]


# ── the whole statement ──────────────────────────────────────────────────────

def gstr4_annual_statement(db, firm_id: str, client_id: str,
                           financial_year: str,
                           gstin: Optional[str] = None) -> dict[str, Any]:
    """Tables 4A-4D plus Table 5 for one composition registration, one year.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT

    `gstin=None` means the client's primary registration. A `gstin` the
    client does not hold, or one that is not COMPOSITION, is refused — the
    same check `cmp08_statement` makes, since this is the other return that
    same registration owes.
    """
    from services.client_gst_registration_service import resolve as _resolve_registration
    from services import gst_return_service
    from domain.gst.registrations import COMPOSITION
    from domain.gst import gstr4_annual as g4
    from core.ist_clock import fy_quarters

    registration = _resolve_registration(db, firm_id, client_id, gstin)
    if registration.registration_type != COMPOSITION:
        raise ValueError(
            f"{registration.gstin} is a {registration.registration_type} "
            f"registration. GSTR-4 Annual is for a COMPOSITION registration "
            f"(CGST s.10) only — this one files GSTR-1 and GSTR-3B instead.")

    b2b_rows = list_b2b_supplies(db, firm_id, client_id, registration.gstin, financial_year)
    b2b_rc_rows = list_b2b_rc_supplies(db, firm_id, client_id, registration.gstin, financial_year)
    urp_rows = list_urp_supplies(db, firm_id, client_id, registration.gstin, financial_year)
    imps_rows = list_import_of_services(db, firm_id, client_id, registration.gstin, financial_year)

    stmt = g4.compute_gstr4_annual(
        financial_year=financial_year,
        b2b_supplies=[g4.SupplyRow(
            supplier_gstin=r["supplier_gstin"], place_of_supply=r["place_of_supply"],
            rate_bps=int(r.get("rate_bps") or 0),
            taxable_value_paise=int(r.get("taxable_value_paise") or 0),
            igst_paise=int(r.get("igst_paise") or 0),
            cgst_paise=int(r.get("cgst_paise") or 0),
            sgst_paise=int(r.get("sgst_paise") or 0),
            cess_paise=int(r.get("cess_paise") or 0),
        ) for r in b2b_rows],
        b2b_rc_supplies=[g4.SupplyRow(
            supplier_gstin=r["supplier_gstin"], place_of_supply=r["place_of_supply"],
            rate_bps=int(r.get("rate_bps") or 0),
            taxable_value_paise=int(r.get("taxable_value_paise") or 0),
            igst_paise=int(r.get("igst_paise") or 0),
            cgst_paise=int(r.get("cgst_paise") or 0),
            sgst_paise=int(r.get("sgst_paise") or 0),
            cess_paise=int(r.get("cess_paise") or 0),
        ) for r in b2b_rc_rows],
        urp_supplies=[g4.UnregisteredSupplyRow(
            counterparty_pan=r.get("counterparty_pan"),
            reverse_charge=bool(r.get("reverse_charge")),
            place_of_supply=r["place_of_supply"],
            supply_type=r.get("supply_type"),
            rate_bps=(int(r["rate_bps"]) if r.get("rate_bps") is not None else None),
            taxable_value_paise=int(r.get("taxable_value_paise") or 0),
            igst_paise=int(r.get("igst_paise") or 0),
            cgst_paise=int(r.get("cgst_paise") or 0),
            sgst_paise=int(r.get("sgst_paise") or 0),
            cess_paise=int(r.get("cess_paise") or 0),
        ) for r in urp_rows],
        import_of_services=[g4.ImportOfServiceRow(
            place_of_supply=r["place_of_supply"],
            rate_bps=int(r.get("rate_bps") or 0),
            taxable_value_paise=int(r.get("taxable_value_paise") or 0),
            igst_paise=int(r.get("igst_paise") or 0),
            cess_paise=int(r.get("cess_paise") or 0),
        ) for r in imps_rows],
        filer_state_code=registration.state_code,
    )

    # Table 5 — four cmp08_statement() calls, one per quarter, Q1 first.
    # A quarter that itself fails (e.g. no composition_category recorded)
    # is not allowed to take the whole annual return down with it — its
    # own gap already names the reason, and build_table_5 tolerates a
    # short list.
    quarterly_dicts: list[dict] = []
    missing_quarters: list[str] = []
    for label, start, _end in fy_quarters(financial_year):
        period = f"{start[5:7]}{start[0:4]}"  # MMYYYY of the quarter's first month
        try:
            quarterly_dicts.append(gst_return_service.cmp08_statement(
                db, firm_id, client_id, period, registration.gstin))
        except ValueError:
            missing_quarters.append(label)

    table5 = g4.build_table_5(financial_year, quarterly_dicts)
    table5_gaps = list(table5.gaps)
    if missing_quarters:
        table5_gaps.append(
            f"Table 5 could not be computed for: {', '.join(missing_quarters)} "
            f"— see that quarter's own CMP-08 for the reason. The totals "
            f"below are partial.")

    return {
        "financial_year": financial_year,
        "gstin": registration.gstin,
        "registration_type": registration.registration_type,
        "b2b_supplies": b2b_rows,
        "b2b_rc_supplies": b2b_rc_rows,
        "urp_supplies": urp_rows,
        "import_of_services": imps_rows,
        "b2b_total_taxable_paise": stmt.b2b_total_taxable_paise,
        "liability_taxable_paise": stmt.liability_taxable_paise,
        "liability_tax_paise": stmt.liability_tax_paise,
        "findings": [{"table": f.table, "identifier": f.identifier,
                     "problems": f.problems} for f in stmt.findings],
        "table_5": {
            "outward_taxable_paise": table5.outward_taxable_paise,
            "outward_tax_paise": table5.outward_tax_paise,
            "inward_rcm_taxable_paise": table5.inward_rcm_taxable_paise,
            "inward_rcm_tax_paise": table5.inward_rcm_tax_paise,
            "tax_paid_paise": table5.tax_paid_paise,
            "interest_paise": table5.interest_paise,
            "gaps": table5_gaps,
        },
        "gaps": stmt.gaps,
        "gstr4_annual_verified": False,
    }
