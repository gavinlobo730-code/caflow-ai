"""
GSTR-1 amendment tables — declaring a correction to a filed return.

CGST Act §37: a filed GSTR-1 cannot be revised. A correction is an amended entry
in a LATER period's return, and every amended entry has to identify the entry it
supersedes — original document number and date, or for B2C-others the original
month. Without that GSTN has nothing to match against.

Three things in here are easy to get wrong and each has statutory consequences:

  * amending in the table the document was ORIGINALLY filed in, not the one it
    now belongs to
  * the original reference keys — oinum/oidt for invoices, ont_num/ont_dt for
    notes; GSTN will not accept one spelling for the other
  * a document raised after filing is NOT an amendment and must not be given one
"""
from __future__ import annotations

import pytest

from domain.gst.amendment_proposal import propose
from domain.gst.amendments import (
    SECTION_TABLE, amendment_section_for, build_b2cs_amendment,
    build_invoice_amendment, build_note_amendment, group_amendments,
    merge_into_payload,
)

AMOUNTS = {"taxable_paise": 100_000, "cgst_paise": 9_000, "sgst_paise": 9_000,
           "igst_paise": 0, "cess_paise": 0}


# ── which table corrects which ───────────────────────────────────────────────

@pytest.mark.parametrize("original,amendment,table", [
    ("b2b", "b2ba", "9A"),
    ("b2cl", "b2cla", "9A"),
    ("exp", "expa", "9A"),
    ("cdnr", "cdnra", "9C"),
    ("cdnur", "cdnura", "9C"),
])
def test_each_original_table_has_its_amendment_table(original, amendment, table):
    assert amendment_section_for(original) == amendment
    assert SECTION_TABLE[amendment] == table


def test_b2cs_amendments_are_table_10():
    assert SECTION_TABLE["b2csa"] == "10"


def test_an_unknown_section_has_no_amendment_table():
    """Better no proposal than a confidently wrong one."""
    assert amendment_section_for("b2cs") is None
    assert amendment_section_for("nonsense") is None


# ── the original reference ───────────────────────────────────────────────────

def test_an_invoice_amendment_carries_the_original_number_and_date():
    node = build_invoice_amendment(
        original_no="INV-1", original_date="10-06-2025", section="b2ba",
        corrected=AMOUNTS, place_of_supply="27")

    assert node["oinum"] == "INV-1"
    assert node["oidt"] == "10-06-2025"


def test_amending_a_renumbered_invoice_still_points_at_the_original():
    """The case that silently creates a second invoice instead of amending the
    first: the number itself was corrected."""
    node = build_invoice_amendment(
        original_no="INV-1", original_date="10-06-2025", section="b2ba",
        corrected=AMOUNTS, doc_no="INV-1A", doc_date="12-06-2025")

    assert node["oinum"] == "INV-1"
    assert node["oidt"] == "10-06-2025"
    assert node["inum"] == "INV-1A"
    assert node["idt"] == "12-06-2025"


def test_a_note_amendment_uses_the_note_reference_keys():
    """ont_num / ont_dt, not oinum / oidt. GSTN will not accept the other."""
    node = build_note_amendment(
        original_no="CN-1", original_date="11-06-2025", corrected=AMOUNTS)

    assert node["ont_num"] == "CN-1"
    assert node["ont_dt"] == "11-06-2025"
    assert "oinum" not in node


def test_an_iso_date_is_converted_to_the_gstn_format():
    """Amendments are built from two sources — a frozen payload (DD-MM-YYYY) and
    the books (ISO) — and sending the wrong one fails the whole return."""
    node = build_invoice_amendment(
        original_no="INV-1", original_date="2025-06-10", section="b2ba",
        corrected=AMOUNTS)

    assert node["oidt"] == "10-06-2025"


def test_a_date_already_in_gstn_format_is_left_alone():
    node = build_invoice_amendment(
        original_no="INV-1", original_date="10-06-2025", section="b2ba",
        corrected=AMOUNTS)

    assert node["oidt"] == "10-06-2025"


# ── the corrected figures ────────────────────────────────────────────────────

def test_the_amendment_declares_the_corrected_amounts_in_rupees():
    node = build_invoice_amendment(
        original_no="INV-1", original_date="10-06-2025", section="b2ba",
        corrected=AMOUNTS)

    det = node["itms"][0]["itm_det"]
    assert det["txval"] == 1000.0
    assert det["camt"] == 90.0
    assert det["samt"] == 90.0
    assert node["val"] == 1180.0


