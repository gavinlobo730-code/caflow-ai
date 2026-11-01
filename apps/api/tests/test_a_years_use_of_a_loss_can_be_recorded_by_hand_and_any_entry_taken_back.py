"""POST-A-368 (items 2 and 3) — a person records a year's use of a brought-forward loss by hand, and takes any entry back, with a reason.

WHAT WAS WRONG
    The write-back of a filed return's use (POST-A-073) stores the use per filing and per year, and the only hand route, `POST /bf-losses/{id}/utilize`,
    called by no screen, could only ADD to the total and carried no year: what it typed became "baseline" that no year is ever offered back, which is
    the hazard migration 567 removed for returns. A return filed before this product, or one whose saved computation was never pinned, left no entry
    at all, and a wrong write-back could be corrected only by a database edit. Every refusal said "There is no screen yet to correct a loss record".

WHAT THIS PINS
    THE RULE    (`loss_utilisation.record_by_hand`, `take_back`, which read nothing)
                a hand entry is one per loss and year, SET and never added to, and an amount of nothing takes it away; it never touches the baseline or
                another year; a year that a return's entry holds is refused (`HeldByReturn`) and an amount past what the record could take is refused
                with the figure it could (`MoreThanTheRecordCanTake`); a filing's write for the same year REPLACES a hand entry and a hand entry
                never supersedes a filing; the year's own hand entry is offered back when that year is computed again; any entry can be taken back and
                nothing else moves; the totals stay baseline + entries and original - used.
    THE SERVICE the reason is required (and bounded); what the record held, what was asked and the reason go into the audit log BEFORE the record
                changes and a failure to write that REFUSES the change (503) and leaves the record; a record that changed under the write is refused (409);
                a loss of another firm is not found; a take-back of a filing's entry says it comes back when that return's records are written again.
    THE ROUTES  behind the compute tier and the client-scope check.
    THE WORDS   the sentences that said "no screen yet" name the screen now.
"""
import pytest

import routers.itr_workspace as itr
from domain.income_tax import loss_utilisation as lu
from domain.income_tax.computation_workspace import _MOCK_LOSSES
from services import bf_loss_service as svc

L = 1_00_000_00
FIRM = "F1"
MINE = "client-mine"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "a1", "email": "ca@example.in", "role": "Partner"}


def entry(fy, amount, kind="original"):
    return {"financial_year": fy, "amount_paise": amount, "return_type": kind}


def row(entries=None, *, original=10 * L, baseline=0):
    entries = entries or {}
    used = baseline + sum(e["amount_paise"] for e in entries.values())
    return {"original_amount_paise": original, "utilized_amount_paise": used, "remaining_amount_paise": original - used, "utilisations": entries}


def consistent(columns, original=10 * L):
    entries = columns["utilisations"]
    assert columns["utilized_amount_paise"] >= sum(e["amount_paise"] for e in entries.values())
    assert columns["remaining_amount_paise"] == original - columns["utilized_amount_paise"]


# ── the rule: recording ─────────────────────────────────────────────────────────────────────────────────────────────

def test_a_hand_entry_is_one_entry_for_the_year_and_the_totals_follow():
    cols = lu.record_by_hand(row(), "2024-25", 3 * L)
    assert cols["utilisations"] == {"manual:2024-25": entry("2024-25", 3 * L, "manual")}
    assert (cols["utilized_amount_paise"], cols["remaining_amount_paise"]) == (3 * L, 7 * L)
    consistent(cols)


def test_recording_the_year_again_sets_it_and_never_adds():
    first = {**row(), **lu.record_by_hand(row(), "2024-25", 3 * L)}
    again = lu.record_by_hand(first, "2024-25", 1 * L)
    assert again["utilisations"]["manual:2024-25"]["amount_paise"] == 1 * L
    assert again["utilized_amount_paise"] == 1 * L and again["remaining_amount_paise"] == 9 * L


