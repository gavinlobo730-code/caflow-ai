"""The hub's thirteen queries, held to the CHECKs they claim to read.

`services/hub_service.py` turns each tile's question into one query, and the
first draft got FOUR of nine status vocabularies wrong — written from memory
and every one of them plausible:

    documents            filtered `status`;  the column is `review_status`
    year_end_engagements not_started/in_progress/review;  it is
                         draft/in_review/approved/locked
    itr_filings          omitted `ready_for_filing`, so a return sitting at the
                         last step before filing counted as done
    gstr1/gstr3b         counted only `draft`, so a validated or CA-approved
                         return — prepared and NOT filed, which is exactly what
                         the tile asks — was invisible

Three of those four produce a WRONG NUMBER rather than an error, which is the
worst outcome on a screen whose whole purpose is a number a CA acts on. (The
`documents` one would have raised PostgREST's 42703 and shown as a failed
tile — visible, and the least bad of the four.)

So the vocabularies are not asserted against a remembered list here either.
`_ALL` in the service is checked against the LIVE CHECK constraint by the
`_pg` sibling of this module; what this one holds is the shape: that every
tile names a real table and column, that the outstanding set is the complement
of the finished set, and that no tile was quietly dropped.
"""
from __future__ import annotations

import ast
from pathlib import Path

from domain.hub.tiles import TILES, BY_ID
from services import hub_service as svc

SERVICE = Path(svc.__file__)


def _signal_keys() -> set[str]:
    """The tile ids `_signals` actually builds, read from the AST rather than
    by calling it — calling it needs a database."""
    tree = ast.parse(SERVICE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_signals":
            for sub in ast.walk(node):
                if isinstance(sub, ast.Dict) and len(sub.keys) > 5:
                    return {k.value for k in sub.keys if isinstance(k, ast.Constant)}
    raise AssertionError("_signals' dict literal could not be read")


def test_every_tile_that_should_have_a_figure_has_a_query():
    """A tile with no entry in `_signals` reads as a FAILED FETCH, which is a
    different sentence from the one it deserves. The only tiles allowed to be
    absent are the two destinations and the one whose figure is client-only."""
    built = _signal_keys()
    expected = {t.id for t in TILES if t.answerable and not t.no_firm_signal_because}
    assert built == expected, (
        f"only-in-service {sorted(built - expected)}, "
        f"only-in-tiles {sorted(expected - built)}")


def test_the_outstanding_set_is_the_complement_of_the_finished_set():
    """Naming the FINISHED states and complementing is the decision: a value
    added to a CHECK is almost always a new intermediate state, and it then
    joins the outstanding count automatically instead of being dropped."""
    for key, done in (
        ("journal_entries", svc._JOURNAL_DONE),
        ("payroll_runs", svc._PAYROLL_DONE),
        ("gst_returns", svc._GST_RETURN_DONE),
        ("itr_filings", svc._ITR_DONE),
        ("compliance_records", svc._COMPLIANCE_DONE),
        ("year_end_engagements", svc._YEAR_END_DONE),
    ):
        outstanding = svc._outstanding(key, done)
        assert set(outstanding) | set(done) == set(svc._ALL[key])
        assert not set(outstanding) & set(done)
        assert outstanding, f"{key}: every status counts as finished"
        for d in done:
            assert d in svc._ALL[key], (
                f"{key} names {d!r} as finished and its CHECK does not allow it")


def test_the_four_that_were_wrong_stay_right():
    """Regression pins, one per defect named in the docstring."""
    assert 'eq={"review_status": "pending_review"}' in SERVICE.read_text(encoding="utf-8"), (
        "the documents tile is back on `status`; the column is `review_status`")
    assert "ready_for_filing" in svc._outstanding("itr_filings", svc._ITR_DONE)
    assert set(svc._outstanding("gst_returns", svc._GST_RETURN_DONE)) == {
        "draft", "validated", "ca_approved"}
    assert set(svc._outstanding("year_end_engagements", svc._YEAR_END_DONE)) == {
        "draft", "in_review", "approved"}


def test_the_banking_tile_asks_the_banking_modules_own_vocabulary():
    """`entry_state` has a Python twin pinned to a trigger. The tile must not
    keep a private list of "not yet passed" beside it."""
    src = SERVICE.read_text(encoding="utf-8")
    assert "bank_entry.OPEN_STATES" in src, (
        "the banking tile spells its own open states — it must ask "
        "domain/banking/entry, which is what the queue itself uses")
    from domain.banking import entry
    assert "passed" not in entry.OPEN_STATES


def test_a_tile_that_fails_loses_only_its_own_figure():
    """`_safely` is what stops one slow table emptying the hub."""
    assert svc._safely("x", lambda: 7) == 7
    assert svc._safely("x", lambda: (_ for _ in ()).throw(RuntimeError("boom"))) is None


def test_the_money_tiles_sum_a_column_the_schema_generates():
    """`outstanding_paise` is GENERATED (migration 278) precisely so the filter
    moves into the query — re-deriving `total - paid` here would omit the §34
    note terms and disagree with every other reader."""
    src = SERVICE.read_text(encoding="utf-8")
    assert '"client_sales_invoices", "outstanding_paise"' in src
    assert '"purchase_bills", "outstanding_paise"' in src
    assert "total_paise" not in src, "the hub is re-deriving what 278 generates"
    # And TDS asks what is NOT deposited, not every deduction ever made.
    assert 'extra_is_null="challan_no"' in src


def test_these_guards_are_not_vacuous():
    assert len(_signal_keys()) == 12, f"_signals builds {len(_signal_keys())} figures"
    assert BY_ID["inventory"].no_firm_signal_because
    assert len(svc._ALL) == 6
