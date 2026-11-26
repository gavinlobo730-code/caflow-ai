"""A hand entry is held to the loss record's own years, the part recorded with no year can be taken back, and a correction is refused when
the entries moved (POST-A-368, the three things it had left).

WHAT WAS LEFT
    (1) `record_by_hand` accepted any financial year, so a year before the loss arose, or after the last year the record says it may be set
        off in, was stored and quietly lowered what every other year is offered.
    (2) The part recorded by hand with no year (what the deleted route typed in) is not an entry, so it had no take-back: it could only be
        reached by recording over it with a figure that is not a year's.
    (3) `store_bf_loss_use` compared the stored totals and not the entries, so two corrections landing together that swap one entry for
        another of the same size left both totals as they were and the second was written over the first.

WHAT IS HELD, AND WHAT IS NOT DECIDED HERE
    The bounds are the RECORD'S OWN words: the loss's `assessment_year` (the year it arose) and its stored `expiry_assessment_year` (the last
    year the record says it may be set off in, which `loss_set_off._is_available` already refuses a computation past). Nothing here reads the
    Act: whether a carried-forward loss may be used in its OWN assessment year or only from the next is a statutory reading that has not been
    confirmed, so the loss's own year is NOT refused, and neither is the expiry's. A record with no readable year on a side is not checked on
    that side. A nil amount is never refused (it only takes away a hand entry), so an entry stored before this check can still be removed.

Runs in mock mode; the database half of (3) is `test_567_a_brought_forward_loss_records_each_filings_use_pg.py`.
"""
from __future__ import annotations

import pytest

from domain.income_tax import loss_utilisation as lu
from domain.income_tax.computation_workspace import _MOCK_LOSSES
from services import bf_loss_service as svc

L = 1_00_000_00
FIRM = "F1"
CLIENT = "client-mine"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "a1", "email": "ca@example.in", "role": "Partner"}


def entry(fy, amount, kind="original"):
    return {"financial_year": fy, "amount_paise": amount, "return_type": kind}


def row(entries=None, *, original=10 * L, baseline=0, assessment_year="2024-25", expiry="2031-32"):
    """A record of a loss that arose in AY 2024-25 and may be set off up to AY 2031-32 (the record's own words)."""
    entries = entries or {}
    used = baseline + sum(e["amount_paise"] for e in entries.values())
    out = {"original_amount_paise": original, "utilized_amount_paise": used, "remaining_amount_paise": original - used, "utilisations": entries}
    if assessment_year is not None:
        out["assessment_year"] = assessment_year
    if expiry is not None:
        out["expiry_assessment_year"] = expiry
    return out


# ── (1) the year is held to the record's own years ───────────────────────────────────────────────────────────────────

def test_a_year_before_the_loss_arose_is_refused_and_names_the_year_it_arose_in():
    # The loss arose in AY 2024-25, so FY 2022-23 (AY 2023-24) is before it.
    with pytest.raises(lu.OutsideTheRecordsYears) as seen:
        lu.record_by_hand(row(), "2022-23", 1 * L)
    assert seen.value.too_early is True and seen.value.first_ay == "2024-25" and seen.value.last_ay == "2031-32"


def test_a_year_after_the_last_year_the_record_allows_is_refused_and_names_that_year():
    # The record allows set-off up to AY 2031-32, so FY 2031-32 (AY 2032-33) is after it.
    with pytest.raises(lu.OutsideTheRecordsYears) as seen:
        lu.record_by_hand(row(), "2031-32", 1 * L)
    assert seen.value.too_early is False and seen.value.last_ay == "2031-32"


def test_the_record_decides_the_loss_own_year_and_the_expiry_year_are_not_refused():
    """The Act is not read here: the loss's own year may or may not be usable (a reading nobody has confirmed), so it is not refused;
    the expiry year is the last the record itself allows, so it is not refused either."""
    own = lu.record_by_hand(row(), "2023-24", 1 * L)           # FY 2023-24 is AY 2024-25, the year the loss arose in
    assert "manual:2023-24" in own["utilisations"]
    last = lu.record_by_hand(row(), "2030-31", 1 * L)          # FY 2030-31 is AY 2031-32, the record's last year
    assert "manual:2030-31" in last["utilisations"]


