"""The writers of a document header's settlement and status columns move to the privileged client, one slice at a time (ledger POST-A-331).

THE DEFECT
    The headers of an invoice, a bill and the four notes carry the columns that say what has been settled against a document,
    what state it is in and which journal entry it posted, and about a dozen API paths write them AS THE CALLER, so no database
    rule that asks who is writing can tell the API's own settlement from a member's direct PostgREST call (a member holding the
    accounting tier can mark an invoice paid or cancel it over PostgREST today). The way out is the order migrations 535 and 536
    used: the writers move to the privileged client first, behind the checks their routes already make, and a later migration
    takes the signed-in role's write away. `services/document_header_writer.py` is the door a moved writer goes through; this
    file holds which writers have gone through it and which have not, so the list only shrinks.

WHAT IS HELD (no database)
    * (source, from the AST of every module of the API) every UPDATE of one of the six header tables whose literal payload names
      a settlement or status column is either in `MOVED` (it calls `update_header` and writes nothing directly) or in
      `NOT_YET_MOVED`, and both lists are exact: a new writer on the caller's client fails here, and a writer that moved but
      stayed on the list fails here too, so the list is cleaned in the change that moves it;
    * an UPDATE whose payload the scan cannot read (a request model or a variable) is on `PAYLOAD_NOT_VISIBLE`, each with the
      reason it is not a settlement write, and the list is exact as well;
    * the three writers that reach a header through a table name held in a variable are named by hand and checked to exist;
    * every call to `update_header` names the firm, the client and the actor, and a literal table that is one of the six;
    * `update_header` refuses an unknown table and a missing document, firm or client before anything is sent, names the
      document, the firm and the client on the statement, adds the guard as a filter, runs on the privileged client where
      there is one and on the caller's own where there is none, and writes its audit row only when the statement changed a row.

WHAT IS HELD (driven through the real routes on the e2e double)
    For each of the four notes, with a request client that REFUSES every write to the six tables the way the signed-in role will
    once the migration lands, and a privileged client that records the statement it receives: issuing the note still succeeds;
    every write to a header comes from the privileged client, names the document, the firm and the client, and carries the
    compare-and-set guard on the column it moves; the audit row of each change exists with the actor, what was replaced and
    what was written; a posting that fails after the application rolls the document back through the same door with a reason
    in the audit row; and an application that cannot be recorded does the same.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

import core.supabase_client as sc
import services.document_header_writer as door
from tests._table_uses import WRITE_VERBS, sources
from tests.e2e_harness import FakeDB, _Query, seed_standard_coa, wire_e2e

API_ROOT = Path(__file__).resolve().parents[1]
DOOR = "services/document_header_writer.py"
HEADER_TABLES = set(door.HEADER_TABLES)
#: The seven tables a document's settlement is derived from (ledger POST-A-336, migration 559). The request's client refuses their writes
#: too, so every flow below proves the receipt, vendor payment, re-allocation, reversal and note-application writers are on the
#: privileged client.
SETTLEMENT_TABLES = {"receipts", "receipt_allocations", "purchase_payments", "purchase_payment_allocations",
                     "debit_note_allocations", "sales_debit_note_allocations", "purchase_credit_note_allocations"}
REFUSED_TABLES = HEADER_TABLES | SETTLEMENT_TABLES

#: The columns that say what has been settled against a document, what state it is in and which journal entry it posted.
SETTLEMENT = {
    "status", "paid_paise", "paid_txn", "credited_paise", "debited_paise", "debit_note_paise", "credit_note_paise",
    "journal_entry_id", "cancelled_at", "issued_at", "received_at", "applied_paise",
}

#: Functions that write a header through the door and write nothing directly.
MOVED = {
    ("routers/credit_notes.py", "issue_credit_note"),
    ("routers/debit_notes.py", "issue_debit_note"),
    ("routers/purchase_credit_notes.py", "issue_purchase_credit_note"),
    ("routers/sales_debit_notes.py", "issue_sales_debit_note"),
    ("routers/sales_invoices.py", "issue_invoice"),
    ("routers/sales_invoices.py", "cancel_invoice"),
    ("routers/sales_invoices.py", "repost_journal"),
    ("routers/purchase_bills.py", "receive_purchase_bill"),
    ("routers/purchase_bills.py", "cancel_purchase_bill"),
    ("routers/purchase_payments.py", "_claim_bill_outstanding"),
    ("routers/purchase_payments.py", "_rollback_bill_claim"),
    ("routers/purchase_payments.py", "_update_bill_payment_status"),
    ("routers/purchase_payments.py", "_create_foreign_payment"),
    ("routers/receipts.py", "_adjust_invoice_paid"),
    ("services/purchase_payment_service.py", "_adjust_bill_paid"),
    ("services/purchase_payment_service.py", "create_payment_core"),
    ("services/purchase_payment_service.py", "create_foreign_payment_core"),
    ("services/receipt_service.py", "create_receipt_core"),
    ("services/receipt_service.py", "create_foreign_receipt"),
    ("services/reversal_service.py", "_rollback_invoice_paid"),
    ("services/reversal_service.py", "_rollback_bill_paid"),
    ("services/bank_posting_service.py", "_settle_doc"),
    ("services/bank_posting_service.py", "_unsettle"),
    ("services/party_credit_service.py", "apply_credit"),
}

#: The three functions that hand the door a table held in a variable, because one body serves an invoice and a bill: every other call
#: names a literal header table. The door refuses a table that is not one of the six.
TABLE_IN_A_VARIABLE = {
    ("services/bank_posting_service.py", "_settle_doc"),
    ("services/bank_posting_service.py", "_unsettle"),
    ("services/party_credit_service.py", "apply_credit"),
}

#: Functions that take the signed-in person the way the door wants it and are called by others: every caller outside the tests passes
#: it by name, so that the audit row of a settlement made by a reversal or a re-allocation is not written with no actor by omission.
ACTOR_THREADED = {
    "_claim_bill_outstanding", "_rollback_bill_claim", "_update_bill_payment_status", "_adjust_invoice_paid", "_adjust_bill_paid",
    "_rollback_invoice_paid", "_rollback_bill_paid", "reverse_receipt", "reverse_payment", "apply_credit",
}

#: Writers of a settlement or status column with a literal table that are still on the caller's client. SHRINK-ONLY, and EMPTY since the
#: third slice: a new one is a red test, and the change that adds it adds its line here with the reason it is not moved.
NOT_YET_MOVED: set = set()

#: UPDATEs of a header whose payload the scan cannot read, and why none of them is a settlement write. They stay on the
#: caller's client: the signed-in role keeps the right to edit a DRAFT and the soft fields of an issued document (migration 541).
PAYLOAD_NOT_VISIBLE = {
    ("routers/credit_notes.py", "update_credit_note", "credit_notes"): "edit of a draft note's own fields",
    ("routers/debit_notes.py", "update_debit_note", "debit_notes"): "edit of a draft note's own fields",
    ("routers/purchase_credit_notes.py", "update_purchase_credit_note", "purchase_credit_notes"): "edit of a draft note's own fields",
    ("routers/sales_debit_notes.py", "update_sales_debit_note", "sales_debit_notes"): "edit of a draft note's own fields",
    ("routers/purchase_bills.py", "update_purchase_bill", "purchase_bills"): "edit of a draft bill, soft fields of an issued one",
    ("routers/sales_invoices.py", "update_invoice", "client_sales_invoices"): "edit of a draft invoice, soft fields of an issued one",
    ("services/billing_service.py", "_stamp_billing_fields", "client_sales_invoices"): "stamps the billing run on a draft it just made",
    ("services/recurring_invoice_service.py", "_stamp_recurring", "client_sales_invoices"): "stamps the template on a draft it just made",
}

#: Writers of a money column that reach a header through a table the scan cannot read (a variable, a constant, a split chain), named by
#: hand. EMPTY since the fourth slice: the second scan below finds any new one and requires it to be listed here with its reason.
NAMED_BY_HAND: set = set()


def _chain_table(node):
    while isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if node.func.attr in {"table", "from_"} and node.args and isinstance(node.args[0], ast.Constant):
            return node.args[0].value
        node = node.func.value
    return None


def _functions(tree):
    parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}

    def enclosing(node):
        while node in parents:
            node = parents[node]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return node.name
        return "<module>"
    return enclosing


def header_updates():
    """(module, function, table, keys-or-None) of every `.update(...)` chained off a literal header table."""
    out = []
    for rel, text in sources():
        if not any(t in text for t in HEADER_TABLES) or rel == DOOR:   # the door is held by its own test below
            continue
        tree = ast.parse(text)
        enclosing = _functions(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "update"):
                continue
            table = _chain_table(node.func.value)
            if table not in HEADER_TABLES:
                continue
            arg = node.args[0] if node.args else None
            keys = None
            if isinstance(arg, ast.Dict) and all(isinstance(k, ast.Constant) for k in arg.keys):
                keys = {k.value for k in arg.keys}
            out.append((rel, enclosing(node), table, keys))
    return out


def test_every_update_of_a_settlement_column_is_moved_or_on_the_shrink_only_list():
    found = {(m, f, t) for m, f, t, keys in header_updates() if keys is not None and keys & SETTLEMENT}
    assert found == NOT_YET_MOVED, {"new writers": sorted(found - NOT_YET_MOVED), "moved but still listed": sorted(NOT_YET_MOVED - found)}


def test_an_update_the_scan_cannot_read_is_named_with_its_reason_and_the_list_is_exact():
    found = {(m, f, t) for m, f, t, keys in header_updates() if keys is None}
    assert found == set(PAYLOAD_NOT_VISIBLE), {"new": sorted(found - set(PAYLOAD_NOT_VISIBLE)), "gone": sorted(set(PAYLOAD_NOT_VISIBLE) - found)}
    assert all(PAYLOAD_NOT_VISIBLE.values())


def test_the_door_holds_one_literal_chain_per_table_and_each_names_the_document_the_firm_and_the_client():
    """The privileged client has no row security, so these filters are the only confinement the UPDATE has; and the chains are
    literal so the firm-scope reader (which reads a chain only when its table is a literal) reads every one of them."""
    tree = ast.parse((API_ROOT / DOOR).read_text(encoding="utf-8"))
    chains = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "update":
            table = _chain_table(node.func.value)
            assert table is not None, f"{DOOR}:{node.lineno} updates a table the reader cannot read"
            chains.setdefault(table, []).append(node)
    assert set(chains) == HEADER_TABLES and all(len(v) == 1 for v in chains.values()), {k: len(v) for k, v in chains.items()}
    for table, (update,) in chains.items():
        parent = next(n for n in ast.walk(tree) if isinstance(n, ast.Lambda) and update in ast.walk(n))
        filters = set()
        node = parent.body
        while isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "eq":
            filters.add(node.args[0].value)
            node = node.func.value
        assert filters == {"id", "firm_id", "client_id"}, (table, filters)


def test_nothing_else_writes_a_header_directly_in_a_moved_function():
    direct = {(m, f) for m, f, t, keys in header_updates()}
    assert not (direct & MOVED), sorted(direct & MOVED)


def test_a_moved_function_goes_through_the_door_and_calls_it_for_every_move_it_makes():
    expected_calls = {
        "issue_credit_note": 4, "issue_debit_note": 4, "issue_purchase_credit_note": 4, "issue_sales_debit_note": 4,
        "issue_invoice": 1, "cancel_invoice": 1, "repost_journal": 1, "receive_purchase_bill": 3, "cancel_purchase_bill": 1,
        "_claim_bill_outstanding": 1, "_rollback_bill_claim": 1, "_update_bill_payment_status": 1, "_create_foreign_payment": 1,
        "_adjust_invoice_paid": 1, "_adjust_bill_paid": 1, "create_payment_core": 1, "create_foreign_payment_core": 1,
        "create_receipt_core": 1, "create_foreign_receipt": 1, "_rollback_invoice_paid": 1, "_rollback_bill_paid": 1,
        "_settle_doc": 1, "_unsettle": 1, "apply_credit": 1,
    }
    for rel, fn in sorted(MOVED):
        tree = ast.parse((API_ROOT / rel).read_text(encoding="utf-8"))
        node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == fn)
        calls = [c for c in ast.walk(node) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == "update_header"]
        assert len(calls) == expected_calls[fn], (rel, fn, len(calls))


def test_every_caller_of_settle_on_post_passes_the_auth_id_by_name():
    seen = 0
    for rel, text in sources():
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "settle_on_post":
                seen += 1
                keyword = next((k for k in node.keywords if k.arg == "actor_auth_id"), None)
                assert keyword is not None and isinstance(keyword.value, ast.Name), f"{rel}:{node.lineno} settle_on_post(...) passes no auth id by name"
    assert seen >= 2, seen


def test_every_call_to_the_door_names_a_literal_header_table_the_firm_the_client_and_the_actor():
    seen = 0
    for rel, text in sources():
        if "update_header" not in text or rel == DOOR:
            continue
        tree = ast.parse(text)
        enclosing = _functions(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "update_header"):
                continue
            seen += 1
            assert len(node.args) >= 4, f"{rel}:{node.lineno}"
            table = node.args[1]
            if (rel, enclosing(node)) in TABLE_IN_A_VARIABLE:
                assert isinstance(table, ast.Name), f"{rel}:{node.lineno} table"
            else:
                assert isinstance(table, ast.Constant) and table.value in HEADER_TABLES, f"{rel}:{node.lineno} table"
            kws = {k.arg for k in node.keywords}
            assert {"firm_id", "client_id", "actor"} <= kws, f"{rel}:{node.lineno} names {sorted(kws)}"
            actor = next(k.value for k in node.keywords if k.arg == "actor")
            assert isinstance(actor, ast.Name), f"{rel}:{node.lineno} actor is not the person the caller was handed: {ast.unparse(actor)}"
    assert seen >= 38, seen                                           # 16 in the four note routes, 7 in the invoice and bill lifecycle, 12 in the money paths and 3 in the bank and credit paths: a vacuous pass would find none


def test_every_caller_of_an_actor_threaded_function_passes_the_actor_by_name():
    seen = 0
    for rel, text in sources():
        for node in ast.walk(ast.parse(text)):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else None
            if name not in ACTOR_THREADED:
                continue
            seen += 1
            keyword = next((k for k in node.keywords if k.arg == "actor"), None)
            assert keyword is not None, f"{rel}:{node.lineno} {name}(...) passes no actor"
            assert isinstance(keyword.value, ast.Name), f"{rel}:{node.lineno} {name}(...) passes {ast.unparse(keyword.value)}, not the person it was handed"
    assert seen >= 12, seen                                           # the twelve call sites at the time of the third slice


#: Columns only the six header tables carry in this form: a literal payload naming one of them, written through a chain whose table is
#: not a literal (a variable, a constant, a query kept in a variable), is a writer the scan above cannot attribute to a table.
MONEY_COLUMNS = {"paid_paise", "paid_txn", "credited_paise", "debited_paise", "debit_note_paise", "credit_note_paise"}


def writers_with_a_table_the_scan_cannot_read():
    found = set()
    for rel, text in sources():
        if rel == DOOR or not any(c in text for c in MONEY_COLUMNS):
            continue
        tree = ast.parse(text)
        enclosing = _functions(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {"update", "upsert"}):
                continue
            arg = node.args[0] if node.args else None
            if not (isinstance(arg, ast.Dict) and {k.value for k in arg.keys if isinstance(k, ast.Constant)} & MONEY_COLUMNS):
                continue
            if _chain_table(node.func.value) is None:
                found.add((rel, enclosing(node)))
    return found


def test_a_money_column_written_through_a_table_the_scan_cannot_read_is_one_of_the_named_ones():
    """The exact-list guard above reads only a literal table. This one finds the rest: a split chain, a constant, a variable. A new
    writer of that shape is red until it is moved to the door or named here with its reason."""
    assert writers_with_a_table_the_scan_cannot_read() == NAMED_BY_HAND


def test_the_writers_the_scan_cannot_see_are_named_and_still_on_the_caller_s_client():
    assert NAMED_BY_HAND == set(), "a writer named here has not moved: say why, or move it"
    for rel, fn in sorted(NAMED_BY_HAND):
        tree = ast.parse((API_ROOT / rel).read_text(encoding="utf-8"))
        node = next((n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == fn), None)
        assert node is not None, f"{rel}:{fn} is gone: delete its line"
        names = {c.func.id for c in ast.walk(node) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
        assert "update_header" not in names, f"{rel}:{fn} moved: delete its line"


# ── the door itself ──────────────────────────────────────────────────────────────

class _Rec:
    """A client that records each statement chained on it and answers a canned response."""

    def __init__(self, label, log, rows=None):
        self.label, self.log, self.rows = label, log, rows if rows is not None else [{"id": "d1"}]

    def table(self, name):
        owner = self

        class Q:
            def __init__(self):
                self.rec = {"label": owner.label, "table": name, "filters": []}

            def update(self, payload):
                self.rec["verb"], self.rec["payload"] = "update", payload
                return self

            def eq(self, col, val):
                self.rec["filters"].append((col, val))
                return self

            def execute(self):
                owner.log.append(self.rec)
                return type("R", (), {"data": list(owner.rows)})()
        return Q()


@pytest.fixture
def audit(monkeypatch):
    calls = []
    monkeypatch.setattr(door.audit_service, "log_event", lambda *a, **k: calls.append((a, k)))
    return calls


def test_the_door_writes_on_the_privileged_client_names_the_document_firm_and_client_and_the_guard(monkeypatch, audit):
    log = []
    monkeypatch.setattr("core.db_provider.service_db_or_none", lambda: _Rec("privileged", log))
    door.update_header(_Rec("request", log), "purchase_bills", "b1", {"debited_paise": 5, "status": "paid"},
                       firm_id="F", client_id="C", actor={"auth_user_id": "A", "email": "a@x"},
                       expect={"debited_paise": 0}, before={"debited_paise": 0, "status": "received"}, reason="why")
    assert [(r["label"], r["table"], r["verb"]) for r in log] == [("privileged", "purchase_bills", "update")]
    assert log[0]["filters"] == [("id", "b1"), ("firm_id", "F"), ("client_id", "C"), ("debited_paise", 0)]
    (args, kwargs), = audit
    assert args == ("F", "purchase_bill", "b1", "update")
    assert kwargs["actor_id"] == "A" and kwargs["actor_email"] == "a@x"
    assert kwargs["old_data"] == {"debited_paise": 0, "status": "received"}
    assert kwargs["new_data"] == {"debited_paise": 5, "status": "paid"}
    assert kwargs["metadata"] == {"source": "api", "table": "purchase_bills", "reason": "why"}


def test_the_door_falls_back_to_the_callers_own_client_where_there_is_no_other(monkeypatch, audit):
    log = []
    monkeypatch.setattr("core.db_provider.service_db_or_none", lambda: None)
    door.update_header(_Rec("request", log), "credit_notes", "n1", {"status": "issued"}, firm_id="F", client_id="C", actor=None)
    assert [r["label"] for r in log] == ["request"]
    assert door.header_writer(None) is None


def test_the_door_writes_no_audit_row_when_the_guard_matched_nothing(monkeypatch, audit):
    log = []
    monkeypatch.setattr("core.db_provider.service_db_or_none", lambda: _Rec("privileged", log, rows=[]))
    res = door.update_header(_Rec("request", log), "client_sales_invoices", "i1", {"paid_paise": 9}, firm_id="F",
                             client_id="C", actor=None, expect={"paid_paise": 1})
    assert res.data == [] and len(log) == 1 and audit == []


@pytest.mark.parametrize("kwargs", [
    {"table": "journal_entries"}, {"table": "users"}, {"doc_id": ""}, {"doc_id": None}, {"firm_id": ""}, {"firm_id": None},
    {"client_id": ""}, {"client_id": None},
])
def test_the_door_refuses_an_unknown_table_and_a_missing_document_firm_or_client_before_sending_anything(monkeypatch, audit, kwargs):
    log = []
    monkeypatch.setattr("core.db_provider.service_db_or_none", lambda: _Rec("privileged", log))
    args = {"table": "purchase_bills", "doc_id": "d1", "firm_id": "F", "client_id": "C", **kwargs}
    with pytest.raises(ValueError):
        door.update_header(_Rec("request", log), args["table"], args["doc_id"], {"status": "paid"},
                           firm_id=args["firm_id"], client_id=args["client_id"], actor=None)
    assert log == [] and audit == []


def test_a_system_caller_with_no_actor_is_recorded_with_no_actor(monkeypatch, audit):
    monkeypatch.setattr("core.db_provider.service_db_or_none", lambda: _Rec("privileged", []))
    door.update_header(None or _Rec("request", []), "debit_notes", "n1", {"status": "issued"}, firm_id="F", client_id="C", actor=None)
    (_, kwargs), = audit
    assert kwargs["actor_id"] is None and kwargs["actor_email"] is None


# ── the four routes, driven on the e2e double with a request client that refuses the writes ──────────────────

FIRM = "FIRM-331-1"
CALLER = {"firm_id": FIRM, "id": "u1", "auth_user_id": "auth-u1", "email": "ca@f.test", "role": "Partner"}


class _Refusing:
    def __init__(self, query, name, attempts):
        self._q, self._name, self._attempts = query, name, attempts

    def __getattr__(self, attr):
        if attr in WRITE_VERBS:
            self._attempts.append((self._name, attr))
            raise RuntimeError(f"permission denied for table {self._name}")

        def call(*a, **k):
            res = getattr(self._q, attr)(*a, **k)
            return self if res is self._q else res
        return call


class _Client:
    def __init__(self, inner, label, attempts, fail_tables=()):
        self.inner, self.label, self.attempts, self.fail_tables = inner, label, attempts, set(fail_tables)

    def table(self, name):
        q = self.inner.table(name)
        q._label = self.label
        if self.label == "request" and name in REFUSED_TABLES:
            return _Refusing(q, name, self.attempts)
        if name in self.fail_tables:
            return _Refusing(q, name, [])
        return q

    def __getattr__(self, attr):
        return getattr(self.inner, attr)


KINDS = {
    "credit_note": dict(doc="client_sales_invoices", note="credit_notes", col="credited_paise", doc_entity="sales_invoice",
                        note_entity="credit_note", side="customer", allocations="credit_note_allocations", reduces=True),
    "sales_debit_note": dict(doc="client_sales_invoices", note="sales_debit_notes", col="debit_note_paise", doc_entity="sales_invoice",
                             note_entity="sales_debit_note", side="customer", allocations="sales_debit_note_allocations", reduces=False),
    "debit_note": dict(doc="purchase_bills", note="debit_notes", col="debited_paise", doc_entity="purchase_bill",
                       note_entity="debit_note", side="vendor", allocations="debit_note_allocations", reduces=True),
    "purchase_credit_note": dict(doc="purchase_bills", note="purchase_credit_notes", col="credit_note_paise", doc_entity="purchase_bill",
                                 note_entity="purchase_credit_note", side="vendor", allocations="purchase_credit_note_allocations", reduces=False),
}


@pytest.fixture
def world(monkeypatch):
    import routers.credit_notes as cn
    import routers.customers as cu
    import routers.debit_notes as dn
    import routers.purchase_bills as pb
    import routers.purchase_credit_notes as pcn
    import routers.purchase_payments as pp
    import routers.receipts as rc
    import routers.sales_debit_notes as sdn
    import routers.sales_invoices as si
    import routers.vendors as ve
    import services.purchase_payment_service as pps
    import services.receipt_service as rs
    from models.invoices import InvoiceLineIn, PurchaseBillIn, PurchaseBillLineIn, SalesInvoiceIn
    from models.parties import CustomerIn, VendorIn

    db = FakeDB()
    wire_e2e(monkeypatch, db, [cu, ve, si, pb, cn, sdn, pcn, dn, rc, pp, rs, pps])
    db.seed("firms", {"id": FIRM})
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5"})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI", "name": "Services", "kind": "service"})
    line = lambda amount: InvoiceLineIn(description="x", quantity=1, rate_paise=amount, gst_rate_percent=0.0, service_catalogue_id="SVC-1")

    def build(kind: str, doc_total=2_000_000, note_total=100_000):
        spec = KINDS[kind]
        if spec["side"] == "customer":
            party = cu.create_customer(CustomerIn(client_id="CLI", name="Acme", state_code="27"), CALLER)["data"]
            doc = si.create_invoice(SalesInvoiceIn(client_id="CLI", customer_id=party["id"], invoice_date="2026-06-01",
                                                   invoice_no="INV-1", lines=[InvoiceLineIn(
                                                       service_catalogue_id="SVC-1", description="Svc", hsn_sac="9982", quantity=1,
                                                       rate_paise=doc_total, gst_rate_percent=0.0)]), CALLER)["data"]
            si.issue_invoice(doc["id"], CALLER)
        else:
            party = ve.create_vendor(VendorIn(client_id="CLI", name="Acme Supplies", state_code="27"), CALLER)["data"]
            doc = pb.create_purchase_bill(PurchaseBillIn(client_id="CLI", vendor_id=party["id"], bill_date="2026-06-01", bill_no="B-1",
                                                         lines=[PurchaseBillLineIn(service_catalogue_id="SVC-1", description="svc",
                                                                                   rate_paise=doc_total, quantity=1,
                                                                                   gst_rate_percent=0.0)]), CALLER)["data"]
            pb.receive_purchase_bill(doc["id"], CALLER)
        if not spec["reduces"]:
            # a note that increases what is owed leaves a fully paid document partly paid, and a rollback must put it back to paid
            row = db.table(spec["doc"]).select("*").eq("id", doc["id"]).execute().data[0]
            db.table(spec["doc"]).update({"status": "paid", "paid_paise": row.get("net_payable_paise") or row["total_paise"]}).eq("id", doc["id"]).execute()
        if kind == "credit_note":
            made = cn.create_credit_note(cn.CreditNoteIn(client_id="CLI", customer_id=party["id"], sales_invoice_id=doc["id"],
                                                         credit_note_date="2026-06-10", reason="Return", lines=[line(note_total)]), CALLER)
        elif kind == "sales_debit_note":
            made = sdn.create_sales_debit_note(sdn.SalesDebitNoteIn(client_id="CLI", customer_id=party["id"], sales_invoice_id=doc["id"],
                                                                    debit_note_date="2026-06-10", reason="Undercharge",
                                                                    lines=[line(note_total)]), CALLER)
        elif kind == "debit_note":
            made = dn.create_debit_note(dn.DebitNoteIn(client_id="CLI", vendor_id=party["id"], purchase_bill_id=doc["id"],
                                                       debit_note_date="2026-06-10", reason="Overcharge", lines=[line(note_total)]), CALLER)
        else:
            made = pcn.create_purchase_credit_note(pcn.PurchaseCreditNoteIn(client_id="CLI", vendor_id=party["id"], purchase_bill_id=doc["id"],
                                                                            credit_note_date="2026-06-10", reason="Return",
                                                                            lines=[line(note_total)]), CALLER)
        assert made["success"] is True, made
        return doc, made["data"]

    issue = {"credit_note": cn.issue_credit_note, "sales_debit_note": sdn.issue_sales_debit_note,
             "debit_note": dn.issue_debit_note, "purchase_credit_note": pcn.issue_purchase_credit_note}
    journal = {"credit_note": "journal_for_credit_note", "sales_debit_note": "journal_for_sales_debit_note",
               "debit_note": "journal_for_debit_note", "purchase_credit_note": "journal_for_purchase_credit_note"}
    return db, build, issue, journal


@pytest.fixture
def two_clients(monkeypatch, world):
    """From here on the caller's sign-in refuses every write to the six header tables and the privileged client records what it
    is handed. Returns (statements, refused attempts, audit calls, install)."""
    db = world[0]
    statements, attempts, audit_calls = [], [], []
    real_execute = _Query.execute

    def recording_execute(self):
        if self.table in HEADER_TABLES and self._op in WRITE_VERBS and getattr(self, "_label", None):
            statements.append({"label": self._label, "table": self.table, "payload": self._payload, "filters": list(self._filters)})
        return real_execute(self)

    def install(fail_tables=()):
        monkeypatch.setattr(_Query, "execute", recording_execute)
        monkeypatch.setattr(sc, "get_supabase", lambda: _Client(db, "request", attempts, fail_tables))
        monkeypatch.setattr(sc, "get_service_supabase", lambda: _Client(db, "privileged", attempts, fail_tables))
        monkeypatch.setattr("core.db_provider._configured", lambda: True)
        monkeypatch.setattr(door.audit_service, "log_event", lambda *a, **k: audit_calls.append((a, k)))
    return statements, attempts, audit_calls, install


def _row(db, table, row_id):
    return db.table(table).select("*").eq("id", row_id).execute().data[0]


def _filters(statement):
    return {(col, val) for kind, col, val in statement["filters"] if kind == "eq"}


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_issuing_a_note_writes_the_document_and_the_note_as_the_api_names_the_firm_and_the_client_and_audits_both(world, two_clients, kind):
    db, build, issue, _ = world
    statements, attempts, audit_calls, install = two_clients
    spec = KINDS[kind]
    doc, note = build(kind)
    before_status = _row(db, spec["doc"], doc["id"])["status"]
    assert before_status == ("paid" if not spec["reduces"] else before_status)
    install()
    result = issue[kind](note["id"], CALLER)
    assert result["success"] is True, result
    assert attempts == [], f"the caller's own client was asked to write a header: {attempts}"
    writes = [s for s in statements if s["table"] in HEADER_TABLES]
    assert {(s["label"], s["table"]) for s in writes} == {("privileged", spec["doc"]), ("privileged", spec["note"])}
    for s in writes:
        assert {("firm_id", FIRM), ("client_id", "CLI")} <= _filters(s), s
    on_doc = next(s for s in writes if s["table"] == spec["doc"])
    assert ("id", doc["id"]) in _filters(on_doc) and any(c == spec["col"] for _, c, _v in on_doc["filters"]), on_doc
    assert on_doc["payload"][spec["col"]] == 100_000
    assert on_doc["payload"]["status"] == "partially_paid" and _row(db, spec["doc"], doc["id"])["status"] == "partially_paid"
    on_note = next(s for s in writes if s["table"] == spec["note"])
    assert ("id", note["id"]) in _filters(on_note) and on_note["payload"]["status"] == "issued"
    assert on_note["payload"]["applied_paise"] == 100_000
    if kind != "credit_note":                                          # the credit note's header does not carry the journal link
        assert on_note["payload"]["journal_entry_id"] and on_note["payload"]["journal_entry_id"] == _row(db, spec["note"], note["id"])["journal_entry_id"]
    assert _row(db, spec["doc"], doc["id"])[spec["col"]] == 100_000
    assert _row(db, spec["note"], note["id"])["status"] == "issued"
    audited = {(a[1], a[2]): k for a, k in audit_calls if a[3] == "update"}
    assert set(audited) == {(spec["doc_entity"], doc["id"]), (spec["note_entity"], note["id"])}
    for (_entity, _id), k in audited.items():
        assert k["actor_id"] == "auth-u1" and k["actor_email"] == "ca@f.test", k
        assert k["old_data"] is not None and k["new_data"], k
    assert audited[(spec["doc_entity"], doc["id"])]["new_data"][spec["col"]] == 100_000
    assert audited[(spec["doc_entity"], doc["id"])]["old_data"][spec["col"]] == 0
    assert audited[(spec["doc_entity"], doc["id"])]["old_data"]["status"] == before_status
    assert audited[(spec["doc_entity"], doc["id"])]["new_data"]["status"] == "partially_paid"
    assert audited[(spec["note_entity"], note["id"])]["old_data"]["status"] == "draft"
    assert audited[(spec["note_entity"], note["id"])]["new_data"]["status"] == "issued"


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_a_posting_that_fails_rolls_the_document_back_through_the_door_and_says_why(monkeypatch, world, two_clients, kind):
    db, build, issue, journal = world
    statements, attempts, audit_calls, install = two_clients
    spec = KINDS[kind]
    doc, note = build(kind)
    before_status = _row(db, spec["doc"], doc["id"])["status"]
    install()
    from services.phase2_journal_service import phase2_journal_service

    def boom(*a, **k):
        raise RuntimeError("journal down")
    monkeypatch.setattr(phase2_journal_service, journal[kind], boom)
    result = issue[kind](note["id"], CALLER)
    assert result["success"] is False
    assert attempts == []
    assert _row(db, spec["doc"], doc["id"])[spec["col"]] == 0
    assert _row(db, spec["doc"], doc["id"])["status"] == before_status
    assert _row(db, spec["note"], note["id"])["status"] == "draft"
    on_doc = [s for s in statements if s["table"] == spec["doc"]]
    assert [s["payload"][spec["col"]] for s in on_doc] == [100_000, 0], on_doc
    assert [s["payload"]["status"] for s in on_doc] == ["partially_paid", before_status], on_doc
    assert all(s["label"] == "privileged" and {("firm_id", FIRM), ("client_id", "CLI"), ("id", doc["id"])} <= _filters(s) for s in on_doc)
    rolled = [k for a, k in audit_calls if a[1] == spec["doc_entity"] and a[2] == doc["id"]]
    assert len(rolled) == 2, rolled
    assert "reason" not in rolled[0]["metadata"]
    assert "journal could not be posted" in rolled[1]["metadata"]["reason"]
    assert rolled[1]["new_data"][spec["col"]] == 0 and rolled[1]["old_data"][spec["col"]] == 100_000
    assert rolled[1]["new_data"]["status"] == before_status and rolled[1]["old_data"]["status"] == "partially_paid"
    assert all(k["actor_id"] == "auth-u1" and k["actor_email"] == "ca@f.test" for k in rolled), rolled


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_an_application_that_cannot_be_recorded_rolls_the_document_back_through_the_door(world, two_clients, kind):
    db, build, issue, _ = world
    statements, attempts, audit_calls, install = two_clients
    spec = KINDS[kind]
    doc, note = build(kind)
    before_status = _row(db, spec["doc"], doc["id"])["status"]
    install(fail_tables=(spec["allocations"],))
    result = issue[kind](note["id"], CALLER)
    assert result["success"] is False                                 # the route answers its failure in words and does not raise
    assert attempts == []
    assert _row(db, spec["doc"], doc["id"])[spec["col"]] == 0
    assert _row(db, spec["doc"], doc["id"])["status"] == before_status
    on_doc = [s for s in statements if s["table"] == spec["doc"]]
    assert [s["payload"][spec["col"]] for s in on_doc] == [100_000, 0], on_doc
    assert [s["payload"]["status"] for s in on_doc] == ["partially_paid", before_status], on_doc
    assert all(s["label"] == "privileged" for s in on_doc)
    rolled = [k for a, k in audit_calls if a[1] == spec["doc_entity"] and a[2] == doc["id"]]
    assert len(rolled) == 2, rolled
    assert "reason" not in rolled[0]["metadata"] and "could not be recorded" in rolled[1]["metadata"]["reason"], rolled
    assert rolled[1]["new_data"][spec["col"]] == 0 and rolled[1]["old_data"][spec["col"]] == 100_000
    assert rolled[1]["new_data"]["status"] == before_status and rolled[1]["old_data"]["status"] == "partially_paid"
    assert all(k["actor_id"] == "auth-u1" and k["actor_email"] == "ca@f.test" for k in rolled), rolled


# ── the invoice and bill lifecycle: issue, repost, receive, cancel ──────────────────────────────────────────────

def _draft_invoice():
    import routers.customers as cu
    import routers.sales_invoices as si
    from models.invoices import InvoiceLineIn, SalesInvoiceIn
    from models.parties import CustomerIn
    party = cu.create_customer(CustomerIn(client_id="CLI", name="Acme", state_code="27"), CALLER)["data"]
    made = si.create_invoice(SalesInvoiceIn(
        client_id="CLI", customer_id=party["id"], invoice_date="2026-06-01", invoice_no="INV-331-2",
        lines=[InvoiceLineIn(service_catalogue_id="SVC-1", description="Svc", hsn_sac="9982", quantity=1,
                             rate_paise=500_000, gst_rate_percent=0.0)]), CALLER)
    assert made["success"] is True, made
    return si, made["data"]


def _draft_bill():
    import routers.purchase_bills as pb
    import routers.vendors as ve
    from models.invoices import PurchaseBillIn, PurchaseBillLineIn
    from models.parties import VendorIn
    party = ve.create_vendor(VendorIn(client_id="CLI", name="Acme Supplies", state_code="27"), CALLER)["data"]
    made = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id=party["id"], bill_date="2026-06-01", bill_no="B-331-2",
        lines=[PurchaseBillLineIn(service_catalogue_id="SVC-1", description="svc", rate_paise=500_000, quantity=1,
                                  gst_rate_percent=0.0)]), CALLER)
    assert made["success"] is True, made
    return pb, made["data"]


def _header_writes(statements, table):
    return [s for s in statements if s["table"] == table]


def _audited(audit_calls, entity, doc_id):
    return [k for a, k in audit_calls if a[1] == entity and a[2] == doc_id and a[3] == "update"]


def test_issuing_an_invoice_writes_its_header_as_the_api_names_the_firm_and_the_client_and_audits_it(world, two_clients):
    db = world[0]
    statements, attempts, audit_calls, install = two_clients
    si, inv = _draft_invoice()
    install()
    result = si.issue_invoice(inv["id"], CALLER)
    assert result["success"] is True, result
    assert attempts == []
    (write,) = _header_writes(statements, "client_sales_invoices")
    assert write["label"] == "privileged"
    assert {("id", inv["id"]), ("firm_id", FIRM), ("client_id", "CLI")} <= _filters(write)
    assert write["payload"]["status"] == "issued" and write["payload"]["issued_at"] and write["payload"]["journal_entry_id"]
    row = _row(db, "client_sales_invoices", inv["id"])
    assert row["status"] == "issued" and row["journal_entry_id"] == write["payload"]["journal_entry_id"]
    (audit,) = _audited(audit_calls, "sales_invoice", inv["id"])
    assert audit["actor_id"] == "auth-u1" and audit["actor_email"] == "ca@f.test"
    assert audit["old_data"]["status"] == "draft" and audit["new_data"]["status"] == "issued"


def test_cancelling_an_invoice_writes_its_status_as_the_api_and_audits_it(world, two_clients):
    db = world[0]
    statements, attempts, audit_calls, install = two_clients
    si, inv = _draft_invoice()
    assert si.issue_invoice(inv["id"], CALLER)["success"] is True
    install()
    result = si.cancel_invoice(inv["id"], CALLER)
    assert result["success"] is True, result
    assert attempts == []
    (write,) = _header_writes(statements, "client_sales_invoices")
    assert write["label"] == "privileged" and write["payload"] == {"status": "cancelled"}
    assert {("id", inv["id"]), ("firm_id", FIRM), ("client_id", "CLI")} <= _filters(write)
    assert _row(db, "client_sales_invoices", inv["id"])["status"] == "cancelled"
    (audit,) = _audited(audit_calls, "sales_invoice", inv["id"])
    assert audit["old_data"] == {"status": "issued"} and audit["new_data"] == {"status": "cancelled"}
    assert audit["actor_id"] == "auth-u1"


def test_reposting_an_invoice_writes_its_journal_link_as_the_api_and_audits_it(world, two_clients):
    db = world[0]
    statements, attempts, audit_calls, install = two_clients
    si, inv = _draft_invoice()
    assert si.issue_invoice(inv["id"], CALLER)["success"] is True
    db.table("client_sales_invoices").update({"journal_entry_id": None}).eq("id", inv["id"]).execute()
    install()
    result = si.repost_journal(inv["id"], CALLER)
    assert result["success"] is True and result["data"]["already_posted"] is False, result
    assert attempts == []
    (write,) = _header_writes(statements, "client_sales_invoices")
    assert write["label"] == "privileged" and set(write["payload"]) == {"journal_entry_id"} and write["payload"]["journal_entry_id"]
    assert {("id", inv["id"]), ("firm_id", FIRM), ("client_id", "CLI")} <= _filters(write)
    (audit,) = _audited(audit_calls, "sales_invoice", inv["id"])
    assert audit["old_data"] == {"journal_entry_id": None} and audit["new_data"] == write["payload"]


def test_receiving_a_bill_writes_its_status_and_its_journal_link_as_the_api_and_audits_both(world, two_clients):
    db = world[0]
    statements, attempts, audit_calls, install = two_clients
    pb, bill = _draft_bill()
    install()
    result = pb.receive_purchase_bill(bill["id"], CALLER)
    assert result["success"] is True, result
    assert attempts == []
    writes = _header_writes(statements, "purchase_bills")
    assert [set(w["payload"]) for w in writes] == [{"status", "received_at"}, {"journal_entry_id"}]
    assert writes[0]["payload"]["status"] == "received" and writes[1]["payload"]["journal_entry_id"]
    for w in writes:
        assert w["label"] == "privileged" and {("id", bill["id"]), ("firm_id", FIRM), ("client_id", "CLI")} <= _filters(w)
    row = _row(db, "purchase_bills", bill["id"])
    assert row["status"] == "received" and row["journal_entry_id"] == writes[1]["payload"]["journal_entry_id"]
    audits = _audited(audit_calls, "purchase_bill", bill["id"])
    assert [a["new_data"] for a in audits] == [w["payload"] for w in writes]
    assert audits[0]["old_data"]["status"] == "draft" and audits[1]["old_data"] == {"journal_entry_id": None}
    assert all(a["actor_id"] == "auth-u1" and a["actor_email"] == "ca@f.test" for a in audits)


def test_a_bill_whose_journal_cannot_be_posted_goes_back_to_a_draft_through_the_door_and_says_why(monkeypatch, world, two_clients):
    db = world[0]
    statements, attempts, audit_calls, install = two_clients
    pb, bill = _draft_bill()
    install()
    from services.phase2_journal_service import phase2_journal_service

    def boom(*a, **k):
        raise RuntimeError("journal down")
    monkeypatch.setattr(phase2_journal_service, "journal_for_purchase_bill", boom)
    result = pb.receive_purchase_bill(bill["id"], CALLER)
    assert result["success"] is False
    assert attempts == []
    writes = _header_writes(statements, "purchase_bills")
    assert [w["payload"].get("status") for w in writes] == ["received", "draft"], writes
    assert writes[1]["payload"] == {"status": "draft", "received_at": None}
    assert all(w["label"] == "privileged" and {("id", bill["id"]), ("firm_id", FIRM), ("client_id", "CLI")} <= _filters(w) for w in writes)
    assert _row(db, "purchase_bills", bill["id"])["status"] == "draft"
    audits = _audited(audit_calls, "purchase_bill", bill["id"])
    assert len(audits) == 2 and "reason" not in audits[0]["metadata"]
    assert "journal could not be posted" in audits[1]["metadata"]["reason"]
    assert audits[1]["old_data"]["status"] == "received" and audits[1]["new_data"] == {"status": "draft", "received_at": None}
    assert all(a["actor_id"] == "auth-u1" for a in audits)


def test_cancelling_a_bill_writes_its_status_as_the_api_and_audits_it(world, two_clients):
    db = world[0]
    statements, attempts, audit_calls, install = two_clients
    pb, bill = _draft_bill()
    assert pb.receive_purchase_bill(bill["id"], CALLER)["success"] is True
    install()
    result = pb.cancel_purchase_bill(bill["id"], CALLER)
    assert result["success"] is True, result
    assert attempts == []
    (write,) = _header_writes(statements, "purchase_bills")
    assert write["label"] == "privileged" and set(write["payload"]) == {"status", "cancelled_at"} and write["payload"]["status"] == "cancelled"
    assert {("id", bill["id"]), ("firm_id", FIRM), ("client_id", "CLI")} <= _filters(write)
    assert _row(db, "purchase_bills", bill["id"])["status"] == "cancelled"
    (audit,) = _audited(audit_calls, "purchase_bill", bill["id"])
    assert audit["old_data"] == {"status": "received"} and audit["new_data"]["status"] == "cancelled"
    assert audit["actor_id"] == "auth-u1"


# ── the money paths: receipts, vendor payments, re-allocation and reversal ───────────────────────────────────

@pytest.fixture
def foreign(monkeypatch, world):
    """The world with a USD-capable client, so a foreign receipt and a foreign vendor payment can be recorded."""
    db = world[0]
    monkeypatch.setenv("MULTI_CURRENCY_ENABLED", "true")
    db.table("firms").update({"multi_currency_entitled": True}).eq("id", FIRM).execute()
    db.table("clients").update({"functional_currency": "INR", "multi_currency_enabled": True}).eq("id", "CLI").execute()
    db.seed("currencies", {"code": "USD", "symbol": "$", "display_name": "US Dollar", "minor_unit": 2, "is_active": True})
    db.seed("currencies", {"code": "INR", "symbol": "₹", "display_name": "Indian Rupee", "minor_unit": 2, "is_active": True})
    return world


def _issued_invoice(currency="INR", rate=None, total=500_000, no="INV-331-3"):
    import routers.customers as cu
    import routers.sales_invoices as si
    from models.invoices import InvoiceLineIn, SalesInvoiceIn
    from models.parties import CustomerIn
    party = cu.create_customer(CustomerIn(client_id="CLI", name="Acme " + no, state_code="27"), CALLER)["data"]
    extra = {"currency": currency, "exchange_rate": rate} if rate else {}
    inv = si.create_invoice(SalesInvoiceIn(
        client_id="CLI", customer_id=party["id"], invoice_date="2026-06-01", invoice_no=no, **extra,
        lines=[InvoiceLineIn(service_catalogue_id="SVC-1", description="Svc", hsn_sac="9982", quantity=1,
                             rate_paise=total, gst_rate_percent=0.0)]), CALLER)["data"]
    assert si.issue_invoice(inv["id"], CALLER)["success"] is True
    return party, inv


def _received_bill(currency="INR", rate=None, total=500_000, no="B-331-3", vendor=None):
    import routers.purchase_bills as pb
    import routers.vendors as ve
    from models.invoices import PurchaseBillIn, PurchaseBillLineIn
    from models.parties import VendorIn
    party = vendor or ve.create_vendor(VendorIn(client_id="CLI", name="Acme Supplies " + no, state_code="27"), CALLER)["data"]
    extra = {"currency": currency, "exchange_rate": rate} if rate else {}
    bill = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id=party["id"], bill_date="2026-06-01", bill_no=no, **extra,
        lines=[PurchaseBillLineIn(service_catalogue_id="SVC-1", description="svc", rate_paise=total, quantity=1,
                                  gst_rate_percent=0.0)]), CALLER)["data"]
    assert pb.receive_purchase_bill(bill["id"], CALLER)["success"] is True
    return party, bill


def _assert_settlement_write(write, doc_id):
    assert write["label"] == "privileged", write
    assert {("id", doc_id), ("firm_id", FIRM), ("client_id", "CLI")} <= _filters(write), write
    assert any(col == "paid_paise" for _kind, col, _v in write["filters"]), f"no compare-and-set on paid_paise: {write}"


def _assert_audited_like(audit_calls, entity, doc_id, writes, pre):
    """One audit row per write: the actor, what was written, and what was REPLACED, which is what the row held before the first
    write and what the previous write left after it (paid amount, status and, where the write carries it, the foreign amount)."""
    audits = _audited(audit_calls, entity, doc_id)
    assert [a["new_data"] for a in audits] == [w["payload"] for w in writes], (audits, writes)
    assert all(a["actor_id"] == "auth-u1" and a["actor_email"] == "ca@f.test" for a in audits), audits
    state = {"paid_paise": int(pre.get("paid_paise") or 0), "status": pre.get("status"), "paid_txn": int(pre.get("paid_txn") or 0)}
    for audit, write in zip(audits, writes, strict=True):
        old = audit["old_data"]
        assert old["paid_paise"] == state["paid_paise"] and old["status"] == state["status"], (old, state)
        if "paid_txn" in write["payload"]:
            assert old["paid_txn"] == state["paid_txn"], (old, state)
        for column in state:
            if column in write["payload"]:
                state[column] = write["payload"][column]


def test_a_foreign_receipt_settles_its_invoice_as_the_api_names_the_firm_and_the_client_and_audits_it(foreign, two_clients):
    import routers.receipts as rc
    from models.invoices import ReceiptAllocationIn, ReceiptIn
    db = foreign[0]
    statements, attempts, audit_calls, install = two_clients
    party, inv = _issued_invoice("USD", "80.0", 100_000, "USD-INV-3")
    pre = _row(db, "client_sales_invoices", inv["id"])
    install()
    made = rc.create_receipt(ReceiptIn(
        client_id="CLI", customer_id=party["id"], receipt_date="2026-06-10", amount_paise=100_000, currency="USD",
        exchange_rate="83.0", allocations=[ReceiptAllocationIn(sales_invoice_id=inv["id"], allocated_paise=100_000)]), CALLER)
    assert made["success"] is True, made
    assert attempts == []
    (write,) = _header_writes(statements, "client_sales_invoices")
    _assert_settlement_write(write, inv["id"])
    assert set(write["payload"]) == {"paid_paise", "paid_txn", "status"} and write["payload"]["status"] == "paid"
    assert _row(db, "client_sales_invoices", inv["id"])["status"] == "paid"
    _assert_audited_like(audit_calls, "sales_invoice", inv["id"], [write], pre)


def test_a_foreign_vendor_payment_on_one_bill_settles_it_as_the_api_and_audits_it(foreign, two_clients):
    import routers.purchase_payments as pp
    from models.invoices import PurchasePaymentIn
    db = foreign[0]
    statements, attempts, audit_calls, install = two_clients
    party, bill = _received_bill("USD", "80.0", 100_000, "USD-B-3")
    pre = _row(db, "purchase_bills", bill["id"])
    install()
    made = pp.create_purchase_payment(PurchasePaymentIn(
        client_id="CLI", vendor_id=party["id"], payment_date="2026-06-10", amount_paise=100_000,
        purchase_bill_id=bill["id"], currency="USD", exchange_rate="83.0"), CALLER)
    assert made["success"] is True, made
    assert attempts == []
    (write,) = _header_writes(statements, "purchase_bills")
    _assert_settlement_write(write, bill["id"])
    assert set(write["payload"]) == {"paid_paise", "paid_txn", "status"} and write["payload"]["status"] == "paid"
    assert _row(db, "purchase_bills", bill["id"])["status"] == "paid"
    _assert_audited_like(audit_calls, "purchase_bill", bill["id"], [write], pre)


def test_a_foreign_vendor_payment_on_several_bills_settles_each_as_the_api_and_audits_each(foreign, two_clients):
    import services.purchase_payment_service as pps
    statements, attempts, audit_calls, install = two_clients
    party, first = _received_bill("USD", "80.0", 50_000, "USD-B-4")
    _, second = _received_bill("USD", "80.0", 50_000, "USD-B-5", vendor=party)
    pres = [_row(foreign[0], "purchase_bills", first["id"]), _row(foreign[0], "purchase_bills", second["id"])]
    install()
    made = pps.create_payment_core(FIRM, {
        "client_id": "CLI", "vendor_id": party["id"], "payment_date": "2026-06-10", "amount_paise": 100_000,
        "currency": "USD", "exchange_rate": "83.0",
        "allocations": [{"purchase_bill_id": first["id"], "allocated_paise": 50_000},
                        {"purchase_bill_id": second["id"], "allocated_paise": 50_000}]}, CALLER, _Client(foreign[0], "request", attempts))
    assert made
    assert attempts == []
    writes = _header_writes(statements, "purchase_bills")
    assert [w["payload"]["status"] for w in writes] == ["paid", "paid"]
    for write, bill, pre in zip(writes, (first, second), pres, strict=True):
        _assert_settlement_write(write, bill["id"])
        _assert_audited_like(audit_calls, "purchase_bill", bill["id"], [write], pre)


def test_a_domestic_vendor_payment_claims_its_bill_as_the_api_and_audits_the_claim(world, two_clients):
    import routers.purchase_payments as pp
    from models.invoices import PurchasePaymentIn
    db = world[0]
    statements, attempts, audit_calls, install = two_clients
    party, bill = _received_bill(total=500_000, no="B-331-6")
    install()
    made = pp.create_purchase_payment(PurchasePaymentIn(
        client_id="CLI", vendor_id=party["id"], payment_date="2026-06-10", amount_paise=200_000, purchase_bill_id=bill["id"]), CALLER)
    assert made["success"] is True, made
    assert attempts == []
    writes = _header_writes(statements, "purchase_bills")
    assert writes and writes[0]["payload"] == {"paid_paise": 200_000, "status": "partially_paid"}, writes
    for w in writes:
        _assert_settlement_write(w, bill["id"])
    assert _row(db, "purchase_bills", bill["id"])["paid_paise"] == 200_000
    audits = _audited(audit_calls, "purchase_bill", bill["id"])
    assert audits[0]["old_data"] == {"paid_paise": 0, "status": "received"}
    assert audits[0]["new_data"] == {"paid_paise": 200_000, "status": "partially_paid"}
    assert all(a["actor_id"] == "auth-u1" for a in audits)


def test_a_payment_that_cannot_be_recorded_gives_the_claim_back_through_the_door_and_says_why(world, two_clients):
    import routers.purchase_payments as pp
    from models.invoices import PurchasePaymentIn
    db = world[0]
    statements, attempts, audit_calls, install = two_clients
    party, bill = _received_bill(total=500_000, no="B-331-7")
    install(fail_tables=("purchase_payments",))
    made = pp.create_purchase_payment(PurchasePaymentIn(
        client_id="CLI", vendor_id=party["id"], payment_date="2026-06-10", amount_paise=200_000, purchase_bill_id=bill["id"]), CALLER)
    assert not (isinstance(made, dict) and made.get("success") is True), made
    assert attempts == []
    writes = _header_writes(statements, "purchase_bills")
    assert [w["payload"]["paid_paise"] for w in writes][:2] == [200_000, 0], writes
    assert writes[1]["payload"]["status"] == "received" and writes[1]["label"] == "privileged"
    assert _row(db, "purchase_bills", bill["id"])["paid_paise"] == 0
    audits = _audited(audit_calls, "purchase_bill", bill["id"])
    assert "reason" not in audits[0]["metadata"] and "could not be recorded" in audits[1]["metadata"]["reason"]
    assert audits[1]["old_data"] == {"paid_paise": 200_000, "status": "partially_paid"}
    assert audits[1]["new_data"] == {"paid_paise": 0, "status": "received"}
    assert audits[1]["metadata"]["reason"] == "the payment could not be recorded"
    assert all(a["actor_id"] == "auth-u1" and a["actor_email"] == "ca@f.test" for a in audits), audits


def test_re_allocating_a_receipt_adjusts_the_invoice_as_the_api_and_audits_both_moves(world, two_clients):
    import routers.receipts as rc
    from models.invoices import ReceiptAllocationIn, ReceiptAllocationsUpdateIn, ReceiptIn
    db = world[0]
    statements, attempts, audit_calls, install = two_clients
    party, inv = _issued_invoice(total=500_000, no="INV-331-8")
    made = rc.create_receipt(ReceiptIn(
        client_id="CLI", customer_id=party["id"], receipt_date="2026-06-10", amount_paise=200_000,
        allocations=[ReceiptAllocationIn(sales_invoice_id=inv["id"], allocated_paise=200_000)]), CALLER)
    assert made["success"] is True, made
    receipt_id = made["data"]["id"]
    install()
    result = rc.update_allocations(receipt_id, ReceiptAllocationsUpdateIn(
        allocations=[ReceiptAllocationIn(sales_invoice_id=inv["id"], allocated_paise=50_000)]), CALLER)
    assert result["success"] is True, result
    assert attempts == []
    writes = _header_writes(statements, "client_sales_invoices")
    assert [w["payload"]["paid_paise"] for w in writes] == [0, 50_000], writes
    for w in writes:
        _assert_settlement_write(w, inv["id"])
    assert _row(db, "client_sales_invoices", inv["id"])["paid_paise"] == 50_000
    audits = _audited(audit_calls, "sales_invoice", inv["id"])
    assert [(a["old_data"]["paid_paise"], a["old_data"]["status"]) for a in audits] == [(200_000, "partially_paid"), (0, "issued")]
    assert [(a["new_data"]["paid_paise"], a["new_data"]["status"]) for a in audits] == [(0, "issued"), (50_000, "partially_paid")]
    assert all(a["actor_id"] == "auth-u1" for a in audits)


def test_re_allocating_a_vendor_payment_adjusts_the_bill_as_the_api_and_audits_both_moves(world, two_clients):
    import routers.purchase_payments as pp
    import services.purchase_payment_service as pps
    from models.invoices import PurchasePaymentAllocationIn, PurchasePaymentAllocationsUpdateIn
    db = world[0]
    statements, attempts, audit_calls, install = two_clients
    party, bill = _received_bill(total=500_000, no="B-331-9")
    made = pps.create_payment_core(FIRM, {
        "client_id": "CLI", "vendor_id": party["id"], "payment_date": "2026-06-10", "amount_paise": 200_000,
        "allocations": [{"purchase_bill_id": bill["id"], "allocated_paise": 200_000}]}, CALLER, db)
    assert _row(db, "purchase_bills", bill["id"])["paid_paise"] == 200_000
    install()
    result = pp.update_purchase_payment_allocations(made["id"], PurchasePaymentAllocationsUpdateIn(
        allocations=[PurchasePaymentAllocationIn(purchase_bill_id=bill["id"], allocated_paise=50_000)]), CALLER)
    assert result["success"] is True, result
    assert attempts == []
    writes = _header_writes(statements, "purchase_bills")
    assert [w["payload"]["paid_paise"] for w in writes] == [0, 50_000], writes
    for w in writes:
        _assert_settlement_write(w, bill["id"])
    assert _row(db, "purchase_bills", bill["id"])["paid_paise"] == 50_000
    audits = _audited(audit_calls, "purchase_bill", bill["id"])
    assert [(a["old_data"]["paid_paise"], a["old_data"]["status"]) for a in audits] == [(200_000, "partially_paid"), (0, "received")]
    assert [(a["new_data"]["paid_paise"], a["new_data"]["status"]) for a in audits] == [(0, "received"), (50_000, "partially_paid")]
    assert all(a["actor_id"] == "auth-u1" for a in audits)


def test_reversing_a_receipt_gives_the_invoice_its_money_back_as_the_api_and_audits_it(world, two_clients):
    import routers.receipts as rc
    from models.accounting import JournalReversalIn
    from models.invoices import ReceiptAllocationIn, ReceiptIn
    db = world[0]
    statements, attempts, audit_calls, install = two_clients
    party, inv = _issued_invoice(total=500_000, no="INV-331-10")
    made = rc.create_receipt(ReceiptIn(
        client_id="CLI", customer_id=party["id"], receipt_date="2026-06-10", amount_paise=200_000,
        allocations=[ReceiptAllocationIn(sales_invoice_id=inv["id"], allocated_paise=200_000)]), CALLER)
    assert made["success"] is True, made
    install()
    result = rc.reverse_receipt(made["data"]["id"], JournalReversalIn(reversal_date="2026-06-20"), CALLER)
    assert result["success"] is True, result
    assert attempts == []
    (write,) = _header_writes(statements, "client_sales_invoices")
    _assert_settlement_write(write, inv["id"])
    assert write["payload"]["paid_paise"] == 0 and write["payload"]["status"] == "issued"
    assert _row(db, "client_sales_invoices", inv["id"])["paid_paise"] == 0
    (audit,) = _audited(audit_calls, "sales_invoice", inv["id"])
    assert audit["old_data"] == {"paid_paise": 200_000, "paid_txn": 0, "status": "partially_paid"}
    assert audit["new_data"] == {"paid_paise": 0, "paid_txn": 0, "status": "issued"} and audit["actor_id"] == "auth-u1"
    assert audit["metadata"]["reason"] == "a receipt's allocation was undone"


def test_reversing_a_vendor_payment_gives_the_bill_its_money_back_as_the_api_and_audits_it(world, two_clients):
    import routers.purchase_payments as pp
    from models.accounting import JournalReversalIn
    from models.invoices import PurchasePaymentIn
    db = world[0]
    statements, attempts, audit_calls, install = two_clients
    party, bill = _received_bill(total=500_000, no="B-331-11")
    made = pp.create_purchase_payment(PurchasePaymentIn(
        client_id="CLI", vendor_id=party["id"], payment_date="2026-06-10", amount_paise=200_000, purchase_bill_id=bill["id"]), CALLER)
    assert made["success"] is True, made
    install()
    result = pp.reverse_purchase_payment(made["data"]["id"], JournalReversalIn(reversal_date="2026-06-20"), CALLER)
    assert result["success"] is True, result
    assert attempts == []
    (write,) = _header_writes(statements, "purchase_bills")
    _assert_settlement_write(write, bill["id"])
    assert write["payload"]["paid_paise"] == 0 and write["payload"]["status"] == "received"
    assert _row(db, "purchase_bills", bill["id"])["paid_paise"] == 0
    (audit,) = _audited(audit_calls, "purchase_bill", bill["id"])
    assert audit["old_data"] == {"paid_paise": 200_000, "paid_txn": 0, "status": "partially_paid"}
    assert audit["new_data"] == {"paid_paise": 0, "paid_txn": 0, "status": "received"} and audit["actor_id"] == "auth-u1"
    assert audit["metadata"]["reason"] == "a payment's allocation was undone"


class _NoRpcClient(_Client):
    """The request's client with the atomic receipt function hidden, to force create_receipt_core down its fallback."""

    def __getattr__(self, attr):
        if attr == "rpc":
            raise AttributeError(attr)
        return super().__getattr__(attr)


