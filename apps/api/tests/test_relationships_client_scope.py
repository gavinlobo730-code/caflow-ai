"""
Client-assignment scope on the relationships router.

This one's tables split in two, and the split IS the design:

  FIRM-LEVEL, no client column — `entities` (a person or company the firm knows
  about), `entity_relationships` and `entity_to_entity_relationships`. They are
  deliberately shared across clients; that sharing is what makes cross-client
  match detection possible at all. Exempt, with the open question recorded.

  CLIENT-BEARING — `entity_roles` (client_id NOT NULL: "X is a Director AT this
  client"), `loans`, `properties`, and `cross_client_matches`.

THE SHARPEST ROW IN THE SWEEP SO FAR
    A cross-client match names **two** clients. Its entire content is "this PAN
    appears at client A and at client B". Firm-scoping alone handed an Executive
    assigned to client A the existence of client B and a named person's link to
    it. Both ends are checked — not either, because seeing the row with one end
    authorised still discloses the other.

AND THE DETECTION RUN IS FIRM-WIDE
    `POST /detect` reads every entity_role in the firm and writes match rows.
    There is no honest partial version: running it over one Executive's book and
    calling the result "the firm's cross-client matches" would be worse than
    refusing, because the gaps are invisible. 403, not 404.
"""
import pytest
from fastapi import HTTPException

import routers.relationships as rel

FIRM = "firm-1"
A, B, C = "client-a", "client-b", "client-c"      # A and B mine, C is not
USER = {"id": "u1", "firm_id": FIRM, "role": "Executive"}
PARTNER = {"id": "p1", "firm_id": FIRM, "role": "Partner"}


@pytest.fixture
def deny(monkeypatch):
    """Refuse exactly one client. Both `assert_client_access` and the boolean
    `can_access_client` are substituted, because this router uses both."""
    seen = []

    def _assert(user, client_id):
        seen.append(client_id)
        if client_id == C:
            raise HTTPException(status_code=404, detail="Not found")

    def _can(user, client_id):
        seen.append(client_id)
        return client_id != C

    monkeypatch.setattr(rel, "assert_client_access", _assert)
    monkeypatch.setattr(rel, "can_access_client", _can)
    monkeypatch.setattr("core.authz.effective_client_ids", lambda _u: {A, B})
    return seen


# ══════════════════════════════════════════════════════════════════════════════
# Cross-client matches — both ends, or nothing
# ══════════════════════════════════════════════════════════════════════════════

MATCHES = [
    {"id": "M-AB", "firm_id": FIRM, "entity_id": "E-1", "client_id_a": A,
     "client_id_b": B, "match_value": "ABCDE1234F", "reviewed": False},
    {"id": "M-AC", "firm_id": FIRM, "entity_id": "E-1", "client_id_a": A,
     "client_id_b": C, "match_value": "PQRSX9999Z", "reviewed": True},
    {"id": "M-CA", "firm_id": FIRM, "entity_id": "E-1", "client_id_a": C,
     "client_id_b": A, "match_value": "LMNOP1111Q", "reviewed": False},
    {"id": "M-CC", "firm_id": FIRM, "entity_id": "E-1", "client_id_a": C,
     "client_id_b": C, "match_value": "ZZZZZ0000Z", "reviewed": False},
]


@pytest.fixture
def matches(monkeypatch):
    monkeypatch.setattr(rel, "_MOCK_CROSS_MATCHES", [dict(m) for m in MATCHES])
    return rel._MOCK_CROSS_MATCHES


def test_a_match_is_visible_only_when_both_ends_are(deny):
    assert rel._match_visible(USER, MATCHES[0]) is True
    assert rel._match_visible(USER, MATCHES[1]) is False
    assert rel._match_visible(USER, MATCHES[2]) is False


def test_checking_only_one_end_would_not_be_enough(deny):
    """M-AC's client_id_a is a client the caller IS on. A guard that stopped at
    the first end would let the row through — and the row's whole content is
    that client C shares a person with client A."""
    assert rel._match_visible(USER, {"client_id_a": A, "client_id_b": C}) is False
    assert rel._match_visible(USER, {"client_id_a": C, "client_id_b": A}) is False


def test_the_match_list_drops_rows_naming_a_client_you_are_not_on(matches, deny):
    """Unreviewed rows: M-AB (both mine), M-CA and M-CC (each names client C)."""
    out = rel.list_cross_client_matches(entity_id=None, reviewed=None,
                                        current_user=USER)
    assert [m["id"] for m in out["data"]] == ["M-AB"]


