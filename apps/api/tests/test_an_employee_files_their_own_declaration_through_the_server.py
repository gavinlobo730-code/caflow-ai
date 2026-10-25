"""POST-A-010, the employee portal's tax-declaration tab: the employee's Form 12BB is read and filed through the server.

THE FAULT. The tab read `payroll_it_declarations` and its lines from PostgREST, and wrote them there: an upsert of the header, a
delete of the old lines and an insert of the new ones, as the employee's own token, under migration 297's policies. The only
rules on that path were the database's: nothing refused a missing landlord's PAN above the Rule 26C threshold, a lender's
PAN against §24(b) interest, a regime that is not one or a head payroll cannot give effect to (the screen offered only the six it
can, and nothing else checked); the three steps were not tied together; and the browser held the employee, client and firm ids it
sent.

WHAT THE DOOR DOES, each pinned here:

  * WHO AND WHAT come from the principal: nothing in the body names an employee, a client or a firm, and a body that tries to is
    ignored, so the row written is the caller's;
  * AN EMPLOYEE DECLARES AND NEVER VERIFIES: the verified columns and the verification flag are reset on every filing, and a
    declaration the CA has finished verifying is read-only (409);
  * THE STAFF DOOR'S VALIDATION applies, in the employee's own words (a 422 whose sentence the tab shows), and a refused
    declaration writes nothing;
  * THE LINES ARE REPLACED WHOLESALE, new before old, and a failure part-way puts back what it replaced: the earlier lines stay,
    the header goes back to what it was, a declaration that did not exist is removed again, and the caller still gets the failure;
  * ONLY the caller's own declaration is ever read or returned.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.payroll as payroll_mod
import routers.portal_employee as portal_mod
import tests.e2e_harness as harness
from core.portal_auth import get_current_portal_employee
from tests.e2e_harness import FakeDB

FIRM, OTHER_FIRM = "F1", "F2"
CLIENT, OTHER_CLIENT = "C1", "C2"
ME, COLLEAGUE = "E-me", "E-colleague"
FY = "2026-27"
ME_CTX = {
    "portal": True, "employee": True, "employee_id": ME, "client_id": CLIENT,
    "firm_id": FIRM, "name": "Me", "employee_code": "EMP-001",
    "email": "me@f1.test", "role": "PortalEmployee", "auth_user_id": "auth-me",
}


@pytest.fixture
def world(monkeypatch):
    db = FakeDB()
    audit: list = []
    monkeypatch.setattr(payroll_mod, "_db", lambda: db)
    import core.supabase_client as sc
    monkeypatch.setattr(sc, "get_service_supabase", lambda: db)
    monkeypatch.setattr(portal_mod, "log_event", lambda *a, **k: audit.append((a, k)))
    app = FastAPI()
    app.include_router(portal_mod.router)
    app.dependency_overrides[get_current_portal_employee] = lambda: dict(ME_CTX)
    db.audit = audit
    return TestClient(app, raise_server_exceptions=False), db


def _body(**over):
    body = {"fy": FY, "regime": "old", "rent_paid_declared_paise": 0, "landlord_name": "", "landlord_address": "",
            "landlord_pan": "", "rent_is_metro": False, "lta_declared_paise": 0, "home_loan_interest_declared_paise": 0,
            "lender_name": "", "lender_pan": "", "other_income_declared_paise": 0, "house_property_loss_declared_paise": 0,
            "items": [{"section": "80C", "amount_declared_paise": 15_000_000}]}
    body.update(over)
    return body


def _put(client, **over):
    return client.put("/api/portal/employee/tax-declaration", json=_body(**over))


def _heads(db, employee=ME):
    return [r for r in db.rows("payroll_it_declarations") if r["employee_id"] == employee]


def _lines(db):
    return sorted((r["section"], r["amount_declared_paise"]) for r in db.rows("payroll_it_declaration_items"))


def _seed_declaration(db, *, employee=ME, firm=FIRM, client=CLIENT, verified=False, rent_verified=0, lines=(("80C", 5_000_000),)):
    head = db.seed("payroll_it_declarations", {
        "firm_id": firm, "client_id": client, "employee_id": employee, "fy": FY, "regime": "new", "status": "submitted",
        "rent_paid_declared_paise": 6_000_000, "rent_paid_verified_paise": rent_verified, "landlord_name": "Old landlord",
        "landlord_address": "", "landlord_pan": "ABCDE1234F", "rent_is_metro": True, "lta_declared_paise": 100_000,
        "lta_verified_paise": 50_000 if rent_verified else 0, "home_loan_interest_declared_paise": 0,
        "home_loan_interest_verified_paise": 0, "lender_name": "", "lender_pan": "", "other_income_declared_paise": 0,
        "house_property_loss_declared_paise": 0, "proofs_verified": verified,
        "verified_at": "2026-10-01T00:00:00+00:00" if verified else None, "verified_by": "u1" if verified else None,
        "submitted_at": "2026-09-01T00:00:00+00:00", "updated_at": "2026-09-01T00:00:00+00:00"})
    for section, paise in lines:
        db.seed("payroll_it_declaration_items", {"firm_id": firm, "declaration_id": head["id"], "section": section, "label": "",
                                                 "amount_declared_paise": paise, "amount_verified_paise": paise // 2,
                                                 "status": "verified", "proof_reference": "", "proof_attachments": []})
    return head


# ── reading ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_with_nothing_filed_the_read_says_so(world):
    client, _ = world
    r = client.get("/api/portal/employee/tax-declaration", params={"financial_year": FY})
    assert r.status_code == 200 and r.json()["data"] == {"fy": FY, "declaration": None, "items": []}


def test_the_read_is_the_callers_own_declaration_and_its_lines_in_the_columns_the_form_shows(world):
    client, db = world
    # The others are seeded FIRST, so a read that forgot to scope by the employee or the firm would return theirs.
    _seed_declaration(db, employee=COLLEAGUE, lines=(("80C", 9_900_000),))
    _seed_declaration(db, employee=ME, firm=OTHER_FIRM, client=OTHER_CLIENT, lines=(("80C", 7_700_000),))
    mine = _seed_declaration(db, lines=(("80D-self", 2_500_000), ("80C", 5_000_000)))
    body = client.get("/api/portal/employee/tax-declaration", params={"financial_year": FY}).json()["data"]
    assert body["declaration"]["id"] == mine["id"] and body["declaration"]["landlord_name"] == "Old landlord"
    assert not ({"firm_id", "client_id", "employee_id", "rent_paid_verified_paise", "verified_by"} & set(body["declaration"]))
    assert [(i["section"], i["amount_declared_paise"]) for i in body["items"]] == [("80C", 5_000_000), ("80D-self", 2_500_000)]


def test_a_year_that_is_not_one_is_a_422(world):
    client, _ = world
    assert client.get("/api/portal/employee/tax-declaration", params={"financial_year": "2026-28"}).status_code == 422


# ── filing ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_filing_writes_the_callers_row_with_the_principals_ids_and_nothing_verified(world):
    client, db = world
    r = _put(client, items=[{"section": "80C", "amount_declared_paise": 15_000_000},
                            {"section": "80D-self", "amount_declared_paise": 2_500_000},
                            {"section": "80TTA", "amount_declared_paise": 0}])
    assert r.status_code == 200, r.text
    [head] = _heads(db)
    assert (head["firm_id"], head["client_id"], head["employee_id"], head["fy"]) == (FIRM, CLIENT, ME, FY)
    assert head["status"] == "submitted" and head["regime"] == "old" and head["proofs_verified"] is False
    assert head["rent_paid_verified_paise"] == head["lta_verified_paise"] == head["home_loan_interest_verified_paise"] == 0
    assert head["verified_at"] is None and head["verified_by"] is None and head["submitted_at"]
    assert _lines(db) == [("80C", 15_000_000), ("80D-self", 2_500_000)], "a head declared at nothing is not a line"
    assert all(i["status"] == "declared" and i["amount_verified_paise"] == 0 and i["firm_id"] == FIRM
               for i in db.rows("payroll_it_declaration_items"))
    assert r.json()["data"]["declaration"]["id"] == head["id"] and len(r.json()["data"]["items"]) == 2


def test_a_body_that_names_somebody_else_is_ignored_and_the_row_is_the_callers(world):
    client, db = world
    r = client.put("/api/portal/employee/tax-declaration", json={
        **_body(), "employee_id": COLLEAGUE, "client_id": OTHER_CLIENT, "firm_id": OTHER_FIRM,
        "proofs_verified": True, "rent_paid_verified_paise": 999, "status": "verified"})
    assert r.status_code == 200, r.text
    [head] = db.rows("payroll_it_declarations")
    assert (head["employee_id"], head["firm_id"], head["client_id"]) == (ME, FIRM, CLIENT)
    assert head["proofs_verified"] is False and head["rent_paid_verified_paise"] == 0 and head["status"] == "submitted"


def test_re_filing_replaces_the_lines_wholesale_and_resets_what_the_ca_had_checked(world):
    client, db = world
    _seed_declaration(db, rent_verified=4_000_000, lines=(("80C", 5_000_000), ("80D-parents", 1_000_000)))
    _seed_declaration(db, employee=COLLEAGUE, lines=(("80C", 9_900_000),))
    r = _put(client, items=[{"section": "80CCD(1B)", "amount_declared_paise": 5_000_000}])
    assert r.status_code == 200, r.text
    [head] = _heads(db)
    assert head["rent_paid_verified_paise"] == 0 and head["lta_verified_paise"] == 0 and head["status"] == "submitted"
    mine = [(i["section"], i["amount_declared_paise"]) for i in db.rows("payroll_it_declaration_items")
            if i["declaration_id"] == head["id"]]
    assert mine == [("80CCD(1B)", 5_000_000)], "the withdrawn investments are gone, not merged"
    assert ("80C", 9_900_000) in _lines(db), "the colleague's lines are untouched"
    assert len(db.rows("payroll_it_declarations")) == 2


def test_one_declaration_per_employee_per_year_is_an_upsert(world):
    client, db = world
    _put(client); _put(client, regime="new")
    assert len(_heads(db)) == 1 and _heads(db)[0]["regime"] == "new"


def test_a_declaration_the_ca_finished_verifying_is_read_only_and_nothing_changes(world):
    client, db = world
    _seed_declaration(db, verified=True, rent_verified=4_000_000)
    before = ([dict(r) for r in db.rows("payroll_it_declarations")], [dict(r) for r in db.rows("payroll_it_declaration_items")])
    r = _put(client, items=[{"section": "80C", "amount_declared_paise": 1}])
    assert r.status_code == 409 and "read-only" in r.json()["detail"]
    assert ([dict(x) for x in db.rows("payroll_it_declarations")], [dict(x) for x in db.rows("payroll_it_declaration_items")]) == before
    assert db.audit == []


def test_the_filing_is_in_the_audit_log_by_the_employees_sign_in_id_and_email(world):
    """`audit_log.actor_id` takes the Supabase sign-in id (the same id the trigger writes), never the employee's row id."""
    client, db = world
    _put(client)
    [(args, kwargs)] = db.audit
    assert args[0] == FIRM and args[1] == "payroll_it_declaration" and args[3] == "employee_declare"
    assert kwargs["actor_id"] == "auth-me" and kwargs["actor_id"] != ME
    assert kwargs["actor_email"] == "me@f1.test" and kwargs["metadata"]["employee_id"] == ME


