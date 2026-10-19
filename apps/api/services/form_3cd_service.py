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


GAP_CHALLAN_RECORDED_MORE_THAN_ONCE = "challan_recorded_more_than_once"


def _deposits_by_deduction(rows: list, challans: list, fy_label: str) -> tuple[dict[str, int], list[dict]]:
    """(each deduction's covered tax in paise by deduction id, the register's own warnings), from the CHALLAN REGISTER.

    A challan pays the deductions of its own financial year and quarter under its own section, first in first out
    (`domain/tds/challan_mapping`, through `deposit_due.mapping_from_register`): the worksheet's match. Nothing else says a
    deduction was deposited. The two columns this clause used to read for it, a deduction's `status` and its `challan_no`,
    are never written for a deduction a purchase bill wrote (`POST /challans` records the challan and never touches the
    deductions it paid), so for nearly every deduction the clause said the whole tax was deducted and not deposited. A
    challan number typed on a hand-keyed deduction is a note and is not read.

    The warnings are what the register itself says about the year, so that a figure is not read without them: a challan
    that paid more than its quarter and section deducted (which is also what a challan filed under the wrong quarter looks
    like), and a challan recorded more than once under the same branch code, serial and date, which would otherwise be
    counted as two deposits."""
    from domain.tds import challan_mapping, deposit_due
    from services.compliance_engine import tds_quarter_of_month

    quarters: dict[str, list] = {}
    for row in rows:
        # A row with no usable date cannot be placed in a quarter: it stays uncovered, which is what the clause then says of it.
        on = challan_mapping.as_date(row.get("transaction_date"))
        if on is not None:
            quarters.setdefault(tds_quarter_of_month(on.month), []).append(row)
    covered: dict[str, int] = {}
    warnings: list[dict] = []
    # A quarter with challans and no deductions is read too: that is where a challan filed under the wrong quarter shows.
    for quarter in sorted(set(quarters) | {c.get("quarter") for c in challans}):
        theirs = [c for c in challans if c.get("quarter") == quarter]
        mapping = deposit_due.mapping_from_register(quarters.get(quarter, []), theirs, fy=fy_label)
        for row in quarters.get(quarter, []):
            covered[str(row.get("id"))] = mapping.for_deduction(row.get("id")).deposited_paise
        warnings.extend({**g, "quarter": quarter} for g in mapping.gaps
                        if g.get("code") == challan_mapping.GAP_CHALLAN_EXCEEDS_DEDUCTIONS)
    seen: dict[tuple, int] = {}
    for c in challans:
        key = (str(c.get("bsr_code") or ""), str(c.get("challan_no") or ""), str(c.get("payment_date") or "")[:10])
        seen[key] = seen.get(key, 0) + 1
    warnings.extend({"code": GAP_CHALLAN_RECORDED_MORE_THAN_ONCE, "bsr_code": k[0], "challan_no": k[1],
                     "payment_date": k[2], "times": n,
                     "message": f"Challan {k[1]} of {k[2]} is recorded {n} times, and each is counted as a deposit."}
                    for k, n in sorted(seen.items()) if n > 1)
    return covered, warnings


