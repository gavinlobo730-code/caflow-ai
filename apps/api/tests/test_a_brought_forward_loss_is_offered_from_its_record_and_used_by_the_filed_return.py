"""POST-A-073 — a brought-forward loss is offered from its record, and the return that is filed uses it.

WHAT WAS WRONG
    The computation screen read `brought_forward_losses` itself and sent the figure it held. Nothing wrote the loss's `utilized_amount_paise` when
    a return was filed, so next year's computation reloaded the whole loss unless the CA edited the record by hand. The obvious write-back (add the
    year's use to the running total) would have made a second, quieter wrong number: recomputing the SAME year, for a revised return, would offer
    the loss net of its own earlier use. The pure rule is pinned in `test_a_loss_is_used_per_filing_and_per_year.py`; this file pins the places it
    is used.

WHAT THIS PINS
    COMPUTE   a loss named by its record id is offered at what the record says THIS year may use, whatever the screen sent, and the answer says
              why in a sentence; it must be THIS client's record (a stale tab cannot take another client's relief); the record's type, year,
              expiry and expired flag win over the request's; a record the caller may not use is the same 404 as a missing one; the same record
              twice is refused; a fully used loss the screen also held at nothing is not listed; a loss with no id is exactly what it was.
    FILING    the acknowledgement writes each set-off loss back, per filing and per year, each on its own, so one failing leaves the others'
              answers true; a revised return replaces the original's use, even when it used nothing, and an original acknowledged after it does
              not write over it; an updated return writes nothing and says why; a computation that names no record, another client's, another
              year's or in a shape this cannot read writes nothing and says why; a forged id spends nothing; a use beyond the loss is capped AND
              SAID; the write is idempotent, including a second submit that loses the race; a caller who may approve but not change loss records
              is told so; and it NEVER fails the acknowledgement or happens for one the state machine refused.
    FILING MADE   a filing that pins a saved computation pins this client's own computation for the year.
"""
import pytest
from fastapi import HTTPException

import routers.income_tax as it
import routers.itr_workspace as itr
from domain.income_tax import computation_workspace as workspace
from domain.income_tax.computation_workspace import _MOCK_LOSSES, _MOCK_SNAPSHOTS
from domain.income_tax.itr_workflow import _MOCK_FILINGS
from services import bf_loss_service as svc

L = 1_00_000_00   # one lakh, in paise
FIRM = "F1"
MINE = "00000000-0000-4000-8000-0000000000a1"
OTHER = "00000000-0000-4000-8000-0000000000a2"
HIDDEN = "00000000-0000-4000-8000-0000000000a3"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "a1", "email": "ca@example.in", "role": "Partner"}


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    for store in (_MOCK_LOSSES, _MOCK_SNAPSHOTS, _MOCK_FILINGS):
        store.clear()
    monkeypatch.setattr(svc, "can_access_client", lambda user, client_id: str(client_id) != HIDDEN)
    yield
    for store in (_MOCK_LOSSES, _MOCK_SNAPSHOTS, _MOCK_FILINGS):
        store.clear()


def _id(n):
    return f"5b4c3a0e-0000-4000-8000-{n:012d}"


def loss(loss_id="L1", *, client=MINE, firm=FIRM, kind="business", ay="2024-25", original=10 * L, utilized=0, entries=None,
         ack="ACK-1", expiry="2032-33", **extra):
    _MOCK_LOSSES[loss_id] = {
        "id": loss_id, "firm_id": firm, "client_id": client, "loss_type": kind, "assessment_year": ay,
        "original_amount_paise": original, "utilized_amount_paise": utilized, "remaining_amount_paise": original - utilized,
        "expiry_assessment_year": expiry, "source_itr_ack": ack, "utilisations": entries or {}, **extra,
    }
    return _MOCK_LOSSES[loss_id]


def compute(fy="2025-26", *, business=20 * L, losses, client=MINE):
    res = it.compute_itr(it.ComputeITRRequest(fy=fy, business_income_paise=business, brought_forward_losses=losses, client_id=client), USER)
    return res["data"]["brought_forward"]


