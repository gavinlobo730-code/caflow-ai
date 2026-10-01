"""gst-12 — two documents the matcher could not tie together are OFFERED to the CA
as a probable pair, and offering them changes nothing.

WHAT WAS MISSING
    `itc_matching.reconcile` is exact on purpose (GSTIN plus folded number, and
    the AMOUNT is never fuzzy). So a bill booked under a supplier GSTIN with one
    character wrong came back as two unrelated rows — `missing_in_2b` for the
    bill, `missing_in_books` for the document the supplier DID file — and the CA
    was left to notice they were one invoice, or to phone a supplier who had
    done nothing wrong.

THE SHAPE OF THESE TESTS
    The finding's verify line has two halves and both are here: a probable pair
    is suggested, AND the Rule 36(4) verdict and the credit claimed stay exactly
    as they were until the bill is corrected. The second half is the one that
    matters, so it is asserted against what the reconciliation STORED and what
    the return's own per-document pass reads back — not against the suggestion.

    The negative control is a pair that must never appear: an exact match, and
    an `amount_mismatch` whose key matched (already linked), neither of which
    is a "probable" anything.
"""
from __future__ import annotations

import ast
import inspect

import pytest

from domain.gst import itc_matching, itc_probable, rule_36_4
from domain.gst.itc_matching import BookBill, PortalDocument, reconcile
from domain.gst.itc_probable import (
    KIND_AMOUNT, KIND_GSTIN, KIND_NUMBER, POSSIBLE, STRONG,
    edit_distance, suggest, suggest_between,
)
from services import gst_2b_reconciliation_service as svc
from services import gst_return_service

SUPPLIER = "29AAAAA1111A1Z5"
# One character wrong in the middle of the PAN — what a slip of the hand makes.
TYPO = "29AAAAA1111B1Z5"
# The same PAN registered in another State (Maharashtra), a different registration.
SAME_PAN_OTHER_STATE = "27AAAAA1111A1Z5"
CLIENT_GSTIN = "29AAACX1234C1ZP"


def _bill(bill_no="INV-0042", gstin=SUPPLIER, date="2025-04-24", taxable=1_00_000,
          cgst=9_000, sgst=9_000, igst=0, bill_id="b1"):
    return BookBill(bill_id=bill_id, supplier_gstin=gstin, bill_no=bill_no,
                    bill_date=date, taxable_paise=taxable, igst_paise=igst,
                    cgst_paise=cgst, sgst_paise=sgst)


def _doc(number="INV-0042", gstin=SUPPLIER, date="2025-04-24", taxable=1_00_000,
         cgst=9_000, sgst=9_000, igst=0, dtype="invoice", itc="Y", name="Acme Supplies"):
    return PortalDocument(section="b2b", document_type=dtype, supplier_gstin=gstin,
                          supplier_name=name, document_number=number,
                          document_date=date, taxable_paise=taxable,
                          igst_paise=igst, cgst_paise=cgst, sgst_paise=sgst,
                          cess_paise=0, itc_available=itc)


def _one(bill, doc):
    got = suggest_between([bill], [doc])
    return got[0] if got else None


# ═════════════════════════════════════════════════════════════════════════════
# THE RULE — pure
# ═════════════════════════════════════════════════════════════════════════════

def test_a_one_character_wrong_gstin_with_everything_else_agreeing_is_strong():
    got = _one(_bill(gstin=TYPO), _doc())
    assert got is not None
    assert got.kind == KIND_GSTIN and got.grade == STRONG
    assert any("1 character(s)" in e for e in got.evidence), got.evidence
    assert any("agree to the paisa" in e for e in got.evidence)
    assert TYPO in got.action and SUPPLIER in got.action
    assert "do not chase the supplier" in got.action


def test_the_same_pan_in_another_state_is_named_as_that():
    got = _one(_bill(gstin=SAME_PAN_OTHER_STATE), _doc())
    assert got.kind == KIND_GSTIN and got.grade == STRONG
    assert any("same PAN" in e for e in got.evidence)


