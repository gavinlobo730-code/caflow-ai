"""An edit of an invoice, a bill or a note records the value it replaced (POST-A-424).

WHAT WAS WRONG
    The six edit routes write with the privileged client, and migration 111's row-level capture trigger records a write only where
    `auth.uid()` is present, so nothing recorded a change unless the route did. The invoice and the bill logged the row AFTER the change and no
    `old_data`; the four notes (`update_credit_note`, `update_sales_debit_note`, `update_debit_note`, `update_purchase_credit_note`) logged nothing.
    A note, a reference or a due date that was changed, and since POST-A-399 one that is CLEARED, left no trace of what it had been. The proviso to
    Rule 3(1) of the Companies (Accounts) Rules 2014 requires an edit log; this is the half of it that says what was replaced. (Whether the law
    needs the replaced text of a free-text note is a question for a practising CA or counsel and is not assumed: the row is recorded because it
    costs nothing and a log that can say what a field was is the log that was asked for.)

WHAT THIS HOLDS
    * `audit_service.log_document_edit` records, for each column the edit wrote, the value it held BEFORE (`old_data`, a column the row did not carry
      is left out and never recorded as empty), the value it holds now (`new_data`) and which differ (`metadata.changed`); a draft's lines replaced as
      a whole are recorded as a whole, both ways; nothing is written when nothing was; the values are JSON-safe, so a date or a decimal cannot make
      the insert fail and, because the logger is non-fatal, vanish without a trace; the actor is the AUTH id;
    * each of the six routes calls it, reading the row BEFORE the write, and the audit row read back from the database says what the document held;
    * no column an edit model can write is a personal identifier, which is why `old_data` may carry values without the redaction the row-level
      path applies (`services/audit_service` explains the rule; this holds the premise it rests on).
"""
from __future__ import annotations

import datetime
import decimal

import pytest

import routers.credit_notes as cn
import routers.debit_notes as dn
import routers.purchase_bills as pb
import routers.purchase_credit_notes as pcn
import routers.sales_debit_notes as sdn
import routers.sales_invoices as si
from models.invoices import (InvoiceLineIn, PurchaseBillIn, PurchaseBillLineIn, PurchaseBillUpdateIn, SalesInvoiceIn,
                             SalesInvoiceLineIn, SalesInvoiceUpdateIn)
from services import audit_service
from tests.e2e_harness import FakeDB, seed_standard_coa, wire_e2e

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "auth_user_id": "auth-u1", "id": "user-1", "email": "ca@firma.test", "role": "Partner"}


# ════════════════════════════════════════════════════════
# the helper, alone
# ════════════════════════════════════════════════════════

@pytest.fixture
def logged(monkeypatch):
    seen: list[dict] = []
    monkeypatch.setattr(audit_service, "log_event", lambda *a, **kw: seen.append({"args": a, **kw}))
    return seen


def _edit(logged, before, written, **kw):
    audit_service.log_document_edit("F", "sales_invoice", "d1", before, written, actor_id="auth-u", actor_email="e@x", **kw)
    return logged[-1] if logged else None


def test_the_value_each_written_column_held_before_is_recorded_beside_the_value_it_holds_now(logged):
    row = _edit(logged, {"notes": "old", "reference_no": "PO-1", "total_paise": 100}, {"notes": "new", "updated_at": "t"},
                updated={"notes": "new", "total_paise": 100})
    assert row["args"][:4] == ("F", "sales_invoice", "d1", "update")
    assert row["old_data"] == {"notes": "old"}, "only the column the edit wrote, and what it held before"
    assert row["new_data"] == {"notes": "new"}
    assert row["metadata"]["changed"] == ["notes"]
    assert (row["actor_id"], row["actor_email"]) == ("auth-u", "e@x")


def test_new_data_is_what_the_row_holds_now_and_not_what_the_route_asked_for(logged):
    """The database may store a value differently from the one written (trimmed, defaulted, normalised): the record says what is there."""
    row = _edit(logged, {"notes": "old", "reference_no": "A"}, {"notes": "  new  ", "reference_no": "B"},
                updated={"notes": "new"})
    assert row["new_data"] == {"notes": "new", "reference_no": "B"}, "the stored value where the row came back, the written one where it did not"


