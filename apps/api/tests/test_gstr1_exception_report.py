"""
The exception report — what moved after the return was filed.

CGST Act §37: a filed GSTR-1 can never be revised. Corrections are declared in
a LATER period's amendment tables. So every finding here has to name the table
the correction belongs in, and the four kinds of finding need four different
answers:

    in books, never filed   -> the current period's ordinary table (nothing to amend)
    filed, gone from books  -> 9A / 9C
    filed, figures changed  -> 9A / 9C
    filed, table changed    -> 9A / 9C, but the table is the real problem

B2CS is deliberately different and that is tested too: GSTR-1 declares B2C-others
as totals by (supply type, rate, place of supply) with no invoice number, so a
per-document diff there is not possible and not meaningful.
"""
from __future__ import annotations

import pytest

from domain.gst.exception_report import (
    AMEND_B2CS, AMEND_INVOICE, AMEND_NOTE, DECLARE_CURRENT,
    compare_payloads, index_b2cs, index_documents, rupees_to_paise,
)


def _itms(taxable, cgst=0, sgst=0, igst=0, cess=0, rate=18.0):
    """One itm_det, in rupees, the way the builder writes it."""
    return [{"num": 1, "itm_det": {
        "txval": taxable / 100, "rt": rate,
        "camt": cgst / 100, "samt": sgst / 100,
        "iamt": igst / 100, "csamt": cess / 100,
    }}]


def _b2b(inum, taxable, cgst=0, sgst=0, igst=0, ctin="27BBBBB1111B1Z5", idt="10-06-2025"):
    return {"ctin": ctin, "inv": [{
        "inum": inum, "idt": idt, "val": (taxable + cgst + sgst + igst) / 100,
        "pos": "27", "rchrg": "N", "inv_typ": "R",
        "itms": _itms(taxable, cgst, sgst, igst),
    }]}


def _payload(**sections):
    return {"gstin": "27AAAAA0000A1Z5", "fp": "062025", **sections}


# ── reading the payload back into paise ──────────────────────────────────────

def test_rupees_come_back_as_exact_paise():
    """paise_to_rupees_2dp writes round(paise/100, 2); this is its inverse."""
    assert rupees_to_paise(1234.56) == 123456
    assert rupees_to_paise(0.01) == 1
    assert rupees_to_paise(0) == 0
    assert rupees_to_paise(None) == 0


@pytest.mark.parametrize("rupees,paise", [(8.29, 829), (0.29, 29), (1.15, 115)])
def test_a_rupee_value_that_truncates_still_comes_back_whole(rupees, paise):
    """The reason this converts with round() and not int().

    8.29 * 100 is 828.9999999999999 in binary floating point, so int() returns
    828 and loses a paisa on a figure that was exact going in. Which values do
    this is not guessable — 1234.56 * 100 is exactly 123456.0, so the obvious
    test case above passes under both and proves nothing. These three do not.
    """
    assert rupees_to_paise(rupees) == paise


def test_an_unreadable_amount_is_zero_rather_than_a_crash():
    assert rupees_to_paise("not-a-number") == 0


def test_a_document_totals_across_its_rate_groups():
    """GSTR-1 splits a document into one itm_det per rate; the document's own
    figure is the sum. Reading the header `val` would fold tax and round-off
    into one number and lose the per-head split every amendment needs."""
    payload = _payload(b2b=[{"ctin": "27BBBBB1111B1Z5", "inv": [{
        "inum": "INV-1", "idt": "10-06-2025", "val": 1416.0, "pos": "27",
        "rchrg": "N", "inv_typ": "R",
        "itms": _itms(100_000, 9_000, 9_000) + _itms(50_000, 1_250, 1_250, rate=5.0),
    }]}])

    doc = index_documents(payload)["invoice:INV-1"]

    assert doc["taxable_paise"] == 150_000
    assert doc["cgst_paise"] == 10_250
    assert doc["sgst_paise"] == 10_250


def test_an_invoice_and_a_note_sharing_a_number_are_not_confused():
    """Invoices and credit notes are separate serial series (CGST Rule 46/53),
    so the same number can legitimately appear as both."""
    payload = _payload(
        b2b=[_b2b("001", 100_000, 9_000, 9_000)],
        cdnr=[{"ctin": "27BBBBB1111B1Z5", "nt": [{
            "ntty": "C", "nt_num": "001", "nt_dt": "12-06-2025", "val": 118.0,
            "pos": "27", "rchrg": "N", "itms": _itms(10_000, 900, 900),
        }]}],
    )

    docs = index_documents(payload)

    assert docs["invoice:001"]["taxable_paise"] == 100_000
    assert docs["note:001"]["taxable_paise"] == 10_000