def test_a_bill_whose_supplier_has_no_gstin_is_offered_the_one_2b_carries():
    got = _one(_bill(gstin=""), _doc())
    assert got.kind == KIND_GSTIN and got.grade == STRONG
    assert any("no GSTIN recorded" in e for e in got.evidence)
    assert "Record the GSTIN" in got.action and SUPPLIER in got.action


def test_a_gstin_that_fails_its_check_digit_is_said_to():
    # SUPPLIER is not the real registration of anything, but what matters is the
    # asymmetry the sentence reports: one side's check digit fails, the other's
    # passes. 27AAPFU0939F1ZV is the repository's own valid example.
    valid = "27AAPFU0939F1ZV"
    wrong = "27AAPFU0939F1ZW"
    got = _one(_bill(gstin=wrong), _doc(gstin=valid))
    assert got is not None
    assert any("fails its own check digit" in e for e in got.evidence)


def test_the_same_number_under_an_unrelated_gstin_with_other_amounts_is_a_coincidence():
    unrelated = "07BBBBB2222B1Z9"
    assert _one(_bill(gstin=unrelated, taxable=50_000, cgst=4_500, sgst=4_500),
                _doc()) is None


def test_the_same_number_and_amounts_under_an_unrelated_gstin_is_only_possible():
    unrelated = "07BBBBB2222B1Z9"
    got = _one(_bill(gstin=unrelated), _doc())
    assert got.kind == KIND_GSTIN and got.grade == POSSIBLE


def test_a_conflicting_date_rules_out_a_gstin_pair_unless_everything_else_is_exact():
    related_but_dated_differently = _one(
        _bill(gstin=TYPO, date="2025-04-01", taxable=99_000, cgst=8_000, sgst=8_000),
        _doc())
    assert related_but_dated_differently is None
    # Exact amounts and a related GSTIN survive a wrong date — as POSSIBLE.
    kept = _one(_bill(gstin=TYPO, date="2025-04-01"), _doc())
    assert kept.grade == POSSIBLE
    assert any("dates differ" in e for e in kept.evidence)


def test_a_transposed_number_with_the_same_date_and_amounts_is_strong():
    got = _one(_bill(bill_no="INV-0024"), _doc(number="INV-0042"))
    assert got.kind == KIND_NUMBER and got.grade == STRONG
    assert "Check the bill number" in got.action
    assert "supplier's own" in got.action, "the number is theirs, not ours"


def test_a_near_number_with_a_different_amount_is_NOT_offered():
    """Sequential invoices are one digit apart — that alone proves nothing."""
    assert _one(_bill(bill_no="INV-0041", taxable=2_00_000, cgst=18_000, sgst=18_000),
                _doc(number="INV-0042")) is None


def test_a_near_number_within_a_rupee_needs_the_date_to_agree_and_is_only_possible():
    near = dict(bill_no="INV-0024", taxable=1_00_050, cgst=9_050, sgst=9_000)
    got = _one(_bill(**near), _doc(number="INV-0042"))
    assert got.kind == KIND_NUMBER and got.grade == POSSIBLE
    assert any("within ₹1" in e for e in got.evidence)
    assert _one(_bill(date="2025-04-02", **near), _doc(number="INV-0042")) is None


def test_a_near_number_with_exact_amounts_and_no_date_is_possible():
    got = _one(_bill(bill_no="INV-0024", date=None), _doc(number="INV-0042"))
    assert got.kind == KIND_NUMBER and got.grade == POSSIBLE


def test_short_numbers_are_never_close():
    """'1' and '2' are one edit apart and are not the same invoice: closeness is
    not a clue below a few characters, so only the weaker kind can apply."""
    assert itc_probable._numbers_are_close("1", "2") is False
    assert itc_probable._numbers_are_close("INV1", "INV2") is True
    assert _one(_bill(bill_no="1", date="2025-04-02"), _doc(number="2")) is None
    got = _one(_bill(bill_no="1"), _doc(number="2"))
    assert got.kind == KIND_AMOUNT and got.grade == POSSIBLE, (
        "same supplier, day and amounts is still worth a look — as the weakest kind")