def test_the_receipt_fallback_settles_its_invoice_as_the_api_and_audits_it(world, two_clients):
    import services.receipt_service as rs
    db = world[0]
    statements, attempts, audit_calls, install = two_clients
    party, inv = _issued_invoice(total=500_000, no="INV-331-12")
    pre = _row(db, "client_sales_invoices", inv["id"])
    install()
    made = rs.create_receipt_core(FIRM, {
        "client_id": "CLI", "customer_id": party["id"], "receipt_date": "2026-06-10", "amount_paise": 200_000,
        "allocations": [{"sales_invoice_id": inv["id"], "allocated_paise": 200_000}]}, CALLER, _NoRpcClient(db, "request", attempts))
    assert made
    assert attempts == []
    (write,) = _header_writes(statements, "client_sales_invoices")
    _assert_settlement_write(write, inv["id"])
    assert write["payload"] == {"paid_paise": 200_000, "status": "partially_paid"}
    assert _row(db, "client_sales_invoices", inv["id"])["paid_paise"] == 200_000
    _assert_audited_like(audit_calls, "sales_invoice", inv["id"], [write], pre)


def test_a_domestic_vendor_payment_across_several_bills_settles_each_as_the_api_and_audits_each(world, two_clients):
    import services.purchase_payment_service as pps
    db = world[0]
    statements, attempts, audit_calls, install = two_clients
    party, first = _received_bill(total=100_000, no="B-331-14")
    _, second = _received_bill(total=100_000, no="B-331-15", vendor=party)
    pres = [_row(db, "purchase_bills", first["id"]), _row(db, "purchase_bills", second["id"])]
    install()
    made = pps.create_payment_core(FIRM, {
        "client_id": "CLI", "vendor_id": party["id"], "payment_date": "2026-06-10", "amount_paise": 150_000,
        "allocations": [{"purchase_bill_id": first["id"], "allocated_paise": 100_000},
                        {"purchase_bill_id": second["id"], "allocated_paise": 50_000}]}, CALLER, _Client(db, "request", attempts))
    assert made
    assert attempts == []
    writes = _header_writes(statements, "purchase_bills")
    assert [w["payload"]["status"] for w in writes] == ["paid", "partially_paid"]
    for write, bill, pre in zip(writes, (first, second), pres, strict=True):
        _assert_settlement_write(write, bill["id"])
        _assert_audited_like(audit_calls, "purchase_bill", bill["id"], [write], pre)


