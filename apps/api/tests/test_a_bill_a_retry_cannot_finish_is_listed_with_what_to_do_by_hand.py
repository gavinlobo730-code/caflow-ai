"""A purchase bill that "Complete the stock" cannot finish is listed with the words that say what to do by hand, and a retry for it moves nothing (POST-A-092, decided 27-11-2026).

The database half (which bills are found, and `hand_fix` on each) is `test_780_..._pg.py`. Held here, in mock mode: the words, that the list carries them
on exactly the documents that need them, that a retry for such a bill is refused in the same words BEFORE any stock function runs, that a document a retry
can finish and a finder that could not be asked are unaffected, and that a kind this code does not know is never a guess.
"""
from __future__ import annotations

import uuid

import pytest

from domain.inventory import stock_hand_fix as hf
from services import stock_effect_retry_service as svc
from tests.e2e_harness import FakeDB

FIRM, CLIENT = "firm-hf", "client-hf"


@pytest.fixture(autouse=True)
def _no_service_client(monkeypatch):
    monkeypatch.setattr("core.db_provider.service_db_or_none", lambda: None)


class _Rpc:
    def __init__(self, data):
        self.data = data

    def execute(self):
        return self


class _Db:
    """A client whose rpc answers what the finder would: the documents given."""
    def __init__(self, documents):
        self._documents = documents

    def rpc(self, name, args):
        assert name == "documents_with_unrecorded_stock"
        return _Rpc({"total": len(self._documents), "documents": self._documents})


def _doc(doc_id, *, hand_fix=None, reference="GS/114", kind="purchase_bill"):
    return {"kind": kind, "document_id": doc_id, "reference": reference, "document_date": "2026-04-20", "owed_lines": 1,
            "moved_lines": 1, "unjournalled_rows": 0, "hand_fix": hand_fix}


# ── the words ─────────────────────────────────────────────────────────────────

def test_each_kind_has_a_sentence_that_names_the_bill_says_what_to_post_and_how_it_leaves_the_list():
    for kind, must in ((hf.LANDED_CHARGES, ("freight", "Inventory")), (hf.OVERSOLD_TRUEUP, ("Cost of Goods Sold", "oversold"))):
        said = hf.says(kind, "Purchase bill GS/114")
        assert said.startswith("Purchase bill GS/114 ")
        for word in must:
            assert word in said, (kind, word)
        assert "mark it as settled by hand" in said, "the way off the list is named"
        assert "does not offer Complete the stock" in said, "the missing button is explained"


def test_a_sentence_never_names_an_amount_because_the_product_does_not_know_it():
    for kind in hf.KINDS:
        said = hf.says(kind, "Purchase bill X")
        assert "₹" not in said and "Rs" not in said and not any(ch.isdigit() for ch in said), said


def test_the_true_up_sentence_says_what_the_finder_cannot_see_and_the_charges_one_does_not():
    assert "only in part" in hf.says(hf.OVERSOLD_TRUEUP, "x")
    assert "only in part" not in hf.says(hf.LANDED_CHARGES, "x")


def test_a_kind_it_does_not_know_and_no_kind_have_no_sentence():
    assert hf.says(None, "x") is None and hf.says("something_new", "x") is None
    assert hf.known(None) is False and hf.known("something_new") is False


def test_the_refusal_is_the_same_words_and_says_nothing_was_moved():
    assert hf.refusal(hf.LANDED_CHARGES, "Purchase bill B-1").startswith(hf.says(hf.LANDED_CHARGES, "Purchase bill B-1"))
    assert hf.refusal(hf.LANDED_CHARGES, "Purchase bill B-1").endswith("Nothing was moved.")


# ── the list ────────────────────────────────────────────────────────────────

def test_the_list_carries_the_sentence_on_exactly_the_documents_that_need_it():
    a, b, c = (str(uuid.uuid4()) for _ in range(3))
    answer = svc.unrecorded_documents(_Db([_doc(a, hand_fix="landed_charges", reference="B-A"), _doc(b, hand_fix=None, reference="B-B"),
                                            _doc(c, hand_fix="oversold_trueup", reference="B-C")]), firm_id=FIRM, client_id=CLIENT)
    docs = {d["document_id"]: d for d in answer["documents"]}
    assert docs[a]["hand_fix_says"].startswith("Purchase bill B-A ") and docs[c]["hand_fix_says"].startswith("Purchase bill B-C ")
    assert "hand_fix_says" not in docs[b], "a document a retry can finish carries no sentence"
    assert answer["total"] == 3