def test_an_amount_of_nothing_takes_the_years_hand_entry_away():
    first = {**row(), **lu.record_by_hand(row(), "2024-25", 3 * L)}
    gone = lu.record_by_hand(first, "2024-25", 0)
    assert gone["utilisations"] == {} and gone["utilized_amount_paise"] == 0 and gone["remaining_amount_paise"] == 10 * L


def test_the_baseline_and_other_years_are_left_exactly_as_found():
    r = row({"F-24": entry("2023-24", 2 * L), "manual:2025-26": entry("2025-26", 1 * L, "manual")}, baseline=1 * L)
    cols = lu.record_by_hand(r, "2024-25", 3 * L)
    assert cols["utilisations"]["F-24"] == entry("2023-24", 2 * L)
    assert cols["utilisations"]["manual:2025-26"] == entry("2025-26", 1 * L, "manual")
    assert lu.baseline_paise({**r, **cols}) == 1 * L
    assert cols["utilized_amount_paise"] == 1 * L + 2 * L + 1 * L + 3 * L
    consistent(cols)


@pytest.mark.parametrize("kind", ["original", "revised"])
def test_a_year_a_return_holds_is_refused_and_names_the_return(kind):
    r = row({"F-25": entry("2024-25", 2 * L, kind)})
    with pytest.raises(lu.HeldByReturn) as e:
        lu.record_by_hand(r, "2024-25", 1 * L)
    assert e.value.by == "F-25"
    # another year is not held by it
    assert "manual:2025-26" in lu.record_by_hand(r, "2025-26", 1 * L)["utilisations"]


def test_more_than_the_record_could_take_is_refused_with_the_figure_it_could_and_nothing_is_stored_smaller():
    r = row({"F-24": entry("2023-24", 6 * L)}, baseline=1 * L)
    with pytest.raises(lu.MoreThanTheRecordCanTake) as e:
        lu.record_by_hand(r, "2024-25", 4 * L)
    assert e.value.room_paise == 3 * L
    assert "manual:2024-25" in lu.record_by_hand(r, "2024-25", 3 * L)["utilisations"]       # exactly the room is allowed


def test_the_years_own_hand_entry_is_not_counted_against_its_own_room():
    r = {**row(), **lu.record_by_hand(row(), "2024-25", 9 * L)}
    assert lu.room_for_manual_paise(r, "2024-25") == 10 * L
    assert lu.record_by_hand(r, "2024-25", 10 * L)["utilized_amount_paise"] == 10 * L


@pytest.mark.parametrize("label", ["", "  ", "last year", "abcd-ef"])
def test_a_label_that_is_not_a_financial_year_is_refused(label):
    with pytest.raises(ValueError):
        lu.record_by_hand(row(), label, 1 * L)


# ── the rule: how a hand entry sits beside a filing ─────────────────────────────────────────────────────────────────

def test_a_filings_write_for_the_same_year_replaces_the_hand_entry_and_is_never_refused_by_it():
    r = {**row(), **lu.record_by_hand(row(), "2024-25", 3 * L)}
    for kind in ("original", "revised"):
        cols = lu.after_filing(r, "F-1", "2024-25", 4 * L, kind)
        assert cols["utilisations"] == {"F-1": entry("2024-25", 4 * L, kind)}
        assert cols["utilized_amount_paise"] == 4 * L


def test_a_hand_entry_is_not_a_return_holding_the_use_so_the_return_is_still_unrecorded():
    r = {**row(), **lu.record_by_hand(row(), "2024-25", 3 * L)}
    assert lu.holds_entry_for(r, "F-1", "2024-25", "original") is False
    assert lu.holds_entry_for({**row({"F-1": entry("2024-25", 1)}), }, "F-1", "2024-25", "original") is True