# ── refusals, each writing nothing ───────────────────────────────────────────────────────────────────────────────────

REFUSALS = [
    ("rent over the Rule 26C threshold with no landlord PAN", dict(rent_paid_declared_paise=15_000_000, landlord_name="L"), "landlord's PAN"),
    ("rent with no landlord named", dict(rent_paid_declared_paise=5_000_000), "landlord's name"),
    ("home-loan interest with no lender PAN", dict(home_loan_interest_declared_paise=100_000_00), "lender's PAN"),
    ("a head payroll cannot give effect to", dict(items=[{"section": "80GG", "amount_declared_paise": 100}]), "80GG"),
    ("a regime that is not one", dict(regime="maybe"), "regime"),
    ("a head declared twice", dict(items=[{"section": "80C", "amount_declared_paise": 1}, {"section": "80C", "amount_declared_paise": 2}]),
     "declared twice"),
]


@pytest.mark.parametrize("why, over, words", REFUSALS, ids=[r[0] for r in REFUSALS])
def test_what_payroll_cannot_give_effect_to_is_refused_in_words_and_writes_nothing(world, why, over, words):
    client, db = world
    r = _put(client, **over)
    assert r.status_code == 422, (why, r.text)
    assert words in str(r.json()["detail"]), (why, r.json())
    assert db.rows("payroll_it_declarations") == [] and db.rows("payroll_it_declaration_items") == []