def test_the_payment_status_reconciliation_writes_the_bill_as_the_api_and_audits_it(world, two_clients):
    import routers.purchase_payments as pp
    db = world[0]
    statements, attempts, audit_calls, install = two_clients
    party, bill = _received_bill(total=500_000, no="B-331-13")
    db.seed("purchase_payments", {"id": "PP-331-13", "firm_id": FIRM, "client_id": "CLI", "vendor_id": party["id"],
                                  "purchase_bill_id": bill["id"], "amount_paise": 200_000})
    install()
    pp._update_bill_payment_status(_Client(db, "request", attempts), FIRM, "CLI", bill["id"], 200_000, actor=CALLER)
    assert attempts == []
    (write,) = _header_writes(statements, "purchase_bills")
    _assert_settlement_write(write, bill["id"])
    assert write["payload"]["paid_paise"] == 200_000 and write["payload"]["status"] == "partially_paid"
    assert _row(db, "purchase_bills", bill["id"])["paid_paise"] == 200_000
    (audit,) = _audited(audit_calls, "purchase_bill", bill["id"])
    assert audit["old_data"] == {"paid_paise": 0, "status": "received"}
    assert audit["new_data"]["paid_paise"] == 200_000 and audit["new_data"]["status"] == "partially_paid"
    assert audit["actor_id"] == "auth-u1" and audit["actor_email"] == "ca@f.test"


