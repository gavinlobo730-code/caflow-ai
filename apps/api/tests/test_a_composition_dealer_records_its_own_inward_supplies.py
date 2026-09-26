"""GSTR-4 Annual (GST-25, part 3): Tables 4A-4D, plus Table 5's summation.

`domain/gst/gstr4_annual.py` does not derive Tables 4A-4D from the books — it
CHECKS what a CA records, the same posture `domain/gst/gstr8.py` takes for
GSTR-8 Table 3. Table 5 is the opposite: a pure sum of four already-computed
`compute_cmp08` statements, with nothing left to validate.
"""
from __future__ import annotations

from domain.gst import gstr4_annual as g4


def test_the_module_says_it_is_unverified():
    assert g4.VERIFIED is False


# ── Table 4A / 4B row shape ──────────────────────────────────────────────────

def _b2b_row(**over):
    base = dict(supplier_gstin="27AAAAA0000A1Z5", place_of_supply="27",
               rate_bps=500, taxable_value_paise=10_00_000,
               igst_paise=0, cgst_paise=25_000, sgst_paise=25_000, cess_paise=0)
    base.update(over)
    return g4.SupplyRow(**base)


def test_tax_paise_sums_all_four_heads():
    row = _b2b_row(igst_paise=0, cgst_paise=25_000, sgst_paise=25_000, cess_paise=1_000)
    assert row.tax_paise == 51_000


def test_a_clean_intrastate_4a_row_has_no_findings():
    row = _b2b_row()
    assert g4._b2b_finding("4A", row, filer_state_code="27") is None


def test_cgst_not_equal_sgst_is_a_finding():
    row = _b2b_row(cgst_paise=30_000, sgst_paise=25_000)
    finding = g4._b2b_finding("4A", row, filer_state_code=None)
    assert finding is not None
    assert any("CGST" in p and "SGST" in p for p in finding.problems)


def test_an_interstate_b2b_row_carrying_cgst_sgst_is_a_finding():
    # Supplier in Karnataka (29), place of supply Maharashtra (27) -> inter-State,
    # but the row still carries CGST/SGST instead of IGST.
    row = _b2b_row(supplier_gstin="29BBBBB1111B1Z5", place_of_supply="27",
                   cgst_paise=25_000, sgst_paise=25_000, igst_paise=0)
    finding = g4._b2b_finding("4B", row, filer_state_code=None)
    assert finding is not None
    assert any("inter-State" in p for p in finding.problems)
    assert finding.table == "4B"


def test_an_intrastate_b2b_row_carrying_igst_is_a_finding():
    row = _b2b_row(supplier_gstin="27AAAAA0000A1Z5", place_of_supply="27",
                   igst_paise=50_000, cgst_paise=0, sgst_paise=0)
    finding = g4._b2b_finding("4A", row, filer_state_code=None)
    assert finding is not None
    assert any("intra-State" in p for p in finding.problems)


def test_a_clean_interstate_row_with_igst_alone_has_no_findings():
    row = _b2b_row(supplier_gstin="29BBBBB1111B1Z5", place_of_supply="27",
                   igst_paise=50_000, cgst_paise=0, sgst_paise=0)
    assert g4._b2b_finding("4B", row, filer_state_code=None) is None


def test_a_row_naming_a_state_other_than_the_filers_own_is_a_finding():
    row = _b2b_row(place_of_supply="27")
    finding = g4._b2b_finding("4A", row, filer_state_code="29")
    assert finding is not None
    assert any("not this registration's own state" in p for p in finding.problems)


def test_no_filer_state_check_when_none_is_supplied():
    row = _b2b_row(place_of_supply="27")
    assert g4._b2b_finding("4A", row, filer_state_code=None) is None


# ── Table 4C — unregistered supplier, reverse charge a per-row fact ─────────

def _urp_row(**over):
    base = dict(counterparty_pan="BBBBB1111B", reverse_charge=False,
               place_of_supply="27", supply_type=None, rate_bps=None,
               taxable_value_paise=50_000, igst_paise=0, cgst_paise=0,
               sgst_paise=0, cess_paise=0)
    base.update(over)
    return g4.UnregisteredSupplyRow(**base)


def test_a_non_reverse_charge_urp_row_is_never_checked_for_a_split():
    row = _urp_row(reverse_charge=False, cgst_paise=999, sgst_paise=1)
    assert g4._urp_finding(row, filer_state_code=None) is None