def test_a_b2cs_amendment_names_the_month_it_corrects():
    """B2C-others carries no document number, so the month, rate and place of
    supply are the identity — the grain table 7 declared it at."""
    row = build_b2cs_amendment(
        original_month="062025", supply_type="INTRA", rate=18.0,
        place_of_supply="27", corrected=AMOUNTS)

    assert row["omon"] == "062025"
    assert row["rt"] == 18.0
    assert row["pos"] == "27"
    assert row["txval"] == 1000.0


# ── section-specific shape ───────────────────────────────────────────────────

def test_a_b2b_amendment_carries_place_of_supply_and_reverse_charge():
    node = build_invoice_amendment(
        original_no="INV-1", original_date="10-06-2025", section="b2ba",
        corrected=AMOUNTS, place_of_supply="29", reverse_charge=True)

    assert node["pos"] == "29"
    assert node["rchrg"] == "Y"


def test_an_export_amendment_carries_the_shipping_bill_fields():
    node = build_invoice_amendment(
        original_no="EXP-1", original_date="10-06-2025", section="expa",
        corrected=AMOUNTS)

    assert "sbnum" in node and "sbdt" in node
    assert "rchrg" not in node, "an export has no reverse charge flag"


def test_an_unregistered_note_amendment_carries_its_type_not_reverse_charge():
    node = build_note_amendment(
        original_no="CN-9", original_date="11-06-2025", corrected=AMOUNTS,
        unregistered_type="B2CL")

    assert node["typ"] == "B2CL"
    assert "rchrg" not in node


# ── grouping, which GSTN validates ───────────────────────────────────────────

def test_b2b_amendments_group_by_counterparty_gstin():
    node = build_invoice_amendment(original_no="A", original_date="10-06-2025",
                                   section="b2ba", corrected=AMOUNTS)
    other = build_invoice_amendment(original_no="B", original_date="11-06-2025",
                                    section="b2ba", corrected=AMOUNTS)

    grouped = group_amendments([
        {"section": "b2ba", "group": "27AAA", "node": node},
        {"section": "b2ba", "group": "27AAA", "node": other},
    ])

    assert len(grouped["b2ba"]) == 1
    assert grouped["b2ba"][0]["ctin"] == "27AAA"
    assert len(grouped["b2ba"][0]["inv"]) == 2


def test_different_counterparties_are_separate_groups():
    node = build_invoice_amendment(original_no="A", original_date="10-06-2025",
                                   section="b2ba", corrected=AMOUNTS)

    grouped = group_amendments([
        {"section": "b2ba", "group": "27AAA", "node": node},
        {"section": "b2ba", "group": "29BBB", "node": node},
    ])

    assert {g["ctin"] for g in grouped["b2ba"]} == {"27AAA", "29BBB"}


def test_note_amendments_group_under_nt_not_inv():
    node = build_note_amendment(original_no="CN-1", original_date="11-06-2025",
                                corrected=AMOUNTS)

    grouped = group_amendments([{"section": "cdnra", "group": "27AAA", "node": node}])

    assert "nt" in grouped["cdnra"][0]
    assert "inv" not in grouped["cdnra"][0]


def test_b2cl_amendments_group_by_place_of_supply():
    node = build_invoice_amendment(original_no="L-1", original_date="10-06-2025",
                                   section="b2cla", corrected=AMOUNTS)

    grouped = group_amendments([{"section": "b2cla", "group": "29", "node": node}])

    assert grouped["b2cla"][0]["pos"] == "29"


@pytest.mark.parametrize("section", ["cdnura", "b2csa"])
def test_the_flat_sections_are_not_grouped(section):
    grouped = group_amendments([{"section": section, "group": "", "node": {"x": 1}}])

    assert grouped[section] == [{"x": 1}]


# ── merging into a payload ───────────────────────────────────────────────────

def test_amendment_sections_are_added_to_the_payload():
    payload = {"gstin": "27AAAAA0000A1Z5", "fp": "072025", "b2b": [{"ctin": "x"}]}

    out = merge_into_payload(payload, {"b2ba": [{"ctin": "y"}]})

    assert out["b2ba"] == [{"ctin": "y"}]
    assert out["b2b"] == [{"ctin": "x"}], "the ordinary tables are untouched"


def test_an_empty_amendment_section_is_omitted_entirely():
    """A present-but-empty amendment table declares "there are no amendments",
    which is a different statement from not amending, and some validators
    reject it outright."""
    out = merge_into_payload({"fp": "072025"}, {"b2ba": [], "cdnra": []})

    assert "b2ba" not in out and "cdnra" not in out