def test_the_match_list_does_not_leak_the_pan_of_a_hidden_pairing(matches, deny):
    """The match_value is a real person's PAN. It is the payload, not metadata."""
    out = rel.list_cross_client_matches(entity_id=None, reviewed=None,
                                        current_user=USER)
    values = {m["match_value"] for m in out["data"]}
    assert "PQRSX9999Z" not in values and "LMNOP1111Q" not in values


def test_filtering_by_entity_does_not_bypass_the_narrowing(matches, deny):
    """The entity_id branch is a DIFFERENT path through the handler: the Entity
    Detail tab deliberately ignores the `reviewed` filter and returns the full
    match history for one entity, confirmed and dismissed included. All four
    fixtures share E-1, so without the narrowing this returns all four."""
    out = rel.list_cross_client_matches(entity_id="E-1", reviewed=None,
                                        current_user=USER)
    assert [m["id"] for m in out["data"]] == ["M-AB"]


def test_the_reviewed_branch_is_narrowed_too(matches, deny):
    """M-AC is the only reviewed row, and it names a client the caller is not
    on — so the reviewed listing must come back empty rather than showing it."""
    out = rel.list_cross_client_matches(entity_id=None, reviewed=True,
                                        current_user=USER)
    assert out["data"] == []


def test_reviewing_a_match_that_names_a_hidden_client_is_refused(matches, deny):
    """Confirming a match records a judgement against two named clients."""
    with pytest.raises(HTTPException) as e:
        rel.review_cross_client_match(
            "M-CA", rel.CrossMatchReviewIn(is_confirmed=True), current_user=USER)
    assert e.value.status_code == 404
    assert matches[2].get("reviewed") is False, "the match was reviewed anyway"


def test_reviewing_a_match_you_can_see_still_works(matches, deny):
    out = rel.review_cross_client_match(
        "M-AB", rel.CrossMatchReviewIn(is_confirmed=True), current_user=USER)
    assert out["success"] is True
    assert matches[0]["reviewed"] is True


def test_an_unknown_match_and_a_hidden_one_are_the_same_404(matches, deny):
    with pytest.raises(HTTPException) as missing:
        rel.review_cross_client_match(
            "M-NOPE", rel.CrossMatchReviewIn(is_confirmed=True), current_user=USER)
    with pytest.raises(HTTPException) as hidden:
        rel.review_cross_client_match(
            "M-CA", rel.CrossMatchReviewIn(is_confirmed=True), current_user=USER)
    assert missing.value.status_code == hidden.value.status_code == 404


# ── The detection run is firm-wide ───────────────────────────────────────────

@pytest.mark.parametrize("role", ["Executive", "Reviewer", "Manager"])
def test_detection_is_refused_to_an_assignment_scoped_role(role, matches, deny,
                                                           monkeypatch):
    """Manager is in this list deliberately: the M3 decision left only the
    Partner firm-wide."""
    monkeypatch.setattr(rel, "_MOCK_ENTITY_ROLES", [])
    with pytest.raises(HTTPException) as e:
        rel.detect_cross_client_matches(
            current_user={"id": "x", "firm_id": FIRM, "role": role})
    assert e.value.status_code == 403, "403, not 404 — no id, nothing hidden"


def test_the_detection_refusal_names_the_roles_that_qualify(deny):
    from core.authz import firmwide_roles_label
    with pytest.raises(HTTPException) as e:
        rel.detect_cross_client_matches(current_user=USER)
    assert firmwide_roles_label() in e.value.detail
    assert "Managers" not in e.value.detail


def test_a_firmwide_role_still_runs_the_detection(monkeypatch, deny):
    monkeypatch.setattr(rel, "_MOCK_ENTITY_ROLES", [])
    monkeypatch.setattr(rel, "_MOCK_ENTITIES", [])
    out = rel.detect_cross_client_matches(current_user=PARTNER)
    assert out["success"] is True
    assert "new_matches_detected" in out["data"]


# ══════════════════════════════════════════════════════════════════════════════
# entity_roles — the row that names a client
# ══════════════════════════════════════════════════════════════════════════════

ROLES = [
    {"id": "R-MINE", "firm_id": FIRM, "entity_id": "E-1", "client_id": A,
     "role": "Director"},
    {"id": "R-THEIRS", "firm_id": FIRM, "entity_id": "E-1", "client_id": C,
     "role": "Shareholder"},
]


@pytest.fixture
def roles(monkeypatch):
    monkeypatch.setattr(rel, "_MOCK_ENTITY_ROLES", [dict(r) for r in ROLES])
    monkeypatch.setattr(rel, "_MOCK_ENTITIES",
                        [{"id": "E-1", "firm_id": FIRM, "full_name": "A Person",
                          "pan": "ABCDE1234F"}])
    monkeypatch.setattr(rel, "_MOCK_RELATIONSHIPS", [])
    return rel._MOCK_ENTITY_ROLES


