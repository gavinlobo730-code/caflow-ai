"""A lead's stage and its signed letter are worked out over EVERY letter of the lead, not the letters the caller can see (POST-A-310).

WHAT WAS WRONG
    Two lifecycle routes work out a lead's standing from the lead's engagement letters: `revert_lead_after_engagement_closed`
    recomputes the stage from the most advanced live letter after one is rejected or deleted, and `convert_lead` picks the
    lead's most recently signed letter and refuses to convert without one. Both read the letters with the CALLER's own
    client. Since migration 529 a letter that names a client the caller is not assigned to (or the internal practice, for
    anyone but a Partner) is not in what the caller reads, so the signed letter could be "not found" (a 409, "a signed
    engagement letter is required") or the stage could fall back further than the evidence says. It is the defect of the
    letter number again (`engagement_letters._numbering_db`): a newest-or-most-advanced computation over rows the caller can
    only partly see. A Partner is unaffected, and so is the web form (it sends the lead only), which is why it was filed low.

WHAT THIS HOLDS
    * `_letters_db` hands the privileged client when there is one and the caller's own only where there is no other;
    * the stage revert, run with a caller who sees only one of two letters, does not downgrade a lead whose other letter is
      signed (the control: read as the caller, the same lead is downgraded and the stage is written);
    * the conversion's signed-letter lookup (`_signed_letters_of_lead`) finds a signed letter the caller's own sign-in cannot
      see, and the write that links it to the new client stays the CALLER's (deliberately not widened), so when the database
      hides that letter from the update and answers with no row and no error, `_link_signed_letter` SAYS the letter was not
      linked instead of letting the conversion go on as though it were (the review of this change found the silent zero-row
      outcome: before the privileged read the same lead ended in a 409);
    * every `.table("engagements")` in `routers/lifecycle.py` is either a SELECT on `_letters_db(...)` or the UPDATE of
      `_link_signed_letter`; a chain held in a variable, which the select rule could not see, fails.

Runs in the mock-mode job: no database is needed.
"""
from __future__ import annotations

import ast
import inspect

import routers.lifecycle as lc


class _Query:
    def __init__(self, store, name):
        self._store, self._name, self._eqs, self._payload = store, name, [], None

    def select(self, *_a, **_k):
        return self

    def eq(self, column, value):
        self._eqs.append((column, value))
        return self

    def limit(self, *_a, **_k):
        return self

    def update(self, payload):
        self._payload = payload
        return self

    def execute(self):
        rows = [r for r in self._store.rows.get(self._name, []) if all(r.get(c) == v for c, v in self._eqs)]
        if self._payload is not None:
            self._store.updates.append((self._name, dict(self._payload), list(self._eqs)))
            if self._store.fail_updates:
                raise RuntimeError("update refused")
        return type("R", (), {"data": rows})()


class _Db:
    """A database that holds `rows` per table and records the updates it was asked to make."""

    def __init__(self, rows, fail_updates=False):
        self.rows, self.updates, self.fail_updates = rows, [], fail_updates

    def table(self, name):
        return _Query(self, name)


LEAD = {"id": "L1", "firm_id": "F1", "stage": "Engagement Signed", "is_converted": False}
SIGNED_ON_AN_UNASSIGNED_CLIENT = {"id": "E1", "lead_id": "L1", "firm_id": "F1", "status": "Signed", "is_deleted": False}
SENT = {"id": "E2", "lead_id": "L1", "firm_id": "F1", "status": "Sent", "is_deleted": False}


def _world(monkeypatch, *, privileged: bool):
    """The caller sees the lead and the SENT letter; the SIGNED letter is of a client they are not assigned to."""
    as_the_caller = _Db({"leads": [dict(LEAD)], "engagements": [dict(SENT)]})
    as_the_server = _Db({"leads": [dict(LEAD)], "engagements": [dict(SIGNED_ON_AN_UNASSIGNED_CLIENT), dict(SENT)]})
    monkeypatch.setattr(lc, "_db", lambda: as_the_caller)
    monkeypatch.setattr(lc.db_provider, "service_db_or_none", lambda: as_the_server if privileged else None)
    monkeypatch.setattr(lc, "_audit_lead_stage_revert", lambda *a, **k: None)
    return as_the_caller, as_the_server


def test_the_letters_are_read_with_the_privileged_client_when_there_is_one(monkeypatch):
    mine, theirs = _Db({}), _Db({})
    monkeypatch.setattr(lc.db_provider, "service_db_or_none", lambda: theirs)
    assert lc._letters_db(mine) is theirs


def test_the_callers_own_client_is_the_fallback_and_mock_mode_has_none(monkeypatch):
    mine = _Db({})
    monkeypatch.setattr(lc.db_provider, "service_db_or_none", lambda: None)
    assert lc._letters_db(mine) is mine
    monkeypatch.setattr(lc.db_provider, "service_db_or_none", lambda: _Db({}))
    assert lc._letters_db(None) is None, "mock mode must stay on the in-memory letters, not reach for a database"


def test_a_lead_with_a_signed_letter_the_caller_cannot_see_is_not_downgraded(monkeypatch):
    caller, server = _world(monkeypatch, privileged=True)
    changed = lc.revert_lead_after_engagement_closed("L1", "F1")
    assert changed is False, "the stage was recomputed over the letters the caller can see"
    assert caller.updates == [] and server.updates == [], "a stage was written"