def test_reversing_a_payment_that_settled_several_bills_gives_each_bill_its_money_back_as_the_api_and_audits_each(world, two_clients):
    import routers.purchase_payments as pp
    import services.purchase_payment_service as pps
    from models.accounting import JournalReversalIn
    db = world[0]
    statements, attempts, audit_calls, install = two_clients
    party, first = _received_bill(total=100_000, no="B-331-16")
    _, second = _received_bill(total=100_000, no="B-331-17", vendor=party)
    made = pps.create_payment_core(FIRM, {
        "client_id": "CLI", "vendor_id": party["id"], "payment_date": "2026-06-10", "amount_paise": 150_000,
        "allocations": [{"purchase_bill_id": first["id"], "allocated_paise": 100_000},
                        {"purchase_bill_id": second["id"], "allocated_paise": 50_000}]}, CALLER, db)
    install()
    result = pp.reverse_purchase_payment(made["id"], JournalReversalIn(reversal_date="2026-06-20"), CALLER)
    assert result["success"] is True, result
    assert attempts == []
    writes = _header_writes(statements, "purchase_bills")
    assert [w["payload"] for w in writes] == [{"paid_paise": 0, "paid_txn": 0, "status": "received"}] * 2
    for write, bill, was in zip(writes, (first, second), ((100_000, "paid"), (50_000, "partially_paid")), strict=True):
        _assert_settlement_write(write, bill["id"])
        (audit,) = _audited(audit_calls, "purchase_bill", bill["id"])
        assert audit["old_data"] == {"paid_paise": was[0], "paid_txn": 0, "status": was[1]}
        assert audit["actor_id"] == "auth-u1" and audit["metadata"]["reason"] == "a payment's allocation was undone"


