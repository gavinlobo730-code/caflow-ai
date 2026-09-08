"""
GST-04 and PUR-11 — the 2A/2B reconciliation, both ends.

WHAT WAS WRONG
    Two things that both looked like a reconciliation and neither of which was.

    1. `POST /gst-workspace/gstr2b/upload` looked for `data.docDetails[]` keyed
       on `sgstin`. A GSTR-2B downloaded from the portal is
       `data.docdata.b2b[].inv[]` keyed on `ctin`, with the taxable value and
       the tax per RATE LINE in `items[]`. So every genuine file parsed to an
       empty list. The BOOKS side came out of the same pasted JSON —
       `raw["book_invoices"]` — so a CA who pasted a real download got
       "Matched 0, Mismatched 0, Missing 0": a clean result from comparing
       nothing against nothing.

    2. `/gst/reconciliation` matched in the BROWSER over a purchase register
       the CA had to export from this product and upload back into it, and
       persisted nothing. Reopening it next month started from zero.

    Nothing anywhere INSERTed into `gstr2a_records`, so `_gstr2a_for_period`
    always returned [] and every GSTR-3B ever computed printed
    `gstr2a_record_count: 0` in its Rule 36(4) working.

WHY IT MATTERS THIS MUCH
    §16(2)(aa), in force since 01-01-2022, makes input tax credit available
    only where the supplier has furnished the invoice in their outward return
    and it has been communicated to the recipient — and that communication IS
    GSTR-2B. So "which of my client's bills has the supplier not filed" is not
    a reporting nicety, it is the question that decides how much credit may be
    claimed this month. It is the single most-performed task in an Indian
    practice, and it could not be done here.
"""
from __future__ import annotations

import pytest

from domain.gst.gstr2b import parse_gstr2b, paise
from domain.gst.itc_matching import (
    BookBill, PortalDocument, defaulters, normalise_document_number, reconcile,
)


# ═════════════════════════════════════════════════════════════════════════════
# THE FILE
# ═════════════════════════════════════════════════════════════════════════════

def _b2b(inum, txval, cgst=0.0, sgst=0.0, igst=0.0, itcavl="Y", rsn="",
         ctin="29AAAAA1111A1Z5", dt="24-04-2025"):
    return {"ctin": ctin, "trdnm": "Acme Supplies", "supfildt": "10-05-2025",
            "inv": [{"inum": inum, "dt": dt, "val": txval + cgst + sgst + igst,
                     "itcavl": itcavl, "rsn": rsn,
                     "items": [{"num": 1, "rt": 18.0, "txval": txval,
                                "cgst": cgst, "sgst": sgst, "igst": igst}]}]}


def _file(**docdata):
    return {"data": {"gstin": "29AAACX1234C1ZP", "rtnprd": "042025",
                     "gendt": "14-05-2025", "docdata": docdata}}


def test_the_real_envelope_parses_and_the_old_one_does_not():
    """THE DEFECT, in one test. `docDetails`/`sgstin` is a shape the portal
    never produced; `data.docdata.b2b[].inv[]` is what a download contains."""
    real = parse_gstr2b(_file(b2b=[_b2b("INV-001", 1000.0, cgst=90.0, sgst=90.0)]))
    assert len(real.documents) == 1

    old = parse_gstr2b({"data": {"docDetails": [
        {"inum": "INV-001", "sgstin": "29AAAAA1111A1Z5", "txval": 1000.0}]}})
    assert old.documents == []
    assert any("docdata" in p for p in old.problems), (
        "and it must SAY so — an empty parse that reports nothing is the "
        "false clean result this replaces")