def test_the_years_own_hand_entry_is_offered_back_when_that_year_is_computed_again_and_other_years_are_not():
    r = {**row(), **lu.record_by_hand(row(), "2024-25", 3 * L)}
    assert lu.used_in_year_paise(r, "2024-25") == 3 * L
    assert lu.available_for_year_paise(r, "2024-25") == 10 * L
    assert lu.available_for_year_paise(r, "2025-26") == 7 * L


def test_a_later_years_hand_entry_is_reported_as_a_later_use_with_its_kind():
    r = {**row(), **lu.record_by_hand(row(), "2025-26", 2 * L)}
    assert lu.later_uses(r, "2024-25") == [{"filing_id": "manual:2025-26", "financial_year": "2025-26", "amount_paise": 2 * L, "return_type": "manual"}]


def test_the_view_draws_a_hand_entry_with_no_return_behind_it_and_says_so_by_its_kind():
    r = {**row({"F-24": entry("2023-24", 2 * L)}, baseline=1 * L), }
    r = {**r, **lu.record_by_hand(r, "2024-25", 3 * L)}
    for filings in ({"F-24": {"acknowledgement_number": "A24"}}, None, {}):
        items = {i["entry_id"]: i for i in lu.uses_view(r, filings)["uses"]}
        hand = items["manual:2024-25"]
        assert hand["return_type"] == "manual" and hand["filing_found"] is None and hand["acknowledgement_number"] is None
        assert hand["amount_paise"] == 3 * L and hand["financial_year"] == "2024-25"
    assert lu.uses_view(r, {})["hand_recorded_paise"] == 1 * L


# ── the rule: taking back ───────────────────────────────────────────────────────────────────────────────────────────

def test_taking_back_a_hand_entry_returns_the_record_to_what_it_was():
    before = row({"F-24": entry("2023-24", 2 * L)}, baseline=1 * L)
    after = {**before, **lu.record_by_hand(before, "2024-25", 3 * L)}
    back = lu.take_back(after, "manual:2024-25")
    assert back == {"utilisations": before["utilisations"], "utilized_amount_paise": before["utilized_amount_paise"],
                    "remaining_amount_paise": before["remaining_amount_paise"]}


def test_a_filings_entry_can_be_taken_back_too_and_nothing_else_moves():
    r = row({"F-24": entry("2023-24", 2 * L), "F-25": entry("2024-25", 3 * L)}, baseline=1 * L)
    back = lu.take_back(r, "F-25")
    assert back["utilisations"] == {"F-24": entry("2023-24", 2 * L)}
    assert back["utilized_amount_paise"] == 3 * L and back["remaining_amount_paise"] == 7 * L


def test_an_entry_that_is_not_there_is_refused():
    with pytest.raises(lu.NoSuchEntry):
        lu.take_back(row({"F-24": entry("2023-24", 2 * L)}), "F-99")
    with pytest.raises(lu.NoSuchEntry):
        lu.take_back(row(), "manual:2024-25")


# ── the service ─────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def world(monkeypatch):
    _MOCK_LOSSES.clear()
    log = []

    def audit(**kw):
        log.append(("audit", kw))

    monkeypatch.setattr(svc, "_write_audit_or_refuse", audit)
    real_store = svc.workspace.store_bf_loss_use

    def store(firm_id, loss_id, before, columns):
        log.append(("store", loss_id))
        return real_store(firm_id, loss_id, before, columns)

    monkeypatch.setattr(svc.workspace, "store_bf_loss_use", store)
    yield log
    _MOCK_LOSSES.clear()


def stored(loss_id="L1", firm=FIRM, entries=None, **kw):
    _MOCK_LOSSES[loss_id] = {"id": loss_id, "firm_id": firm, "client_id": MINE, "loss_type": "business", "assessment_year": "2023-24",
                             "expiry_assessment_year": "2031-32", **row(entries, **kw)}
    return _MOCK_LOSSES[loss_id]