def filing(filing_id="F-ORIG", *, fy="2025-26", kind="original", snapshot_id=None, client=MINE, status="ready_for_filing"):
    _MOCK_FILINGS[filing_id] = {
        "id": filing_id, "firm_id": FIRM, "client_id": client, "financial_year": fy, "assessment_year": "2026-27",
        "return_type": kind, "status": status, "computation_snapshot_id": snapshot_id, "itr_form": "ITR-3",
    }
    return _MOCK_FILINGS[filing_id]


def snapshot(snapshot_id="S1", *, client=MINE, fy="2025-26", lines=None, computation=None):
    lines = lines if lines is not None else []
    _MOCK_SNAPSHOTS[snapshot_id] = {
        "id": snapshot_id, "firm_id": FIRM, "client_id": client, "financial_year": fy,
        "computation_json": computation if computation is not None else {
            "brought_forward": {"set_off_paise": sum(ln["set_off_paise"] for ln in lines), "lines": lines}},
    }
    return _MOCK_SNAPSHOTS[snapshot_id]


def line(loss_id, used):
    return {"loss_id": loss_id, "loss_type": "business", "section": "§72", "set_off_paise": used}


# ───────────────────────────── COMPUTE ─────────────────────────────

def test_a_loss_with_an_id_is_offered_at_what_the_record_says_and_the_answer_says_why():
    loss(_id(1), original=10 * L, utilized=4 * L)                      # 6 lakh remain on the record
    bf = compute(losses=[{"id": _id(1), "loss_type": "business", "amount_paise": 9 * L}])
    assert bf["set_off_paise"] == 6 * L, "the screen sent 9 lakh and the record holds 6"
    assert bf["lines"][0]["loss_id"] == _id(1)
    [note] = bf["offered_from_record"]
    assert note["sent_paise"] == 9 * L and note["offered_paise"] == 6 * L
    for rupees in ("₹6,00,000.00", "₹9,00,000.00", "₹10,00,000.00", "₹4,00,000.00"):
        assert rupees in note["note"], f"{rupees} missing: a sentence for a person names the rupees"
    assert "already used by returns for other years or recorded by hand" in note["note"]


def test_a_figure_the_screen_got_right_is_not_noted():
    loss(_id(1), original=10 * L, utilized=4 * L)
    bf = compute(losses=[{"id": _id(1), "loss_type": "business", "amount_paise": 6 * L}])
    assert bf["set_off_paise"] == 6 * L and bf["offered_from_record"] == []


def test_a_loss_with_no_id_is_computed_exactly_as_typed():
    bf = compute(losses=[{"loss_type": "business", "amount_paise": 4 * L}], client=None)
    assert bf["set_off_paise"] == 4 * L and bf["offered_from_record"] == []
    assert bf["lines"][0]["loss_id"] is None


def test_the_year_that_used_a_loss_is_offered_it_back_and_the_next_year_is_not():
    """THE HAZARD this exists for: a revised return for 2025-26 must not see the loss net of 2025-26's own use."""
    loss(_id(1), original=10 * L, utilized=4 * L, entries={"F-2025": {"financial_year": "2025-26", "amount_paise": 4 * L}})
    asked = [{"id": _id(1), "loss_type": "business", "amount_paise": 6 * L}]      # the screen sends what remains
    same_year = compute("2025-26", losses=asked)
    next_year = compute("2026-27", losses=asked)
    assert same_year["set_off_paise"] == 10 * L, "2025-26 again: its own 4 lakh is offered back"
    assert next_year["set_off_paise"] == 6 * L, "2026-27: net of the 4 lakh 2025-26 used"
    [note] = same_year["offered_from_record"]
    assert note["offered_paise"] == 10 * L
    assert "₹4,00,000.00 used by the return for FY 2025-26 itself is offered back because that year is being computed again" in note["note"], \
        "the note says WHY the figure moved, by cause"
    assert next_year["offered_from_record"] == []


