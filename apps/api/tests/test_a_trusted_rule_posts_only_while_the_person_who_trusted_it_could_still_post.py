"""A trusted bank rule posts only while the person who trusted it could still let it (ledger POST-A-339).

A trusted rule passes entries without a click and every journal it posts is credited to `rule.trusted_by`. The one authority the sweep
asked was that a trusted rule EXISTS for the client; it never asked, when it ran, whether that person is still a member, still reaches
the client and still holds the Banking approval and access. A member un-assigned, suspended, demoted or blocked on the Team screen after
trusting a rule left a rule that kept posting under their name, every day, from the scheduler.

These tests state the rule from the outside: who is refused, that the refusal is the same one the screen's number and the sweep both
see, that the lines stay in the review queue for a person, that the run says which rule and why, and that nothing else changed.
"""
from __future__ import annotations

import ast
import logging
import pathlib
from types import SimpleNamespace

import pytest

import core.authz as authz
import jobs.bank_trusted_rules_job as job
import services.bank_entry_service as bes
import services.trusted_rule_authority as authority
from domain.banking import entry as E
from services.bank_entry_service import bank_entry_service as svc
from tests.e2e_harness import FakeDB
from tests.test_bank_entry_service import _db, _line, _Poster, _row, _rule, _state
from tests.test_bank_matching import CLIENT, FIRM

API = pathlib.Path(__file__).resolve().parents[1]
RULE_TRUSTED = dict(is_trusted=True, trusted_at="2026-09-03T00:00:00Z")


# ── the verdict, person by person ────────────────────────────────────────────────────────────────────────────────────────

def _members(*rows) -> FakeDB:
    db = FakeDB()
    for r in rows:
        db.seed("users", dict({"firm_id": FIRM, "is_active": True}, **r))
    return db


@pytest.fixture
def real_assignments(monkeypatch):
    """Judge client reach against the fake's own assignment table, as production does against the real one (mock mode is permissive)."""
    def use(db):
        monkeypatch.setattr(authz, "_USE_MOCK", False)
        monkeypatch.setattr(authz, "_db", lambda: db)
    return use


def _assign(db, user, client=CLIENT, firm=FIRM):
    db.seed("user_client_assignments", {"user_id": user, "client_id": client, "firm_id": firm})


def test_a_manager_assigned_to_the_client_still_answers_for_the_rule(real_assignments):
    db = _members({"id": "m", "role": "Manager"})
    _assign(db, "m")
    real_assignments(db)
    assert authority.authority_gap(db, FIRM, CLIENT, "m") is None


def test_a_partner_reaches_every_client_of_the_firm_without_an_assignment(real_assignments):
    db = _members({"id": "p", "role": "Partner"})
    real_assignments(db)
    assert authority.authority_gap(db, FIRM, CLIENT, "p") is None


def test_a_manager_who_was_unassigned_no_longer_answers(real_assignments):
    db = _members({"id": "m", "role": "Manager"})
    real_assignments(db)
    assert authority.authority_gap(db, FIRM, CLIENT, "m") == authority.NOT_ASSIGNED


def test_an_assignment_to_another_client_or_written_in_another_firm_does_not_count(real_assignments):
    db = _members({"id": "m", "role": "Manager"})
    _assign(db, "m", client="another-client")
    _assign(db, "m", firm="another-firm")
    real_assignments(db)
    assert authority.authority_gap(db, FIRM, CLIENT, "m") == authority.NOT_ASSIGNED


def test_a_suspended_member_no_longer_answers(real_assignments):
    db = _members({"id": "m", "role": "Partner", "is_active": False})
    real_assignments(db)
    assert authority.authority_gap(db, FIRM, CLIENT, "m") == authority.SUSPENDED


def test_a_member_row_that_does_not_say_it_is_inactive_is_active(real_assignments):
    db = FakeDB()
    db.seed("users", {"id": "m", "firm_id": FIRM, "role": "Partner"})        # no is_active key at all
    real_assignments(db)
    assert authority.authority_gap(db, FIRM, CLIENT, "m") is None