# ── bank settlement and its undo, and the application of a party's credit ──────────────────────────────────

class _Spying:
    """Wraps ANY fluent client: records every statement written to a header table with its filters, and, when `refuse`, raises
    instead of writing (the way the signed-in role will once the migration lands)."""

    def __init__(self, inner, label, log, attempts=None, refuse=False):
        self.inner, self.label, self.log, self.attempts, self.refuse = inner, label, log, attempts, refuse

    def table(self, name):
        return _SpyingQuery(self.inner.table(name), name, self)

    def __getattr__(self, attr):
        return getattr(self.inner, attr)


class _SpyingQuery:
    def __init__(self, query, name, owner):
        self.q, self.name, self.owner = query, name, owner
        self.rec = {"label": owner.label, "table": name, "verb": "select", "payload": None, "filters": []}

    def __getattr__(self, attr):
        if attr in WRITE_VERBS and self.name in REFUSED_TABLES and self.owner.refuse:
            self.owner.attempts.append((self.name, attr))
            raise RuntimeError(f"permission denied for table {self.name}")

        def call(*a, **k):
            if attr in WRITE_VERBS:
                self.rec["verb"], self.rec["payload"] = attr, (a[0] if a else None)
            elif attr == "eq":
                self.rec["filters"].append(("eq", a[0], a[1]))
            elif attr == "execute" and self.rec["verb"] in WRITE_VERBS and self.name in HEADER_TABLES:
                self.owner.log.append(self.rec)
            res = getattr(self.q, attr)(*a, **k)
            return self if res is self.q else res
        return call