def test_a_cleared_value_is_recorded_as_what_it_was_and_what_it_is(logged):
    row = _edit(logged, {"notes": "Please pay by cheque"}, {"notes": None}, updated={"notes": None})
    assert row["old_data"] == {"notes": "Please pay by cheque"} and row["new_data"] == {"notes": None}
    assert row["metadata"]["changed"] == ["notes"]


def test_a_column_the_row_did_not_carry_is_left_out_and_never_recorded_as_empty(logged):
    row = _edit(logged, {"notes": "n"}, {"notes": "m", "brand_new_column": 3}, updated={})
    assert row["old_data"] == {"notes": "n"}
    assert row["new_data"] == {"notes": "m", "brand_new_column": 3}
    assert row["metadata"]["changed"] == ["notes"]


def test_a_column_written_the_same_value_is_not_listed_as_changed(logged):
    row = _edit(logged, {"notes": "same", "reference_no": "A"}, {"notes": "same", "reference_no": "B"}, updated={})
    assert row["metadata"]["changed"] == ["reference_no"]


def test_nothing_is_written_when_nothing_was(logged):
    assert _edit(logged, {"notes": "n"}, {}) is None
    assert _edit(logged, {"notes": "n"}, {"updated_at": "t"}) is None
    assert not logged


def test_a_drafts_lines_replaced_as_a_whole_are_recorded_as_a_whole_both_ways(logged):
    old = [{"id": "l1", "description": "A", "rate_paise": 100}, {"id": "l2", "description": "B", "rate_paise": 200}]
    new = [{"description": "C", "rate_paise": 300}]
    row = _edit(logged, {"total_paise": 300}, {"total_paise": 300, "lines": "ignored"}, updated={}, old_lines=old, new_lines=new)
    assert row["old_data"]["lines"] == old and row["new_data"]["lines"] == new
    assert "lines" in row["metadata"]["changed"]
    assert row["old_data"]["total_paise"] == 300


def test_a_draft_that_had_no_lines_records_an_empty_list_and_not_nothing(logged):
    row = _edit(logged, {"total_paise": 0}, {}, updated={}, old_lines=[], new_lines=[{"description": "A"}])
    assert row is not None and row["old_data"] == {"lines": []} and row["new_data"]["lines"] == [{"description": "A"}]


def test_a_date_and_a_decimal_are_recorded_as_text_so_the_insert_cannot_fail(logged):
    row = _edit(logged, {"due_date": datetime.date(2026, 4, 1), "rate": decimal.Decimal("1.5")},
                {"due_date": datetime.date(2026, 4, 25), "rate": decimal.Decimal("2.5")}, updated={})
    assert row["old_data"] == {"due_date": "2026-04-01", "rate": "1.5"}
    assert row["new_data"] == {"due_date": "2026-04-25", "rate": "2.5"}


def test_the_audit_insert_is_the_one_logger_and_stays_non_fatal(monkeypatch):
    """`log_document_edit` goes through `log_event`, which swallows a failed insert: a failed audit write never undoes the edit."""
    import core.supabase_client as sc

    class Boom:
        def table(self, *_):
            raise RuntimeError("db down")
    monkeypatch.setattr(sc, "get_service_supabase", lambda: Boom())
    audit_service.log_document_edit("F", "credit_note", "d1", {"notes": "a"}, {"notes": "b"}, actor_id="u")


# ════════════════════════════════════════════════════════
# the six routes, over the fake database, reading the audit row back
# ════════════════════════════════════════════════════════

def _audit(db):
    return [r for r in db.rows("audit_log") if (r.get("metadata") or {}).get("recorded_by") == "log_document_edit"]


def _invoice_db(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [si])
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5"})
    db.seed("customers", {"id": "CUST", "firm_id": FIRM, "client_id": "CLI", "name": "Acme", "state_code": "27", "gstin": "27XYZAB5678C1Z2",
                          "credit_days": 15, "is_active": True})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI", "name": "Consulting", "kind": "service"})
    return db


