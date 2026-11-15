"""A client keeps narration templates for its manual journals (POST-A-093, migration 590).

WHAT WAS MISSING
    A manual journal's narration is required, and a practice types the same few dozen sentences every month for every client. Nothing
    kept them.

WHAT THESE HOLD (mock mode, through the real routes and service over the shared in-memory database; the table's own refusals, grants
and policies are in the `_pg` file)
    * a template is saved with its words normalised, the member's internal id as `created_by`, and the firm and client on the row;
    * the same words again (ignoring case and spacing) answer the template that holds them and save nothing; words the rule refuses
      are a 422 in its words and save nothing;
    * the list is the client's live templates only, alphabetically: not another client's, not another firm's, not an archived one;
    * an archive takes a template out of the list and keeps its row; another client's template is a 404, worded as a missing one;
    * every read and write names the firm and the client, every write goes through the privileged client, and the routes ask the
      manual journal's own permissions;
    * a save that loses a race to the same words answers the template that won.
"""
from __future__ import annotations

import ast
import pathlib

import pytest
from fastapi import HTTPException

from routers import narration_templates as routes
from services import narration_template_service as svc
from tests.e2e_harness import FakeDB

API = pathlib.Path(__file__).resolve().parents[1]
FIRM, OTHER_FIRM = "F1", "F2"
CLIENT, SIBLING = "C1", "C2"
CALLER = {"firm_id": FIRM, "id": "member-internal-id", "auth_user_id": "member-sign-in-id", "email": "ca@f.test", "role": "Partner"}


@pytest.fixture()
def db(monkeypatch):
    fake = FakeDB()
    import core.supabase_client as sc
    monkeypatch.setenv("SUPABASE_URL", "http://supabase.test")
    monkeypatch.setattr(sc, "get_supabase", lambda: fake)
    monkeypatch.setattr(sc, "get_service_supabase", lambda: fake)
    import services.audit_service as audit
    fake.audited = []
    monkeypatch.setattr(audit, "log_event", lambda *a, **k: fake.audited.append((a, k)))
    return fake


def _save(narration, client=CLIENT, user=CALLER):
    return routes.save_narration_template(routes.TemplateIn(client_id=client, narration=narration), current_user=user)["data"]


def _list(client=CLIENT, user=CALLER):
    return routes.list_narration_templates(client_id=client, current_user=user)["data"]


def test_a_template_is_saved_normalised_with_the_members_internal_id_and_its_firm_and_client(db):
    answer = _save("  Being salary   payable\nfor the month ")
    assert answer["created"] is True and answer["template"]["narration"] == "Being salary payable for the month"
    [row] = db.rows("journal_narration_templates")
    assert row["narration"] == "Being salary payable for the month"
    assert (row["firm_id"], row["client_id"], row["created_by"]) == (FIRM, CLIENT, "member-internal-id")
    assert row["narration_key"] == "being salary payable for the month"     # the key the database's unique index holds
    [(args, kwargs)] = db.audited
    assert args[1:4] == ("journal_narration_template", row["id"], "create") and kwargs["actor_id"] == "member-sign-in-id"


def test_the_same_words_again_answer_the_template_that_holds_them_and_save_nothing(db):
    first = _save("Being rent for the month")
    again = _save("  being RENT for the month ")
    assert again == {"template": first["template"], "created": False}
    assert len(db.rows("journal_narration_templates")) == 1 and len(db.audited) == 1


@pytest.mark.parametrize("words,says", [("   ", "needs some words"), ("x" * 301, "at most 300 characters")])
def test_words_the_rule_refuses_are_a_422_in_its_words_and_save_nothing(db, words, says):
    with pytest.raises(HTTPException) as exc:
        _save(words)
    assert exc.value.status_code == 422 and says in exc.value.detail
    assert db.rows("journal_narration_templates") == []


def test_the_list_is_the_clients_live_templates_alphabetically_and_nothing_else(db):
    for words in ("Being salary payable", "being depreciation for the month", "Being audit fee provided"):
        _save(words)
    db.seed("journal_narration_templates", {"firm_id": FIRM, "client_id": SIBLING, "narration": "A sibling's"})
    db.seed("journal_narration_templates", {"firm_id": OTHER_FIRM, "client_id": CLIENT, "narration": "Another firm's"})
    db.seed("journal_narration_templates", {"firm_id": FIRM, "client_id": CLIENT, "narration": "Archived",
                                            "archived_at": "2026-11-01T10:00:00+05:30"})
    assert [t["narration"] for t in _list()] == [
        "Being audit fee provided", "being depreciation for the month", "Being salary payable"]
    assert set(_list()[0]) == {"id", "narration", "created_at"}


def test_an_archive_takes_a_template_out_of_the_list_and_keeps_its_row(db):
    kept, gone = _save("Being rent"), _save("Being bonus")
    routes.archive_narration_template(template_id=gone["template"]["id"], client_id=CLIENT, current_user=CALLER)
    assert [t["id"] for t in _list()] == [kept["template"]["id"]]
    row = next(r for r in db.rows("journal_narration_templates") if r["id"] == gone["template"]["id"])
    assert row["archived_at"] and row["narration"] == "Being bonus"
    again = _save("Being bonus")                       # archived words may be saved afresh
    assert again["created"] is True and again["template"]["id"] != gone["template"]["id"]