@pytest.mark.parametrize("over", [dict(landlord_pan="NOTAPAN"), dict(lender_pan="123"), dict(rent_paid_declared_paise=-1),
                                  dict(lta_declared_paise=-5), dict(fy="2026-28"), dict(landlord_name="x" * 201),
                                  dict(items=[{"section": "80C", "amount_declared_paise": -1}])])
def test_a_shape_the_model_refuses_is_a_422_and_writes_nothing(world, over):
    client, db = world
    assert _put(client, **over).status_code == 422
    assert db.rows("payroll_it_declarations") == []


def test_a_pan_is_upper_cased_and_a_blank_one_stays_blank(world):
    client, db = world
    _put(client, rent_paid_declared_paise=15_000_000, landlord_name="L", landlord_pan="abcde1234f")
    assert _heads(db)[0]["landlord_pan"] == "ABCDE1234F"


# ── a failure part-way puts back what it replaced ────────────────────────────────────────────────────────────────────

class _Fail:
    """Make the n-th matching write on a table raise or come back short, on top of the harness's own double."""

    def __init__(self, monkeypatch, table, op, *, nth=1, short=False):
        self.table, self.op, self.nth, self.short, self.seen = table, op, nth, short, 0
        real = harness._Query.execute
        me = self

        def execute(q):
            if q.table == me.table and q._op == me.op:
                me.seen += 1
                if me.seen == me.nth:
                    if me.short:
                        return harness._Result([])
                    raise RuntimeError("write refused")
            return real(q)

        monkeypatch.setattr(harness._Query, "execute", execute)