def _new_invoice():
    return si.create_invoice(SalesInvoiceIn(
        client_id="CLI", customer_id="CUST", invoice_date="2026-04-10", invoice_no="CL-001", reference_no="PO-77", notes="Please pay by cheque",
        lines=[InvoiceLineIn(service_catalogue_id="SVC-1", description="X", hsn_sac="9982", quantity=1, rate_paise=1_000_000, gst_rate_percent=18.0)],
    ), CALLER)["data"]


def test_an_invoice_edit_records_what_the_note_and_the_reference_were(monkeypatch):
    db = _invoice_db(monkeypatch)
    inv = _new_invoice()
    db.rows("audit_log").clear()
    out = si.update_invoice(inv["id"], SalesInvoiceUpdateIn(notes="Paid by cheque", reference_no=None), CALLER)
    assert out["success"] is True, out
    (row,) = _audit(db)
    assert (row["entity_type"], row["entity_id"], row["action"]) == ("sales_invoice", inv["id"], "update")
    assert row["old_data"] == {"notes": "Please pay by cheque", "reference_no": "PO-77"}
    assert row["new_data"] == {"notes": "Paid by cheque", "reference_no": None}
    assert sorted(row["metadata"]["changed"]) == ["notes", "reference_no"]
    assert (row["actor_id"], row["actor_email"], row["firm_id"]) == ("auth-u1", "ca@firma.test", FIRM)


def test_an_invoice_edit_that_replaces_the_lines_of_a_draft_records_the_lines_it_replaced(monkeypatch):
    db = _invoice_db(monkeypatch)
    inv = _new_invoice()
    db.rows("audit_log").clear()
    before = [ln for ln in db.rows("client_sales_invoice_lines") if ln.get("sales_invoice_id") == inv["id"]]
    assert len(before) == 1
    out = si.update_invoice(inv["id"], SalesInvoiceUpdateIn(lines=[SalesInvoiceLineIn(
        service_catalogue_id="SVC-1", description="Y", hsn_sac="9982", quantity=2, rate_paise=400_000, gst_rate_percent=18.0)]), CALLER)
    assert out["success"] is True, out
    rows = _audit(db)
    (lines_row,) = [r for r in rows if "lines" in (r["old_data"] or {})]
    (header_row,) = [r for r in rows if "lines" not in (r["old_data"] or {})]
    assert [ln["description"] for ln in lines_row["old_data"]["lines"]] == ["X"], "the line the edit replaced"
    assert [ln["description"] for ln in lines_row["new_data"]["lines"]] == ["Y"]
    assert lines_row["metadata"]["changed"] == ["lines"]
    assert (lines_row["entity_type"], lines_row["entity_id"], lines_row["actor_id"]) == ("sales_invoice", inv["id"], "auth-u1")
    assert header_row["old_data"]["total_paise"] == inv["total_paise"], "the header's total as it was is recorded beside the lines"
    assert header_row["new_data"]["total_paise"] != inv["total_paise"]


def test_an_invoice_edit_that_writes_nothing_records_nothing(monkeypatch):
    db = _invoice_db(monkeypatch)
    inv = _new_invoice()
    db.rows("audit_log").clear()
    out = si.update_invoice(inv["id"], SalesInvoiceUpdateIn(), CALLER)
    assert out["success"] is True, out
    assert not _audit(db), "an edit with nothing to write was recorded as a change"


def _bill_db(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [pb])
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5"})
    db.seed("vendors", {"id": "VEND", "firm_id": FIRM, "client_id": "CLI", "name": "Supplier Co", "state_code": "27", "gstin": "27PQRST9012K1Z8",
                        "pan": "PQRST9012K", "is_active": True, "tds_applicable": False, "credit_days": 15})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI", "name": "Consulting", "kind": "service"})
    return db


def _new_bill():
    return pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id="VEND", bill_date="2026-04-10", bill_no="B-001", our_reference="OUR-1", notes="Received with the goods",
        document_url="path/to/scan.pdf",
        lines=[PurchaseBillLineIn(description="X", hsn_sac="9982", quantity=1, rate_paise=1_000_000, gst_rate_percent=18.0, service_catalogue_id="SVC-1")],
    ), CALLER)["data"]