def test_the_tax_is_on_the_rate_lines_not_the_invoice_header():
    """`inv.val` is the invoice VALUE — taxable plus tax plus cess. Reading it
    as the taxable value overstates the credit being matched by the tax
    itself: on this document, 1,180 against 1,000."""
    f = parse_gstr2b(_file(b2b=[_b2b("INV-001", 1000.0, cgst=90.0, sgst=90.0)]))
    d = f.documents[0]
    assert d.taxable_value_paise == 1_00_000
    assert d.cgst_paise == 9_000 and d.sgst_paise == 9_000
    assert d.invoice_value_paise == 1_18_000
    assert d.total_tax_paise == 18_000


def test_rupees_convert_through_decimal_and_land_exactly():
    """The portal sends 729248.16 as a JSON number. float(x) * 100 is not
    guaranteed to land on 72924816."""
    assert paise(729248.16) == 7_29_24_816
    assert paise("19999.99") == 19_99_999
    assert paise(0) == 0 and paise(None) == 0
    assert paise("not a number") == 0


def test_itcavl_and_its_reason_survive_the_parse():
    """§16(2)(aa) makes the credit depend on what 2B SAYS. A reconciliation
    that matches an invoice and drops this flag tells a CA the credit is safe
    when the portal has already said it is not."""
    f = parse_gstr2b(_file(b2b=[_b2b("INV-9", 1000.0, cgst=90.0, sgst=90.0,
                                     itcavl="N", rsn="P")]))
    d = f.documents[0]
    assert d.itc_available == "N"
    assert d.itc_unavailable_reason_code == "P"
    assert "Place of supply" in d.itc_unavailable_reason


def test_a_credit_note_is_signed_negative():
    """A credit note REVERSES ITC in the recipient's hands. Treating it as an
    ordinary document would report more available credit than 2B allows, which
    is the direction that draws a reversal notice."""
    f = parse_gstr2b(_file(cdnr=[{"ctin": "29AAAAA1111A1Z5", "nt": [
        {"ntnum": "CN-1", "ntdt": "28-04-2025", "typ": "C", "val": 1180.0,
         "itms": [{"txval": 1000.0, "cgst": 90.0, "sgst": 90.0}]}]}]))
    d = f.documents[0]
    assert d.document_type == "credit_note"
    assert d.taxable_value_paise == -1_00_000
    assert d.total_tax_paise == -18_000


def test_a_debit_note_is_positive():
    f = parse_gstr2b(_file(cdnr=[{"ctin": "29AAAAA1111A1Z5", "nt": [
        {"ntnum": "DN-1", "ntdt": "28-04-2025", "typ": "D", "val": 1180.0,
         "itms": [{"txval": 1000.0, "cgst": 90.0, "sgst": 90.0}]}]}]))
    assert f.documents[0].document_type == "debit_note"
    assert f.documents[0].taxable_value_paise == 1_00_000


def test_an_import_has_no_supplier_gstin_and_says_so():
    """The document is a bill of entry and the tax is IGST paid at the port."""
    f = parse_gstr2b(_file(impg=[{"boenum": "9876543", "boedt": "20-04-2025",
                                  "portcd": "INNSA1", "txval": 50000, "igst": 9000}]))
    d = f.documents[0]
    assert d.document_type == "bill_of_entry"
    assert d.supplier_gstin == ""
    assert d.document_number == "9876543"
    assert d.igst_paise == 9_00_000


def test_an_amendment_is_marked_not_merged():
    """b2ba reports the amended document in its own section. Merging it needs
    the original's PERIOD, which this client may not have downloaded."""
    f = parse_gstr2b(_file(b2ba=[{"ctin": "29AAAAA1111A1Z5", "inv": [
        {"inum": "INV-001-R1", "oinum": "INV-001", "dt": "24-04-2025", "val": 1180.0,
         "items": [{"txval": 1000.0, "cgst": 90.0, "sgst": 90.0}]}]}]))
    d = f.documents[0]
    assert d.is_amendment is True
    assert d.amends_document_number == "INV-001"