def test_merging_does_not_mutate_the_original_payload():
    """The caller still needs the un-amended payload to show the CA what
    changed."""
    payload = {"fp": "072025"}

    merge_into_payload(payload, {"b2ba": [{"ctin": "y"}]})

    assert "b2ba" not in payload


# ── turning exception findings into proposals ────────────────────────────────

def _report(**kw):
    docs = {"missing_from_return": [], "missing_from_books": [],
            "amount_changed": [], "reclassified": []}
    docs.update(kw.pop("documents", {}))
    return {"documents": docs, "b2cs": {"changed": kw.pop("b2cs", [])}}


def test_a_changed_invoice_becomes_an_amendment_in_9A():
    report = _report(documents={"amount_changed": [{
        "doc_no": "INV-1", "kind": "invoice", "section": "b2b",
        "counterparty": "27BBBBB1111B1Z5", "doc_date": "10-06-2025",
        "filed": AMOUNTS, "books": {**AMOUNTS, "taxable_paise": 150_000},
        "delta": {"taxable_paise": 50_000},
    }]})

    out = propose(report, original_period="062025")

    assert out["counts"]["amendments"] == 1
    entry = out["entries"][0]
    assert entry["section"] == "b2ba"
    assert entry["table"] == "9A"
    assert entry["node"]["oinum"] == "INV-1"
    assert entry["node"]["itms"][0]["itm_det"]["txval"] == 1500.0


def test_a_reclassified_invoice_is_amended_in_the_table_it_was_filed_in():
    """An invoice filed as B2B and now an export is amended in 9A (b2ba), not
    declared in expa — 9A supersedes the entry that exists, and expa would
    amend one that never did."""
    report = _report(documents={"reclassified": [{
        "doc_no": "INV-1", "kind": "invoice",
        "filed_section": "b2b", "books_section": "exp",
        "delta": {"taxable_paise": 0},
    }]})

    out = propose(report, original_period="062025")

    assert out["entries"][0]["section"] == "b2ba"


def test_a_b2cs_change_becomes_a_table_10_amendment_naming_the_month():
    report = _report(b2cs=[{
        "supply_type": "INTRA", "rate": 18.0, "place_of_supply": "27",
        "filed": AMOUNTS, "books": {**AMOUNTS, "taxable_paise": 130_000},
        "delta": {"taxable_paise": 30_000},
    }])

    out = propose(report, original_period="062025")

    entry = out["entries"][0]
    assert entry["section"] == "b2csa"
    assert entry["node"]["omon"] == "062025"
    assert entry["node"]["txval"] == 1300.0


def test_an_invoice_raised_after_filing_is_carried_forward_not_amended():
    """It was never declared, so there is nothing to supersede. And it would
    otherwise fall through the floor entirely: gstr1_from_books selects by date
    range, so it is outside the current period's window as well as inside a
    closed one."""
    report = _report(documents={"missing_from_return": [{
        "doc_no": "INV-LATE", "doc_date": "10-06-2025", "section": "b2b",
        "counterparty": "27BBBBB1111B1Z5", **AMOUNTS,
    }]})

    out = propose(report, original_period="062025")

    assert out["counts"]["amendments"] == 0
    assert out["counts"]["carry_forward"] == 1
    assert out["carry_forward"][0]["doc_no"] == "INV-LATE"
    assert "ordinary table" in out["carry_forward"][0]["reason"]


def test_a_cancelled_document_is_not_resolved_silently():
    """Amend to nil, or raise a credit note? Different liabilities, and it
    depends on why it was cancelled. That is the CA's call."""
    report = _report(documents={"missing_from_books": [{
        "doc_no": "INV-1", "doc_date": "10-06-2025", "section": "b2b", **AMOUNTS,
    }]})

    out = propose(report, original_period="062025")

    assert out["counts"]["amendments"] == 0
    assert out["counts"]["needs_decision"] == 1
    assert "credit note" in out["needs_decision"][0]["question"]


def test_a_clean_period_proposes_nothing():
    out = propose(_report(), original_period="062025")

    assert out["counts"] == {"amendments": 0, "carry_forward": 0, "needs_decision": 0}


def test_the_proposal_names_the_rule_and_asks_for_review():
    out = propose(_report(), original_period="062025")

    assert "§37" in out["rule"]
    assert out["ca_review_required"] is True, "this proposes; it files nothing"


def test_an_empty_report_does_not_crash():
    assert propose({}, original_period="062025")["counts"]["amendments"] == 0
    assert propose(None, original_period="062025")["counts"]["amendments"] == 0