def test_every_document_carrying_section_is_read():
    payload = _payload(
        b2b=[_b2b("B-1", 100_00)],
        b2cl=[{"pos": "29", "inv": [{"inum": "L-1", "idt": "10-06-2025", "val": 3540.0,
                                     "itms": _itms(300_000, igst=54_000)}]}],
        exp=[{"exp_typ": "WOPAY", "inv": [{"inum": "E-1", "idt": "10-06-2025", "val": 5000.0,
                                           "itms": _itms(500_000)}]}],
        cdnr=[{"ctin": "27B", "nt": [{"ntty": "C", "nt_num": "CN-1", "nt_dt": "11-06-2025",
                                      "val": 118.0, "itms": _itms(10_000, 900, 900)}]}],
        cdnur=[{"ntty": "C", "nt_num": "CU-1", "nt_dt": "11-06-2025", "typ": "B2CL",
                "val": 118.0, "pos": "29", "itms": _itms(20_000, igst=3_600)}],
    )

    assert set(index_documents(payload)) == {
        "invoice:B-1", "invoice:L-1", "invoice:E-1", "note:CN-1", "note:CU-1",
    }


def test_an_empty_or_missing_payload_reads_as_no_documents():
    assert index_documents(None) == {}
    assert index_documents({}) == {}
    assert index_documents(_payload()) == {}


# ── nothing changed ──────────────────────────────────────────────────────────

def test_books_matching_the_return_is_a_clean_report():
    payload = _payload(b2b=[_b2b("INV-1", 100_000, 9_000, 9_000)])

    out = compare_payloads(payload, payload)

    assert out["clean"] is True
    assert out["finding_count"] == 0
    assert out["totals"]["delta"] == {
        "taxable_paise": 0, "cgst_paise": 0, "sgst_paise": 0,
        "igst_paise": 0, "cess_paise": 0,
    }


def test_the_report_names_the_rule_and_asks_for_review():
    out = compare_payloads(_payload(), _payload())

    assert "§37" in out["rule"]
    assert out["ca_review_required"] is True, "this reports drift; it drafts no amendment"


# ── an invoice raised after filing ───────────────────────────────────────────

def test_an_invoice_missing_from_the_return_goes_in_the_current_period():
    """It was never declared, so there is no filed entry to amend. Table 9A
    amends something that exists; this belongs in the current period's own
    ordinary table."""
    filed = _payload(b2b=[_b2b("INV-1", 100_000, 9_000, 9_000)])
    books = _payload(b2b=[_b2b("INV-1", 100_000, 9_000, 9_000), _b2b("INV-2", 50_000, 4_500, 4_500)])

    out = compare_payloads(filed, books)

    missing = out["documents"]["missing_from_return"]
    assert [d["doc_no"] for d in missing] == ["INV-2"]
    assert missing[0]["declare_in"] == DECLARE_CURRENT
    assert out["clean"] is False


# ── an invoice deleted after filing ──────────────────────────────────────────

def test_an_invoice_gone_from_the_books_is_reported_against_the_amendment_table():
    """A filed return cannot simply drop a document it declared."""
    filed = _payload(b2b=[_b2b("INV-1", 100_000, 9_000, 9_000)])

    out = compare_payloads(filed, _payload())

    gone = out["documents"]["missing_from_books"]
    assert [d["doc_no"] for d in gone] == ["INV-1"]
    assert gone[0]["declare_in"] == AMEND_INVOICE


def test_a_credit_note_gone_from_the_books_amends_in_9C_not_9A():
    """Notes have their own amendment table — filing an amended note in 9A
    would be the wrong table."""
    filed = _payload(cdnr=[{"ctin": "27B", "nt": [{
        "ntty": "C", "nt_num": "CN-1", "nt_dt": "11-06-2025", "val": 118.0,
        "itms": _itms(10_000, 900, 900)}]}])

    out = compare_payloads(filed, _payload())

    assert out["documents"]["missing_from_books"][0]["declare_in"] == AMEND_NOTE


# ── an invoice edited after filing ───────────────────────────────────────────

def test_a_changed_amount_reports_the_delta_per_tax_head():
    """GSTR-3B table 3.1 and every amendment need the heads separately."""
    filed = _payload(b2b=[_b2b("INV-1", 100_000, 9_000, 9_000)])
    books = _payload(b2b=[_b2b("INV-1", 120_000, 10_800, 10_800)])

    out = compare_payloads(filed, books)

    changed = out["documents"]["amount_changed"]
    assert len(changed) == 1
    assert changed[0]["doc_no"] == "INV-1"
    assert changed[0]["delta"] == {
        "taxable_paise": 20_000, "cgst_paise": 1_800, "sgst_paise": 1_800,
        "igst_paise": 0, "cess_paise": 0,
    }
    assert changed[0]["filed"]["taxable_paise"] == 100_000
    assert changed[0]["books"]["taxable_paise"] == 120_000
    assert changed[0]["declare_in"] == AMEND_INVOICE


