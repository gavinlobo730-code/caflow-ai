"""POST-A-073 — a brought-forward loss is offered from its record, and the return that is filed uses it.

WHAT WAS WRONG
    The computation screen read `brought_forward_losses` itself and sent the figure it held. Nothing wrote the loss's `utilized_amount_paise` when
    a return was filed, so next year's computation reloaded the whole loss unless the CA edited the record by hand. The obvious write-back (add the
    year's use to the running total) would have made a second, quieter wrong number: recomputing the SAME year, for a revised return, would offer
    the loss net of its own earlier use. The pure rule is pinned in `test_a_loss_is_used_per_filing_and_per_year.py`; this file pins the two
    places it is used.

WHAT THIS PINS
    COMPUTE   a loss named by its record id is offered at what the record says THIS year may use, whatever the screen sent, and the answer says
              when that differs; the record's type, year and expiry win over the request's; a record the caller may not use is the same 404 as
              a missing one; the same record twice is refused; a loss with no id is exactly what it was.
    FILING    the acknowledgement writes each set-off loss back, per filing and per year; a revised return replaces the original's use; an updated
              return writes nothing and says why; a snapshot that names no record, another client's, or another year's writes nothing and says
              why; a loss of another client inside the snapshot is left alone and the rest are written; the write is capped at the loss; it is
              idempotent; a concurrent change leaves the record as it was; and it NEVER fails the acknowledgement.
"""
import pytest
from fastapi import HTTPException

import routers.income_tax as it
import routers.itr_workspace as itr
from domain.income_tax.computation_workspace import _MOCK_LOSSES, _MOCK_SNAPSHOTS
from domain.income_tax.itr_workflow import _MOCK_FILINGS
from services import bf_loss_service as svc

L = 1_00_000_00   # one lakh, in paise
FIRM = "F1"
MINE, OTHER = "client-mine", "client-other"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "a1", "role": "Partner"}


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    for store in (_MOCK_LOSSES, _MOCK_SNAPSHOTS, _MOCK_FILINGS):
        store.clear()
    monkeypatch.setattr(svc, "can_access_client", lambda user, client_id: client_id != "client-hidden")
    yield
    for store in (_MOCK_LOSSES, _MOCK_SNAPSHOTS, _MOCK_FILINGS):
        store.clear()


def loss(loss_id="L1", *, client=MINE, firm=FIRM, kind="business", ay="2024-25", original=10 * L, utilized=0, entries=None,
         ack="ACK-1", expiry="2032-33"):
    _MOCK_LOSSES[loss_id] = {
        "id": loss_id, "firm_id": firm, "client_id": client, "loss_type": kind, "assessment_year": ay,
        "original_amount_paise": original, "utilized_amount_paise": utilized, "remaining_amount_paise": original - utilized,
        "expiry_assessment_year": expiry, "source_itr_ack": ack, "utilisations": entries or {},
    }
    return _MOCK_LOSSES[loss_id]


def compute(fy="2025-26", *, business=20 * L, losses):
    res = it.compute_itr(it.ComputeITRRequest(fy=fy, business_income_paise=business, brought_forward_losses=losses), USER)
    return res["data"]["brought_forward"]


def filing(filing_id="F-ORIG", *, fy="2025-26", kind="original", snapshot_id=None, client=MINE):
    _MOCK_FILINGS[filing_id] = {
        "id": filing_id, "firm_id": FIRM, "client_id": client, "financial_year": fy, "assessment_year": "2026-27",
        "return_type": kind, "status": "ready_for_filing", "computation_snapshot_id": snapshot_id, "itr_form": "ITR-3",
    }
    return _MOCK_FILINGS[filing_id]


def snapshot(snapshot_id="S1", *, client=MINE, fy="2025-26", lines):
    _MOCK_SNAPSHOTS[snapshot_id] = {
        "id": snapshot_id, "firm_id": FIRM, "client_id": client, "financial_year": fy,
        "computation_json": {"brought_forward": {"set_off_paise": sum(ln["set_off_paise"] for ln in lines), "lines": lines}},
    }
    return _MOCK_SNAPSHOTS[snapshot_id]


def line(loss_id, used):
    return {"loss_id": loss_id, "loss_type": "business", "section": "§72", "set_off_paise": used}


