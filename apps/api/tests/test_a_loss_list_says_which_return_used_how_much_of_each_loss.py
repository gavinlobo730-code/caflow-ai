"""POST-A-368 (item 1) — the list of a client's brought-forward losses says which return used how much of each, from the server.

WHAT WAS WRONG
    The write-back of a filed return's use (POST-A-073) stores the use per filing and per financial year, and the Tax Computation screen's loss list
    showed only "remaining of original". A CA looking at a loss that was partly used could not see which return holds which part, which return the
    record has no use for, or how much was recorded by hand: the figure was right and unexplained, so the only way to check it was the database.

WHAT THIS PINS
    THE RULE   (`loss_utilisation.uses_view`, which reads nothing) the part recorded by hand is the stored total less the entries and is not a
               filing's; each entry is one item with its year, the kind of return, the rupees and the return's acknowledgement number, oldest
               year first; an entry of no rupees is not a use; a record that predates the column has none; an entry whose return cannot be
               found says so, and when the filings could not be READ it says nothing about whether the return is on file (a failed read is not a
               return that is gone).
    THE ROUTE  `GET /api/itr/bf-losses` serves each record with `uses` and `hand_recorded_paise`, for the client asked for only, behind the
               client-scope check, and the filings are read for that client only. A failure to read the filings never fails the list.
"""
import pytest
from fastapi import HTTPException

import routers.itr_workspace as itr
from domain.income_tax.computation_workspace import _MOCK_LOSSES
from domain.income_tax.itr_workflow import _MOCK_FILINGS
from domain.income_tax.loss_utilisation import uses_view

L = 1_00_000_00
FIRM = "F1"
MINE, OTHER = "client-mine", "client-other"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "a1", "email": "ca@example.in", "role": "Partner"}


def row(entries=None, *, original=10 * L, utilized=None):
    entries = entries or {}
    used = sum(e["amount_paise"] for e in entries.values()) if utilized is None else utilized
    return {"original_amount_paise": original, "utilized_amount_paise": used, "remaining_amount_paise": original - used,
            "utilisations": entries}


def entry(fy, rupees, kind="original"):
    return {"financial_year": fy, "amount_paise": rupees, "return_type": kind}


# ── the rule ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_each_entry_is_one_item_oldest_year_first_with_the_returns_acknowledgement_number():
    r = row({"f-26": entry("2026-27", 2 * L, "revised"), "f-25": entry("2025-26", 4 * L)})
    filings = {"f-25": {"id": "f-25", "acknowledgement_number": "ACK-25"}, "f-26": {"id": "f-26", "acknowledgement_number": "ACK-26"}}
    view = uses_view(r, filings)
    assert [(u["financial_year"], u["return_type"], u["amount_paise"], u["acknowledgement_number"], u["filing_found"])
            for u in view["uses"]] == [("2025-26", "original", 4 * L, "ACK-25", True), ("2026-27", "revised", 2 * L, "ACK-26", True)]
    assert [u["filing_id"] for u in view["uses"]] == ["f-25", "f-26"]
    assert view["hand_recorded_paise"] == 0


def test_the_part_recorded_by_hand_is_the_stored_total_less_the_entries():
    r = row({"f-25": entry("2025-26", 4 * L)}, utilized=7 * L)
    assert uses_view(r, {"f-25": {}})["hand_recorded_paise"] == 3 * L
    assert uses_view(row(utilized=2 * L), {})["hand_recorded_paise"] == 2 * L and uses_view(row(utilized=2 * L), {})["uses"] == []


def test_a_record_that_predates_the_column_or_holds_nothing_has_no_uses_and_no_hand_recorded_part():
    assert uses_view({"original_amount_paise": 5 * L, "remaining_amount_paise": 5 * L}, {}) == {"hand_recorded_paise": 0, "uses": []}
    assert uses_view(row(), {}) == {"hand_recorded_paise": 0, "uses": []}
    assert uses_view({"utilisations": "oops"}, {}) == {"hand_recorded_paise": 0, "uses": []}


def test_an_entry_of_no_rupees_is_not_a_use():
    r = row({"f-25": entry("2025-26", 0), "f-26": entry("2026-27", 1 * L)})
    assert [u["filing_id"] for u in uses_view(r, {})["uses"]] == ["f-26"]