def test_a_reverse_charge_urp_row_with_no_supply_type_names_the_gap():
    row = _urp_row(reverse_charge=True, supply_type=None, rate_bps=500,
                   cgst_paise=25_000, sgst_paise=25_000)
    finding = g4._urp_finding(row, filer_state_code=None)
    assert finding is not None
    assert any("supply type" in p for p in finding.problems)


def test_a_reverse_charge_intrastate_urp_row_with_igst_is_a_finding():
    row = _urp_row(reverse_charge=True, supply_type="Intra-State", rate_bps=500,
                   igst_paise=50_000, cgst_paise=0, sgst_paise=0)
    finding = g4._urp_finding(row, filer_state_code=None)
    assert finding is not None
    assert any("intra-State" in p for p in finding.problems)


def test_a_clean_reverse_charge_urp_row_has_no_findings():
    row = _urp_row(reverse_charge=True, supply_type="Intra-State", rate_bps=500,
                   cgst_paise=25_000, sgst_paise=25_000)
    assert g4._urp_finding(row, filer_state_code="27") is None


def test_urp_finding_names_the_pan_or_a_dash():
    row = _urp_row(counterparty_pan=None, reverse_charge=True,
                   supply_type=None, rate_bps=500)
    finding = g4._urp_finding(row, filer_state_code=None)
    assert finding.identifier == "—"


# ── Table 4D — import of services, no CGST/SGST column at all ──────────────

def _imps_row(**over):
    base = dict(place_of_supply="27", rate_bps=1800, taxable_value_paise=1_00_000,
               igst_paise=18_000, cess_paise=0)
    base.update(over)
    return g4.ImportOfServiceRow(**base)


def test_imps_tax_paise_is_igst_plus_cess_only():
    row = _imps_row(igst_paise=18_000, cess_paise=2_000)
    assert row.tax_paise == 20_000


def test_imps_row_only_checks_the_filer_state():
    row = _imps_row(place_of_supply="29")
    finding = g4._imps_finding(row, filer_state_code="27")
    assert finding is not None
    assert finding.table == "4D"


def test_imps_row_clean_with_no_filer_state_given():
    row = _imps_row()
    assert g4._imps_finding(row, filer_state_code=None) is None


# ── the whole statement — which tables feed the liability ──────────────────

def test_4a_is_never_summed_into_the_liability():
    stmt = g4.compute_gstr4_annual(
        financial_year="2025-26",
        b2b_supplies=[_b2b_row(taxable_value_paise=10_00_000, cgst_paise=25_000,
                               sgst_paise=25_000)],
        b2b_rc_supplies=[], urp_supplies=[], import_of_services=[],
    )
    assert stmt.b2b_total_taxable_paise == 10_00_000
    assert stmt.liability_taxable_paise == 0
    assert stmt.liability_tax_paise == 0


def test_4b_feeds_the_liability():
    stmt = g4.compute_gstr4_annual(
        financial_year="2025-26", b2b_supplies=[],
        b2b_rc_supplies=[_b2b_row(taxable_value_paise=5_00_000, cgst_paise=12_500,
                                  sgst_paise=12_500)],
        urp_supplies=[], import_of_services=[],
    )
    assert stmt.liability_taxable_paise == 5_00_000
    assert stmt.liability_tax_paise == 25_000


def test_only_reverse_charge_urp_rows_feed_the_liability():
    ordinary = _urp_row(reverse_charge=False, taxable_value_paise=1_000)
    rc = _urp_row(reverse_charge=True, supply_type="Intra-State", rate_bps=500,
                 taxable_value_paise=50_000, cgst_paise=2_500, sgst_paise=2_500)
    stmt = g4.compute_gstr4_annual(
        financial_year="2025-26", b2b_supplies=[], b2b_rc_supplies=[],
        urp_supplies=[ordinary, rc], import_of_services=[],
    )
    assert stmt.liability_taxable_paise == 50_000
    assert stmt.liability_tax_paise == 5_000


def test_import_of_services_always_feeds_the_liability():
    stmt = g4.compute_gstr4_annual(
        financial_year="2025-26", b2b_supplies=[], b2b_rc_supplies=[],
        urp_supplies=[], import_of_services=[_imps_row(taxable_value_paise=1_00_000,
                                                       igst_paise=18_000)],
    )
    assert stmt.liability_taxable_paise == 1_00_000
    assert stmt.liability_tax_paise == 18_000