def test_a_section_this_version_does_not_read_is_reported():
    """Silently ignoring a section is how a CA concludes their client has no
    imports from a file that had an import section."""
    f = parse_gstr2b(_file(b2b=[_b2b("INV-1", 1000.0)],
                           nonstandard=[{"x": 1}, {"x": 2}]))
    assert any("nonstandard" in p and "2 row" in p for p in f.problems)


def test_a_date_that_will_not_parse_is_None_not_a_guess():
    f = parse_gstr2b(_file(b2b=[_b2b("INV-1", 1000.0, dt="not a date")]))
    assert f.documents[0].document_date is None
    ok = parse_gstr2b(_file(b2b=[_b2b("INV-1", 1000.0, dt="24-04-2025")]))
    assert ok.documents[0].document_date == "2025-04-24"


# ═════════════════════════════════════════════════════════════════════════════
# THE MATCH
# ═════════════════════════════════════════════════════════════════════════════

GSTIN_A = "29AAAAA1111A1Z5"
GSTIN_B = "29BBBBB2222B1Z5"


def _bill(bill_id, no, taxable, cgst=0, sgst=0, igst=0, gstin=GSTIN_A):
    return BookBill(bill_id=bill_id, supplier_gstin=gstin, bill_no=no,
                    bill_date="2025-04-24", taxable_paise=taxable,
                    igst_paise=igst, cgst_paise=cgst, sgst_paise=sgst)


def _doc(no, taxable, cgst=0, sgst=0, igst=0, gstin=GSTIN_A, itcavl="Y"):
    return PortalDocument(section="b2b", document_type="invoice",
                          supplier_gstin=gstin, supplier_name="Acme",
                          document_number=no, document_date="2025-04-24",
                          taxable_paise=taxable, igst_paise=igst, cgst_paise=cgst,
                          sgst_paise=sgst, cess_paise=0, itc_available=itcavl)


@pytest.mark.parametrize("a,b", [
    ("INV/2025-26/0042", "inv 2025 26 42"),
    ("INV/2025-26/0042", "INV-2025-26-42"),
    ("0025/2025", "25/2025"),
    ("  INV.1  ", "inv/1"),
])
def test_the_document_number_folds_the_ways_one_number_gets_written(a, b):
    """A supplier writing "INV/2025-26/0042" and a data-entry hand writing
    "INV-2025-26-42" is the commonest cause of a false missing_in_2b — and
    chasing a supplier who did file costs the CA their credibility."""
    assert normalise_document_number(a) == normalise_document_number(b)


def test_zeros_inside_an_alphanumeric_serial_are_left_alone():
    """"S008400" and "S8400" are NOT folded together. A false match silently
    claims credit against the wrong document, which is the expensive
    direction; a false MISS is a phone call."""
    assert normalise_document_number("S008400") != normalise_document_number("S8400")


def test_the_four_answers_are_four():
    """matched / amount_mismatch / missing_in_2b / missing_in_books. The last
    two are OPPOSITE problems: one chases the supplier, the other chases the
    document. Reporting one figure for both sends the CA to the wrong party."""
    bills = [
        _bill("b1", "INV-1", 1_00_000, cgst=9_000, sgst=9_000),
        _bill("b2", "INV-2", 2_00_000, cgst=18_000, sgst=18_000),
        _bill("b3", "INV-3", 3_00_000, cgst=27_000, sgst=27_000),
    ]
    docs = [
        _doc("INV-1", 1_00_000, cgst=9_000, sgst=9_000),        # matches
        _doc("INV-2", 2_00_000, cgst=17_000, sgst=18_000),       # 1,000p short
        _doc("INV-9", 5_00_000, cgst=45_000, sgst=45_000),       # we hold no bill
    ]
    rec = reconcile(bills, docs)
    s = rec.summary()
    assert s["matched_count"] == 1
    assert s["amount_mismatch_count"] == 1
    assert s["missing_in_2b_count"] == 1     # INV-3
    assert s["missing_in_books_count"] == 1  # INV-9

    mismatch = rec.amount_mismatch[0]
    assert mismatch.difference_paise == 1_000, "books claim 1,000 paise more"
    assert "at risk" in mismatch.reason

    missing = rec.missing_in_2b[0]
    assert missing.bill_id == "b3"
    assert "chase the supplier" in missing.reason
    assert "chase the document" in rec.missing_in_books[0].reason