def test_a_person_who_is_not_a_member_of_this_firm_does_not_answer(real_assignments):
    db = FakeDB()
    db.seed("users", {"id": "m", "firm_id": "another-firm", "role": "Partner", "is_active": True})
    real_assignments(db)
    assert authority.authority_gap(db, FIRM, CLIENT, "m") == authority.NOT_A_MEMBER
    assert authority.authority_gap(db, FIRM, CLIENT, "nobody") == authority.NOT_A_MEMBER


def test_a_manager_demoted_to_an_executive_no_longer_answers_though_an_executive_may_write_banking(real_assignments):
    """The reason the check asks the approval as well as the write: an Executive writes banking, so write alone would have let a
    demoted person's rule keep posting. The approval is what went with the seat."""
    db = _members({"id": "m", "role": "Executive"})
    _assign(db, "m")
    real_assignments(db)
    assert authority.authority_gap(db, FIRM, CLIENT, "m") == authority.CANNOT_TRUST


def test_the_per_person_grid_decides_both_pairs(real_assignments):
    db = _members({"id": "m", "role": "Manager"}, {"id": "e", "role": "Executive"})
    _assign(db, "m")
    _assign(db, "e")
    real_assignments(db)
    db.seed("user_permissions", {"firm_id": FIRM, "user_id": "m", "resource": "banking", "action": "write", "granted": False})
    assert authority.authority_gap(db, FIRM, CLIENT, "m") == authority.CANNOT_POST
    db.rows("user_permissions").clear()
    db.seed("user_permissions", {"firm_id": FIRM, "user_id": "m", "resource": "banking", "action": "approve", "granted": False})
    assert authority.authority_gap(db, FIRM, CLIENT, "m") == authority.CANNOT_TRUST
    # ...and a grant is honoured: an Executive the Partner gave the approval to answers for what they trust
    db.seed("user_permissions", {"firm_id": FIRM, "user_id": "e", "resource": "banking", "action": "approve", "granted": True})
    assert authority.authority_gap(db, FIRM, CLIENT, "e") is None


def test_a_block_written_in_another_firm_for_the_same_person_is_not_theirs(real_assignments):
    db = _members({"id": "m", "role": "Manager"})
    _assign(db, "m")
    real_assignments(db)
    db.seed("user_permissions", {"firm_id": "another-firm", "user_id": "m", "resource": "banking", "action": "write",
                                 "granted": False})
    assert authority.authority_gap(db, FIRM, CLIENT, "m") is None


@pytest.mark.parametrize("role", [None, "", "Overlord"])
def test_a_member_with_no_known_role_does_not_answer(real_assignments, role):
    db = _members({"id": "m", "role": role})
    real_assignments(db)
    assert authority.authority_gap(db, FIRM, CLIENT, "m") == authority.NO_ROLE


@pytest.mark.parametrize("who", [None, ""])
def test_a_rule_nobody_is_recorded_as_trusting_posts_nothing(who):
    class _Untouchable:
        def table(self, name):
            raise AssertionError("no read is made for a rule with no person")
    assert authority.authority_gap(_Untouchable(), FIRM, CLIENT, who) == authority.NO_ONE


def test_a_check_that_cannot_be_made_is_a_refusal_and_is_reported(monkeypatch, caplog):
    caplog.set_level(logging.ERROR, logger="caflow.bank.trusted_rule_authority")
    seen = []
    monkeypatch.setattr(authority, "capture_soft_failure", lambda exc, **ctx: seen.append((exc, ctx)))

    class _Broken:
        def table(self, name):
            raise RuntimeError("the database went away")
    assert authority.authority_gap(_Broken(), FIRM, CLIENT, "m") == authority.UNREADABLE
    assert len(seen) == 1 and seen[0][1] == {"operation": "trusted_rule_authority"}
    assert any("could not be read" in r.getMessage() for r in caplog.records)      # and logged with its traceback, not swallowed


def test_the_servers_own_client_does_the_reading_where_there_is_one(monkeypatch, real_assignments):
    """A request's client reads another member's grid under row security and would see it empty, which falls back to the role, which
    is failing open. With a privileged client the grid that is read is the real one."""
    request_db = _members({"id": "m", "role": "Manager"})
    server_db = _members({"id": "m", "role": "Manager"})
    server_db.seed("user_permissions", {"firm_id": FIRM, "user_id": "m", "resource": "banking", "action": "write",
                                        "granted": False})
    _assign(server_db, "m")
    real_assignments(server_db)
    monkeypatch.setattr(authority.db_provider, "service_db_or_none", lambda: server_db)
    assert authority.authority_gap(request_db, FIRM, CLIENT, "m") == authority.CANNOT_POST


