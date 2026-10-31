"""POST-A-367 (items 2, 3 and 5) — a computation says what OTHER years did with a loss, and a filing is recorded as filed once.

WHAT WAS WRONG
    COMPUTE   A computation for a year offers the loss less the uses of OTHER years. That is right for the year's own revised return and it
              understates what an EARLIER year could have had when a LATER year's return has already used part of the loss: using more now may
              mean that later return has to be revised, and nothing said so. And a return recorded as filed whose write-back was refused (or that
              was recorded before the write-back existed) leaves the loss record showing the whole loss, so the next year's computation offered it
              again with no word that a filed return had used part of it.
    FILING    `record_filing_acknowledgement` read the status and then updated by id and firm. Two submits at the same moment both passed the read,
              and the second overwrote the first's acknowledgement number and date, which is what the refusal it sits behind exists to prevent.
              `transition_itr_status` had the same shape: a step from a status somebody else had just changed overwrote it.

WHAT THIS PINS
    LATER YEARS   a loss that a later year's return used is named in the compute note, with the year and the rupees, even when the figure offered
                  is the figure the screen sent; the same or an earlier year's entry is not "later"; a loss no later year touched has no note.
    UNRECORDED    an earlier-year return recorded as filed whose saved computation set off part of a loss the record does not show is named, by year,
                  acknowledgement number and rupees; nothing is said when the record shows it (also when a revised return replaced the original's
                  entry), for a return that is not filed, is an updated return, has no pinned computation, or whose computation is another
                  client's, another year's or does not name the loss by its record; a failure to read the filings never breaks the computation.
    STATUS        the update that records an acknowledgement, and the one that moves a return on, name the status they read as their condition:
                  a lost race matches no row and is told what is on file, and the winner's acknowledgement stands.
"""
import pytest

import routers.income_tax as it
from domain.income_tax import itr_workflow as wf
from domain.income_tax.computation_workspace import _MOCK_LOSSES, _MOCK_SNAPSHOTS
from domain.income_tax.itr_workflow import _MOCK_FILINGS
from domain.income_tax.loss_utilisation import holds_entry_for, is_earlier_year, later_uses
from services import bf_loss_service as svc

L = 1_00_000_00
FIRM = "F1"
MINE = "00000000-0000-4000-8000-0000000000a1"
OTHER = "00000000-0000-4000-8000-0000000000a2"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "a1", "email": "ca@example.in", "role": "Partner"}
LOSS_ID = "5b4c3a0e-0000-4000-8000-000000000001"


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    for store in (_MOCK_LOSSES, _MOCK_SNAPSHOTS, _MOCK_FILINGS):
        store.clear()
    monkeypatch.setattr(svc, "can_access_client", lambda user, client_id: True)
    yield
    for store in (_MOCK_LOSSES, _MOCK_SNAPSHOTS, _MOCK_FILINGS):
        store.clear()


def loss(entries=None, *, original=10 * L, utilized=0, client=MINE):
    _MOCK_LOSSES[LOSS_ID] = {
        "id": LOSS_ID, "firm_id": FIRM, "client_id": client, "loss_type": "business", "assessment_year": "2024-25",
        "original_amount_paise": original, "utilized_amount_paise": utilized, "remaining_amount_paise": original - utilized,
        "expiry_assessment_year": "2032-33", "source_itr_ack": "ACK-1", "utilisations": entries or {},
    }
    return _MOCK_LOSSES[LOSS_ID]


def used(*pairs):
    """Entries for (filing id, year, rupees in lakh, kind) and the totals that go with them."""
    entries = {fid: {"financial_year": fy, "amount_paise": lakh * L, "return_type": kind} for fid, fy, lakh, kind in pairs}
    return entries, sum(e["amount_paise"] for e in entries.values())


def snapshot(snapshot_id="S1", *, client=MINE, fy="2025-26", lines=None):
    lines = lines if lines is not None else [{"loss_id": LOSS_ID, "loss_type": "business", "section": "§72", "set_off_paise": 4 * L}]
    _MOCK_SNAPSHOTS[snapshot_id] = {
        "id": snapshot_id, "firm_id": FIRM, "client_id": client, "financial_year": fy,
        "computation_json": {"brought_forward": {"set_off_paise": sum(ln["set_off_paise"] for ln in lines), "lines": lines}},
    }


