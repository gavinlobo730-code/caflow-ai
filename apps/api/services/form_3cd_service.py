"""Fetching Form 3CD's derivable clauses from the modules that already answer
each one, and reading/writing the CA's own answers for the rest.

WHY A SERVICE RATHER THAN MORE OF THE DOMAIN MODULE: `domain/income_tax/
form_3cd.py` holds the clause vocabulary and assembles a register from figures
handed to it — it touches no database. This is the layer CLAUDE.md's
architecture puts a database handle in, and it is deliberately a THIN one: every
figure below is fetched by CALLING an existing service or domain function, never
by re-deriving it from raw tables. Re-deriving the §43B(h) disallowance, the §32
block depreciation, or the brought-forward-loss balances here would be a second
implementation of a rule this codebase already has exactly one of — the same
"MOVE it, don't copy it" discipline `domain/recurrence.py`'s docstring states.

STORAGE FOR THE CLAUSES THIS PRODUCT CANNOT DERIVE: `public.tax_audit_checklists`
(migration 014) has existed since the very first schema sweep, keyed UNIQUE on
(firm_id, client_id, financial_year), with a `clauses_json` JSONB column and a
draft/review/finalised `status` — and had NO READER OR WRITER ANYWHERE in this
codebase until this file. It is exactly the shape a manual-clause store needs,
so this is the FIRST caller rather than a new migration.
"""
from __future__ import annotations

import logging
from typing import Optional

from core.db_paging import fetch_all
from domain.income_tax import form_3cd as f3cd

_logger = logging.getLogger("caflow.form_3cd")


def _fy_window(financial_year: str) -> tuple[str, str]:
    start_year = int(str(financial_year)[:4])
    return f"{start_year}-04-01", f"{start_year + 1}-03-31"


def _clause_8(db, firm_id: str, client_id: str, financial_year: str,
             nature: Optional[str]) -> tuple[Optional[object], str]:
    """Which limb of §44AB the audit is conducted under.

    Needs the client's ACTIVITY (business/profession, never inferred from the
    amount — `domain/income_tax/tax_audit.py`'s own rule) and the year's
    turnover. The activity is not a field this product stores anywhere, so it
    is asked of the CALLER; the turnover comes off the Tax Audit tracker's own
    row for this client and year, because that is the turnover the audit was
    actually opened against.
    """
    rows = (db.table("tax_audits").select("turnover_paise, form_type")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("financial_year", financial_year).limit(1)
            .execute().data or [])
    if not rows:
        return None, ("No Tax Audit tracker entry exists for this client and "
                       "year — open one on /income-tax/tax-audit first, then "
                       "this clause can be answered.")
    if not nature:
        return None, ("Turnover is on record (from the Tax Audit tracker), "
                       "but WHICH ACTIVITY it is from — business or profession "
                       "— is not stored anywhere and is never inferred from "
                       "the amount. Pass nature=business or nature=profession "
                       "to resolve this clause.")
    from domain.income_tax import tax_audit as ta
    try:
        result = ta.answer(nature=nature,
                           turnover_paise=int(rows[0]["turnover_paise"] or 0),
                           financial_year=financial_year)
    except ValueError as e:
        return None, str(e)
    return {"clause": result.clause, "form_type": result.form_type,
            "basis": result.basis}, (
        f"§44AB({result.clause.split('(')[-1].rstrip(')')}) — computed from "
        f"the Tax Audit tracker's turnover for {financial_year} and the "
        f"activity supplied. See domain/income_tax/tax_audit.py.")


def _clause_14(db, firm_id: str, client_id: str) -> tuple[Optional[object], str]:
    rows = (db.table("clients").select("inventory_costing_method")
            .eq("firm_id", firm_id).eq("id", client_id).limit(1)
            .execute().data or [])
    method = (rows[0].get("inventory_costing_method") if rows else None)
    if not method:
        return "weighted_average", (
            "No policy is recorded on the client, which reads as the "
            "weighted average — every book in this product was kept that way "
            "before FIFO existed as an option (migration 394). Deviation "
            "from §145A is not tracked and is the CA's own answer.")
    return method, ("clients.inventory_costing_method — the client's own "
                    "AS-2 paragraph 14 policy. Deviation from §145A is not "
                    "tracked and is the CA's own answer.")


def _clause_18(db, firm_id: str, client_id: str,
              financial_year: str) -> tuple[Optional[object], str]:
    from services.section_32_service import section_32_service
    try:
        out = section_32_service.assemble(db, firm_id, client_id, financial_year)
    except Exception as e:                                        # noqa: BLE001
        _logger.warning("form 3CD clause 18 for %s %s: %s", client_id,
                        financial_year, e)
        return None, "§32 block depreciation could not be assembled."
    return out, ("services/section_32_service.py — §32 written-down-value "
                "depreciation by block. Blocks with no opening WDV or rate "
                "recorded, and assets with no block assigned, are named in "
                "the value's own 'unclassified' / 'gaps' — not silently "
                "included or excluded.")


