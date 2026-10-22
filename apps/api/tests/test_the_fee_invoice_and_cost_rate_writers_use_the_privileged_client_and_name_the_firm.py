"""The writers of `fee_invoices` and of a staff cost rate use the privileged client and name the firm (ledger POST-A-320).

THE DEFECT
    The signed-in role holds no UPDATE on `fee_invoices` (migrations 172 and 245) and none on `users.cost_rate_paise`
    (migration 153), so a writer that used the caller's own client was refused with 42501 in production while every double
    accepted it. The real-database half is `test_the_cost_rate_and_the_fee_invoice_writes_use_the_privileged_client_pg.py`; this
    file is the part that runs in the required mock-mode job, so the next writer that reaches for the caller's client on these
    tables fails there and not only in production.

WHAT IS HELD (no database)
    * (source, from the AST of every module of the API, `scripts/` included) the only code that writes `fee_invoices` is
      `InvoiceRepository.create` (INSERT is still granted to the signed-in role, so it stays on the caller's client),
      `update`, `delete` and `soft_delete`; the last three write through `self._writer(firm_id)` and never through the
      caller's client; and a query kept in a variable, a table name held in a constant, `from_` or SQL text cannot carry a
      write past the scan;
    * every caller of the repository's write methods names the firm, because the privileged client carries no row security;
    * `set_staff_cost_rate` writes `users` through `db_provider.service_db()`;
    * driven through a request client that REFUSES the writes the way `authenticated` does, every write still lands, on the
      privileged client, and names the firm; a write with no firm is refused before it reaches any client;
    * the status route refuses a bare 'Paid' and says to record a receipt, makes only the moves a person may make (Draft ->
      Issued, Issued <-> Overdue), refuses any other once money has been received, and writes conditionally on the status it
      read; the delete route refuses a draft that has receipts; and both the delete and the cost-rate route record an audit
      row, because the privileged client has no sign-in and the database's own audit trigger records nothing for it;
    * `list_staff_cost_rates` reads `users` through the privileged client too (it is the same table, and `users` shows a
      signed-in caller their own row only).
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fastapi import HTTPException

import core.db_provider
import repositories.invoice_repository as invoice_repository
import services.billing_service as billing_service
from tests._table_uses import WRITE_VERBS, sources, uses

API_ROOT = Path(__file__).resolve().parents[1]
REPO = "repositories/invoice_repository.py"
WRITERS = {"create", "update", "delete", "soft_delete"}
FIRM = "firm-320"


def test_only_the_repository_writes_fee_invoices_and_the_updates_go_through_the_firm_checked_writer():
    found, hidden = {}, []
    for rel, text in sources():
        if "fee_invoices" not in text:
            continue
        for kind, fn, line, receiver, _verbs in uses(text, "fee_invoices"):
            if kind == "write":
                # EVERY write of a function, not the last one: a second statement placed before the checked one must be seen
                found.setdefault(rel, {}).setdefault(fn, []).append(ast.unparse(receiver))
            elif kind in {"unchained", "named", "raw_write"}:
                hidden.append((rel, line, kind))
    assert not hidden, f"these places name fee_invoices in a way the guard cannot read: {hidden}"
    assert set(found) == {REPO}, sorted(found)
    assert set(found[REPO]) == WRITERS, found[REPO]
    assert found[REPO]["create"] == ["_get_db()"]                    # INSERT is still granted to the signed-in role
    for fn in ("update", "delete", "soft_delete"):
        assert found[REPO][fn] == ["self._writer(firm_id)"], (fn, found[REPO][fn])


def test_the_writer_helper_hands_out_the_privileged_client_and_refuses_a_missing_firm(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(core.db_provider, "service_db", lambda: sentinel)
    assert invoice_repository.InvoiceRepository._writer(FIRM) is sentinel
    for no_firm in ("", None):
        with pytest.raises(ValueError):
            invoice_repository.InvoiceRepository._writer(no_firm)


def test_every_caller_of_a_repository_write_names_the_firm():
    seen = 0
    for rel, text in sources():
        if "invoice_repo" not in text and "InvoiceRepository" not in text:
            continue
        for node in ast.walk(ast.parse(text)):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in {"update", "change_status", "delete", "soft_delete"}):
                continue
            receiver = ast.unparse(node.func.value)
            if receiver not in {"invoice_repo", "self"} or (receiver == "self" and rel != REPO):
                continue
            if rel == REPO and receiver == "self" and node.func.attr not in {"update"}:
                continue
            seen += 1
            assert any(k.arg == "firm_id" for k in node.keywords), f"{rel}:{node.lineno} {receiver}.{node.func.attr}(...) names no firm"
    assert seen >= 5, seen                                           # the walk found the callers: a vacuous pass would find none


def test_the_cost_rate_is_written_through_the_privileged_client():
    tree = ast.parse((API_ROOT / "services" / "billing_service.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "set_staff_cost_rate")
    users_writes = []
    for call in ast.walk(fn):
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == "table" \
                and call.args and isinstance(call.args[0], ast.Constant) and call.args[0].value == "users":
            users_writes.append(ast.unparse(call.func.value))
    assert users_writes == ["db_provider.service_db()"], users_writes


# ── driven through a request client that refuses the writes ──────────────────────

class _Refusing:
    """Stands in for the caller's sign-in: any write to a table the signed-in role cannot write raises as the database does."""

    def __init__(self, tables):
        self.tables, self.attempts = set(tables), []

    def table(self, name):
        owner = self

        class Q:
            def __getattr__(self, attr):
                if attr in WRITE_VERBS and name in owner.tables:
                    owner.attempts.append((name, attr))
                    raise RuntimeError(f"permission denied for table {name}")
                return lambda *a, **k: self
        return Q()


