"""The GSTR-1 payload must match the shape GSTN's own generator produces.

WHERE THE REFERENCE COMES FROM
    The GSTN Returns Offline Tool V3.2.4, downloaded from gst.gov.in under
    Downloads > Returns. It is an Inno Setup installer wrapping a Node.js
    application, and the code that turns a filled worksheet into GSTR-1 JSON is
    plain JavaScript in `app/utility/returnStructure.js`. Every expectation
    below was read out of that file, with its `case` labels noted so each claim
    is traceable. The same exercise on the GSTR-3B Excel utility found three
    payload bugs; this is that method applied to GSTR-1.

    Reading the CGST Act or the GSTR-1 instructions cannot settle any of this.
    They say which figure belongs in which TABLE. They do not say what the
    tables are called in JSON, and a return can be entirely correct on the law
    and still be rejected on upload.

WHAT WAS WRONG
    1. B2CS declared its supply type under "sply_tp". The key is "sply_ty"
       (returnStructure.js, case 'b2cs'). The nil table in the same module has
       always used sply_ty; B2CS used a spelling that appears nowhere in the
       tool, the schema, or the form.

       The misspelling had spread: apps/web's GSTR-1 screen rendered
       row.sply_tp, and domain/gst/exception_report.py grouped filed B2CS rows
       by it. Both now read either spelling, because returns ALREADY FILED and
       stored carry the old one and must keep reconciling.

    2. B2CS had no "typ" at all. The tool writes it on every row; it is the
       e-commerce indicator, and its only current value is "OE" — Other Than
       E-COMMERCE — since supplies through an operator moved to their own
       table.

    3. doc_issue.doc_num was `enumerate(..., start=1)` over the document
       natures that happened to have a non-zero count. It is a fixed position
       in the form's twelve-nature list: `docDetails.indexOf(nature) + 1` (case
       'doc_issue'). A period with only credit notes filed them as doc_num 1,
       "Invoices for outward supply". Even a full period put Credit Note at 2
       and Debit Note at 3, where the form fixes them at 5 and 4.

WHAT IS STILL MISSING, AND IS NOT FIXED HERE
    The tool builds eighteen GSTR-1 sections. This payload builds nine. Absent:
    every amendment table (b2ba, b2cla, b2csa, cdnra, cdnura, expa), advances
    received (at / ata) and their adjustment (txpd, called atadj in the tool /
    atadja). domain/gst/amendments.py computes amendment data that build_gstr1
    never merges in. Those are data and design gaps, not spelling, and are
    tracked separately — see the last test in this file.
"""
import pytest

from domain.gst.classifier import GSTInvoiceCategory
from domain.gst.gstr1_builder import InvoiceForGSTR1, InvoiceLine, build_gstr1

GSTIN = "27AAAAA0000A1Z5"
PERIOD = "042026"


def _inv(**kw):
    base = dict(
        id="i1", transaction_type="sales_invoice", reference_no="INV-1",
        transaction_date="2026-04-10", party_gstin=None, party_name="Walk-in",
        place_of_supply="27", is_interstate=False,
        taxable_amount_paise=1_00000, cgst_paise=9000, sgst_paise=9000,
        igst_paise=0, cess_paise=0, is_reverse_charge=False,
        invoice_type="Regular", supply_type="taxable",
        gst_invoice_category=GSTInvoiceCategory.B2CS,
        original_invoice_ref=None, original_invoice_date=None,
        lines=[InvoiceLine(hsn_sac_code="9983", description="svc", quantity=1,
                           unit="NOS", rate_paise=1_00000, taxable_paise=1_00000,
                           gst_rate=18.0, cgst_paise=9000, sgst_paise=9000,
                           igst_paise=0, cess_paise=0)],
    )
    base.update(kw)
    return InvoiceForGSTR1(**base)


def _payload(invoices):
    return build_gstr1(invoices, GSTIN, PERIOD).payload


# ── B2CS ─────────────────────────────────────────────────────────────────────