def _clause_22_and_26(db, firm_id: str, client_id: str, financial_year: str,
                      bank_rate_bps: Optional[int]) -> dict[str, tuple]:
    from services.msme_43bh_service import for_financial_year
    try:
        out = for_financial_year(db, firm_id, client_id, financial_year,
                                 bank_rate_bps=bank_rate_bps)
    except Exception as e:                                        # noqa: BLE001
        _logger.warning("form 3CD clause 22/26 for %s %s: %s", client_id,
                        financial_year, e)
        return {}
    clause_22 = out.get("msmed_interest")
    clause_26 = {
        "msme_sums_disallowed_paise": out.get("disallowed_paise"),
        "gaps": out.get("gaps"),
    }
    return {
        "22": (clause_22, "services/msme_43bh_service.py's own msmed_interest "
              "— §16 of the MSMED Act, compound interest with monthly rests "
              "at three times the RBI Bank Rate, from the same appointed day "
              "§43B(h) uses. §23 disallows this interest outright. The rate "
              "itself is not held here and is refused where not supplied."),
        "26": (clause_26, "The MSME-dues limb of §43B ONLY — "
              "domain/income_tax/section_43b_h.py's own disallowed_paise. "
              "The tax/duty/cess/fee, employer PF/gratuity/welfare-fund, "
              "bonus and interest-on-specified-loan limbs of §43B are not "
              "assembled here and are the CA's to add."),
    }


def _clause_32(db, firm_id: str, client_id: str) -> tuple[Optional[object], str]:
    from domain.income_tax.computation_workspace import list_bf_losses
    try:
        rows = list_bf_losses(firm_id, client_id)
    except Exception as e:                                        # noqa: BLE001
        _logger.warning("form 3CD clause 32 for %s: %s", client_id, e)
        return None, "Brought-forward losses could not be read."
    if not rows:
        return [], ("brought_forward_losses — no rows recorded for this "
                    "client. §79 shareholding-change, §73 speculation loss "
                    "and §73A specified-business loss are not tracked here "
                    "and are the CA's own answer regardless.")
    losses = [
        {"loss_type": r.get("loss_type"),
         "assessment_year": r.get("assessment_year"),
         "original_amount_paise": r.get("original_amount_paise"),
         "remaining_amount_paise": r.get("remaining_amount_paise"),
         "expiry_assessment_year": r.get("expiry_assessment_year")}
        for r in rows
    ]
    return losses, ("brought_forward_losses, one row per year and head — "
                    "IT-10/domain/income_tax/loss_carry_forward.py's own "
                    "expiry. §79, §73 and §73A are NOT tested here and are "
                    "named regardless of whether any row exists.")


def _clause_34(db, firm_id: str, client_id: str,
              financial_year: str) -> tuple[Optional[object], str]:
    start, end = _fy_window(financial_year)
    ident_rows = (db.table("client_statutory_identity").select("tan")
                  .eq("firm_id", firm_id).eq("client_id", client_id)
                  .limit(1).execute().data or [])
    tan = (ident_rows[0].get("tan") if ident_rows else None)

    rows = fetch_all(
        lambda: (db.table("tds_deductions")
                 .select("id, section, payment_amount_paise, tds_paise, "
                         "status, challan_no")
                 .eq("firm_id", firm_id).eq("client_id", client_id)
                 .gte("transaction_date", start).lte("transaction_date", end)),
        label="form_3cd.tds_deductions")

    by_section: dict[str, dict] = {}
    for r in rows:
        section = r.get("section") or "—"
        bucket = by_section.setdefault(section, {
            "section": section, "count": 0,
            "total_amount_paise": 0, "total_tds_deducted_paise": 0,
            "total_tds_deposited_paise": 0,
        })
        bucket["count"] += 1
        bucket["total_amount_paise"] += int(r.get("payment_amount_paise") or 0)
        deducted = int(r.get("tds_paise") or 0)
        bucket["total_tds_deducted_paise"] += deducted
        if r.get("status") in ("deposited", "filed") or r.get("challan_no"):
            bucket["total_tds_deposited_paise"] += deducted
    for bucket in by_section.values():
        bucket["tax_deducted_not_deposited_paise"] = (
            bucket["total_tds_deducted_paise"]
            - bucket["total_tds_deposited_paise"])

    value = {"tan": tan, "by_section": list(by_section.values())}
    return value, (
        "tds_deductions, grouped by section for the financial year — a "
        "SIMPLIFIED summary (total payment, total tax deducted, total "
        "deposited, the shortfall). The form's own finer columns — amount on "
        "which tax was required to be deducted against what was actually "
        "deducted, and at the specified rate against a lesser one — need a "
        "per-line comparison against domain/tds/section_rates.py this "
        "summary does not attempt; §201(1A)/§206C(7) interest is in "
        "domain/tds/interest.py and is not carried into this row either. "
        "TAN is read from client_statutory_identity.")