@pytest.mark.parametrize("fy,ok", [("2022-23", False), ("2023-24", True), ("2024-25", True), ("2030-31", True), ("2031-32", False),
                                   ("2040-41", False)])
def test_the_edges_of_the_records_years(fy, ok):
    if ok:
        assert f"manual:{fy}" in lu.record_by_hand(row(), fy, 1 * L)["utilisations"]
    else:
        with pytest.raises(lu.OutsideTheRecordsYears):
            lu.record_by_hand(row(), fy, 1 * L)


@pytest.mark.parametrize("record", [row(assessment_year=None), row(assessment_year="unknown"), row(assessment_year="")],
                         ids=["no-year", "unreadable-year", "blank-year"])
def test_a_record_with_no_readable_year_is_not_checked_on_that_side(record):
    assert "manual:2000-01" in lu.record_by_hand(record, "2000-01", 1 * L)["utilisations"]       # nothing says it is too early
    with pytest.raises(lu.OutsideTheRecordsYears):
        lu.record_by_hand(record, "2031-32", 1 * L)                                               # the other side is still held


@pytest.mark.parametrize("record", [row(expiry=None), row(expiry="unknown"), row(expiry="")], ids=["no-expiry", "unreadable", "blank"])
def test_a_record_with_no_readable_expiry_is_not_checked_on_that_side(record):
    assert "manual:2090-91" in lu.record_by_hand(record, "2090-91", 1 * L)["utilisations"]
    with pytest.raises(lu.OutsideTheRecordsYears):
        lu.record_by_hand(record, "2022-23", 1 * L)


def test_a_record_with_neither_bound_takes_any_year_as_before():
    bare = row(assessment_year=None, expiry=None)
    assert "manual:2005-06" in lu.record_by_hand(bare, "2005-06", 1 * L)["utilisations"]


def test_a_nil_is_never_refused_so_an_entry_stored_before_the_check_can_still_be_removed():
    stale = row({"manual:2020-21": entry("2020-21", 2 * L, "manual")})        # a year before the loss arose, stored before the check existed
    gone = lu.record_by_hand(stale, "2020-21", 0)
    assert gone["utilisations"] == {} and gone["utilized_amount_paise"] == 0 and gone["remaining_amount_paise"] == 10 * L
    # Taking it back is the other way out and is untouched.
    assert lu.take_back(stale, "manual:2020-21")["utilisations"] == {}


def test_a_label_that_is_not_a_year_is_still_the_old_refusal_and_not_this_one():
    with pytest.raises(ValueError) as seen:
        lu.record_by_hand(row(), "banana", 1 * L)
    assert not isinstance(seen.value, lu.OutsideTheRecordsYears)


def test_a_filed_returns_own_use_is_not_held_to_the_records_years():
    """The return is the evidence of its year's use; only a person's hand entry is checked. A filing for a year the record puts outside is
    written as it always was."""
    cols = lu.after_filing(row(), "F-2022", "2022-23", 2 * L)
    assert cols["utilisations"]["F-2022"]["amount_paise"] == 2 * L


# ── (2) the part recorded with no year can be taken back ─────────────────────────────────────────────────────────────

def test_the_part_recorded_with_no_year_is_named_by_the_view_only_when_there_is_one():
    assert lu.uses_view(row(baseline=3 * L), {})["hand_recorded_entry_id"] == lu.HAND_RECORDED
    assert lu.uses_view(row(), {})["hand_recorded_entry_id"] is None
    assert lu.uses_view(row({"f-25": entry("2025-26", 4 * L)}), {})["hand_recorded_entry_id"] is None


def test_taking_back_the_part_recorded_with_no_year_leaves_every_entry_and_the_totals_follow():
    r = row({"f-25": entry("2025-26", 4 * L), "manual:2026-27": entry("2026-27", 1 * L, "manual")}, baseline=3 * L)
    assert r["utilized_amount_paise"] == 8 * L
    cols = lu.take_back(r, lu.HAND_RECORDED)
    assert cols["utilisations"] == r["utilisations"]
    assert (cols["utilized_amount_paise"], cols["remaining_amount_paise"]) == (5 * L, 5 * L)


