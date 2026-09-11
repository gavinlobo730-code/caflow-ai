"""The copilot's four firm-wide endpoints answer for the CALLER's clients.

THE LEAK

ACC-17 drew this line for the seven reporting endpoints: a request with no
client_id means "all clients", and that is right only for a Partner.
core.authz._FIRMWIDE_ROLES is {Role.PARTNER}.

The copilot router was left behind, and one endpoint short of consistent —
/intelligence/client/{id} calls assert_client_access, while these four passed
only a firm_id and answered across every client of the firm:

    /intelligence/compliance      rbac("compliance", "read")
    /intelligence/workflows       rbac("task", "read")
    /intelligence/relationships   rbac("client", "read")
    /executive-dashboard          rbac("firm", "read")  -> Manager and above

So an Executive or a Manager saw the whole practice. The relationship endpoint
is the worst of the four: it feeds client PANs and email domains into an AI
prompt to look for related parties, so it leaks the identifying data of clients
the caller is not assigned to.

THE SECOND LEAK, WHICH SCOPING THE QUERIES ALONE WOULD NOT HAVE CLOSED

These summaries are cached on (firm_id, summary_type, entity_id) and every call
passed entity_id=None. A Partner's firm-wide answer would therefore have been
served straight back to the next Executive who asked, from cache, however well
the queries were narrowed. The scope is now part of the key.
"""
from __future__ import annotations

import asyncio

import pytest

from domain.ai_copilot_service import ai_copilot_service as svc

FIRM = "f1"
MINE, THEIRS = "c-mine", "c-theirs"


# ── the scope key ────────────────────────────────────────────────────────────

def test_a_partner_has_no_scope_key_and_everyone_else_does():
    assert svc._scope_key(None) is None, "None means unrestricted — a Partner"
    assert svc._scope_key({MINE}) is not None


def test_two_different_scopes_cannot_share_a_cached_answer():
    assert svc._scope_key({MINE}) != svc._scope_key({THEIRS})
    assert svc._scope_key({MINE}) != svc._scope_key({MINE, THEIRS})
    assert svc._scope_key({MINE}) != svc._scope_key(None)


def test_the_same_scope_is_the_same_key_whatever_the_order():
    """Or the cache would miss on every request and re-bill the AI call."""
    assert svc._scope_key({MINE, THEIRS}) == svc._scope_key({THEIRS, MINE})


def test_an_empty_scope_is_not_the_same_as_no_scope():
    """The distinction the whole shape turns on: an empty set means NO clients,
    never "no filter". Getting it backwards hands over the entire practice."""
    assert svc._scope_key(set()) is not None
    assert svc._scope_key(set()) != svc._scope_key(None)


# ── the row filter ───────────────────────────────────────────────────────────

ROWS = [{"client_id": MINE}, {"client_id": THEIRS}, {"client_id": None}]


def test_a_partner_sees_every_row():
    assert svc._visible(ROWS, None) == ROWS


def test_a_scoped_caller_sees_only_their_own():
    got = svc._visible(ROWS, {MINE})
    assert {r["client_id"] for r in got} == {MINE, None}, (
        "their own rows, plus rows that belong to no client at all")


def test_an_empty_scope_sees_no_client_rows():
    got = svc._visible(ROWS, set())
    assert [r["client_id"] for r in got] == [None]


def test_the_client_list_is_scoped_by_its_own_id():
    """A client row has no client_id column — it IS the client."""
    clients = [{"id": MINE, "pan": "AAAPA1111A"}, {"id": THEIRS, "pan": "BBBPB2222B"}]
    got = svc._visible(clients, {MINE}, "id")
    assert [c["id"] for c in got] == [MINE]


# ── workflow rows, which carry no client_id of their own ─────────────────────

class _Repo:
    """Stands in for the workflow repository's parent resolver."""

    def __init__(self, owners):
        self.owners = owners
        self.calls = 0

    def client_ids_for_instances(self, firm_id, instance_ids):
        self.calls += 1
        return {i: self.owners[i] for i in instance_ids if i in self.owners}


@pytest.fixture()
def wf(monkeypatch):
    repo = _Repo({"i-mine": MINE, "i-theirs": THEIRS, "i-firm": None})
    monkeypatch.setattr("domain.ai_copilot_service._get_workflow_repo", lambda: repo)
    return repo


ROWS_WF = [
    {"instance_id": "i-mine"},
    {"instance_id": "i-theirs"},
    {"instance_id": "i-firm"},
    {"instance_id": "i-unknown"},
]


def test_a_partner_keeps_every_workflow_row(wf):
    assert svc._visible_by_instance(FIRM, ROWS_WF, None) == ROWS_WF
    assert wf.calls == 0, "and does not pay for a resolve it does not need"


def test_a_scoped_caller_keeps_their_own_and_the_firm_level_row(wf):
    got = svc._visible_by_instance(FIRM, ROWS_WF, {MINE})
    assert [r["instance_id"] for r in got] == ["i-mine", "i-firm"]


def test_an_unresolvable_parent_is_dropped_not_kept(wf):
    """An instance that cannot be resolved is not evidence of entitlement.

    Keeping it would make a deleted or cross-firm instance a way through.
    """
    got = svc._visible_by_instance(FIRM, [{"instance_id": "i-unknown"}], {MINE})
    assert got == []


def test_the_parents_are_resolved_in_one_query(wf):
    """Not one per row: these lists run to hundreds, and this service is a
    cross-region round trip from the database."""
    svc._visible_by_instance(FIRM, ROWS_WF, {MINE})
    assert wf.calls == 1