def test_the_codes_are_the_ones_the_sentences_carry():
    gaps = [authority.NO_ONE, authority.FIRM_UNAVAILABLE, authority.NOT_A_MEMBER, authority.SUSPENDED, authority.NO_ROLE,
            authority.CANNOT_TRUST, authority.CANNOT_POST, authority.NOT_ASSIGNED, authority.UNREADABLE]
    assert tuple(g.code for g in gaps) == authority.CODES
    assert len({g.code for g in gaps}) == len(gaps) == 9
    assert all(g.sentence.endswith(".") and g.sentence[0].isupper() for g in gaps)


# ── the sweep and the screen's number ────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def poster(monkeypatch):
    p = _Poster()
    monkeypatch.setattr(bes.bank_posting_service, "post", p)
    return p


def _trusting(db, who="mgr-1", rid="trusted"):
    # one pattern per rule, so a line is drafted by exactly the rule its test means
    rule = _rule(db, rid=rid, pattern=rid.upper(), trusted_by=who, **RULE_TRUSTED)
    _line(db, f"line-{rid}", f"NEFT {rid.upper()} APR")
    return rule


def _member(db, who, **kw):
    db.store["users"].append(dict({"id": who, "firm_id": FIRM, "role": "Manager", "is_active": True}, **kw))


def _unassign_everyone(monkeypatch, db):
    monkeypatch.setattr(authz, "_USE_MOCK", False)
    monkeypatch.setattr(authz, "_db", lambda: SimpleNamespace(table=lambda name: _EmptyQuery()))


class _EmptyQuery:
    def select(self, *_a, **_k): return self
    def eq(self, *_a, **_k): return self
    def limit(self, *_a, **_k): return self
    def execute(self): return SimpleNamespace(data=[])


def test_the_control_a_rule_whose_person_still_answers_posts_as_them(poster):
    db = _db()
    _trusting(db)
    svc.redraft(db, FIRM, CLIENT)
    out = svc.pass_ready(db, FIRM, CLIENT, only_trusted=True)
    assert out["passed"] == 1 and "rules_not_posting" not in out
    assert [c["actor_id"] for c in poster.calls] == ["mgr-1"]


@pytest.mark.parametrize("how,code", [
    ("suspend", "suspended"),
    ("remove", "not_a_member"),
    ("demote", "cannot_trust"),
    ("block_write", "cannot_post"),
    ("block_approve", "cannot_trust"),
    ("unassign", "not_assigned"),
])
def test_a_rule_whose_person_stopped_answering_posts_nothing_and_its_line_stays_in_the_queue(poster, monkeypatch, how, code):
    db = _db()
    _trusting(db)
    svc.redraft(db, FIRM, CLIENT)
    assert svc.counts(db, FIRM, CLIENT)["trusted_pending"] == 1
    member = db.store["users"][0]
    if how == "suspend":
        member["is_active"] = False
    elif how == "remove":
        db.store["users"].clear()
    elif how == "demote":
        member["role"] = "Executive"
    elif how in ("block_write", "block_approve"):
        db.store["user_permissions"].append({"firm_id": FIRM, "user_id": "mgr-1", "resource": "banking",
                                             "action": "write" if how == "block_write" else "approve", "granted": False})
    elif how == "unassign":
        _unassign_everyone(monkeypatch, db)

    out = svc.pass_ready(db, FIRM, CLIENT, only_trusted=True)

    assert (out["passed"], out["failed"], out["skipped"], out["remaining"]) == (0, 0, 0, 0)
    assert out["rules_not_posting"] == [{"rule_id": "trusted", "code": code,
                                         "reason": next(g.sentence for g in (authority.SUSPENDED, authority.NOT_A_MEMBER,
                                                                             authority.CANNOT_TRUST, authority.CANNOT_POST,
                                                                             authority.NOT_ASSIGNED) if g.code == code)}]
    assert poster.calls == []
    assert _state(db, "line-trusted") == E.READY                       # still there for a person to pass
    assert svc.counts(db, FIRM, CLIENT)["trusted_pending"] == 0        # and the screen's number agrees with the sweep


