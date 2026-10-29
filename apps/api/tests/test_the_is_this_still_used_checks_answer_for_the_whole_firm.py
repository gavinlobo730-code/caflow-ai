"""The "is this code (service) still used?" checks of the HSN library and the service catalogue answer for the WHOLE firm (POST-A-303).

WHAT WAS WRONG
    `routers/firm_hsn_library._find_hsn_usage` (the purge and the bulk delete) and `routers/service_catalogue._find_service_usage`
    (the delete) were handed the CALLER's client, and every table they read is assignment-scoped: the invoice, credit note,
    debit note and bill lines follow documents that are scoped (invoices, credit notes and bills since migration 084, debit notes
    since 370), and the recurring-template lines since 528. So a Manager assigned to some
    clients had the check run over THEIR clients' documents only, and a code (a service) that another client's issued
    invoice still used was reported unused and deleted. The line stores the code as text, so nothing is orphaned; the guard
    exists to keep a used code visible for the audit trail, and a guard that answers for part of the firm is not one.

WHAT THIS HOLDS
    * the purge, the bulk delete and the service delete refuse a code (a service) that a document the caller cannot see
      still uses, because the check is read with the privileged client; the control, run with no privileged client, is the
      caller's own view and deletes it, which is the defect;
    * a code nothing uses is still deleted (the guard is not simply refusing everything), and the ownership lookup stays on the
      CALLER's client (the server double holds no library row and no service row, so a lookup that wandered onto it would answer
      404). The DELETE of a library code is the SERVER's since POST-A-329 (the signed-in role holds no write on `firm_hsn_library`
      and the statement names the firm); a service-catalogue delete is still the caller's;
    * the check counts the firm's own documents only: a line of another firm that carries the same code does not block the
      delete (the filters that keep the privileged read to one firm are the only thing doing that);
    * every call of either check passes `_usage_db(...)` as the client, so the next author cannot hand the caller's client
      straight back in.

Runs in the mock-mode job: no database is needed.
"""
from __future__ import annotations

import ast
import inspect

import pytest

import routers.firm_hsn_library as hsn
import routers.service_catalogue as svc

USER = {"id": "u1", "firm_id": "F1", "role": "Manager"}


class _Query:
    def __init__(self, store, name):
        self._store, self._name, self._filters, self._deleting = store, name, [], False

    def select(self, *_a, **_k):
        return self

    def eq(self, column, value):
        self._filters.append(("eq", column, value))
        return self

    def in_(self, column, values):
        self._filters.append(("in", column, list(values)))
        return self

    def limit(self, *_a, **_k):
        return self

    def delete(self):
        self._deleting = True
        return self

    def execute(self):
        def keep(row):
            for kind, column, value in self._filters:
                if kind == "eq" and row.get(column) != value:
                    return False
                if kind == "in" and row.get(column) not in value:
                    return False
            return True

        rows = [r for r in self._store.rows.get(self._name, []) if keep(r)]
        if self._deleting:
            self._store.deleted.append((self._name, [r["id"] for r in rows]))
            self._store.rows[self._name] = [r for r in self._store.rows.get(self._name, []) if r not in rows]
        return type("R", (), {"data": rows})()


class _Db:
    def __init__(self, rows):
        self.rows, self.deleted = rows, []

    def table(self, name):
        return _Query(self, name)


LIBRARY = {"id": "LIB1", "firm_id": "F1", "hsn_code": "9983"}
# A line of a sales invoice of a client the caller is not assigned to. The parent's firm is a key of its own because the
# check filters on the embedded parent (`client_sales_invoices.firm_id`).
OTHER_CLIENTS_LINE = {"id": "ln1", "hsn_sac": "9983", "client_sales_invoices.firm_id": "F1",
                      "service_catalogue_id": "S1", "sales_invoice_id": "I1"}
OTHER_CLIENTS_INVOICE = {"id": "I1", "status": "issued"}
SERVICE = {"id": "S1", "firm_id": "F1"}