# ───────────────────────────── COMPUTE ─────────────────────────────

def _id(n):
    return f"5b4c3a0e-0000-4000-8000-{n:012d}"


def test_a_loss_with_an_id_is_offered_at_what_the_record_says_and_the_answer_says_so():
    loss(_id(1), original=10 * L, utilized=4 * L)                      # 6 lakh remain on the record
    bf = compute(losses=[{"id": _id(1), "loss_type": "business", "amount_paise": 9 * L}])
    assert bf["set_off_paise"] == 6 * L, "the screen sent 9 lakh and the record holds 6"
    assert bf["lines"][0]["loss_id"] == _id(1)
    [note] = bf["offered_from_record"]
    assert note["sent_paise"] == 9 * L and note["offered_paise"] == 6 * L
    assert "₹6,00,000.00" in note["note"] and "₹9,00,000.00" in note["note"], "a sentence for a person names rupees"


def test_a_figure_the_screen_got_right_is_not_noted():
    loss(_id(1), original=10 * L, utilized=4 * L)
    bf = compute(losses=[{"id": _id(1), "loss_type": "business", "amount_paise": 6 * L}])
    assert bf["set_off_paise"] == 6 * L and bf["offered_from_record"] == []


def test_a_loss_with_no_id_is_computed_exactly_as_typed():
    bf = compute(losses=[{"loss_type": "business", "amount_paise": 4 * L}])
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
    assert same_year["offered_from_record"][0]["offered_paise"] == 10 * L
    assert next_year["offered_from_record"] == []


def test_the_record_decides_the_head_and_the_expiry_not_the_request():
    """An id means the stored row: a request cannot attach a business loss's use to a capital head, or lift its expiry."""
    loss(_id(1), kind="business", original=5 * L, expiry="2025-26")        # last usable in AY 2025-26
    bf = compute("2025-26", losses=[{"id": _id(1), "loss_type": "capital_long_term", "amount_paise": 5 * L,
                                     "expiry_assessment_year": "2040-41"}])
    ln = bf["lines"][0]
    assert ln["loss_type"] == "business" and ln["section"] == "§72"
    # computing for AY 2026-27 is past the record's own expiry, whatever the request claimed
    late = compute("2025-26", losses=[{"id": _id(1), "loss_type": "business", "amount_paise": 5 * L, "expiry_assessment_year": "2040-41"}])
    assert late["set_off_paise"] == 0 and any("carried forward only to 2025-26" in r for r in late["lines"][0]["reasons"])


def test_a_record_the_caller_cannot_use_is_the_same_404_as_a_missing_one():
    loss(_id(1), client="client-hidden")
    loss(_id(2), firm="F2")
    for rid in (_id(1), _id(2), _id(3)):
        with pytest.raises(HTTPException) as e:
            compute(losses=[{"id": rid, "loss_type": "business", "amount_paise": L}])
        assert e.value.status_code == 404 and e.value.detail == "Loss record not found"


def test_the_same_record_twice_is_refused():
    loss(_id(1))
    with pytest.raises(HTTPException) as e:
        compute(losses=[{"id": _id(1), "loss_type": "business", "amount_paise": L}] * 2)
    assert e.value.status_code == 422


def test_an_id_that_is_not_a_uuid_is_refused_by_the_model():
    with pytest.raises(ValueError):                      # pydantic's ValidationError is one
        it.BroughtForwardLossInput(id="L1", loss_type="business", amount_paise=L)


# ───────────────────────────── FILING ─────────────────────────────

def test_the_acknowledgement_writes_what_the_return_used_back_to_the_record():
    loss("L1", original=10 * L)
    f = filing(snapshot_id=snapshot(lines=[line("L1", 4 * L)])["id"])
    out = svc.write_back_filing(USER, f)
    assert out["state"] == svc.WRITTEN and out["losses"][0]["state"] == svc.WRITTEN and out["losses"][0]["used_paise"] == 4 * L
    row = _MOCK_LOSSES["L1"]
    assert row["utilisations"] == {"F-ORIG": {"financial_year": "2025-26", "amount_paise": 4 * L}}
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


