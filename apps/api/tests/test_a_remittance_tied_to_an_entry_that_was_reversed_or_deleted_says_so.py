"""POST-A-272 (the ESI / professional-tax side of the stale link) — a remittance can only be tied to an entry that records the payment, and one
tied to an entry that later stopped doing so says so, in the server's words, and the link can be taken back.

WHAT WAS WRONG
    The TDS challan's link door refuses a draft, a reversed original, the reversal that undid it and a deleted entry, and a tied challan says when
    its entry no longer records the payment. The ESI / professional-tax remittance's door (`PATCH /remittances/{id}/payment`) only asked that the
    entry be a non-deleted entry of the client, so it accepted all of those, and a remittance tied to an entry that was later reversed went on
    reading as matched: it was not in the reconciliation's list of unmatched remittances (it had a link) and nothing said that the ledger no longer
    showed its payment. There was also no way to take a link back.

WHAT THIS PINS
    THE DOOR   a draft, a reversed original, a reversal and a deleted entry are refused in words that say why, an entry of another client is "not an
               entry of this client", and a live entry is tied; nothing is written by a refusal;
    THE STATE  one reader of an entry's state (`entry_states`) serves both registers, with the five states and `missing` (no such entry of this client);
    THE LIST   `remittance-reconciliation` lists, apart from `unmatched`, each remittance tied to an entry that is not live, with the server's label and note
               and never a live link; a ledger that cannot be read marks every tied remittance UNKNOWN (a failed read is not a live link), and
               nothing is cleared by reading;
    UNLINK     `DELETE /remittances/{id}/payment` takes the link back, once (a second call finds none), for this client's remittance only, audited as the
               person; after it the remittance is unmatched again and offered its candidates;
    AUDIT      linking is audited too, as the person (the AUTH id).
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import routers.payroll as pay
from services import statutory_remittance_service as svc
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "id": "u1", "auth_user_id": "auth-1", "email": "ca@f.test", "role": "Partner"}
ESI_ACC, BANK_ACC = "ACC-ESI", "ACC-BANK"


@pytest.fixture
def world(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [pay])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    monkeypatch.setattr(pay, "assert_client_access", lambda user, client_id: None)
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "client_name": "Acme"})
    for aid, name in ((ESI_ACC, "ESI Payable"), (BANK_ACC, "Bank - Current")):
        db.seed("chart_of_accounts", {"id": aid, "firm_id": FIRM, "client_id": "CLI", "account_name": name, "account_type": "Liability",
                                      "is_active": True})
    return db


def entry(db, eid, *, client="CLI", posted=True, reversed_=False, reversal_of=None, deleted=None, on="2026-10-15"):
    db.seed("journal_entries", {"id": eid, "firm_id": FIRM, "client_id": client, "entry_date": on, "reference_no": f"PAY/{eid}",
                                "narration": "ESI paid", "is_posted": posted, "is_reversed": reversed_, "reversal_of": reversal_of,
                                "deleted_at": deleted})
    db.seed("journal_lines", {"journal_entry_id": eid, "account_id": ESI_ACC, "debit_paise": 10_500_00, "credit_paise": 0})
    db.seed("journal_lines", {"journal_entry_id": eid, "account_id": BANK_ACC, "debit_paise": 0, "credit_paise": 10_500_00})


def remit(db, **over):
    args = dict(firm_id=FIRM, client_id="CLI", scheme=svc.ESIC, wage_month="2026-09", submitted_on="2026-10-14", status=svc.PAID,
                paid_on="2026-10-15", amount_paise=10_500_00)
    args.update(over)
    return svc.record(db, **args)


def link(db, remittance_id, entry_id):
    return svc.link_payment(db, firm_id=FIRM, client_id="CLI", remittance_id=remittance_id, journal_entry_id=entry_id)


def stored_link(db, remittance_id):
    return next(r for r in db.rows("statutory_remittances") if r["id"] == remittance_id).get("journal_entry_id")


# ── the door ─────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind,words", [
    ("draft", "still a draft"),
    ("reversed", "was reversed"),
    ("reversal", "undid another entry"),
    ("deleted", "was deleted"),
])
def test_an_entry_that_does_not_record_a_payment_is_refused_in_words_and_nothing_is_written(world, kind, words):
    r = remit(world)
    kwargs = {"draft": dict(posted=False), "reversed": dict(reversed_=True), "reversal": dict(reversal_of="JE-ORIG"),
              "deleted": dict(deleted="2026-10-20T00:00:00+00:00")}[kind]
    entry(world, "JE1", **kwargs)
    with pytest.raises(svc.RemittanceError) as e:
        link(world, r["id"], "JE1")
    assert words in str(e.value) and "payment of this remittance" in str(e.value)
    assert stored_link(world, r["id"]) is None


def test_an_entry_of_another_client_is_not_an_entry_of_this_client(world):
    r = remit(world)
    entry(world, "JE-B", client="OTHER")
    with pytest.raises(svc.RemittanceError, match="not an entry of this client"):
        link(world, r["id"], "JE-B")
    with pytest.raises(svc.RemittanceError, match="not an entry of this client"):
        link(world, r["id"], "JE-NOWHERE")
    assert stored_link(world, r["id"]) is None


def test_a_live_entry_is_tied(world):
    r = remit(world)
    entry(world, "JE1")
    assert link(world, r["id"], "JE1") is True
    assert stored_link(world, r["id"]) == "JE1"


def test_the_route_answers_a_refusal_as_a_422_with_the_sentence(world):
    r = remit(world)
    entry(world, "JE1", reversed_=True)
    with pytest.raises(HTTPException) as e:
        pay.link_remittance_payment("CLI", r["id"], pay.RemittancePaymentIn(journal_entry_id="JE1"), CALLER)
    assert e.value.status_code == 422 and "was reversed" in e.value.detail


# ── the state ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_one_reader_serves_both_registers_with_the_five_states_and_missing(world):
    entry(world, "L")
    entry(world, "D", posted=False)
    entry(world, "R", reversed_=True)
    entry(world, "V", reversal_of="R")
    entry(world, "X", deleted="2026-10-20T00:00:00+00:00")
    entry(world, "B", client="OTHER")
    got = svc.entry_states(world, firm_id=FIRM, client_id="CLI", entry_ids=["L", "D", "R", "V", "X", "B", "GONE"])
    assert got == {"L": "live", "D": "draft", "R": "reversed", "V": "reversal", "X": "deleted", "B": "missing", "GONE": "missing"}
    from services import tds_challan_ledger_service as tds
    assert tds.entry_states(world, firm_id=FIRM, client_id="CLI", entry_ids=["L", "R"]) == {"L": "live", "R": "reversed"}


def test_the_two_registers_have_words_for_the_same_states():
    from services import tds_challan_ledger_service as tds
    assert set(svc.LINK_LABEL) == set(tds._LABEL) and set(svc.LINK_NOTE) == set(tds._NOTE) and set(svc.NOT_A_PAYMENT) == set(tds._NOT_A_PAYMENT)
    assert svc.LINK_LABEL == tds._LABEL                                   # the labels are one vocabulary
    for state, note in svc.LINK_NOTE.items():
        assert "remittance" in note and "challan" not in note.lower(), state


# ── the list ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def _tied(world, entry_kwargs, *, month="2026-09"):
    r = remit(world, wage_month=month)
    entry(world, f"JE-{month}")
    link(world, r["id"], f"JE-{month}")
    return r


def _stale(world):
    res = pay.remittance_reconciliation("CLI", CALLER)
    assert res["success"] is True, res
    return res["data"]


def test_a_remittance_tied_to_a_live_entry_is_not_listed_and_is_not_unmatched(world):
    _tied(world, {})
    data = _stale(world)
    assert data["stale_links"] == [] and data["unmatched"] == []


@pytest.mark.parametrize("change,state,label", [
    (dict(is_reversed=True), "reversed", "Tied to an entry that was reversed"),
    (dict(deleted_at="2026-10-20T00:00:00+00:00"), "deleted", "Tied to an entry that was deleted"),
    (dict(is_posted=False), "draft", "Tied to an entry that is still a draft"),
])
def test_a_remittance_tied_to_an_entry_that_later_stopped_recording_the_payment_is_listed_with_the_servers_words(world, change, state, label):
    r = _tied(world, {})
    next(e for e in world.rows("journal_entries") if e["id"] == "JE-2026-09").update(change)
    data = _stale(world)
    [row] = data["stale_links"]
    assert row["id"] == r["id"] and row["journal_entry_id"] == "JE-2026-09"
    assert row["ledger_link"]["state"] == state and row["ledger_link"]["label"] == label
    assert "link back" in row["ledger_link"]["note"] and "remittance" in row["ledger_link"]["note"]
    assert data["unmatched"] == []                                       # it still has a link: unmatched and stale are different lists


def test_the_server_says_whether_taking_the_link_back_is_worth_offering_and_a_failed_read_is_not(world):
    assert svc.link_view("reversed")["can_take_back"] is True and svc.link_view("missing")["can_take_back"] is True
    assert svc.link_view("unknown")["can_take_back"] is False


def test_a_tie_to_an_entry_that_cannot_be_found_says_so(world):
    remit(world)
    world.rows("statutory_remittances")[0]["journal_entry_id"] = "JE-GONE"
    [row] = _stale(world)["stale_links"]
    assert row["ledger_link"]["state"] == "missing" and "can no longer be found" in row["ledger_link"]["label"]


def test_a_ledger_that_cannot_be_read_marks_every_tied_remittance_unknown_and_never_live(world, monkeypatch):
    _tied(world, {})
    monkeypatch.setattr(svc, "entry_states", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")))
    [row] = _stale(world)["stale_links"]
    assert row["ledger_link"]["state"] == "unknown" and "not checked just now" in row["ledger_link"]["label"]
    assert "not known" in row["ledger_link"]["note"]


def test_reading_the_list_clears_nothing(world):
    r = _tied(world, {})
    next(e for e in world.rows("journal_entries") if e["id"] == "JE-2026-09").update(is_reversed=True)
    _stale(world)
    _stale(world)
    assert stored_link(world, r["id"]) == "JE-2026-09"


def test_another_clients_remittance_is_never_listed(world):
    world.seed("clients", {"id": "OTHER", "firm_id": FIRM, "client_name": "Other"})
    entry(world, "JE-O", client="OTHER")
    r = remit(world, client_id="OTHER")
    link_other = svc.link_payment(world, firm_id=FIRM, client_id="OTHER", remittance_id=r["id"], journal_entry_id="JE-O")
    assert link_other is True
    assert _stale(world)["stale_links"] == []


# ── unlink ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_unlinking_takes_the_link_back_once_and_the_remittance_is_unmatched_again_with_its_candidates(world):
    r = _tied(world, {})
    next(e for e in world.rows("journal_entries") if e["id"] == "JE-2026-09").update(is_reversed=True)
    entry(world, "JE-NEW")
    out = pay.unlink_remittance_payment("CLI", r["id"], CALLER)
    assert out["data"] == {"remittance_id": r["id"], "unlinked": True, "was": "JE-2026-09"}
    assert stored_link(world, r["id"]) is None
    data = _stale(world)
    assert data["stale_links"] == []
    [row] = data["unmatched"]
    assert row["id"] == r["id"] and [c["journal_entry_id"] for c in row["candidates"]] == ["JE-NEW"]
    with pytest.raises(HTTPException) as e:
        pay.unlink_remittance_payment("CLI", r["id"], CALLER)
    assert e.value.status_code == 404


def test_unlinking_another_clients_remittance_or_a_missing_one_finds_nothing(world):
    world.seed("clients", {"id": "OTHER", "firm_id": FIRM, "client_name": "Other"})
    entry(world, "JE-O", client="OTHER")
    r = remit(world, client_id="OTHER")
    svc.link_payment(world, firm_id=FIRM, client_id="OTHER", remittance_id=r["id"], journal_entry_id="JE-O")
    with pytest.raises(HTTPException) as e:
        pay.unlink_remittance_payment("CLI", r["id"], CALLER)
    assert e.value.status_code == 404 and stored_link(world, r["id"]) == "JE-O"
    with pytest.raises(HTTPException):
        pay.unlink_remittance_payment("CLI", "no-such-remittance", CALLER)


def test_a_link_changed_under_the_call_is_not_taken_back(world, monkeypatch):
    """The update is guarded by the id that was read, so a link somebody re-tied in between is left alone."""
    r = _tied(world, {})
    entry(world, "JE-OTHER")
    calls = {"n": 0}
    real = svc.privileged_for

    def racing(db):
        calls["n"] += 1
        if calls["n"] == 2:                      # between the read of the link and the update that takes it back
            for row in db.rows("statutory_remittances"):
                row["journal_entry_id"] = "JE-OTHER"
        return real(db)

    monkeypatch.setattr(svc, "privileged_for", racing)
    assert svc.unlink_payment(world, firm_id=FIRM, client_id="CLI", remittance_id=r["id"]) is None
    assert calls["n"] == 2 and stored_link(world, r["id"]) == "JE-OTHER"


# ── audit ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_linking_and_unlinking_are_audited_as_the_person_with_the_auth_id(world):
    r = remit(world)
    entry(world, "JE1")
    pay.link_remittance_payment("CLI", r["id"], pay.RemittancePaymentIn(journal_entry_id="JE1"), CALLER)
    pay.unlink_remittance_payment("CLI", r["id"], CALLER)
    rows = [a for a in world.rows("audit_log") if a.get("entity_type") == "statutory_remittance"]
    assert [(a["metadata"]["change"], a["actor_id"], a["old_data"]["journal_entry_id"], a["new_data"]["journal_entry_id"]) for a in rows] == [
        ("payment_linked", "auth-1", None, "JE1"), ("payment_unlinked", "auth-1", "JE1", None)]
    assert all(a["entity_id"] == r["id"] and a["metadata"]["client_id"] == "CLI" for a in rows)


def test_the_unlink_route_is_a_delete_at_the_payroll_write_tier_and_checks_the_client():
    import inspect
    routes = [r for r in pay.router.routes if getattr(r, "path", "").endswith("/remittances/{remittance_id}/payment")]
    assert sorted(m for r in routes for m in r.methods) == ["DELETE", "PATCH"]
    src = inspect.getsource(pay.unlink_remittance_payment)
    assert 'rbac("payroll", "write")' in src and "assert_client_access(current_user, client_id)" in src