def test_the_record_decides_the_head_the_expiry_and_the_expired_flag_not_the_request():
    """An id means the stored row: a request cannot attach a business loss's use to a capital head, lift its expiry, or un-expire it."""
    loss(_id(1), kind="business", original=5 * L, expiry="2025-26")        # last usable in AY 2025-26
    bf = compute("2025-26", losses=[{"id": _id(1), "loss_type": "capital_long_term", "amount_paise": 5 * L,
                                     "expiry_assessment_year": "2040-41"}])
    ln = bf["lines"][0]
    assert ln["loss_type"] == "business" and ln["section"] == "§72"
    late = compute("2025-26", losses=[{"id": _id(1), "loss_type": "business", "amount_paise": 5 * L, "expiry_assessment_year": "2040-41"}])
    assert late["set_off_paise"] == 0 and any("carried forward only to 2025-26" in r for r in late["lines"][0]["reasons"])
    loss(_id(2), kind="business", original=5 * L, is_expired=True)
    expired = compute("2025-26", losses=[{"id": _id(2), "loss_type": "business", "amount_paise": 5 * L, "is_expired": False}])
    assert expired["set_off_paise"] == 0 and any("marked expired" in r for r in expired["lines"][0]["reasons"])


def test_a_record_the_caller_cannot_use_is_the_same_404_as_a_missing_one():
    loss(_id(1), client=HIDDEN)
    loss(_id(2), firm="F2")
    for rid in (_id(1), _id(2), _id(3)):
        with pytest.raises(HTTPException) as e:
            compute(losses=[{"id": rid, "loss_type": "business", "amount_paise": L}], client=HIDDEN if rid == _id(1) else MINE)
        assert e.value.status_code == 404 and e.value.detail == "Loss record not found"


def test_another_clients_record_is_refused_even_when_the_caller_may_use_both_clients(monkeypatch):
    """A stale tab or a hand-made request: client B's loss id in client A's computation. The caller's scope covers both, so only the client
    on the request can tell."""
    loss(_id(1), client=OTHER, original=10 * L)
    monkeypatch.setattr(it, "assert_client_access", lambda user, client_id: None)
    with pytest.raises(HTTPException) as e:
        compute(losses=[{"id": _id(1), "loss_type": "business", "amount_paise": 10 * L}], client=MINE)
    assert e.value.status_code == 404 and e.value.detail == "Loss record not found"


def test_a_loss_named_by_record_in_a_computation_that_names_no_client_is_refused():
    loss(_id(1))
    with pytest.raises(HTTPException) as e:
        compute(losses=[{"id": _id(1), "loss_type": "business", "amount_paise": L}], client=None)
    assert e.value.status_code == 422 and "client" in e.value.detail


def test_the_same_record_twice_is_refused():
    loss(_id(1))
    with pytest.raises(HTTPException) as e:
        compute(losses=[{"id": _id(1), "loss_type": "business", "amount_paise": L}] * 2)
    assert e.value.status_code == 422


def test_a_fully_used_loss_the_screen_also_held_at_nothing_is_not_listed():
    loss(_id(1), original=10 * L, utilized=10 * L)
    loss(_id(2), original=5 * L)
    bf = compute(losses=[{"id": _id(1), "loss_type": "business", "amount_paise": 0},
                         {"id": _id(2), "loss_type": "business", "amount_paise": 5 * L}])
    assert [ln["loss_id"] for ln in bf["lines"]] == [_id(2)], "a used-up loss adds a zero line to the working panel for ever"
    assert bf["offered_from_record"] == []


def test_an_id_that_is_not_a_uuid_is_refused_by_the_model():
    with pytest.raises(ValueError):                      # pydantic's ValidationError is one
        it.BroughtForwardLossInput(id="L1", loss_type="business", amount_paise=L)


# ───────────────────────────── FILING ─────────────────────────────

def test_the_acknowledgement_writes_what_the_return_used_back_to_the_record():
    loss("L1", original=10 * L)
    f = filing(snapshot_id=snapshot(lines=[line("L1", 4 * L)])["id"])
    out = svc.write_back_filing(USER, f)
    assert out["state"] == svc.WRITTEN and out["losses"][0]["state"] == svc.WRITTEN and out["losses"][0]["used_paise"] == 4 * L
    assert "1 brought-forward loss record(s) now show what this return used" in out["message"]
    row = _MOCK_LOSSES["L1"]
    assert row["utilisations"] == {"F-ORIG": {"financial_year": "2025-26", "amount_paise": 4 * L, "return_type": "original"}}
    assert (row["utilized_amount_paise"], row["remaining_amount_paise"]) == (4 * L, 6 * L)


