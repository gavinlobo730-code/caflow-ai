"""GSTR-9C (GST-25, part 4): the audited-books reconciliation statement.

`domain/gst/gstr9c.py` does not derive Tables 5, 7, 12A-12C, 14 or 16 from
anything — it reads what a CA records and computes only a plain sum or a
plain subtraction of already-known numbers, reading the "declared" side of
every comparison from the already-built GSTR-9.
"""
from __future__ import annotations

from domain.gst import gstr9c as g9c


def _recon(**over) -> g9c.Reconciliation:
    base = dict(
        financial_year="2025-26", act_name="Companies Act, 2013",
        turnover_per_audited_fs_paise=None, unbilled_revenue_begin_paise=None,
        unadjusted_advances_end_paise=None, deemed_supply_paise=None,
        credit_notes_issued_post_fy_paise=None, trade_discount_not_permissible_paise=None,
        unbilled_revenue_end_paise=None, unadjusted_advances_begin_paise=None,
        credit_notes_in_fs_not_permissible_paise=None, sez_dta_adjustment_paise=None,
        composition_period_turnover_paise=None, section_15_adjustment_paise=None,
        forex_adjustment_paise=None, other_turnover_adjustment_paise=None,
        turnover_after_adjustments_paise=None, turnover_reasons=[],
        exempt_nil_nongst_turnover_paise=None, zero_rated_no_tax_turnover_paise=None,
        reverse_charge_turnover_paise=None, ecommerce_9_5_turnover_paise=None,
        taxable_turnover_after_adjustments_paise=None, taxable_turnover_reasons=[],
        itc_per_audited_fs_paise=None, itc_booked_earlier_fy_claimed_this_fy_paise=None,
        itc_booked_this_fy_claimed_later_fy_paise=None, itc_reasons=[],
        unreconciled_itc_tax_igst_paise=None, unreconciled_itc_tax_cgst_paise=None,
        unreconciled_itc_tax_sgst_paise=None, unreconciled_itc_tax_cess_paise=None,
        unreconciled_itc_interest_paise=None, unreconciled_itc_penalty_paise=None,
        itc_reasons_16=[],
    )
    base.update(over)
    return g9c.Reconciliation(**base)


def _line(table_ref: str, **over) -> g9c.RateWiseLine:
    base = dict(table_ref=table_ref, rate_description="5%", taxable_value_paise=0,
               igst_paise=0, cgst_paise=0, sgst_paise=0, cess_paise=0)
    base.update(over)
    return g9c.RateWiseLine(**base)


def _gstr9_row(code: str, txval=0, igst=0, cgst=0, sgst=0, cess=0) -> dict:
    return {"code": code, "txval_paise": txval, "igst_paise": igst,
           "cgst_paise": cgst, "sgst_paise": sgst, "cess_paise": cess}


def _compute(**over):
    kwargs = dict(financial_year="2025-26", gstin="27AAAAA0000A1Z5",
                 reconciliation=_recon(), rate_wise_lines=[], expense_lines=[],
                 gstr9_tables={})
    kwargs.update(over)
    return g9c.compute_gstr9c(**kwargs)


def test_the_module_says_it_is_unverified():
    assert g9c.VERIFIED is False


def test_threshold_table_is_reference_only_and_never_decides():
    assert len(g9c.THRESHOLD_TABLE) == 3
    assert g9c.THRESHOLD_TABLE[-1]["gstr9c_required"] is True
    assert g9c.THRESHOLD_TABLE[0]["gstr9c_required"] is False


def test_self_certification_from_fy_is_named_and_flagged_unverified():
    assert g9c.SELF_CERTIFICATION_FROM_FY == "2020-21"


# ── Table 5 ───────────────────────────────────────────────────────────────

def test_table5_declared_turnover_reads_gstr9s_own_5n():
    stmt = _compute(gstr9_tables={"5": [_gstr9_row("5N", txval=50_00_000)]})
    assert stmt.table5.declared_turnover_paise == 50_00_000


def test_table5_unreconciled_is_none_when_5p_is_not_recorded():
    stmt = _compute(reconciliation=_recon(turnover_after_adjustments_paise=None),
                    gstr9_tables={"5": [_gstr9_row("5N", txval=50_00_000)]})
    assert stmt.table5.unreconciled_paise is None
    assert g9c.GAP_5P_NOT_RECORDED in stmt.gaps


def test_table5_unreconciled_is_a_plain_subtraction_once_5p_is_recorded():
    stmt = _compute(reconciliation=_recon(turnover_after_adjustments_paise=55_00_000),
                    gstr9_tables={"5": [_gstr9_row("5N", txval=50_00_000)]})
    assert stmt.table5.unreconciled_paise == 5_00_000
    assert g9c.GAP_5P_NOT_RECORDED not in stmt.gaps