def test_deleting_a_role_at_a_client_you_are_not_on_is_refused(roles, deny):
    """Deleting "X is a Shareholder at client C" is editing client C's record."""
    with pytest.raises(HTTPException) as e:
        rel.remove_entity_role("R-THEIRS", current_user=USER)
    assert e.value.status_code == 404
    assert [r["id"] for r in rel._MOCK_ENTITY_ROLES] == ["R-MINE", "R-THEIRS"]


def test_deleting_your_own_clients_role_still_works(roles, deny):
    out = rel.remove_entity_role("R-MINE", current_user=USER)
    assert out["success"] is True
    assert [r["id"] for r in rel._MOCK_ENTITY_ROLES] == ["R-THEIRS"]


def test_an_unknown_role_and_a_hidden_one_are_the_same_404(roles, deny):
    with pytest.raises(HTTPException) as missing:
        rel.remove_entity_role("R-NOPE", current_user=USER)
    with pytest.raises(HTTPException) as hidden:
        rel.remove_entity_role("R-THEIRS", current_user=USER)
    assert missing.value.status_code == hidden.value.status_code == 404


def test_adding_a_role_at_a_client_you_are_not_on_is_refused(roles, deny):
    with pytest.raises(HTTPException):
        rel.add_entity_role("E-1", rel.EntityRoleIn(
            client_id=C, role_type="Director"), current_user=USER)


# ── The entity register stays firm-level; its ROLES do not ───────────────────

def test_the_entity_register_is_not_narrowed(roles, deny):
    """`entities` has no client_id (migration 059) and is deliberately shared
    across clients — that sharing is what makes cross-client detection work.
    Over-guarding is a real failure mode; this fails if somebody narrows it."""
    out = rel.list_entities(entity_type=None, search=None, limit=50, offset=0,
                            current_user=USER)
    assert [e["id"] for e in out["data"]] == ["E-1"]


def test_the_roles_embedded_in_an_entity_ARE_narrowed(roles, deny):
    """The entity itself is firm-level. "This person is a Shareholder at client
    C" is not — and it is returned right alongside the entity. The sweep lets
    this endpoint pass on its exemption, so this test is what holds it."""
    out = rel.get_entity("E-1", current_user=USER)
    assert out["data"]["full_name"] == "A Person"
    assert [r["id"] for r in out["data"]["roles"]] == ["R-MINE"]


def test_the_hidden_role_does_not_leak_the_client_it_names(roles, deny):
    out = rel.get_entity("E-1", current_user=USER)
    assert C not in {r.get("client_id") for r in out["data"]["roles"]}


# ══════════════════════════════════════════════════════════════════════════════
# The endpoints that were already guarded — pinned, not assumed
# ══════════════════════════════════════════════════════════════════════════════

def test_reading_another_clients_loans_is_refused(deny):
    """Section 185/186 Companies Act — loans and advances to directors."""
    with pytest.raises(HTTPException) as e:
        rel.list_loans(client_id=C, flagged_only=False, current_user=USER)
    assert e.value.status_code == 404


def test_the_section_185_report_is_refused_for_another_client(deny):
    with pytest.raises(HTTPException):
        rel.section_185_report(client_id=C, current_user=USER)


def test_reading_another_clients_properties_is_refused(deny):
    with pytest.raises(HTTPException):
        rel.list_properties(client_id=C, current_user=USER)


def test_the_related_party_report_is_refused_for_another_client(deny):
    """AS 18 / Ind AS 24 related-party disclosure — the whole point of it is to
    name every connected person and company."""
    with pytest.raises(HTTPException):
        rel.related_party_report(client_id=C, current_user=USER)


def test_your_own_clients_loans_still_load(deny, monkeypatch):
    monkeypatch.setattr(rel, "_MOCK_LOANS",
                        [{"id": "L1", "firm_id": FIRM, "client_id": A,
                          "principal_paise": 100}])
    out = rel.list_loans(client_id=A, flagged_only=False, current_user=USER)
    assert [l["id"] for l in out["data"]] == ["L1"]