def test_the_next_years_return_adds_beside_the_first_and_leaves_it_alone():
    loss("L1", original=10 * L)
    svc.write_back_filing(USER, filing("F-25", fy="2025-26", snapshot_id=snapshot("S1", fy="2025-26", lines=[line("L1", 4 * L)])["id"]))
    svc.write_back_filing(USER, filing("F-26", fy="2026-27", snapshot_id=snapshot("S2", fy="2026-27", lines=[line("L1", 3 * L)])["id"]))
    row = _MOCK_LOSSES["L1"]
    assert set(row["utilisations"]) == {"F-25", "F-26"} and row["remaining_amount_paise"] == 3 * L


def test_an_updated_return_writes_nothing_and_says_why():
    loss("L1", original=10 * L)
    out = svc.write_back_filing(USER, filing(kind="updated", snapshot_id=snapshot(lines=[line("L1", 4 * L)])["id"]))
    assert out["state"] == svc.NOT_WRITTEN and "updated return" in out["message"] and "by hand" in out["message"]
    assert _MOCK_LOSSES["L1"]["utilized_amount_paise"] == 0


@pytest.mark.parametrize("make,fragment", [
    (lambda: filing(snapshot_id=None), "pins no saved computation"),
    (lambda: filing(snapshot_id="gone"), "could not be read for this client"),
    (lambda: filing(snapshot_id=snapshot(client=OTHER, lines=[line("L1", L)])["id"]), "could not be read for this client"),
    (lambda: filing(fy="2024-25", snapshot_id=snapshot(fy="2025-26", lines=[line("L1", L)])["id"]), "is for FY 2025-26 and the return"),
])
def test_a_computation_that_cannot_be_trusted_for_this_return_writes_nothing_and_says_why(make, fragment):
    loss("L1", original=10 * L)
    out = svc.write_back_filing(USER, make())
    assert out["state"] == svc.NOT_WRITTEN and fragment in out["message"]
    assert _MOCK_LOSSES["L1"]["utilized_amount_paise"] == 0


def test_a_computation_that_set_off_nothing_says_nothing_and_one_that_names_no_record_says_so():
    loss("L1", original=10 * L)
    none_set_off = svc.write_back_filing(USER, filing(snapshot_id=snapshot("S1", lines=[])["id"]))
    assert none_set_off["state"] == svc.NO_LOSSES
    zero = svc.write_back_filing(USER, filing("F3", snapshot_id=snapshot("S3", lines=[{"section": "§72", "set_off_paise": 0}])["id"]))
    assert zero["state"] == svc.NO_LOSSES, "a typed-in loss that relieved nothing needs no note"
    typed_in = svc.write_back_filing(USER, filing("F2", snapshot_id=snapshot("S2", lines=[{"section": "§72", "set_off_paise": L}])["id"]))
    assert typed_in["state"] == svc.NOT_WRITTEN and "Record the use of the loss by hand" in typed_in["message"]
    assert _MOCK_LOSSES["L1"]["utilized_amount_paise"] == 0


def test_another_clients_loss_in_the_snapshot_is_left_alone_and_the_rest_are_written():
    loss("L1", original=10 * L)
    loss("L-OTHER", client=OTHER, original=10 * L)
    f = filing(snapshot_id=snapshot(lines=[line("L1", 2 * L), line("L-OTHER", 5 * L), line("L-MISSING", L)])["id"])
    out = svc.write_back_filing(USER, f)
    by_id = {r["loss_id"]: r for r in out["losses"]}
    assert by_id["L1"]["state"] == svc.WRITTEN
    assert by_id["L-OTHER"]["state"] == svc.NOT_WRITTEN and by_id["L-MISSING"]["state"] == svc.NOT_WRITTEN
    assert _MOCK_LOSSES["L-OTHER"]["utilized_amount_paise"] == 0, "a forged id cannot spend another client's loss"
    assert out["state"] == svc.WRITTEN


def test_a_use_the_snapshot_claims_beyond_the_loss_is_capped_at_the_loss():
    loss("L1", original=10 * L, utilized=8 * L)
    svc.write_back_filing(USER, filing(snapshot_id=snapshot(lines=[line("L1", 9 * L)])["id"]))
    row = _MOCK_LOSSES["L1"]
    assert row["utilized_amount_paise"] == 10 * L and row["remaining_amount_paise"] == 0
    assert row["utilisations"]["F-ORIG"]["amount_paise"] == 2 * L