def test_a_matched_document_that_2B_marks_unavailable_still_says_so():
    """The figures agreeing does not make the credit claimable."""
    rec = reconcile([_bill("b1", "INV-1", 1_00_000, cgst=9_000, sgst=9_000)],
                    [_doc("INV-1", 1_00_000, cgst=9_000, sgst=9_000, itcavl="N")])
    m = rec.matched[0]
    assert m.status == "matched"
    assert "UNAVAILABLE" in m.reason
    s = rec.summary()
    assert s["itc_available_per_2b_paise"] == 0
    assert s["itc_blocked_by_2b_paise"] == 18_000


def test_the_summary_reports_the_figures_the_return_turns_on():
    """"Matched 12" is not an answer to "how much credit may I take"."""
    rec = reconcile(
        [_bill("b1", "INV-1", 1_00_000, cgst=9_000, sgst=9_000),
         _bill("b2", "INV-2", 2_00_000, cgst=18_000, sgst=18_000)],
        [_doc("INV-1", 1_00_000, cgst=9_000, sgst=9_000)])
    s = rec.summary()
    assert s["books_tax_paise"] == 18_000 + 36_000
    assert s["itc_available_per_2b_paise"] == 18_000
    assert s["itc_at_risk_paise"] == 36_000, (
        "the credit the books claim that 2B does not support — the figure "
        "§16(2)(aa) makes the CA hold back")


def test_a_bill_whose_vendor_has_no_gstin_surfaces_rather_than_vanishing():
    """It cannot key-match anything, so it is missing_in_2b. Dropping it would
    hide a bill from the one report that exists to find unfiled ones."""
    rec = reconcile([_bill("b1", "INV-1", 1_00_000, cgst=9_000, sgst=9_000, gstin="")],
                    [_doc("INV-1", 1_00_000, cgst=9_000, sgst=9_000)])
    assert rec.missing_in_2b[0].bill_id == "b1"
    assert rec.missing_in_books[0].document is not None


def test_one_document_is_consumed_once():
    """Two bills with the same number from one supplier must not both match the
    same 2B document — that would report credit twice."""
    rec = reconcile(
        [_bill("b1", "INV-1", 1_00_000, cgst=9_000, sgst=9_000),
         _bill("b2", "INV-1", 1_00_000, cgst=9_000, sgst=9_000)],
        [_doc("INV-1", 1_00_000, cgst=9_000, sgst=9_000)])
    assert len(rec.matched) == 1
    assert len(rec.missing_in_2b) == 1


def test_the_defaulter_list_is_worst_first_and_keyed_on_the_bill():
    """The whole point of a defaulter is that no portal document exists to take
    a name from, so the GSTIN comes off the BILL."""
    rec = reconcile(
        [_bill("b1", "INV-1", 1_00_000, cgst=9_000, sgst=9_000, gstin=GSTIN_A),
         _bill("b2", "INV-2", 5_00_000, cgst=45_000, sgst=45_000, gstin=GSTIN_B),
         _bill("b3", "INV-3", 1_00_000, cgst=9_000, sgst=9_000, gstin=GSTIN_B)],
        [])
    d = defaulters(rec)
    assert [r["supplier_gstin"] for r in d] == [GSTIN_B, GSTIN_A]
    assert d[0]["unfiled_count"] == 2
    assert d[0]["itc_at_risk_paise"] == 90_000 + 18_000
    assert sorted(d[0]["bill_ids"]) == ["b2", "b3"]


