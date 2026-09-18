"""
THE ACT ALLOWS AN INVOICE NUMBER THE E-INVOICE PORTAL REFUSES (GST-32).

CGST Rule 46(b) permits "alphabets or numerals or special characters hyphen or
dash and slash ... and any combination thereof", sixteen characters. The IRP
publishes its own expression for the same field:

    Document_Num   ^([a-zA-Z1-9]{1}[a-zA-Z0-9/-]{0,15})$

and the FIRST character class is not the second — a letter or a digit ONE TO
NINE. So `0001`, `-INV-1` and `/2026/1` are lawful numbers the portal rejects,
and nothing in this product said so.

`0001` IS REACHABLE TODAY AND THE PRODUCT SUGGESTS IT. `invoice_settings` holds
a prefix and a padding, and a firm with an empty prefix and the financial year
switched off gets exactly `0001` out of `sales_numbering_service.suggest` — a
premise this module asserts rather than asserting the string, so the day the
numbering changes this test says what happened instead of quietly passing.

TWO AUTHORITIES, AND THE SECOND ONE ONLY REPORTS. `invoice_series` refuses
against the Act at every door and is untouched: a client below the Rule 48(4)
threshold may number their invoices `0001` for ever. `irp_validations` answers a
different question — would the PORTAL take this — and it is asked only where the
supply limb of Rule 48(4) is in scope, because a B2C invoice never reaches an
IRP at all.

GST-32's REFUSAL STANDS. This builds no IRP or EWB payload. It asks whether a
value this product already holds would be accepted in a named field, and every
expression is transcribed from a document committed under
`docs/compliance/sources/e-invoice/` — which is what makes `VERIFIED = True`
here a claim about PROVENANCE rather than about confidence.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from domain.gst import invoice_series, irp_validations as irp

REPO = Path(__file__).resolve().parents[3]
SOURCE = (REPO / "docs/compliance/sources/e-invoice/field-regular-expressions.txt")


# ── the expressions are the published ones ───────────────────────────────────

def test_the_document_number_expression_is_transcribed_from_the_source():
    """Character for character, against the file in this repository.

    The whole value of this module is that its rules came from a document
    somebody read. A transcription nobody checks is a rule written from
    memory with a citation attached.
    """
    text = SOURCE.read_text()
    assert "^([a-zA-Z1-9]{1}[a-zA-Z0-9/-]{0,15})$" in text
    assert irp.DOCUMENT_NUMBER_RE.pattern == "^([a-zA-Z1-9]{1}[a-zA-Z0-9/-]{0,15})$"
    assert irp.VERIFIED is True


def test_the_other_two_expressions_are_transcribed_too():
    text = SOURCE.read_text()
    assert "^[a-zA-Z0-9]{1}[a-zA-Z0-9-/]*$" in text
    assert irp.TRANSPORT_DOCUMENT_NUMBER_RE.pattern == "^[a-zA-Z0-9]{1}[a-zA-Z0-9-/]*$"
    assert "^[0-9]*$" in text
    assert irp.HSN_CODE_RE.pattern == "^[0-9]*$"


def test_the_transport_document_rule_is_DIFFERENT_and_that_is_not_a_typo():
    """Sr. 10.3 admits a leading 0 and caps no length; Sr. 1.1 does neither.

    A transporter's document is somebody else's numbering and the IRP does not
    govern it, so the two must not be harmonised — which is exactly what a
    reader who noticed the difference would be tempted to do.
    """
    assert irp.DOCUMENT_NUMBER_RE.pattern != irp.TRANSPORT_DOCUMENT_NUMBER_RE.pattern
    assert irp.TRANSPORT_DOCUMENT_NUMBER_RE.match("0001")
    assert not irp.DOCUMENT_NUMBER_RE.match("0001")
    assert irp.TRANSPORT_DOCUMENT_NUMBER_RE.match("A" * 40), "no length cap"
    assert not irp.DOCUMENT_NUMBER_RE.match("A" * 17)


# ── the disagreement with the Act ────────────────────────────────────────────

@pytest.mark.parametrize("number", ["0001", "0", "---", "///", "-INV-1", "/2026/1"])
def test_a_LAWFUL_number_the_portal_REFUSES(number):
    """Both halves asserted on the same string, which is the whole finding."""
    assert invoice_series.format_violation(number) is None, \
        "premise: CGST Rule 46(b) permits this number"
    found = irp.document_number_finding(number)
    assert found is not None
    assert "Rule 46(b)" in found.reason, \
        "the CA must be told the invoice is lawful and only the IRN is blocked"
    assert "field-regular-expressions" in found.source


@pytest.mark.parametrize("number", ["INV/2026-27/0001", "INV-001", "1", "A"])
def test_a_number_BOTH_accept(number):
    assert invoice_series.format_violation(number) is None
    assert irp.document_number_finding(number) is None


def test_the_product_suggests_one_of_the_refused_numbers_today():
    """The premise, asserted rather than the string.

    A firm with an empty prefix and no financial year is a real configuration
    `invoice_settings` allows, and `format_number` pads it — so the box the CA
    is shown carries a number the portal will reject on every invoice of the
    year, with nothing saying why.
    """
    settings = invoice_series.SeriesSettings(
        prefix="", include_financial_year=False,
        sequence_length=4, starting_number=1)
    suggested = invoice_series.format_number(settings, "2026-27", 1)
    assert suggested == "0001"
    assert invoice_series.format_violation(suggested) is None
    assert irp.document_number_finding(suggested) is not None


def test_the_three_failures_are_NOT_INTERCHANGEABLE():
    """A first character is the SERIES, a length is the PREFIX, a stray
    character is the number itself. One sentence for all three would send a CA
    to change the wrong setting."""
    first = irp.document_number_finding("0001")
    longg = irp.document_number_finding("A" * 17)
    char = irp.document_number_finding("INV#1")
    absent = irp.document_number_finding("")
    assert len({first.reason, longg.reason, char.reason, absent.reason}) == 4
    assert "beginning with" in first.reason
    assert "17 characters" in longg.reason
    assert "'#'" in char.reason


def test_a_preceding_document_number_takes_the_SAME_rule_and_its_OWN_field():
    """Sr. 3.1.1 is the same expression — a credit note's reference to its
    original is a document number too — and the field name has to differ or a
    CA cannot tell which of the two to fix."""
    out = irp.assess(document_number="INV-1", preceding_document_number="0001")
    assert len(out) == 1
    assert out[0].field == "RefDtls.PrecDocDtls.InvNo"
    assert "3.1.1" in out[0].source


# ── the HSN limb, which is not the notification's ────────────────────────────

@pytest.mark.parametrize("code,fragment", [
    ("", "at least 4 digits"),
    ("99", "has 2 digits"),
    ("SAC9983", "is not a code"),
])
def test_the_portal_refuses_these_HSN_codes(code, fragment):
    found = irp.hsn_finding(code, line_no=0)
    assert found is not None and fragment in found.reason
    assert found.field == "ItemList[0].HsnCd"


def test_four_digits_satisfy_the_PORTAL_where_the_NOTIFICATION_may_want_six():
    """Two rules about one field, and neither is the other.

    Notification 78/2020 asks how many digits a RETURN must carry and lets a
    B2C supply carry none; the IRP asks for at least four on every item of
    every document it registers. `hsn_digits` answers the first.
    """
    assert irp.hsn_finding("9983", line_no=0) is None
    from domain.gst import hsn_digits
    big = hsn_digits.required_digits(100_00_00_000_00, is_b2b=True,
                                     period_start="2026-04-01")
    assert hsn_digits.problem_with("9983", big) is not None


def test_the_line_number_travels_so_a_CA_knows_WHICH_line():
    out = irp.assess(document_number="INV-1",
                     hsn_codes=["998313", "99", "998314", ""])
    assert [f.field for f in out] == ["ItemList[1].HsnCd", "ItemList[3].HsnCd"]


def test_no_lines_reports_the_DOCUMENT_only_and_claims_nothing_about_items():
    assert irp.assess(document_number="INV-1") == []
    assert irp.assess(document_number="INV-1", hsn_codes=[]) == []


# ── the contract ─────────────────────────────────────────────────────────────

def test_nothing_here_RAISES():
    """It reports. A document that fails these rules is still a lawful invoice
    and the CA still has to be able to issue it."""
    for bad in [None, "", "0", "-", "/", "#" * 40]:
        irp.document_number_finding(bad)
        irp.hsn_finding(bad, line_no=0)
    assert irp.assess(document_number=None, hsn_codes=[None]) != []


def test_the_Act_side_is_UNTOUCHED_by_this_module():
    """`invoice_series` must not learn the portal's rule.

    A client below the Rule 48(4) threshold numbers their invoices however
    Rule 46(b) allows, and refusing `0001` at the door would refuse a lawful
    document over a portal this product does not reach.
    """
    src = Path(irp.__file__).parent.joinpath("invoice_series.py").read_text()
    assert "a-zA-Z1-9" not in src
    assert "irp_validations" not in src


def test_what_is_NOT_held_is_named_and_the_reasons_DIFFER():
    """Four refusals, each its own sentence. A shared "not implemented" would
    say the wrong thing about most of them — the HSN master is a fact this
    product cannot hold, and the payload expressions are a decision.

    It was FIVE until migration 411 gave a sales invoice line an `is_service`:
    the goods-only quantity rule is built now, and the IsServc-against-the-HSN
    entry narrowed to the half that is still refused — the MASTER, not the flag.
    """
    assert len(irp.NOT_HELD) == 4
    assert len(set(irp.NOT_HELD.values())) == 4
    assert all(len(v) > 80 for v in irp.NOT_HELD.values())
    joined = " ".join(irp.NOT_HELD.values())
    assert "master" in joined and "GST-32" in joined


def test_the_payload_is_STILL_refused():
    """GST-32's own reasoning, which this module narrows rather than reverses:
    a wrong field NAME fails visibly at the portal, a misremembered field
    MEANING generates a real document with wrong figures."""
    src = Path(irp.__file__).read_text()
    for forbidden in ("def build_irn", "def build_payload", '"Version"', "SellerDtls"):
        assert forbidden not in src, \
            f"{forbidden} — this module checks values, it does not build a payload"


def _served(*, invoice_no, gstin, hsn="998313", unit="PCS", is_service=False):
    """The assessment the endpoint actually serves, through the real function.

    A guard that only greps the router survives a router that computes the
    findings and throws them away — which is exactly what a first attempt at
    the negative control for this test did by accident.

    The line carries a UNIT and an `is_service` because the default fixture is
    meant to be CLEAN: the goods-only unit rule fires on a line that records
    neither, which is correct and is asserted on its own fixtures below.
    """
    from routers.sales_invoices import _irn_assessment
    inv = {"invoice_no": invoice_no, "invoice_date": "2026-06-01",
           "client_id": "C1", "customers": {"gstin": gstin},
           "lines": [{"hsn_sac": hsn, "unit": unit, "is_service": is_service}]}
    return _irn_assessment(inv, "regular")


def test_the_module_is_wired_to_a_reader():
    """A domain module nothing calls is a second opinion the product never
    asks for — SALES-18's own lesson, which is why irn_scope exists at all."""
    got = _served(invoice_no="0001", gstin="27AAACI1195H1ZM")
    assert got["supply_in_scope"] is True, "premise: a B2B supply is in scope"
    assert [f["field"] for f in got["irp_findings"]] == ["DocDtls.No"]
    assert "Rule 46(b)" in got["irp_findings"][0]["reason"]


