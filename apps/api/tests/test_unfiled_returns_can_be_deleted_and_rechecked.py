"""A draft GST return is a working note. A filed one is a record.

WHY THIS EXISTS
    Reported: a CA presses Compute from Books to SEE what April owes, saves it
    because saving is the only way to keep the figure, and is then stuck with a
    row that looks like a return in progress and cannot be removed.

    And the harder half: the books move afterwards. An invoice is corrected, a
    bill arrives late, and the saved figures quietly stop describing the period
    they are named after. Nothing said so. Approval is the CA stating those
    figures are right, so approval is where it has to be caught.

WHAT MUST NEVER HAPPEN
    A submitted return being deleted or rewritten. It carries the real ARN and
    the gst_filings row journal_period_lock_reason (migration 266) reads to
    refuse edits inside a filed period — removing it would silently unlock a
    period already filed with the government, and let the books move under a
    return the department holds. Most of this file is about that.
"""
from __future__ import annotations

import pytest

from routers import gst_workspace as gw


# ── The staleness comparison ────────────────────────────────────────────────

def _rec(liab=100, itc=40, net=60, status="draft"):
    return {"id": "R1", "client_id": "CLI", "period": "042026", "gstin": "27AAAAA0000A1Z5",
            "status": status, "tax_liability_paise": liab,
            "itc_claimed_paise": itc, "net_tax_paise": net}


def test_a_return_the_books_still_support_is_not_stale():
    state = gw._staleness(_rec(), {"tax_liability_paise": 100,
                                   "itc_claimed_paise": 40, "net_tax_paise": 60})
    assert state["stale"] is False
    assert state["differences"] == {}


def test_a_moved_figure_is_reported_with_both_sides_and_the_gap():
    """"Changed" alone tells a CA nothing about whether it matters. The saved
    figure, the current one and the difference are all reported so they can
    judge it without leaving the screen."""
    state = gw._staleness(_rec(), {"tax_liability_paise": 175,
                                   "itc_claimed_paise": 40, "net_tax_paise": 135})
    assert state["stale"] is True
    assert state["differences"]["tax_liability_paise"] == {
        "saved_paise": 100, "books_paise": 175, "difference_paise": 75}
    assert state["differences"]["net_tax_paise"]["difference_paise"] == 75
    assert "itc_claimed_paise" not in state["differences"], "unchanged heads are not noise"


def test_a_figure_that_fell_is_stale_too():
    """A credit note issued after the return was saved REDUCES liability. Only
    checking for increases would miss the case where a CA over-declares."""
    state = gw._staleness(_rec(), {"tax_liability_paise": 40,
                                   "itc_claimed_paise": 40, "net_tax_paise": 0})
    assert state["stale"] is True
    assert state["differences"]["tax_liability_paise"]["difference_paise"] == -60


def test_a_missing_figure_reads_as_zero_rather_than_crashing():
    """An older row may predate a column. A comparison that throws would block
    approval entirely, which is a worse failure than comparing against zero."""
    state = gw._staleness({"tax_liability_paise": None}, {})
    assert state["saved"]["tax_liability_paise"] == 0
    assert state["stale"] is False


# ── What is deletable ───────────────────────────────────────────────────────

def test_the_deletable_statuses_are_exactly_the_unfiled_ones():
    """Pinned as a set rather than checked case by case: a new status added to
    the workflow must be a deliberate decision about whether it may be deleted,
    not an accident of which branch it falls through."""
    assert set(gw._DELETABLE_STATUSES) == {"draft", "validated", "ca_approved"}
    assert "submitted" not in gw._DELETABLE_STATUSES


@pytest.fixture()
def store(monkeypatch):
    monkeypatch.setattr(gw, "_USE_MOCK", True)
    monkeypatch.setattr(gw, "_MOCK_GSTR3B", {}, raising=False)
    return gw._MOCK_GSTR3B


CALLER = {"firm_id": "F1", "id": "u1", "email": "ca@f.test", "role": "Partner"}


def _seed(store, status):
    store["R1"] = {**_rec(status=status), "firm_id": "F1"}
    return store