def test_after_it_is_taken_back_there_is_none_to_take_back_and_the_rest_of_the_record_is_as_it_was():
    r = row({"f-25": entry("2025-26", 4 * L)}, baseline=3 * L)
    after = {**r, **lu.take_back(r, lu.HAND_RECORDED)}
    assert lu.baseline_paise(after) == 0
    assert lu.uses_view(after, {})["hand_recorded_entry_id"] is None
    with pytest.raises(lu.NoSuchEntry):
        lu.take_back(after, lu.HAND_RECORDED)


def test_a_record_with_no_such_part_has_nothing_to_take_back():
    with pytest.raises(lu.NoSuchEntry):
        lu.take_back(row({"f-25": entry("2025-26", 4 * L)}), lu.HAND_RECORDED)


def test_no_entry_a_person_or_a_return_can_make_has_the_id_of_the_part_recorded_with_no_year():
    """A filing's id is a uuid and a hand entry's is `manual:<year>`, so neither can be taken for the part with no year."""
    assert lu.HAND_RECORDED == "hand-recorded"
    assert not lu.manual_entry_id("2025-26") == lu.HAND_RECORDED and ":" in lu.manual_entry_id("2025-26")


# ── the service: the sentence, the audit entry, and nothing written on a refusal ─────────────────────────────────────

@pytest.fixture
def world(monkeypatch):
    _MOCK_LOSSES.clear()
    log = []
    monkeypatch.setattr(svc, "_write_audit_or_refuse", lambda **kw: log.append(("audit", kw)))
    real_store = svc.workspace.store_bf_loss_use

    def store(firm_id, loss_id, before, columns):
        log.append(("store", loss_id))
        return real_store(firm_id, loss_id, before, columns)

    monkeypatch.setattr(svc.workspace, "store_bf_loss_use", store)
    yield log
    _MOCK_LOSSES.clear()


def stored(loss_id="L1", entries=None, **kw):
    _MOCK_LOSSES[loss_id] = {"id": loss_id, "firm_id": FIRM, "client_id": CLIENT, "loss_type": "business", **row(entries, **kw)}
    return _MOCK_LOSSES[loss_id]


def test_a_year_before_the_loss_arose_is_a_sentence_and_nothing_is_written(world):
    stored()
    with pytest.raises(svc.UseRefused) as seen:
        svc.record_year_use(USER, "L1", "2022-23", 1 * L, "typed from the old file")
    assert seen.value.status == 422
    assert seen.value.sentence == ("FY 2022-23 (AY 2023-24) is before this loss arose, in AY 2024-25, so the record cannot show it as "
                                   "using the loss.")
    assert world == [] and _MOCK_LOSSES["L1"]["utilisations"] == {}


def test_a_year_after_the_last_year_is_a_sentence_and_nothing_is_written(world):
    stored()
    with pytest.raises(svc.UseRefused) as seen:
        svc.record_year_use(USER, "L1", "2031-32", 1 * L, "typed from the old file")
    assert seen.value.sentence == ("FY 2031-32 (AY 2032-33) is after AY 2031-32, the last year this record allows the loss to be set off in, "
                                   "so the record cannot show it as using the loss.")
    assert world == []


def test_the_sentences_advise_nothing_because_a_loss_records_years_cannot_be_edited():
    """There is no route or screen that edits a loss record's years, so a sentence that said to correct them would send a person nowhere."""
    from routers import itr_workspace
    paths = {getattr(r, "path", "") for r in itr_workspace.router.routes}
    assert not any("bf-losses" in p and "{loss_id}" in p and "year-use" not in p and "take-back" not in p for p in paths), paths
    for exc in (lu.OutsideTheRecordsYears("2024-25", "2031-32", True), lu.OutsideTheRecordsYears("2024-25", "2031-32", False)):
        text = svc._outside_sentence("2022-23", exc)
        assert "correct" not in text.lower() and "first" not in text.lower()


def test_a_year_inside_the_records_years_is_recorded_as_before(world):
    stored()
    out = svc.record_year_use(USER, "L1", "2024-25", 3 * L, "typed from the old file")
    assert out["state"] == svc.WRITTEN and out["recorded_paise"] == 3 * L
    assert [step for step, _ in world] == ["audit", "store"]