def test_recording_a_year_writes_the_record_and_the_audit_entry_goes_first(world):
    stored()
    out = svc.record_year_use(USER, "L1", "2024-25", 3 * L, "Return filed on the portal before we took the client")
    assert out["state"] == "written" and out["recorded_paise"] == 3 * L and "FY 2024-25" in out["message"]
    assert [k for k, _ in world] == ["audit", "store"]
    assert _MOCK_LOSSES["L1"]["utilisations"]["manual:2024-25"]["amount_paise"] == 3 * L
    assert _MOCK_LOSSES["L1"]["utilized_amount_paise"] == 3 * L and _MOCK_LOSSES["L1"]["remaining_amount_paise"] == 7 * L
    audit = world[0][1]
    assert audit["change"] == "year_use_recorded_by_hand" and audit["reason"].startswith("Return filed")
    assert audit["requested"] == {"financial_year": "2024-25", "amount_paise": 3 * L} and audit["row"]["id"] == "L1"


def test_recording_the_same_figure_again_changes_nothing_and_writes_no_audit_entry(world):
    stored()
    svc.record_year_use(USER, "L1", "2024-25", 3 * L, "first")
    world.clear()
    out = svc.record_year_use(USER, "L1", "2024-25", 3 * L, "again")
    assert out["state"] == "unchanged" and world == []


@pytest.mark.parametrize("reason", [None, "", "   "])
def test_a_reason_is_required_and_nothing_is_written_without_one(world, reason):
    stored()
    with pytest.raises(svc.UseRefused) as e:
        svc.record_year_use(USER, "L1", "2024-25", 3 * L, reason)
    assert e.value.status == 422 and "Say why" in e.value.sentence
    assert world == [] and _MOCK_LOSSES["L1"]["utilisations"] == {}


def test_a_reason_past_its_limit_is_refused(world):
    stored()
    with pytest.raises(svc.UseRefused) as e:
        svc.record_year_use(USER, "L1", "2024-25", 3 * L, "x" * (svc.MAX_REASON_CHARS + 1))
    assert e.value.status == 422 and str(svc.MAX_REASON_CHARS) in e.value.sentence and world == []
    svc.record_year_use(USER, "L1", "2024-25", 3 * L, "x" * svc.MAX_REASON_CHARS)


def test_a_year_a_return_holds_is_refused_in_a_sentence_that_says_where_to_correct_it(world):
    stored(entries={"F-25": entry("2024-25", 2 * L)})
    with pytest.raises(svc.UseRefused) as e:
        svc.record_year_use(USER, "L1", "2024-25", 1 * L, "why")
    assert e.value.status == 409 and "Tax Filing" in e.value.sentence and "FY 2024-25" in e.value.sentence
    assert world == []


def test_an_amount_past_the_room_is_refused_with_the_figure_it_could_take(world):
    stored(entries={"F-24": entry("2023-24", 8 * L)})
    with pytest.raises(svc.UseRefused) as e:
        svc.record_year_use(USER, "L1", "2024-25", 3 * L, "why")
    assert e.value.status == 422 and "₹2,00,000" in e.value.sentence and "₹10,00,000" in e.value.sentence
    assert world == [] and "manual:2024-25" not in _MOCK_LOSSES["L1"]["utilisations"]


def test_a_label_that_is_not_a_year_is_a_sentence_and_not_a_traceback(world):
    stored()
    with pytest.raises(svc.UseRefused) as e:
        svc.record_year_use(USER, "L1", "last year", 1 * L, "why")
    assert e.value.status == 422 and e.value.sentence.endswith(".") and world == []


def test_a_loss_that_is_not_the_firms_is_not_found_and_nothing_is_written(world):
    stored("L-ALIEN", firm="F2")
    for call in (lambda: svc.record_year_use(USER, "L-ALIEN", "2024-25", L, "why"),
                 lambda: svc.take_back_use(USER, "L-ALIEN", "manual:2024-25", "why"),
                 lambda: svc.record_year_use(USER, "L-NONE", "2024-25", L, "why")):
        with pytest.raises(svc.UseRefused) as e:
            call()
        assert e.value.status == 404
    assert world == [] and _MOCK_LOSSES["L-ALIEN"]["utilisations"] == {}