@pytest.fixture
def bank(monkeypatch):
    """The bank-undo test double seen through a request client that refuses the header writes and a privileged client that records."""
    import services.bank_posting_service as bps
    import services.journal_posting_service as jpsmod
    from tests import test_bank_undo as fx
    db = fx._db()
    statements, attempts, audit_calls = [], [], []
    request = _Spying(db, "request", statements, attempts, refuse=True)
    privileged = _Spying(db, "privileged", statements)
    monkeypatch.setattr("core.db_provider.service_db_or_none", lambda: privileged)
    monkeypatch.setattr(bps.timeline_service, "log", lambda *a, **k: None)
    monkeypatch.setattr(jpsmod.timeline_service, "log", lambda *a, **k: None)
    monkeypatch.setattr(bps.period_validation_service, "validate_posting_date", lambda *a, **k: None)
    monkeypatch.setattr(jpsmod.period_validation_service, "validate_posting_date", lambda *a, **k: None)
    monkeypatch.setattr(door.audit_service, "log_event", lambda *a, **k: audit_calls.append((a, k)))
    return fx, db, request, statements, attempts, audit_calls


def test_a_bank_posting_settles_its_invoice_as_the_api_and_audits_it_and_the_undo_gives_it_back(bank):
    from services.bank_posting_service import bank_posting_service as svc
    fx, db, request, statements, attempts, audit_calls = bank
    fx._invoice(db, total=118_000)
    fx._txn(db, credit=118_000, category="Customer Payment", matched_type="sales_invoice", matched_id="inv-1")
    svc.post(request, fx.FIRM, "t1", actor_id="u1", actor_auth_id="auth-u1")
    assert attempts == []
    (write,) = _header_writes(statements, "client_sales_invoices")
    assert write["label"] == "privileged"
    assert {("id", "inv-1"), ("firm_id", fx.FIRM), ("client_id", fx.CLIENT)} <= _filters(write)
    assert write["payload"]["paid_paise"] == 118_000 and write["payload"]["status"] == "paid"
    assert db.store["client_sales_invoices"][0]["status"] == "paid"
    (audit,) = _audited(audit_calls, "sales_invoice", "inv-1")
    assert audit["old_data"] == {"paid_paise": 0, "status": "issued"} and audit["actor_id"] == "auth-u1"
    assert audit["new_data"]["paid_paise"] == 118_000 and audit["metadata"]["reason"] == "a bank transaction was posted"

    statements.clear()
    audit_calls.clear()
    svc.undo(request, fx.FIRM, "t1", actor_id="u1", actor_auth_id="auth-u1")
    assert attempts == []
    (back,) = _header_writes(statements, "client_sales_invoices")
    assert back["label"] == "privileged" and {("id", "inv-1"), ("firm_id", fx.FIRM), ("client_id", fx.CLIENT)} <= _filters(back)
    assert back["payload"]["paid_paise"] == 0 and back["payload"]["status"] == "issued"
    (undo_audit,) = _audited(audit_calls, "sales_invoice", "inv-1")
    assert undo_audit["old_data"] == {"paid_paise": 118_000, "status": "paid"} and undo_audit["actor_id"] == "auth-u1"
    assert undo_audit["metadata"]["reason"] == "a bank posting was undone"