@pytest.mark.parametrize("status", ["draft", "validated", "ca_approved"])
def test_an_unfiled_return_can_be_deleted(monkeypatch, store, status):
    _seed(store, status)
    monkeypatch.setattr(gw, "log_event", lambda *a, **k: None)
    r = gw._delete_return(CALLER, "gstr3b_returns", store, "R1", "GSTR-3B")
    assert r["success"] is True
    assert r["data"]["deleted"] is True
    assert "R1" not in store


def test_a_submitted_return_is_refused_and_told_why(monkeypatch, store):
    """The one that matters. Deleting this would unlock a filed period."""
    _seed(store, "submitted")
    monkeypatch.setattr(gw, "log_event", lambda *a, **k: None)
    r = gw._delete_return(CALLER, "gstr3b_returns", store, "R1", "GSTR-3B")
    assert r["success"] is False
    assert "cannot be deleted" in r["error"]
    assert "locks the period" in r["error"], (
        "the refusal has to say WHY, or it reads as an arbitrary block"
    )
    assert "R1" in store, "the return must still be there"


def test_the_whole_row_is_written_to_the_audit_log_before_it_goes(monkeypatch, store):
    """CLAUDE.md: a deletion writes what it removed, not merely that it
    happened. Logged BEFORE the delete so a failure cannot leave the row gone
    and unrecorded."""
    _seed(store, "draft")
    logged = {}

    def _capture(*a, **k):
        logged.update(k)

    monkeypatch.setattr(gw, "log_event", _capture)
    gw._delete_return(CALLER, "gstr3b_returns", store, "R1", "GSTR-3B")

    assert logged["action"] == "delete"
    assert logged["old_data"]["period"] == "042026"
    assert logged["old_data"]["tax_liability_paise"] == 100
    assert logged["actor_id"] == "u1"


def test_deleting_something_that_is_not_there_is_a_clean_not_found(monkeypatch, store):
    monkeypatch.setattr(gw, "log_event", lambda *a, **k: None)
    r = gw._delete_return(CALLER, "gstr3b_returns", store, "NOPE", "GSTR-3B")
    assert r["success"] is False
    assert r["error"] == "Not found"


# ── The approval gate ───────────────────────────────────────────────────────

def test_the_override_exists_but_is_off_by_default():
    """A CA who has read the difference and still wants the computed figures
    can say so. Defaulting it true, or letting it be set by omission, would
    make the refusal invisible — which is the entire point of it."""
    from routers.gst_workspace import UpdateStatusRequest
    assert UpdateStatusRequest(status="ca_approved").acknowledge_stale is False
    assert UpdateStatusRequest(status="ca_approved",
                               acknowledge_stale=True).acknowledge_stale is True


def test_recompute_defaults_to_read_only():
    """A CA asking whether a figure is still right must never have that question
    change the figure."""
    import inspect
    sig = inspect.signature(gw.recompute_gstr3b)
    assert sig.parameters["dry_run"].default.default is True


def test_recompute_clears_an_approval_it_invalidates():
    """Recomputing changes what the return says, so an approval of the earlier
    figures no longer applies to it. Leaving ca_approved in place would let a
    return be filed on figures nobody approved."""
    import inspect
    src = inspect.getsource(gw.recompute_gstr3b)
    assert '"status": "draft"' in src
    assert '"ca_approved_by": None' in src
    assert '"ca_approved_at": None' in src


def test_recompute_refuses_to_rewrite_a_filed_return():
    import inspect
    src = inspect.getsource(gw.recompute_gstr3b)
    assert "_DELETABLE_STATUSES" in src
    assert "amendment tables" in src, (
        "the refusal should point at the lawful correction route (§37(3), §39(9)), "
        "not just say no"
    )


def test_only_approval_is_blocked_by_staleness_never_recording_a_filing():
    """Refusing to let a CA write down something that already happened on the
    portal — because our copy drifted — would be the wrong failure. A stale
    submission is reported instead."""
    import inspect
    src = inspect.getsource(gw.update_gstr3b_status)
    assert 'body.status == "ca_approved" and stale_state' in src
    assert "stale_at_submission" in src