def _clause_44(db, firm_id: str, client_id: str,
              financial_year: str) -> tuple[Optional[object], str]:
    from domain.accounting.opening_documents import without_carried_over

    start, end = _fy_window(financial_year)
    bills = without_carried_over(fetch_all(
        lambda: (db.table("purchase_bills")
                 .select("id, vendor_id, total_paise, status, is_opening")
                 .eq("firm_id", firm_id).eq("client_id", client_id)
                 .gte("bill_date", start).lte("bill_date", end)
                 .neq("status", "cancelled")),
        label="form_3cd.purchase_bills"))

    vendor_ids = {str(b["vendor_id"]) for b in bills if b.get("vendor_id")}
    vendors: dict[str, dict] = {}
    if vendor_ids:
        for v in fetch_all(
            lambda: (db.table("vendors").select("id, gst_registration_status")
                     .eq("firm_id", firm_id).in_("id", list(vendor_ids))),
            label="form_3cd.vendors"):
            vendors[str(v["id"])] = v

    buckets = {"registered": 0, "unregistered": 0, "unrecorded": 0}
    total = 0
    for b in bills:
        amt = int(b.get("total_paise") or 0)
        total += amt
        v = vendors.get(str(b.get("vendor_id"))) or {}
        status = v.get("gst_registration_status")
        key = status if status in ("registered", "unregistered") else "unrecorded"
        buckets[key] += amt

    value = {"total_expenditure_paise": total,
             "registered_paise": buckets["registered"],
             "unregistered_paise": buckets["unregistered"],
             "unrecorded_paise": buckets["unrecorded"]}
    return value, (
        "purchase_bills joined to vendors.gst_registration_status "
        "(PUR-19), excluding opening/carried-over bills and cancelled ones. "
        "A THREE-WAY split only — registered / unregistered / unrecorded — "
        "not the form's finer columns (goods or services exempt from GST, a "
        "composition-scheme vendor, versus other registered entities), which "
        "this product does not track as separate facts about a vendor.")


def build(db, firm_id: str, client_id: str, financial_year: str, *,
         nature: Optional[str] = None,
         bank_rate_bps: Optional[int] = None) -> dict:
    """The whole register: every derivable clause computed, every manual
    clause read from `tax_audit_checklists` if the CA has recorded one."""
    derived: dict[str, tuple[Optional[object], str]] = {}
    derived["8"] = _clause_8(db, firm_id, client_id, financial_year, nature)
    derived["14"] = _clause_14(db, firm_id, client_id)
    derived["18"] = _clause_18(db, firm_id, client_id, financial_year)
    derived.update(_clause_22_and_26(db, firm_id, client_id, financial_year,
                                     bank_rate_bps))
    derived["32"] = _clause_32(db, firm_id, client_id)
    derived["34"] = _clause_34(db, firm_id, client_id, financial_year)
    derived["44"] = _clause_44(db, firm_id, client_id, financial_year)

    manual_rows = (db.table("tax_audit_checklists")
                   .select("clauses_json, status")
                   .eq("firm_id", firm_id).eq("client_id", client_id)
                   .eq("financial_year", financial_year).limit(1)
                   .execute().data or [])
    manual: dict = (manual_rows[0].get("clauses_json") or {}) if manual_rows else {}
    status = manual_rows[0].get("status") if manual_rows else "draft"

    register = f3cd.build_register(client_id=client_id,
                                   financial_year=financial_year,
                                   derived=derived, manual=manual)
    out = register.to_dict()
    out["checklist_status"] = status
    return out


def save_manual_clauses(db, firm_id: str, client_id: str, financial_year: str,
                        clauses: dict, status: str = "draft") -> dict:
    """Upsert the CA's own answers for clauses this product does not derive.

    `clauses` may name ANY clause code, including a derivable one — the
    caller's value does not win there (`build` above only reads `manual` for
    codes ABSENT from `derived`), so recording a note against clause 18 does
    not shadow the computed §32 figure. That is a deliberate asymmetry from
    `domain/tds/deductor.resolve`'s "caller wins": the derived clauses here are
    figures from the client's own live books, and a stale manual override
    sitting underneath one would go stale the next time a bill was entered.
    """
    existing = (db.table("tax_audit_checklists").select("id")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .eq("financial_year", financial_year).limit(1)
                .execute().data or [])
    # Inline at both calls rather than built once and passed by name: the
    # schema-safety scanner (tests/test_backend_columns_exist_pg.py) reads a
    # write's columns off a literal dict argument, not off whatever a variable
    # happens to be bound to, so a shared `payload` is invisible to it twice.
    if existing:
        (db.table("tax_audit_checklists")
         .update({"firm_id": firm_id, "client_id": client_id,
                  "financial_year": financial_year, "clauses_json": clauses,
                  "status": status})
         .eq("id", existing[0]["id"]).execute())
    else:
        db.table("tax_audit_checklists").insert(
            {"firm_id": firm_id, "client_id": client_id,
             "financial_year": financial_year, "clauses_json": clauses,
             "status": status}).execute()
    return {"firm_id": firm_id, "client_id": client_id,
            "financial_year": financial_year, "clauses_json": clauses,
            "status": status}