def test_a_line_that_cannot_be_written_leaves_the_earlier_lines_and_puts_the_header_back(world, monkeypatch):
    client, db = world
    head = _seed_declaration(db, rent_verified=4_000_000, lines=(("80C", 5_000_000), ("80D-parents", 1_000_000)))
    before_head = dict(head)
    before_lines = _lines(db)
    _Fail(monkeypatch, "payroll_it_declaration_items", "insert", nth=2)
    r = _put(client, regime="new", rent_paid_declared_paise=0,
             items=[{"section": "80CCD(1B)", "amount_declared_paise": 1}, {"section": "80D-self", "amount_declared_paise": 2}])
    assert r.status_code == 500
    assert _lines(db) == before_lines, "the earlier lines stay and the line that did go in came out again"
    [after] = _heads(db)
    assert {k: after[k] for k in before_head if k != "updated_at"} == {k: v for k, v in before_head.items() if k != "updated_at"}
    assert db.audit == []


def test_a_delete_that_removed_fewer_lines_than_were_there_stops_the_filing_and_puts_back(world, monkeypatch):
    """A refusal that came back as an empty answer is the defect POST-A-255 found in the browser's version of this save."""
    client, db = world
    head = _seed_declaration(db, lines=(("80C", 5_000_000),))
    before_lines = _lines(db)
    _Fail(monkeypatch, "payroll_it_declaration_items", "delete", nth=1, short=True)
    r = _put(client, items=[{"section": "80D-self", "amount_declared_paise": 7}])
    assert r.status_code == 500
    assert _lines(db) == before_lines and _heads(db)[0]["regime"] == head["regime"]
    assert db.audit == []


def test_a_first_filing_that_fails_part_way_leaves_no_declaration_at_all(world, monkeypatch):
    client, db = world
    _Fail(monkeypatch, "payroll_it_declaration_items", "insert", nth=2)
    r = _put(client, items=[{"section": "80C", "amount_declared_paise": 1}, {"section": "80D-self", "amount_declared_paise": 2}])
    assert r.status_code == 500
    assert db.rows("payroll_it_declarations") == [] and db.rows("payroll_it_declaration_items") == []


def test_the_new_lines_go_in_before_the_old_ones_come_out(world, monkeypatch):
    client, db = world
    _seed_declaration(db, lines=(("80C", 5_000_000),))
    order: list = []
    real = harness._Query.execute

    def execute(q):
        if q.table == "payroll_it_declaration_items" and q._op in ("insert", "delete"):
            order.append(q._op)
        return real(q)

    monkeypatch.setattr(harness._Query, "execute", execute)
    assert _put(client, items=[{"section": "80D-self", "amount_declared_paise": 7}]).status_code == 200
    assert order == ["insert", "delete"]


