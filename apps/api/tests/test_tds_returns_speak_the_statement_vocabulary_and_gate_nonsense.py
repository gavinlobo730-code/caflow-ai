"""apex-tax-compliance-03 — two bugs on the TDS Returns screen.

(a) `list_returns` did a bare `select("*")` and never called the router's own
    `_statement_label` translator, so the frontend had nothing but the raw
    stored routing key ("26Q") to render — even though `create_return`'s own
    error messages and audit trail already speak through `_statement_label`,
    which per CLAUDE.md's TDS-vocabulary-fork rule renders "Form 140 (26Q)"
    for an FY2026-27+ period under the Income-tax Act 2025 renumbering.

(b) `update_return_status` had no guard against approving/filing a statement
    that is still EMPTY (`deductee_count == 0`) or whose own `quarter_end`
    has not arrived yet — so a Q2 return could be CA-approved before Q2 even
    ended, with zero deductees on it. The guard refuses by default and is
    overridable with `acknowledge_incomplete=True`, the same
    named-override shape `gst_workspace.py`'s `acknowledge_stale` uses for the
    analogous "the underlying facts look wrong" refusal on GSTR-3B approval.
"""
from __future__ import annotations

import pytest

import routers.tds_workspace as tw
from routers.tds_workspace import (
    CreateReturnRequest, UpdateReturnStatusRequest, _statement_label,
    create_return, list_returns, update_return_status,
)

PARTNER = {"firm_id": "F1", "id": "u1", "auth_user_id": "a1", "role": "Partner"}
CLIENT = "C1"


@pytest.fixture(autouse=True)
def _clean_store():
    tw._MOCK_RETURNS.clear()
    yield
    tw._MOCK_RETURNS.clear()


def _computed(**over) -> CreateReturnRequest:
    base = dict(client_id=CLIENT, return_type="26Q", quarter="Q1",
                financial_year="2025-26",
                deductee_details=[{"deductee_pan": "ABCDE1234F", "section": "194C",
                                   "tds_paise": 20000}],
                total_deductions_paise=20000, total_deposits_paise=20000,
                deductee_count=1, validation_errors=[])
    base.update(over)
    return CreateReturnRequest(**base)


# ── (a) list_returns carries the translated form ─────────────────────────────

def test_list_returns_carries_the_statement_form():
    create_return(_computed(financial_year="2025-26"), PARTNER)
    result = list_returns(client_id=CLIENT, limit=50, offset=0, current_user=PARTNER)
    assert result["success"] is True
    row = result["data"][0]
    assert row["statement_form"] == _statement_label("26Q", "2025-26")
    assert row["statement_form"] == "Form 26Q", \
        "a pre-fork FY26Q shows the FORM number as it was always called"


def test_list_returns_translates_the_2026_fork():
    create_return(_computed(financial_year="2026-27"), PARTNER)
    result = list_returns(client_id=CLIENT, limit=50, offset=0, current_user=PARTNER)
    row = result["data"][0]
    assert row["statement_form"] == "Form 140 (26Q)", \
        "an FY2026-27+ 26Q is Form 140 under the Income-tax Act 2025 fork"
    # And the RAW routing key must still be there — challan matching and every
    # other reader key on it, per CLAUDE.md: "translate at the boundary, never
    # rekey a store".
    assert row["return_type"] == "26Q"


def test_the_raw_routing_key_alone_is_no_longer_all_the_screen_gets():
    """Negative-control shape: this is what the screen saw before the fix —
    proving the field the fix adds is genuinely new, not already there under
    another name."""
    create_return(_computed(financial_year="2026-27"), PARTNER)
    row = list_returns(client_id=CLIENT, limit=50, offset=0, current_user=PARTNER)["data"][0]
    assert row["return_type"] != row["statement_form"], \
        "a 2026-27 26Q's raw key and its statement form must differ"


# ── (b) the ca_approved/filed guard ───────────────────────────────────────────

def _approve(return_id, status="ca_approved", **over):
    return update_return_status(return_id, UpdateReturnStatusRequest(
        status=status, ca_approved=True, **over), PARTNER)


def test_an_empty_statement_cannot_be_approved():
    rid = create_return(_computed(
        deductee_details=[], total_deductions_paise=0,
        total_deposits_paise=0, deductee_count=0), PARTNER)["data"]["id"]

    result = _approve(rid)

    assert result["success"] is False
    assert "no deductees" in result["error"]
    assert tw._MOCK_RETURNS[rid]["status"] != "ca_approved"


def test_a_return_whose_quarter_has_not_ended_cannot_be_approved():
    # Q4 of FY2026-27 runs Jan-Mar 2027 — well after "today" in this test run.
    rid = create_return(_computed(quarter="Q4", financial_year="2026-27"),
                        PARTNER)["data"]["id"]

    result = _approve(rid)

    assert result["success"] is False
    assert "quarter has not ended" in result["error"]
    assert tw._MOCK_RETURNS[rid]["status"] != "ca_approved"


def test_filing_is_gated_too_not_only_ca_approved():
    rid = create_return(_computed(quarter="Q4", financial_year="2026-27"),
                        PARTNER)["data"]["id"]

    result = _approve(rid, status="filed", prn="123456789012345")

    assert result["success"] is False
    assert tw._MOCK_RETURNS[rid]["status"] != "filed"


def test_a_genuinely_ready_return_still_approves_with_no_flag_needed():
    """The guard must not become a second, redundant confirmation for the
    ordinary case: a non-empty statement whose quarter has already closed."""
    rid = create_return(_computed(quarter="Q1", financial_year="2025-26"),
                        PARTNER)["data"]["id"]

    result = _approve(rid)

    assert result["success"] is True
    assert tw._MOCK_RETURNS[rid]["status"] == "ca_approved"


def test_the_named_override_lets_a_ca_record_it_anyway():
    rid = create_return(_computed(
        deductee_details=[], total_deductions_paise=0,
        total_deposits_paise=0, deductee_count=0,
        quarter="Q4", financial_year="2026-27"), PARTNER)["data"]["id"]

    refused = _approve(rid)
    assert refused["success"] is False

    overridden = _approve(rid, acknowledge_incomplete=True)
    assert overridden["success"] is True
    assert tw._MOCK_RETURNS[rid]["status"] == "ca_approved"


def test_the_override_is_not_on_by_default():
    """A field that silently defaulted true would make the whole guard
    decorative — the same discipline gst_workspace.py's acknowledge_stale
    documents about itself."""
    assert UpdateReturnStatusRequest(status="ca_approved",
                                     ca_approved=True).acknowledge_incomplete is False


def test_moving_a_draft_to_prepared_is_not_gated_by_this_at_all():
    """The guard is about APPROVAL/FILING on facts that look wrong — an
    ordinary pending -> prepared transition on an empty statement is routine
    and must not start failing."""
    rid = create_return(_computed(
        deductee_details=[], total_deductions_paise=0,
        total_deposits_paise=0, deductee_count=0), PARTNER)["data"]["id"]

    result = update_return_status(
        rid, UpdateReturnStatusRequest(status="prepared"), PARTNER)

    assert result["success"] is True