def test_a_clean_invoice_carries_an_EMPTY_list_rather_than_nothing():
    got = _served(invoice_no="INV/2026-27/0001", gstin="27AAACI1195H1ZM")
    assert got["irp_findings"] == []


def test_a_B2C_INVOICE_IS_NOT_ASKED_AT_ALL():
    """The gate. Asked unconditionally, every retail invoice in the country
    would carry a portal rule it never has to satisfy — and `0001` is a
    perfectly good number for a client below the Rule 48(4) threshold."""
    got = _served(invoice_no="0001", gstin=None)
    assert got["supply_in_scope"] is False
    assert got["irp_findings"] == []


def test_the_router_gates_on_the_supply_limb_in_SOURCE_too():
    """Both halves: the behaviour above, and the reason it is that way.

    The functional test would still pass if the gate moved to something that
    happens to agree on these fixtures, so the rule is named as well.
    """
    router = Path(irp.__file__).parents[1].joinpath(
        "..", "routers", "sales_invoices.py").resolve().read_text()
    assert "irp_validations" in router
    assert 'scope.get("supply_in_scope")' in router


# ── the goods-only unit rule, askable since migration 411 ────────────────────

def test_a_GOODS_line_with_no_unit_is_refused():
    found = irp.goods_unit_finding(is_service=False, unit="", line_no=0)
    assert found is not None
    assert "GOODS" in found.reason and "46(h)" in found.reason


