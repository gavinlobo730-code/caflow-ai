"""`@audited(kind, action)` records one audit row when a write route answers success, and nothing otherwise (POST-A-167).

It is the shape a route takes when the table it writes has no row-level audit trigger and the rows are a person's statement: the firm and the
person come from `current_user` (the person by the AUTH id, which is what `audit_log.actor_id` takes), the record's id from the answer or from the
path, the client from the request, and the request as it was sent, kept short. These tests drive the wrapper itself, a real FastAPI route through
a client, and every route in the tree that carries it.
"""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import pytest
from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

import services.audit_service as audit

API = Path(__file__).resolve().parents[1]
USER = {"id": "internal-1", "auth_user_id": "auth-1", "firm_id": "firm-1", "email": "p@firm.test", "role": "Partner"}


@pytest.fixture
def events(monkeypatch):
    seen = []
    monkeypatch.setattr(audit, "log_event", lambda *a, **k: seen.append((a, k)))
    return seen


class Body(BaseModel):
    client_id: str
    note: str
    amount_paise: int = 0


def test_a_success_records_one_row_naming_the_firm_the_person_and_the_request(events):
    @audit.audited("widget", "create")
    def route(body: Body, current_user: dict):
        return {"success": True, "data": {"id": "w-1"}, "error": None}

    route(body=Body(client_id="c-1", note="hello", amount_paise=500), current_user=USER)
    assert len(events) == 1
    (firm, kind, entity_id, action), kw = events[0][0][:4], events[0][1]
    assert (firm, kind, entity_id, action) == ("firm-1", "widget", "w-1", "create")
    assert kw["actor_id"] == "auth-1", "the person is named by the AUTH id, not the internal one"
    assert kw["new_data"] == {"client_id": "c-1", "body": {"client_id": "c-1", "note": "hello", "amount_paise": 500}}
    assert kw["metadata"] == {"recorded_by": "audited"}


def test_an_answer_of_failure_and_a_raised_refusal_record_nothing(events):
    @audit.audited("widget", "create")
    def refuses(current_user: dict):
        return {"success": False, "data": None, "error": "no"}

    @audit.audited("widget", "create")
    def raises(current_user: dict):
        raise HTTPException(422, "no")

    refuses(current_user=USER)
    with pytest.raises(HTTPException):
        raises(current_user=USER)
    assert events == []


def test_the_record_comes_from_the_path_when_the_answer_names_none(events):
    @audit.audited("widget", "update")
    def route(widget_id: str, client_id: str, current_user: dict):
        return {"success": True, "data": {"updated": True}, "error": None}

    route(widget_id="w-9", client_id="c-2", current_user=USER)
    assert events[0][0][2] == "w-9"
    assert events[0][1]["new_data"]["client_id"] == "c-2"


def test_a_long_request_is_kept_short(events):
    @audit.audited("upload", "create")
    def route(xml: str, rows: list, current_user: dict):
        return {"success": True, "data": None, "error": None}

    route(xml="x" * 5000, rows=list(range(500)), current_user=USER)
    kept = events[0][1]["new_data"]
    assert kept["xml"] == {"chars": 5000}, "a pasted file is kept as its length, never its content"
    assert kept["rows"] == {"count": 500}


def test_an_async_route_is_recorded_too(events):
    @audit.audited("widget", "create")
    async def route(current_user: dict):
        return {"success": True, "data": {"id": "w-2"}, "error": None}

    asyncio.run(route(current_user=USER))
    assert events[0][0][2] == "w-2"


