"""GSTR-9C — the audited-books reconciliation statement (GST-25, part 4).

CGST Act s.44 with Rule 80(3): a registered person whose turnover crosses the
notified threshold reconciles the annual return (GSTR-9) against its own
AUDITED FINANCIAL STATEMENTS and files FORM GSTR-9C. GSTR-9 (GST-10) is
already built; this is the reconciliation on top of it.

WHY THIS MODULE COMPUTES SO LITTLE, ON PURPOSE
    Almost every figure GSTR-9C asks for is a fact ONLY the audited financial
    statements and the CA's own working papers carry — an unbilled-revenue
    movement, a SEZ-to-DTA adjustment, a foreign-exchange reconciling item —
    which this product's books do not model as distinguishable figures at
    all. So, the same posture `domain/gst/gstr8.py` takes for GSTR-8 Table 3:
    this module does not derive Tables 5, 7, 12A-12C, 14 or 16 from anything.
    It reads what a CA records (`gstr9c_reconciliations` and its two child
    tables, migration 423), computes the handful of figures that are a PLAIN
    SUM or a PLAIN SUBTRACTION of already-known numbers, and reads the
    "declared" side of every comparison from the GSTR-9 this product already
    built (`domain/gst/gstr9_builder.py`) rather than a second, independent
    read of the filed returns.

WHAT IS DERIVED, AND WHY EACH ONE IS SAFE
    - Table 9's own total payable, and Table 11's own total: a RATE-WISE ARRAY
      SUMMED WITH ITS OWN TAIL ROWS (interest/late fee/penalty/other) — the
      offline utility's VBA has no cross-table arithmetic anywhere (confirmed
      by a full grep of all five source files for "Sum"/"foot"/"must equal" —
      there is none), but a table's own total being the sum of its own rows
      is not an assumption about a SIGN, it is the definition of "total."
    - Table 12D ("ITC availed as per audited financial statements/books") is
      12A + 12B − 12C — the addition the row's OWN LABEL states (A+B−C is
      recorded in the offline utility's own row order, not invented here),
      carried with a caveat rather than treated as `[P]`-graded, since the
      exact formula is not literally present as VBA arithmetic (the workbook
      reads a cell value, which may itself be an Excel formula this
      extraction cannot see).
    - Table 12F / 14T / 9's "un-reconciled" rows: a PLAIN SUBTRACTION of two
      already-resolved figures (declared minus audited, or payable minus
      paid) — safe once both sides are known, which is a different claim
      from summing 5B-5O with an unconfirmed sign per line (5P, 7E — see
      below).

WHAT IS DELIBERATELY NEVER DERIVED, AND REFUSED RATHER THAN GUESSED
    - Table 5P ("turnover after adjustments") and Table 7E (its taxable-
      turnover twin): each is 5A/7A plus a SIGNED sum of up to a dozen
      reconciling lines, and which of 5B-5O add and which subtract is not
      textual content of the VBA (it reads a cell value). Guessing a sign on
      money a client reconciles against its own audited accounts is exactly
      the "never guess a statutory sign" rule INV-05/migration 210's
      credit-note asymmetry is the precedent for. `turnover_after_
      adjustments_paise` / `taxable_turnover_after_adjustments_paise` are
      CA-typed columns for exactly this reason, and 5R/7G are computed ONLY
      once the CA has supplied that one summary figure themselves.
    - Table 14's per-expense-head figures: this product's chart of accounts
      classifies for Schedule III captions, not GSTR-9C's 26 expense-head
      categories, so nothing here maps a purchase bill or a ledger account
      onto "Power & Fuel" versus "Other Misc. Expenses." `expense_totals`
      sums only what a CA has typed — a safe sum of CA-entered numbers, never
      a classification this module invents.
    - Multi-GSTIN apportionment of PAN-level audited turnover: GST-20 already
      established that one client may hold several GSTINs, and the audited
      financial statements are prepared at the PAN level. No statutory
      formula apportions the one figure across several registrations' 5A —
      it is a CA judgement every time, named as a gap rather than split by an
      invented "reasonable basis."

TWO BINDINGS TO THE DECLARED SIDE ARE `[S]`-GRADED ASSUMPTIONS, NOT CONFIRMED
FORM INSTRUCTIONS, AND ARE NAMED AS SUCH ON EVERY STATEMENT THAT USES THEM
    - `itc_claim_paise` (Table 12E / 14S, "ITC claimed per Annual Return")
      reads GSTR-9's own Table 6O ("Total ITC availed"). The alternative
      candidate, Table 7J ("Net ITC available for utilisation"), is also
      served on the statement so a CA can see both and pick the one their own
      copy of the form asks for.
    - `declared_tax_paid_paise` (Table 9's own "amount paid as declared in
      Annual Return") reads GSTR-9's Table 9 row `9d` ("Paid in cash"). GSTR-9
      table 9 rows 9a-9d are a single aggregate figure each (liability / ITC
      / net / cash) rather than rate-wise or per-head, which this product's
      GSTR-9 builder does not compute any other way — so this binding is the
      closest single figure available, not a confirmed match to the notified
      form's own row.
    Neither binding changes the underlying GSTR-9 figures; both are pinned
    exactly by tests so a future correction is a one-line diff.

THE ONE THING THIS MODULE MUST NEVER DO: DECIDE ELIGIBILITY
    `THRESHOLD_TABLE` is reference data for display only, following exactly
    the posture `services/filing_demo/gstr9.py` already takes for the same
    figures — a CA reads it, this module never places a client in a band.
    CGST §2(6) aggregate turnover is PAN-level and all-India (migration 401),
    so no figure derivable from one registration's own returns could decide
    it safely, and getting eligibility wrong either direction is a mis-filed
    return, not a rounding.

    ⚠️ EVERY THRESHOLD FIGURE, AND THE READING THAT SELF-CERTIFICATION IS
    PERMANENT FROM FY 2020-21, ARE `[S]`-GRADED. Egress to every `.gov.in` is
    refused at this environment's proxy. The self-certification reading is
    corroborated directly from the offline utility's own VBA — its
    `PARTB_RESTRICTED_FY` list omits `isauditor` and the whole Part B/Part V
    signature block from the JSON for exactly FY 2020-21 through 2024-25 —
    but the same workbook's FY list does not extend to FY 2025-26 onward
    either, and this module treats that as the workbook's own list being
    unmaintained rather than as evidence CA/CMA certification is returning
    (see the module's own test file for both readings). `VERIFIED = False`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

VERIFIED = False

#: [S]-graded — see the module docstring. Reference only; never used to place
#: a client in a band. CGST §2(6) aggregate turnover, PAN-level and
#: all-India, is the figure that actually decides this.
THRESHOLD_TABLE = (
    {"up_to_paise": 2_00_00_000_00, "gstr9_required": False, "gstr9c_required": False,
     "label": "Up to ₹2 crore — GSTR-9 optional, no GSTR-9C"},
    {"up_to_paise": 5_00_00_000_00, "gstr9_required": True, "gstr9c_required": False,
     "label": "Above ₹2 crore up to ₹5 crore — GSTR-9 mandatory, no GSTR-9C"},
    {"up_to_paise": None, "gstr9_required": True, "gstr9c_required": True,
     "label": "Above ₹5 crore — GSTR-9 and GSTR-9C, self-certified"},
)

#: [S]-graded, corroborated directly from the offline utility's own VBA (see
#: the module docstring) — the Finance Act 2021 removed CA/CMA certification
#: from FY 2020-21 onward, and this workbook's current-version export writes
#: no certification concept whatsoever for that year and every one after it
#: up to its own FY list. Treated as the permanent, current-law position.
SELF_CERTIFICATION_FROM_FY = "2020-21"

#: [S]-graded — see the module docstring's "two bindings" section.
ITC_CLAIM_BINDING_ROW = "6O"          # "Total ITC availed" — Table 12E / 14S
DECLARED_TAX_PAID_BINDING_ROW = "9d"  # "Paid in cash" — Table 9's declared side

GAP_5P_NOT_RECORDED = (
    "Turnover after adjustments (5P) is not recorded, so the un-reconciled "
    "turnover (5R) cannot be computed. 5P is CA-entered because the "
    "addition/subtraction sign of each of 5B-5O is not confirmed from any "
    "primary source available here — see domain/gst/gstr9c.py.")
GAP_7E_NOT_RECORDED = (
    "Taxable turnover after adjustments (7E) is not recorded, so the "
    "un-reconciled taxable turnover (7G) cannot be computed. Same reason "
    "as 5P.")
GAP_ECOMMERCE_ROW = (
    "This financial year's schema (FY 2024-25 onward) adds an e-commerce "
    "operator row to Tables 7, 9 and 11 (CGST s.9(5)) that this product "
    "cannot compute: nothing here marks a supply as made through an "
    "e-commerce operator, the same gap already named for GSTR-3B Table "
    "3.1.1. Record it directly on the portal's own form.")
GAP_TABLE_14_NOT_BUILT = (
    "Table 14's per-expense-head ITC reconciliation has no auto-fill: this "
    "product's chart of accounts classifies for Schedule III captions, not "
    "GSTR-9C's 26 expense-head categories. Record each expense head "
    "directly; only the totals of what is recorded are summed here.")
GAP_MULTI_GSTIN_APPORTIONMENT = (
    "This client holds more than one GST registration. The audited "
    "financial statements are prepared at the PAN level, and no statutory "
    "formula apportions Table 5A's turnover across several GSTINs — record "
    "this registration's own share directly.")
GAP_ITC_CLAIM_BINDING = (
    f"ITC claimed per Annual Return (12E/14S) is read from GSTR-9 Table "
    f"{ITC_CLAIM_BINDING_ROW} (\"Total ITC availed\") — an [S]-graded "
    f"assumption, not a confirmed form instruction. Table 7J (\"Net ITC "
    f"available for utilisation\") is served alongside for comparison.")
GAP_DECLARED_PAID_BINDING = (
    f"Amount paid as declared in the Annual Return (Table 9's own declared "
    f"side) is read from GSTR-9 Table 9 row {DECLARED_TAX_PAID_BINDING_ROW} "
    f"(\"Paid in cash\") — an [S]-graded assumption. GSTR-9's own Table 9 "
    f"carries no rate-wise or per-head split to compare against more "
    f"precisely.")


@dataclass(frozen=True)
class RateWiseLine:
    """One row of Table 9, Table 11 or Part V's rate-wise array."""
    table_ref: str   # "9" | "11" | "partv"
    rate_description: str
    taxable_value_paise: int
    igst_paise: int
    cgst_paise: int
    sgst_paise: int
    cess_paise: int

    @property
    def tax_paise(self) -> int:
        return self.igst_paise + self.cgst_paise + self.sgst_paise + self.cess_paise


