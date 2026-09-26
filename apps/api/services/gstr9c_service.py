"""GSTR-9C — the audited-books reconciliation statement (GST-25, part 4).

`domain/gst/gstr9c.py` is the rule; this fetches the CA-recorded rows
migration 423 created, the already-built GSTR-9 for the same registration and
year (`services.gstr9_service.build`), and the fact of whether this client
holds more than one GSTIN (GST-20) — the one input the domain module has no
database handle to resolve itself.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException

from core.db_paging import fetch_all


def _first(rows) -> Optional[dict]:
    rows = rows or []
    return rows[0] if rows else None


def _is_ecommerce_year(financial_year: str) -> bool:
    """FY 2024-25 onward — see domain/gst/gstr9c.py's own GAP_ECOMMERCE_ROW."""
    try:
        start_year = int(financial_year[:4])
    except (ValueError, TypeError):
        return False
    return start_year >= 2024


# ── Part A — the reconciliation row ─────────────────────────────────────────
#
# `get_reconciliation`'s `.select()` and `save_reconciliation`'s `.update()`/
# `.insert()` each name every column as a LITERAL rather than through a shared
# constant or a spread `**payload` dict — a `.select()` reached through a name
# and a `**` spread are both invisible to `test_backend_columns_exist_pg.py`'s
# AST scan, which would take every column named here out of the schema check
# (CLAUDE.md's `domain/firm/identity.py` note records the same trade and
# takes the same side of it: duplicated literals, not an unreadable write).

def get_reconciliation(db, firm_id: str, client_id: str, gstin: str,
                       financial_year: str) -> Optional[dict]:
    return _first(db.table("gstr9c_reconciliations").select(
            "id, firm_id, client_id, gstin, financial_year, act_name, "
            "turnover_per_audited_fs_paise, unbilled_revenue_begin_paise, "
            "unadjusted_advances_end_paise, deemed_supply_paise, "
            "credit_notes_issued_post_fy_paise, trade_discount_not_permissible_paise, "
            "unbilled_revenue_end_paise, unadjusted_advances_begin_paise, "
            "credit_notes_in_fs_not_permissible_paise, sez_dta_adjustment_paise, "
            "composition_period_turnover_paise, section_15_adjustment_paise, "
            "forex_adjustment_paise, other_turnover_adjustment_paise, "
            "turnover_after_adjustments_paise, turnover_reasons, "
            "exempt_nil_nongst_turnover_paise, zero_rated_no_tax_turnover_paise, "
            "reverse_charge_turnover_paise, ecommerce_9_5_turnover_paise, "
            "taxable_turnover_after_adjustments_paise, taxable_turnover_reasons, "
            "itc_per_audited_fs_paise, itc_booked_earlier_fy_claimed_this_fy_paise, "
            "itc_booked_this_fy_claimed_later_fy_paise, itc_reasons, "
            "unreconciled_itc_tax_igst_paise, unreconciled_itc_tax_cgst_paise, "
            "unreconciled_itc_tax_sgst_paise, unreconciled_itc_tax_cess_paise, "
            "unreconciled_itc_interest_paise, unreconciled_itc_penalty_paise, "
            "itc_reasons_16, notes, created_at, updated_at")
                  .eq("firm_id", firm_id).eq("client_id", client_id)
                  .eq("gstin", gstin).eq("financial_year", financial_year)
                  .is_("deleted_at", "null").limit(1).execute().data)


