"""The engagement letters are WRITTEN with the privileged client, and the one write that leaned on row security asks the questions
itself (POST-A-008, the engagements tranche, part 1 of 2).

THE PREMISE
    `engagements` (an engagement letter: the fee, the scope of work, the signatory and the signing link of a client, or of a lead before
    there is one) is granted to the signed-in role behind policies that ask the firm, the client assignment (a lead's letter, with no client,
    is the firm's), the practice's own client (a Partner's) and the client write tier (migration 537). The browser writes none of it; every
    writer is the API's. Found by POST-A-008's list of the tables a signed-in session reaches outside the access matrix: it is the last table
    on it a signed-in session can write.

    A later migration takes the signed-in write away. THIS is the half that ships first: every write is made with the privileged client now,
    which carries no row security, so each route must ask what the policies asked. The staff routes already did (`client:write`, and
    `_assert_engagement_scope` or `assert_client_access` on the letter's client before the write); the public signing page writes by the
    letter's token with the service client, as it always did, and now names the firm too. The one write that RELIED on row security is
    linking a signed letter to the client a lead converts into (`lifecycle._link_signed_letter`): it ran as the caller so that a letter
    naming a client they cannot reach, or one they could not reach after the link, was not linked, and the route said so. It asks both
    sides itself now, and says the same sentence without writing.

The rules are `tests/_privileged_write_sites.py`'s, shared with the other tranches; this file names the group, its census and the link.
"""
from __future__ import annotations

from tests import _privileged_write_sites as pw

TABLES = frozenset({"engagements"})

#: A letter may be a lead's, with no client, so it is named by its id and the firm.
KEYS = {"engagements": ("firm_id", "id")}

#: How many write sites the table has today. A change that adds or removes one updates this.
WRITE_SITES = {"engagements": 14}


def test_every_write_to_the_engagement_letters_starts_at_the_privileged_client():
    bad = pw.unprivileged_writes(TABLES)
    assert not bad, ("A write to an engagement letter is made with the caller's own client: the migration that follows takes that "
                     "client's write grant away. Make it with `privileged_for(db)`, naming its scope:\n  " + "\n  ".join(bad))


def test_every_update_names_the_letter_and_the_firm():
    bad = pw.unscoped(TABLES, KEYS)
    assert not bad, "an update of an engagement letter does not name the letter and the firm:\n  " + "\n  ".join(bad)


def test_the_census_finds_the_writes_there_are():
    found = pw.census(TABLES)
    assert found == WRITE_SITES, f"the writers changed: {found} (expected {WRITE_SITES}); update WRITE_SITES and read the new writer against the rule"


def test_the_rules_can_fail():
    src = ('def f(db):\n'
           '    db.table("engagements").insert({}).execute()\n'
           '    privileged_for(db).table("engagements").update({}).eq("id", 1).eq("sign_token", 2).execute()\n')
    sites = pw.write_sites(src, TABLES)
    assert [ok for *_x, ok, _r in sites] == [False, True]
    assert pw.unscoped_updates_and_deletes(src, TABLES, KEYS) == ["engagements at line 3"]


# ── the link of a signed letter to the client a lead converts into ──────────────────────────────────────────────
FIRM, LETTER, NEW, OTHER = "firm-1", "eng-1", "client-new", "client-other"


class _Q:
    def __init__(self, db, table):
        self.db, self.table, self.op, self.filters, self.payload = db, table, "select", [], None

    def select(self, *_a):
        return self

    def update(self, payload):
        self.op, self.payload = "update", payload
        return self

    def eq(self, col, val):
        self.filters.append((col, val))
        return self

    def limit(self, _n):
        return self

    def execute(self):
        rows = [r for r in self.db.rows if all(r.get(c) == v for c, v in self.filters)]
        if self.op == "update":
            self.db.updates.append(dict(self.filters))
            for r in rows:
                r.update(self.payload)

        class R:
            data = [dict(r) for r in rows]
        return R()


class _Db:
    def __init__(self, client_id):
        self.rows = [{"id": LETTER, "firm_id": FIRM, "client_id": client_id}]
        self.updates = []

    def table(self, name):
        assert name == "engagements"
        return _Q(self, name)


def _link(monkeypatch, letter_client, reachable):
    import core.authz
    from routers import lifecycle
    monkeypatch.setattr(core.authz, "can_access_client", lambda _user, client_id: client_id is None or client_id in reachable)
    db = _Db(letter_client)
    warning = lifecycle._link_signed_letter(db, LETTER, NEW, FIRM, "2026-11-15T00:00:00Z", {"id": "u1", "firm_id": FIRM})
    return db, warning


def test_a_leads_letter_is_linked_to_the_client_the_caller_may_reach(monkeypatch):
    db, warning = _link(monkeypatch, None, {NEW})
    assert warning is None
    assert db.rows[0]["client_id"] == NEW and db.updates == [{"id": LETTER, "firm_id": FIRM}]


def test_a_letter_naming_a_client_the_caller_cannot_reach_is_not_linked_and_says_so(monkeypatch):
    db, warning = _link(monkeypatch, OTHER, {NEW})
    assert warning and "not assigned to" in warning
    assert db.updates == [] and db.rows[0]["client_id"] == OTHER


def test_a_letter_is_not_linked_to_a_client_the_caller_could_not_reach_after(monkeypatch):
    db, warning = _link(monkeypatch, None, set())
    assert warning and "not assigned to" in warning
    assert db.updates == [] and db.rows[0]["client_id"] is None