def test_a_bill_edit_records_what_the_note_and_the_reference_were_and_the_lines_it_replaced(monkeypatch):
    db = _bill_db(monkeypatch)
    bill = _new_bill()
    db.rows("audit_log").clear()
    out = pb.update_purchase_bill(bill["id"], PurchaseBillUpdateIn(notes=None, our_reference="OUR-2", lines=[PurchaseBillLineIn(
        description="Z", hsn_sac="9982", quantity=1, rate_paise=700_000, gst_rate_percent=18.0, service_catalogue_id="SVC-1")]), CALLER)
    assert out["success"] is True, out
    rows = _audit(db)
    (lines_row,) = [r for r in rows if "lines" in (r["old_data"] or {})]
    (row,) = [r for r in rows if "lines" not in (r["old_data"] or {})]
    assert (row["entity_type"], row["entity_id"]) == ("purchase_bill", bill["id"])
    assert row["old_data"]["notes"] == "Received with the goods" and row["new_data"]["notes"] is None
    assert row["old_data"]["our_reference"] == "OUR-1" and row["new_data"]["our_reference"] == "OUR-2"
    assert [ln["description"] for ln in lines_row["old_data"]["lines"]] == ["X"]
    assert [ln["description"] for ln in lines_row["new_data"]["lines"]] == ["Z"]


_NOTES = [
    (cn, "credit_notes", "credit_note", "update_credit_note", "CreditNoteUpdateIn", {"customer_id": "CUST", "credit_note_date": "2026-04-12", "total_paise": 100}),
    (sdn, "sales_debit_notes", "sales_debit_note", "update_sales_debit_note", "SalesDebitNoteUpdateIn", {"customer_id": "CUST", "debit_note_date": "2026-04-12", "total_paise": 100}),
    (dn, "debit_notes", "debit_note", "update_debit_note", "DebitNoteUpdateIn", {"vendor_id": "VEND", "debit_note_date": "2026-04-12", "total_paise": 100}),
    (pcn, "purchase_credit_notes", "purchase_credit_note", "update_purchase_credit_note", "PurchaseCreditNoteUpdateIn", {"vendor_id": "VEND", "credit_note_date": "2026-04-12", "total_paise": 100}),
]


@pytest.mark.parametrize("module,table,kind,handler,model_name,extra", _NOTES, ids=[t for _, t, *_ in _NOTES])
def test_a_note_edit_records_what_the_note_was_and_what_it_is(monkeypatch, module, table, kind, handler, model_name, extra):
    """The four notes logged NOTHING: a note that was changed or cleared left no trace of what it had been."""
    db = FakeDB()
    wire_e2e(monkeypatch, db, [module])
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5"})
    row = db.seed(table, {"firm_id": FIRM, "client_id": "CLI", "status": "draft", "notes": "A note to change", "deleted_at": None, **extra})
    model = getattr(module, model_name)
    out = getattr(module, handler)(row["id"], model(notes="A better note"), CALLER)
    assert out["success"] is True, out
    (rec,) = _audit(db)
    assert (rec["entity_type"], rec["entity_id"], rec["action"]) == (kind, row["id"], "update")
    assert rec["old_data"] == {"notes": "A note to change"} and rec["new_data"] == {"notes": "A better note"}
    assert rec["metadata"]["changed"] == ["notes"]
    assert (rec["actor_id"], rec["firm_id"]) == ("auth-u1", FIRM), "the actor is the AUTH id, as every audit row's is"
    db.rows("audit_log").clear()
    out = getattr(module, handler)(row["id"], model(notes=None), CALLER)
    assert out["success"] is True, out
    (rec,) = _audit(db)
    assert rec["old_data"] == {"notes": "A better note"} and rec["new_data"] == {"notes": None}, "a cleared note says what it was"