def test_only_the_rule_whose_person_stopped_is_left_alone(poster):
    db = _db()
    _member(db, "mgr-2", is_active=False)
    _trusting(db, "mgr-1", rid="good")
    _trusting(db, "mgr-2", rid="stopped")
    svc.redraft(db, FIRM, CLIENT)
    out = svc.pass_ready(db, FIRM, CLIENT, only_trusted=True)
    assert out["passed"] == 1 and [c["actor_id"] for c in poster.calls] == ["mgr-1"]
    assert [r["rule_id"] for r in out["rules_not_posting"]] == ["stopped"]
    assert _row(db, "line-good")["posted_by_rule_id"] == "good"
    assert _state(db, "line-stopped") == E.READY


def test_a_rule_with_no_recorded_person_posts_nothing(poster):
    db = _db()
    _trusting(db, who=None)
    svc.redraft(db, FIRM, CLIENT)
    out = svc.pass_ready(db, FIRM, CLIENT, only_trusted=True)
    assert out["passed"] == 0 and out["rules_not_posting"][0]["code"] == "no_one_answers"
    assert poster.calls == []


def test_the_person_getting_their_access_back_puts_the_rule_back(poster):
    db = _db()
    _trusting(db)
    svc.redraft(db, FIRM, CLIENT)
    db.store["users"][0]["is_active"] = False
    assert svc.pass_ready(db, FIRM, CLIENT, only_trusted=True)["passed"] == 0
    db.store["users"][0]["is_active"] = True
    assert svc.pass_ready(db, FIRM, CLIENT, only_trusted=True)["passed"] == 1
    assert [c["actor_id"] for c in poster.calls] == ["mgr-1"]


def test_a_person_clicking_pass_ready_is_not_a_trusted_rule_and_is_not_asked_about_the_rules_person(poster):
    """The click posts as the clicker with the clicker's own rights (the route's rbac). The rule's person is asked only when a rule
    is what passes."""
    db = _db()
    _trusting(db)
    svc.redraft(db, FIRM, CLIENT)
    db.store["users"][0]["is_active"] = False
    out = svc.pass_ready(db, FIRM, CLIENT, actor_id="exec-1")
    assert out["passed"] == 1 and "rules_not_posting" not in out
    assert [c["actor_id"] for c in poster.calls] == ["exec-1"]


def test_a_rule_that_is_not_trusted_is_never_reported_as_not_posting(poster):
    db = _db()
    _rule(db, rid="plain", pattern="CHARGES")
    _line(db, "l", "NEFT CHARGES")
    svc.redraft(db, FIRM, CLIENT)
    out = svc.pass_ready(db, FIRM, CLIENT, only_trusted=True)
    assert out == {"passed": 0, "failed": 0, "skipped": 0, "remaining": 0, "results": []}


def test_the_daily_sweep_names_the_rule_and_the_reason_and_leaves_the_line(poster, monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="caflow.bank_trusted_rules")
    monkeypatch.setattr(job, "_USE_MOCK", False)
    db = _db()
    _member(db, "mgr-2", is_active=False)
    _trusting(db, "mgr-1", rid="good")
    _trusting(db, "mgr-2", rid="stopped")
    out = job.run_trusted_rules_for_firm(FIRM, db=db)
    summary = out["clients"][CLIENT]
    assert out["passed"] == 1 and summary["passed"] == 1
    assert summary["rules_not_posting"] == [
        {"rule_id": "stopped", "code": "suspended", "reason": authority.SUSPENDED.sentence}]
    assert _state(db, "line-stopped") == E.READY and _row(db, "line-good")["posted_by_rule_id"] == "good"
    assert any("left alone" in r.getMessage() for r in caplog.records)            # and a Partner reading the log can see it


def test_the_daily_sweep_when_every_rule_stopped_ends_quickly_and_still_says_so(poster, monkeypatch):
    monkeypatch.setattr(job, "_USE_MOCK", False)
    db = _db()
    _trusting(db)
    db.store["users"][0]["is_active"] = False
    out = job.run_trusted_rules_for_firm(FIRM, db=db)
    assert out["passed"] == 0 and out["failed"] == 0
    assert out["clients"][CLIENT]["rules_not_posting"][0]["code"] == "suspended"
    assert poster.calls == []