def test_another_clients_or_a_missing_or_an_archived_template_is_a_404_worded_the_same(db):
    sibling = db.seed("journal_narration_templates", {"firm_id": FIRM, "client_id": SIBLING, "narration": "Theirs"})
    archived = db.seed("journal_narration_templates", {"firm_id": FIRM, "client_id": CLIENT, "narration": "Old",
                                                       "archived_at": "2026-11-01T10:00:00+05:30"})
    for template_id in (sibling["id"], archived["id"], "no-such-id"):
        with pytest.raises(HTTPException) as exc:
            routes.archive_narration_template(template_id=template_id, client_id=CLIENT, current_user=CALLER)
        assert exc.value.status_code == 404 and exc.value.detail == "That narration template was not found."
    assert not next(r for r in db.rows("journal_narration_templates") if r["id"] == sibling["id"]).get("archived_at")


def test_a_save_that_loses_a_race_to_the_same_words_answers_the_template_that_won(db, monkeypatch):
    class _Duplicate(Exception):
        code = "23505"

    winner = {}
    real_insert_table = db.table

    class _RacingDB:
        def table(self, name):
            q = real_insert_table(name)
            real_insert = q.insert

            def insert(payload, **k):
                winner.update(db.seed("journal_narration_templates", dict(payload)))     # the other request commits first
                raise _Duplicate("duplicate key value violates unique constraint uq_journal_narration_templates_live_words")
            q.insert = insert
            q._real_insert = real_insert
            return q

    monkeypatch.setattr(svc, "privileged_for", lambda _db: _RacingDB())
    answer = svc.save(db, FIRM, CLIENT, "Being rent", actor_id="m")
    assert answer == {"template": {"id": winner["id"], "narration": "Being rent", "created_at": winner.get("created_at")},
                      "created": False}


def test_a_duplicate_the_database_refuses_and_the_service_cannot_read_back_is_a_409_in_words(db, monkeypatch):
    class _Duplicate(Exception):
        code = "23505"

    class _RefusingDB:
        def table(self, name):
            q = db.table(name)

            def insert(payload, **k):
                raise _Duplicate("duplicate key value violates unique constraint uq_journal_narration_templates_live_words")
            q.insert = insert
            return q

    monkeypatch.setattr(svc, "privileged_for", lambda _db: _RefusingDB())
    with pytest.raises(HTTPException) as exc:
        svc.save(db, FIRM, CLIENT, "Being rent", actor_id="m")
    assert exc.value.status_code == 409 and exc.value.detail == svc.ALREADY_SAVED


def test_a_template_another_request_archived_first_is_a_404_and_audits_nothing(db, monkeypatch):
    saved = _save("Being rent")["template"]
    real_table = db.table

    class _LateDB:
        """Answers the archive's own read with the live row, as a request that read it a moment before the other archived it would."""
        def table(self, name):
            q = real_table(name)
            row = next(r for r in db.rows("journal_narration_templates") if r["id"] == saved["id"])
            row["archived_at"] = "2026-11-15T02:00:00+05:30"
            return q

    monkeypatch.setattr(svc, "privileged_for", lambda _db: _LateDB())
    db.audited.clear()
    with pytest.raises(HTTPException) as exc:
        routes.archive_narration_template(template_id=saved["id"], client_id=CLIENT, current_user=CALLER)
    assert exc.value.status_code == 404 and db.audited == []


def _functions(rel: str) -> dict:
    tree = ast.parse((API / rel).read_text())
    return {n.name: ast.unparse(n) for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def test_every_read_and_write_names_the_firm_and_the_client_and_writes_go_through_the_privileged_client():
    src = (API / "services/narration_template_service.py").read_text()
    tree = ast.parse(src)
    chains = [ast.unparse(n) for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "execute"]
    assert chains, "no query found"
    for chain in chains:
        assert "journal_narration_templates" in chain, chain
        assert ("eq('firm_id'" in chain and "eq('client_id'" in chain) or ("'firm_id': firm_id" in chain and "'client_id': client_id" in chain), chain
        if ".insert(" in chain or ".update(" in chain or ".delete(" in chain:
            assert chain.startswith("privileged_for(db)"), chain
    listed = _functions("services/narration_template_service.py")["list_templates"]
    assert "eq('firm_id', firm_id).eq('client_id', client_id)" in listed


def test_the_routes_ask_the_manual_journals_own_permissions():
    fns = _functions("routers/narration_templates.py")
    assert "rbac('accounting', 'read')" in fns["list_narration_templates"]
    assert "rbac('accounting', 'write')" in fns["save_narration_template"]
    assert "rbac('accounting', 'write')" in fns["archive_narration_template"]
    for name in ("list_narration_templates", "save_narration_template", "archive_narration_template"):
        assert "assert_client_access(current_user" in fns[name], name


def test_without_a_database_the_routes_say_so(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    with pytest.raises(HTTPException) as exc:
        _list()
    assert exc.value.status_code == 503 and "database" in exc.value.detail