class _Recording:
    """The privileged client: records each statement with the filters it carried and answers one matching row."""

    def __init__(self):
        self.log = []

    def table(self, name):
        owner = self

        class Q:
            def __init__(self):
                self.verb, self.payload, self.filters = "select", None, []

            def update(self, payload):
                self.verb, self.payload = "update", payload
                return self

            def eq(self, column, value):
                self.filters.append((column, value))
                return self

            def execute(self):
                owner.log.append({"table": name, "verb": self.verb, "payload": self.payload, "filters": dict(self.filters)})

                class R:
                    data = [{"id": dict(self.filters).get("id"), "status": (self.payload or {}).get("status"),
                             "cost_rate_paise": (self.payload or {}).get("cost_rate_paise")}]
                return R()
        return Q()


@pytest.fixture()
def clients(monkeypatch):
    refusing, privileged = _Refusing({"fee_invoices", "users"}), _Recording()
    monkeypatch.setattr(core.db_provider, "service_db", lambda: privileged)
    monkeypatch.setattr(core.db_provider, "request_db", lambda: refusing)
    monkeypatch.setattr(invoice_repository, "_get_db", lambda: refusing)
    monkeypatch.setattr(invoice_repository, "_USE_MOCK", False)
    monkeypatch.setattr(billing_service, "_USE_MOCK", False)
    return refusing, privileged


def test_each_write_lands_on_the_privileged_client_and_names_the_firm(clients):
    refusing, privileged = clients
    repo = invoice_repository.invoice_repo
    repo.change_status("inv-1", "Overdue", firm_id=FIRM)
    repo.update("inv-2", {"notes": "x"}, firm_id=FIRM)
    repo.delete("inv-3", firm_id=FIRM)
    repo.soft_delete("inv-4", firm_id=FIRM)
    out = billing_service.set_staff_cost_rate(FIRM, "user-1", 80000)
    assert out == {"user_id": "user-1", "cost_rate_paise": 80000}
    assert refusing.attempts == []                                    # nothing was attempted on the caller's client
    assert [(e["table"], e["verb"]) for e in privileged.log] == [("fee_invoices", "update")] * 4 + [("users", "update")]
    for entry in privileged.log:
        assert entry["filters"].get("firm_id") == FIRM, entry          # the privileged client has no row security: the statement names the firm
        assert entry["filters"].get("id"), entry


def test_a_write_with_no_firm_reaches_no_client(clients):
    refusing, privileged = clients
    repo = invoice_repository.invoice_repo
    for call in (lambda: repo.change_status("inv-1", "Overdue", firm_id=""),
                 lambda: repo.update("inv-1", {}, firm_id=None),
                 lambda: repo.delete("inv-1", firm_id=""),
                 lambda: repo.soft_delete("inv-1", firm_id=None)):
        with pytest.raises(ValueError):
            call()
    assert privileged.log == [] and refusing.attempts == []