def filing(filing_id="F-25", *, fy="2025-26", kind="original", status="filed", snapshot_id="S1", client=MINE, ack="ACK-FILED"):
    _MOCK_FILINGS[filing_id] = {
        "id": filing_id, "firm_id": FIRM, "client_id": client, "financial_year": fy, "assessment_year": "2026-27",
        "return_type": kind, "status": status, "computation_snapshot_id": snapshot_id, "itr_form": "ITR-3",
        "acknowledgement_number": ack,
    }


def compute(fy, *, sent=6 * L):
    res = it.compute_itr(it.ComputeITRRequest(
        fy=fy, business_income_paise=20 * L, client_id=MINE,
        brought_forward_losses=[{"id": LOSS_ID, "loss_type": "business", "amount_paise": sent}]), USER)
    return res["data"]["brought_forward"]


# ───────────────────────────── the rule ─────────────────────────────

def test_later_uses_are_the_entries_of_years_after_the_one_computed_oldest_first():
    entries, total = used(("F-27", "2027-28", 2, "original"), ("F-26", "2026-27", 3, "original"), ("F-25", "2025-26", 1, "original"))
    row = loss(entries, utilized=total)
    assert [(u["financial_year"], u["amount_paise"]) for u in later_uses(row, "2025-26")] == [("2026-27", 3 * L), ("2027-28", 2 * L)]
    assert [u["financial_year"] for u in later_uses(row, "2026-27")] == ["2027-28"]
    assert later_uses(row, "2027-28") == [], "the last year has no later year"


def test_an_entry_that_took_nothing_is_not_a_use():
    entries, _ = used(("F-26", "2026-27", 0, "revised"))
    assert later_uses(loss(entries), "2025-26") == []


def test_a_label_that_cannot_be_read_is_neither_earlier_nor_later():
    assert is_earlier_year("2025-26", "2026-27") and not is_earlier_year("2026-27", "2025-26") and not is_earlier_year("2025-26", "2025-26")
    for bad in ("", "x", "26-27"):
        assert not is_earlier_year(bad, "2026-27") and not is_earlier_year("2025-26", bad)


def test_the_record_holds_an_entry_for_a_filing_or_for_the_return_that_stands_over_it():
    entries, _ = used(("F-25", "2025-26", 4, "original"))
    row = loss(entries)
    assert holds_entry_for(row, "F-25", "2025-26", "original")
    assert not holds_entry_for(row, "F-OTHER", "2025-26", "revised"), "an original's entry does not stand in for a revised return's"
    assert not holds_entry_for(row, "F-25", "2026-27", "original"), "another year"
    revised, _ = used(("F-REV", "2025-26", 3, "revised"))
    assert holds_entry_for(loss(revised), "F-ORIG", "2025-26", "original"), "a revised return replaced the original's entry"


# ───────────────────────────── later years ─────────────────────────────

def test_a_later_years_use_is_named_even_when_the_screen_sent_the_right_figure():
    entries, total = used(("F-26", "2026-27", 3, "original"))
    loss(entries, utilized=total)                                          # 7 lakh remain on the record
    bf = compute("2025-26", sent=7 * L)
    [note] = bf["offered_from_record"]
    assert note["offered_paise"] == 7 * L == note["sent_paise"]
    for text in ("later years", "FY 2026-27: ₹3,00,000.00", "may mean that later return has to be revised", "no view on which year should have had it"):
        assert text in note["note"], f"{text!r} missing: {note['note']}"
    assert note["later_years"] == [{"filing_id": "F-26", "financial_year": "2026-27", "amount_paise": 3 * L, "return_type": "original"}]


def test_a_later_years_use_is_added_to_the_sentence_about_a_figure_that_moved():
    entries, total = used(("F-26", "2026-27", 3, "original"))
    loss(entries, utilized=total)
    [note] = compute("2025-26", sent=9 * L)["offered_from_record"]
    assert "was not used" in note["note"] and "FY 2026-27: ₹3,00,000.00" in note["note"]
    assert note["sent_paise"] == 9 * L and note["offered_paise"] == 7 * L


def test_no_later_year_no_sentence():
    entries, total = used(("F-25", "2025-26", 4, "original"))
    loss(entries, utilized=total)
    assert compute("2025-26", sent=10 * L)["offered_from_record"] == [], "its own year is not later"
    assert compute("2026-27", sent=6 * L)["offered_from_record"] == [], "a year after the entry is not before it"