def test_a_reduction_reports_a_negative_delta():
    """Direction matters — the CA needs to know which way the return moved."""
    filed = _payload(b2b=[_b2b("INV-1", 100_000, 9_000, 9_000)])
    books = _payload(b2b=[_b2b("INV-1", 80_000, 7_200, 7_200)])

    assert compare_payloads(filed, books)["documents"]["amount_changed"][0]["delta"]["taxable_paise"] == -20_000


def test_a_one_paisa_change_is_still_a_finding():
    """The whole point is that nothing moves silently."""
    filed = _payload(b2b=[_b2b("INV-1", 100_000, 9_000, 9_000)])
    books = _payload(b2b=[_b2b("INV-1", 100_001, 9_000, 9_000)])

    assert compare_payloads(filed, books)["clean"] is False


# ── an invoice reclassified after filing ─────────────────────────────────────

def test_a_document_that_changed_table_is_reported_as_reclassified():
    """An SEZ supply filed as ordinary B2B — exactly what task #150 made
    possible to record and #156 made possible to enter. Amending the value
    alone would leave it in the wrong table."""
    filed = _payload(b2b=[_b2b("INV-1", 100_000, 9_000, 9_000)])
    books = _payload(exp=[{"exp_typ": "WOPAY", "inv": [{
        "inum": "INV-1", "idt": "10-06-2025", "val": 1000.0, "itms": _itms(100_000)}]}])

    out = compare_payloads(filed, books)

    rec = out["documents"]["reclassified"]
    assert len(rec) == 1
    assert rec[0]["filed_section"] == "b2b"
    assert rec[0]["books_section"] == "exp"
    assert rec[0]["declare_in"] == AMEND_INVOICE


def test_a_reclassified_document_is_not_also_counted_as_an_amount_change():
    """Otherwise one document appears twice and every total double-counts it."""
    filed = _payload(b2b=[_b2b("INV-1", 100_000, 9_000, 9_000)])
    books = _payload(exp=[{"exp_typ": "WOPAY", "inv": [{
        "inum": "INV-1", "idt": "10-06-2025", "val": 1000.0, "itms": _itms(100_000)}]}])

    out = compare_payloads(filed, books)

    assert out["documents"]["amount_changed"] == []
    assert out["finding_count"] == 1


# ── B2CS, at the only grain it has ───────────────────────────────────────────

def _b2cs(txval, camt=0, samt=0, iamt=0, rate=18.0, pos="27", sply="INTRA",
          key="sply_tp"):
    """A filed B2CS row.

    `key` defaults to the OLD misspelling on purpose. This function parses
    returns that are already filed and stored, and every one saved before the
    spelling was corrected against the GSTN Returns Offline Tool carries
    "sply_tp". If the report stopped reading it, INTER and INTRA would collapse
    into one empty-keyed bucket and a correctly filed historical return would be
    reported as differing from the books.
    """
    return {key: sply, "rt": rate, "pos": pos,
            "txval": txval / 100, "camt": camt / 100, "samt": samt / 100,
            "iamt": iamt / 100, "csamt": 0}


@pytest.mark.parametrize("key", ["sply_ty", "sply_tp"])
def test_both_spellings_of_the_supply_type_key_are_read(key):
    """New returns carry sply_ty; stored ones carry sply_tp. A return that
    matches its books must reconcile under either."""
    rows = [_b2cs(100_000, 9_000, 9_000, sply="INTRA", key=key),
            _b2cs(50_000, iamt=9_000, sply="INTER", pos="29", key=key)]
    out = compare_payloads(_payload(b2cs=rows), _payload(b2cs=rows))
    assert out["finding_count"] == 0, out["findings"]


@pytest.mark.parametrize("key", ["sply_ty", "sply_tp"])
def test_inter_and_intra_stay_separate_under_either_spelling(key):
    """The guard on the test above: if the key were unreadable, both rows would
    land in one bucket, their totals would still tie, and the test would pass
    while the grouping was broken."""
    filed = _payload(b2cs=[_b2cs(100_000, 9_000, 9_000, sply="INTRA", key=key),
                           _b2cs(50_000, iamt=9_000, sply="INTER", pos="29", key=key)])
    books = _payload(b2cs=[_b2cs(100_000, 9_000, 9_000, sply="INTER", pos="29", key=key),
                           _b2cs(50_000, iamt=9_000, sply="INTRA", key=key)])
    out = compare_payloads(filed, books)
    assert out["finding_count"] > 0, (
        "the two supply types were swapped and nothing was reported — they are "
        "being merged into a single bucket")