def test_read_as_the_caller_the_same_lead_is_downgraded_which_is_the_defect(monkeypatch):
    """The control: with no privileged client the caller's own view is all there is, and it reads one letter, Sent."""
    caller, _server = _world(monkeypatch, privileged=False)
    changed = lc.revert_lead_after_engagement_closed("L1", "F1")
    assert changed is True
    assert caller.updates and caller.updates[0][1]["stage"] == "Engagement Sent"


def test_the_signed_letter_of_a_lead_is_found_though_it_names_a_client_the_caller_cannot_see(monkeypatch):
    caller, server = _world(monkeypatch, privileged=True)
    # the caller's own view holds a SENT letter and no signed one; the server holds the signed letter too
    letters = lc._signed_letters_of_lead(lc._db(), "L1", "F1")
    assert [l["id"] for l in letters] == ["E1"], "the signed letter the caller cannot see was not found"
    assert lc._pick_signed_engagement(letters)["id"] == "E1"


def test_read_as_the_caller_the_same_lead_has_no_signed_letter_which_is_the_409(monkeypatch):
    _world(monkeypatch, privileged=False)
    assert lc._signed_letters_of_lead(lc._db(), "L1", "F1") == [], "the control: the caller's own view holds no signed letter"


def test_a_signed_letter_of_another_lead_or_firm_is_not_found(monkeypatch):
    _world(monkeypatch, privileged=True)
    assert lc._signed_letters_of_lead(lc._db(), "L2", "F1") == []
    assert lc._signed_letters_of_lead(lc._db(), "L1", "F2") == []


def test_linking_a_letter_the_caller_can_see_says_nothing(monkeypatch):
    caller = _Db({"engagements": [dict(SIGNED_ON_AN_UNASSIGNED_CLIENT)]})
    assert lc._link_signed_letter(caller, "E1", "C-NEW", "F1", "2026-10-21T00:00:00+00:00") is None
    assert caller.updates and caller.updates[0][1]["client_id"] == "C-NEW"


def test_linking_a_letter_the_database_hides_from_the_caller_says_it_was_not_linked(monkeypatch):
    """The database answers an update of a row it hides with no row and no error; the caller must still be told."""
    caller = _Db({"engagements": []})      # the letter exists, but not in the caller's view
    said = lc._link_signed_letter(caller, "E1", "C-NEW", "F1", "2026-10-21T00:00:00+00:00")
    assert said and "not linked" in said and "not assigned" in said, said


def test_a_link_the_database_refuses_with_an_error_still_says_so(monkeypatch):
    caller = _Db({"engagements": [dict(SIGNED_ON_AN_UNASSIGNED_CLIENT)]}, fail_updates=True)
    said = lc._link_signed_letter(caller, "E1", "C-NEW", "F1", "2026-10-21T00:00:00+00:00")
    assert said and said.startswith("Client created, but linking the signed engagement to it failed")


def test_the_link_is_written_as_the_caller_and_never_as_the_server(monkeypatch):
    """Widening the read is the fix; widening the write would let a Manager move another client's letter."""
    caller, server = _world(monkeypatch, privileged=True)
    caller.rows["engagements"] = [dict(SIGNED_ON_AN_UNASSIGNED_CLIENT)]
    lc._link_signed_letter(lc._db(), "E1", "C-NEW", "F1", "2026-10-21T00:00:00+00:00")
    assert caller.updates and server.updates == [], "the link was written with the privileged client"


def _engagement_chains():
    """Every `X.table("engagements")` call of the module, with the chain method that follows it (or None) and whether the
    call is held in a variable instead of being chained straight on."""
    tree = ast.parse(inspect.getsource(lc))
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "table"
                and node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == "engagements"):
            continue
        up = parents.get(node)
        follows = up.attr if isinstance(up, ast.Attribute) else None
        found.append((node.func.value, follows, not isinstance(up, ast.Attribute)))
    return found


def test_every_select_of_the_engagement_letters_goes_through_the_letters_client():
    chains = _engagement_chains()
    selects = [c for c in chains if c[1] == "select"]
    assert len(selects) >= 2, "the scan found fewer reads of the letters than the two the lifecycle makes"
    for receiver, _follows, _held in selects:
        assert isinstance(receiver, ast.Call) and getattr(receiver.func, "id", "") == "_letters_db", (
            "a select of `engagements` in the lifecycle router reads with the caller's client: " + ast.dump(receiver)[:160])


def test_no_chain_on_the_engagement_letters_is_held_in_a_variable_and_the_only_other_use_is_the_link():
    """A chain held in a variable (`eng = db.table("engagements")` then `eng.select(...)`) is invisible to the select rule, so
    none may exist; and the only chain that is not a select is the caller's UPDATE inside `_link_signed_letter`."""
    chains = _engagement_chains()
    held = [c for c in chains if c[2]]
    assert not held, "a `.table(\"engagements\")` call is not chained straight on: the select rule cannot see where it goes"
    others = [c for c in chains if c[1] != "select"]
    assert [c[1] for c in others] == ["update"], [c[1] for c in others]
    owner = inspect.getsource(lc._link_signed_letter)
    assert 'table("engagements")' in owner and ".update(" in owner, "the one update left the link function"