def test_a_failure_to_write_the_audit_entry_refuses_the_change_and_leaves_the_record(world, monkeypatch):
    stored()

    def broken(**kw):
        raise svc.UseRefused("The loss record was not changed, because the audit log could not be written just now.", status=503)

    monkeypatch.setattr(svc, "_write_audit_or_refuse", broken)
    with pytest.raises(svc.UseRefused) as e:
        svc.record_year_use(USER, "L1", "2024-25", L, "why")
    assert e.value.status == 503
    assert world == [] and _MOCK_LOSSES["L1"]["utilisations"] == {} and _MOCK_LOSSES["L1"]["utilized_amount_paise"] == 0


def test_a_record_that_changed_under_the_write_is_refused_and_not_overwritten(world, monkeypatch):
    stored()
    # Another writer lands between the read and the write: the totals the write compares against no longer match.
    original_store = svc.workspace.store_bf_loss_use

    def racing(firm_id, loss_id, before, columns):
        _MOCK_LOSSES[loss_id]["utilized_amount_paise"] = 1 * L
        _MOCK_LOSSES[loss_id]["remaining_amount_paise"] = 9 * L
        return original_store(firm_id, loss_id, before, columns)

    monkeypatch.setattr(svc.workspace, "store_bf_loss_use", racing)
    with pytest.raises(svc.UseRefused) as e:
        svc.record_year_use(USER, "L1", "2024-25", 3 * L, "why")
    assert e.value.status == 409 and "changed while this was being saved" in e.value.sentence
    assert _MOCK_LOSSES["L1"]["utilisations"] == {}


def test_taking_back_a_hand_entry_removes_it_and_keeps_the_reason_first(world):
    stored()
    svc.record_year_use(USER, "L1", "2024-25", 3 * L, "first")
    world.clear()
    out = svc.take_back_use(USER, "L1", "manual:2024-25", "Typed against the wrong loss")
    assert out["state"] == "written" and "FY 2024-25" in out["message"] and "comes back" not in out["message"]
    assert [k for k, _ in world] == ["audit", "store"]
    assert world[0][1]["change"] == "use_taken_back" and world[0][1]["reason"] == "Typed against the wrong loss"
    assert world[0][1]["requested"] == {"entry_id": "manual:2024-25", "financial_year": "2024-25", "amount_paise": 3 * L, "kind": "manual"}
    assert _MOCK_LOSSES["L1"]["utilisations"] == {} and _MOCK_LOSSES["L1"]["utilized_amount_paise"] == 0


def test_taking_back_a_filings_entry_says_it_comes_back_when_that_returns_records_are_written_again(world):
    stored(entries={"F-25": entry("2024-25", 2 * L)})
    out = svc.take_back_use(USER, "L1", "F-25", "The return was filed against the wrong loss")
    assert "comes back the next time that return's loss records are written" in out["message"]
    assert _MOCK_LOSSES["L1"]["utilisations"] == {}


def test_an_entry_already_taken_back_is_not_found_and_no_audit_entry_is_written(world):
    stored()
    with pytest.raises(svc.UseRefused) as e:
        svc.take_back_use(USER, "L1", "manual:2024-25", "why")
    assert e.value.status == 404 and world == []


def test_a_take_back_needs_a_reason_too(world):
    stored(entries={"F-25": entry("2024-25", 2 * L)})
    with pytest.raises(svc.UseRefused) as e:
        svc.take_back_use(USER, "L1", "F-25", " ")
    assert e.value.status == 422 and world == [] and "F-25" in _MOCK_LOSSES["L1"]["utilisations"]