def test_same_supplier_day_and_amounts_with_an_unrelated_number_is_possible_only():
    got = _one(_bill(bill_no="PO/77"), _doc(number="INV-0042"))
    assert got.kind == KIND_AMOUNT and got.grade == POSSIBLE
    assert "both stand" in got.action


def test_an_amount_alone_is_never_enough():
    assert _one(_bill(bill_no="PO/77", date="2025-04-02"), _doc()) is None
    assert _one(_bill(bill_no="PO/77", taxable=1_00_050, cgst=9_050), _doc()) is None


def test_two_nil_documents_agreeing_is_not_a_clue():
    nil_bill = _bill(bill_no="PO/77", taxable=0, cgst=0, sgst=0)
    nil_doc = _doc(taxable=0, cgst=0, sgst=0)
    assert _one(nil_bill, nil_doc) is None


def test_a_credit_note_a_debit_note_and_an_import_are_not_compared_with_a_bill():
    for dtype in ("credit_note", "debit_note", "bill_of_entry"):
        rec = reconcile([_bill(gstin=TYPO)], [_doc(dtype=dtype)])
        assert suggest(rec) == [], dtype


def test_strongest_first_then_the_larger_credit():
    strong_small = _bill(bill_id="s", gstin=TYPO, bill_no="A-1001",
                         taxable=10_000, cgst=900, sgst=900)
    possible_big = _bill(bill_id="p", bill_no="PO/77", gstin=SUPPLIER,
                         taxable=9_00_000, cgst=81_000, sgst=81_000, date="2025-04-24")
    docs = [_doc(number="A-1001", taxable=10_000, cgst=900, sgst=900),
            _doc(number="INV-9", taxable=9_00_000, cgst=81_000, sgst=81_000)]
    got = suggest_between([possible_big, strong_small], docs)
    assert [p.grade for p in got] == [STRONG, POSSIBLE]
    assert got[0].bill.bill_id == "s"


def test_one_answer_per_pair_and_a_document_may_be_offered_to_several_bills():
    docs = [_doc()]
    bills = [_bill(bill_id="x", gstin=TYPO), _bill(bill_id="y", gstin=SAME_PAN_OTHER_STATE)]
    got = suggest_between(bills, docs)
    assert sorted(p.bill.bill_id for p in got) == ["x", "y"], (
        "picking a winner for the CA is the guess this module is here to avoid")


@pytest.mark.parametrize("a,b,limit,expected", [
    ("ABC", "ABC", 2, 0), ("ABC", "ABD", 2, 1), ("ABCD", "ABDC", 2, 1),
    ("ABC", "ABCD", 2, 1), ("ABCDEF", "UVWXYZ", 2, 3),
])
def test_edit_distance_counts_a_swap_as_one(a, b, limit, expected):
    assert edit_distance(a, b, limit) == expected


# ── what must never be called probable ───────────────────────────────────────

def test_an_exact_match_never_appears_as_probable():
    rec = reconcile([_bill()], [_doc()])
    assert [m.status for m in rec.matches] == ["matched"]
    assert suggest(rec) == []


def test_an_amount_mismatch_is_already_linked_and_is_not_offered_again():
    """Same GSTIN, same number, tax a rupee out: the KEY matched, so the two are
    one `amount_mismatch` row. Offering it as a guess would present a finished
    link as a hunch."""
    rec = reconcile([_bill()], [_doc(cgst=9_050, sgst=9_050)])
    assert [m.status for m in rec.matches] == ["amount_mismatch"]
    assert suggest(rec) == []


def test_suggest_does_not_mutate_the_reconciliation():
    rec = reconcile([_bill(gstin=TYPO)], [_doc()])
    before = [(m.status, m.bill_id, m.difference_paise) for m in rec.matches]
    summary = dict(rec.summary())
    assert suggest(rec)
    assert [(m.status, m.bill_id, m.difference_paise) for m in rec.matches] == before
    assert rec.summary() == summary