def test_recording_the_same_acknowledgement_again_changes_nothing():
    loss("L1", original=10 * L)
    f = filing(snapshot_id=snapshot(lines=[line("L1", 4 * L)])["id"])
    svc.write_back_filing(USER, f)
    again = svc.write_back_filing(USER, f)
    assert again["state"] == svc.UNCHANGED and _MOCK_LOSSES["L1"]["utilized_amount_paise"] == 4 * L


def test_a_revised_return_replaces_the_originals_use_for_the_same_year():
    loss("L1", original=10 * L)
    svc.write_back_filing(USER, filing("F-ORIG", snapshot_id=snapshot("S1", lines=[line("L1", 4 * L)])["id"]))
    svc.write_back_filing(USER, filing("F-REV", kind="revised", snapshot_id=snapshot("S2", lines=[line("L1", 6 * L)])["id"]))
    row = _MOCK_LOSSES["L1"]
    assert list(row["utilisations"]) == ["F-REV"], "one entry for the year, the revised return's"
    assert (row["utilized_amount_paise"], row["remaining_amount_paise"]) == (6 * L, 4 * L)


def test_a_revised_return_that_set_off_nothing_clears_the_use_its_original_recorded():
    """The computation lists no loss at all, and the original's 4 lakh still stands in the record: the revised return is the return now."""
    loss("L1", original=10 * L)
    svc.write_back_filing(USER, filing("F-ORIG", snapshot_id=snapshot("S1", lines=[line("L1", 4 * L)])["id"]))
    out = svc.write_back_filing(USER, filing("F-REV", kind="revised", snapshot_id=snapshot("S2", lines=[])["id"]))
    assert out["state"] == svc.WRITTEN
    row = _MOCK_LOSSES["L1"]
    assert (row["utilized_amount_paise"], row["remaining_amount_paise"]) == (0, 10 * L)
    assert row["utilisations"]["F-REV"]["amount_paise"] == 0


def test_an_original_acknowledged_after_the_revised_return_does_not_write_over_it():
    loss("L1", original=10 * L)
    svc.write_back_filing(USER, filing("F-REV", kind="revised", snapshot_id=snapshot("S2", lines=[line("L1", 2 * L)])["id"]))
    out = svc.write_back_filing(USER, filing("F-ORIG", snapshot_id=snapshot("S1", lines=[line("L1", 5 * L)])["id"]))
    assert out["state"] == svc.NOT_WRITTEN and "already holds this year's use" in out["message"]
    assert list(_MOCK_LOSSES["L1"]["utilisations"]) == ["F-REV"] and _MOCK_LOSSES["L1"]["utilized_amount_paise"] == 2 * L


def test_the_next_years_return_adds_beside_the_first_and_leaves_it_alone():
    loss("L1", original=10 * L)
    svc.write_back_filing(USER, filing("F-25", fy="2025-26", snapshot_id=snapshot("S1", fy="2025-26", lines=[line("L1", 4 * L)])["id"]))
    svc.write_back_filing(USER, filing("F-26", fy="2026-27", snapshot_id=snapshot("S2", fy="2026-27", lines=[line("L1", 3 * L)])["id"]))
    row = _MOCK_LOSSES["L1"]
    assert set(row["utilisations"]) == {"F-25", "F-26"} and row["remaining_amount_paise"] == 3 * L


def test_an_updated_return_writes_nothing_and_says_why():
    loss("L1", original=10 * L)
    out = svc.write_back_filing(USER, filing(kind="updated", snapshot_id=snapshot(lines=[line("L1", 4 * L)])["id"]))
    assert out["state"] == svc.NOT_WRITTEN and "This is an updated return" in out["message"] and "no screen yet" in out["message"]
    assert "by hand" not in out["message"], "no screen can record a loss by hand, so the sentence must not tell anyone to"
    assert _MOCK_LOSSES["L1"]["utilized_amount_paise"] == 0


