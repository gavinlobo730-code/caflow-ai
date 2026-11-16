"""An assignment to the firm's own practice grants a non-Partner nothing, wherever the assignment is asked (POST-A-433).

THE GAP
    The practice (the firm's internal client) is the Partner's alone (G1). The router guard asks that for a URL that names a client,
    but the routes that resolve a row by its OWN id (a year-end engagement, an adjustment's engagement, an XBRL package, an e-invoice
    record, a GST or TDS return, a document and some twenty more) are outside the guard and ask only `can_access_client`, which asked
    the firm and the assignment and never G1. That was held by something else: only a Partner is firm-wide, and a signed-in session
    cannot assign the practice to anybody (migration 537), so a non-Partner could reach it only through an assignment row the service
    role wrote. Defence in depth, not an open door.

WHAT IS HELD
    * the assignment read itself drops the practice: `assigned_client_ids` and `is_client_assigned` answer as though the row were not
      there, so `can_access_client`, `effective_client_ids` and every route built on them refuse it, in their own 404;
    * a Partner still reaches the practice (firm-wide, the assignment is never asked) and a non-Partner still reaches the clients
      assigned to them;
    * the practice is recognised in the SAME statement that reads the assignment (the client's `is_internal`, embedded through
      the assignment's foreign key), so the rule costs no extra round trip on a set the bulk imports ask once per row;
    * the two year-end resolvers the finding named refuse a Manager assigned to the practice by a privileged write with the words
      they use for a missing engagement, and answer a Partner.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import core.authz as authz

FIRM, PRACTICE, CLIENT = "F1", "P-practice", "C-ordinary"
MANAGER = {"id": "U-mgr", "firm_id": FIRM, "role": "Manager"}
EXECUTIVE = {"id": "U-exe", "firm_id": FIRM, "role": "Executive"}
PARTNER = {"id": "U-ptr", "firm_id": FIRM, "role": "Partner"}


class _Rows:
    def __init__(self, rows, log):
        self.rows, self.log = rows, log

    def select(self, cols, *_a, **_k):
        self.log.append(cols)
        return self

    def eq(self, col, val):
        self.rows = [r for r in self.rows if r.get(col) == val]
        return self

    def limit(self, n):
        self.rows = self.rows[:n]
        return self

    def single(self):
        self._single = True
        return self

    def execute(self):
        data = (self.rows[0] if self.rows else None) if getattr(self, "_single", False) else list(self.rows)
        return type("R", (), {"data": data})()


class _DB:
    def __init__(self, log, **tables):
        self.tables, self.log = tables, log

    def table(self, name):
        return _Rows([dict(r) for r in self.tables.get(name, [])], self.log)


def _client(is_internal: bool) -> dict:
    """What the assignment read's `clients(is_internal)` embed answers for a row."""
    return {"is_internal": is_internal}


ASSIGNMENTS = [
    {"user_id": "U-mgr", "firm_id": FIRM, "client_id": PRACTICE, "id": "a1", "clients": _client(True)},   # by the service role
    {"user_id": "U-mgr", "firm_id": FIRM, "client_id": CLIENT, "id": "a2", "clients": _client(False)},
    {"user_id": "U-exe", "firm_id": FIRM, "client_id": PRACTICE, "id": "a3", "clients": _client(True)},
]


@pytest.fixture
def enforced(monkeypatch):
    """The enforced path: assignments read from a stand-in table that embeds each client's `is_internal`."""
    log: list = []
    monkeypatch.setattr(authz, "_USE_MOCK", False)
    monkeypatch.setattr(authz, "_db", lambda: _DB(log, user_client_assignments=ASSIGNMENTS))
    monkeypatch.setattr(authz, "_client_belongs_to_firm", lambda client_id, firm_id: firm_id == FIRM)
    return log