def test_a_put_back_that_itself_fails_is_reported_and_the_real_failure_still_reaches_the_caller(world, monkeypatch):
    client, db = world
    _seed_declaration(db, lines=(("80C", 5_000_000),))
    reported: list = []
    monkeypatch.setattr(portal_mod, "capture_soft_failure", lambda exc, **kw: reported.append((str(exc), kw["operation"])))
    real = harness._Query.execute
    header_updates = {"n": 0}

    def execute(q):
        if q.table == "payroll_it_declaration_items" and q._op == "insert":
            raise RuntimeError("insert refused")
        if q.table == "payroll_it_declarations" and q._op == "update":
            header_updates["n"] += 1
            if header_updates["n"] == 2:   # the first is the filing's own write; the second is the put-back
                raise RuntimeError("restore refused")
        return real(q)

    monkeypatch.setattr(harness._Query, "execute", execute)
    r = _put(client, items=[{"section": "80D-self", "amount_declared_paise": 7}])
    assert r.status_code == 500
    assert ("restore refused", "employee_declaration.put_back_header") in reported


# ── the lock is decided in the write, the put-back never undoes a verification, nothing is lost to a delete that raised ──

def _after_first(monkeypatch, table, op, hook):
    """Run `hook(query)` once, right after the first matching request has been answered."""
    real = harness._Query.execute
    state = {"done": False}

    def execute(q):
        res = real(q)
        if not state["done"] and q.table == table and q._op == op:
            state["done"] = True
            hook(q)
        return res

    monkeypatch.setattr(harness._Query, "execute", execute)


def test_a_ca_who_finishes_verifying_between_the_read_and_the_write_is_not_overwritten(world, monkeypatch):
    """The 409 is not only a read: migration 297's update policy asked `proofs_verified IS FALSE` of the statement itself, and the
    update here carries the same condition, so a verification that lands after the read wins and the filing changes nothing."""
    client, db = world
    head = _seed_declaration(db, lines=(("80C", 5_000_000),))
    before = ([dict(r) for r in db.rows("payroll_it_declaration_items")], dict(head))

    def verify(q):
        row = db.rows("payroll_it_declarations")[0]
        row.update(proofs_verified=True, rent_paid_verified_paise=4_000_000, verified_by="u1")

    _after_first(monkeypatch, "payroll_it_declarations", "select", verify)
    r = _put(client, items=[{"section": "80D-self", "amount_declared_paise": 7}])
    assert r.status_code == 409 and "read-only" in r.json()["detail"]
    row = db.rows("payroll_it_declarations")[0]
    assert row["proofs_verified"] is True and row["rent_paid_verified_paise"] == 4_000_000, "the verification must stand"
    assert row["regime"] == head["regime"] and row["landlord_name"] == "Old landlord", "and nothing of the filing was written"
    assert [dict(r) for r in db.rows("payroll_it_declaration_items")] == before[0]
    assert db.audit == []


def test_a_put_back_never_undoes_a_verification_that_landed_meanwhile(world, monkeypatch):
    client, db = world
    _seed_declaration(db, lines=(("80C", 5_000_000),))
    real = harness._Query.execute

    def execute(q):
        if q.table == "payroll_it_declaration_items" and q._op == "insert":
            # the CA finishes verifying, and then this line cannot be written
            db.rows("payroll_it_declarations")[0].update(proofs_verified=True, rent_paid_verified_paise=777)
            raise RuntimeError("insert refused")
        return real(q)

    monkeypatch.setattr(harness._Query, "execute", execute)
    assert _put(client, items=[{"section": "80D-self", "amount_declared_paise": 7}]).status_code == 500
    row = db.rows("payroll_it_declarations")[0]
    assert row["proofs_verified"] is True and row["rent_paid_verified_paise"] == 777


def test_a_delete_that_was_applied_and_then_raised_leaves_the_old_lines_exactly_as_they_were(world, monkeypatch):
    """The old lines' own ids and figures (including what a verifier had put on them) are written back, not just their sections."""
    client, db = world
    _seed_declaration(db, lines=(("80C", 5_000_000), ("80D-parents", 1_000_000)))
    snapshot = sorted((r["id"], r["section"], r["amount_declared_paise"], r["amount_verified_paise"], r["status"])
                      for r in db.rows("payroll_it_declaration_items"))
    real = harness._Query.execute
    seen = {"n": 0}

    def execute(q):
        if q.table == "payroll_it_declaration_items" and q._op == "delete":
            seen["n"] += 1
            if seen["n"] == 1:
                real(q)                                   # the database applied it ...
                raise RuntimeError("connection reset")    # ... and the answer never arrived
        return real(q)

    monkeypatch.setattr(harness._Query, "execute", execute)
    assert _put(client, items=[{"section": "80CCD(1B)", "amount_declared_paise": 9}]).status_code == 500
    assert sorted((r["id"], r["section"], r["amount_declared_paise"], r["amount_verified_paise"], r["status"])
                  for r in db.rows("payroll_it_declaration_items")) == snapshot
    assert _heads(db)[0]["regime"] == "new" and _heads(db)[0]["landlord_name"] == "Old landlord"