def test_b2cs_declares_the_supply_type_under_sply_ty():
    rows = _payload([_inv()])["b2cs"]
    assert rows, "the fixture produced no B2CS row"
    assert rows[0]["sply_ty"] == "INTRA"
    assert "sply_tp" not in rows[0], (
        "sply_tp is not a key the GSTN tool, schema or form has ever had")


def test_b2cs_carries_the_e_commerce_indicator():
    """The tool writes `typ` on every b2cs row. Omitting a field the generator
    always emits is the same class of defect as misspelling one."""
    assert _payload([_inv()])["b2cs"][0]["typ"] == "OE"


def test_inter_and_intra_are_still_separate_rows():
    """The grouping this key drives. If sply_ty were dropped rather than
    renamed, the two would merge and the return would understate one of them."""
    rows = _payload([
        _inv(id="a", is_interstate=False, place_of_supply="27"),
        _inv(id="b", is_interstate=True, place_of_supply="29",
             cgst_paise=0, sgst_paise=0, igst_paise=18000),
    ])["b2cs"]
    assert {r["sply_ty"] for r in rows} == {"INTRA", "INTER"}
    assert len(rows) == 2


def test_every_b2cs_row_has_the_fields_the_tool_writes():
    rows = _payload([_inv()])["b2cs"]
    for r in rows:
        assert {"sply_ty", "typ", "rt", "pos", "txval",
                "camt", "samt", "csamt"} <= set(r), sorted(r)


# ── doc_issue ────────────────────────────────────────────────────────────────

def _docs(invoices):
    return {d["doc_typ"]: d["doc_num"] for d in _payload(invoices)["doc_issue"]["doc_det"]}


def test_doc_num_is_the_forms_fixed_position_not_a_running_count():
    got = _docs([
        _inv(id="a"),
        _inv(id="b", transaction_type="credit_note", reference_no="CN-1",
             gst_invoice_category=GSTInvoiceCategory.CDNA),
        _inv(id="c", transaction_type="debit_note", reference_no="DN-1",
             gst_invoice_category=GSTInvoiceCategory.CDNA),
    ])
    assert got == {"Invoices for outward supply": 1, "Debit Note": 4,
                   "Credit Note": 5}, got


def test_a_period_with_only_credit_notes_still_numbers_them_five():
    """THE BUG, at its clearest. Under the old code this filed a credit-note
    count against "Invoices for outward supply"."""
    got = _docs([_inv(id="b", transaction_type="credit_note", reference_no="CN-1",
                      gst_invoice_category=GSTInvoiceCategory.CDNA)])
    assert got == {"Credit Note": 5}, got


def test_the_rows_come_out_in_form_order():
    rows = _payload([
        _inv(id="b", transaction_type="credit_note", reference_no="CN-1",
             gst_invoice_category=GSTInvoiceCategory.CDNA),
        _inv(id="a"),
    ])["doc_issue"]["doc_det"]
    assert [d["doc_num"] for d in rows] == sorted(d["doc_num"] for d in rows)


def test_the_natures_we_emit_are_spelled_as_the_form_spells_them():
    """doc_typ is matched against the tool's list by exact string. A near-miss
    — "Credit Notes", "Invoice for outward supply" — indexes to nothing."""
    from domain.gst.gstr1_builder import _DOC_NATURES
    assert _DOC_NATURES[0] == "Invoices for outward supply"
    assert _DOC_NATURES[3] == "Debit Note"
    assert _DOC_NATURES[4] == "Credit Note"
    assert len(_DOC_NATURES) == 12, "the form has twelve document natures"
    for d in _payload([_inv()])["doc_issue"]["doc_det"]:
        assert d["doc_typ"] in _DOC_NATURES


# ── nil: already correct, and worth keeping that way ─────────────────────────

def test_the_nil_supply_type_codes_are_unchanged_and_correct():
    """INTR* is INTER-state and INTRA* is INTRA-state. Confirmed against
    returnStructure.js getNilType(); the prefixes differ by one letter and
    swapping them files every nil supply against the wrong half of table 8."""
    from domain.gst.gstr1_builder import _NIL_SPLY_TY
    assert _NIL_SPLY_TY[(True, True)] == "INTRB2B"
    assert _NIL_SPLY_TY[(True, False)] == "INTRB2C"
    assert _NIL_SPLY_TY[(False, True)] == "INTRAB2B"
    assert _NIL_SPLY_TY[(False, False)] == "INTRAB2C"