def test_the_assignment_read_drops_the_practice(enforced):
    assert authz.assigned_client_ids(MANAGER) == {CLIENT}
    assert authz.assigned_client_ids(EXECUTIVE) == set()
    assert authz.effective_client_ids(MANAGER) == {CLIENT}


def test_a_non_partner_assigned_to_the_practice_cannot_reach_it_and_still_reaches_their_own_client(enforced):
    assert authz.can_access_client(MANAGER, PRACTICE) is False
    assert authz.can_access_client(EXECUTIVE, PRACTICE) is False
    assert authz.can_access_client(MANAGER, CLIENT) is True
    with pytest.raises(HTTPException) as e:
        authz.assert_client_access(MANAGER, PRACTICE, detail="Engagement not found")
    assert (e.value.status_code, e.value.detail) == (404, "Engagement not found")


def test_the_partner_still_reaches_the_practice_and_the_assignment_is_not_asked(enforced):
    assert authz.can_access_client(PARTNER, PRACTICE) is True
    assert authz.effective_client_ids(PARTNER) is None
    assert enforced == [], "a Partner is firm-wide and never reaches the assignment read"


def test_the_single_assignment_check_answers_the_same(enforced):
    assert authz.is_client_assigned("U-mgr", PRACTICE, FIRM) is False
    assert authz.is_client_assigned("U-mgr", CLIENT, FIRM) is True


def test_the_practice_is_recognised_in_the_statement_that_reads_the_assignment(enforced):
    authz.assigned_client_ids(MANAGER)
    authz.is_client_assigned("U-mgr", CLIENT, FIRM)
    assert len(enforced) == 2, "one statement per question, and no second read to find the practice"
    assert all("clients(is_internal)" in cols.replace(" ", "") for cols in enforced), enforced


def test_a_row_read_without_the_embed_is_an_ordinary_client(monkeypatch, enforced):
    """A stand-in (or a database) that does not answer the embed leaves the assignment as it was: the embed is what says
    a row is the practice, so its absence can only keep a grant the code always gave, never invent a refusal."""
    plain = [{k: v for k, v in r.items() if k != "clients"} for r in ASSIGNMENTS]
    monkeypatch.setattr(authz, "_db", lambda: _DB([], user_client_assignments=plain))
    assert authz.assigned_client_ids(MANAGER) == {PRACTICE, CLIENT}


# ── the two year-end resolvers the finding named ─────────────────────────────────────────────────────────────

ENGAGEMENT = {"id": "E-practice", "firm_id": FIRM, "client_id": PRACTICE, "status": "draft"}


def test_the_year_end_resolver_refuses_a_manager_assigned_to_the_practice_in_the_missing_engagements_words(monkeypatch, enforced):
    import core.supabase_client as supabase_client
    import routers.year_end as year_end
    monkeypatch.setattr(year_end, "_USE_MOCK", False)
    monkeypatch.setattr(supabase_client, "get_supabase", lambda: _DB([], year_end_engagements=[ENGAGEMENT]))
    with pytest.raises(HTTPException) as e:
        year_end._assert_engagement_scope(MANAGER, "E-practice")
    with pytest.raises(HTTPException) as missing:
        year_end._assert_engagement_scope(MANAGER, "E-nowhere")
    assert (e.value.status_code, e.value.detail) == (missing.value.status_code, missing.value.detail) == (404, "Engagement not found")
    assert year_end._assert_engagement_scope(PARTNER, "E-practice")["id"] == "E-practice"


def test_the_adjustments_resolver_refuses_the_same_manager(enforced):
    import routers.year_end_adjustments as adjustments
    db = _DB([], year_end_engagements=[ENGAGEMENT])
    with pytest.raises(HTTPException) as e:
        adjustments._assert_engagement_scope(db, "E-practice", MANAGER)
    assert (e.value.status_code, e.value.detail) == (404, "Engagement not found")
    assert adjustments._assert_engagement_scope(db, "E-practice", PARTNER)["id"] == "E-practice"