def test_a_line_a_concurrent_filing_added_is_not_left_beside_the_new_ones(world, monkeypatch):
    client, db = world
    head = _seed_declaration(db, lines=(("80C", 5_000_000),))

    def another_filer(q):
        db.seed("payroll_it_declaration_items", {"firm_id": FIRM, "declaration_id": head["id"], "section": "80TTA", "label": "",
                                                 "amount_declared_paise": 99, "amount_verified_paise": 0, "status": "declared",
                                                 "proof_reference": "", "proof_attachments": []})

    _after_first(monkeypatch, "payroll_it_declaration_items", "insert", another_filer)
    r = _put(client, items=[{"section": "80D-self", "amount_declared_paise": 7}])
    assert r.status_code == 200, r.text
    assert _lines(db) == [("80D-self", 7)], "exactly the lines filed: neither the old ones nor the stranger's"


def test_a_first_filing_made_from_another_window_at_the_same_instant_is_a_409_in_words(world, monkeypatch):
    client, db = world
    real = harness._Query.execute

    class _Dup(Exception):
        code = "23505"

    def execute(q):
        if q.table == "payroll_it_declarations" and q._op == "insert":
            raise _Dup('duplicate key value violates unique constraint "payroll_it_declarations_employee_fy_key"')
        return real(q)

    monkeypatch.setattr(harness._Query, "execute", execute)
    r = _put(client)
    assert r.status_code == 409 and "changed while you were saving" in r.json()["detail"]
    assert db.rows("payroll_it_declaration_items") == [] and db.audit == []


def test_the_two_payload_literals_do_not_drift():
    """The header is written out in full for a declaration that exists (an update) and for one that does not (an insert), so the
    column guard reads every name; they must carry the same columns or one door writes what the other forgets."""
    import ast
    import inspect
    import textwrap
    tree = ast.parse(textwrap.dedent(inspect.getsource(portal_mod.file_employee_tax_declaration)))
    literals = [n for n in ast.walk(tree) if isinstance(n, ast.Dict)
                and any(isinstance(k, ast.Constant) and k.value == "proofs_verified" for k in n.keys)]
    assert len(literals) == 2, "the route must hold exactly the update payload and the insert payload"
    keys = [{k.value for k in lit.keys if isinstance(k, ast.Constant)} for lit in literals]
    assert keys[0] == keys[1]
    assert {"firm_id", "client_id", "employee_id", "fy", "rent_paid_verified_paise", "proofs_verified", "verified_by"} <= keys[0]


# ── a refusal names the box ──────────────────────────────────────────────────────────────────────────────────────────

def _messages(r):
    return [d["msg"] for d in r.json()["detail"]]


def test_two_bad_pans_are_two_sentences_each_naming_its_own_box(world):
    client, _ = world
    r = _put(client, landlord_pan="bad", lender_pan="12")
    assert r.status_code == 422
    assert _messages(r) == ["Landlord's PAN must be in the form AAAAA9999A.", "Lender's PAN must be in the form AAAAA9999A."]


def test_a_name_or_address_that_is_too_long_names_which_one(world):
    client, db = world
    r = _put(client, landlord_name="x" * 201, landlord_address="y" * 501, lender_name="z" * 201)
    assert r.status_code == 422
    assert sorted(_messages(r)) == sorted([
        "The landlord's name must be at most 200 characters.", "The landlord's address must be at most 500 characters.",
        "The lender's name must be at most 200 characters."])
    assert db.rows("payroll_it_declarations") == []


def test_a_name_at_the_limit_is_accepted(world):
    client, db = world
    assert _put(client, landlord_name="x" * 200, landlord_address="y" * 500).status_code == 200


def test_a_principal_with_no_client_is_refused_before_anything_is_written(monkeypatch, world):
    _, db = world
    app = FastAPI()
    app.include_router(portal_mod.router)
    app.dependency_overrides[get_current_portal_employee] = lambda: {**ME_CTX, "client_id": None}
    r = TestClient(app, raise_server_exceptions=False).put("/api/portal/employee/tax-declaration", json=_body())
    assert r.status_code == 403 and db.rows("payroll_it_declarations") == []