@dataclass(frozen=True)
class ExpenseLine:
    """One row of Table 14's expense-head array."""
    expense_head: str
    value_paise: int
    total_itc_paise: int
    eligible_itc_availed_paise: int


@dataclass(frozen=True)
class Reconciliation:
    """The CA-recorded figures — one `gstr9c_reconciliations` row."""
    financial_year: str
    act_name: Optional[str]
    # Table 5
    turnover_per_audited_fs_paise: Optional[int]           # 5A
    unbilled_revenue_begin_paise: Optional[int]             # 5B
    unadjusted_advances_end_paise: Optional[int]             # 5C
    deemed_supply_paise: Optional[int]                       # 5D
    credit_notes_issued_post_fy_paise: Optional[int]         # 5E
    trade_discount_not_permissible_paise: Optional[int]      # 5F
    unbilled_revenue_end_paise: Optional[int]                # 5H
    unadjusted_advances_begin_paise: Optional[int]            # 5I
    credit_notes_in_fs_not_permissible_paise: Optional[int]  # 5J
    sez_dta_adjustment_paise: Optional[int]                  # 5K
    composition_period_turnover_paise: Optional[int]         # 5L
    section_15_adjustment_paise: Optional[int]               # 5M
    forex_adjustment_paise: Optional[int]                    # 5N
    other_turnover_adjustment_paise: Optional[int]           # 5O
    turnover_after_adjustments_paise: Optional[int]          # 5P — CA-typed
    turnover_reasons: list[str]
    # Table 7
    exempt_nil_nongst_turnover_paise: Optional[int]          # 7B
    zero_rated_no_tax_turnover_paise: Optional[int]          # 7C
    reverse_charge_turnover_paise: Optional[int]             # 7D
    ecommerce_9_5_turnover_paise: Optional[int]               # 7D(ecom)
    taxable_turnover_after_adjustments_paise: Optional[int]  # 7E — CA-typed
    taxable_turnover_reasons: list[str]
    # Table 12
    itc_per_audited_fs_paise: Optional[int]                        # 12A
    itc_booked_earlier_fy_claimed_this_fy_paise: Optional[int]     # 12B
    itc_booked_this_fy_claimed_later_fy_paise: Optional[int]       # 12C
    itc_reasons: list[str]
    # Table 16
    unreconciled_itc_tax_igst_paise: Optional[int]
    unreconciled_itc_tax_cgst_paise: Optional[int]
    unreconciled_itc_tax_sgst_paise: Optional[int]
    unreconciled_itc_tax_cess_paise: Optional[int]
    unreconciled_itc_interest_paise: Optional[int]
    unreconciled_itc_penalty_paise: Optional[int]
    itc_reasons_16: list[str]


