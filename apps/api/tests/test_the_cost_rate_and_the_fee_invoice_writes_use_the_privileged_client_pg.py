"""A staff cost rate and a fee invoice's status, deletion and overdue mark are written with the privileged client (ledger POST-A-320).

WHAT WAS WRONG
    Three writers used the caller's own database client on a table whose signed-in write had been taken away on purpose, so
    with per-user sign-in on (USE_USER_JWT, the production default) each was refused with 42501 for every caller, a Partner
    included, while every double in the suite accepted it:

      * `services/billing_service.set_staff_cost_rate` updates `users.cost_rate_paise`; migration 153 left the signed-in role
        UPDATE on `users.full_name` alone, and 246 granted that again after 194 undid it (`PUT /api/billing/staff-cost-rates/{id}`,
        an API route no screen calls yet: the API client has the wrapper `setCostRate`);
      * `repositories/invoice_repository.update`, `delete`, `soft_delete` and `change_status` update `fee_invoices`; migrations
        172 and 245 took UPDATE from the signed-in role because the browser used to force-set `status = 'Paid'` whatever the
        receipt (`POST /api/invoices/run-overdue-check`, which the billing screen calls; `DELETE /api/invoices/{id}`;
        `PATCH /api/invoices/{id}/status`, which no screen calls).

    The grants were read in production on 22-10-2026 and match: the signed-in role holds no UPDATE on `fee_invoices` (any
    column) and none on `users.cost_rate_paise`, and keeps INSERT on `fee_invoices`, which is why `create` stays on the caller's
    client.

WHAT THIS DRIVES, AND HOW
    The real code against a real database, as the roles production uses: the request's client is
    `tests/_signed_in_postgrest.SignedInDb` running as `authenticated`, the privileged client is the same double running as
    `service_role`; nothing in the code under test is replaced except which client `core.db_provider` hands out (and the
    notification a newly overdue invoice sends, which is not under test).

    * THE PREMISE, in a database built from the migrations: `authenticated` holds no UPDATE on `fee_invoices` and none on
      `users.cost_rate_paise`, and the same UPDATE through the caller's client is refused with 42501 (the defect, reproduced);
    * the cost rate is written (and cleared), only for a member of the caller's own firm, and a member of another firm or no
      member at all is a 404 and not a success that changed nothing; the answer carries two fields and not the whole user row;
    * the overdue check marks exactly the issued invoices of the firm whose due date has passed, leaves an invoice not yet due,
      a draft and every other firm's invoice alone, and the form with no firm named (no caller today: the nightly job names
      each firm) marks each firm's own; the mark is conditional on the invoice still being Issued, so an invoice a receipt
      covered since it was read is not overwritten with Overdue;
    * a draft invoice is deleted by its own firm and not by another's (the statement names the firm), and a status change
      reaches only the firm's own invoice; the status route refuses a bare 'Paid', refuses to move an invoice out of Paid or
      back to Draft once issued, and refuses any move but Issued <-> Overdue once money has been received; the delete route
      refuses a draft that has receipts recorded;
    * `list_staff_cost_rates` lists the firm's members (it listed only the caller under their own sign-in) and no other firm's;
    * CONTROL: with the request's own client handed to the writers (the previous behaviour) each write is refused by the
      database, so these tests can see the defect.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode job.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid

import pytest
from fastapi import HTTPException

from tests._signed_in_postgrest import SignedInDb, SignedInError

_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None,
    reason="the signed-in writers proof requires HARNESS_PG + psql",
)

FIRM_A = "32000000-0000-0000-0000-00000000000a"
FIRM_B = "32000000-0000-0000-0000-00000000000b"
CLIENT_A = "32000000-0000-0000-0000-0000000000a1"
CLIENT_B = "32000000-0000-0000-0000-0000000000b1"
PARTNER = {"id": "32000000-0000-0000-0000-0000000000a0", "auth_user_id": "32000000-1111-0000-0000-000000000001",
           "role": "Partner", "firm_id": FIRM_A, "email": "partner@a.in"}
STAFF_A = "32000000-0000-0000-0000-0000000000a2"
STAFF_B = "32000000-0000-0000-0000-0000000000b2"
INV_DRAFT = "32000000-0000-0000-0000-000000000d01"
INV_OVERDUE = "32000000-0000-0000-0000-000000000d02"
INV_NOT_DUE = "32000000-0000-0000-0000-000000000d03"
INV_OTHER_FIRM = "32000000-0000-0000-0000-000000000d04"
INV_OTHER_FIRM_DRAFT = "32000000-0000-0000-0000-000000000d05"
INV_PAID = "32000000-0000-0000-0000-000000000d06"
INV_DRAFT_WITH_RECEIPT = "32000000-0000-0000-0000-000000000d07"
INV_PART_PAID = "32000000-0000-0000-0000-000000000d08"


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql], capture_output=True, text=True)


def _rows(dsn: str, sql: str) -> list[list[str]]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-F", "\t", "-c", sql], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [line.split("\t") for line in r.stdout.splitlines() if line.strip()]


@pytest.fixture()
def world(pg_template, monkeypatch):
    admin = _ADMIN.strip()
    name = f"e320_{uuid.uuid4().hex[:12]}"
    if _psql(f"{admin} dbname=postgres", f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES ('{PARTNER["auth_user_id"]}', 'partner@a.in');
            INSERT INTO firms (id, name, email) VALUES ('{FIRM_A}', 'A', 'a@t.in'), ('{FIRM_B}', 'B', 'b@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type)
                 VALUES ('{CLIENT_A}', '{FIRM_A}', 'CA', 'Proprietorship'), ('{CLIENT_B}', '{FIRM_B}', 'CB', 'Proprietorship');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active, cost_rate_paise)
                 VALUES ('{PARTNER["id"]}', '{FIRM_A}', '{PARTNER["auth_user_id"]}', 'partner@a.in', 'P', 'Partner', true, NULL),
                        ('{STAFF_A}', '{FIRM_A}', NULL, 'sa@a.in', 'SA', 'Executive', true, NULL),
                        ('{STAFF_B}', '{FIRM_B}', NULL, 'sb@b.in', 'SB', 'Executive', true, 111);
            INSERT INTO fee_invoices (id, firm_id, client_id, invoice_no, invoice_date, total_paise, status, due_date)
                 VALUES ('{INV_DRAFT}', '{FIRM_A}', '{CLIENT_A}', 'A-1', '2026-01-01', 100000, 'Draft', NULL),
                        ('{INV_OVERDUE}', '{FIRM_A}', '{CLIENT_A}', 'A-2', '2026-01-01', 100000, 'Issued', '2026-02-01'),
                        ('{INV_NOT_DUE}', '{FIRM_A}', '{CLIENT_A}', 'A-3', '2026-09-01', 100000, 'Issued', '2099-12-31'),
                        ('{INV_OTHER_FIRM}', '{FIRM_B}', '{CLIENT_B}', 'B-1', '2026-01-01', 100000, 'Issued', '2026-02-01'),
                        ('{INV_OTHER_FIRM_DRAFT}', '{FIRM_B}', '{CLIENT_B}', 'B-2', '2026-01-01', 100000, 'Draft', NULL);
            -- the invoices a receipt has touched (migration 172: paid_paise moves with the receipts)
            INSERT INTO fee_invoices (id, firm_id, client_id, invoice_no, invoice_date, total_paise, status, due_date, paid_paise)
                 VALUES ('{INV_PAID}', '{FIRM_A}', '{CLIENT_A}', 'A-6', '2026-01-01', 100000, 'Paid', '2026-02-01', 100000),
                        ('{INV_DRAFT_WITH_RECEIPT}', '{FIRM_A}', '{CLIENT_A}', 'A-7', '2026-01-01', 100000, 'Draft', NULL, 5000),
                        ('{INV_PART_PAID}', '{FIRM_A}', '{CLIENT_A}', 'A-8', '2026-01-01', 100000, 'Issued', '2099-12-31', 40000);
        """)
        assert seed.returncode == 0, seed.stderr

        class World:
            pass

        w = World()
        w.dsn = dsn
        w.request = SignedInDb(dsn, auth_user_id=PARTNER["auth_user_id"])
        w.privileged = SignedInDb(dsn, role="service_role")

        import core.db_provider
        import repositories.invoice_repository as invoice_repository
        import services.invoice_lifecycle_service as lifecycle

        monkeypatch.setattr(core.db_provider, "service_db", lambda: w.privileged)
        monkeypatch.setattr(core.db_provider, "service_db_or_none", lambda: w.privileged)
        monkeypatch.setattr(invoice_repository, "_USE_MOCK", False)
        monkeypatch.setattr(invoice_repository, "_get_db", lambda: w.request)
        monkeypatch.setattr(lifecycle, "_notify_overdue", lambda invoice: None)
        import services.billing_service as billing_service
        monkeypatch.setattr(billing_service, "_USE_MOCK", False)
        w.invoice_repository = invoice_repository
        w.lifecycle = lifecycle
        w.billing = billing_service
        yield w
    finally:
        _psql(f"{admin} dbname=postgres", f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _status(w, invoice_id) -> str:
    return _rows(w.dsn, f"SELECT status FROM fee_invoices WHERE id = '{invoice_id}'")[0][0]


def _is_deleted(w, invoice_id) -> bool:
    return _rows(w.dsn, f"SELECT is_deleted FROM fee_invoices WHERE id = '{invoice_id}'")[0][0] == "t"


def _row(w, invoice_id) -> dict:
    status, paid, no = _rows(w.dsn, f"SELECT status, paid_paise, invoice_no FROM fee_invoices WHERE id = '{invoice_id}'")[0]
    return {"id": invoice_id, "status": status, "paid_paise": int(paid), "invoice_no": no}


def _rate(w, user_id):
    value = _rows(w.dsn, f"SELECT coalesce(cost_rate_paise::text, 'NULL') FROM users WHERE id = '{user_id}'")[0][0]
    return None if value == "NULL" else int(value)


# ── the premise, and the defect reproduced ──────────────────────────────────────

def test_the_signed_in_role_cannot_write_either_table_and_a_write_through_it_is_refused(world):
    assert _rows(world.dsn, "SELECT has_table_privilege('authenticated', 'public.fee_invoices', 'UPDATE'), "
                            "has_any_column_privilege('authenticated', 'public.fee_invoices', 'UPDATE'), "
                            "has_column_privilege('authenticated', 'public.users', 'cost_rate_paise', 'UPDATE')") == [["f", "f", "f"]]
    with pytest.raises(SignedInError) as refused:
        world.request.table("fee_invoices").update({"status": "Overdue"}).eq("id", INV_OVERDUE).execute()
    assert refused.value.code == "42501" or "permission denied" in refused.value.message
    with pytest.raises(SignedInError):
        world.request.table("users").update({"cost_rate_paise": 5}).eq("id", STAFF_A).execute()
    assert _status(world, INV_OVERDUE) == "Issued" and _rate(world, STAFF_A) is None


# ── the staff cost rate ─────────────────────────────────────────────────────────

def test_a_cost_rate_is_set_and_cleared_for_a_member_of_the_callers_firm(world):
    out = world.billing.set_staff_cost_rate(FIRM_A, STAFF_A, 80000)
    assert out == {"user_id": STAFF_A, "cost_rate_paise": 80000}, out          # two fields, not the whole users row
    assert _rate(world, STAFF_A) == 80000
    assert world.billing.set_staff_cost_rate(FIRM_A, STAFF_A, None) == {"user_id": STAFF_A, "cost_rate_paise": None}
    assert _rate(world, STAFF_A) is None


def test_a_cost_rate_is_not_set_for_a_member_of_another_firm_or_for_nobody(world):
    with pytest.raises(HTTPException) as other:
        world.billing.set_staff_cost_rate(FIRM_A, STAFF_B, 99999)
    assert other.value.status_code == 404
    assert _rate(world, STAFF_B) == 111                                           # untouched
    with pytest.raises(HTTPException) as nobody:
        world.billing.set_staff_cost_rate(FIRM_A, str(uuid.uuid4()), 5)
    assert nobody.value.status_code == 404


def test_a_negative_cost_rate_is_refused_before_any_write(world):
    with pytest.raises(HTTPException) as bad:
        world.billing.set_staff_cost_rate(FIRM_A, STAFF_A, -1)
    assert bad.value.status_code == 422 and _rate(world, STAFF_A) is None


# ── the overdue check ───────────────────────────────────────────────────────────

def test_the_overdue_check_marks_only_this_firms_issued_invoices_that_are_past_due(world):
    out = world.lifecycle.run_overdue_check(firm_id=FIRM_A)
    assert out == {"transitioned": 1, "invoice_ids": [INV_OVERDUE]}, out
    assert _status(world, INV_OVERDUE) == "Overdue"
    assert _status(world, INV_NOT_DUE) == "Issued"            # not yet due
    assert _status(world, INV_DRAFT) == "Draft"               # a draft is never touched by the check
    assert _status(world, INV_OTHER_FIRM) == "Issued"         # another firm's invoice, though past due


def test_the_firm_wide_nightly_form_marks_each_firms_own_invoices(world, monkeypatch):
    # the scheduler has no sign-in, so its reads and writes are both the privileged client's
    monkeypatch.setattr(world.invoice_repository, "_get_db", lambda: world.privileged)
    out = world.lifecycle.run_overdue_check()
    assert sorted(out["invoice_ids"]) == sorted([INV_OVERDUE, INV_OTHER_FIRM]), out
    assert _status(world, INV_OVERDUE) == "Overdue" and _status(world, INV_OTHER_FIRM) == "Overdue"
    assert _status(world, INV_NOT_DUE) == "Issued"


def test_the_overdue_check_confined_to_one_client_leaves_the_others(world):
    out = world.lifecycle.run_overdue_check(firm_id=FIRM_A, client_id=CLIENT_A)
    assert out["invoice_ids"] == [INV_OVERDUE]
    assert _status(world, INV_OTHER_FIRM) == "Issued"


# ── status, delete ──────────────────────────────────────────────────────────────

def test_a_status_change_and_a_delete_reach_only_the_firms_own_invoice(world):
    repo = world.invoice_repository.invoice_repo
    assert repo.change_status(INV_DRAFT, "Issued", firm_id=FIRM_A)["status"] == "Issued"
    assert _status(world, INV_DRAFT) == "Issued"
    # another firm's invoice named under this firm: the statement names the firm, so nothing matches and nothing changes
    assert repo.change_status(INV_OTHER_FIRM_DRAFT, "Issued", firm_id=FIRM_A) is None
    assert _status(world, INV_OTHER_FIRM_DRAFT) == "Draft"
    assert repo.delete(INV_OTHER_FIRM_DRAFT, firm_id=FIRM_A) is False         # matched nothing, and says so
    assert not _is_deleted(world, INV_OTHER_FIRM_DRAFT)
    assert repo.soft_delete(INV_OTHER_FIRM_DRAFT, firm_id=FIRM_A) is False
    assert not _is_deleted(world, INV_OTHER_FIRM_DRAFT)
    # and its own
    assert repo.delete(INV_NOT_DUE, firm_id=FIRM_A) is True
    assert _is_deleted(world, INV_NOT_DUE)
    assert repo.soft_delete(INV_OVERDUE, firm_id=FIRM_A) is True
    assert _is_deleted(world, INV_OVERDUE)


def test_a_write_with_no_firm_is_refused_before_it_reaches_the_database(world):
    repo = world.invoice_repository.invoice_repo
    for call in (lambda: repo.update(INV_DRAFT, {"notes": "x"}, firm_id=""),
                 lambda: repo.change_status(INV_DRAFT, "Issued", firm_id=None),
                 lambda: repo.delete(INV_DRAFT, firm_id=""),
                 lambda: repo.soft_delete(INV_DRAFT, firm_id=None)):
        with pytest.raises(ValueError):
            call()
    assert _status(world, INV_DRAFT) == "Draft"


def test_the_status_route_refuses_a_bare_paid_and_moves_the_firms_own_invoice(world, monkeypatch):
    import routers.invoices as invoices
    monkeypatch.setattr(invoices, "_assert_invoice_scope", lambda user, invoice_id: _row(world, invoice_id))
    monkeypatch.setattr(invoices, "log_event", lambda *a, **k: None)
    with pytest.raises(HTTPException) as paid:
        invoices.change_invoice_status(INV_OVERDUE, invoices.StatusChangeRequest(new_status="Paid"), current_user=PARTNER)
    assert paid.value.status_code == 422 and "receipt" in paid.value.detail
    assert _status(world, INV_OVERDUE) == "Issued"
    out = invoices.change_invoice_status(INV_DRAFT, invoices.StatusChangeRequest(new_status="Issued"), current_user=PARTNER)
    assert out["data"]["invoice"]["status"] == "Issued" and _status(world, INV_DRAFT) == "Issued"


def test_the_delete_route_deletes_a_draft_of_the_callers_firm(world, monkeypatch):
    import routers.invoices as invoices
    monkeypatch.setattr(invoices, "_assert_invoice_scope", lambda user, invoice_id: _row(world, invoice_id))
    monkeypatch.setattr(invoices, "log_event", lambda *a, **k: None)
    assert invoices.delete_invoice(INV_DRAFT, current_user=PARTNER)["data"] == {"deleted": True}
    assert _is_deleted(world, INV_DRAFT)
    with pytest.raises(HTTPException):                                          # not a draft
        invoices.delete_invoice(INV_OVERDUE, current_user=PARTNER)
    assert not _is_deleted(world, INV_OVERDUE)


def _route_world(world, monkeypatch):
    import routers.invoices as invoices
    monkeypatch.setattr(invoices, "_assert_invoice_scope", lambda user, invoice_id: _row(world, invoice_id))
    monkeypatch.setattr(invoices, "log_event", lambda *a, **k: None)
    return invoices


@pytest.mark.parametrize("invoice,target", [
    (INV_PAID, "Draft"), (INV_PAID, "Issued"), (INV_PAID, "Overdue"),            # nothing moves out of Paid
    (INV_OVERDUE, "Draft"), (INV_NOT_DUE, "Draft"),                             # an issued invoice does not go back to Draft
    (INV_DRAFT, "Overdue"), (INV_DRAFT, "Draft"),                               # a draft is issued first; a move to the same status is no move
    (INV_PART_PAID, "Draft"),                                                   # money received: only Issued <-> Overdue
    (INV_DRAFT_WITH_RECEIPT, "Issued"),                                         # a draft that has receipts is not issued by hand
])
def test_the_status_route_refuses_a_move_that_contradicts_what_the_receipts_say(world, monkeypatch, invoice, target):
    invoices = _route_world(world, monkeypatch)
    before = _row(world, invoice)
    with pytest.raises(HTTPException) as refused:
        invoices.change_invoice_status(invoice, invoices.StatusChangeRequest(new_status=target), current_user=PARTNER)
    assert refused.value.status_code == 422, refused.value.detail
    assert _row(world, invoice) == before, "the refused move changed the invoice"


@pytest.mark.parametrize("invoice,target", [
    (INV_DRAFT, "Issued"), (INV_OVERDUE, "Overdue"), (INV_PART_PAID, "Overdue"),
])
def test_the_status_route_makes_the_moves_a_person_may_make(world, monkeypatch, invoice, target):
    invoices = _route_world(world, monkeypatch)
    out = invoices.change_invoice_status(invoice, invoices.StatusChangeRequest(new_status=target), current_user=PARTNER)
    assert out["data"]["invoice"]["status"] == target and _status(world, invoice) == target


def test_the_status_route_answers_409_when_the_invoice_changed_under_it(world, monkeypatch):
    invoices = _route_world(world, monkeypatch)
    stale = {**_row(world, INV_OVERDUE), "status": "Overdue"}                  # the route read it as Overdue; the database says Issued
    monkeypatch.setattr(invoices, "_assert_invoice_scope", lambda user, invoice_id: stale)
    with pytest.raises(HTTPException) as moved:
        invoices.change_invoice_status(INV_OVERDUE, invoices.StatusChangeRequest(new_status="Issued"), current_user=PARTNER)
    assert moved.value.status_code == 409 and _status(world, INV_OVERDUE) == "Issued"


def test_the_delete_route_refuses_a_draft_that_has_receipts(world, monkeypatch):
    invoices = _route_world(world, monkeypatch)
    with pytest.raises(HTTPException) as refused:
        invoices.delete_invoice(INV_DRAFT_WITH_RECEIPT, current_user=PARTNER)
    assert refused.value.status_code == 400 and "receipts" in refused.value.detail
    assert not _is_deleted(world, INV_DRAFT_WITH_RECEIPT)


def test_a_status_write_conditional_on_the_old_status_changes_nothing_when_the_invoice_has_moved(world):
    repo = world.invoice_repository.invoice_repo
    assert repo.change_status(INV_PAID, "Overdue", firm_id=FIRM_A, only_from="Issued") is None
    assert _status(world, INV_PAID) == "Paid"
    assert repo.change_status(INV_OVERDUE, "Overdue", firm_id=FIRM_A, only_from="Issued")["status"] == "Overdue"


def test_the_overdue_check_does_not_overwrite_an_invoice_a_receipt_covered_since_it_was_read(world, monkeypatch):
    """The sweep reads the invoice as Issued; a receipt then covers it (Paid); the write must not flip it to Overdue."""
    stale = {**_row(world, INV_PAID), "status": "Issued", "firm_id": FIRM_A, "due_date": "2026-02-01"}
    monkeypatch.setattr(world.invoice_repository.invoice_repo, "find_all", lambda **k: [stale])
    out = world.lifecycle.run_overdue_check(firm_id=FIRM_A)
    assert out == {"transitioned": 0, "invoice_ids": []}, out
    assert _status(world, INV_PAID) == "Paid"


# ── the list of cost rates ──────────────────────────────────────────────────────

def test_the_cost_rate_list_is_the_firms_members_and_not_only_the_caller(world, monkeypatch):
    rows = world.billing.list_staff_cost_rates(FIRM_A)
    assert {r["id"] for r in rows} == {PARTNER["id"], STAFF_A}, rows           # the firm's, and not firm B's STAFF_B
    # CONTROL: read as the caller (the previous behaviour) the list is the one row `users` shows a signed-in member
    import core.db_provider
    monkeypatch.setattr(core.db_provider, "service_db", lambda: world.request)
    assert {r["id"] for r in world.billing.list_staff_cost_rates(FIRM_A)} == {PARTNER["id"]}


# ── the control ─────────────────────────────────────────────────────────────────

def test_with_the_requests_own_client_each_write_is_refused_so_these_tests_can_see_the_defect(world, monkeypatch):
    """The previous behaviour: the writers handed the caller's sign-in. Each is refused by the database."""
    import core.db_provider
    monkeypatch.setattr(core.db_provider, "service_db", lambda: world.request)
    repo = world.invoice_repository.invoice_repo
    with pytest.raises(SignedInError):
        repo.change_status(INV_OVERDUE, "Overdue", firm_id=FIRM_A)
    with pytest.raises(SignedInError):
        repo.delete(INV_DRAFT, firm_id=FIRM_A)
    with pytest.raises(SignedInError):
        world.billing.set_staff_cost_rate(FIRM_A, STAFF_A, 5)
    assert _status(world, INV_OVERDUE) == "Issued" and _status(world, INV_DRAFT) == "Draft" and _rate(world, STAFF_A) is None