def test_the_status_route_refuses_a_bare_paid_and_asks_for_a_receipt(monkeypatch):
    import routers.invoices as invoices
    monkeypatch.setattr(invoices, "_assert_invoice_scope", lambda user, invoice_id: {"id": invoice_id, "status": "Draft", "paid_paise": 0})
    calls = []
    monkeypatch.setattr(invoices.invoice_repo, "change_status", lambda *a, **k: calls.append((a, k)) or {"id": a[0], "status": a[1]})
    monkeypatch.setattr(invoices, "log_event", lambda *a, **k: None)
    user = {"firm_id": FIRM, "id": "u1", "auth_user_id": "a1", "email": "p@t.in", "role": "Partner"}
    with pytest.raises(HTTPException) as refused:
        invoices.change_invoice_status("inv-1", invoices.StatusChangeRequest(new_status="Paid"), current_user=user)
    assert refused.value.status_code == 422 and "receipt" in refused.value.detail and calls == []
    invoices.change_invoice_status("inv-1", invoices.StatusChangeRequest(new_status="Issued"), current_user=user)
    assert calls == [(("inv-1", "Issued"), {"firm_id": FIRM, "only_from": "Draft"})], calls


# ── the rules the review added ───────────────────────────────────────────────────

def _route_user():
    return {"firm_id": FIRM, "id": "u1", "auth_user_id": "a1", "email": "p@t.in", "role": "Partner"}


def _status_route(monkeypatch, invoice, written=None):
    import routers.invoices as invoices
    monkeypatch.setattr(invoices, "_assert_invoice_scope", lambda user, invoice_id: dict(invoice))
    logged = []
    monkeypatch.setattr(invoices, "log_event", lambda *a, **k: logged.append((a, k)))
    monkeypatch.setattr(invoices.invoice_repo, "change_status",
                        lambda iid, status, **k: (written.append((iid, status, k)) if written is not None else None) or {"id": iid, "status": status})
    return invoices, logged


@pytest.mark.parametrize("current,target,paid", [
    ("Draft", "Issued", 0), ("Issued", "Overdue", 0), ("Overdue", "Issued", 0), ("Issued", "Overdue", 40000), ("Overdue", "Issued", 40000),
])
def test_a_status_move_a_person_may_make_is_made_and_conditional_on_the_status_it_read(monkeypatch, current, target, paid):
    written = []
    invoices, logged = _status_route(monkeypatch, {"id": "inv-1", "status": current, "paid_paise": paid}, written)
    invoices.change_invoice_status("inv-1", invoices.StatusChangeRequest(new_status=target), current_user=_route_user())
    assert written == [("inv-1", target, {"firm_id": FIRM, "only_from": current})], written
    assert [a[3] for a, _k in logged] == ["status_change"]


@pytest.mark.parametrize("current,target,paid", [
    ("Paid", "Draft", 100000), ("Paid", "Issued", 100000), ("Paid", "Overdue", 100000), ("Paid", "Paid", 100000),
    ("Paid", "Draft", 0), ("Paid", "Issued", 0),         # a Paid row that carries no paid amount (old data) is still not moved on
    ("Issued", "Draft", 0), ("Overdue", "Draft", 0), ("Draft", "Overdue", 0), ("Draft", "Draft", 0),
    ("Issued", "Draft", 40000), ("Draft", "Issued", 5000), ("Issued", "Issued", 0),
    ("Cancelled", "Issued", 0),
])
def test_a_status_move_the_receipts_contradict_is_refused_and_writes_nothing(monkeypatch, current, target, paid):
    written = []
    invoices, logged = _status_route(monkeypatch, {"id": "inv-1", "status": current, "paid_paise": paid}, written)
    with pytest.raises(HTTPException) as refused:
        invoices.change_invoice_status("inv-1", invoices.StatusChangeRequest(new_status=target), current_user=_route_user())
    assert refused.value.status_code == 422 and written == [] and logged == [], (refused.value.detail, written)