def test_table5_adjustments_total_sums_5b_through_5o_when_all_present():
    stmt = _compute(reconciliation=_recon(
        unbilled_revenue_begin_paise=1_000, unadjusted_advances_end_paise=2_000,
        deemed_supply_paise=0, credit_notes_issued_post_fy_paise=0,
        trade_discount_not_permissible_paise=0, unbilled_revenue_end_paise=0,
        unadjusted_advances_begin_paise=0, credit_notes_in_fs_not_permissible_paise=0,
        sez_dta_adjustment_paise=0, composition_period_turnover_paise=0,
        section_15_adjustment_paise=0, forex_adjustment_paise=0,
        other_turnover_adjustment_paise=0,
    ))
    assert stmt.table5.adjustments_total_paise == 3_000


def test_table5_adjustments_total_sums_only_the_lines_recorded_so_far():
    # Informational only — it is never used to derive 5P, which stays refused
    # (test_table5_unreconciled_is_none_when_5p_is_not_recorded) whatever
    # partial total this shows.
    stmt = _compute(reconciliation=_recon(unbilled_revenue_begin_paise=1_000))
    assert stmt.table5.adjustments_total_paise == 1_000


def test_table5_adjustments_total_is_none_when_nothing_at_all_is_recorded():
    stmt = _compute(reconciliation=_recon())
    assert stmt.table5.adjustments_total_paise is None


# ── Table 7 ───────────────────────────────────────────────────────────────

def test_table7_declared_reads_gstr9s_own_4n():
    stmt = _compute(gstr9_tables={"4": [_gstr9_row("4N", txval=40_00_000)]})
    assert stmt.table7.declared_taxable_turnover_paise == 40_00_000


def test_table7_unreconciled_is_none_without_7e():
    stmt = _compute()
    assert stmt.table7.unreconciled_paise is None
    assert g9c.GAP_7E_NOT_RECORDED in stmt.gaps


def test_table7_unreconciled_is_a_plain_subtraction_once_7e_is_recorded():
    stmt = _compute(reconciliation=_recon(taxable_turnover_after_adjustments_paise=42_00_000),
                    gstr9_tables={"4": [_gstr9_row("4N", txval=40_00_000)]})
    assert stmt.table7.unreconciled_paise == 2_00_000


# ── Table 9 ───────────────────────────────────────────────────────────────

def test_table9_sums_only_its_own_table_ref():
    lines = [_line("9", taxable_value_paise=10_00_000, cgst_paise=25_000, sgst_paise=25_000),
            _line("11", taxable_value_paise=999)]
    stmt = _compute(rate_wise_lines=lines)
    assert stmt.table9.total_payable_paise["taxable_value_paise"] == 10_00_000
    assert stmt.table9.total_payable_paise["cgst_paise"] == 25_000
    assert len(stmt.table9.lines) == 1


def test_table9_declared_tax_paid_reads_9d():
    stmt = _compute(gstr9_tables={"9": [
        _gstr9_row("9a", txval=1_00_000), _gstr9_row("9b", txval=40_000),
        _gstr9_row("9c", txval=60_000), _gstr9_row("9d", txval=60_000),
    ]})
    assert stmt.table9.declared_tax_paid_paise == 60_000
    assert stmt.table9.declared["9a"] == 1_00_000
    assert g9c.GAP_DECLARED_PAID_BINDING in stmt.gaps


# ── Table 11 ──────────────────────────────────────────────────────────────

def test_table11_sums_only_its_own_table_ref():
    lines = [_line("11", igst_paise=5_000), _line("9", igst_paise=999),
            _line("partv", igst_paise=999)]
    stmt = _compute(rate_wise_lines=lines)
    assert stmt.table11.total_paise["igst_paise"] == 5_000
    assert len(stmt.table11.lines) == 1


# ── Part V ────────────────────────────────────────────────────────────────

def test_part_v_sums_only_its_own_table_ref():
    lines = [_line("partv", cess_paise=100), _line("9", cess_paise=999)]
    stmt = _compute(rate_wise_lines=lines)
    assert stmt.part_v.total_paise["cess_paise"] == 100
    assert len(stmt.part_v.lines) == 1


# ── Table 12 ──────────────────────────────────────────────────────────────

def test_table12d_needs_all_three_legs_together():
    stmt = _compute(reconciliation=_recon(itc_per_audited_fs_paise=10_00_000,
                                          itc_booked_earlier_fy_claimed_this_fy_paise=1_00_000))
    assert stmt.table12.audited_adjusted_paise is None