def _wire(monkeypatch, module, *, privileged_sees_the_line: bool, privileged: bool = True, with_use: bool = True):
    """The caller's sign-in sees the library and the service and NO document line; the privileged client sees the line."""
    caller = _Db({"firm_hsn_library": [dict(LIBRARY)], "service_catalogue": [dict(SERVICE)]})
    server_rows: dict = {}        # the library row and the service row are the caller's to find, not the server's
    if privileged_sees_the_line and with_use:
        server_rows["client_sales_invoice_lines"] = [dict(OTHER_CLIENTS_LINE)]
        server_rows["client_sales_invoices"] = [dict(OTHER_CLIENTS_INVOICE)]
    server = _Db(server_rows)
    monkeypatch.setattr(module, "_USE_MOCK", False)
    import core.supabase_client as sc
    monkeypatch.setattr(sc, "get_supabase", lambda: caller)
    monkeypatch.setattr(module.db_provider, "service_db_or_none", lambda: server if privileged else None)
    return caller, server


def test_a_code_another_clients_invoice_uses_cannot_be_purged_by_a_manager_who_cannot_see_that_invoice(monkeypatch):
    caller, server = _wire(monkeypatch, hsn, privileged_sees_the_line=True)
    out = hsn.purge_code("LIB1", current_user=USER)
    assert out["success"] is False and "a sales invoice" in out["error"], out
    assert caller.deleted == [] and server.deleted == [], "the code was deleted"


def test_the_same_purge_read_as_the_caller_deletes_it_which_is_the_defect(monkeypatch):
    """The control: with no privileged client the caller's own view is all there is, and it holds no invoice line."""
    caller, _server = _wire(monkeypatch, hsn, privileged_sees_the_line=True, privileged=False)
    out = hsn.purge_code("LIB1", current_user=USER)
    assert out["success"] is True
    assert caller.deleted == [("firm_hsn_library", ["LIB1"])]


def test_a_code_nothing_uses_is_still_purged_and_the_delete_is_the_servers(monkeypatch):
    caller, server = _wire(monkeypatch, hsn, privileged_sees_the_line=True, with_use=False)
    server.rows["firm_hsn_library"] = [dict(LIBRARY)]   # the delete is the server's, so the server holds the row it removes
    out = hsn.purge_code("LIB1", current_user=USER)
    assert out["success"] is True and server.deleted == [("firm_hsn_library", ["LIB1"])]
    assert caller.deleted == [], "the delete ran on the caller's session, which holds no write on the table (POST-A-329)"


def test_the_bulk_delete_of_an_unused_code_deletes_as_the_server(monkeypatch):
    caller, server = _wire(monkeypatch, hsn, privileged_sees_the_line=True, with_use=False)
    server.rows["firm_hsn_library"] = [dict(LIBRARY)]   # the delete is the server's, so the server holds the row it removes
    out = hsn.bulk_purge_codes(hsn.FirmHsnLibraryBulkDeleteIn(ids=["LIB1"]), current_user=USER)
    assert out["data"]["deleted"] == ["LIB1"] and out["data"]["blocked"] == []
    assert server.deleted == [("firm_hsn_library", ["LIB1"])] and caller.deleted == []


def test_a_line_of_another_firm_with_the_same_code_does_not_block_the_purge(monkeypatch):
    """The privileged client sees every firm's rows, so the check's own firm filters are what keep it to this firm."""
    caller, server = _wire(monkeypatch, hsn, privileged_sees_the_line=True, with_use=False)
    server.rows["client_sales_invoice_lines"] = [{**OTHER_CLIENTS_LINE, "client_sales_invoices.firm_id": "F2"}]
    server.rows["service_catalogue"] = [{"id": "S9", "firm_id": "F2", "hsn_sac": "9983"}]
    server.rows["firm_hsn_library"] = [dict(LIBRARY)]   # the delete is the server's, so the server holds the row it removes
    out = hsn.purge_code("LIB1", current_user=USER)
    assert out["success"] is True, out
    assert server.deleted == [("firm_hsn_library", ["LIB1"])]