def test_a_SERVICE_line_with_no_unit_is_FINE():
    """The portal's own words: mandatory for goods, optional for services. A
    professional's fee line has no unit and owes none."""
    assert irp.goods_unit_finding(is_service=True, unit="", line_no=0) is None
    assert irp.goods_unit_finding(is_service=True, unit=None, line_no=0) is None


def test_an_UNRECORDED_kind_is_its_OWN_answer_and_not_either_guess():
    """Both guesses are wrong in opposite directions — goods demands a UQC on
    every fee line, services waives one Rule 46(h) asks for. So it says so."""
    goods = irp.goods_unit_finding(is_service=False, unit="", line_no=0)
    unknown = irp.goods_unit_finding(is_service=None, unit="", line_no=0)
    assert unknown is not None
    assert unknown.reason != goods.reason
    assert "does not say whether" in unknown.reason


def test_a_unit_that_IS_recorded_ends_the_question_whatever_the_kind():
    for svc in (True, False, None):
        assert irp.goods_unit_finding(is_service=svc, unit="PCS", line_no=0) is None


def test_the_unit_rule_is_asked_THROUGH_the_served_assessment():
    got = _served(invoice_no="INV-1", gstin="27AAACI1195H1ZM")
    assert got["irp_findings"] == [], "premise: the fixture line carries a unit"
    from routers.sales_invoices import _irn_assessment
    inv = {"invoice_no": "INV-1", "invoice_date": "2026-06-01", "client_id": "C1",
           "customers": {"gstin": "27AAACI1195H1ZM"},
           "lines": [{"hsn_sac": "998313", "unit": None, "is_service": False}]}
    out = _irn_assessment(inv, "regular")["irp_findings"]
    assert [f["field"] for f in out] == ["ItemList[0].Unit"]