@pytest.mark.parametrize("make,fragment", [
    (lambda: filing(snapshot_id=None), "was not created from a saved computation"),
    (lambda: filing(snapshot_id="gone"), "could not be read for this client"),
    (lambda: filing(snapshot_id=snapshot(client=OTHER, lines=[line("L1", L)])["id"]), "could not be read for this client"),
    (lambda: filing(fy="2024-25", snapshot_id=snapshot(fy="2025-26", lines=[line("L1", L)])["id"]), "is for FY 2025-26 and the return"),
    (lambda: filing(snapshot_id=snapshot(computation={"income": {}})["id"]), "does not list its brought-forward losses"),
    (lambda: filing(snapshot_id=snapshot(computation={"brought_forward": {"lines": "x"}})["id"]), "does not list its brought-forward losses"),
])
def test_a_computation_that_cannot_be_trusted_for_this_return_writes_nothing_and_says_why(make, fragment):
    loss("L1", original=10 * L)
    out = svc.write_back_filing(USER, make())
    assert out["state"] == svc.NOT_WRITTEN and fragment in out["message"]
    assert _MOCK_LOSSES["L1"]["utilized_amount_paise"] == 0


def test_a_client_with_no_loss_on_record_hears_nothing_whatever_the_return_is():
    """The callout would be a cry of wolf: no pin, an updated return and an unreadable computation all say nothing when there is no loss."""
    for f in (filing("A", snapshot_id=None), filing("B", kind="updated", snapshot_id=None), filing("C", snapshot_id="gone")):
        out = svc.write_back_filing(USER, f)
        assert out["state"] == svc.NO_LOSSES and out["message"] == "This client has no brought-forward loss on record."


def test_a_computation_that_set_off_nothing_says_nothing_and_one_that_names_no_record_says_so():
    loss("L1", original=10 * L)
    none_set_off = svc.write_back_filing(USER, filing(snapshot_id=snapshot("S1", lines=[])["id"]))
    assert none_set_off["state"] == svc.NO_LOSSES
    zero = svc.write_back_filing(USER, filing("F3", snapshot_id=snapshot("S3", lines=[{"section": "§72", "set_off_paise": 0}])["id"]))
    assert zero["state"] == svc.NO_LOSSES, "a typed-in loss that relieved nothing needs no note"
    typed_in = svc.write_back_filing(USER, filing("F2", snapshot_id=snapshot("S2", lines=[{"section": "§72", "set_off_paise": L}])["id"]))
    assert typed_in["state"] == svc.NOT_WRITTEN and "names no loss record" in typed_in["message"] and "no screen yet" in typed_in["message"]
    assert _MOCK_LOSSES["L1"]["utilized_amount_paise"] == 0


def test_a_typed_in_loss_is_not_hidden_behind_an_unchanged_record():
    """Probe: one line for a record at nothing plus one nameless line that set off 5 lakh. The record is unchanged and the 5 lakh is not."""
    loss("L1", original=10 * L)
    out = svc.write_back_filing(USER, filing(snapshot_id=snapshot(lines=[line("L1", 0), {"section": "§72", "set_off_paise": 5 * L}])["id"]))
    assert out["state"] == svc.NOT_WRITTEN and "typed in rather than taken from a record" in out["message"]


def test_another_clients_loss_in_the_snapshot_is_left_alone_and_the_rest_are_written():
    loss("L1", original=10 * L)
    loss("L-OTHER", client=OTHER, original=10 * L)
    f = filing(snapshot_id=snapshot(lines=[line("L1", 2 * L), line("L-OTHER", 5 * L), line("L-MISSING", L)])["id"])
    out = svc.write_back_filing(USER, f)
    assert [r["loss_id"] for r in out["losses"]] == ["L1"] and out["losses"][0]["state"] == svc.WRITTEN
    assert "2 loss(es) named in the computation are not records of this client and were left alone" in out["message"]
    assert _MOCK_LOSSES["L-OTHER"]["utilized_amount_paise"] == 0, "a forged id cannot spend another client's loss"
    assert out["state"] == svc.WRITTEN


def test_ten_thousand_forged_ids_cost_no_read_of_their_own_and_one_line(monkeypatch):
    loss("L1", original=10 * L)
    reads = []
    real = workspace.get_bf_loss
    monkeypatch.setattr(svc.workspace, "get_bf_loss", lambda *a, **k: (reads.append(a), real(*a, **k))[1])
    lines = [line(f"forged-{n}", L) for n in range(10_000)] + [line("L1", L)]
    out = svc.write_back_filing(USER, filing(snapshot_id=snapshot(lines=lines)["id"]))
    assert reads == [], "ids are looked up among the client's own records, read once"
    assert len(out["losses"]) == 1 and "10000 loss(es)" in out["message"]