def test_a_kind_the_code_does_not_know_is_listed_as_it_came_and_carries_no_guess():
    d = str(uuid.uuid4())
    answer = svc.unrecorded_documents(_Db([_doc(d, hand_fix="a_kind_from_a_newer_database")]), firm_id=FIRM, client_id=CLIENT)
    assert "hand_fix_says" not in answer["documents"][0]


def test_a_finder_from_before_780_has_no_hand_fix_and_the_list_is_as_it_was():
    d = str(uuid.uuid4())
    older = {"kind": "purchase_bill", "document_id": d, "reference": "B-1", "document_date": "2026-04-20", "owed_lines": 1, "moved_lines": 0, "unjournalled_rows": 0}
    answer = svc.unrecorded_documents(_Db([older]), firm_id=FIRM, client_id=CLIENT)
    assert answer["documents"] == [older]


# ── the retry ───────────────────────────────────────────────────────────────

def _bill(db, no="GS/114"):
    row = db.seed("purchase_bills", {"id": str(uuid.uuid4()), "firm_id": FIRM, "client_id": CLIENT, "bill_no": no, "bill_date": "2026-04-20", "status": "received"})
    return row["id"]


def test_a_retry_for_a_bill_it_cannot_finish_is_refused_in_the_lists_words_before_any_stock_function_runs(monkeypatch):
    db = FakeDB()
    bill = _bill(db)
    monkeypatch.setattr(svc, "unrecorded_documents", lambda *a, **k: {"total": 1, "documents": [_doc(bill, hand_fix="oversold_trueup")]})
    called = []
    monkeypatch.setattr("domain.inventory_service.apply_purchase_to_inventory", lambda *a, **k: called.append(1))
    with pytest.raises(svc.Refused) as refused:
        svc.retry(db, firm_id=FIRM, client_id=CLIENT, kind="purchase_bill", document_id=bill, created_by="u")
    assert str(refused.value).startswith(hf.says(hf.OVERSOLD_TRUEUP, "Purchase bill GS/114"))
    assert str(refused.value).endswith("Nothing was moved.")
    assert called == [], "no stock function ran"


def test_a_retry_for_a_document_the_finder_lists_without_a_hand_fix_runs_as_before(monkeypatch):
    db = FakeDB()
    bill = _bill(db)
    monkeypatch.setattr(svc, "unrecorded_documents", lambda *a, **k: {"total": 1, "documents": [_doc(bill, hand_fix=None)]})
    ran = []

    class _Effect:
        def as_dict(self):
            return {"recorded": True, "problem": None}

    monkeypatch.setattr("domain.inventory_service.apply_purchase_to_inventory", lambda *a, **k: ran.append(1) or _Effect())
    monkeypatch.setattr("services.period_lock_service.assert_not_closed", lambda *a, **k: None)
    monkeypatch.setattr("domain.inventory.stock_effect.guarded", lambda kind, ref, run, on_error: run())
    answer = svc.retry(db, firm_id=FIRM, client_id=CLIENT, kind="purchase_bill", document_id=bill, created_by="u")
    assert ran == [1] and answer["recorded"] is True


def test_a_finder_that_could_not_be_asked_is_not_a_reason_to_refuse(monkeypatch):
    db = FakeDB()
    bill = _bill(db)
    monkeypatch.setattr(svc, "unrecorded_documents", lambda *a, **k: None)
    ran = []

    class _Effect:
        def as_dict(self):
            return {"recorded": True, "problem": None}

    monkeypatch.setattr("domain.inventory_service.apply_purchase_to_inventory", lambda *a, **k: ran.append(1) or _Effect())
    monkeypatch.setattr("services.period_lock_service.assert_not_closed", lambda *a, **k: None)
    monkeypatch.setattr("domain.inventory.stock_effect.guarded", lambda kind, ref, run, on_error: run())
    svc.retry(db, firm_id=FIRM, client_id=CLIENT, kind="purchase_bill", document_id=bill, created_by="u")
    assert ran == [1]