def test_no_bills_and_no_documents_is_not_a_match():
    """The false clean result, checked directly: nothing against nothing is
    four zeroes, and every one of them is honest only because there is
    genuinely nothing — which is why the SERVICE refuses to persist an empty
    parse at all."""
    s = reconcile([], []).summary()
    assert s["matched_count"] == 0 and s["missing_in_2b_count"] == 0


# ═════════════════════════════════════════════════════════════════════════════
# THE SERVICE — the books are read HERE, and the answer is kept
# ═════════════════════════════════════════════════════════════════════════════
#
# The reconciliation this replaces asked the CA to export the purchase register
# out of this product and upload it back in, and then threw the answer away on
# refresh. Both halves are the test below: the books come from the database,
# and gstr2a_records holds the result.

class _Q:
    def __init__(self, store, table):
        self.store, self.table = store, table
        self.rows = list(store.get(table, []))
        self._delete = False

    def select(self, *_a, **_k):
        return self

    def eq(self, k, v):
        self.rows = [r for r in self.rows if str(r.get(k)) == str(v)]
        return self

    def in_(self, k, vals):
        vals = {str(v) for v in vals}
        self.rows = [r for r in self.rows if str(r.get(k)) in vals]
        return self

    def is_(self, k, _v):
        self.rows = [r for r in self.rows if r.get(k) is None]
        return self

    def gte(self, k, v):
        self.rows = [r for r in self.rows if str(r.get(k) or "") >= v]
        return self

    def lte(self, k, v):
        self.rows = [r for r in self.rows if str(r.get(k) or "") <= v]
        return self

    def delete(self):
        self._delete = True
        return self

    def insert(self, rows):
        self.store.setdefault(self.table, []).extend(
            rows if isinstance(rows, list) else [rows])
        self.rows = []
        return self

    def execute(self):
        if self._delete:
            keep = [r for r in self.store.get(self.table, []) if r not in self.rows]
            self.store[self.table] = keep
        return type("R", (), {"data": self.rows})()


class _DB:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return _Q(self.store, name)


FIRM, CLIENT = "firm-1", "client-1"


def _store():
    return {
        "vendors": [
            {"id": "v1", "firm_id": FIRM, "gstin": GSTIN_A},
            {"id": "v2", "firm_id": FIRM, "gstin": GSTIN_B},
        ],
        "purchase_bills": [
            {"id": "b1", "firm_id": FIRM, "client_id": CLIENT, "vendor_id": "v1",
             "bill_no": "INV/2025-26/0001", "bill_date": "2025-04-10",
             "taxable_amount_paise": 1_00_000, "cgst_paise": 9_000,
             "sgst_paise": 9_000, "igst_paise": 0, "status": "received",
             "deleted_at": None},
            {"id": "b2", "firm_id": FIRM, "client_id": CLIENT, "vendor_id": "v2",
             "bill_no": "INV-77", "bill_date": "2025-04-20",
             "taxable_amount_paise": 5_00_000, "cgst_paise": 45_000,
             "sgst_paise": 45_000, "igst_paise": 0, "status": "paid",
             "deleted_at": None},
            # A DRAFT bill is not a document the supplier could have filed
            # against, so it must not appear as a defaulter.
            {"id": "b3", "firm_id": FIRM, "client_id": CLIENT, "vendor_id": "v1",
             "bill_no": "DRAFT-1", "bill_date": "2025-04-25",
             "taxable_amount_paise": 9_00_000, "cgst_paise": 81_000,
             "sgst_paise": 81_000, "igst_paise": 0, "status": "draft",
             "deleted_at": None},
            # Another month.
            {"id": "b4", "firm_id": FIRM, "client_id": CLIENT, "vendor_id": "v1",
             "bill_no": "MAY-1", "bill_date": "2025-05-02",
             "taxable_amount_paise": 1_00_000, "cgst_paise": 9_000,
             "sgst_paise": 9_000, "igst_paise": 0, "status": "received",
             "deleted_at": None},
        ],
        "gstr2a_records": [],
    }