# ── the sections that do not exist yet ───────────────────────────────────────

def test_the_sections_this_builder_does_not_produce_are_recorded():
    """Pins the current section set so adding one is deliberate, and names what
    is absent so nobody reads this file as "GSTR-1 is complete".

    The tool builds eighteen sections (app/public/data/tablename.json). These
    six amendment tables and the four advance tables are not among the nine
    this payload produces.
    """
    p = _payload([_inv()])
    missing = {"b2ba", "b2cla", "b2csa", "cdnra", "cdnura", "expa",
               "at", "ata", "txpd", "atadj", "atadja", "supeco"}
    assert missing.isdisjoint(p), sorted(missing & set(p))
    assert set(p) <= {"gstin", "fp", "gt", "cur_gt", "b2b", "b2cl", "b2cs",
                      "cdnr", "cdnur", "exp", "nil", "hsn", "doc_issue"}, sorted(p)


# ── cdnur: the type codes Table 9B actually accepts ──────────────────────────

def _note(**kw):
    base = dict(id="n1", transaction_type="credit_note", reference_no="CN-1",
                gst_invoice_category=GSTInvoiceCategory.CDNA)
    base.update(kw)
    return _inv(**base)


def _cdnur(invoices):
    return _payload(invoices).get("cdnur", [])


def test_cdnur_never_emits_b2cs():
    """B2CS is not one of the values Table 9B offers (returns.fct.js cdnur type
    list: B2CL, EXPWP, EXPWOP). This builder emitted it for every intra-state
    note to an unregistered person — a value the portal rejects."""
    rows = _cdnur([
        _note(id="a", is_interstate=False),
        _note(id="b", is_interstate=True, place_of_supply="29",
              cgst_paise=0, sgst_paise=0, igst_paise=18000),
    ])
    assert all(r["typ"] != "B2CS" for r in rows), rows
    assert all(r["typ"] in {"B2CL", "EXPWP", "EXPWOP"} for r in rows), rows


def test_an_inter_state_note_is_b2cl():
    rows = _cdnur([_note(is_interstate=True, place_of_supply="29",
                         cgst_paise=0, sgst_paise=0, igst_paise=18000)])
    assert [r["typ"] for r in rows] == ["B2CL"]


@pytest.mark.parametrize("igst,expected", [(18000, "EXPWP"), (0, "EXPWOP")])
def test_an_export_note_is_typed_by_whether_igst_was_paid(igst, expected):
    """A without-payment (LUT/bond) export carries no IGST by construction, so
    the presence of IGST is what separates the two."""
    rows = _cdnur([_note(supply_type="zero_rated", place_of_supply="96",
                         is_interstate=True, cgst_paise=0, sgst_paise=0,
                         igst_paise=igst)])
    assert [r["typ"] for r in rows] == [expected]


def test_an_intra_state_note_is_left_out_rather_than_mislabelled():
    """It has no row in 9B: an intra-state B2C supply is never reported
    invoice-wise, so its note has nothing to point at and is absorbed into the
    Table 7 summary. Dropping it is correct; inventing a code was not."""
    from domain.gst.gstr1_builder import _cdnur_unreportable
    note = _note(is_interstate=False)
    assert _cdnur([note]) == []
    # And it is countable, so the omission is visible rather than silent.
    assert [i.id for i in _cdnur_unreportable([note])] == ["n1"]


def test_the_fixture_would_have_produced_a_b2cs_row_before():
    """Guard. If an intra-state note no longer reached _build_cdnur at all, the
    assertion above would hold for a reason unrelated to the fix."""
    from domain.gst.gstr1_builder import _cdnur_type
    assert _cdnur_type(_note(is_interstate=False)) is None
    assert _cdnur_type(_note(is_interstate=True)) == "B2CL"