def test_a_bank_posting_settles_a_bill_the_same_way(bank):
    from services.bank_posting_service import bank_posting_service as svc
    fx, db, request, statements, attempts, audit_calls = bank
    db.store.setdefault("purchase_bills", []).append(
        {"id": "bill-1", "firm_id": fx.FIRM, "client_id": fx.CLIENT, "bill_no": "BILL-1", "total_paise": 59_000,
         "net_payable_paise": 59_000, "paid_paise": 0, "credit_note_paise": 0, "debited_paise": 0, "status": "received",
         "vendor_id": "vend-1"})
    fx._txn(db, debit=59_000, category="Vendor Payment", matched_type="purchase_bill", matched_id="bill-1")
    svc.post(request, fx.FIRM, "t1", actor_id="u1", actor_auth_id="auth-u1")
    assert attempts == []
    (write,) = _header_writes(statements, "purchase_bills")
    assert write["label"] == "privileged" and {("id", "bill-1"), ("firm_id", fx.FIRM), ("client_id", fx.CLIENT)} <= _filters(write)
    assert write["payload"]["paid_paise"] == 59_000 and write["payload"]["status"] == "paid"
    (audit,) = _audited(audit_calls, "purchase_bill", "bill-1")
    assert audit["actor_id"] == "auth-u1" and audit["old_data"] == {"paid_paise": 0, "status": "received"}
    assert audit["new_data"]["paid_paise"] == 59_000 and audit["metadata"]["reason"] == "a bank transaction was posted"