def test_table12d_is_a_plus_b_minus_c_once_all_three_are_recorded():
    stmt = _compute(reconciliation=_recon(
        itc_per_audited_fs_paise=10_00_000,
        itc_booked_earlier_fy_claimed_this_fy_paise=1_00_000,
        itc_booked_this_fy_claimed_later_fy_paise=50_000,
    ))
    assert stmt.table12.audited_adjusted_paise == 10_50_000


def test_table12e_reads_gstr9s_own_6o_not_7j():
    stmt = _compute(gstr9_tables={
        "6": [_gstr9_row("6O", igst=1_000, cgst=2_000, sgst=2_000, cess=0)],
        "7": [_gstr9_row("7J", txval=3_999)],
    })
    assert stmt.table12.itc_claim_paise == 5_000
    assert stmt.table12.itc_claim_alternate_paise == 3_999
    assert g9c.GAP_ITC_CLAIM_BINDING in stmt.gaps


def test_table12f_is_none_until_12d_is_known():
    stmt = _compute(reconciliation=_recon(itc_per_audited_fs_paise=10_00_000))
    assert stmt.table12.unreconciled_paise is None


def test_table12f_is_a_plain_subtraction_once_12d_is_known():
    stmt = _compute(
        reconciliation=_recon(itc_per_audited_fs_paise=10_00_000,
                              itc_booked_earlier_fy_claimed_this_fy_paise=0,
                              itc_booked_this_fy_claimed_later_fy_paise=0),
        gstr9_tables={"6": [_gstr9_row("6O", igst=9_00_000)]},
    )
    assert stmt.table12.audited_adjusted_paise == 10_00_000
    assert stmt.table12.unreconciled_paise == 1_00_000


# ── Table 14 ──────────────────────────────────────────────────────────────

def test_table14_sums_only_what_was_typed():
    lines = [g9c.ExpenseLine(expense_head="Purchases", value_paise=1_00_000,
                             total_itc_paise=18_000, eligible_itc_availed_paise=18_000),
            g9c.ExpenseLine(expense_head="Freight", value_paise=10_000,
                            total_itc_paise=1_800, eligible_itc_availed_paise=1_500)]
    stmt = _compute(expense_lines=lines,
                    gstr9_tables={"6": [_gstr9_row("6O", igst=19_500)]})
    assert stmt.table14.total_value_paise == 1_10_000
    assert stmt.table14.total_eligible_itc_availed_paise == 19_500
    assert stmt.table14.unreconciled_paise == 0
    assert g9c.GAP_TABLE_14_NOT_BUILT in stmt.gaps


def test_table14_with_no_lines_answers_zero_rather_than_raising():
    stmt = _compute()
    assert stmt.table14.total_value_paise == 0
    assert stmt.table14.total_eligible_itc_availed_paise == 0


# ── Table 16 ──────────────────────────────────────────────────────────────

def test_table16_is_a_pure_passthrough_no_derivation():
    stmt = _compute(reconciliation=_recon(unreconciled_itc_tax_igst_paise=1_000,
                                          unreconciled_itc_interest_paise=50))
    assert stmt.table16.tax_igst_paise == 1_000
    assert stmt.table16.interest_paise == 50
    assert stmt.table16.tax_cgst_paise is None


# ── gaps ──────────────────────────────────────────────────────────────────

def test_multi_gstin_names_the_apportionment_gap_only_when_asked():
    assert g9c.GAP_MULTI_GSTIN_APPORTIONMENT not in _compute(multi_gstin_client=False).gaps
    assert g9c.GAP_MULTI_GSTIN_APPORTIONMENT in _compute(multi_gstin_client=True).gaps


def test_ecommerce_row_gap_names_itself_only_for_the_later_years():
    assert g9c.GAP_ECOMMERCE_ROW not in _compute(is_ecommerce_year=False).gaps
    assert g9c.GAP_ECOMMERCE_ROW in _compute(is_ecommerce_year=True).gaps


def test_the_two_bindings_are_always_named():
    stmt = _compute()
    assert g9c.GAP_ITC_CLAIM_BINDING in stmt.gaps
    assert g9c.GAP_DECLARED_PAID_BINDING in stmt.gaps


def test_an_empty_statement_answers_zero_rather_than_raising():
    stmt = _compute()
    assert stmt.table9.total_payable_paise["taxable_value_paise"] == 0
    assert stmt.table11.total_paise["igst_paise"] == 0
    assert stmt.part_v.total_paise["cess_paise"] == 0
    assert stmt.table5.declared_turnover_paise == 0