def test_a_return_that_is_not_among_the_filings_is_said_to_be_gone_and_an_unreadable_list_says_nothing_either_way():
    r = row({"f-25": entry("2025-26", 4 * L)})
    gone = uses_view(r, {"someone-else": {"acknowledgement_number": "X"}})["uses"][0]
    assert gone["filing_found"] is False and gone["acknowledgement_number"] is None
    unread = uses_view(r, None)["uses"][0]
    assert unread["filing_found"] is None and unread["acknowledgement_number"] is None and unread["amount_paise"] == 4 * L


def test_a_return_with_no_acknowledgement_yet_has_no_number_and_is_still_found():
    item = uses_view(row({"f-25": entry("2025-26", L)}), {"f-25": {"id": "f-25", "acknowledgement_number": None}})["uses"][0]
    assert item["filing_found"] is True and item["acknowledgement_number"] is None


# ── the route ────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    for store in (_MOCK_LOSSES, _MOCK_FILINGS):
        store.clear()
    monkeypatch.setattr(itr, "assert_client_access", lambda user, client_id: None)
    yield
    for store in (_MOCK_LOSSES, _MOCK_FILINGS):
        store.clear()


def stored(loss_id, client=MINE, entries=None, **kw):
    _MOCK_LOSSES[loss_id] = {"id": loss_id, "firm_id": FIRM, "client_id": client, "loss_type": "business", "assessment_year": "2024-25",
                             "expiry_assessment_year": "2032-33", **row(entries, **kw)}


def filed(filing_id, client=MINE, ack="ACK-1", fy="2025-26"):
    _MOCK_FILINGS[filing_id] = {"id": filing_id, "firm_id": FIRM, "client_id": client, "financial_year": fy, "return_type": "original",
                                "status": "filed", "acknowledgement_number": ack}


def listing(client=MINE):
    out = itr.list_bf_losses(client, USER)
    assert out["success"] is True
    return {r["id"]: r for r in out["data"]}


def test_each_record_is_served_with_where_it_went():
    stored("L1", entries={"F1": entry("2025-26", 4 * L)}, utilized=5 * L)
    filed("F1", ack="ACK-A")
    got = listing()["L1"]
    assert got["hand_recorded_paise"] == L
    assert [(u["financial_year"], u["amount_paise"], u["acknowledgement_number"], u["filing_found"]) for u in got["uses"]] == [
        ("2025-26", 4 * L, "ACK-A", True)]
    assert got["original_amount_paise"] == 10 * L and got["remaining_amount_paise"] == 5 * L        # the record's own columns are still served


def test_a_loss_nobody_used_is_served_with_an_empty_list_and_nothing_by_hand():
    stored("L1")
    got = listing()["L1"]
    assert got["uses"] == [] and got["hand_recorded_paise"] == 0


def test_only_the_asked_for_clients_losses_and_filings_are_read():
    stored("L1", entries={"F1": entry("2025-26", 4 * L)})
    stored("L2", client=OTHER, entries={"F9": entry("2025-26", 3 * L)})
    filed("F1", ack="MINE")
    filed("F9", client=OTHER, ack="THEIRS")
    mine = listing(MINE)
    assert list(mine) == ["L1"] and mine["L1"]["uses"][0]["acknowledgement_number"] == "MINE"
    # a use that names ANOTHER client's filing id does not borrow its acknowledgement number
    stored("L3", entries={"F9": entry("2025-26", 3 * L)})
    leaked = listing(MINE)["L3"]["uses"][0]
    assert leaked["filing_found"] is False and leaked["acknowledgement_number"] is None


def test_the_filings_that_cannot_be_read_never_fail_the_list(monkeypatch):
    stored("L1", entries={"F1": entry("2025-26", 4 * L)})
    seen = []
    import core.observability as obs
    from domain.income_tax import itr_workflow
    monkeypatch.setattr(itr_workflow, "list_itr_filings", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    monkeypatch.setattr(obs, "capture_soft_failure", lambda exc, **k: seen.append(k.get("operation")))
    got = listing()["L1"]
    assert got["uses"][0]["amount_paise"] == 4 * L and got["uses"][0]["filing_found"] is None
    assert seen == ["bf_loss_service.uses_by_loss"]


def test_the_client_scope_check_still_comes_first(monkeypatch):
    stored("L1")

    def refuse(user, client_id):
        raise HTTPException(status_code=404, detail="Client not found")
    monkeypatch.setattr(itr, "assert_client_access", refuse)
    with pytest.raises(HTTPException) as e:
        itr.list_bf_losses(MINE, USER)
    assert e.value.status_code == 404
