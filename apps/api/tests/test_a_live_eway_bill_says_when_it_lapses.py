"""
SALES-28's other half: which live e-way bills are about to expire.

`eway_validity` has computed Rule 138(10)'s answer since SALES-28's first half
and `/records/{id}/validity` served it — but only to somebody who had already
opened that one record. A bill that lapses while the lorry is still moving
exposes the consignment to detention and seizure under CGST §129, and the
extension path (the proviso to Rule 138(10)) has existed the whole time with
nothing to prompt it.

FOUR RULES, AND THE FIRST IS A ONE-DAY BOUNDARY ON A §129 EXPOSURE.
"""
from __future__ import annotations

import ast
import pathlib
from datetime import date

import pytest

from domain.gst import eway_expiry

_API = pathlib.Path(__file__).resolve().parents[1]
TODAY = date(2026, 9, 18)


def _bill(**over):
    row = {"id": "1", "client_id": "c", "invoice_number": "INV/1",
           "ewb_number": "E1", "status": "generated",
           "ewb_valid_upto": "2026-09-20"}
    row.update(over)
    return row


# ── 1. midnight, not a rolling day ───────────────────────────────────────────

@pytest.mark.parametrize("valid_upto,expected", [
    (date(2026, 9, 17), eway_expiry.EXPIRED),
    (date(2026, 9, 18), eway_expiry.EXPIRES_TODAY),
    (date(2026, 9, 19), eway_expiry.EXPIRING),
    (date(2026, 9, 20), eway_expiry.EXPIRING),
    (date(2026, 9, 21), ""),
    (None, eway_expiry.UNKNOWN),
])
def test_the_boundary_between_today_and_expired_is_one_day(valid_upto, expected):
    """The Explanation to Rule 138(10) makes a day expire at MIDNIGHT, so a
    bill valid upto the 20th is good for the whole of the 20th. A naive `<`
    reads "expires today" as fine, which is the last chance to extend."""
    state, _ = eway_expiry.state_for(valid_upto, TODAY, 2)
    assert state == expected


# ── 2. what is and is not a live bill ────────────────────────────────────────

def test_a_cancelled_or_never_generated_record_is_not_running():
    out = eway_expiry.assess(
        [_bill(id="a", status="cancelled", ewb_valid_upto="2026-09-17"),
         _bill(id="b", ewb_number="", ewb_valid_upto="2026-09-17"),
         _bill(id="c", ewb_valid_upto="2026-09-17")], TODAY, 2)
    assert [b.record_id for b in out["bills"]] == ["c"]


def test_a_comfortably_live_bill_is_not_a_prompt():
    out = eway_expiry.assess([_bill(ewb_valid_upto="2026-12-01")], TODAY, 2)
    assert out["bills"] == []


# ── 3. the recorded date wins, and the answer says which it used ─────────────

def test_the_portals_own_date_is_preferred_over_the_computed_one():
    """NIC may know what this cannot — a leg by ship, an extension already
    granted — so a computed date is used only where none is recorded."""
    called = []

    def computed(row):
        called.append(row["id"])
        return {"valid_upto": "2026-09-19", "gap": None}

    out = eway_expiry.assess([_bill(ewb_valid_upto="2026-09-17")], TODAY, 2,
                             computed_expiry=computed)
    assert called == []
    assert out["bills"][0].source == eway_expiry.SOURCE_RECORDED
    assert out["bills"][0].valid_upto == "2026-09-17"


def test_a_bill_with_no_recorded_date_falls_back_and_says_so():
    out = eway_expiry.assess([_bill(ewb_valid_upto=None)], TODAY, 2,
                             computed_expiry=lambda r: {"valid_upto": "2026-09-19",
                                                        "gap": None})
    assert out["bills"][0].source == eway_expiry.SOURCE_COMPUTED


# ── 4. a bill nobody can date is LISTED, not dropped ─────────────────────────

def test_an_undeterminable_expiry_is_named_rather_than_omitted():
    """A silent omission reads as a clean answer — the `table_4a_gaps`
    discipline. Counting it as expiring would raise an alarm on a fact nobody
    holds, so it is its own bucket."""
    out = eway_expiry.assess([_bill(ewb_valid_upto=None)], TODAY, 2,
                             computed_expiry=lambda r: {"valid_upto": None,
                                                        "gap": "no distance recorded"})
    assert out["undeterminable"] == 1
    assert out["bills"][0].state == eway_expiry.UNKNOWN
    assert out["bills"][0].gap == "no distance recorded"


def test_the_worst_comes_first_and_the_undeterminable_last():
    out = eway_expiry.assess(
        [_bill(id="ok", invoice_number="D", ewb_valid_upto="2026-09-19"),
         _bill(id="gone", invoice_number="A", ewb_valid_upto="2026-09-16"),
         _bill(id="none", invoice_number="C", ewb_valid_upto=None),
         _bill(id="now", invoice_number="B", ewb_valid_upto="2026-09-18")],
        TODAY, 2, computed_expiry=lambda r: {"valid_upto": None, "gap": "x"})
    assert [b.record_id for b in out["bills"]] == ["gone", "now", "ok", "none"]


# ── 5. both caveats travel, and it is never a compliance row ─────────────────

def test_every_answer_carries_the_portal_and_the_extension_sentence():
    out = eway_expiry.assess([_bill(ewb_valid_upto="2026-09-17")], TODAY, 2)
    assert eway_expiry.PORTAL_IS_AUTHORITATIVE in out["caveats"]
    assert eway_expiry.EXTENSION_IS_THE_ACTION in out["caveats"]


def test_it_is_not_modelled_as_a_compliance_obligation():
    """Nothing is FILED for an e-way bill: the action is to extend it on the
    portal. Folding it into `ComplianceEntry` would mean inventing a
    compliance_type and offering a Mark Filed button that means nothing."""
    tree = ast.parse((_API / "domain/gst/eway_expiry.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)) \
                and ast.get_docstring(node):
            node.body = node.body[1:]
    code = ast.dump(tree)
    for forbidden in ("compliance_type", "filing_status", "filed_date", "ComplianceEntry"):
        assert forbidden not in code, forbidden


def test_the_firm_wide_read_treats_an_empty_scope_as_nothing():
    """`effective_client_ids` returns None for firm-wide and a SET otherwise.
    An EMPTY set means NOTHING, never "no filter" — getting that backwards is
    a cross-client read, so the empty case is written out."""
    from domain.income_tax.eway_service import live_eway_bills
    assert live_eway_bills("firm", set()) == []