# ── the audit entry itself ──────────────────────────────────────────────────────────────────────────────────────────

class _Table:
    def __init__(self, sink, fail):
        self.sink, self.fail = sink, fail

    def insert(self, payload):
        self.payload = payload
        return self

    def execute(self):
        if self.fail:
            raise RuntimeError("down")
        self.sink.append(self.payload)


class _Client:
    def __init__(self, fail=False):
        self.rows, self.fail = [], fail

    def table(self, name):
        assert name == "audit_log"
        return _Table(self.rows, self.fail)


def test_the_audit_entry_carries_what_the_record_held_what_was_asked_and_the_reason_under_the_auth_id(monkeypatch):
    client = _Client()
    monkeypatch.setattr("core.supabase_client.get_service_supabase", lambda: client)
    held = {"id": "L1", "client_id": MINE, **row({"F-24": entry("2023-24", 2 * L)}, baseline=1 * L)}
    svc._write_audit_or_refuse(firm_id=FIRM, row=held, change="use_taken_back", requested={"entry_id": "F-24"}, reason="why", actor=USER)
    (written,) = client.rows
    assert written["actor_id"] == "a1" and written["actor_email"] == "ca@example.in"           # the AUTH id, not the users row id
    assert written["entity_type"] == "brought_forward_loss" and written["entity_id"] == "L1" and written["action"] == "update"
    assert written["old_data"] == {"utilisations": {"F-24": entry("2023-24", 2 * L)}, "utilized_amount_paise": 3 * L, "remaining_amount_paise": 7 * L}
    assert written["new_data"] == {"requested": {"entry_id": "F-24"}, "reason": "why"}
    assert written["metadata"] == {"client_id": MINE, "change": "use_taken_back"}


def test_an_audit_log_that_cannot_be_written_refuses_with_503(monkeypatch):
    monkeypatch.setattr("core.supabase_client.get_service_supabase", lambda: _Client(fail=True))
    with pytest.raises(svc.UseRefused) as e:
        svc._write_audit_or_refuse(firm_id=FIRM, row={"id": "L1", "client_id": MINE}, change="x", requested={}, reason="why", actor=USER)
    assert e.value.status == 503 and "Nothing changed" in e.value.sentence


# ── the routes ──────────────────────────────────────────────────────────────────────────────────────────────────────

def _route(path):
    return next(r for r in itr.router.routes if getattr(r, "path", "").endswith(path))


@pytest.mark.parametrize("path", ["/bf-losses/{loss_id}/year-use", "/bf-losses/{loss_id}/uses/{entry_id}/take-back"])
def test_each_route_is_a_post_at_the_compute_tier_and_checks_the_losses_client(path):
    route = _route(path)
    assert route.methods == {"POST"}
    src = open(itr.__file__, encoding="utf-8").read()
    body = src.split(f'@router.post("{path}")')[1].split("@router.")[0]
    assert 'rbac("income_tax", "compute")' in body and "_assert_bf_loss_scope(current_user, loss_id)" in body


def test_the_old_route_that_typed_a_total_in_with_no_year_is_gone():
    assert not any(getattr(r, "path", "").endswith("/utilize") for r in itr.router.routes)
    assert not hasattr(itr, "utilize_loss") and not hasattr(itr, "UtilizeLossRequest")
    from domain.income_tax import computation_workspace
    assert not hasattr(computation_workspace, "utilize_bf_loss")


def test_a_refusal_reaches_the_caller_as_its_own_status_and_sentence(monkeypatch):
    from fastapi import HTTPException
    _MOCK_LOSSES.clear()
    stored(entries={"F-25": entry("2024-25", 2 * L)})
    monkeypatch.setattr(svc, "_write_audit_or_refuse", lambda **kw: None)
    monkeypatch.setattr(itr, "can_access_client", lambda user, client_id: True)
    with pytest.raises(HTTPException) as e:
        itr.record_year_use("L1", itr.YearUseRequest(financial_year="2024-25", amount_paise=L, reason="why"), current_user=USER)
    assert e.value.status_code == 409 and "Tax Filing" in e.value.detail
    _MOCK_LOSSES.clear()


