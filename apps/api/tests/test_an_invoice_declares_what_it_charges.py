"""Two ways an invoice could be issued that GSTR-1 would later refuse.

SALES-16 — WHAT THE INVOICE SAYS vs WHAT IT CHARGES.
    `_create_invoice_core` computed GST from `gst_rate_bps` and `is_interstate`
    alone. `supply_type` and `is_reverse_charge` were stored and never
    consulted, so a CA could tick "Exempt" — or "Reverse charge" — and leave the
    lines at 18%. The ledger then charged the tax while
    `gstr1_builder._build_nil_exempt` reported a value-only nil supply, or a
    B2B row went out with `rchrg: "Y"` telling the portal the RECIPIENT owes
    tax the supplier had already collected. The books and the return differed
    by the whole amount and nothing said so.

SALES-29 — NO PLACE OF SUPPLY.
    `supply_state_code` fell through to `""`, was written unvalidated, and first
    became an error when the return was built — `domain/gst/validator` rejects
    anything outside VALID_STATE_CODES. So invoices went out all quarter and the
    CA met the list on the 10th of the following month, by which time each was
    issued, posted and sent, and correcting one is a §34 credit note rather than
    an edit.

Both are now refused where the document becomes a tax invoice, and both have a
lawful DEFAULT before the refusal — which is the half that makes the refusal
usable rather than a wall.
"""
from __future__ import annotations

import pytest

from domain.gst.supply_classification import UNTAXED_SUPPLY_TYPES, tax_conflict


# ── SALES-16: the classification and the tax ─────────────────────────────────

@pytest.mark.parametrize("stype", sorted(UNTAXED_SUPPLY_TYPES))
def test_an_untaxed_supply_carrying_tax_is_refused(stype):
    """§2(47) (exempt / nil-rated) and §2(78) (non-taxable): no tax is
    chargeable, so tax on the lines contradicts the document's own words."""
    why = tax_conflict(supply_type=stype, is_reverse_charge=False,
                       cgst_paise=9_000_00, sgst_paise=9_000_00)
    assert why and "18,000.00" in why, why


def test_reverse_charge_carrying_tax_is_refused():
    """§9(3)/(4) shift the liability to the RECIPIENT and Rule 46(p) has the
    invoice say so. A supplier who also charges the tax has collected money the
    customer is separately being told to pay to the government."""
    why = tax_conflict(supply_type="taxable", is_reverse_charge=True,
                       igst_paise=18_000_00)
    assert why and "§9(3)/(4)" in why, why


def test_a_zero_rated_supply_carrying_igst_is_allowed():
    """THE ONE THAT MUST NOT BE REFUSED. §16(3) gives an exporter or SEZ
    supplier a CHOICE: under an LUT or bond, charge nothing (§16(3)(a)); or
    supply ON PAYMENT of IGST and reclaim it under §54 (§16(3)(b)). The second
    is an ordinary lawful export, and a rule that swept up 'anything not
    plain-taxable' would block it."""
    assert tax_conflict(supply_type="zero_rated", is_reverse_charge=False,
                        igst_paise=18_000_00) is None


def test_the_untaxed_types_are_exactly_the_three():
    """Named, because adding `zero_rated` here is the mistake this guards and it
    would read as a completion rather than a change."""
    assert UNTAXED_SUPPLY_TYPES == {"nil_rated", "exempt", "non_gst"}


@pytest.mark.parametrize("stype,rcm", [
    ("taxable", False), ("exempt", False), ("non_gst", True), ("taxable", True),
])
def test_no_tax_is_never_a_conflict(stype, rcm):
    """A nil invoice is consistent with every classification, including a
    reverse-charge one — that is what a correct reverse-charge invoice IS."""
    assert tax_conflict(supply_type=stype, is_reverse_charge=rcm) is None


def test_cess_counts_as_tax():
    """Explanation to §9 and the compensation cess Act charge it as tax on the
    same supply, so an exempt supply carrying only cess is the same defect in a
    column the header totals do not add up."""
    assert tax_conflict(supply_type="exempt", is_reverse_charge=False,
                        cess_paise=1_200_00)


# ── the rule reaches both the write path and the return build ───────────────