def test_the_matcher_itself_still_has_no_tolerance_and_never_reads_the_suggestions():
    """The finding's own warning: a tolerance on the tax is a tolerance on the
    credit. The band lives in `itc_probable` and the matcher must not know it."""
    tree = ast.parse(inspect.getsource(itc_matching))
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert "domain.gst.itc_probable" not in imported
    assert not any(a.name.endswith("itc_probable")
                   for n in ast.walk(tree) if isinstance(n, ast.Import)
                   for a in n.names)
    assert "AMOUNT_BAND" not in inspect.getsource(itc_matching)
    # and the matcher's exactness is intact: one paisa out is a MISMATCH.
    rec = reconcile([_bill()], [_doc(sgst=9_001)])
    assert [m.status for m in rec.matches] == ["amount_mismatch"]


# ═════════════════════════════════════════════════════════════════════════════
# THE SERVICE — against a database that records what it was asked to write
# ═════════════════════════════════════════════════════════════════════════════

FIRM, CLIENT = "firm-1", "client-1"


class _R:
    def __init__(self, data):
        self.data = data


class _Q:
    def __init__(self, db, table):
        self.db, self.table = db, table
        self.rows = list(db.store.get(table, []))
        self._op, self._payload = None, None

    def select(self, *_a, **_k): return self
    def order(self, *_a, **_k): return self

    def limit(self, n):
        self.rows = self.rows[:n]
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

    def gt(self, k, v):
        self.rows = [r for r in self.rows if str(r.get(k) or "") > str(v)]
        return self

    def delete(self):
        self._op = "delete"
        return self

    def insert(self, rows):
        self._op, self._payload = "insert", rows
        return self

    def execute(self):
        if self._op == "delete":
            gone = {id(r) for r in self.rows}
            self.db.store[self.table] = [r for r in self.db.store.get(self.table, [])
                                         if id(r) not in gone]
            return _R([])
        if self._op == "insert":
            rows = self._payload if isinstance(self._payload, list) else [self._payload]
            self.db.store.setdefault(self.table, []).extend(dict(r) for r in rows)
            return _R([])
        return _R(self.rows)


class _DB:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return _Q(self, name)


def _file(inum="INV-0042", ctin=SUPPLIER, dt="24-04-2025"):
    return {"data": {"gstin": CLIENT_GSTIN, "rtnprd": "042025", "gendt": "14-05-2025",
                     "docdata": {"b2b": [
                         {"ctin": ctin, "trdnm": "Acme Supplies", "supfildt": "10-05-2025",
                          "inv": [{"inum": inum, "dt": dt, "val": 1180.0, "itcavl": "Y",
                                   "items": [{"num": 1, "rt": 18.0, "txval": 1000.0,
                                              "cgst": 90.0, "sgst": 90.0, "igst": 0}]}]}]}}}


def _world(vendor_gstin):
    return {
        "vendors": [{"id": "v1", "firm_id": FIRM, "gstin": vendor_gstin}],
        "purchase_bills": [
            {"id": "b1", "firm_id": FIRM, "client_id": CLIENT, "vendor_id": "v1",
             "bill_no": "INV-0042", "bill_date": "2025-04-24",
             "taxable_amount_paise": 1_00_000, "cgst_paise": 9_000,
             "sgst_paise": 9_000, "igst_paise": 0, "status": "received",
             "deleted_at": None, "created_at": "2025-04-24T05:00:00+00:00"}],
        "gstr2a_records": [], "gstr2b_reconciliations": [],
    }


def _reconcile(store, raw=None):
    return svc.reconcile_2b(_DB(store), firm_id=FIRM, client_id=CLIENT,
                            period="042025", raw=raw or _file())


def test_PREMISE_with_the_right_gstin_the_same_two_documents_simply_match():
    """What every assertion below is the absence of."""
    out = _reconcile(_world(SUPPLIER))
    assert out["summary"]["matched_count"] == 1
    assert out["probable_matches"] == [], "an exact match is never probable"