@pytest.mark.parametrize("bad", [{"financial_year": "2026-28"}, {"financial_year": "last year"}, {"amount_paise": -1}, {"reason": "x" * 2001}])
def test_a_request_with_a_bad_year_amount_or_reason_is_refused_at_the_door(bad):
    from pydantic import ValidationError
    good = {"financial_year": "2024-25", "amount_paise": 1, "reason": "why"}
    with pytest.raises(ValidationError):
        itr.YearUseRequest(**{**good, **bad})


# ── the words ───────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_sentences_that_said_there_was_no_screen_name_the_screen_now_and_advise_nothing():
    assert "no screen yet" not in svc._WHERE_TO_CORRECT.lower()
    assert "Tax Computation screen" in svc._WHERE_TO_CORRECT
    # It says where a record can be corrected, and does not tell anyone to record anything: for an updated return (section 139(8A)) how its
    # set-off sits beside the return it updates has not been read from the Act, so no sentence about it may advise a use.
    assert "by hand" not in svc._WHERE_TO_CORRECT
    src = open(svc.__file__, encoding="utf-8").read()
    assert "no screen yet" not in src.lower() and "_NO_SCREEN" not in src


def test_the_later_years_sentence_names_hand_entries_when_there_are_some():
    r = {**row(), **lu.record_by_hand(row(), "2025-26", 2 * L)}
    assert "uses recorded by hand" in svc._later_years_sentence(r, "2024-25")
    r2 = row({"F-26": entry("2025-26", 2 * L)})
    sentence = svc._later_years_sentence(r2, "2024-25")
    assert sentence.startswith("The returns for later years have") and "by hand" not in sentence


# ── found in review: what a return's write does to a hand entry, and sentences that named a return where there was none ───────────────────

FILING = {"id": "F-25", "financial_year": "2024-25", "return_type": "original", "client_id": MINE}


def test_a_return_that_does_not_name_a_loss_leaves_the_use_recorded_by_hand_for_its_year():
    """The saved computation set off a TYPED-IN loss (no record id): it cannot say this loss was untouched, so the hand entry stays."""
    r = {"id": "L1", **row(), **lu.record_by_hand(row(), "2024-25", 3 * L)}
    assert svc._targets({"L1": r}, {}, FILING) == {}
    # ...while a return's OWN earlier entry for the same year is still cleared, as it always was
    earlier = {"id": "L2", **row({"F-24b": entry("2024-25", 2 * L, "revised")})}
    assert svc._targets({"L2": earlier}, {}, FILING) == {"L2": 0}


def test_a_return_that_names_the_loss_replaces_the_hand_entry_and_says_so():
    r = stored(entries={"manual:2024-25": entry("2024-25", 3 * L, "manual")}, baseline=0)
    out = svc._write_one(FIRM, FILING, r, 4 * L)
    assert out["state"] == "written" and out["used_paise"] == 4 * L and out["replaced_by_hand_paise"] == 3 * L
    assert "₹3,00,000.00 recorded by hand for FY 2024-25 was replaced" in out["message"]
    assert list(_MOCK_LOSSES["L1"]["utilisations"]) == ["F-25"]


def test_a_write_that_replaced_nothing_by_hand_says_nothing_about_it():
    out = svc._write_one(FIRM, FILING, stored(), 4 * L)
    assert "replaced_by_hand_paise" not in out and "message" not in out