# ══════════════════════════════════════════════════════════════════════════════
# The LIVE query path
# ══════════════════════════════════════════════════════════════════════════════
# Everything above drives the mock branch, because `_db()` returns None without
# SUPABASE_URL. That is half the router: every endpoint here has a second,
# entirely separate real-DB implementation, and a first mutation pass found SIX
# guards that no test touched because of it. Two of those mutants are a live
# `SELECT` dropping the very column the guard reads — and `can_access_client(
# user, None)` treats a missing client as "firm-level resource" and returns
# True, so that is the guard failing OPEN. The fake below honours the column
# projection precisely so those cannot hide.

class _Res:
    def __init__(self, data):
        self.data = data


class _FakeQ:
    def __init__(self, name, rows, log):
        self.name, self.rows, self.log = name, rows, log
        self.cols, self.op, self.filters, self.ors, self.single_ = "*", "select", [], None, False

    def select(self, cols="*"):
        self.cols = cols
        return self

    def insert(self, payload):
        self.op, self.payload = "insert", payload
        return self

    def update(self, payload):
        self.op, self.payload = "update", payload
        return self

    def delete(self):
        self.op = "delete"
        return self

    def eq(self, col, val):
        self.filters.append((col, val))
        return self

    def or_(self, expr):
        self.ors = expr
        return self

    def order(self, *_a, **_k):
        return self

    def range(self, *_a, **_k):
        return self

    def single(self):
        self.single_ = True
        return self

    def execute(self):
        self.log.append((self.name, self.op, self.cols))
        out = list(self.rows)
        for col, val in self.filters:
            out = [r for r in out if r.get(col) == val]
        if self.ors:
            wanted = {p.split(".eq.")[1] for p in self.ors.split(",") if ".eq." in p}
            out = [r for r in out
                   if r.get("from_entity_id") in wanted or r.get("to_entity_id") in wanted]
        if self.op in ("update", "delete"):
            return _Res(list(out))
        keep = None if self.cols == "*" else [c.strip() for c in self.cols.split(",")]
        proj = [{k: v for k, v in r.items() if keep is None or k in keep} for r in out]
        if self.single_:
            return _Res(proj[0] if proj else None)
        return _Res(proj)


class _FakeDb:
    def __init__(self, tables):
        self.tables, self.log = tables, []

    def table(self, name):
        return _FakeQ(name, self.tables.get(name, []), self.log)


@pytest.fixture
def live_db(monkeypatch):
    db = _FakeDb({
        "cross_client_matches": [dict(m) for m in MATCHES],
        "entity_roles": [dict(r) for r in ROLES],
        "entities": [{"id": "E-1", "firm_id": FIRM, "full_name": "A Person",
                      "pan": "ABCDE1234F"}],
        "entity_relationships": [],
    })
    monkeypatch.setattr(rel, "_db", lambda: db)
    return db


def test_live_the_match_list_is_narrowed(live_db, deny):
    out = rel.list_cross_client_matches(entity_id=None, reviewed=None,
                                        current_user=USER)
    assert [m["id"] for m in out["data"]] == ["M-AB"]


def test_live_reviewing_a_hidden_match_is_refused(live_db, deny):
    with pytest.raises(HTTPException) as e:
        rel.review_cross_client_match(
            "M-CA", rel.CrossMatchReviewIn(is_confirmed=True), current_user=USER)
    assert e.value.status_code == 404
    assert [op for _n, op, _c in live_db.log] == ["select"], \
        "the update ran despite the refusal"
    assert deny[-2:] == [C, A] or deny[-1:] == [C], \
        "the guard was handed no client ids — a missing one reads as firm-level"


def test_live_reviewing_a_visible_match_still_works(live_db, deny):
    out = rel.review_cross_client_match(
        "M-AB", rel.CrossMatchReviewIn(is_confirmed=True), current_user=USER)
    assert out["success"] is True
    assert "update" in [op for _n, op, _c in live_db.log]


def test_live_deleting_a_role_at_a_hidden_client_is_refused(live_db, deny):
    with pytest.raises(HTTPException) as e:
        rel.remove_entity_role("R-THEIRS", current_user=USER)
    assert e.value.status_code == 404
    assert "delete" not in [op for _n, op, _c in live_db.log], \
        "the role was deleted despite the refusal"
    assert deny[-1] == C, \
        "the guard was handed no client_id — a missing one reads as firm-level"


def test_live_deleting_your_own_clients_role_still_works(live_db, deny):
    out = rel.remove_entity_role("R-MINE", current_user=USER)
    assert out["success"] is True
    assert "delete" in [op for _n, op, _c in live_db.log]


def test_live_the_roles_on_an_entity_are_narrowed(live_db, deny):
    out = rel.get_entity("E-1", current_user=USER)
    assert out["data"]["full_name"] == "A Person"
    assert [r["id"] for r in out["data"]["roles"]] == ["R-MINE"]