def save_reconciliation(db, firm_id: str, client_id: str, *, gstin: str,
                        financial_year: str, actor_id: Optional[str] = None,
                        **fields: Any) -> dict:
    """Record or correct the CA's own reconciling figures for the year.

    Same upsert-by-natural-key shape as `gstr4_annual_service.record_b2b_supply`
    — a second call for the same (client, gstin, year) UPDATES rather than
    duplicates. `fields` is whichever of the Table 5/7/12/16 columns the
    caller sends.
    """
    existing = get_reconciliation(db, firm_id, client_id, gstin, financial_year)
    if existing:
        rows = (db.table("gstr9c_reconciliations")
                .update({
                    "act_name": fields.get("act_name"),
                    "turnover_per_audited_fs_paise": fields.get("turnover_per_audited_fs_paise"),
                    "unbilled_revenue_begin_paise": fields.get("unbilled_revenue_begin_paise"),
                    "unadjusted_advances_end_paise": fields.get("unadjusted_advances_end_paise"),
                    "deemed_supply_paise": fields.get("deemed_supply_paise"),
                    "credit_notes_issued_post_fy_paise": fields.get("credit_notes_issued_post_fy_paise"),
                    "trade_discount_not_permissible_paise": fields.get("trade_discount_not_permissible_paise"),
                    "unbilled_revenue_end_paise": fields.get("unbilled_revenue_end_paise"),
                    "unadjusted_advances_begin_paise": fields.get("unadjusted_advances_begin_paise"),
                    "credit_notes_in_fs_not_permissible_paise": fields.get("credit_notes_in_fs_not_permissible_paise"),
                    "sez_dta_adjustment_paise": fields.get("sez_dta_adjustment_paise"),
                    "composition_period_turnover_paise": fields.get("composition_period_turnover_paise"),
                    "section_15_adjustment_paise": fields.get("section_15_adjustment_paise"),
                    "forex_adjustment_paise": fields.get("forex_adjustment_paise"),
                    "other_turnover_adjustment_paise": fields.get("other_turnover_adjustment_paise"),
                    "turnover_after_adjustments_paise": fields.get("turnover_after_adjustments_paise"),
                    "turnover_reasons": fields.get("turnover_reasons") or [],
                    "exempt_nil_nongst_turnover_paise": fields.get("exempt_nil_nongst_turnover_paise"),
                    "zero_rated_no_tax_turnover_paise": fields.get("zero_rated_no_tax_turnover_paise"),
                    "reverse_charge_turnover_paise": fields.get("reverse_charge_turnover_paise"),
                    "ecommerce_9_5_turnover_paise": fields.get("ecommerce_9_5_turnover_paise"),
                    "taxable_turnover_after_adjustments_paise": fields.get("taxable_turnover_after_adjustments_paise"),
                    "taxable_turnover_reasons": fields.get("taxable_turnover_reasons") or [],
                    "itc_per_audited_fs_paise": fields.get("itc_per_audited_fs_paise"),
                    "itc_booked_earlier_fy_claimed_this_fy_paise": fields.get("itc_booked_earlier_fy_claimed_this_fy_paise"),
                    "itc_booked_this_fy_claimed_later_fy_paise": fields.get("itc_booked_this_fy_claimed_later_fy_paise"),
                    "itc_reasons": fields.get("itc_reasons") or [],
                    "unreconciled_itc_tax_igst_paise": fields.get("unreconciled_itc_tax_igst_paise"),
                    "unreconciled_itc_tax_cgst_paise": fields.get("unreconciled_itc_tax_cgst_paise"),
                    "unreconciled_itc_tax_sgst_paise": fields.get("unreconciled_itc_tax_sgst_paise"),
                    "unreconciled_itc_tax_cess_paise": fields.get("unreconciled_itc_tax_cess_paise"),
                    "unreconciled_itc_interest_paise": fields.get("unreconciled_itc_interest_paise"),
                    "unreconciled_itc_penalty_paise": fields.get("unreconciled_itc_penalty_paise"),
                    "itc_reasons_16": fields.get("itc_reasons_16") or [],
                    "notes": fields.get("notes"),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
                .eq("id", existing["id"]).eq("firm_id", firm_id)
                .execute().data) or []
        return rows[0] if rows else existing
    rows = db.table("gstr9c_reconciliations").insert({
        "firm_id": firm_id,
        "client_id": client_id,
        "gstin": gstin,
        "financial_year": financial_year,
        "act_name": fields.get("act_name"),
        "turnover_per_audited_fs_paise": fields.get("turnover_per_audited_fs_paise"),
        "unbilled_revenue_begin_paise": fields.get("unbilled_revenue_begin_paise"),
        "unadjusted_advances_end_paise": fields.get("unadjusted_advances_end_paise"),
        "deemed_supply_paise": fields.get("deemed_supply_paise"),
        "credit_notes_issued_post_fy_paise": fields.get("credit_notes_issued_post_fy_paise"),
        "trade_discount_not_permissible_paise": fields.get("trade_discount_not_permissible_paise"),
        "unbilled_revenue_end_paise": fields.get("unbilled_revenue_end_paise"),
        "unadjusted_advances_begin_paise": fields.get("unadjusted_advances_begin_paise"),
        "credit_notes_in_fs_not_permissible_paise": fields.get("credit_notes_in_fs_not_permissible_paise"),
        "sez_dta_adjustment_paise": fields.get("sez_dta_adjustment_paise"),
        "composition_period_turnover_paise": fields.get("composition_period_turnover_paise"),
        "section_15_adjustment_paise": fields.get("section_15_adjustment_paise"),
        "forex_adjustment_paise": fields.get("forex_adjustment_paise"),
        "other_turnover_adjustment_paise": fields.get("other_turnover_adjustment_paise"),
        "turnover_after_adjustments_paise": fields.get("turnover_after_adjustments_paise"),
        "turnover_reasons": fields.get("turnover_reasons") or [],
        "exempt_nil_nongst_turnover_paise": fields.get("exempt_nil_nongst_turnover_paise"),
        "zero_rated_no_tax_turnover_paise": fields.get("zero_rated_no_tax_turnover_paise"),
        "reverse_charge_turnover_paise": fields.get("reverse_charge_turnover_paise"),
        "ecommerce_9_5_turnover_paise": fields.get("ecommerce_9_5_turnover_paise"),
        "taxable_turnover_after_adjustments_paise": fields.get("taxable_turnover_after_adjustments_paise"),
        "taxable_turnover_reasons": fields.get("taxable_turnover_reasons") or [],
        "itc_per_audited_fs_paise": fields.get("itc_per_audited_fs_paise"),
        "itc_booked_earlier_fy_claimed_this_fy_paise": fields.get("itc_booked_earlier_fy_claimed_this_fy_paise"),
        "itc_booked_this_fy_claimed_later_fy_paise": fields.get("itc_booked_this_fy_claimed_later_fy_paise"),
        "itc_reasons": fields.get("itc_reasons") or [],
        "unreconciled_itc_tax_igst_paise": fields.get("unreconciled_itc_tax_igst_paise"),
        "unreconciled_itc_tax_cgst_paise": fields.get("unreconciled_itc_tax_cgst_paise"),
        "unreconciled_itc_tax_sgst_paise": fields.get("unreconciled_itc_tax_sgst_paise"),
        "unreconciled_itc_tax_cess_paise": fields.get("unreconciled_itc_tax_cess_paise"),
        "unreconciled_itc_interest_paise": fields.get("unreconciled_itc_interest_paise"),
        "unreconciled_itc_penalty_paise": fields.get("unreconciled_itc_penalty_paise"),
        "itc_reasons_16": fields.get("itc_reasons_16") or [],
        "notes": fields.get("notes"),
        "created_by": actor_id,
    }).execute().data or []
    return rows[0] if rows else {}


# ── Tables 9, 11, Part V — the rate-wise lines ──────────────────────────────

def list_rate_wise_lines(db, firm_id: str, reconciliation_id: str,
                         table_ref: Optional[str] = None) -> list[dict]:
    query = (db.table("gstr9c_rate_wise_lines").select(
            "id, reconciliation_id, table_ref, rate_description, "
            "taxable_value_paise, igst_paise, cgst_paise, sgst_paise, "
            "cess_paise, line_order")
            .eq("firm_id", firm_id).eq("reconciliation_id", reconciliation_id)
            .is_("deleted_at", "null"))
    if table_ref:
        query = query.eq("table_ref", table_ref)
    return fetch_all(lambda: query, key="id", label="gstr9c_rate_wise_lines")


def add_rate_wise_line(db, firm_id: str, client_id: str, reconciliation_id: str, *,
                       table_ref: str, rate_description: str,
                       taxable_value_paise: int = 0, igst_paise: int = 0,
                       cgst_paise: int = 0, sgst_paise: int = 0, cess_paise: int = 0,
                       line_order: int = 0, actor_id: Optional[str] = None) -> dict:
    rows = db.table("gstr9c_rate_wise_lines").insert({
        "firm_id": firm_id, "client_id": client_id,
        "reconciliation_id": reconciliation_id, "table_ref": table_ref,
        "rate_description": rate_description,
        "taxable_value_paise": taxable_value_paise, "igst_paise": igst_paise,
        "cgst_paise": cgst_paise, "sgst_paise": sgst_paise, "cess_paise": cess_paise,
        "line_order": line_order, "created_by": actor_id,
    }).execute().data or []
    return rows[0] if rows else {}


def delete_rate_wise_line(db, firm_id: str, line_id: str) -> dict:
    rows = (db.table("gstr9c_rate_wise_lines")
            .update({"deleted_at": datetime.now(timezone.utc).isoformat()})
            .eq("id", line_id).eq("firm_id", firm_id)
            .execute().data) or []
    if not rows:
        raise HTTPException(status_code=404, detail="Entry not found.")
    return rows[0]


# ── Table 14 — the expense-head lines ───────────────────────────────────────

def list_expense_lines(db, firm_id: str, reconciliation_id: str) -> list[dict]:
    return fetch_all(
        lambda: db.table("gstr9c_expense_lines").select(
            "id, reconciliation_id, expense_head, value_paise, total_itc_paise, "
            "eligible_itc_availed_paise, line_order")
        .eq("firm_id", firm_id).eq("reconciliation_id", reconciliation_id)
        .is_("deleted_at", "null"),
        key="id", label="gstr9c_expense_lines")


def add_expense_line(db, firm_id: str, client_id: str, reconciliation_id: str, *,
                     expense_head: str, value_paise: int = 0, total_itc_paise: int = 0,
                     eligible_itc_availed_paise: int = 0, line_order: int = 0,
                     actor_id: Optional[str] = None) -> dict:
    rows = db.table("gstr9c_expense_lines").insert({
        "firm_id": firm_id, "client_id": client_id,
        "reconciliation_id": reconciliation_id, "expense_head": expense_head,
        "value_paise": value_paise, "total_itc_paise": total_itc_paise,
        "eligible_itc_availed_paise": eligible_itc_availed_paise,
        "line_order": line_order, "created_by": actor_id,
    }).execute().data or []
    return rows[0] if rows else {}


def delete_expense_line(db, firm_id: str, line_id: str) -> dict:
    rows = (db.table("gstr9c_expense_lines")
            .update({"deleted_at": datetime.now(timezone.utc).isoformat()})
            .eq("id", line_id).eq("firm_id", firm_id)
            .execute().data) or []
    if not rows:
        raise HTTPException(status_code=404, detail="Entry not found.")
    return rows[0]


# ── the whole statement ──────────────────────────────────────────────────────

def gstr9c_statement(db, firm_id: str, client_id: str, financial_year: str,
                     gstin: Optional[str] = None) -> dict[str, Any]:
    """The reconciliation statement for one registration, one financial year.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT

    `gstin=None` means the client's primary registration. Reads the
    already-built GSTR-9 for the SAME key (services.gstr9_service.build) —
    never a second, independent read of the filed returns — and whether this
    client holds more than one registration, which is the one fact
    domain/gst/gstr9c.py has no database handle to resolve itself.
    """
    from services.client_gst_registration_service import resolve as _resolve_registration
    from services.client_gst_registration_service import listing as _list_registrations
    from services import gstr9_service
    from domain.gst import gstr9c as g9c

    registration = _resolve_registration(db, firm_id, client_id, gstin)
    all_registrations = _list_registrations(db, firm_id, client_id)

    recon_row = get_reconciliation(db, firm_id, client_id, registration.gstin,
                                   financial_year)
    reconciliation = g9c.Reconciliation(
        financial_year=financial_year,
        act_name=(recon_row or {}).get("act_name"),
        turnover_per_audited_fs_paise=(recon_row or {}).get("turnover_per_audited_fs_paise"),
        unbilled_revenue_begin_paise=(recon_row or {}).get("unbilled_revenue_begin_paise"),
        unadjusted_advances_end_paise=(recon_row or {}).get("unadjusted_advances_end_paise"),
        deemed_supply_paise=(recon_row or {}).get("deemed_supply_paise"),
        credit_notes_issued_post_fy_paise=(recon_row or {}).get("credit_notes_issued_post_fy_paise"),
        trade_discount_not_permissible_paise=(recon_row or {}).get("trade_discount_not_permissible_paise"),
        unbilled_revenue_end_paise=(recon_row or {}).get("unbilled_revenue_end_paise"),
        unadjusted_advances_begin_paise=(recon_row or {}).get("unadjusted_advances_begin_paise"),
        credit_notes_in_fs_not_permissible_paise=(recon_row or {}).get("credit_notes_in_fs_not_permissible_paise"),
        sez_dta_adjustment_paise=(recon_row or {}).get("sez_dta_adjustment_paise"),
        composition_period_turnover_paise=(recon_row or {}).get("composition_period_turnover_paise"),
        section_15_adjustment_paise=(recon_row or {}).get("section_15_adjustment_paise"),
        forex_adjustment_paise=(recon_row or {}).get("forex_adjustment_paise"),
        other_turnover_adjustment_paise=(recon_row or {}).get("other_turnover_adjustment_paise"),
        turnover_after_adjustments_paise=(recon_row or {}).get("turnover_after_adjustments_paise"),
        turnover_reasons=(recon_row or {}).get("turnover_reasons") or [],
        exempt_nil_nongst_turnover_paise=(recon_row or {}).get("exempt_nil_nongst_turnover_paise"),
        zero_rated_no_tax_turnover_paise=(recon_row or {}).get("zero_rated_no_tax_turnover_paise"),
        reverse_charge_turnover_paise=(recon_row or {}).get("reverse_charge_turnover_paise"),
        ecommerce_9_5_turnover_paise=(recon_row or {}).get("ecommerce_9_5_turnover_paise"),
        taxable_turnover_after_adjustments_paise=(recon_row or {}).get("taxable_turnover_after_adjustments_paise"),
        taxable_turnover_reasons=(recon_row or {}).get("taxable_turnover_reasons") or [],
        itc_per_audited_fs_paise=(recon_row or {}).get("itc_per_audited_fs_paise"),
        itc_booked_earlier_fy_claimed_this_fy_paise=(recon_row or {}).get("itc_booked_earlier_fy_claimed_this_fy_paise"),
        itc_booked_this_fy_claimed_later_fy_paise=(recon_row or {}).get("itc_booked_this_fy_claimed_later_fy_paise"),
        itc_reasons=(recon_row or {}).get("itc_reasons") or [],
        unreconciled_itc_tax_igst_paise=(recon_row or {}).get("unreconciled_itc_tax_igst_paise"),
        unreconciled_itc_tax_cgst_paise=(recon_row or {}).get("unreconciled_itc_tax_cgst_paise"),
        unreconciled_itc_tax_sgst_paise=(recon_row or {}).get("unreconciled_itc_tax_sgst_paise"),
        unreconciled_itc_tax_cess_paise=(recon_row or {}).get("unreconciled_itc_tax_cess_paise"),
        unreconciled_itc_interest_paise=(recon_row or {}).get("unreconciled_itc_interest_paise"),
        unreconciled_itc_penalty_paise=(recon_row or {}).get("unreconciled_itc_penalty_paise"),
        itc_reasons_16=(recon_row or {}).get("itc_reasons_16") or [],
    )

    rate_wise_rows = (list_rate_wise_lines(db, firm_id, recon_row["id"])
                      if recon_row else [])
    rate_wise_lines = [g9c.RateWiseLine(
        table_ref=r["table_ref"], rate_description=r["rate_description"],
        taxable_value_paise=int(r.get("taxable_value_paise") or 0),
        igst_paise=int(r.get("igst_paise") or 0), cgst_paise=int(r.get("cgst_paise") or 0),
        sgst_paise=int(r.get("sgst_paise") or 0), cess_paise=int(r.get("cess_paise") or 0),
    ) for r in rate_wise_rows]

    expense_rows = (list_expense_lines(db, firm_id, recon_row["id"])
                    if recon_row else [])
    expense_lines = [g9c.ExpenseLine(
        expense_head=r["expense_head"],
        value_paise=int(r.get("value_paise") or 0),
        total_itc_paise=int(r.get("total_itc_paise") or 0),
        eligible_itc_availed_paise=int(r.get("eligible_itc_availed_paise") or 0),
    ) for r in expense_rows]

    gstr9 = gstr9_service.build(db, firm_id, client_id,
                                financial_year=financial_year, gstin=registration.gstin)

    stmt = g9c.compute_gstr9c(
        financial_year=financial_year, gstin=registration.gstin,
        reconciliation=reconciliation, rate_wise_lines=rate_wise_lines,
        expense_lines=expense_lines, gstr9_tables=gstr9.get("tables") or {},
        multi_gstin_client=len(all_registrations) > 1,
        is_ecommerce_year=_is_ecommerce_year(financial_year),
    )

    def _line_dict(l) -> dict:
        return {"table_ref": l.table_ref, "rate_description": l.rate_description,
               "taxable_value_paise": l.taxable_value_paise, "igst_paise": l.igst_paise,
               "cgst_paise": l.cgst_paise, "sgst_paise": l.sgst_paise,
               "cess_paise": l.cess_paise, "tax_paise": l.tax_paise}

    def _expense_dict(l) -> dict:
        return {"expense_head": l.expense_head, "value_paise": l.value_paise,
               "total_itc_paise": l.total_itc_paise,
               "eligible_itc_availed_paise": l.eligible_itc_availed_paise}

    return {
        "financial_year": financial_year,
        "gstin": registration.gstin,
        "registration_type": registration.registration_type,
        "reconciliation_id": (recon_row or {}).get("id"),
        "act_name": reconciliation.act_name,
        "table5": {
            "audited_turnover_paise": stmt.table5.audited_turnover_paise,
            "adjustments_total_paise": stmt.table5.adjustments_total_paise,
            "turnover_after_adjustments_paise": stmt.table5.turnover_after_adjustments_paise,
            "declared_turnover_paise": stmt.table5.declared_turnover_paise,
            "unreconciled_paise": stmt.table5.unreconciled_paise,
            "reasons": reconciliation.turnover_reasons,
        },
        "table7": {
            "taxable_turnover_after_adjustments_paise": stmt.table7.taxable_turnover_after_adjustments_paise,
            "declared_taxable_turnover_paise": stmt.table7.declared_taxable_turnover_paise,
            "unreconciled_paise": stmt.table7.unreconciled_paise,
            "reasons": reconciliation.taxable_turnover_reasons,
        },
        "table9": {
            "lines": [_line_dict(l) for l in stmt.table9.lines],
            "total_payable_paise": stmt.table9.total_payable_paise,
            "declared": stmt.table9.declared,
            "declared_tax_paid_paise": stmt.table9.declared_tax_paid_paise,
        },
        "table11": {
            "lines": [_line_dict(l) for l in stmt.table11.lines],
            "total_paise": stmt.table11.total_paise,
        },
        "table12": {
            "itc_per_audited_fs_paise": stmt.table12.itc_per_audited_fs_paise,
            "booked_earlier_claimed_this_fy_paise": stmt.table12.booked_earlier_claimed_this_fy_paise,
            "booked_this_fy_claimed_later_fy_paise": stmt.table12.booked_this_fy_claimed_later_fy_paise,
            "audited_adjusted_paise": stmt.table12.audited_adjusted_paise,
            "itc_claim_paise": stmt.table12.itc_claim_paise,
            "itc_claim_alternate_paise": stmt.table12.itc_claim_alternate_paise,
            "unreconciled_paise": stmt.table12.unreconciled_paise,
            "reasons": reconciliation.itc_reasons,
        },
        "table14": {
            "lines": [_expense_dict(l) for l in stmt.table14.lines],
            "total_value_paise": stmt.table14.total_value_paise,
            "total_itc_paise": stmt.table14.total_itc_paise,
            "total_eligible_itc_availed_paise": stmt.table14.total_eligible_itc_availed_paise,
            "itc_claim_paise": stmt.table14.itc_claim_paise,
            "unreconciled_paise": stmt.table14.unreconciled_paise,
        },
        "table16": {
            "tax_igst_paise": stmt.table16.tax_igst_paise,
            "tax_cgst_paise": stmt.table16.tax_cgst_paise,
            "tax_sgst_paise": stmt.table16.tax_sgst_paise,
            "tax_cess_paise": stmt.table16.tax_cess_paise,
            "interest_paise": stmt.table16.interest_paise,
            "penalty_paise": stmt.table16.penalty_paise,
            "reasons": reconciliation.itc_reasons_16,
        },
        "part_v": {
            "lines": [_line_dict(l) for l in stmt.part_v.lines],
            "total_paise": stmt.part_v.total_paise,
        },
        "gaps": stmt.gaps,
        "threshold_table": list(g9c.THRESHOLD_TABLE),
        "self_certification_from_fy": g9c.SELF_CERTIFICATION_FROM_FY,
        "gstr9c_verified": g9c.VERIFIED,
    }