def test_the_statement_names_table_6_and_table_7_as_gaps_always():
    stmt = g4.compute_gstr4_annual(
        financial_year="2025-26", b2b_supplies=[], b2b_rc_supplies=[],
        urp_supplies=[], import_of_services=[],
    )
    assert g4.TABLE_6_OUTWARD_SUMMARY_NOT_BUILT in stmt.gaps
    assert g4.TABLE_7_NOT_BUILT in stmt.gaps


def test_findings_accumulate_across_all_four_tables():
    bad_b2b = _b2b_row(cgst_paise=30_000, sgst_paise=25_000)
    bad_urp = _urp_row(reverse_charge=True, supply_type=None)
    bad_imps = _imps_row(place_of_supply="29")
    stmt = g4.compute_gstr4_annual(
        financial_year="2025-26", b2b_supplies=[bad_b2b],
        b2b_rc_supplies=[], urp_supplies=[bad_urp],
        import_of_services=[bad_imps], filer_state_code="27",
    )
    tables = {f.table for f in stmt.findings}
    assert tables == {"4A", "4C", "4D"}


def test_an_empty_year_answers_zero_rather_than_raising():
    stmt = g4.compute_gstr4_annual(
        financial_year="2025-26", b2b_supplies=[], b2b_rc_supplies=[],
        urp_supplies=[], import_of_services=[],
    )
    assert stmt.b2b_total_taxable_paise == 0
    assert stmt.liability_taxable_paise == 0
    assert stmt.findings == []


# ── Table 5 — four CMP-08 statements, summed ────────────────────────────────

def _cmp08_dict(*, outward_taxable=0, outward_tax=0, inward_taxable=0,
                inward_tax=0, tax_paid=0, interest=0):
    return {
        "outward_supplies": {"taxable_value_paise": outward_taxable,
                             "tax_paise": outward_tax},
        "inward_rcm_supplies": {"taxable_value_paise": inward_taxable,
                                "tax_paise": inward_tax},
        "tax_paid": {"tax_paise": tax_paid},
        "interest_paise": interest,
    }


def test_table_5_sums_four_quarters():
    quarters = [
        _cmp08_dict(outward_taxable=10_00_000, outward_tax=10_000, tax_paid=10_000),
        _cmp08_dict(outward_taxable=12_00_000, outward_tax=12_000, tax_paid=12_000),
        _cmp08_dict(outward_taxable=8_00_000, outward_tax=8_000, tax_paid=8_000),
        _cmp08_dict(outward_taxable=15_00_000, outward_tax=15_000, tax_paid=15_000),
    ]
    table5 = g4.build_table_5("2025-26", quarters)
    assert table5.outward_taxable_paise == 45_00_000
    assert table5.outward_tax_paise == 45_000
    assert table5.tax_paid_paise == 45_000


def test_table_5_sums_inward_rcm_and_interest_too():
    quarters = [
        _cmp08_dict(inward_taxable=1_00_000, inward_tax=18_000, interest=500),
        _cmp08_dict(inward_taxable=2_00_000, inward_tax=36_000, interest=0),
    ]
    table5 = g4.build_table_5("2025-26", quarters)
    assert table5.inward_rcm_taxable_paise == 3_00_000
    assert table5.inward_rcm_tax_paise == 54_000
    assert table5.interest_paise == 500


def test_table_5_names_the_interest_split_gap_only_when_interest_is_nonzero():
    clean = g4.build_table_5("2025-26", [_cmp08_dict(interest=0)])
    assert clean.gaps == []
    with_interest = g4.build_table_5("2025-26", [_cmp08_dict(interest=250)])
    assert any("not split by tax head" in gap for gap in with_interest.gaps)


def test_table_5_handles_fewer_than_four_quarters_without_raising():
    table5 = g4.build_table_5("2025-26", [_cmp08_dict(outward_taxable=1_00_000,
                                                       outward_tax=1_000)])
    assert table5.outward_taxable_paise == 1_00_000


def test_table_5_handles_no_quarters_at_all():
    table5 = g4.build_table_5("2025-26", [])
    assert table5.outward_taxable_paise == 0
    assert table5.gaps == []