@pytest.mark.parametrize("module,table,kind,handler,model_name,extra", _NOTES, ids=[t for _, t, *_ in _NOTES])
def test_an_edit_that_sends_nothing_to_write_records_nothing(monkeypatch, module, table, kind, handler, model_name, extra):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [module])
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5"})
    row = db.seed(table, {"firm_id": FIRM, "client_id": "CLI", "status": "draft", "notes": "kept", "deleted_at": None, **extra})
    out = getattr(module, handler)(row["id"], getattr(module, model_name)(), CALLER)
    assert out["success"] is True, out
    assert not _audit(db), "an edit with nothing to write was recorded as a change"


# ════════════════════════════════════════════════════════
# the one door that replaces a draft's lines records what it replaced
# ════════════════════════════════════════════════════════

class _Db:
    """A database that holds the lines a draft has now and answers the replacement the way the real function does, or refuses."""

    def __init__(self, lines, refuse=None):
        self.lines, self.refuse, self.rpcs = lines, refuse, []

    def table(self, name):
        return self

    def select(self, *_):
        return self

    def eq(self, *_):
        return self

    def rpc(self, fn, params):
        self.rpcs.append((fn, params))
        return self

    def execute(self):
        if self.refuse and self.rpcs:
            raise RuntimeError(self.refuse)
        return type("R", (), {"data": self.lines if not self.rpcs else None})()


@pytest.fixture
def audit_rows(monkeypatch):
    seen = []
    monkeypatch.setattr(audit_service, "log_event", lambda *a, **kw: seen.append({"args": a, **kw}))
    monkeypatch.setattr("services.draft_document_lines.privileged_for", lambda db: db)
    return seen


def test_the_door_records_the_lines_it_replaced_beside_the_lines_that_replace_them(audit_rows):
    from services import draft_document_lines as door
    db = _Db([{"id": "l1", "description": "old"}])
    n = door.replace_draft_lines(db, "credit_note", "cn-1", "F", [{"credit_note_id": "cn-1", "description": "new"}],
                                 edited_by={"auth_user_id": "auth-7", "email": "a@b"})
    assert n == 1
    (row,) = audit_rows
    assert row["args"][:4] == ("F", "credit_note", "cn-1", "update")
    assert row["old_data"] == {"lines": [{"id": "l1", "description": "old"}]}
    assert row["new_data"] == {"lines": [{"description": "new"}]}, "the foreign key is the document's own and is not recorded as a column"
    assert (row["actor_id"], row["actor_email"]) == ("auth-7", "a@b")


def test_the_lines_it_replaced_are_read_as_the_api_and_not_as_the_caller(audit_rows, monkeypatch):
    """The signed-in role holds no read on the document tables (migration 551): the caller's own client finds nothing, and recording
    that would say the lines were empty beside lines that were not."""
    from services import draft_document_lines as door
    caller = _Db([])                                   # what a client with no grant reads
    privileged = _Db([{"id": "l1", "description": "really there"}])
    monkeypatch.setattr(door, "privileged_for", lambda db: privileged)
    door.replace_draft_lines(caller, "sales_invoice", "inv-1", "F", [{"description": "new"}], edited_by={"auth_user_id": "u"})
    (row,) = audit_rows
    assert row["old_data"] == {"lines": [{"id": "l1", "description": "really there"}]}


def test_a_replacement_the_database_refused_records_nothing(audit_rows):
    from fastapi import HTTPException
    from services import draft_document_lines as door
    db = _Db([{"id": "l1"}], refuse="document_not_draft")
    with pytest.raises(HTTPException) as refused:
        door.replace_draft_lines(db, "credit_note", "cn-1", "F", [], edited_by={"auth_user_id": "u"})
    assert refused.value.status_code == 409
    assert not audit_rows, "an edit that did not happen was recorded as one"


def test_every_caller_of_the_door_says_whose_edit_it_is():
    """`edited_by` has no default, so a call that omits it is a TypeError; this reads the six routes for it all the same."""
    import ast
    from pathlib import Path
    routers = Path(__file__).resolve().parents[1] / "routers"
    seen = 0
    for path in routers.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "replace_draft_lines"):
                seen += 1
                assert any(k.arg == "edited_by" for k in node.keywords), f"{path.name}:{node.lineno} replaces a draft's lines and says nobody did"
    assert seen == 6, f"{seen} callers of replace_draft_lines in routers/: a seventh needs its edit recorded too, and this count moved on purpose"


