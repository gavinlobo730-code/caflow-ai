"""The retainer tracker raises a real draft invoice (ACC-06, the retainer third).

WHAT WAS WRONG, AND WHY IT WAS NEVER A MISSING FEATURE

`/accounting/retainer` kept retainers, a work checklist and "invoices" in three
localStorage keys. That is how ACC-06 described it, and it understates the
defect: the screen MINTED a document —

  * headed TAX INVOICE, under the firm's own name and GSTIN;
  * numbered `CAF/<year>/NNNN` from a counter over the browser's own list, so
    two devices produce the same number and CGST Rule 46(b)'s "consecutive
    serial number ... unique for a financial year" cannot hold;
  * taxed at a hardcoded CGST 9% + SGST 9%, so it was the wrong tax for any
    client outside the firm's own state, where IGST 18% applies;
  * with a Print button, and "Save Invoice" saving it to localStorage.

A CA could hand that to a client. It existed in no ledger, no GSTR-1 and no
receivable.

AND NONE OF IT NEEDED BUILDING. `billing_schedules` (migration 073) has carried
`arrangement IN ('retainer','one_time','package')` since 2024;
`billing_service.generate_for_schedule` produces a DRAFT invoice per schedule
per period, idempotently, THROUGH THE SALES ENGINE — so GST, place of supply
and the firm's real numbering series are the real ones — and
`api.billing.listSchedules / createSchedule / generate` were already in the
frontend client with no callers.

What was genuinely missing was an UPDATE path: create, list, get, generate and
run, and nothing to change a fee with. A retainer whose fee goes up is the
ordinary case, and without it the only way to record one was a SECOND schedule,
which then bills the client twice.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clean_schedules():
    from services import billing_service
    billing_service.MOCK_BILLING_SCHEDULES.clear()
    yield
    billing_service.MOCK_BILLING_SCHEDULES.clear()


def _make(firm="F1", client="C1", **over):
    from services import billing_service
    data = {"client_id": client, "arrangement": "retainer", "cadence": "monthly",
            "amount_paise": 15_00_000, "gst_rate": 18.0, "service_id": "SVC1",
            "next_run_date": "2026-09-01"}
    data.update(over)
    return billing_service.create_schedule(firm, data, "u1")


# ── the update path that did not exist ──────────────────────────────────────

def test_the_fee_can_be_changed_in_place():
    """Without this the only way to record a rise was a second schedule, which
    then bills the client twice."""
    from services import billing_service
    s = _make()
    out = billing_service.update_schedule("F1", s["id"], {"amount_paise": 20_00_000})
    assert out["amount_paise"] == 20_00_000
    assert len(billing_service.list_schedules("F1")) == 1


def test_the_client_cannot_be_moved():
    """Re-pointing a schedule would re-point every invoice already generated
    against it, and `_find_generated`'s idempotency key is (schedule, period) —
    so the new client's first period would read as already billed."""
    from services import billing_service
    s = _make(client="C1")
    out = billing_service.update_schedule("F1", s["id"], {"client_id": "C2"})
    assert out["client_id"] == "C1"


def test_a_retainer_can_be_paused_and_resumed():
    """`is_active: False` is a real value, not an absent one. A filter on
    truthiness rather than `is not None` would drop it and make pausing
    impossible."""
    from services import billing_service
    s = _make()
    assert billing_service.update_schedule("F1", s["id"], {"is_active": False})["is_active"] is False
    assert billing_service.update_schedule("F1", s["id"], {"is_active": True})["is_active"] is True


def test_a_zero_amount_is_written_not_dropped():
    from services import billing_service
    s = _make()
    assert billing_service.update_schedule("F1", s["id"], {"amount_paise": 0})["amount_paise"] == 0


def test_an_empty_update_leaves_the_row_alone():
    from services import billing_service
    s = _make()
    out = billing_service.update_schedule("F1", s["id"], {})
    assert out["amount_paise"] == s["amount_paise"]


def test_another_firms_schedule_is_not_found():
    """None rather than a silent success, so the router can 404."""
    from services import billing_service
    s = _make(firm="F1")
    assert billing_service.update_schedule("F2", s["id"], {"amount_paise": 1}) is None
    assert billing_service.update_schedule("F1", "no-such-id", {"amount_paise": 1}) is None


# ── the endpoint ────────────────────────────────────────────────────────────

def _client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from core.auth import get_current_user
    import routers.billing as mod

    app = FastAPI()
    app.include_router(mod.router)
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "u1", "firm_id": "F1", "role": "Partner",
        "email": "p@f1.test", "auth_user_id": "auth-partner"}
    return TestClient(app, raise_server_exceptions=False)


def test_the_patch_endpoint_updates():
    s = _make()
    res = _client().patch(f"/api/billing/schedules/{s['id']}", json={"amount_paise": 25_00_000})
    assert res.status_code == 200, res.text
    assert res.json()["data"]["amount_paise"] == 25_00_000


def test_the_patch_endpoint_404s_on_a_missing_schedule():
    res = _client().patch("/api/billing/schedules/nope", json={"amount_paise": 1})
    assert res.status_code == 404, res.text


def test_the_patch_endpoint_refuses_a_bad_cadence():
    s = _make()
    res = _client().patch(f"/api/billing/schedules/{s['id']}", json={"cadence": "fortnightly"})
    assert res.status_code == 422, res.text


def test_the_patch_endpoint_refuses_a_negative_fee():
    s = _make()
    res = _client().patch(f"/api/billing/schedules/{s['id']}", json={"amount_paise": -1})
    assert res.status_code == 422, res.text