def _reconcile(store, raw, period="042025"):
    from services import gst_2b_reconciliation_service as svc
    return svc.reconcile_2b(_DB(store), firm_id=FIRM, client_id=CLIENT,
                            period=period, raw=raw)


def test_the_books_side_comes_from_the_database():
    """The CALLER sends the portal file and nothing else. Asking a screen to
    supply the purchase register it is reconciling is asking it to supply the
    answer — which is what `raw["book_invoices"]` did."""
    store = _store()
    # The supplier filed b1, under a differently-punctuated number.
    result = _reconcile(store, _file(b2b=[
        _b2b("INV 2025 26 1", 1000.0, cgst=90.0, sgst=90.0, ctin=GSTIN_A)]))

    assert result["book_bill_count"] == 2, (
        "April's received and paid bills only — not the draft, not May")
    s = result["summary"]
    assert s["matched_count"] == 1, "the punctuation fold is what makes this 1"
    assert s["missing_in_2b_count"] == 1
    assert s["itc_at_risk_paise"] == 90_000


def test_the_answer_is_persisted_and_can_be_read_back():
    """The reason this exists: the browser reconciliation started from zero
    every time it was reopened."""
    from services import gst_2b_reconciliation_service as svc

    store = _store()
    _reconcile(store, _file(b2b=[
        _b2b("INV 2025 26 1", 1000.0, cgst=90.0, sgst=90.0, ctin=GSTIN_A)]))

    rows = store["gstr2a_records"]
    assert len(rows) == 1
    row = rows[0]
    assert row["purchase_bill_id"] == "b1", "the MATCH is what had nowhere to live"
    assert row["match_status"] == "matched"
    assert row["return_period"] == "042025"
    assert row["itc_available"] == "Y"
    assert row["source"] == "upload"

    back = svc.read_reconciliation(_DB(store), firm_id=FIRM, client_id=CLIENT,
                                   period="042025")
    assert back["record_count"] == 1
    assert back["by_status"] == {"matched": 1}


def test_a_second_upload_replaces_rather_than_doubling():
    """A CA re-uploads when the first download was for the wrong month. Two
    runs must not double the credit the Rule 36(4) working reads back."""
    store = _store()
    f = _file(b2b=[_b2b("INV 2025 26 1", 1000.0, cgst=90.0, sgst=90.0, ctin=GSTIN_A)])
    _reconcile(store, f)
    _reconcile(store, f)
    assert len(store["gstr2a_records"]) == 1


def test_an_unparseable_file_persists_NOTHING():
    """Writing zero rows and calling it reconciled is exactly the false clean
    result this replaces."""
    store = _store()
    result = _reconcile(store, {"invoices": [{"inum": "X", "sgstin": GSTIN_A}]})
    assert result["persisted"] is False
    assert result["summary"] is None
    assert store["gstr2a_records"] == []
    assert result["problems"]


def test_a_file_for_the_wrong_period_says_so():
    """The commonest real mistake, and the one an empty result used to hide."""
    store = _store()
    result = _reconcile(store, _file(b2b=[_b2b("INV-1", 1000.0, cgst=90.0, sgst=90.0)]),
                        period="052025")
    assert any("042025" in p and "052025" in p for p in result["problems"])


def test_the_defaulter_list_reaches_the_caller():
    store = _store()
    result = _reconcile(store, _file(b2b=[]))
    # An empty b2b section is a parseable file with no documents, which does
    # not persist — so ask for a file that HAS one, from the other supplier.
    result = _reconcile(store, _file(b2b=[
        _b2b("INV-77", 5000.0, cgst=450.0, sgst=450.0, ctin=GSTIN_B)]))
    assert [d["supplier_gstin"] for d in result["defaulters"]] == [GSTIN_A]
    assert result["defaulters"][0]["bill_ids"] == ["b1"]