def test_b2cs_is_compared_as_totals_because_it_carries_no_invoice_number():
    filed = _payload(b2cs=[_b2cs(100_000, 9_000, 9_000)])
    books = _payload(b2cs=[_b2cs(130_000, 11_700, 11_700)])

    out = compare_payloads(filed, books)

    changed = out["b2cs"]["changed"]
    assert len(changed) == 1
    assert changed[0]["delta"]["taxable_paise"] == 30_000
    assert changed[0]["declare_in"] == AMEND_B2CS
    assert changed[0]["rate"] == 18.0
    assert changed[0]["place_of_supply"] == "27"


def test_b2cs_rows_at_different_rates_are_separate_findings():
    """GSTN requires a distinct row per rate; a correction is declared the
    same way, so merging them would misstate both."""
    filed = _payload(b2cs=[_b2cs(100_000, 9_000, 9_000, rate=18.0)])
    books = _payload(b2cs=[_b2cs(100_000, 9_000, 9_000, rate=18.0),
                           _b2cs(50_000, 1_250, 1_250, rate=5.0)])

    assert len(compare_payloads(filed, books)["b2cs"]["changed"]) == 1


def test_interstate_and_intrastate_b2cs_never_merge():
    """The GSTN spec keeps sply_tp separate even at identical rate and POS."""
    filed = _payload(b2cs=[_b2cs(100_000, 9_000, 9_000, sply="INTRA")])
    books = _payload(b2cs=[_b2cs(100_000, 9_000, 9_000, sply="INTRA"),
                           _b2cs(40_000, iamt=7_200, sply="INTER")])

    changed = compare_payloads(filed, books)["b2cs"]["changed"]

    assert len(changed) == 1
    assert changed[0]["supply_type"] == "INTER"


def test_the_report_says_why_b2cs_has_no_document_detail():
    """An empty per-document list must not read as "B2CS is unchanged"."""
    out = compare_payloads(_payload(), _payload())

    assert "no invoice number" in out["b2cs"]["note"].lower()


def test_b2cs_is_not_indexed_as_a_document():
    assert index_documents(_payload(b2cs=[_b2cs(100_000, 9_000, 9_000)])) == {}
    assert len(index_b2cs(_payload(b2cs=[_b2cs(100_000, 9_000, 9_000)]))) == 1


# ── how it reads ─────────────────────────────────────────────────────────────

def test_the_largest_movement_comes_first():
    filed = _payload(b2b=[_b2b("SMALL", 10_000), _b2b("BIG", 10_000)])
    books = _payload(b2b=[_b2b("SMALL", 10_100), _b2b("BIG", 90_000)])

    changed = compare_payloads(filed, books)["documents"]["amount_changed"]

    assert [c["doc_no"] for c in changed] == ["BIG", "SMALL"]


def test_totals_cover_documents_and_b2cs_together():
    """A CA reading only the totals must not be shown a number that silently
    excludes B2C sales."""
    filed = _payload(b2b=[_b2b("INV-1", 100_000, 9_000, 9_000)],
                     b2cs=[_b2cs(50_000, 4_500, 4_500)])
    books = _payload(b2b=[_b2b("INV-1", 100_000, 9_000, 9_000)],
                     b2cs=[_b2cs(70_000, 6_300, 6_300)])

    out = compare_payloads(filed, books)

    assert out["totals"]["delta"]["taxable_paise"] == 20_000
    assert out["totals"]["delta"]["cgst_paise"] == 1_800


def test_every_reported_amount_is_an_integer_number_of_paise():
    """CLAUDE.md — a float here would survive most assertions and fail on a
    figure nobody tested."""
    filed = _payload(b2b=[_b2b("INV-1", 100_003, 9_001, 9_001)],
                     b2cs=[_b2cs(50_007, 4_501, 4_501)])
    books = _payload(b2b=[_b2b("INV-1", 120_011, 10_801, 10_801)],
                     b2cs=[_b2cs(70_013, 6_301, 6_301)])

    out = compare_payloads(filed, books)

    for key, value in out["totals"]["delta"].items():
        assert isinstance(value, int), f"totals.delta.{key} is {type(value).__name__}"
    for finding in out["documents"]["amount_changed"] + out["b2cs"]["changed"]:
        for key, value in finding["delta"].items():
            assert isinstance(value, int), f"{key} is {type(value).__name__}"


@pytest.mark.parametrize("filed,books", [(None, None), ({}, None), (None, {})])
def test_a_missing_payload_on_either_side_does_not_crash(filed, books):
    """A return submitted before payloads were persisted has no payload_json."""
    out = compare_payloads(filed, books)

    assert out["clean"] is True