@dataclass(frozen=True)
class Table5:
    audited_turnover_paise: Optional[int]      # 5A
    #: Sum of whichever of 5B-5O the CA has recorded so far, informational
    #: only — None once nothing at all is recorded. NEVER used to derive 5P;
    #: that stays refused whatever this partial total shows (see 5P below).
    adjustments_total_paise: Optional[int]
    turnover_after_adjustments_paise: Optional[int]  # 5P, CA-typed
    declared_turnover_paise: int                # 5Q, from GSTR-9's own 5N
    unreconciled_paise: Optional[int]           # 5R = 5P - 5Q, only if 5P is known


@dataclass(frozen=True)
class Table7:
    taxable_turnover_after_adjustments_paise: Optional[int]  # 7E, CA-typed
    declared_taxable_turnover_paise: int         # 7F, from GSTR-9's own 4N
    unreconciled_paise: Optional[int]            # 7G = 7E - 7F


@dataclass(frozen=True)
class Table9:
    lines: list[RateWiseLine]
    total_payable_paise: dict[str, int]         # summed igst/cgst/sgst/cess + taxable
    declared: dict[str, int]                    # GSTR-9's own 9a-9d, txval each
    declared_tax_paid_paise: int                # [S]-graded binding — see docstring


@dataclass(frozen=True)
class Table11:
    lines: list[RateWiseLine]
    total_paise: dict[str, int]