# ════════════════════════════════════════════════════════
# what the independent read of the first version found
# ════════════════════════════════════════════════════════

def test_an_update_that_matched_no_row_records_nothing(logged):
    audit_service.log_document_edit("F", "credit_note", "c1", {"notes": "a"}, {"notes": "b"}, actor_id="u", matched=False)
    assert not logged, "a write that changed nothing was recorded as an edit"


def test_a_credit_note_whose_update_matched_no_row_records_nothing(monkeypatch):
    """The draft was deleted, or its client changed, between the route's read and its UPDATE: the route still answers success, and the
    log must not say an edit happened."""
    db = FakeDB()
    wire_e2e(monkeypatch, db, [cn])
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5"})
    row = db.seed("credit_notes", {"firm_id": FIRM, "client_id": "CLI", "status": "draft", "notes": "a", "deleted_at": None,
                                   "customer_id": "CUST", "credit_note_date": "2026-04-12", "total_paise": 100})

    class _Empty:
        def update(self, *_a, **_k):
            return self

        def eq(self, *_a, **_k):
            return self

        def execute(self):
            return type("R", (), {"data": []})()

    class _Ghost:
        def __init__(self, real):
            self._real = real

        def table(self, name):
            return _Empty() if name == "credit_notes" else self._real.table(name)

        def __getattr__(self, attr):
            return getattr(self._real, attr)

    monkeypatch.setattr(cn, "privileged_for", lambda d: _Ghost(d))
    out = cn.update_credit_note(row["id"], cn.CreditNoteUpdateIn(notes="ghost"), CALLER)
    assert out["success"] is True, out
    assert not _audit(db)


