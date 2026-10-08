"""The GSTR-2B tab says what it shows, in the words it uses everywhere (PRE-A-001).

Found by driving the tab in Chromium on 08-10-2026 against a reconciled period:

  * the "Last reconciled for this period" line printed the raw status tokens
    (`amount_mismatch: 1, missing_in_books: 3`) while the bucket buttons beside it
    said "Amount mismatch" and "No bill in the books";
  * the amber note said "of matched credit is marked UNAVAILABLE" over a figure
    (`itc_blocked_by_2b_paise`) that sums EVERY document 2B marks unavailable,
    matched or not, so it described a smaller number than it printed;
  * a bill the supplier has not filed has no portal document to take a name from,
    so the row printed the supplier's GSTIN twice and the "chase these suppliers"
    list showed GSTINs with no names.

The words live in apps/web/lib/gst/recon2bBuckets.ts and the statuses are the
server's, so the two are held together HERE, from the side that owns the
vocabulary: a guard written in apps/web would assert the file against a copy of
itself.
"""
from __future__ import annotations

import re
from pathlib import Path

from domain.gst.itc_matching import BookBill, PortalDocument, defaulters, reconcile

API_ROOT = Path(__file__).resolve().parents[1]
WEB = API_ROOT.parent / "web"
BUCKETS = WEB / "lib" / "gst" / "recon2bBuckets.ts"
PAGE = WEB / "app" / "clients" / "[id]" / "compliance" / "gst" / "page.tsx"

GSTIN_A = "29AAAAA1111A1Z5"
GSTIN_B = "29BBBBB2222B1Z5"


def _bill(bill_id, no, taxable, cgst=0, sgst=0, gstin=GSTIN_A, name=""):
    return BookBill(bill_id=bill_id, supplier_gstin=gstin, bill_no=no,
                    bill_date="2025-04-24", taxable_paise=taxable,
                    igst_paise=0, cgst_paise=cgst, sgst_paise=sgst, supplier_name=name)


def _doc(no, taxable, cgst=0, sgst=0, gstin=GSTIN_A, itcavl="Y", name="Acme"):
    return PortalDocument(section="b2b", document_type="invoice",
                          supplier_gstin=gstin, supplier_name=name,
                          document_number=no, document_date="2025-04-24",
                          taxable_paise=taxable, igst_paise=0, cgst_paise=cgst,
                          sgst_paise=sgst, cess_paise=0, itc_available=itcavl)


def _all_four_answers():
    bills = [
        _bill("b1", "INV-1", 1_00_000, cgst=9_000, sgst=9_000),
        _bill("b2", "INV-2", 2_00_000, cgst=18_000, sgst=18_000),
        _bill("b3", "INV-3", 3_00_000, cgst=27_000, sgst=27_000, gstin=GSTIN_B),
    ]
    docs = [
        _doc("INV-1", 1_00_000, cgst=9_000, sgst=9_000),
        _doc("INV-2", 2_00_000, cgst=17_000, sgst=18_000),
        _doc("INV-9", 5_00_000, cgst=45_000, sgst=45_000),
    ]
    return reconcile(bills, docs)


# ── the words ────────────────────────────────────────────────────────────────

def test_the_screens_buckets_are_exactly_the_answers_the_matcher_gives():
    """The map holds one entry per status `reconcile` can produce, and no other.

    A status added to the matcher with no entry would show on the screen as its
    own raw words; an entry for a status the matcher never gives is a button that
    is always zero."""
    produced = {m.status for m in _all_four_answers().matches}
    assert produced == {"matched", "amount_mismatch", "missing_in_2b", "missing_in_books"}
    source = BUCKETS.read_text()
    on_screen = re.findall(r'\bstatus:\s*"([a-z0-9_]+)"', source)
    assert sorted(on_screen) == sorted(produced), on_screen