def test_a_use_beyond_the_loss_is_capped_and_the_cap_is_said():
    """Two returns computed while nothing was recorded each set off 7 lakh of a 10 lakh loss. The second is capped, and the answer must say the
    returns together used more than there was, not that the records 'now show what this return used'."""
    loss("L1", original=10 * L)
    svc.write_back_filing(USER, filing("F-24", fy="2024-25", snapshot_id=snapshot("S1", fy="2024-25", lines=[line("L1", 7 * L)])["id"]))
    out = svc.write_back_filing(USER, filing("F-25", fy="2025-26", snapshot_id=snapshot("S2", lines=[line("L1", 7 * L)])["id"]))
    row = _MOCK_LOSSES["L1"]
    assert row["utilized_amount_paise"] == 10 * L and row["remaining_amount_paise"] == 0
    assert row["utilisations"]["F-25"]["amount_paise"] == 3 * L
    [r] = out["losses"]
    assert r["state"] == svc.WRITTEN and r["requested_paise"] == 7 * L and r["used_paise"] == 3 * L
    for fragment in ("set off ₹7,00,000.00", "could still take only ₹3,00,000.00", "used more of this loss than there was"):
        assert fragment in out["message"], fragment


def test_a_use_recorded_by_hand_is_kept_beside_the_returns():
    loss("L1", original=10 * L, utilized=3 * L)
    svc.write_back_filing(USER, filing(snapshot_id=snapshot(lines=[line("L1", 2 * L)])["id"]))
    assert _MOCK_LOSSES["L1"]["utilized_amount_paise"] == 5 * L


def test_one_loss_failing_leaves_the_others_answers_true(monkeypatch):
    """The first is stored when the second raises. An answer that said nothing was written would send the CA to record the first again."""
    loss("L1", original=10 * L)
    loss("L2", original=10 * L)
    real = workspace.store_bf_loss_use

    def boom_on_the_second(firm, loss_id, before, columns):
        if loss_id == "L2":
            raise RuntimeError("the database did not answer")
        return real(firm, loss_id, before, columns)

    monkeypatch.setattr(svc.workspace, "store_bf_loss_use", boom_on_the_second)
    out = svc.write_back_filing(USER, filing(snapshot_id=snapshot(lines=[line("L1", 3 * L), line("L2", 2 * L)])["id"]))
    states = {r["loss_id"]: r["state"] for r in out["losses"]}
    assert states == {"L1": svc.WRITTEN, "L2": svc.NOT_WRITTEN}
    assert _MOCK_LOSSES["L1"]["utilized_amount_paise"] == 3 * L
    assert out["state"] == svc.WRITTEN and "may or may not have been" in out["message"] and "1 brought-forward loss record(s) now show" in out["message"]


def test_a_record_that_changed_while_the_write_was_made_is_left_as_it_was(monkeypatch):
    loss("L1", original=10 * L)
    f = filing(snapshot_id=snapshot(lines=[line("L1", L)])["id"])

    def refused_after_a_hand_edit(firm, loss_id, before, columns):
        _MOCK_LOSSES[loss_id]["utilized_amount_paise"], _MOCK_LOSSES[loss_id]["remaining_amount_paise"] = 1 * L, 9 * L
        return False

    monkeypatch.setattr(svc.workspace, "store_bf_loss_use", refused_after_a_hand_edit)
    out = svc.write_back_filing(USER, f)
    assert out["state"] == svc.NOT_WRITTEN and "changed while this was being written" in out["losses"][0]["message"]
    assert _MOCK_LOSSES["L1"]["utilisations"] == {}, "the record was not written"


def test_a_record_the_caller_may_not_write_is_told_apart_from_one_that_changed(monkeypatch):
    """Row security answers a blocked update with no row and no error, so the refusal re-reads the record: unchanged totals mean the
    write was not allowed, not that another write landed first."""
    loss("L1", original=10 * L)
    monkeypatch.setattr(svc.workspace, "store_bf_loss_use", lambda *a, **k: False)
    out = svc.write_back_filing(USER, filing(snapshot_id=snapshot(lines=[line("L1", L)])["id"]))
    msg = out["losses"][0]["message"]
    assert out["state"] == svc.NOT_WRITTEN and "could not be written with your access" in msg and "changed while" not in msg
    assert _MOCK_LOSSES["L1"]["utilized_amount_paise"] == 0


