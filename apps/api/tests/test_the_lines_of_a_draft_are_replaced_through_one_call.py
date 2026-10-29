"""The lines of a draft document are replaced through ONE call that locks the header first (ledger POST-A-332, migration 560).

WHAT WAS WRONG
    An invoice, bill or note PATCH replaced a draft's lines as a DELETE and then an INSERT (the notes one line per request), two
    requests or more, and updated the header after both. A session that issued the document in between left an ISSUED document with
    no lines, and the saver saw only a generic failure. The database function is proved against real Postgres in
    `test_560_..._pg.py`; this file holds the rest, in the required job:

    * THE HELPER: it replaces a draft's lines for each of the six documents with the document's own id as their foreign key, strips
      a foreign key an element carries, answers 409 in words when the document was issued meanwhile and 404 when it is not the firm's,
      falls back to the old two steps ONLY when the function is missing from the database (PGRST202 or "function ... does not
      exist"), and lets every other error through.
    * THE KINDS MATCH THE SQL: the helper's table of (lines table, foreign key) is the CASE of the migration's function, read from
      the file, so one cannot move without the other.
    * THE RULE: no module deletes the lines of one of the six documents except this helper and the four reviewed places that remove
      the lines of a draft they have just made (a compensating delete after losing a race). A seventh route that went back to delete-then-insert fails
      here and is told where the call is.
    * THE ROUTE: a PATCH that finds the invoice issued while it was replacing the lines answers 409 and writes no header.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi import HTTPException

from services import draft_document_lines as ddl
from services.draft_document_lines import DOCUMENTS, replace_draft_lines
from tests._table_uses import API_ROOT, sources, uses
from tests.e2e_harness import FakeDB

FIRM, OTHER_FIRM = "F1", "F2"
HEADERS = {"sales_invoice": "client_sales_invoices", "purchase_bill": "purchase_bills", "credit_note": "credit_notes",
           "debit_note": "debit_notes", "sales_debit_note": "sales_debit_notes", "purchase_credit_note": "purchase_credit_notes"}
MIGRATION = API_ROOT / "migrations" / "560_a_draft_documents_lines_are_replaced_in_one_transaction_that_locks_the_header_first.sql"


def _db(kind: str, status: str = "draft") -> tuple[FakeDB, str]:
    db = FakeDB()
    doc = db.seed(HEADERS[kind], {"firm_id": FIRM, "status": status})
    table, fk, _ = DOCUMENTS[kind]
    db.seed(table, {fk: doc["id"], "description": "old"})
    return db, doc["id"]


# ── THE HELPER ────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind", sorted(DOCUMENTS))
def test_the_old_lines_go_and_the_new_ones_carry_the_documents_own_id(kind):
    db, doc = _db(kind)
    table, fk, _ = DOCUMENTS[kind]
    n = replace_draft_lines(db, kind, doc, FIRM, [{"description": "new", fk: "someone-elses"}, {"description": "newer"}])
    assert n == 2
    rows = db.rows(table)
    assert [r["description"] for r in rows] == ["new", "newer"]
    assert {r[fk] for r in rows} == {doc}, "a foreign key an element carried must not decide which document it lands on"


@pytest.mark.parametrize("kind", sorted(DOCUMENTS))
def test_a_document_issued_meanwhile_is_a_409_in_words_and_keeps_its_lines(kind):
    db, doc = _db(kind, status="issued")
    table = DOCUMENTS[kind][0]
    with pytest.raises(HTTPException) as caught:
        replace_draft_lines(db, kind, doc, FIRM, [{"description": "new"}])
    assert caught.value.status_code == 409
    assert "was issued while you were editing it" in caught.value.detail and "were not changed" in caught.value.detail
    assert [r["description"] for r in db.rows(table)] == ["old"]


@pytest.mark.parametrize("kind", sorted(DOCUMENTS))
def test_another_firms_document_is_a_404(kind):
    db, doc = _db(kind)
    with pytest.raises(HTTPException) as caught:
        replace_draft_lines(db, kind, doc, OTHER_FIRM, [{"description": "new"}])
    assert caught.value.status_code == 404
    assert [r["description"] for r in db.rows(DOCUMENTS[kind][0])] == ["old"]


class _WithoutTheFunction(FakeDB):
    """A database that has not had migration 560 applied: PostgREST says so the way it says it for any missing function."""

    def rpc(self, fn, params=None):
        if fn == "replace_draft_document_lines":
            raise Exception("Could not find the function public.replace_draft_document_lines(p_document, p_document_id, p_firm_id, "
                            "p_lines) in the schema cache (PGRST202)")
        return super().rpc(fn, params)


@pytest.mark.parametrize("kind", sorted(DOCUMENTS))
def test_while_the_function_is_missing_the_two_step_replacement_runs(kind, caplog):
    db = _WithoutTheFunction()
    doc = db.seed(HEADERS[kind], {"firm_id": FIRM, "status": "draft"})
    table, fk, _ = DOCUMENTS[kind]
    db.seed(table, {fk: doc["id"], "description": "old"})
    db.seed(table, {fk: "another-document", "description": "not ours"})
    with caplog.at_level("WARNING", logger="caflow.services"):
        n = replace_draft_lines(db, kind, doc["id"], FIRM, [{"description": "new", fk: doc["id"]}])
    assert n == 1
    assert sorted((r[fk], r["description"]) for r in db.rows(table)) == sorted([(doc["id"], "new"), ("another-document", "not ours")])
    assert "is not in the database yet" in caplog.text


def test_any_other_error_is_the_callers_and_nothing_is_replaced():
    class Broken(FakeDB):
        def rpc(self, fn, params=None):
            raise Exception("connection reset by peer")

    db = Broken()
    doc = db.seed("client_sales_invoices", {"firm_id": FIRM, "status": "draft"})
    db.seed("client_sales_invoice_lines", {"sales_invoice_id": doc["id"], "description": "old"})
    with pytest.raises(Exception, match="connection reset"):
        replace_draft_lines(db, "sales_invoice", doc["id"], FIRM, [{"description": "new"}])
    assert [r["description"] for r in db.rows("client_sales_invoice_lines")] == ["old"]


# ── THE KINDS MATCH THE SQL ───────────────────────────────────────────────────────────────────────────────────────────

def test_the_helpers_kinds_are_the_functions_case():
    sql = MIGRATION.read_text(encoding="utf-8")
    case = re.findall(r"WHEN '([a-z_]+)'\s+THEN v_header := '([a-z_]+)';\s+v_lines := '([a-z_]+)';\s+v_fk := '([a-z_]+)';", sql)
    assert len(case) == 6, case
    assert {k: (lines, fk) for k, _header, lines, fk in case} == {k: (v[0], v[1]) for k, v in DOCUMENTS.items()}
    assert {k: header for k, header, _l, _f in case} == HEADERS


# ── THE RULE ──────────────────────────────────────────────────────────────────────────────────────────────────────────

#: (file, function) -> why it may delete a document's lines itself. Each removes the lines of a draft it has JUST made, in the same
#: call, to undo a half-built document; none edits a draft someone else may be issuing.
REVIEWED = {
    ("services/draft_document_lines.py", "_two_step"): "the fallback for the hour migration 560 is not in the database; deleted with it",
    ("services/recurring_invoice_service.py", "_stamp_recurring"): "the loser of a unique(template, occurrence) race removes the draft it just generated",
    ("services/recurring_purchase_bill_service.py", "_stamp_recurring"): "the same, for a bill generated from a recurring template",
    ("services/billing_service.py", "_stamp_billing_fields"): "the loser of a unique(schedule, period) race removes the draft invoice it just built",
    ("services/late_interest_service.py", "_delete_draft"): "takes back a draft invoice this module just made when its claim failed",
}


def _deleters() -> set[tuple[str, str]]:
    found = set()
    for table, _fk, _noun in DOCUMENTS.values():
        for rel, text in sources():
            if table not in text:
                continue
            for use_kind, function, _line, _receiver, verbs in uses(text, table):
                if use_kind == "write" and "delete" in verbs:
                    found.add((rel, function))
    return found


def test_the_scan_sees_the_places_that_delete_the_lines_of_a_document():
    assert len(_deleters()) >= 4, "the scan stopped finding deleters; the rule below would pass over nothing"


def test_no_module_deletes_a_documents_lines_except_the_helper_and_the_reviewed_compensations():
    found = _deleters()
    unreviewed = sorted(found - set(REVIEWED))
    stale = sorted(set(REVIEWED) - found)
    assert not unreviewed, (
        f"{unreviewed} delete the lines of an invoice, bill or note. Replacing a draft's lines as a delete and then an insert let an "
        "invoice be issued in between and left it with no lines: call services.draft_document_lines.replace_draft_lines instead, "
        "or, for the compensating delete of a draft you have just made, review it here.")
    assert not stale, f"these reviewed places no longer delete the lines of a document: delete the entries: {stale}"


def test_the_rule_would_catch_a_route_that_went_back_to_delete_then_insert():
    planted = ("def update_invoice(db, invoice_id, lines):\n"
               "    db.table('client_sales_invoice_lines').delete().eq('sales_invoice_id', invoice_id).execute()\n"
               "    db.table('client_sales_invoice_lines').insert(lines).execute()\n")
    assert [(k, f) for k, f, *_ in uses(planted, "client_sales_invoice_lines") if k == "write"] == [("write", "update_invoice")] * 2


# ── THE ROUTE ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_patch_that_finds_the_invoice_issued_meanwhile_answers_409_and_writes_no_header(monkeypatch):
    from models.invoices import InvoiceLineIn, SalesInvoiceUpdateIn
    from routers import sales_invoices
    from tests.test_sales_invoice_lines_fk import _USER, _FakeDB, _Resp

    events: list[dict] = []

    def controller(event):
        if event["table"] == "client_sales_invoices" and event["op"] == "select":
            return _Resp(data=[{"id": "INV-1", "status": "draft", "is_interstate": True}])
        return _Resp(data=[])

    monkeypatch.setattr(sales_invoices, "_USE_MOCK", False)
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: _FakeDB(events, controller))
    monkeypatch.setattr(sales_invoices.period_validation_service, "validate_posting_date", lambda *a, **k: None)
    monkeypatch.setattr(sales_invoices, "log_event", lambda *a, **k: None)

    def issued_meanwhile(*_a, **_k):
        raise HTTPException(status_code=409, detail="This invoice was issued while you were editing it, so its lines were not changed.")

    monkeypatch.setattr(ddl, "replace_draft_lines", issued_meanwhile)
    with pytest.raises(HTTPException) as caught:
        sales_invoices.update_invoice("INV-1", SalesInvoiceUpdateIn(lines=[InvoiceLineIn(
            service_catalogue_id="SVC-1", description="Revised", rate_paise=10000, quantity=1, gst_rate_percent=18.0)]), _USER)
    assert caught.value.status_code == 409
    assert not [e for e in events if e["table"] == "client_sales_invoices" and e["op"] == "update"], \
        "the header was written although the lines were not"
    assert Path(sales_invoices.__file__).exists()