def test_the_saved_line_and_the_buttons_take_their_words_from_one_map():
    page = PAGE.read_text()
    assert "savedReconciliationBreakdown(saved.by_status)" in page
    assert "RECON_2B_BUCKETS.map" in page
    # The page keeps no second copy of the labels, and no longer prints a raw
    # status token.
    assert "const RECON_2B_BUCKETS" not in page
    assert not re.search(r"Object\.entries\(saved\.by_status\)", page), (
        "the saved line is built from the status map, not from the raw keys")
    for label in re.findall(r'\blabel:\s*"([^"]+)"', BUCKETS.read_text()):
        assert not re.search(r'\blabel:\s*"' + re.escape(label) + '"', page), (
            f"{label!r} is declared as a bucket label in the page as well as in the map")


# ── the amber note's figure ──────────────────────────────────────────────────

def test_the_blocked_figure_counts_every_document_2b_marks_unavailable_not_only_matched_ones():
    """The note is worded from this arithmetic, so the arithmetic is pinned.

    A document the books HAVE a bill for and one they have not both count: 2B has
    said the credit is unavailable for each, whatever the books hold."""
    rec = reconcile(
        [_bill("b1", "INV-1", 1_00_000, cgst=9_000, sgst=9_000)],
        [_doc("INV-1", 1_00_000, cgst=9_000, sgst=9_000, itcavl="N"),                 # matched
         _doc("INV-9", 5_00_000, cgst=45_000, sgst=45_000, itcavl="N", gstin=GSTIN_B)])  # no bill
    s = rec.summary()
    assert [m.status for m in rec.matches if m.document and m.document.document_number == "INV-9"] \
        == ["missing_in_books"]
    assert s["itc_blocked_by_2b_paise"] == 18_000 + 90_000
    assert s["itc_available_per_2b_paise"] == 0


def test_the_amber_note_describes_that_figure_and_does_not_call_it_matched_credit():
    page = PAGE.read_text()
    note = page[page.index("summary.itc_blocked_by_2b_paise > 0"):]
    note = note[:note.index("</p>")]
    flat = re.sub(r"\s+", " ", note)
    assert "of matched credit" not in flat
    assert "UNAVAILABLE" in flat and "§16(2)(aa)" in flat
    assert "whether or not the books hold the bill" in flat


# ── the supplier's name ──────────────────────────────────────────────────────

def test_the_chase_list_carries_the_vendors_name_from_the_books():
    rec = reconcile(
        [_bill("b1", "INV-1", 1_00_000, cgst=9_000, sgst=9_000, name="Ravindra Packaging"),
         _bill("b2", "INV-2", 2_00_000, cgst=18_000, sgst=18_000, name="Ravindra Packaging"),
         _bill("b3", "INV-3", 3_00_000, cgst=27_000, sgst=27_000, gstin=GSTIN_B)],   # no name recorded
        [])
    rows = {r["supplier_gstin"]: r for r in defaulters(rec)}
    assert rows[GSTIN_A]["supplier_name"] == "Ravindra Packaging"
    assert rows[GSTIN_A]["unfiled_count"] == 2
    assert rows[GSTIN_B]["supplier_name"] is None, "no name is None, not an invented one"


def test_a_name_is_for_the_reader_and_plays_no_part_in_matching():
    """Two parties type one supplier's name two ways. The key is the GSTIN and the
    number, so a different name on the bill and in the file is still a match."""
    rec = reconcile(
        [_bill("b1", "INV-1", 1_00_000, cgst=9_000, sgst=9_000, name="RAVINDRA PACKAGING PVT LTD")],
        [_doc("INV-1", 1_00_000, cgst=9_000, sgst=9_000, name="Ravindra Packaging Private Limited")])
    assert [m.status for m in rec.matches] == ["matched"]


# ── the service: the vendor's name is read, and a row carries it ─────────────

class _Query:
    def __init__(self, store, table, log):
        self.store, self.table, self.log = store, table, log
        self.rows = list(store.get(table, []))

    def select(self, projection, *_a, **_k):
        self.log.append((self.table, projection))
        return self

    def eq(self, k, v):
        self.rows = [r for r in self.rows if str(r.get(k)) == str(v)]
        return self

    def in_(self, k, values):
        values = {str(v) for v in values}
        self.rows = [r for r in self.rows if str(r.get(k)) in values]
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

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def execute(self):
        return type("R", (), {"data": self.rows})()