def test_a_caller_that_supplies_NO_units_is_answered_about_the_CODES_only():
    """Zipped rather than indexed: reporting a missing unit on a line nobody
    described would be a finding about the caller, not about the invoice."""
    out = irp.assess(document_number="INV-1", hsn_codes=["998313", "998313"])
    assert out == []


def test_the_quantity_itself_is_NOT_checked_and_the_reason_is_recorded():
    """It is NUMERIC(10,3) NOT NULL DEFAULT 1 on every line table, so it is
    never absent, and `domain/quantity` already refuses a fourth decimal at six
    doors. A second check here would fire on nothing."""
    src = Path(irp.__file__).read_text()
    assert irp.QUANTITY_DECIMALS_AGREE_WITH_THE_COLUMN == 3
    assert "NUMERIC(10,3)" in src


def test_the_router_RESOLVES_rather_than_reading_the_column_raw():
    """The distinguishing case, and NC-D found it unguarded.

    A line with `is_service = NULL` and an HSN of `998313` is a SERVICE — the
    code says so, Chapter 99 of the tariff — so it owes no unit. Reading the
    stored column alone would answer "nobody said" and report a gap on every
    professional's fee line, which is the reason `goods_or_services.resolve`
    exists rather than the router reading `ln["is_service"]`.
    """
    from routers.sales_invoices import _irn_assessment
    def _findings(hsn):
        inv = {"invoice_no": "INV-1", "invoice_date": "2026-06-01",
               "client_id": "C1", "customers": {"gstin": "27AAACI1195H1ZM"},
               "lines": [{"hsn_sac": hsn, "unit": None, "is_service": None}]}
        return [f["field"] for f in _irn_assessment(inv, "regular")["irp_findings"]]

    assert _findings("998313") == [], \
        "a SAC with no unit is complete; the router is not resolving from the code"
    assert _findings("8471") == ["ItemList[0].Unit"], \
        "an HSN of goods with no unit owes one"
    assert _findings("") == ["ItemList[0].HsnCd", "ItemList[0].Unit"], \
        "no code and no unit: two findings, and the unit one says nobody can tell"
