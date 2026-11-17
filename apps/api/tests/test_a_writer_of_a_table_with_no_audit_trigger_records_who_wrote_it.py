"""A route that writes a table the row-level audit trigger does not cover records who wrote it (POST-A-167).

THE PREMISE. Migration 111 attached `trg_audit_capture` with a one-shot loop over the tables that existed that day, and the trigger writes a
row only when a signed-in person is the writer. A freshly migrated database holds 185 firm tables without it. A write the API makes with its
privileged client is audited by `audit_service.log_event` or not at all. The year-end FX revaluation run (which writes `fx_revaluations` and
`fx_adjustments`) and the writers named below called it nowhere; the ledger entries they post are audited by the ledger's own trigger, the
rows that say what the CA chose are not.

WHAT IS HELD. Every route below, read from its own source, reaches `log_event` (directly or through its router's `_audit` helper), and the
helper names the actor by the person's AUTH id, which is what `audit_log.actor_id` takes (`test_the_audit_log_names_one_kind_of_actor`).
The list names what was read and fixed; it is not a census of the other tables, which the ledger names.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

API = Path(__file__).resolve().parents[1]

ROUTES = {
    "fx_revaluation": ["run_revaluation"],
    "cwip": ["create_project", "add_cost", "set_status", "capitalise"],
    "party_credits": ["apply_party_credit"],
    "cost_centres": ["create_cost_centre", "update_cost_centre"],
    "income_tax_worksheets": ["save_worksheet"],
    "ais": ["upload_statement", "save_working", "add_manual_record", "delete_record", "decide_computation_line"],
    "reconciliation": ["resolve_finding"],
    "purchase_cycle": ["create_order", "update_order", "create_receipt", "update_receipt"],
}
CASES = [(m, f) for m, fs in ROUTES.items() for f in fs]


def _fn(module: str, name: str) -> ast.FunctionDef:
    tree = ast.parse((API / "routers" / f"{module}.py").read_text())
    return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)


def _calls(fn: ast.FunctionDef) -> set[str]:
    out = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            out.add(n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", ""))
    return out


@pytest.mark.parametrize("module,name", CASES)
def test_the_route_records_who_wrote(module, name):
    assert _calls(_fn(module, name)) & {"log_event", "_audit"}, f"routers/{module}.py {name}() writes and records nothing"


@pytest.mark.parametrize("module", sorted(ROUTES))
def test_every_audit_call_names_the_actor_by_the_auth_id(module):
    """`log_event(...)` takes the AUTH id as `actor_id`; the internal id belongs to `created_by` columns, not this log."""
    tree = ast.parse((API / "routers" / f"{module}.py").read_text())
    seen = 0
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "log_event":
            seen += 1
            actor = next((k.value for k in n.keywords if k.arg == "actor_id"), None)
            assert actor is not None and 'auth_user_id' in ast.unparse(actor), f"{module}.py:{n.lineno} log_event without the auth id"
    assert seen >= 1


def test_the_rule_can_fail():
    tree = ast.parse("def f(x):\n    return svc.write(x)\n")
    assert not (_calls(tree.body[0]) & {"log_event", "_audit"})


@pytest.fixture
def purchase_cycle_driven(monkeypatch):
    """The purchase cycle's two amend routes, driven for real with the service and the audit log stood in for."""
    import routers.purchase_cycle as pc
    monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.test")
    monkeypatch.setattr(pc, "assert_client_access", lambda user, cid, **k: None)
    monkeypatch.setattr(pc, "_db", lambda: None)
    for name in ("order_of_client", "receipt_of_client"):
        monkeypatch.setattr(pc.svc, name, lambda *a, **k: None)
    monkeypatch.setattr(pc.svc, "update_order", lambda db, firm, oid, patch: {"id": oid})
    monkeypatch.setattr(pc.svc, "update_receipt", lambda db, firm, rid, patch: {"id": rid})
    events = []
    monkeypatch.setattr(pc, "log_event", lambda *a, **k: events.append(k["new_data"]))
    return pc, events


_USER = {"id": "u1", "firm_id": "firm-1", "auth_user_id": "a1", "email": "p@f.test", "role": "Partner"}


def test_an_amended_receipt_records_what_was_changed_and_never_a_field_left_alone_as_cleared(purchase_cycle_driven):
    """`None` means unchanged in these models and the service applies only what is not None, so a receipt whose notes alone were edited
    (or whose objection date was sent as null) must not record its objection dates as null: the stored receipt still carries them."""
    pc, events = purchase_cycle_driven
    pc.update_receipt("r1", pc.GoodsReceiptUpdateIn(notes="checked"), client_id="c1", current_user=_USER)
    pc.update_receipt("r1", pc.GoodsReceiptUpdateIn(notes="again", objection_removed_on=None), client_id="c1", current_user=_USER)
    pc.update_receipt("r1", pc.GoodsReceiptUpdateIn(objection_raised_on="2026-05-02"), client_id="c1", current_user=_USER)
    assert events == [{"client_id": "c1", "notes": "checked"}, {"client_id": "c1", "notes": "again"},
                      {"client_id": "c1", "objection_raised_on": "2026-05-02"}]


def test_an_amended_order_records_what_was_changed(purchase_cycle_driven):
    pc, events = purchase_cycle_driven
    pc.update_order("o1", pc.PurchaseOrderUpdateIn(notes="revised"), client_id="c1", current_user=_USER)
    assert events == [{"client_id": "c1", "notes": "revised"}]
