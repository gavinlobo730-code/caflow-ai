"""
domain/banking/entry.py — the voucher kind, the entry state, and the grading.

WHAT IS ASSERTED
    1. The kind is decided by the line, never chosen: money in is a Receipt,
       money out a Payment, and a transfer either way is a Contra.
    2. entry_state's branches, in the trigger's order. The table here is the
       same one tests/test_bank_entry_state_parity_pg.py feeds to Postgres —
       if a branch is added, it is added to BOTH.
    3. A human's own coding outranks a draft's failure: draft_error demotes a
       machine draft to needs_you, never a line the CA already answered.
    4. Grading: a rule is always ready; a document is ready only when exact,
       high-scored and ALONE; history is ready only when unanimous over three
       or more postings; a transfer only when high and unambiguous.
    5. choose(): ready beats proposed from any source; within a grade the
       order is rule, document, transfer, history.
    6. draft_changed(): a steady-state redraft writes nothing.
"""
from __future__ import annotations

import pytest

from domain.banking import entry as E
from domain.banking.rules import RuleSuggestion
from domain.banking.history import HistorySuggestion


# ── 1. kind ──────────────────────────────────────────────────────────────────

def test_money_in_is_a_receipt_and_money_out_a_payment():
    assert E.kind_for({"credit_paise": 100, "debit_paise": 0}) == E.RECEIPT
    assert E.kind_for({"credit_paise": 0, "debit_paise": 100}) == E.PAYMENT


def test_a_transfer_is_a_contra_whichever_way_the_money_moved():
    assert E.kind_for({"credit_paise": 100, "transfer_pair_id": "x"}) == E.CONTRA
    assert E.kind_for({"debit_paise": 100, "category": "Transfer"}) == E.CONTRA


# ── 2. state, branch by branch, in the trigger's order ──────────────────────

STATE_TABLE = [
    # posted wins over everything, including a draft error
    ({"match_status": "posted", "account_id": "a", "draft_error": "x"}, E.PASSED),
    ({"match_status": "ignored", "draft_grade": "ready", "draft_source": "rule"}, E.SET_ASIDE),
    # the receiving side of a pair is covered by the paying side
    ({"match_status": "matched", "transfer_pair_id": "p", "transfer_is_primary": False,
      "draft_error": "x"}, E.COVERED),
    # the paying side is ready
    ({"match_status": "matched", "transfer_pair_id": "p", "transfer_is_primary": True}, E.READY),
    # coded by the CA, four ways
    ({"match_status": "matched", "account_id": "a"}, E.READY),
    ({"match_status": "matched", "matched_entity_id": "inv"}, E.READY),
    ({"match_status": "unmatched", "has_splits": True}, E.READY),
    ({"match_status": "unmatched", "category": "Customer Payment"}, E.READY),
    ({"match_status": "unmatched", "category": "Vendor Payment"}, E.READY),
    ({"match_status": "unmatched", "category": "GST Payment"}, E.READY),
    # a category that still needs a ledger is NOT an answer
    ({"match_status": "unmatched", "category": "Expense"}, E.NEEDS_YOU),
    # a failed pass demotes a machine draft ...
    ({"match_status": "unmatched", "draft_source": "rule", "draft_grade": "ready",
      "draft_error": "Period locked"}, E.NEEDS_YOU),
    # ... but never a human's coding
    ({"match_status": "matched", "account_id": "a", "draft_error": "Period locked"}, E.READY),
    ({"match_status": "unmatched", "draft_source": "rule", "draft_grade": "ready"}, E.READY),
    ({"match_status": "unmatched", "draft_source": "history", "draft_grade": "proposed"}, E.PROPOSED),
    ({"match_status": "unmatched"}, E.NEEDS_YOU),
    ({}, E.NEEDS_YOU),
]


@pytest.mark.parametrize("row,expected", STATE_TABLE)
def test_entry_state(row, expected):
    assert E.entry_state(row) == expected


def test_every_state_the_trigger_can_produce_is_in_the_table():
    produced = {expected for _, expected in STATE_TABLE}
    assert produced == set(E.STATES)


def test_coded_by_a_human_is_exactly_the_ready_branch_that_owes_nothing_to_a_draft():
    assert E.coded_by_a_human({"account_id": "a"})
    assert E.coded_by_a_human({"has_splits": True})
    assert E.coded_by_a_human({"transfer_pair_id": "p", "transfer_is_primary": True})
    assert not E.coded_by_a_human({"transfer_pair_id": "p", "transfer_is_primary": False})
    assert not E.coded_by_a_human({"draft_grade": "ready", "draft_source": "rule"})


# ── 4. grading ───────────────────────────────────────────────────────────────

def _rule(**kw):
    base = dict(rule_id="r1", rule_name="Bank charges", category="Expense",
                account_id="acc-charges", narration=None)
    base.update(kw)
    return RuleSuggestion(**base)


def test_a_rule_is_always_ready_and_carries_its_gst_treatment():
    d = E.from_rule(_rule(gst_rate_bps=1800, is_interstate=True), "Bank Charges")
    assert d.grade == E.GRADE_READY and d.source == E.SOURCE_RULE
    assert d.account_id == "acc-charges" and d.rule_id == "r1"
    assert d.gst_rate_bps == 1800 and d.is_interstate is True
    assert d.label == "Bank Charges" and "Bank charges" in d.reason


def test_a_narration_only_rule_proposes_no_posting():
    assert E.from_rule(_rule(category=None, account_id=None, narration="x"), None) is None
    assert E.from_rule(None, None) is None