# ───────────────────────────── unrecorded earlier returns ─────────────────────────────

def test_a_filed_return_the_record_does_not_show_is_named():
    loss()
    snapshot()
    filing()
    bf = compute("2026-27", sent=10 * L)
    [note] = bf["offered_from_record"]
    for text in ("recorded as filed set off part of this loss", "FY 2025-26 (acknowledgement ACK-FILED), ₹4,00,000.00",
                 "counts that part as unused", "Tax Filing, Brought-forward losses"):
        assert text in note["note"], f"{text!r} missing: {note['note']}"
    assert note["unrecorded_returns"] == [{"filing_id": "F-25", "financial_year": "2025-26", "set_off_paise": 4 * L,
                                            "acknowledgement_number": "ACK-FILED"}]


def test_nothing_is_said_when_the_record_shows_the_return():
    entries, total = used(("F-25", "2025-26", 4, "original"))
    loss(entries, utilized=total)
    snapshot()
    filing()
    assert compute("2026-27", sent=6 * L)["offered_from_record"] == []


def test_the_original_a_revised_return_replaced_is_not_reported_missing():
    entries, total = used(("F-REV", "2025-26", 3, "revised"))
    loss(entries, utilized=total)
    snapshot("S-ORIG")
    filing("F-ORIG", snapshot_id="S-ORIG")
    snapshot("S-REV", lines=[{"loss_id": LOSS_ID, "loss_type": "business", "section": "§72", "set_off_paise": 3 * L}])
    filing("F-REV", kind="revised", snapshot_id="S-REV")
    assert compute("2026-27", sent=7 * L)["offered_from_record"] == []


@pytest.mark.parametrize("what, make", [
    ("a return that is not yet filed", lambda: filing(status="ready_for_filing")),
    ("an updated return", lambda: filing(kind="updated")),
    ("a return with no pinned computation", lambda: filing(snapshot_id=None)),
    ("a return for the year being computed", lambda: filing(fy="2026-27")),
    ("a return for a later year", lambda: filing(fy="2027-28")),
    ("a computation of another client", lambda: snapshot(client=OTHER)),
    ("a computation of another year", lambda: snapshot(fy="2024-25")),
    ("a computation that does not name the loss by its record", lambda: snapshot(lines=[{"loss_type": "business", "section": "§72", "set_off_paise": 4 * L}])),
    ("a computation that set off nothing of it", lambda: snapshot(lines=[{"loss_id": LOSS_ID, "loss_type": "business", "section": "§72", "set_off_paise": 0}])),
    ("a computation that names another record", lambda: snapshot(lines=[{"loss_id": "someone-else", "loss_type": "business", "section": "§72", "set_off_paise": 4 * L}])),
])
def test_nothing_is_said_for(what, make):
    loss()
    snapshot()
    filing()
    make()
    assert compute("2026-27", sent=10 * L)["offered_from_record"] == [], f"{what} must not be reported as a missed use"


def test_a_filing_that_cannot_be_read_does_not_break_the_computation_and_is_reported(monkeypatch):
    loss()
    snapshot()
    filing()
    reported = []
    import core.observability as observability
    monkeypatch.setattr(observability, "capture_soft_failure", lambda exc, **k: reported.append((str(exc), k.get("operation"))))

    def _boom(firm_id, client_id):
        raise RuntimeError("the database did not answer")
    monkeypatch.setattr(wf, "list_itr_filings", _boom)
    bf = compute("2026-27", sent=10 * L)
    assert bf["set_off_paise"] == 10 * L and bf["offered_from_record"] == []
    assert reported == [("the database did not answer", "bf_loss_service._unrecorded_returns")]


def test_a_loss_typed_without_a_record_is_not_asked_about_other_years():
    entries, total = used(("F-26", "2026-27", 3, "original"))
    loss(entries, utilized=total)
    res = it.compute_itr(it.ComputeITRRequest(
        fy="2025-26", business_income_paise=20 * L, client_id=MINE,
        brought_forward_losses=[{"loss_type": "business", "amount_paise": 4 * L}]), USER)
    assert res["data"]["brought_forward"]["offered_from_record"] == []