def test_a_second_submit_that_lost_the_race_finds_the_record_already_right(monkeypatch):
    """Two tabs record the same acknowledgement. The second's compare fails because the first wrote; the record holds exactly what the second
    would have stored, so the answer is 'unchanged' and not a sentence telling the CA to fix something that is fine."""
    loss("L1", original=10 * L)
    f = filing(snapshot_id=snapshot(lines=[line("L1", 4 * L)])["id"])
    real = workspace.store_bf_loss_use

    def first_one_got_there_first(firm, loss_id, before, columns):
        real(firm, loss_id, dict(_MOCK_LOSSES[loss_id]), columns)       # the other request's write lands
        return False

    monkeypatch.setattr(svc.workspace, "store_bf_loss_use", first_one_got_there_first)
    out = svc.write_back_filing(USER, f)
    assert out["state"] == svc.UNCHANGED and "message" not in out["losses"][0]
    assert _MOCK_LOSSES["L1"]["utilized_amount_paise"] == 4 * L


def test_a_caller_who_may_approve_but_not_change_loss_records_is_told_so(monkeypatch):
    loss("L1", original=10 * L)
    monkeypatch.setattr(svc, "can_user", lambda user, resource, action: (resource, action) != ("income_tax", "compute"))
    out = svc.write_back_filing(USER, filing(snapshot_id=snapshot(lines=[line("L1", L)])["id"]))
    assert out["state"] == svc.NOT_WRITTEN and "approve a return but not change loss records" in out["message"]
    assert _MOCK_LOSSES["L1"]["utilized_amount_paise"] == 0


def test_the_store_refuses_a_write_when_the_totals_moved_underneath_it():
    row = loss("L1", original=10 * L)
    before = dict(row)
    row["utilized_amount_paise"], row["remaining_amount_paise"] = 1 * L, 9 * L            # a hand edit landed first
    assert workspace.store_bf_loss_use(FIRM, "L1", before, {"utilisations": {}, "utilized_amount_paise": 4 * L,
                                                            "remaining_amount_paise": 6 * L}) is False
    assert row["utilized_amount_paise"] == 1 * L


def test_the_real_store_names_the_row_the_firm_and_both_totals_it_read(monkeypatch):
    """The production branch is the one mock mode never runs: a dropped .eq would let a stale write overwrite a hand edit, silently."""
    calls = []

    class Fake:
        def table(self, name):
            calls.append(("table", name))
            return self

        def update(self, columns):
            calls.append(("update", columns))
            return self

        def eq(self, column, value):
            calls.append(("eq", column, value))
            return self

        def execute(self):
            return type("R", (), {"data": [{"id": "L1"}]})()

    monkeypatch.setattr(workspace, "_USE_MOCK", False)
    monkeypatch.setattr(workspace, "_supabase", lambda: Fake())
    columns = {"utilisations": {}, "utilized_amount_paise": 4 * L, "remaining_amount_paise": 6 * L}
    assert workspace.store_bf_loss_use(FIRM, "L1", {"utilized_amount_paise": 0, "remaining_amount_paise": 10 * L}, columns) is True
    assert calls[:2] == [("table", "brought_forward_losses"), ("update", columns)]
    assert {c[1:] for c in calls if c[0] == "eq"} == {("id", "L1"), ("firm_id", FIRM), ("utilized_amount_paise", 0),
                                                       ("remaining_amount_paise", 10 * L)}


def test_a_failure_before_any_write_never_raises_and_says_so(monkeypatch):
    loss("L1", original=10 * L)
    monkeypatch.setattr(svc.workspace, "get_snapshot", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("database down")))
    out = svc.write_back_filing(USER, filing(snapshot_id="S1"))
    assert out["state"] == svc.NOT_WRITTEN and "acknowledgement is recorded" in out["message"] and "Check each loss" in out["message"]
    assert "by hand" not in out["message"]


# ───────────────── through the acknowledge route, end to end ─────────────────