def test_taking_back_the_part_recorded_with_no_year_writes_the_audit_entry_first_and_says_what_went(world):
    stored(baseline=3 * L, entries={"f-25": entry("2025-26", 4 * L)})
    out = svc.take_back_use(USER, "L1", lu.HAND_RECORDED, "typed in by the old route, no year")
    assert [step for step, _ in world] == ["audit", "store"]
    audit = world[0][1]
    assert audit["change"] == "use_taken_back" and audit["reason"] == "typed in by the old route, no year"
    assert audit["requested"] == {"entry_id": "hand-recorded", "financial_year": None, "amount_paise": 3 * L, "kind": "hand_recorded"}
    assert out["state"] == svc.WRITTEN and out["entry_id"] == "hand-recorded"
    assert out["message"] == "The ₹3,00,000.00 recorded by hand with no year was taken off this loss."
    kept = _MOCK_LOSSES["L1"]
    assert (kept["utilized_amount_paise"], kept["remaining_amount_paise"]) == (4 * L, 6 * L)
    assert kept["utilisations"] == {"f-25": entry("2025-26", 4 * L)}


def test_there_being_none_to_take_back_is_a_404_and_no_audit_entry(world):
    stored(entries={"f-25": entry("2025-26", 4 * L)})
    with pytest.raises(svc.UseRefused) as seen:
        svc.take_back_use(USER, "L1", lu.HAND_RECORDED, "typed in by the old route, no year")
    assert seen.value.status == 404 and world == []


def test_taking_it_back_needs_a_reason_like_every_other_take_back(world):
    stored(baseline=3 * L)
    with pytest.raises(svc.UseRefused):
        svc.take_back_use(USER, "L1", lu.HAND_RECORDED, "   ")
    assert world == [] and _MOCK_LOSSES["L1"]["utilized_amount_paise"] == 3 * L


# ── (3) a correction is refused when the entries moved, not only the totals ──────────────────────────────────────────

def test_an_entry_swapped_for_another_of_the_same_size_is_seen_by_the_store(world):
    mine = stored(entries={"manual:2024-25": entry("2024-25", 2 * L, "manual")})
    read = dict(mine)                                                         # what a correction read and worked its columns out from
    columns = lu.take_back(read, "manual:2024-25")
    # Another correction lands first: it swaps the entry for another of the same size, which leaves BOTH totals as they were.
    _MOCK_LOSSES["L1"].update(utilisations={"manual:2025-26": entry("2025-26", 2 * L, "manual")})
    assert (_MOCK_LOSSES["L1"]["utilized_amount_paise"], _MOCK_LOSSES["L1"]["remaining_amount_paise"]) == (
        read["utilized_amount_paise"], read["remaining_amount_paise"])
    assert svc.workspace.store_bf_loss_use(FIRM, "L1", read, columns) is False
    assert _MOCK_LOSSES["L1"]["utilisations"] == {"manual:2025-26": entry("2025-26", 2 * L, "manual")}      # not written over


def test_a_correction_that_lost_to_a_swap_says_the_record_changed_and_writes_nothing(world):
    stored(entries={"manual:2024-25": entry("2024-25", 2 * L, "manual")})
    read = dict(_MOCK_LOSSES["L1"])
    columns = lu.take_back(read, "manual:2024-25")
    _MOCK_LOSSES["L1"].update(utilisations={"manual:2025-26": entry("2025-26", 2 * L, "manual")})
    with pytest.raises(svc.UseRefused) as seen:
        svc._store_or_refuse(FIRM, read, columns)
    assert seen.value.status == 409 and "changed while this was being saved" in seen.value.sentence


def test_a_row_that_did_not_move_is_still_written():
    _MOCK_LOSSES.clear()
    mine = stored(entries={"manual:2024-25": entry("2024-25", 2 * L, "manual")})
    read = dict(mine)
    assert svc.workspace.store_bf_loss_use(FIRM, "L1", read, lu.take_back(read, "manual:2024-25")) is True
    assert _MOCK_LOSSES["L1"]["utilisations"] == {}
    _MOCK_LOSSES.clear()


def test_the_reading_compares_the_entries_and_the_totals():
    from domain.income_tax.computation_workspace import bf_loss_reads_as
    a = row({"x": entry("2025-26", 2 * L)})
    assert bf_loss_reads_as(a, dict(a)) is True
    assert bf_loss_reads_as(a, {**a, "utilisations": {"y": entry("2025-26", 2 * L)}}) is False           # swapped, same totals
    assert bf_loss_reads_as(a, {**a, "utilized_amount_paise": 1}) is False                               # a total moved
    assert bf_loss_reads_as({"utilized_amount_paise": 0, "remaining_amount_paise": 5}, {"utilized_amount_paise": 0,
                                                                                         "remaining_amount_paise": 5}) is True    # no column yet