def test_the_firms_own_catalogue_entry_with_the_code_still_blocks_the_purge(monkeypatch):
    _caller, server = _wire(monkeypatch, hsn, privileged_sees_the_line=True, with_use=False)
    server.rows["service_catalogue"] = [{"id": "S9", "firm_id": "F1", "hsn_sac": "9983"}]
    out = hsn.purge_code("LIB1", current_user=USER)
    assert out["success"] is False and "Product/Service catalogue" in out["error"], out


def test_the_bulk_delete_blocks_a_used_code_the_caller_cannot_see_used(monkeypatch):
    caller, _server = _wire(monkeypatch, hsn, privileged_sees_the_line=True)
    out = hsn.bulk_purge_codes(hsn.FirmHsnLibraryBulkDeleteIn(ids=["LIB1"]), current_user=USER)
    assert out["success"] is True
    assert out["data"]["deleted"] == [] and [b["id"] for b in out["data"]["blocked"]] == ["LIB1"], out
    assert out["data"]["blocked"][0]["used_in"] == ["a sales invoice"]
    assert caller.deleted == []


def test_a_service_another_clients_issued_invoice_uses_cannot_be_deleted_by_a_manager_who_cannot_see_that_invoice(monkeypatch):
    monkeypatch.setattr(svc, "_assert_service_scope", lambda *_a, **_k: None)     # the scope gate is tested where it lives
    caller, server = _wire(monkeypatch, svc, privileged_sees_the_line=True)
    out = svc.delete_service("S1", current_user=USER)
    assert out["success"] is False and "a sales invoice" in out["error"], out
    assert caller.deleted == [] and server.deleted == []


def test_the_same_service_delete_read_as_the_caller_deletes_it_which_is_the_defect(monkeypatch):
    monkeypatch.setattr(svc, "_assert_service_scope", lambda *_a, **_k: None)
    caller, _server = _wire(monkeypatch, svc, privileged_sees_the_line=True, privileged=False)
    out = svc.delete_service("S1", current_user=USER)
    assert out["success"] is True and caller.deleted == [("service_catalogue", ["S1"])]


def test_a_service_nothing_uses_is_deleted_and_the_delete_is_the_callers(monkeypatch):
    monkeypatch.setattr(svc, "_assert_service_scope", lambda *_a, **_k: None)
    caller, server = _wire(monkeypatch, svc, privileged_sees_the_line=True, with_use=False)
    out = svc.delete_service("S1", current_user=USER)
    assert out["success"] is True and caller.deleted == [("service_catalogue", ["S1"])]
    assert server.deleted == [], "the delete ran with the privileged client"


def test_a_draft_invoice_does_not_block_the_service_delete(monkeypatch):
    """Only an ISSUED document counts, as before: the privileged client changes who is asked, not what the rule is."""
    monkeypatch.setattr(svc, "_assert_service_scope", lambda *_a, **_k: None)
    caller, server = _wire(monkeypatch, svc, privileged_sees_the_line=True)
    server.rows["client_sales_invoices"] = [{"id": "I1", "status": "draft"}]
    out = svc.delete_service("S1", current_user=USER)
    assert out["success"] is True and caller.deleted == [("service_catalogue", ["S1"])]


@pytest.mark.parametrize("module, check", [(hsn, "_find_hsn_usage"), (svc, "_find_service_usage")])
def test_every_call_of_the_usage_check_hands_it_the_usage_client(module, check):
    tree = ast.parse(inspect.getsource(module))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == check]
    assert calls, f"no call of {check}: the rule would pass on nothing"
    for call in calls:
        first = call.args[0]
        assert isinstance(first, ast.Call) and getattr(first.func, "id", "") == "_usage_db", (
            f"{check} is handed the caller's client: " + ast.dump(first)[:120])