@pytest.fixture
def ack_route(monkeypatch):
    monkeypatch.setattr(itr, "can_access_client", lambda user, client_id: True)
    monkeypatch.setattr(itr, "_close_the_obligation", lambda user, f, req: {"state": "not_closed"})
    monkeypatch.setattr(itr.timeline_service, "log", lambda **k: None)
    events = []
    import services.audit_service as audit
    monkeypatch.setattr(audit, "log_event", lambda *a, **k: events.append((a, k)))
    return events


def _acknowledge(filing_id="F-ORIG"):
    return itr.record_acknowledgement(
        filing_id, itr.AcknowledgementRequest(acknowledgement_number="ACK-123456789", filing_date="2026-07-20"), USER)


def test_recording_the_acknowledgement_answers_with_what_became_of_each_loss_and_audits_it(ack_route):
    loss("L1", original=10 * L)
    filing("F-ORIG", snapshot_id=snapshot(lines=[line("L1", 4 * L)])["id"])
    data = _acknowledge()["data"]
    assert data["status"] == "filed"
    assert data["brought_forward_losses"]["state"] == svc.WRITTEN
    assert _MOCK_LOSSES["L1"]["remaining_amount_paise"] == 6 * L
    [(args, kwargs)] = ack_route
    assert args[:4] == (FIRM, "brought_forward_loss", "L1", "update")
    assert kwargs["actor_id"] == "a1", "the audit log names the AUTH id, never the internal one"
    assert kwargs["new_data"]["itr_filing_id"] == "F-ORIG" and kwargs["new_data"]["used_paise"] == 4 * L


def test_a_refused_acknowledgement_leaves_the_losses_untouched(ack_route):
    """The write-back must come AFTER the state machine: a draft whose computation was never reviewed must not consume a client's loss."""
    loss("L1", original=10 * L)
    filing("F-DRAFT", status="draft", snapshot_id=snapshot(lines=[line("L1", 4 * L)])["id"])
    with pytest.raises(HTTPException) as e:
        _acknowledge("F-DRAFT")
    assert e.value.status_code == 400
    assert _MOCK_LOSSES["L1"]["utilized_amount_paise"] == 0 and ack_route == []
    filing("F-DONE", status="filed", snapshot_id=snapshot("S9", lines=[line("L1", 4 * L)])["id"])
    with pytest.raises(HTTPException):
        _acknowledge("F-DONE")
    assert _MOCK_LOSSES["L1"]["utilized_amount_paise"] == 0


def test_only_a_record_that_changed_is_audited(ack_route):
    loss("L1", original=10 * L)
    filing("F-ORIG", snapshot_id=snapshot(lines=[line("L1", 0)])["id"])
    _acknowledge()
    assert ack_route == []


# ───────────────── a filing is created from this client's own computation ─────────────────

def _create(snapshot_id, *, client=MINE, fy="2025-26"):
    return itr.create_filing(itr.CreateFilingRequest(
        client_id=client, financial_year=fy, assessment_year="2026-27", itr_form="ITR-3", computation_snapshot_id=snapshot_id), USER)


def test_a_filing_pins_this_clients_computation_for_this_year(monkeypatch):
    monkeypatch.setattr(itr, "assert_client_access", lambda user, client_id: None)
    monkeypatch.setattr(itr.timeline_service, "log", lambda **k: None)
    own = snapshot("S-OWN", client=MINE, fy="2025-26")
    assert _create(own["id"])["data"]["computation_snapshot_id"] == "S-OWN"
    assert _create(None)["data"]["computation_snapshot_id"] is None, "a return computed outside the product pins nothing"


@pytest.mark.parametrize("make", [
    lambda: snapshot("S-X", client=OTHER),
    lambda: snapshot("S-X", fy="2024-25"),
])
def test_a_filing_cannot_pin_another_clients_or_another_years_computation(make, monkeypatch):
    monkeypatch.setattr(itr, "assert_client_access", lambda user, client_id: None)
    make()
    with pytest.raises(HTTPException) as e:
        _create("S-X")
    assert e.value.status_code == 400 and "not one of this client's for FY 2025-26" in e.value.detail
    with pytest.raises(HTTPException):
        _create("no-such-snapshot")
