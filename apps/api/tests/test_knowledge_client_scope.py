"""
Client-assignment scope in the knowledge base.

`knowledge` is the first router in the sweep that was already *mostly* right: it
has its own client-scope model in `services/knowledge_service.py`, richer than
`core.authz`'s — internal-client (G1) separate from assignment, read separate
from write. The guards live in the SERVICE, not the router, which is why the
router-source sweep in test_router_client_scope.py has to follow the call through.

Two things were wrong underneath it.

1. **`?scope=client` returned every client's articles.** `search_articles`
   checked the caller only on the `client_id` branch:

       if client_id:   assert, filter to that client
       elif scope:     filter to that scope        ← no check at all
       else:           firm + department only

   `GET /api/knowledge/articles?scope=client` took the middle branch, so any
   firm member with `knowledge.read` got the client-scoped articles of every
   client in the firm. The function's own docstring claimed the opposite, so the
   intent was never in doubt — the branch simply escaped it.

2. **The mutating article paths checked the READ predicate.** edit / restore /
   archive called `_load_article_or_404(..., write=False)`.
   `can_view_client_content` admits Reviewer and Viewer;
   `can_write_instruction` deliberately does not. Not reachable today (RBAC
   gates `knowledge.write` to Partner and Manager, who pass both), so this is
   the two layers agreeing rather than a live hole — but it is one RBAC grant
   away from mattering, and the tests below pin it either way.
"""
import pytest
from fastapi import HTTPException

import services.knowledge_service as kb

FIRM, MINE, THEIRS = "firm-1", "client-mine", "client-theirs"


def _user(role, uid="u1"):
    return {"id": uid, "firm_id": FIRM, "role": role}


ARTICLES = [
    {"id": "A-FIRM", "firm_id": FIRM, "scope": "firm", "client_id": None,
     "title": "Leave policy", "current_version": 1, "is_archived": False},
    {"id": "A-MINE", "firm_id": FIRM, "scope": "client", "client_id": MINE,
     "title": "Acme quirks", "current_version": 1, "is_archived": False},
    {"id": "A-THEIRS", "firm_id": FIRM, "scope": "client", "client_id": THEIRS,
     "title": "Beta quirks", "current_version": 1, "is_archived": False},
]


class _Q:
    def __init__(self, rows): self.rows = rows
    def select(self, *_a): return self
    def eq(self, k, v): self.rows = [r for r in self.rows if r.get(k) == v]; return self
    def in_(self, k, vs): self.rows = [r for r in self.rows if r.get(k) in vs]; return self
    def ilike(self, k, pat):
        needle = pat.strip("%").lower()
        self.rows = [r for r in self.rows if needle in str(r.get(k, "")).lower()]
        return self
    def order(self, *_a, **_k): return self
    def limit(self, n): self.rows = self.rows[:n]; return self
    def execute(self): return type("R", (), {"data": list(self.rows)})()


class _DB:
    def __init__(self, rows): self.rows = rows
    def table(self, name):
        return _Q([dict(r) for r in self.rows] if name == "knowledge_articles" else [])


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setattr(kb, "_USE_MOCK", False)
    monkeypatch.setattr(kb, "_db", lambda: _DB(ARTICLES))
    monkeypatch.setattr(kb, "is_internal_client", lambda cid, fid: False)
    # This caller is assigned to MINE only.
    monkeypatch.setattr(kb, "is_assigned",
                        lambda firm_id, user_id, client_id: client_id == MINE)


# ══════════════════════════════════════════════════════════════════════════════
# 1. ?scope=client used to walk straight past the check
# ══════════════════════════════════════════════════════════════════════════════

def test_asking_for_scope_client_no_longer_returns_every_clients_articles(db):
    """The regression this file exists for. An Executive assigned to one client
    asked for scope=client and got the whole firm's client-scoped knowledge."""
    got = kb.search_articles(_user("executive"), None, "client", None, False)
    assert [a["id"] for a in got] == ["A-MINE"]


def test_a_firm_wide_role_still_sees_every_clients_articles(db):
    """Partner and Manager ARE firm-wide (_FIRMWIDE_ROLES). Narrowing them too
    would be over-guarding — the fix must not cost them visibility."""
    got = kb.search_articles(_user("manager"), None, "client", None, False)
    assert [a["id"] for a in got] == ["A-MINE", "A-THEIRS"]


def test_a_reviewer_is_assignment_gated_the_same_way(db):
    got = kb.search_articles(_user("reviewer"), None, "client", None, False)
    assert [a["id"] for a in got] == ["A-MINE"]