@dataclass(frozen=True)
class Table12:
    itc_per_audited_fs_paise: Optional[int]     # 12A
    booked_earlier_claimed_this_fy_paise: Optional[int]  # 12B
    booked_this_fy_claimed_later_fy_paise: Optional[int]  # 12C
    audited_adjusted_paise: Optional[int]       # 12D = 12A + 12B - 12C
    itc_claim_paise: int                        # 12E, [S]-graded binding
    itc_claim_alternate_paise: int              # Table 7J, for comparison
    unreconciled_paise: Optional[int]           # 12F = 12D - 12E


@dataclass(frozen=True)
class Table14:
    lines: list[ExpenseLine]
    total_value_paise: int
    total_itc_paise: int
    total_eligible_itc_availed_paise: int       # 14R
    itc_claim_paise: int                        # 14S, same binding as 12E
    unreconciled_paise: int                     # 14T = 14R - 14S


@dataclass(frozen=True)
class Table16:
    tax_igst_paise: Optional[int]
    tax_cgst_paise: Optional[int]
    tax_sgst_paise: Optional[int]
    tax_cess_paise: Optional[int]
    interest_paise: Optional[int]
    penalty_paise: Optional[int]


@dataclass(frozen=True)
class PartV:
    lines: list[RateWiseLine]
    total_paise: dict[str, int]


@dataclass(frozen=True)
class Gstr9cStatement:
    financial_year: str
    gstin: str
    table5: Table5
    table7: Table7
    table9: Table9
    table11: Table11
    table12: Table12
    table14: Table14
    table16: Table16
    part_v: PartV
    gaps: list[str]