def _doc(conf=95, diff=0, tds=None, label="INV-1 · Acme", eid="inv-1"):
    return {"matched_entity_type": "sales_invoice", "matched_entity_id": eid, "label": label,
            "confidence": conf, "difference_paise": diff, "tds_rate_bps": tds}


def test_an_exact_high_scored_lone_document_is_ready():
    d = E.from_documents([_doc()])
    assert d.grade == E.GRADE_READY and d.entity_id == "inv-1" and d.label == "INV-1 · Acme"


def test_two_exact_documents_are_a_question_not_an_answer():
    d = E.from_documents([_doc(eid="inv-1"), _doc(eid="inv-2", conf=90)])
    assert d.grade == E.GRADE_PROPOSED
    assert "2 documents" in d.reason


def test_an_exact_but_lower_scored_document_is_proposed():
    # exact amount alone scores 50 in the ranker: no date, no narration agreement
    assert E.from_documents([_doc(conf=50)]).grade == E.GRADE_PROPOSED
    assert E.from_documents([_doc(conf=89)]).grade == E.GRADE_PROPOSED


def test_a_short_line_is_proposed_with_the_tds_question_on_it():
    d = E.from_documents([_doc(conf=25, diff=250000, tds=1000)])
    assert d.grade == E.GRADE_PROPOSED
    assert "short by" in d.reason and "10%" in d.reason
    d2 = E.from_documents([_doc(conf=25, diff=59, tds=None)])
    assert "bank charges, or TDS" in d2.reason


def test_a_weak_candidate_proposes_nothing():
    assert E.from_documents([_doc(conf=30, diff=-5000)]) is None
    assert E.from_documents([]) is None


def _hist(**kw):
    base = dict(key="acme", key_kind="counterparty", account_id="acc-1", category="Expense",
                times_seen=8, total_seen=9, last_seen="2026-08-01", alternatives=())
    base.update(kw)
    return HistorySuggestion(**base)


def test_history_is_ready_only_when_unanimous_over_three_or_more():
    assert E.from_history(_hist(times_seen=3, total_seen=3), "Rent").grade == E.GRADE_READY
    assert E.from_history(_hist(times_seen=2, total_seen=2), "Rent").grade == E.GRADE_PROPOSED
    assert E.from_history(_hist(times_seen=8, total_seen=9), "Rent").grade == E.GRADE_PROPOSED
    assert E.from_history(None, "Rent") is None


def test_the_history_reason_is_the_evidence_sentence():
    d = E.from_history(_hist(), "Rent")
    assert "8" in d.reason and "9" in d.reason


def _pair(conf="high", unamb=True):
    return {"primary_id": "out", "counterpart_id": "in", "confidence": conf,
            "is_unambiguous": unamb, "summary": "₹10,000 HDFC → Cosmos, same day"}


def test_a_transfer_is_written_on_both_sides_pointing_at_the_other():
    out = E.from_transfer(_pair(), "out", "Cosmos Bank")
    inn = E.from_transfer(_pair(), "in", "HDFC Bank")
    assert out.entity_id == "in" and out.label == "to Cosmos Bank" and out.category == "Transfer"
    assert inn.entity_id == "out" and inn.label == "from HDFC Bank"
    assert out.grade == inn.grade == E.GRADE_READY


def test_a_transfer_is_ready_only_when_high_and_unambiguous():
    assert E.from_transfer(_pair(conf="medium"), "out", None).grade == E.GRADE_PROPOSED
    assert E.from_transfer(_pair(unamb=False), "out", None).grade == E.GRADE_PROPOSED
    assert E.from_transfer(_pair(), "someone-else", None) is None
    assert E.from_transfer(None, "out", None) is None


# ── 5. choose ────────────────────────────────────────────────────────────────

def _d(source, grade):
    return E.Draft(source=source, grade=grade, label=source, reason=source)


def test_ready_from_a_weaker_source_beats_proposed_from_a_stronger_one():
    doc = _d(E.SOURCE_DOCUMENT, E.GRADE_PROPOSED)
    hist = _d(E.SOURCE_HISTORY, E.GRADE_READY)
    assert E.choose(None, doc, None, hist) is hist


def test_within_a_grade_the_order_is_rule_document_transfer_history():
    r, d, t, h = (_d(s, E.GRADE_READY) for s in E.SOURCES)
    assert E.choose(r, d, t, h) is r
    assert E.choose(None, d, t, h) is d
    assert E.choose(None, None, t, h) is t
    assert E.choose(None, None, None, h) is h
    assert E.choose(None, None, None, None) is None


# ── 6. draft_changed ─────────────────────────────────────────────────────────

def test_a_row_already_carrying_the_draft_is_not_rewritten():
    d = E.from_rule(_rule(), "Bank Charges")
    row = dict(d.as_columns())
    assert not E.draft_changed(row, d)
    row["draft_grade"] = "proposed"
    assert E.draft_changed(row, d)


def test_clearing_a_draft_is_a_change_only_when_one_was_there():
    assert not E.draft_changed(dict(E.EMPTY_DRAFT_COLUMNS), None)
    assert not E.draft_changed({}, None)
    assert E.draft_changed({"draft_source": "rule", "draft_grade": "ready"}, None)


def test_as_columns_and_the_empty_set_name_the_same_columns():
    assert set(_d("rule", "ready").as_columns()) == set(E.EMPTY_DRAFT_COLUMNS)