def test_a_failed_audit_insert_never_undoes_the_write(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("audit store down")
    monkeypatch.setattr(audit, "log_event", boom)

    @audit.audited("widget", "create")
    def route(current_user: dict):
        return {"success": True, "data": {"id": "w-3"}, "error": None}

    assert route(current_user=USER)["data"]["id"] == "w-3"


def test_a_route_called_through_fastapi_keeps_its_signature_and_records(events):
    router = APIRouter()

    @router.post("/widgets")
    @audit.audited("widget", "create")
    def create(body: Body, user: dict = Depends(lambda: USER)):
        return {"success": True, "data": {"id": "w-4"}, "error": None}

    app = FastAPI()
    app.include_router(router)
    r = TestClient(app).post("/widgets", json={"client_id": "c-3", "note": "n"})
    assert r.status_code == 200, r.text
    assert events and events[0][0][2] == "w-4"
    assert events[0][1]["new_data"]["body"]["note"] == "n"


def test_every_route_that_carries_the_marker_can_name_the_person_and_is_registered_wrapped():
    """The marker goes BELOW the `@router.post(...)` line, or the registered function is the bare one and records nothing; and the route must take
    the signed-in person as `current_user` (or `user`), or there is no one to name."""
    seen = 0
    for path in sorted((API / "routers").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            order = []
            for d in fn.decorator_list:
                if isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id == "audited":
                    order.append("audited")
                elif isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in {"post", "put", "patch", "delete", "get"}:
                    order.append("route")
            if "audited" not in order:
                continue
            seen += 1
            where = f"{path.name}:{fn.name}"
            assert "route" in order and order.index("route") < order.index("audited"), f"{where}: @audited is above the route decorator, so the route registers the unwrapped function"
            params = {a.arg for a in fn.args.args + fn.args.kwonlyargs}
            assert params & {"current_user", "user"}, f"{where}: no current_user to name"
    assert seen >= 80, f"the routers carry {seen} audited routes; the first pass of POST-A-167 marked 91"


# ── what the record keeps and what it leaves out (the second independent review of POST-A-167) ───────────────────────────────────────────

def test_identifiers_of_a_person_are_replaced_at_any_depth_and_the_key_stays(events):
    @audit.audited("widget", "create")
    def route(body: dict, current_user: dict):
        return {"success": True, "data": {"id": "w-1"}, "error": None}

    route(body={"name": "Asha", "pan": "ABCDE1234F", "uan": "123456789012", "bank_account_no": "000123456789", "date_of_birth": None}, current_user=USER)
    kept = events[0][1]["new_data"]["body"]
    assert kept["pan"] == kept["uan"] == kept["bank_account_no"] == audit.REDACTED
    assert kept["date_of_birth"] is None, "an empty field stays empty: 'this was empty' is a fact"
    assert kept["name"] == "Asha"
    nested = audit.redact_identifiers({"a": [{"pan": "ABCDE1234F"}], "b": {"deductee_pan": "x", "ok": 1}})
    assert nested == {"a": [{"pan": audit.REDACTED}], "b": {"deductee_pan": audit.REDACTED, "ok": 1}}


def test_the_redacted_keys_are_the_ones_the_row_level_trigger_redacts():
    """`audit_redact` (migration 336) is the rule for a table's snapshot; this module repeats it for a route's record, so the two are pinned."""
    import re
    sql = (API / "migrations" / "336_the_audit_log_stops_collecting_identifiers.sql").read_text(encoding="utf-8")
    block = sql[sql.index("k_redact CONSTANT text[] := ARRAY["):]
    block = block[:block.index("];")]
    in_sql = set(re.findall(r"'([a-z_0-9]+)'", block))
    assert in_sql, "the key list was not read out of the migration"
    assert set(audit.AUDIT_REDACT_KEYS) == in_sql


def test_a_nested_record_or_a_json_payload_is_kept_as_a_size_never_its_content(events):
    @audit.audited("widget", "create")
    def route(body: dict, current_user: dict):
        return {"success": True, "data": {"id": "w-1"}, "error": None}

    route(body={"json_payload": {"personal_info": {"pan": "ABCDE1234F"}}, "rows": [{"a": 1}], "note": "short"}, current_user=USER)
    kept = events[0][1]["new_data"]["body"]
    assert kept["json_payload"] == {"keys": 1} and kept["rows"] == {"count": 1} and kept["note"] == "short"


def test_a_preview_or_a_dry_run_writes_nothing_and_so_records_nothing(events):
    @audit.audited("widget", "create")
    def route(body: Body, current_user: dict, preview: bool = False):
        return {"success": True, "data": {"id": "w"}, "error": None}

    route(body=Body(client_id="c", note="n"), preview=True, current_user=USER)
    assert events == []
    route(body=Body(client_id="c", note="n"), current_user=USER)
    assert len(events) == 1


def test_a_route_can_say_its_success_changed_nothing(events):
    @audit.audited("widget", "apply", wrote=lambda d: bool(d.get("applied")))
    def route(current_user: dict):
        return {"success": True, "data": {"applied": 0}, "error": None}

    route(current_user=USER)
    assert events == []


def test_the_record_id_comes_from_where_the_route_says_the_answer_carries_it(events):
    @audit.audited("loan", "create", id_in=("loan_id",))
    def route(employee_id: str, current_user: dict):
        return {"success": True, "data": {"employee_id": employee_id, "loan_id": "L-7"}, "error": None}

    @audit.audited("filing", "create", id_in=("filing.id",))
    def nested(run_id: str, current_user: dict):
        return {"success": True, "data": {"run_id": run_id, "filing": {"id": "F-3"}}, "error": None}

    route(employee_id="E-1", current_user=USER)
    nested(run_id="R-1", current_user=USER)
    assert [e[0][2] for e in events] == ["L-7", "F-3"]


def test_a_cleared_field_shows_as_cleared_and_a_default_the_caller_never_sent_does_not_appear(events):
    class Patch(BaseModel):
        note: str | None = None
        amount_paise: int = 0

    @audit.audited("widget", "update")
    def route(widget_id: str, body: Patch, current_user: dict):
        return {"success": True, "data": {"updated": True}, "error": None}

    route(widget_id="w-1", body=Patch(note=None), current_user=USER)
    assert events[0][1]["new_data"]["body"] == {"note": None}


def test_a_body_field_never_overwrites_a_path_parameter_of_the_same_name(events):
    class Patch(BaseModel):
        widget_id: str

    @audit.audited("widget", "update")
    def route(widget_id: str, body: Patch, current_user: dict):
        return {"success": True, "data": {"updated": True}, "error": None}

    route(widget_id="from-the-path", body=Patch(widget_id="from-the-body"), current_user=USER)
    kept = events[0][1]["new_data"]
    assert kept["widget_id"] == "from-the-path" and kept["body"]["widget_id"] == "from-the-body"
    assert events[0][0][2] == "from-the-path"



# ── the six routes the wider walk found to be a person's act with no record of who (POST-A-167, 28-11-2026) ──────────────────────────

@pytest.mark.parametrize("module, route, kind, action", [
    ("routers.ai_insights", "ack_insight", "ai_insight", "acknowledge"),
    ("routers.ai_insights", "dis_insight", "ai_insight", "dismiss"),
    ("routers.insights", "update_insight_status", "ai_insight", "status_change"),
    ("routers.task_extras", "remove_dependency", "task", "remove_dependency"),
    ("routers.notifications", "create_notification", "notification", "create"),
    ("routers.form_26as", "mark_26as_uploaded", "form_26as_upload", "mark_uploaded"),
])
def test_the_six_routes_carry_the_marker_on_the_function_the_router_registered(module, route, kind, action):
    """The marker must be on the function FastAPI was given (it goes below the `@router` line), or the route answers without recording."""
    import importlib
    mod = importlib.import_module(module)
    assert getattr(getattr(mod, route), "__audited__", None) == (kind, action)
    registered = [r.endpoint for r in mod.router.routes if getattr(r.endpoint, "__name__", "") == route]
    assert registered and all(getattr(e, "__audited__", None) == (kind, action) for e in registered), f"{module}.{route} is registered without its marker"


def test_removing_a_tasks_dependency_records_the_task_and_the_dependency_and_a_refusal_records_nothing(monkeypatch):
    """Driven through the marker itself: the record names the task (the first path id) and carries the dependency in what was sent."""
    import routers.task_extras as te
    written = []
    monkeypatch.setattr(audit, "log_event", lambda *a, **k: written.append((a, k)))
    monkeypatch.setattr(te.task_repo, "find_by_id", lambda task_id, firm_id=None: {"id": task_id, "firm_id": firm_id, "client_id": None})
    monkeypatch.setattr(te, "_assert_task_scope", lambda user, task: None)
    monkeypatch.setattr(te.task_extras_repo, "remove_dependency", lambda *a, **k: None)
    user = {"firm_id": "F1", "id": "u1", "auth_user_id": "auth-1", "email": "p@f.test", "role": "Partner"}
    assert te.remove_dependency(task_id="T1", dependency_id="D9", current_user=user)["success"] is True
    assert len(written) == 1, written
    args, kwargs = written[0]
    flat = " ".join(map(str, args)) + " " + str(kwargs)
    assert "T1" in flat and "D9" in flat and "auth-1" in flat and "remove_dependency" in flat, flat
    monkeypatch.setattr(te.task_repo, "find_by_id", lambda task_id, firm_id=None: None)
    with pytest.raises(Exception):  # noqa: B017 - the route's own 404
        te.remove_dependency(task_id="T2", dependency_id="D9", current_user=user)
    assert len(written) == 1, "a refused removal was recorded"