class _EmptyUpdate:
    """A statement that matches no row: the draft was deleted, or its client changed, between the route's read and its UPDATE."""

    def update(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def execute(self):
        return type("R", (), {"data": []})()


class _GhostWrites:
    """The privileged client, except that the one table named matches nothing when written."""

    def __init__(self, real, table):
        self._real, self._table = real, table

    def table(self, name):
        return _EmptyUpdate() if name == self._table else self._real.table(name)

    def __getattr__(self, attr):
        return getattr(self._real, attr)


def test_an_invoice_whose_update_matched_no_row_records_nothing(monkeypatch):
    db = _invoice_db(monkeypatch)
    inv = _new_invoice()
    db.rows("audit_log").clear()
    monkeypatch.setattr(si, "privileged_for", lambda d: _GhostWrites(d, "client_sales_invoices"))
    out = si.update_invoice(inv["id"], SalesInvoiceUpdateIn(notes="ghost"), CALLER)
    assert out["success"] is True, out
    assert not _audit(db), "an edit that never reached the database was recorded as one"


def test_a_bill_whose_update_matched_no_row_records_nothing(monkeypatch):
    db = _bill_db(monkeypatch)
    bill = _new_bill()
    db.rows("audit_log").clear()
    monkeypatch.setattr(pb, "privileged_for", lambda d: _GhostWrites(d, "purchase_bills"))
    out = pb.update_purchase_bill(bill["id"], PurchaseBillUpdateIn(notes="ghost"), CALLER)
    assert out["success"] is True, out
    assert not _audit(db), "an edit that never reached the database was recorded as one"


def _units_of(db, table):
    return {r["id"]: r.get("unit") for r in db.rows(table)}


def test_a_unit_only_correction_on_an_issued_invoice_records_the_unit_it_replaced(monkeypatch):
    """A unit-only save wrote NO audit row once the edit record began: the helper returned early on a write of `updated_at` alone."""
    db = _invoice_db(monkeypatch)
    inv = _new_invoice()
    (line,) = db.rows("client_sales_invoice_lines")
    db.rows("client_sales_invoices")[0]["status"] = "issued"
    old = _units_of(db, "client_sales_invoice_lines")[line["id"]]
    db.rows("audit_log").clear()
    out = si.update_invoice(inv["id"], SalesInvoiceUpdateIn(line_units={line["id"]: "KGS"}), CALLER)
    assert out["success"] is True, out
    assert _units_of(db, "client_sales_invoice_lines")[line["id"]] == "KGS"
    (row,) = _audit(db)
    assert (row["entity_type"], row["entity_id"], row["actor_id"]) == ("sales_invoice", inv["id"], "auth-u1")
    assert row["old_data"] == {"line_units": {line["id"]: old}} and row["new_data"] == {"line_units": {line["id"]: "KGS"}}
    assert row["metadata"]["changed"] == ["line_units"]
    db.rows("audit_log").clear()
    si.update_invoice(inv["id"], SalesInvoiceUpdateIn(line_units={line["id"]: "KGS"}), CALLER)
    assert not _audit(db), "a unit sent as it already was is written and is not recorded as a change"


def test_a_unit_correction_beside_a_note_is_two_rows_the_notes_and_the_units(monkeypatch):
    db = _invoice_db(monkeypatch)
    inv = _new_invoice()
    (line,) = db.rows("client_sales_invoice_lines")
    db.rows("audit_log").clear()
    si.update_invoice(inv["id"], SalesInvoiceUpdateIn(notes="n2", line_units={line["id"]: "LTR"}), CALLER)
    rows = _audit(db)
    assert sorted(tuple(r["metadata"]["changed"]) for r in rows) == [("line_units",), ("notes",)]


def test_a_unit_correction_on_a_bill_is_recorded_the_same_way(monkeypatch):
    db = _bill_db(monkeypatch)
    bill = _new_bill()
    (line,) = db.rows("purchase_bill_lines")
    old = line.get("unit")
    db.rows("audit_log").clear()
    out = pb.update_purchase_bill(bill["id"], PurchaseBillUpdateIn(line_units={line["id"]: "KGS"}), CALLER)
    assert out["success"] is True, out
    (row,) = _audit(db)
    assert (row["entity_type"], row["entity_id"]) == ("purchase_bill", bill["id"])
    assert row["old_data"] == {"line_units": {line["id"]: old}} and row["new_data"] == {"line_units": {line["id"]: "KGS"}}


def test_a_save_that_sends_the_lines_the_draft_already_holds_records_no_lines(monkeypatch):
    """The editor re-sends every line on every save. A note-only edit must not copy every line both ways into a log that is never purged."""
    db = _invoice_db(monkeypatch)
    inv = _new_invoice()
    db.rows("audit_log").clear()
    same = SalesInvoiceLineIn(service_catalogue_id="SVC-1", description="X", hsn_sac="9982", quantity=1, rate_paise=1_000_000, gst_rate_percent=18.0)
    out = si.update_invoice(inv["id"], SalesInvoiceUpdateIn(notes="only the note", lines=[same]), CALLER)
    assert out["success"] is True, out
    rows = _audit(db)
    assert [r["metadata"]["changed"] for r in rows] == [["notes"]], rows
    assert not any("lines" in (r["old_data"] or {}) for r in rows)


def test_a_door_that_replaces_different_lines_records_them_and_one_that_replaces_the_same_lines_does_not(audit_rows):
    from services import draft_document_lines as door
    held = [{"id": "l1", "credit_note_id": "cn-1", "description": "A", "rate_paise": 100, "sort_order": 0, "created_at": "t"}]
    door.replace_draft_lines(_Db(list(held)), "credit_note", "cn-1", "F", [{"description": "A", "rate_paise": 100, "sort_order": 0}],
                             edited_by={"auth_user_id": "u"})
    assert not audit_rows, "lines identical to what the draft held were recorded as replaced"
    door.replace_draft_lines(_Db(list(held)), "credit_note", "cn-1", "F", [{"description": "A", "rate_paise": 101, "sort_order": 0}],
                             edited_by={"auth_user_id": "u"})
    assert len(audit_rows) == 1
    door.replace_draft_lines(_Db(list(held)), "credit_note", "cn-1", "F", [], edited_by={"auth_user_id": "u"})
    assert len(audit_rows) == 2, "a draft whose lines were all removed is a replacement"


def test_the_lines_it_replaced_are_all_of_them_past_the_databases_row_cap_and_in_the_documents_order():
    """An unpaged read of a draft with more than 1,000 lines was recorded short, in the log that can never be corrected."""
    from services import draft_document_lines as door
    from tests._capped_postgrest import DB_MAX_ROWS, CappedDB
    n = DB_MAX_ROWS + 300
    rows = [{"id": f"l{i:05d}", "bill_id": "b1", "description": f"line {i}", "sort_order": n - i} for i in range(n)]
    rows.append({"id": "elsewhere", "bill_id": "b2", "description": "another bill's", "sort_order": 0})
    db = CappedDB({"purchase_bill_lines": rows})
    got = door._read_lines(db, "purchase_bill", "b1")
    assert len(got) == n and all(r["bill_id"] == "b1" for r in got)
    assert [r["sort_order"] for r in got] == sorted(r["sort_order"] for r in got), "the order the document shows its lines in"
    assert len(db.requests["purchase_bill_lines"]) >= 2, "read in more than one request"


import tests.test_an_item_on_a_document_line_is_the_documents_clients as _items  # noqa: E402
from tests.test_an_item_on_a_document_line_is_the_documents_clients import KINDS, world  # noqa: E402,F401  (the fixture and the six routes)

_ENTITY = {"sales invoice": "sales_invoice", "purchase bill": "purchase_bill", "credit note": "credit_note", "debit note": "debit_note",
           "sales debit note": "sales_debit_note", "purchase credit note": "purchase_credit_note"}


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_each_of_the_six_routes_records_the_lines_it_replaced_from_the_right_table_under_the_right_actor(world, kind):  # noqa: F811  (the imported fixture, requested by its name)
    """The door's tests use a fake that ignores table and column names; this drives each route over the in-memory database, so a lines
    table or a foreign key named wrongly reads nothing and records `[]` beside lines that were there."""
    create, update, table, lines_table, fk = KINDS[kind]
    doc = _items._created(create([_items.OWN, _items.OWN]))
    world.rows("audit_log").clear()
    out = update(doc, [_items.OWN])
    assert out["success"] is True, out
    rows = _audit(world)
    (lines_row,) = [r for r in rows if "lines" in (r["old_data"] or {})]
    assert (lines_row["entity_type"], lines_row["entity_id"]) == (_ENTITY[kind], doc)
    assert lines_row["actor_id"] == _items.CALLER["auth_user_id"], "the lines are recorded under the member who edited, not nobody"
    assert len(lines_row["old_data"]["lines"]) == 2 and len(lines_row["new_data"]["lines"]) == 1
    assert {ln[fk] for ln in lines_row["old_data"]["lines"]} == {doc}, f"read from {lines_table} by {fk}"
    header = [r for r in rows if "lines" not in (r["old_data"] or {})]
    assert len(header) == 1 and header[0]["actor_id"] == _items.CALLER["auth_user_id"]


# ════════════════════════════════════════════════════════
# the premise: no column an edit can write is a personal identifier
# ════════════════════════════════════════════════════════

_IDENTIFIER_WORDS = ("pan", "gstin", "uan", "esic", "aadhaar", "aadhar", "account_no", "account_number", "ifsc", "passport")


@pytest.mark.parametrize("model", [SalesInvoiceUpdateIn, PurchaseBillUpdateIn, cn.CreditNoteUpdateIn, sdn.SalesDebitNoteUpdateIn,
                                   dn.DebitNoteUpdateIn, pcn.PurchaseCreditNoteUpdateIn])
def test_no_column_an_edit_can_write_is_a_personal_identifier(model):
    """`audit_service` records the changed columns without the redaction the row-level path applies, because 'of 893 rows this Python
    path has written, zero carried an identifier'. That holds only while no edit can write one."""
    for name in model.model_fields:
        assert not any(w == name or name.startswith(w + "_") or name.endswith("_" + w) for w in _IDENTIFIER_WORDS), \
            f"{model.__name__}.{name} looks like an identifier: redact it in log_document_edit before recording it"