def test_a_use_recorded_by_hand_is_kept_beside_the_return_s():
    loss("L1", original=10 * L, utilized=3 * L)
    svc.write_back_filing(USER, filing(snapshot_id=snapshot(lines=[line("L1", 2 * L)])["id"]))
    assert _MOCK_LOSSES["L1"]["utilized_amount_paise"] == 5 * L


def test_a_record_that_changed_while_the_write_was_made_is_left_as_it_was(monkeypatch):
    loss("L1", original=10 * L)
    f = filing(snapshot_id=snapshot(lines=[line("L1", L)])["id"])

    def refused_after_a_hand_edit(firm, loss_id, before, columns):
        _MOCK_LOSSES[loss_id]["utilized_amount_paise"], _MOCK_LOSSES[loss_id]["remaining_amount_paise"] = 1 * L, 9 * L
        return False

    monkeypatch.setattr(svc.workspace, "store_bf_loss_use", refused_after_a_hand_edit)
    out = svc.write_back_filing(USER, f)
    assert out["state"] == svc.NOT_WRITTEN and "changed while this was being written" in out["losses"][0]["message"]
    assert "utilisations" in _MOCK_LOSSES["L1"] and _MOCK_LOSSES["L1"]["utilisations"] == {}, "the record was not written"


def test_a_record_the_caller_may_not_write_is_told_apart_from_one_that_changed(monkeypatch):
    """Row security answers a blocked update with no row and no error, so the refusal re-reads the record: unchanged totals mean the
    write was not allowed, not that another write landed first."""
    loss("L1", original=10 * L)
    monkeypatch.setattr(svc.workspace, "store_bf_loss_use", lambda *a, **k: False)
    out = svc.write_back_filing(USER, filing(snapshot_id=snapshot(lines=[line("L1", L)])["id"]))
    msg = out["losses"][0]["message"]
    assert out["state"] == svc.NOT_WRITTEN and "could not be written with your access" in msg and "changed while" not in msg
    assert _MOCK_LOSSES["L1"]["utilized_amount_paise"] == 0


def test_the_store_refuses_a_write_when_the_totals_moved_underneath_it():
    from domain.income_tax.computation_workspace import store_bf_loss_use
    row = loss("L1", original=10 * L)
    before = dict(row)
    row["utilized_amount_paise"], row["remaining_amount_paise"] = 1 * L, 9 * L            # a hand edit landed first
    assert store_bf_loss_use(FIRM, "L1", before, {"utilisations": {}, "utilized_amount_paise": 4 * L, "remaining_amount_paise": 6 * L}) is False
    assert row["utilized_amount_paise"] == 1 * L


def test_a_failure_inside_the_write_back_never_raises_and_says_so(monkeypatch):
    monkeypatch.setattr(svc.workspace, "get_snapshot", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("database down")))
    out = svc.write_back_filing(USER, filing(snapshot_id="S1"))
    assert out["state"] == svc.NOT_WRITTEN and "acknowledgement is recorded" in out["message"] and "by hand" in out["message"]


# ───────────────── through the acknowledge route, end to end ─────────────────

def test_recording_the_acknowledgement_answers_with_what_became_of_each_loss(monkeypatch):
    monkeypatch.setattr(itr, "can_access_client", lambda user, client_id: True)
    monkeypatch.setattr(itr, "_close_the_obligation", lambda user, f, req: {"state": "not_closed"})
    monkeypatch.setattr(itr.timeline_service, "log", lambda **k: None)
    loss("L1", original=10 * L)
    filing("F-ORIG", snapshot_id=snapshot(lines=[line("L1", 4 * L)])["id"])
    res = itr.record_acknowledgement(
        "F-ORIG", itr.AcknowledgementRequest(acknowledgement_number="ACK-123456789", filing_date="2026-07-20"), USER)
    data = res["data"]
    assert data["status"] == "filed"
    assert data["brought_forward_losses"]["state"] == svc.WRITTEN
    assert _MOCK_LOSSES["L1"]["remaining_amount_paise"] == 6 * L