# ───────────────────────────── the status condition ─────────────────────────────

class _Query:
    """A one-table double that answers the way PostgREST does: an update names its conditions and matches no row when one fails."""

    def __init__(self, rows):
        self.rows = rows
        self.updates = []
        self._conditions = {}
        self._mode = None
        self._values = None

    def table(self, name):
        assert name == "itr_filings"
        return self

    def select(self, *_a, **_k):
        self._mode, self._conditions = "select", {}
        return self

    def update(self, values):
        self._mode, self._values, self._conditions = "update", values, {}
        return self

    def eq(self, column, value):
        self._conditions[column] = value
        return self

    def limit(self, _n):
        return self

    def maybe_single(self):
        self._single = True
        return self

    def execute(self):
        matched = [r for r in self.rows if all(r.get(c) == v for c, v in self._conditions.items())]
        if self._mode == "update":
            self.updates.append((dict(self._conditions), dict(self._values)))
            for r in matched:
                r.update(self._values)
            return type("R", (), {"data": [dict(r) for r in matched]})()
        data = [dict(r) for r in matched]
        if getattr(self, "_single", False):
            self._single = False
            return type("R", (), {"data": data[0] if data else None})()
        return type("R", (), {"data": data})()


@pytest.fixture
def store(monkeypatch):
    rows = [{"id": "F-1", "firm_id": FIRM, "status": "ready_for_filing", "acknowledgement_number": None, "computation_snapshot_id": None}]
    q = _Query(rows)
    monkeypatch.setattr(wf, "_USE_MOCK", False)
    monkeypatch.setattr(wf, "_supabase", lambda: q)
    return q, rows


def test_recording_an_acknowledgement_names_the_status_it_read(store):
    q, rows = store
    wf.record_filing_acknowledgement(FIRM, "F-1", "ACK-A", "2026-07-30", "u1")
    [(conditions, values)] = q.updates
    assert conditions["status"] == "ready_for_filing", "the update must be conditional on the status that was read"
    assert rows[0]["status"] == "filed" and rows[0]["acknowledgement_number"] == "ACK-A"


def test_the_second_of_two_simultaneous_acknowledgements_loses_and_the_first_stands(store, monkeypatch):
    q, rows = store
    real_execute = q.execute
    state = {"raced": False}

    def racing_execute():
        # The first caller's read has happened; before its update lands, the other submit wins.
        if q._mode == "update" and not state["raced"]:
            state["raced"] = True
            rows[0].update({"status": "filed", "acknowledgement_number": "ACK-WINNER"})
        return real_execute()
    monkeypatch.setattr(q, "execute", racing_execute)
    with pytest.raises(wf.ITRWorkflowError) as lost:
        wf.record_filing_acknowledgement(FIRM, "F-1", "ACK-LOSER", "2026-07-31", "u2")
    assert "already recorded as filed under acknowledgement ACK-WINNER" in str(lost.value)
    assert rows[0]["acknowledgement_number"] == "ACK-WINNER", "the loser must not overwrite the winner"


def test_a_step_taken_from_a_status_that_has_just_changed_is_refused_and_changes_nothing(store, monkeypatch):
    q, rows = store
    rows[0]["status"] = "partner_review"
    real_execute = q.execute
    state = {"raced": False}

    def racing_execute():
        if q._mode == "update" and not state["raced"]:
            state["raced"] = True
            rows[0].update({"status": "filed", "acknowledgement_number": "ACK-WINNER"})
        return real_execute()
    monkeypatch.setattr(q, "execute", racing_execute)
    with pytest.raises(ValueError) as lost:
        wf.transition_itr_status(FIRM, "F-1", "ready_for_filing", "u1")
    assert "moved from 'partner_review' to 'filed' while you were working on it" in str(lost.value)
    assert rows[0]["status"] == "filed" and rows[0]["acknowledgement_number"] == "ACK-WINNER", "the filed return must not be moved back"


def test_a_step_that_is_not_raced_names_its_status_and_moves(store):
    q, rows = store
    rows[0]["status"] = "partner_review"
    wf.transition_itr_status(FIRM, "F-1", "ready_for_filing", "u1")
    [(conditions, _)] = q.updates
    assert conditions["status"] == "partner_review" and rows[0]["status"] == "ready_for_filing"