def test_the_acknowledgements_audit_event_carries_the_hand_figure_it_replaced():
    from unittest import mock
    events = []
    with mock.patch("services.audit_service.log_event", lambda *a, **k: events.append(k)):
        itr._audit_the_loss_records(USER, FILING, {"losses": [
            {"state": "written", "loss_id": "L1", "used_paise": 4 * L, "requested_paise": 4 * L, "replaced_by_hand_paise": 3 * L},
            {"state": "written", "loss_id": "L2", "used_paise": L, "requested_paise": L}]})
    assert events[0]["new_data"]["replaced_by_hand_paise"] == 3 * L and "replaced_by_hand_paise" not in events[1]["new_data"]


def test_the_room_sentence_says_the_most_the_year_could_be_and_not_more_than_what_is_there(world):
    stored(entries={"manual:2024-25": entry("2024-25", 2 * L, "manual")})
    with pytest.raises(svc.UseRefused) as e:
        svc.record_year_use(USER, "L1", "2024-25", 11 * L, "why")
    assert "cannot be recorded as using more than ₹10,00,000.00 of this loss" in e.value.sentence and " more for " not in e.value.sentence


def test_a_hand_entry_alone_is_not_called_a_return_in_the_later_years_sentence_or_the_offer_note():
    only = {**row(), **lu.record_by_hand(row(), "2025-26", 2 * L)}
    s = svc._later_years_sentence(only, "2024-25")
    assert s.startswith("The uses recorded by hand for later years have") and "that later return" not in s and "what was recorded for those years" in s
    mixed = {**row({"F-26": entry("2026-27", 1 * L)}), **lu.record_by_hand(row({"F-26": entry("2026-27", 1 * L)}), "2025-26", 2 * L)}
    assert "and the uses recorded by hand for some of them" in svc._later_years_sentence(mixed, "2024-25")
    own = {**row(), **lu.record_by_hand(row(), "2024-25", 3 * L)}
    note = svc._offer_note(own, 10 * L, 10 * L, "2024-25")
    assert "recorded by hand for FY 2024-25 itself is offered back" in note and "used by the return" not in note
    ret = row({"F-25": entry("2024-25", 3 * L)})
    assert "used by the return for FY 2024-25 itself is offered back" in svc._offer_note(ret, 10 * L, 10 * L, "2024-25")


def test_an_unrecorded_return_beside_a_hand_entry_does_not_say_the_figure_counts_it_as_unused():
    plain = svc._unrecorded_sentence([{"financial_year": "2024-25", "set_off_paise": 4 * L, "acknowledgement_number": None,
                                       "recorded_by_hand_paise": 0}])
    assert "counts that part as unused" in plain
    beside = svc._unrecorded_sentence([{"financial_year": "2024-25", "set_off_paise": 4 * L, "acknowledgement_number": None,
                                        "recorded_by_hand_paise": 3 * L}])
    assert "counts that part as unused" not in beside and "₹3,00,000" in beside and "replaces the hand entry" in beside


def test_a_revised_return_that_used_nothing_is_listed_so_it_can_be_seen_and_taken_back_and_the_year_then_recorded():
    r = row({"F-R": entry("2024-25", 0, "revised"), "F-O": entry("2023-24", 0, "original")})
    items = lu.uses_view(r, {"F-R": {"acknowledgement_number": "R1"}})["uses"]
    assert [(i["entry_id"], i["amount_paise"], i["return_type"]) for i in items] == [("F-R", 0, "revised")]        # an original's nothing is not a use
    with pytest.raises(lu.HeldByReturn):
        lu.record_by_hand(r, "2024-25", L)
    freed = {**r, **lu.take_back(r, "F-R")}
    assert "manual:2024-25" in lu.record_by_hand(freed, "2024-25", L)["utilisations"]


def test_the_held_year_sentence_says_how_to_correct_a_return_whose_own_use_is_wrong(world):
    stored(entries={"F-25": entry("2024-25", 2 * L)})
    with pytest.raises(svc.UseRefused) as e:
        svc.record_year_use(USER, "L1", "2024-25", 1 * L, "why")
    assert "take it off the list first and then record the year" in e.value.sentence