def test_the_patch_body_has_no_client_id_field():
    """Not merely ignored downstream — absent from the model, so a caller
    sending one is told rather than silently obeyed in part."""
    from routers.billing import BillingScheduleUpdateIn
    assert "client_id" not in BillingScheduleUpdateIn.model_fields


def test_service_options_answers_a_shape_the_form_can_render():
    res = _client().get("/api/billing/service-options")
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert set(data) == {"internal_client_id", "services"}
    assert isinstance(data["services"], list)


def test_service_options_never_takes_a_client_from_the_caller():
    """The internal client is resolved server-side from the caller's own
    firm_id. A caller-supplied client_id would be a worse endpoint and would
    put the internal-client concept in the browser."""
    import inspect
    from routers import billing
    sig = inspect.signature(billing.service_options)
    assert list(sig.parameters) == ["current_user"]


# ── the database branch, which mock mode cannot reach ───────────────────────
#
# Two negative controls passed the whole suite against a mutated
# `update_schedule`: deleting the UPDATE's own `.eq("firm_id", …)`, and
# neutering the router's `out is None` 404. Both live only on the DB path, and
# the mock branch returns before either. `db` is injectable for exactly this —
# the convention `recurring_invoice_service` states in its own header.

class _FakeQuery:
    def __init__(self, rows, log):
        self._rows, self._log, self._filters = rows, log, {}

    def update(self, fields):
        self._log["fields"] = fields
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def execute(self):
        self._log["filters"] = dict(self._filters)
        matched = [r for r in self._rows
                   if all(r.get(k) == v for k, v in self._filters.items())]
        return type("R", (), {"data": [{**m, **self._log.get("fields", {})} for m in matched]})()


class _FakeDb:
    def __init__(self, rows):
        self.rows, self.log = rows, {}

    def table(self, name):
        assert name == "billing_schedules", name
        return _FakeQuery(self.rows, self.log)


def test_the_database_update_is_filtered_on_the_firm():
    from services import billing_service
    rows = [{"id": "S1", "firm_id": "F1", "client_id": "C1", "amount_paise": 1}]
    db = _FakeDb(rows)
    out = billing_service.update_schedule("F1", "S1", {"amount_paise": 99}, db=db)
    assert out["amount_paise"] == 99
    # The filter itself, not just the outcome — an UPDATE keyed on the id alone
    # would reach another firm's row and this asserts it cannot.
    assert db.log["filters"] == {"id": "S1", "firm_id": "F1"}


def test_the_database_update_finds_nothing_for_another_firm():
    from services import billing_service
    rows = [{"id": "S1", "firm_id": "F1", "client_id": "C1", "amount_paise": 1}]
    assert billing_service.update_schedule("F2", "S1", {"amount_paise": 99},
                                           db=_FakeDb(rows)) is None


def test_the_router_404s_when_the_row_vanishes_between_read_and_write():
    """The second 404 in the handler is not redundant with the first: the row
    can be deleted between `get_schedule` and the UPDATE, and without it the
    caller is told the change succeeded."""
    import unittest.mock as m
    from services import billing_service
    s = _make()
    with m.patch.object(billing_service, "update_schedule", return_value=None):
        res = _client().patch(f"/api/billing/schedules/{s['id']}", json={"amount_paise": 1})
    assert res.status_code == 404, res.text


def test_every_updatable_field_is_a_column_the_create_path_writes():
    """The other end of the schema chain.

    `tests/test_backend_columns_exist_pg.py` checks a write's columns against
    the real schema only when they are written as a dict LITERAL. A PATCH's key
    set is variable, so `update_schedule`'s `.update(fields)` cannot be one —
    it costs a unit of that test's unreadable budget and its columns go
    unchecked.

    So `create_schedule`'s INSERT is a literal (checked against Postgres) and
    this asserts `editable` is a SUBSET of those names. Payload keys are a
    subset of a set verified against the database; the chain closes without
    duplicating anything. Add a field to `editable` that is not a column and
    this fails, in mock mode, with no database needed.
    """
    import ast, inspect, pathlib as _p
    from services import billing_service

    src = _p.Path(inspect.getfile(billing_service)).read_text()
    tree = ast.parse(src)

    def _fn(name):
        return next(n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and n.name == name)

    editable = next(
        {e.value for e in n.value.elts}
        for n in ast.walk(_fn("update_schedule"))
        if isinstance(n, ast.Assign)
        and getattr(n.targets[0], "id", None) == "editable")

    insert_keys = next(
        {k.value for k in call.args[0].keys}
        for call in ast.walk(_fn("create_schedule"))
        if isinstance(call, ast.Call)
        and getattr(call.func, "attr", None) == "insert"
        and call.args and isinstance(call.args[0], ast.Dict))

    assert editable - insert_keys == set(), (
        f"update_schedule can write {sorted(editable - insert_keys)}, which "
        f"create_schedule does not — either it is not a column, or the create "
        f"path is missing it")


def test_a_field_the_table_has_no_column_for_is_not_offered_on_the_patch():
    """`billing_schedules` has no `description` and no `due_date` (migration
    073, unchanged). `BillingScheduleIn` accepts both and create_schedule
    silently drops them — a gap of its own, named here rather than fixed,
    because adding the columns is a migration.

    Offering them on a PATCH would be strictly worse than the gap: PostgREST
    rejects the WHOLE row on an unknown key (PGRST204), so a CA who edited a
    fee and typed a description would have the fee change fail with the
    description, silently."""
    from routers.billing import BillingScheduleUpdateIn
    assert "description" not in BillingScheduleUpdateIn.model_fields
    assert "due_date" not in BillingScheduleUpdateIn.model_fields