def test_the_invoice_path_refuses_it():
    """The create path, not just the domain function — a rule nothing calls is
    a second opinion the product never asks for."""
    import inspect
    import re
    import routers.sales_invoices as si

    src = inspect.getsource(si)
    src = re.sub(r"#[^\n]*", "", src)
    src = re.sub(r'"""[\s\S]*?"""', "", src)
    assert src.count("supply_classification.tax_conflict(") >= 2, (
        "the classification check is missing from the create or the update "
        "path — an edit can reach the conflict from either side: reclassify a "
        "taxable invoice as exempt, or put taxed lines on one already exempt")


def test_the_validator_catches_a_row_written_before_the_check_existed():
    """The same rule at the return build, because the create-time refusal
    cannot reach a row that is already stored."""
    from domain.gst.validator import GSTValidator, InvoiceToValidate

    bad = InvoiceToValidate(
        reference_no="INV-1", transaction_date="2026-06-10", party_gstin=None,
        place_of_supply="27", taxable_amount_paise=1_00_000_00,
        cgst_paise=9_000_00, sgst_paise=9_000_00, igst_paise=0,
        is_interstate=False, gst_rate=18.0, supply_type="exempt")
    fields = [e.field for e in GSTValidator().validate_invoice(bad, "062026")]
    assert "supply_type" in fields, fields


def test_an_ordinary_taxable_invoice_still_validates():
    """The negative half: the new check must not fire on the common case."""
    from domain.gst.validator import GSTValidator, InvoiceToValidate

    ok = InvoiceToValidate(
        reference_no="INV-2", transaction_date="2026-06-10", party_gstin=None,
        place_of_supply="27", taxable_amount_paise=1_00_000_00,
        cgst_paise=9_000_00, sgst_paise=9_000_00, igst_paise=0,
        is_interstate=False, gst_rate=18.0)
    assert [e.field for e in GSTValidator().validate_invoice(ok, "062026")] == []


# ── SALES-29: a place of supply, and where it comes from ────────────────────

def test_issue_requires_a_valid_place_of_supply():
    """AT ISSUE, not at create. A draft is allowed to be incomplete — that is
    what a draft is — and Rule 46(n) requires the place of supply on a tax
    INVOICE, which is what issuing makes it."""
    import inspect
    import re
    import routers.sales_invoices as si

    body = inspect.getsource(si.issue_invoice)
    body = re.sub(r"#[^\n]*", "", body)
    body = re.sub(r'"""[\s\S]*?"""', "", body)
    assert "VALID_STATE_CODES" in body, (
        "issue_invoice no longer checks the place of supply, so an invoice can "
        "again be issued, posted and sent and first fail at the GSTR-1 build")


def test_the_place_of_supply_has_four_sources_ending_in_the_suppliers_own_state():
    """The default is what makes the refusal usable. IGST §12(2)(b)(ii): where
    the recipient is unregistered and no address is on record, the place of
    supply is the location of the SUPPLIER — the ordinary B2C counter sale.
    Without it, requiring a place of supply at issue would block billing a
    walk-in customer, which is most of a retail client's day.

    The GSTIN is the third source and it is free: CGST §25 makes the first two
    characters of a GSTIN the registration's state, so a REGISTERED customer
    always carries their own place of supply whether or not the field was
    filled in."""
    import inspect
    import re
    import routers.sales_invoices as si

    src = inspect.getsource(si)
    src = re.sub(r"#[^\n]*", "", src)
    src = re.sub(r'"""[\s\S]*?"""', "", src)
    # Sliced to the expression's own closing paren — `block.index(")")` finds
    # the one inside `customer.get("state_code")` and truncates the block
    # before the two sources that matter.
    block = src[src.index("effective_supply_state = ("):]
    block = block[:block.index("\n    )") + 6]
    assert 'customer.get("state_code")' in block, block
    assert 'customer.get("gstin")' in block, (
        "the customer's GSTIN is no longer read as a place of supply — CGST "
        "§25 puts the state in its first two characters, and it is the source "
        "that needs nobody to have filled a field in")
    assert "client_state_code" in block, (
        "the supplier's own state is no longer the last resort, so an "
        "unregistered walk-in customer with no address on record cannot be "
        "billed at all — IGST §12(2)(b)(ii) says that case has an answer")