def _rate_wise_total(lines: list[RateWiseLine]) -> dict[str, int]:
    total = {"taxable_value_paise": 0, "igst_paise": 0, "cgst_paise": 0,
             "sgst_paise": 0, "cess_paise": 0}
    for line in lines:
        total["taxable_value_paise"] += line.taxable_value_paise
        total["igst_paise"] += line.igst_paise
        total["cgst_paise"] += line.cgst_paise
        total["sgst_paise"] += line.sgst_paise
        total["cess_paise"] += line.cess_paise
    return total


def _row(tables: dict, table_no: str, code: str) -> dict:
    for row in tables.get(table_no) or []:
        if row.get("code") == code:
            return row
    return {}


def compute_gstr9c(*, financial_year: str, gstin: str,
                   reconciliation: Reconciliation,
                   rate_wise_lines: list[RateWiseLine],
                   expense_lines: list[ExpenseLine],
                   gstr9_tables: dict,
                   multi_gstin_client: bool = False,
                   is_ecommerce_year: bool = False) -> Gstr9cStatement:
    """The reconciliation statement for one registration, one financial year.

    `gstr9_tables` is `GSTR9.as_dict()["tables"]` (or `gstr9_service.build()`'s
    own `"tables"` key) for the SAME financial_year/gstin — the declared side
    of every comparison below is read from it, never re-derived.

    `multi_gstin_client` names GAP_MULTI_GSTIN_APPORTIONMENT when the client
    holds more than one registration (GST-20) — the caller resolves this from
    `client_gst_registration_service.listing`, not this module, which has no
    database handle.

    `is_ecommerce_year` gates GAP_ECOMMERCE_ROW — true from FY 2024-25 onward
    per the offline utility's own schema fork (`rev_sup_ecom`/`oth_ecom`).
    """
    gaps: list[str] = []
    if multi_gstin_client:
        gaps.append(GAP_MULTI_GSTIN_APPORTIONMENT)
    if is_ecommerce_year:
        gaps.append(GAP_ECOMMERCE_ROW)
    gaps.append(GAP_ITC_CLAIM_BINDING)
    gaps.append(GAP_DECLARED_PAID_BINDING)
    gaps.append(GAP_TABLE_14_NOT_BUILT)

    r = reconciliation

    # ── Table 5 ──────────────────────────────────────────────────────────
    adjustments = [r.unbilled_revenue_begin_paise, r.unadjusted_advances_end_paise,
                  r.deemed_supply_paise, r.credit_notes_issued_post_fy_paise,
                  r.trade_discount_not_permissible_paise, r.unbilled_revenue_end_paise,
                  r.unadjusted_advances_begin_paise,
                  r.credit_notes_in_fs_not_permissible_paise, r.sez_dta_adjustment_paise,
                  r.composition_period_turnover_paise, r.section_15_adjustment_paise,
                  r.forex_adjustment_paise, r.other_turnover_adjustment_paise]
    adjustments_total = sum(a for a in adjustments if a is not None) or None
    declared_turnover = int(_row(gstr9_tables, "5", "5N").get("txval_paise") or 0)
    table5_unrec = (None if r.turnover_after_adjustments_paise is None
                   else r.turnover_after_adjustments_paise - declared_turnover)
    if r.turnover_after_adjustments_paise is None:
        gaps.append(GAP_5P_NOT_RECORDED)
    table5 = Table5(
        audited_turnover_paise=r.turnover_per_audited_fs_paise,
        adjustments_total_paise=adjustments_total,
        turnover_after_adjustments_paise=r.turnover_after_adjustments_paise,
        declared_turnover_paise=declared_turnover,
        unreconciled_paise=table5_unrec,
    )

    # ── Table 7 ──────────────────────────────────────────────────────────
    declared_taxable_turnover = int(_row(gstr9_tables, "4", "4N").get("txval_paise") or 0)
    table7_unrec = (None if r.taxable_turnover_after_adjustments_paise is None
                    else r.taxable_turnover_after_adjustments_paise - declared_taxable_turnover)
    if r.taxable_turnover_after_adjustments_paise is None:
        gaps.append(GAP_7E_NOT_RECORDED)
    table7 = Table7(
        taxable_turnover_after_adjustments_paise=r.taxable_turnover_after_adjustments_paise,
        declared_taxable_turnover_paise=declared_taxable_turnover,
        unreconciled_paise=table7_unrec,
    )

    # ── Table 9 ──────────────────────────────────────────────────────────
    table9_lines = [l for l in rate_wise_lines if l.table_ref == "9"]
    table9_total = _rate_wise_total(table9_lines)
    declared_9 = {row.get("code"): int(row.get("txval_paise") or 0)
                 for row in (gstr9_tables.get("9") or [])}
    declared_paid = int(_row(gstr9_tables, "9", DECLARED_TAX_PAID_BINDING_ROW)
                        .get("txval_paise") or 0)
    table9 = Table9(lines=table9_lines, total_payable_paise=table9_total,
                    declared=declared_9, declared_tax_paid_paise=declared_paid)

    # ── Table 11 ─────────────────────────────────────────────────────────
    table11_lines = [l for l in rate_wise_lines if l.table_ref == "11"]
    table11 = Table11(lines=table11_lines, total_paise=_rate_wise_total(table11_lines))

    # ── Table 12 ─────────────────────────────────────────────────────────
    # 12D = 12A + 12B - 12C, and ALL THREE are required together: a formula
    # with one leg missing is not a smaller formula, it is an unanswered one.
    if None in (r.itc_per_audited_fs_paise, r.itc_booked_earlier_fy_claimed_this_fy_paise,
               r.itc_booked_this_fy_claimed_later_fy_paise):
        audited_adjusted = None
    else:
        audited_adjusted = (r.itc_per_audited_fs_paise
                            + r.itc_booked_earlier_fy_claimed_this_fy_paise
                            - r.itc_booked_this_fy_claimed_later_fy_paise)
    itc_claim = sum(int(_row(gstr9_tables, "6", ITC_CLAIM_BINDING_ROW).get(k) or 0)
                    for k in ("igst_paise", "cgst_paise", "sgst_paise", "cess_paise"))
    itc_claim_alt = int(_row(gstr9_tables, "7", "7J").get("txval_paise") or 0)
    table12_unrec = (None if audited_adjusted is None else audited_adjusted - itc_claim)
    table12 = Table12(
        itc_per_audited_fs_paise=r.itc_per_audited_fs_paise,
        booked_earlier_claimed_this_fy_paise=r.itc_booked_earlier_fy_claimed_this_fy_paise,
        booked_this_fy_claimed_later_fy_paise=r.itc_booked_this_fy_claimed_later_fy_paise,
        audited_adjusted_paise=audited_adjusted,
        itc_claim_paise=itc_claim,
        itc_claim_alternate_paise=itc_claim_alt,
        unreconciled_paise=table12_unrec,
    )

    # ── Table 14 ─────────────────────────────────────────────────────────
    total_value = sum(l.value_paise for l in expense_lines)
    total_itc = sum(l.total_itc_paise for l in expense_lines)
    total_eligible = sum(l.eligible_itc_availed_paise for l in expense_lines)
    table14 = Table14(
        lines=expense_lines, total_value_paise=total_value,
        total_itc_paise=total_itc, total_eligible_itc_availed_paise=total_eligible,
        itc_claim_paise=itc_claim, unreconciled_paise=total_eligible - itc_claim,
    )

    # ── Table 16 ─────────────────────────────────────────────────────────
    table16 = Table16(
        tax_igst_paise=r.unreconciled_itc_tax_igst_paise,
        tax_cgst_paise=r.unreconciled_itc_tax_cgst_paise,
        tax_sgst_paise=r.unreconciled_itc_tax_sgst_paise,
        tax_cess_paise=r.unreconciled_itc_tax_cess_paise,
        interest_paise=r.unreconciled_itc_interest_paise,
        penalty_paise=r.unreconciled_itc_penalty_paise,
    )

    # ── Part V ───────────────────────────────────────────────────────────
    partv_lines = [l for l in rate_wise_lines if l.table_ref == "partv"]
    part_v = PartV(lines=partv_lines, total_paise=_rate_wise_total(partv_lines))

    return Gstr9cStatement(
        financial_year=financial_year, gstin=gstin,
        table5=table5, table7=table7, table9=table9, table11=table11,
        table12=table12, table14=table14, table16=table16, part_v=part_v,
        gaps=gaps,
    )