def test_the_purchases_tab_can_ask_a_bill_whether_it_was_filed():
    """PUR-11's other half: there was no way to see, from the Purchases tab,
    that a specific bill was unmatched."""
    from services import gst_2b_reconciliation_service as svc

    store = _store()
    _reconcile(store, _file(b2b=[
        _b2b("INV 2025 26 1", 1000.0, cgst=90.0, sgst=90.0, ctin=GSTIN_A)]))
    got = svc.status_for_bills(_DB(store), firm_id=FIRM, client_id=CLIENT,
                               bill_ids=["b1", "b2"])
    assert got["b1"]["match_status"] == "matched"
    assert "b2" not in got, (
        "a bill with no 2B row has not been filed OR has not been reconciled, "
        "and the caller is given the row rather than a boolean so it can tell")


# ═════════════════════════════════════════════════════════════════════════════
# RULE 36(4) STARTS BITING — because the table finally has rows in it
# ═════════════════════════════════════════════════════════════════════════════
#
# `_gstr2a_for_period` always returned [] and `_apply_rule_36_4_cap` always took
# its no-data branch, so the ceiling has never been applied to any return this
# product has produced. Persisting the reconciliation changes that, and two
# things had to be corrected for it to be right rather than merely live.

def test_a_document_2B_blocks_does_not_raise_the_ceiling():
    """`itcavl = "N"` means the portal has already refused the credit. Counting
    it towards the Rule 36(4) cap would raise the ceiling by exactly the credit
    §16(2)(aa) exists to withhold."""
    import inspect

    from services import gst_return_service

    src = inspect.getsource(gst_return_service._gstr2a_for_period)
    assert 'neq("itc_available", "N")' in src, (
        "the Rule 36(4) ceiling must be built from documents 2B says are "
        "available, not from every document in the file")
    # `neq`, not `eq("Y")`: an import carries no itcavl at all and a row written
    # before migration 340 has an empty string, and excluding those would
    # silently SHRINK the cap.
    assert 'eq("itc_available", "Y")' not in src


def test_an_uploaded_2B_with_no_eligible_credit_caps_at_nil():
    """ZERO MEANS TWO DIFFERENT THINGS. Until this table had rows, a zero could
    only mean "nobody uploaded anything", and leaving book ITC alone was the
    honest answer. Now a 2B can be on file and show no eligible credit under a
    head — and for that the cap is genuinely nil."""
    from domain.gst.gstr3b_computer import _apply_rule_36_4_cap

    # Nothing on file: uncapped, as before.
    assert _apply_rule_36_4_cap(50_000, 0, False) == (50_000, False)
    # A 2B IS on file and shows nothing under this head: the cap is nil.
    assert _apply_rule_36_4_cap(50_000, 0, True) == (0, True)
    # And the ordinary case is unchanged.
    assert _apply_rule_36_4_cap(50_000, 80_000, True) == (50_000, False)
    assert _apply_rule_36_4_cap(90_000, 80_000, True) == (80_000, True)


def test_the_computer_passes_whether_a_2B_is_on_file():
    from domain.gst.gstr3b_computer import (
        GSTR2ARecord, PurchaseTransaction, compute_gstr3b,
    )

    purchases = [PurchaseTransaction(taxable_amount_paise=1_00_000,
                                     cgst_paise=9_000, sgst_paise=9_000,
                                     igst_paise=0, cess_paise=0,
                                     is_reverse_charge=False)]
    # No 2B at all — book ITC stands.
    assert compute_gstr3b([], purchases, []).itc_cgst == 9_000
    # A 2B on file that carries only IGST: the CGST ceiling is nil, because 2B
    # shows no CGST credit for the month.
    on_file = [GSTR2ARecord(cgst_paise=0, sgst_paise=0, igst_paise=5_000)]
    out = compute_gstr3b([], purchases, on_file)
    assert out.itc_cgst == 0
    assert out.itc_capped_by_2a is True