def _clause_34(db, firm_id: str, client_id: str,
              financial_year: str) -> tuple[Optional[object], str]:
    """Form 3CD clause 34 (Rule 6G; IT Act §44AB): tax deducted or collected, by section, and how much of it has not been
    deposited to the credit of the Central Government (§200, Rule 30). THE DEPOSIT IS READ FROM THE CHALLAN REGISTER, and a
    quarter in which no challan at all is recorded is NOT "nothing was deposited": the books cannot say, so its tax is
    reported apart (`deposit_not_recorded_paise`), never as a deposit default."""
    from domain.tds import deposit_due

    start, end = _fy_window(financial_year)
    fy_label = f"{start[:4]}-{(int(start[:4]) + 1) % 100:02d}"
    ident_rows = (db.table("client_statutory_identity").select("tan")
                  .eq("firm_id", firm_id).eq("client_id", client_id)
                  .limit(1).execute().data or [])
    tan = (ident_rows[0].get("tan") if ident_rows else None)

    rows = fetch_all(
        lambda: (db.table("tds_deductions")
                 .select("id, section, payment_amount_paise, tds_paise, surcharge_paise, cess_paise, transaction_date")
                 .eq("firm_id", firm_id).eq("client_id", client_id)
                 .gte("transaction_date", start).lte("transaction_date", end)),
        label="form_3cd.tds_deductions")
    challans = fetch_all(
        lambda: (db.table("tds_challans")
                 .select("id, challan_no, bsr_code, section, financial_year, quarter, tds_paise, surcharge_paise, payment_date")
                 .eq("firm_id", firm_id).eq("client_id", client_id)
                 .eq("financial_year", fy_label)),
        label="form_3cd.tds_challans")

    # Salary (section 192) is deposited from payroll and its challans are matched in the 24Q, not in this register's
    # deductions: a row under it is left out and counted, not shown as undeposited.
    salary_rows = [r for r in rows if deposit_due.is_salary(str(r.get("section") or ""))]
    rows = [r for r in rows if not deposit_due.is_salary(str(r.get("section") or ""))]
    challans = [c for c in challans if not deposit_due.is_salary(str(c.get("section") or ""))]
    covered, warnings = _deposits_by_deduction(rows, challans, fy_label)
    quarters_with_a_challan = {c.get("quarter") for c in challans}

    from domain.tds import challan_mapping
    from services.compliance_engine import tds_quarter_of_month

    by_section: dict[str, dict] = {}
    for r in rows:
        section = r.get("section") or "—"
        bucket = by_section.setdefault(section, {
            "section": section, "count": 0,
            "total_amount_paise": 0, "total_tds_deducted_paise": 0,
            "total_tds_deposited_paise": 0, "tax_deducted_not_deposited_paise": 0,
            "deposit_not_recorded_paise": 0, "surcharge_or_cess_makes_the_split_approximate": False,
        })
        bucket["count"] += 1
        bucket["total_amount_paise"] += int(r.get("payment_amount_paise") or 0)
        deducted = int(r.get("tds_paise") or 0)
        bucket["total_tds_deducted_paise"] += deducted
        # Measured against the tax column this clause has always summed (tds_paise); the register's cover is of tax, surcharge
        # and cess together, so it is capped at the row's own tax.
        paid = min(deducted, covered.get(str(r.get("id")), 0))
        bucket["total_tds_deposited_paise"] += paid
        on = challan_mapping.as_date(r.get("transaction_date"))
        quarter = tds_quarter_of_month(on.month) if on is not None else None
        # Not deposited where the register has spoken about the quarter; not RECORDED where it holds no challan for it.
        key = ("tax_deducted_not_deposited_paise" if quarter in quarters_with_a_challan
               else "deposit_not_recorded_paise")
        bucket[key] += deducted - paid
        if int(r.get("surcharge_paise") or 0) or int(r.get("cess_paise") or 0):
            bucket["surcharge_or_cess_makes_the_split_approximate"] = True

    value = {"tan": tan, "by_section": list(by_section.values()),
             "challans_read": len(challans), "salary_rows_left_out": len(salary_rows),
             "register_warnings": warnings}
    return value, (
        "tds_deductions, grouped by section for the financial year — a "
        "SIMPLIFIED summary (total payment, total tax deducted, total "
        "deposited, the shortfall). DEPOSITED is what the CHALLAN REGISTER covers: "
        + (f"the {len(challans)} challan(s) recorded for FY {fy_label}, each paying the deductions of its own quarter and "
           "section first in first out, the worksheet's match"
           if challans else f"no challan is recorded for FY {fy_label}, so no deduction is covered")
        + ". NOT DEPOSITED is the tax the register does not cover in a quarter for which at least one challan is recorded; "
        "the tax of a quarter for which NO challan is recorded is shown apart as NOT RECORDED, because the books cannot say "
        "whether it was deposited (a deposit made outside this product, or recorded under another quarter, would change "
        "it): record the challan to have it counted. A challan number typed on a deduction is not read. Whether a deposit "
        "was made on time is not judged here, and a challan paid on any date counts, including one dated before the "
        "deduction (the worksheet judges the date and §201(1A)/§206C(7) interest is in domain/tds/interest.py); whether "
        "this clause counts only deposits made by a stated date is a reading nobody has confirmed from the form's own "
        "text (ledger POST-C-207). Where a row carries surcharge or cess (section 195) the register covers tax, surcharge "
        "and cess together and the tax column is the tax alone, so the split for that section is approximate. Salary tax "
        "(section 192) is deposited from payroll and matched in the 24Q, and is not in this summary. "
        "`register_warnings` lists a challan that paid more than its quarter and section deducted (which is also what a "
        "challan recorded under the wrong quarter looks like) and a challan recorded more than once. The form's own finer "
        "columns — amount on "
        "which tax was required to be deducted against what was actually "
        "deducted, and at the specified rate against a lesser one — need a "
        "per-line comparison against domain/tds/section_rates.py this "
        "summary does not attempt; "
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


class FinalisedNeedsApprover(PermissionError):
    """The checklist is, or would become, `finalised` and the caller may not approve income tax work."""


def save_manual_clauses(db, firm_id: str, client_id: str, financial_year: str,
                        clauses: dict, status: Optional[str] = None, *,
                        may_approve: bool = False) -> dict:
    """Upsert the CA's own answers for clauses this product does not derive.

    RECORDING THE CHECKLIST AS `finalised` IS AN APPROVER'S ACT, like recording a tax audit as completed
    (migration 496) or a return as filed. `may_approve` is the caller's `income_tax:approve`, asked per PERSON
    (`can_user`), and it DEFAULTS TO FALSE so a caller that forgets to ask is refused and not trusted. It is
    needed to give the checklist that status AND to change one that already has it, whatever the new status is:
    an Executive who may write the clauses cannot reopen or rewrite a finalised checklist by saving it as
    `draft`. Nothing reads `status` for a figure today, so no number moves; what the status says is that someone
    who may approve has signed the checklist off.

    `status` None means "do not touch the status": a checklist keeps the one it has (a new one starts as `draft`), so
    saving a clause never silently reopens a finalised checklist. A status is changed only when one is sent.

    `clauses` may name ANY clause code, including a derivable one — the
    caller's value does not win there (`build` above only reads `manual` for
    codes ABSENT from `derived`), so recording a note against clause 18 does
    not shadow the computed §32 figure. That is a deliberate asymmetry from
    `domain/tds/deductor.resolve`'s "caller wins": the derived clauses here are
    figures from the client's own live books, and a stale manual override
    sitting underneath one would go stale the next time a bill was entered.
    """
    existing = (db.table("tax_audit_checklists").select("id, status")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .eq("financial_year", financial_year).limit(1)
                .execute().data or [])
    current = existing[0].get("status") if existing else None
    new_status = status if status is not None else (current or "draft")
    reopen_refusal = ("This Form 3CD checklist is recorded as finalised, so only someone who may approve income tax "
                      "work can change or reopen it.")
    if not may_approve:
        if status == "finalised":
            raise FinalisedNeedsApprover(
                "Only someone who may approve income tax work can record the Form 3CD checklist as finalised.")
        if current == "finalised":
            raise FinalisedNeedsApprover(reopen_refusal)
    # Inline at both calls rather than built once and passed by name: the
    # schema-safety scanner (tests/test_backend_columns_exist_pg.py) reads a
    # write's columns off a literal dict argument, not off whatever a variable
    # happens to be bound to, so a shared `payload` is invisible to it twice.
    if existing:
        write = (db.table("tax_audit_checklists")
                 .update({"firm_id": firm_id, "client_id": client_id,
                          "financial_year": financial_year, "clauses_json": clauses,
                          "status": new_status})
                 .eq("id", existing[0]["id"]))
        if not may_approve:
            # ONE statement, `UPDATE ... WHERE status <> 'finalised'`: the read above and this write are two requests, and
            # an approver can finalise the checklist between them. Without the condition a non-approver's save that read
            # `draft` would overwrite the `finalised` that landed in that gap.
            written = write.neq("status", "finalised").execute().data
            if not written:
                raise FinalisedNeedsApprover(reopen_refusal)
        else:
            write.execute()
    else:
        db.table("tax_audit_checklists").insert(
            {"firm_id": firm_id, "client_id": client_id,
             "financial_year": financial_year, "clauses_json": clauses,
             "status": new_status}).execute()
    return {"firm_id": firm_id, "client_id": client_id,
            "financial_year": financial_year, "clauses_json": clauses,
            "status": new_status}