def test_a_bill_under_a_wrong_gstin_is_offered_the_document_and_nothing_else_moves():
    store = _world(TYPO)
    out = _reconcile(store)

    # the suggestion ------------------------------------------------------
    (pair,) = out["probable_matches"]
    assert pair["kind"] == KIND_GSTIN and pair["grade"] == STRONG
    assert pair["bill_id"] == "b1" and pair["bill_supplier_gstin"] == TYPO
    assert pair["document_supplier_gstin"] == SUPPLIER
    assert pair["document_number"] == "INV-0042"
    assert pair["changes_credit"] is False
    assert out["summary"]["matched_count"] == 0

    # the reconciliation's own verdicts are UNCHANGED ------------------------
    statuses = sorted(m["status"] for m in out["matches"])
    assert statuses == ["missing_in_2b", "missing_in_books"]
    assert out["summary"]["missing_in_2b_count"] == 1
    assert out["summary"]["missing_in_books_count"] == 1
    assert out["summary"]["itc_at_risk_paise"] == 18_000, (
        "the credit the bill carries is still at risk — a suggestion rescues none")
    assert out["defaulters"][0]["supplier_gstin"] == TYPO

    # what was STORED carries no link -------------------------------------
    (row,) = store["gstr2a_records"]
    assert row["purchase_bill_id"] is None
    assert row["match_status"] == "missing_in_books"
    assert row["match_status"] not in ("matched", "amount_mismatch")

    # and the return's own §16(2)(aa) pass still WITHHOLDS the credit --------
    two_b = gst_return_service._two_b_by_document(store["gstr2a_records"])
    assert "b1" not in two_b
    assessment = rule_36_4.assess(
        [rule_36_4.BookDocument(document_id="b1", label="INV-0042",
                                supplier="Acme", cgst_paise=9_000, sgst_paise=9_000)],
        two_b, have_2b=True)
    assert [v.verdict for v in assessment.verdicts] == [rule_36_4.NOT_IN_2B]
    assert assessment.withheld_total_paise == 18_000
    assert assessment.allowed_cgst_paise == 0


def test_correcting_the_supplier_and_running_again_turns_the_suggestion_into_a_match():
    store = _world(TYPO)
    assert _reconcile(store)["probable_matches"]

    store["vendors"][0]["gstin"] = SUPPLIER          # the CA corrects the vendor
    again = _reconcile(store)

    assert again["probable_matches"] == []
    assert again["summary"]["matched_count"] == 1
    (row,) = store["gstr2a_records"]
    assert row["purchase_bill_id"] == "b1" and row["match_status"] == "matched"
    two_b = gst_return_service._two_b_by_document(store["gstr2a_records"])
    assessment = rule_36_4.assess(
        [rule_36_4.BookDocument(document_id="b1", label="INV-0042", supplier="Acme",
                                cgst_paise=9_000, sgst_paise=9_000)],
        two_b, have_2b=True)
    assert [v.verdict for v in assessment.verdicts] == [rule_36_4.ALLOWED]
    assert assessment.withheld_total_paise == 0


def test_a_file_that_is_not_a_2b_still_answers_with_an_empty_suggestion_list():
    out = svc.reconcile_2b(_DB(_world(SUPPLIER)), firm_id=FIRM, client_id=CLIENT,
                           period="042025", raw={"invoices": []})
    assert out["persisted"] is False and out["probable_matches"] == []


def test_the_service_writes_the_same_rows_with_and_without_the_suggestion_step(monkeypatch):
    """The suggestion is computed AFTER the write, so it cannot reach a row.
    Prove it by making the suggestion step explode: the stored rows must be
    identical to those of a run where it does not."""
    plain = _world(TYPO)
    _reconcile(plain)

    boom = _world(TYPO)

    def explode(_rec):
        raise RuntimeError("the suggestion step ran")

    monkeypatch.setattr(svc.itc_probable, "suggest", explode)
    with pytest.raises(RuntimeError):
        _reconcile(boom)

    def strip(rows):
        return [{k: v for k, v in r.items() if k not in ("reconciled_at", "updated_at")}
                for r in rows]

    assert strip(boom["gstr2a_records"]) == strip(plain["gstr2a_records"])