def test_a_status_write_that_matched_nothing_is_a_409_and_not_a_success(monkeypatch):
    import routers.invoices as invoices
    monkeypatch.setattr(invoices, "_assert_invoice_scope", lambda user, invoice_id: {"id": invoice_id, "status": "Issued", "paid_paise": 0})
    monkeypatch.setattr(invoices.invoice_repo, "change_status", lambda *a, **k: None)
    logged = []
    monkeypatch.setattr(invoices, "log_event", lambda *a, **k: logged.append(a))
    with pytest.raises(HTTPException) as moved:
        invoices.change_invoice_status("inv-1", invoices.StatusChangeRequest(new_status="Overdue"), current_user=_route_user())
    assert moved.value.status_code == 409 and logged == []


def _delete_route(monkeypatch, invoice, deleted=True):
    import routers.invoices as invoices
    monkeypatch.setattr(invoices, "_assert_invoice_scope", lambda user, invoice_id: dict(invoice))
    calls, logged = [], []
    monkeypatch.setattr(invoices.invoice_repo, "delete", lambda iid, **k: calls.append((iid, k)) or deleted)
    monkeypatch.setattr(invoices, "log_event", lambda *a, **k: logged.append((a, k)))
    return invoices, calls, logged


def test_a_draft_without_receipts_is_deleted_and_the_delete_is_recorded(monkeypatch):
    invoices, calls, logged = _delete_route(monkeypatch, {"id": "inv-1", "status": "Draft", "paid_paise": 0, "invoice_no": "A-1"})
    assert invoices.delete_invoice("inv-1", current_user=_route_user())["data"] == {"deleted": True}
    assert calls == [("inv-1", {"firm_id": FIRM})]
    (args, kwargs), = logged
    assert args[:4] == (FIRM, "invoice", "inv-1", "delete") and kwargs["actor_id"] == "a1" and kwargs["old_data"]["invoice_no"] == "A-1"


@pytest.mark.parametrize("invoice", [
    {"status": "Draft", "paid_paise": 5000},          # a draft that has receipts: deleting it would orphan them
    {"status": "Issued", "paid_paise": 0},
    {"status": "Paid", "paid_paise": 100000},
])
def test_an_invoice_that_is_not_a_receipt_free_draft_is_not_deleted(monkeypatch, invoice):
    invoices, calls, logged = _delete_route(monkeypatch, {"id": "inv-1", **invoice})
    with pytest.raises(HTTPException) as refused:
        invoices.delete_invoice("inv-1", current_user=_route_user())
    assert refused.value.status_code == 400 and calls == [] and logged == []


def test_a_delete_that_matched_nothing_is_a_404_and_is_not_recorded(monkeypatch):
    invoices, calls, logged = _delete_route(monkeypatch, {"id": "inv-1", "status": "Draft", "paid_paise": 0}, deleted=False)
    with pytest.raises(HTTPException) as gone:
        invoices.delete_invoice("inv-1", current_user=_route_user())
    assert gone.value.status_code == 404 and logged == []


def test_the_cost_rate_route_records_that_a_rate_was_set_and_not_the_rate(monkeypatch):
    import routers.billing as billing
    monkeypatch.setattr(billing.billing_service, "set_staff_cost_rate", lambda firm, user, rate: {"user_id": user, "cost_rate_paise": rate})
    logged = []
    monkeypatch.setattr(billing, "log_event", lambda *a, **k: logged.append((a, k)))
    out = billing.set_staff_cost_rate("user-9", billing.StaffCostRateIn(cost_rate_paise=80000), current_user=_route_user())
    assert out["data"] == {"user_id": "user-9", "cost_rate_paise": 80000}
    (args, kwargs), = logged
    assert args[:4] == (FIRM, "user", "user-9", "cost_rate_set") and kwargs["actor_id"] == "a1"
    assert "80000" not in repr(kwargs), kwargs


def test_the_cost_rate_list_reads_users_through_the_privileged_client():
    tree = ast.parse((API_ROOT / "services" / "billing_service.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "list_staff_cost_rates")
    receivers = [ast.unparse(c.func.value) for c in ast.walk(fn) if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                 and c.func.attr == "table" and c.args and isinstance(c.args[0], ast.Constant) and c.args[0].value == "users"]
    assert receivers == ["db_provider.service_db()"], receivers