def test_a_reading_that_never_held_the_entries_is_compared_on_the_totals_alone_and_both_readers_hold_them():
    """A narrow select that left `utilisations` out would otherwise read as a record with NO entries and refuse every write to one that has
    some. So the entries are named only when the reading holds them, and the two readers that feed a correction select every column."""
    import inspect

    from domain.income_tax import computation_workspace as workspace
    totals = {"utilized_amount_paise": 2 * L, "remaining_amount_paise": 8 * L}
    assert workspace.bf_loss_reads_as(totals, {**totals, "utilisations": {"x": entry("2025-26", 2 * L)}}) is True
    assert workspace.bf_loss_reads_as({**totals, "utilisations": {}}, {**totals, "utilisations": {"x": entry("2025-26", 2 * L)}}) is False
    for reader in (workspace.get_bf_loss, workspace.list_bf_losses):
        assert '.select("*")' in inspect.getsource(reader), f"{reader.__name__} no longer reads every column of the loss record"


def test_the_real_store_names_no_entries_for_a_reading_that_never_held_them(monkeypatch):
    from domain.income_tax import computation_workspace as workspace
    calls = []

    class Fake:
        def table(self, name):
            return self

        def update(self, columns):
            return self

        def eq(self, column, value):
            return self

        def contains(self, column, value):
            calls.append(("contains", column))
            return self

        def contained_by(self, column, value):
            calls.append(("contained_by", column))
            return self

        def execute(self):
            return type("R", (), {"data": [{"id": "L1"}]})()

    monkeypatch.setattr(workspace, "_USE_MOCK", False)
    monkeypatch.setattr(workspace, "_supabase", lambda: Fake())
    columns = {"utilisations": {}, "utilized_amount_paise": 0, "remaining_amount_paise": 10 * L}
    assert workspace.store_bf_loss_use(FIRM, "L1", {"utilized_amount_paise": 1, "remaining_amount_paise": 2}, columns) is True
    assert calls == []
    assert workspace.store_bf_loss_use(FIRM, "L1", {"utilized_amount_paise": 1, "remaining_amount_paise": 2, "utilisations": {}}, columns) is True
    assert calls == [("contains", "utilisations"), ("contained_by", "utilisations")]


# ── through the two routes, as a caller sees them ────────────────────────────────────────────────────────────────────

def test_a_year_outside_the_records_years_reaches_the_caller_as_a_422_with_the_sentence(monkeypatch):
    from fastapi import HTTPException

    from routers import itr_workspace as itr
    _MOCK_LOSSES.clear()
    stored()
    monkeypatch.setattr(svc, "_write_audit_or_refuse", lambda **kw: None)
    monkeypatch.setattr(itr, "can_access_client", lambda user, client_id: True)
    monkeypatch.setattr(itr, "assert_client_access", lambda user, client_id: None)
    with pytest.raises(HTTPException) as e:
        itr.record_year_use("L1", itr.YearUseRequest(financial_year="2022-23", amount_paise=L, reason="why"), current_user=USER)
    assert e.value.status_code == 422 and e.value.detail.startswith("FY 2022-23 (AY 2023-24) is before this loss arose")
    _MOCK_LOSSES.clear()


def test_the_part_recorded_with_no_year_is_taken_back_through_the_take_back_route(monkeypatch):
    from routers import itr_workspace as itr
    _MOCK_LOSSES.clear()
    stored(baseline=3 * L)
    monkeypatch.setattr(svc, "_write_audit_or_refuse", lambda **kw: None)
    monkeypatch.setattr(itr, "can_access_client", lambda user, client_id: True)
    monkeypatch.setattr(itr, "assert_client_access", lambda user, client_id: None)
    out = itr.take_back_loss_use("L1", lu.HAND_RECORDED, itr.TakeBackRequest(reason="typed in by the old route"), current_user=USER)
    assert out["success"] is True and out["data"]["entry_id"] == "hand-recorded"
    assert _MOCK_LOSSES["L1"]["utilized_amount_paise"] == 0 and _MOCK_LOSSES["L1"]["remaining_amount_paise"] == 10 * L
    _MOCK_LOSSES.clear()