class _Db:
    def __init__(self, store):
        self.store, self.log = store, []

    def table(self, name):
        return _Query(self.store, name, self.log)


def _store():
    firm, client = "f1", "c1"
    return {
        "vendors": [
            {"id": "v1", "firm_id": firm, "gstin": GSTIN_A, "name": "  Ravindra Packaging  "},
            {"id": "v2", "firm_id": firm, "gstin": GSTIN_B, "name": None},
        ],
        "purchase_bills": [
            {"id": "b1", "firm_id": firm, "client_id": client, "vendor_id": "v1",
             "bill_no": "INV-1", "bill_date": "2025-04-10", "taxable_amount_paise": 1_00_000,
             "cgst_paise": 9_000, "sgst_paise": 9_000, "igst_paise": 0,
             "status": "received", "deleted_at": None, "is_opening": False},
            {"id": "b2", "firm_id": firm, "client_id": client, "vendor_id": "v2",
             "bill_no": "INV-2", "bill_date": "2025-04-11", "taxable_amount_paise": 2_00_000,
             "cgst_paise": 18_000, "sgst_paise": 18_000, "igst_paise": 0,
             "status": "received", "deleted_at": None, "is_opening": False},
        ],
    }


def test_read_book_bills_carries_the_vendors_trimmed_name_and_asks_for_the_column():
    from services import gst_2b_reconciliation_service as svc
    db = _Db(_store())
    bills = {b.bill_id: b for b in svc.read_book_bills(db, "f1", "c1", "042025")}
    assert bills["b1"].supplier_name == "Ravindra Packaging"
    assert bills["b2"].supplier_name == "", "a vendor with no name is an empty name, not 'None'"
    asked = [p for t, p in db.log if t == "vendors"]
    assert asked and all("name" in re.split(r"\s*,\s*", p) for p in asked), asked


def test_a_book_side_row_names_its_supplier_and_a_document_row_keeps_the_files_name():
    from services import gst_2b_reconciliation_service as svc
    rec = reconcile(
        [_bill("b1", "INV-1", 1_00_000, cgst=9_000, sgst=9_000, name="Ravindra Packaging"),
         _bill("b2", "INV-2", 2_00_000, cgst=18_000, sgst=18_000, gstin=GSTIN_B),
         _bill("b4", "INV-4", 4_00_000, cgst=36_000, sgst=36_000, name="Books Name", gstin="29CCCCC3333C1Z5")],
        [_doc("INV-4", 4_00_000, cgst=36_000, sgst=36_000, name="Portal Name", gstin="29CCCCC3333C1Z5")])
    rows = {m["bill_no"] or m["document_number"]: m for m in (svc._match_json(m) for m in rec.matches)}
    assert rows["INV-1"]["status"] == "missing_in_2b"
    assert rows["INV-1"]["supplier_name"] == "Ravindra Packaging"
    assert rows["INV-2"]["supplier_name"] is None, "no name anywhere stays None"
    assert rows["INV-4"]["supplier_name"] == "Portal Name", "the file's name wins where there is a document"


def test_a_document_with_an_empty_name_falls_back_to_the_books_name():
    from services import gst_2b_reconciliation_service as svc
    rec = reconcile(
        [_bill("b1", "INV-1", 1_00_000, cgst=9_000, sgst=9_000, name="Books Name")],
        [_doc("INV-1", 1_00_000, cgst=9_000, sgst=9_000, name="")])
    [row] = [svc._match_json(m) for m in rec.matches]
    assert row["supplier_name"] == "Books Name"


def test_the_chase_list_on_the_screen_shows_a_name_when_there_is_one():
    page = PAGE.read_text()
    assert "d.supplier_name" in page and "supplier_name?: string | null" in page