def test_a_clean_sweep_adds_nothing_to_its_summary(poster, monkeypatch):
    monkeypatch.setattr(job, "_USE_MOCK", False)
    db = _db()
    _trusting(db)
    out = job.run_trusted_rules_for_firm(FIRM, db=db)
    assert "rules_not_posting" not in out["clients"][CLIENT]


# ── the rule over the source ─────────────────────────────────────────────────────────────────────────────────────────────

def test_every_read_of_the_trusted_flag_is_one_of_the_four_that_cannot_post_without_the_question():
    """THE RULE, NOT A SPELLING OF IT: the column name `is_trusted` as a string constant, in any call or key of any non-test module,
    in any spelling of the read (`.eq`, `.match`, `.filter`, a dict key, a `.get`), may appear only in these four functions. `counts()`
    and `pass_ready()` read the trusted set through `_trusted_rules`, which asks whether the person still answers; the job's list of
    clients to visit posts nothing; the rules list only READS the flag to say which rules are waiting; and the edit route WRITES it.
    A fifth is a way to post, or to say a rule posts, without the question."""
    found = set()
    for path in sorted(API.glob("**/*.py")):
        if {"tests", "migrations", "venv", "scripts"} & set(path.parts):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in (n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))):
            inner = {id(c) for d in ast.walk(fn) if d is not fn and isinstance(d, (ast.FunctionDef, ast.AsyncFunctionDef))
                     for c in ast.walk(d)}
            if any(isinstance(c, ast.Constant) and c.value == "is_trusted" and id(c) not in inner for c in ast.walk(fn)):
                found.add((path.relative_to(API).as_posix(), fn.name))
    assert found == {("jobs/bank_trusted_rules_job.py", "_clients_with_trusted_rules"),
                     ("services/bank_entry_service.py", "_trusted_rules"),
                     ("routers/banking.py", "list_rules"),
                     ("routers/banking.py", "update_rule")}, sorted(found)


def test_counts_and_pass_ready_both_ask_through_trusted_rules():
    tree = ast.parse((API / "services/bank_entry_service.py").read_text(encoding="utf-8"))
    for name in ("counts", "pass_ready"):
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
        assert any(isinstance(c, ast.Call) and getattr(c.func, "attr", "") == "_trusted_rules" for c in ast.walk(fn)), name