def test_the_default_list_still_excludes_client_scoped_articles(db):
    """The `else` branch was always right; this pins it so the fix did not
    change what the plain firm KB shows."""
    got = kb.search_articles(_user("executive"), None, None, None, False)
    assert [a["id"] for a in got] == ["A-FIRM"]


def test_naming_a_client_you_are_not_on_is_still_refused_outright(db):
    """A named request gets a refusal, not a silently empty list — an empty list
    reads as "this client has no articles"."""
    with pytest.raises(HTTPException) as e:
        kb.search_articles(_user("executive"), None, "client", THEIRS, False)
    assert e.value.status_code == 403


def test_naming_a_client_you_are_on_returns_it(db):
    got = kb.search_articles(_user("executive"), None, "client", MINE, False)
    assert [a["id"] for a in got] == ["A-MINE"]


def test_the_narrowing_survives_a_text_query(db):
    """Filters compose — a search term must not become a way back around the
    scope check."""
    got = kb.search_articles(_user("executive"), "quirks", "client", None, False)
    assert [a["id"] for a in got] == ["A-MINE"]


def test_an_internal_client_article_stays_partner_only(db, monkeypatch):
    """G1 overrides assignment: the internal practice client is Partner-only
    even for a Manager, who is otherwise firm-wide."""
    monkeypatch.setattr(kb, "is_internal_client", lambda cid, fid: cid == THEIRS)
    assert [a["id"] for a in kb.search_articles(_user("manager"), None, "client", None, False)] \
        == ["A-MINE"]
    assert [a["id"] for a in kb.search_articles(_user("partner"), None, "client", None, False)] \
        == ["A-MINE", "A-THEIRS"]


# ══════════════════════════════════════════════════════════════════════════════
# 2. A write is checked as a write
# ══════════════════════════════════════════════════════════════════════════════

def test_reading_an_article_uses_the_read_predicate(db):
    art = kb._load_article_or_404(kb._db(), _user("reviewer"), "A-MINE")
    assert art["id"] == "A-MINE"


def test_the_loader_can_be_asked_for_the_write_predicate(db):
    """can_write_instruction is explicit that Reviewer and Viewer are read-only.
    Today RBAC keeps them off knowledge.write anyway, so this is the two layers
    agreeing — and it stops a future grant handing a read-only role an edit
    button without anyone noticing."""
    with pytest.raises(HTTPException) as e:
        kb._load_article_or_404(kb._db(), _user("reviewer"), "A-MINE", write=True)
    assert e.value.status_code == 403


@pytest.mark.parametrize("call", [
    pytest.param(lambda u: kb.edit_article(u, "A-MINE", "new text"), id="edit"),
    pytest.param(lambda u: kb.archive_article(u, "A-MINE"), id="archive"),
    pytest.param(lambda u: kb.restore_version(u, "A-MINE", 1), id="restore"),
])
def test_each_mutating_path_actually_asks_for_the_write_predicate(db, call):
    """Testing the loader's parameter is not the same as testing that the three
    call sites pass it — a mutant that reverted every call site to write=False
    left the parameter test passing."""
    with pytest.raises(HTTPException) as e:
        call(_user("reviewer"))
    assert e.value.status_code == 403


def test_a_manager_may_still_modify_a_client_article(db):
    art = kb._load_article_or_404(kb._db(), _user("manager"), "A-THEIRS", write=True)
    assert art["id"] == "A-THEIRS"


def test_a_firm_scoped_article_is_not_client_checked_at_all(db):
    """There is no client to scope to, and requiring one would block the firm
    knowledge base for everybody."""
    for role in ("reviewer", "viewer", "executive"):
        art = kb._load_article_or_404(kb._db(), _user(role), "A-FIRM", write=True)
        assert art["id"] == "A-FIRM"


def test_the_article_lookup_is_still_firm_scoped(db):
    with pytest.raises(HTTPException) as e:
        kb._load_article_or_404(kb._db(), _user("partner", uid="u9") | {"firm_id": "firm-2"},
                                "A-MINE")
    assert e.value.status_code == 404


def test_the_check_keys_on_client_id_not_on_the_scope_label(db, monkeypatch):
    """A row carrying a client_id but labelled something else must not slip
    through on its label. Migration 073 makes this unreachable in practice; the
    condition is on client_id so it stays unreachable if that ever changes."""
    monkeypatch.setattr(kb, "_db",
                        lambda: _DB([{"id": "A-ODD", "firm_id": FIRM, "scope": "firm",
                                      "client_id": THEIRS, "is_archived": False}]))
    with pytest.raises(HTTPException) as e:
        kb._load_article_or_404(kb._db(), _user("executive"), "A-ODD")
    assert e.value.status_code == 403