def test_a_scheduled_posting_that_names_no_person_is_recorded_with_none_and_never_with_the_internal_id(bank):
    from services.bank_posting_service import bank_posting_service as svc
    fx, db, request, statements, attempts, audit_calls = bank
    fx._invoice(db, total=118_000)
    fx._txn(db, credit=118_000, category="Customer Payment", matched_type="sales_invoice", matched_id="inv-1")
    svc.post(request, fx.FIRM, "t1", actor_id="u1")                    # the scheduled job names no auth id; the internal id is "u1"
    (audit,) = _audited(audit_calls, "sales_invoice", "inv-1")
    assert audit["actor_id"] is None and audit["actor_email"] is None


def test_a_legacy_bank_draft_approved_by_a_person_settles_with_that_persons_auth_id(bank):
    import services.journal_posting_service as jps
    fx, db, request, statements, attempts, audit_calls = bank
    fx._invoice(db, total=118_000)
    fx._txn(db, credit=118_000, category="Customer Payment", matched_type="sales_invoice", matched_id="inv-1",
            match_status="matched")
    db.store.setdefault("journal_entries", []).append(
        {"id": "je-d", "firm_id": fx.FIRM, "client_id": fx.CLIENT, "entry_date": "2026-06-10", "is_posted": False,
         "status": "draft", "source_type": "bank_transaction", "source_id": "t1", "reference_no": "BANK-t1"})
    db.store.setdefault("journal_lines", []).extend([
        {"id": "jl-1", "journal_entry_id": "je-d", "account_id": "acc-bank", "debit_paise": 118_000, "credit_paise": 0},
        {"id": "jl-2", "journal_entry_id": "je-d", "account_id": "acc-ar", "debit_paise": 0, "credit_paise": 118_000}])
    out = jps.journal_posting_service.post_draft(request, fx.FIRM, "je-d", actor_id="u1", actor_auth_id="auth-u1")
    assert out["settlement"]["allocated_paise"] == 118_000 and attempts == []
    (audit,) = _audited(audit_calls, "sales_invoice", "inv-1")
    assert audit["actor_id"] == "auth-u1"


def test_a_draft_approved_into_a_bank_posting_settles_through_the_door_with_the_approvers_auth_id(bank):
    from services.bank_posting_service import bank_posting_service as svc
    fx, db, request, statements, attempts, audit_calls = bank
    fx._invoice(db, total=118_000)
    fx._txn(db, credit=118_000, category="Customer Payment", matched_type="sales_invoice", matched_id="inv-1",
            match_status="matched")
    out = svc.settle_on_post(request, fx.FIRM, "t1", "je-1", actor_id="u1", actor_auth_id="auth-u1")
    assert out["allocated_paise"] == 118_000 and attempts == []
    (audit,) = _audited(audit_calls, "sales_invoice", "inv-1")
    assert audit["actor_id"] == "auth-u1"


def test_applying_a_party_credit_settles_the_invoice_as_the_api_and_audits_it(bank):
    from services.party_credit_service import party_credit_service
    fx, db, request, statements, attempts, audit_calls = bank
    fx._invoice(db, total=100_000)
    party_credit_service.grant_credit(db, fx.FIRM, fx.CLIENT, "customer", "cust-1", 30_000, source_type="manual")
    statements.clear()
    row = party_credit_service.apply_credit(
        request, fx.FIRM, fx.CLIENT, "customer", "cust-1", 30_000, "sales_invoice", "inv-1", created_by="u1", actor=CALLER)
    assert row and attempts == []
    (write,) = _header_writes(statements, "client_sales_invoices")
    assert write["label"] == "privileged"
    assert {("id", "inv-1"), ("firm_id", fx.FIRM), ("client_id", fx.CLIENT)} <= _filters(write)
    assert any(col == "paid_paise" for _kind, col, _v in write["filters"]), write
    assert write["payload"]["paid_paise"] == 30_000 and write["payload"]["status"] == "partially_paid"
    (audit,) = _audited(audit_calls, "sales_invoice", "inv-1")
    assert audit["old_data"] == {"paid_paise": 0, "status": "issued"} and audit["actor_id"] == "auth-u1"
    assert audit["metadata"]["reason"] == "a party's credit was applied"