def test_the_trusted_rules_function_asks_the_authority_of_every_rule_it_returns():
    tree = ast.parse((API / "services/bank_entry_service.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_trusted_rules")
    assert any(isinstance(c, ast.Call) and ast.unparse(c.func) == "trusted_rule_authority.verdict" for c in ast.walk(fn))


# ── what the independent review of 24-10-2026 added ──────────────────────────────────────────────────────────────────────

def test_a_suspended_or_deleted_firm_has_no_member_who_can_post(real_assignments):
    """Sign-in refuses every member of a suspended or soft-deleted firm, so none of them could post; a rule credited to one of them
    must not either (the scheduler lists every firm, and nothing there filters a suspended one)."""
    db = _members({"id": "p", "role": "Partner"})
    real_assignments(db)
    db.seed("firms", {"id": FIRM, "is_active": False})
    assert authority.authority_gap(db, FIRM, CLIENT, "p") == authority.FIRM_UNAVAILABLE
    db.rows("firms").clear()
    db.seed("firms", {"id": FIRM, "is_active": True, "deleted_at": "2026-10-01T00:00:00Z"})
    assert authority.authority_gap(db, FIRM, CLIENT, "p") == authority.FIRM_UNAVAILABLE
    db.rows("firms").clear()
    db.seed("firms", {"id": FIRM, "is_active": True, "deleted_at": None})
    assert authority.authority_gap(db, FIRM, CLIENT, "p") is None
    db.rows("firms").clear()          # a firm row that does not say so blocks nobody, exactly as sign-in reads it
    assert authority.authority_gap(db, FIRM, CLIENT, "p") is None


def test_the_verdict_carries_the_members_auth_id_for_the_audit_log(real_assignments):
    db = _members({"id": "m", "role": "Partner", "auth_user_id": "auth-m"}, {"id": "s", "role": "Partner", "is_active": False,
                                                                           "auth_user_id": "auth-s"})
    real_assignments(db)
    assert authority.verdict(db, FIRM, CLIENT, "m") == authority.Verdict(None, "auth-m")
    assert authority.verdict(db, FIRM, CLIENT, "s") == authority.Verdict(authority.SUSPENDED, "auth-s")
    assert authority.verdict(db, FIRM, CLIENT, "nobody").auth_user_id is None


def test_the_audit_row_of_a_pass_by_rule_names_the_trusted_person_by_their_auth_id_and_not_their_users_id(poster, monkeypatch):
    """audit_log.actor_id takes the AUTH id (the edit-log rule in CLAUDE.md); the rule carries the internal users.id, which is what
    the journal's created_by wants and what this row used to name."""
    db = _db()
    db.store["users"][0]["auth_user_id"] = "auth-mgr-1"
    seen = []
    monkeypatch.setattr("services.audit_service.log_event", lambda *a, **k: seen.append(k))
    _trusting(db)
    svc.redraft(db, FIRM, CLIENT)
    assert svc.pass_ready(db, FIRM, CLIENT, only_trusted=True)["passed"] == 1
    rows = [k for k in seen if (k.get("metadata") or {}).get("source") == "bank_trusted_rule"]
    assert [k["actor_id"] for k in rows] == ["auth-mgr-1"]
    assert [c["actor_id"] for c in poster.calls] == ["mgr-1"]          # the journal is still credited to the internal id


def test_one_verdict_is_taken_per_person_per_read_however_many_rules_they_trusted(monkeypatch):
    """The cost note ('about three small reads per person per screen load') depends on it: a client with many rules trusted by one
    person must not multiply the cross-region reads on every counts call and every pass chunk."""
    db = _db()
    _member(db, "mgr-2")
    for rid in ("a", "b", "c"):
        _trusting(db, "mgr-1", rid=rid)
    _trusting(db, "mgr-2", rid="d")
    asked = []
    real = authority.verdict
    monkeypatch.setattr(authority, "verdict", lambda d, f, c, who: asked.append(who) or real(d, f, c, who))
    assert len(svc._trusted_rules(db, FIRM, CLIENT)) == 4
    assert sorted(asked) == ["mgr-1", "mgr-2"]


def test_a_privileged_client_that_cannot_be_built_is_a_check_that_cannot_be_made(monkeypatch):
    """`a check that cannot be made is a refusal` includes failing to get the client the check is made with."""
    seen = []
    monkeypatch.setattr(authority, "capture_soft_failure", lambda exc, **ctx: seen.append(exc))

    def no_service_key():
        raise RuntimeError("no service key")
    monkeypatch.setattr(authority.db_provider, "service_db_or_none", no_service_key)
    assert authority.authority_gap(FakeDB(), FIRM, CLIENT, "m") == authority.UNREADABLE
    assert len(seen) == 1


PARTNER = {"firm_id": FIRM, "role": "Partner", "auth_user_id": "p1", "id": "u1"}


def _banking_router(monkeypatch, db):
    import routers.banking as banking_router
    monkeypatch.setattr(banking_router, "_db", lambda: db)
    monkeypatch.setattr(authz, "_USE_MOCK", True)
    return banking_router


def test_the_pass_ready_answer_gives_every_caller_the_same_neutral_words_for_a_waiting_rule(poster, monkeypatch):
    """The specific reason names a colleague's suspension or removal, which the Team screen shows only to those who hold team:read.
    The run's summary keeps it; an answer any banking user can read does not carry it."""
    from models.banking import EntriesPassReadyIn
    db = _db()
    _trusting(db)
    svc.redraft(db, FIRM, CLIENT)
    db.store["users"][0]["is_active"] = False
    out = _banking_router(monkeypatch, db).pass_ready_entries(
        EntriesPassReadyIn(client_id=CLIENT, only_trusted=True), current_user=PARTNER)["data"]
    assert out["rules_not_posting"] == [{"rule_id": "trusted", "reason": authority.WAITING_SENTENCE}]
    assert "suspend" not in str(out).lower() and "member" not in str(out).lower()
    assert "code" not in out["rules_not_posting"][0]
    # while the service, which the job reads, keeps the specific reason
    assert svc.pass_ready(db, FIRM, CLIENT, only_trusted=True)["rules_not_posting"][0]["code"] == "suspended"


def test_the_rules_list_says_which_trusted_rule_is_waiting_so_no_screen_says_it_passes(monkeypatch):
    db = _db()
    _member(db, "mgr-2", is_active=False)
    _trusting(db, "mgr-1", rid="ok")
    _trusting(db, "mgr-2", rid="stopped")
    _rule(db, rid="plain", pattern="PLAIN")
    listed = {r["id"]: r for r in _banking_router(monkeypatch, db).list_rules(client_id=CLIENT, current_user=PARTNER)["data"]}
    assert listed["stopped"]["trusted_waiting"] is True
    assert listed["stopped"]["trusted_waiting_reason"] == authority.WAITING_SENTENCE
    assert "trusted_waiting" not in listed["ok"] and "trusted_waiting" not in listed["plain"]


def test_the_rules_list_reads_nobodys_status_when_no_rule_is_trusted(monkeypatch):
    db = _db()
    _rule(db, rid="plain", pattern="PLAIN")
    listed = _banking_router(monkeypatch, db).list_rules(client_id=CLIENT, current_user=PARTNER)["data"]
    assert [r["id"] for r in listed] == ["plain"] and "trusted_waiting" not in listed[0]


def test_the_promotion_door_asks_the_per_person_grid_as_the_sweep_does(monkeypatch):
    """A Manager the Partner blocked from approving is refused at trust time with a sentence (not given a rule that is dead on arrival);
    an Executive the Partner granted the approval to may trust, which is what 'a grant is honoured' means."""
    from fastapi import HTTPException
    from models.banking import MatchingRuleUpdateIn
    db = _db()
    _rule(db, rid="r1")
    router = _banking_router(monkeypatch, db)
    blocked_manager = {**PARTNER, "role": "Manager", "id": "mgr-1", "permission_overrides": {"banking:approve": False}}
    with pytest.raises(HTTPException) as e:
        router.update_rule("r1", MatchingRuleUpdateIn(is_trusted=True), current_user=blocked_manager)
    assert e.value.status_code == 403
    assert db.store["bank_matching_rules"][0]["is_trusted"] is False
    granted_executive = {**PARTNER, "role": "Executive", "id": "exe-1", "permission_overrides": {"banking:approve": True}}
    assert router.update_rule("r1", MatchingRuleUpdateIn(is_trusted=True), current_user=granted_executive)["success"] is True
    assert db.store["bank_matching_rules"][0]["trusted_by"] == "exe-1"
    plain_executive = {**PARTNER, "role": "Executive", "id": "exe-2"}
    with pytest.raises(HTTPException):
        router.update_rule("r1", MatchingRuleUpdateIn(is_trusted=True), current_user=plain_executive)


def test_no_door_in_the_banking_router_asks_the_role_template_for_the_approval():
    """`can(role, ...)` is the template, not the person; the grid governs every request through `can_user`. Both doors that turn on
    the approval (promote a rule, delete one that posted lines) ask the person."""
    tree = ast.parse((API / "routers/banking.py").read_text(encoding="utf-8"))
    templated = [ast.unparse(c) for c in ast.walk(tree) if isinstance(c, ast.Call) and getattr(c.func, "id", "") == "can"]
    assert templated == [], templated
    asked = [c for c in ast.walk(tree) if isinstance(c, ast.Call) and getattr(c.func, "id", "") == "can_user"
             and ast.unparse(c).endswith("'banking', 'approve')")]
    assert len(asked) == 2


def test_the_rules_screen_reads_the_key_the_list_serves_and_says_it_is_waiting():
    """The badge used to say 'Trusted — passes without a click' of every trusted rule, true or not. The screen reads
    `trusted_waiting` and `trusted_waiting_reason`, which the list serves under exactly those names."""
    tab = (API.parents[1] / "apps/web/components/banking/RulesTab.tsx").read_text(encoding="utf-8")
    router = (API / "routers/banking.py").read_text(encoding="utf-8")
    for key in ("trusted_waiting", "trusted_waiting_reason"):
        assert key in tab and f'"{key}"' in router, key
    assert "Trusted — waiting" in tab and "passes without a click" in tab
    assert tab.index("r.is_trusted && r.trusted_waiting") < tab.index("r.is_trusted && !r.trusted_waiting")      # waiting is its own branch
