"""
POST-A-205, slice 1 — one client's books as a ZIP of CSV files, taken by a Partner, with a manifest that says what is in it and what is not.

WHAT THIS ASSERTS
    * the ZIP holds every file the service promises, the manifest names each with its row count and the SHA-256 of exactly the bytes in the file, and README.txt;
    * the client's rows only: another client's and another firm's rows are in no file, the client's own chart AND the firm-level accounts the entries may use are;
    * every state is exported (a draft, a reversed and a soft-deleted entry are rows with their flags), and the trial balance made from the files counts posted,
      non-deleted entries only and is equal to what recomputing it by hand from journal_lines.csv gives;
    * a text cell that would run as a formula is prefixed, a number is not, and the manifest counts the prefixing;
    * a file whose row count differs from what the database counted at the start says so (manifest and problems) and is never smoothed over;
    * a client over the ceilings is refused in words before a row is read, a build that runs out of time is stopped with a sentence, and neither leaves a half-built
      archive behind or masks its own error with a ZIP error;
    * a table larger than the row cap is written whole, in pages, and its children (lines) by chunks of parent ids;
    * the route: Partner-only (`firm:admin`), the client scope, MFA, the audit row first and the download refused without it, an audit row for the outcome, the
      problems header, 503 without a database.
"""
from __future__ import annotations

import ast
import csv
import hashlib
import inspect
import io
import json
import zipfile

import pytest
from fastapi import HTTPException

import routers.data_export as route
import services.client_books_export_service as svc
from core.permissions import PERMISSIONS, Role
from domain.reporting.export_document import ExportRefused
from tests._capped_postgrest import DB_MAX_ROWS, CappedDB
from tests.e2e_harness import FakeDB

FIRM, OTHER_FIRM = "firm-1", "firm-2"
CLIENT, OTHER_CLIENT = "client-a", "client-b"


def _books() -> FakeDB:
    db = FakeDB()
    db.seed("clients", {"id": CLIENT, "firm_id": FIRM, "client_name": "Anand Textiles", "legal_name": "Anand Textiles Pvt Ltd", "pan": "AAACA1234A", "gstin": None})
    db.seed("clients", {"id": OTHER_CLIENT, "firm_id": FIRM, "client_name": "Other Co"})
    # the chart: the client's own, a firm-level account (no client) and another client's
    db.seed("chart_of_accounts", {"id": "a-cash", "firm_id": FIRM, "client_id": CLIENT, "account_code": "1000", "account_name": "Cash", "account_type": "asset"})
    db.seed("chart_of_accounts", {"id": "a-sales", "firm_id": FIRM, "client_id": CLIENT, "account_code": "4000", "account_name": "Sales", "account_type": "income"})
    db.seed("chart_of_accounts", {"id": "a-firm", "firm_id": FIRM, "client_id": None, "account_code": "9000", "account_name": "Firm suspense", "account_type": "asset"})
    db.seed("chart_of_accounts", {"id": "a-other", "firm_id": FIRM, "client_id": OTHER_CLIENT, "account_code": "1000", "account_name": "Other cash", "account_type": "asset"})
    db.seed("chart_of_accounts", {"id": "a-else", "firm_id": OTHER_FIRM, "client_id": CLIENT, "account_code": "1000", "account_name": "Another firm", "account_type": "asset"})
    db.seed("customers", {"id": "cu1", "firm_id": FIRM, "client_id": CLIENT, "name": "=HYPERLINK(\"http://evil\",\"x\")", "gstin": None})
    db.seed("customers", {"id": "cu2", "firm_id": FIRM, "client_id": OTHER_CLIENT, "name": "Not ours"})
    db.seed("vendors", {"id": "v1", "firm_id": FIRM, "client_id": CLIENT, "name": "+91 98765 43210", "phone": "-5"})
    # entries: posted, a draft, a soft-deleted one, another client's
    for eid, posted, deleted, client, firm in (("e1", True, None, CLIENT, FIRM), ("e2", False, None, CLIENT, FIRM), ("e3", True, "2026-01-01T00:00:00Z", CLIENT, FIRM),
                                                ("e4", True, None, OTHER_CLIENT, FIRM), ("e5", True, None, CLIENT, OTHER_FIRM)):
        db.seed("journal_entries", {"id": eid, "firm_id": firm, "client_id": client, "entry_date": "2026-04-05", "is_posted": posted, "deleted_at": deleted,
                                    "narration": "@SUM(A1:A9)" if eid == "e1" else f"entry {eid}", "reference_no": eid.upper()})
    for lid, entry, account, dr, cr in (("l1", "e1", "a-cash", 118000, 0), ("l2", "e1", "a-sales", 0, 100000), ("l3", "e1", "a-firm", 0, 18000),
                                        ("l4", "e2", "a-cash", 5000, 0), ("l5", "e2", "a-sales", 0, 5000),
                                        ("l6", "e3", "a-cash", 7000, 0), ("l7", "e3", "a-sales", 0, 7000),
                                        ("l8", "e4", "a-other", 999, 0), ("l9", "e4", "a-other", 0, 999)):
        db.seed("journal_lines", {"id": lid, "journal_entry_id": entry, "account_id": account, "debit_paise": dr, "credit_paise": cr, "line_order": 1})
    db.seed("client_sales_invoices", {"id": "inv1", "firm_id": FIRM, "client_id": CLIENT, "invoice_no": "INV-1", "total_paise": 118000})
    db.seed("client_sales_invoices", {"id": "inv2", "firm_id": FIRM, "client_id": OTHER_CLIENT, "invoice_no": "INV-X", "total_paise": 1})
    db.seed("client_sales_invoice_lines", {"id": "il1", "sales_invoice_id": "inv1", "description": "Cloth", "quantity": 10})
    db.seed("client_sales_invoice_lines", {"id": "il2", "sales_invoice_id": "inv2", "description": "Not ours", "quantity": 1})
    db.seed("receipts", {"id": "r1", "firm_id": FIRM, "client_id": CLIENT, "amount_paise": 118000})
    db.seed("receipt_allocations", {"id": "ra1", "receipt_id": "r1", "sales_invoice_id": "inv1", "allocated_paise": 118000})
    db.seed("tds_deductions", {"id": "t1", "firm_id": FIRM, "client_id": CLIENT, "section": "194C", "tds_paise": 2000})
    # another FIRM's rows that carry this client's id (the same uuid cannot occur in life; the filter on the firm is what keeps them out if it did)
    db.seed("chart_of_accounts", {"id": "a-else-firm", "firm_id": OTHER_FIRM, "client_id": None, "account_code": "9999", "account_name": "StrangerFirm level account"})
    for table, extra in (("customers", {"name": "StrangerFirm customer"}), ("vendors", {"name": "StrangerFirm vendor"}),
                         ("client_sales_invoices", {"invoice_no": "StrangerFirm-INV"}), ("receipts", {"reference_no": "StrangerFirm-RCT"}),
                         ("tds_deductions", {"deductee_name": "StrangerFirm payee"}), ("tds_returns", {"quarter": "StrangerFirm-Q"})):
        db.seed(table, {"id": f"x-{table}", "firm_id": OTHER_FIRM, "client_id": CLIENT, **extra})
    db.seed("tds_returns", {"id": "tr1", "firm_id": FIRM, "client_id": CLIENT, "return_type": "24Q", "quarter": "Q1",
                            "fvu_json": {"deductees": [{"deductee_name": "Ravi Employee", "deductee_pan": "ABCDE1234F", "payment_amount_paise": 90000000}]}})
    return db


def _unzip(content: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        assert zf.testzip() is None
        return {n: zf.read(n) for n in zf.namelist()}


def _rows(files: dict[str, bytes], name: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(files[name].decode("utf-8-sig"))))


@pytest.fixture
def out():
    return svc.build(_books(), FIRM, CLIENT, exported_by="auth-1")


@pytest.fixture
def files(out):
    return _unzip(out.content)


# ── what is in the archive ───────────────────────────────────────────────────────────────────────────────────

def test_the_archive_holds_every_promised_file_a_manifest_and_a_readme(files):
    promised = {s.file for s in svc._SECTIONS} | {c.file for s in svc._SECTIONS for c in s.children}
    assert promised <= set(files)
    assert {"trial_balance_from_the_ledger_files.csv", "manifest.json", "README.txt"} <= set(files)


def test_the_manifest_names_each_file_with_the_rows_and_the_sha256_of_its_exact_bytes(out, files):
    manifest = json.loads(files["manifest.json"])
    listed = {f["name"]: f for f in manifest["files"]}
    for name, entry in listed.items():
        assert entry["sha256"] == hashlib.sha256(files[name]).hexdigest(), name
        assert entry["bytes"] == len(files[name]), name
        assert entry["rows"] == len(_rows(files, name)), name
    assert manifest["schema"] == svc.SCHEMA and manifest["client"]["name"] == "Anand Textiles Pvt Ltd" and manifest["exported_by"] == "auth-1"
    assert out.manifest["files"] == manifest["files"] and out.problems == []


def test_the_manifest_and_readme_say_what_is_not_here(files):
    manifest = json.loads(files["manifest.json"])
    assert manifest["not_included"] == list(svc.NOT_INCLUDED) and any("Payroll" in line for line in manifest["not_included"])
    readme = files["README.txt"].decode("utf-8")
    assert "WHAT IS NOT HERE" in readme and "Payroll" in readme and "not_a_snapshot" in readme


# ── only this client's rows ──────────────────────────────────────────────────────────────────────────────────

def test_another_clients_and_another_firms_rows_are_in_no_file(files):
    everything = b"".join(v for k, v in files.items() if k.endswith(".csv")).decode("utf-8")
    for stranger in ("Other cash", "Another firm", "Not ours", "INV-X", "a-other", "a-else", "StrangerFirm"):
        assert stranger not in everything, stranger
    assert {r["id"] for r in _rows(files, "journal_entries.csv")} == {"e1", "e2", "e3"}
    assert {r["id"] for r in _rows(files, "journal_lines.csv")} == {"l1", "l2", "l3", "l4", "l5", "l6", "l7"}
    assert [r["id"] for r in _rows(files, "sales_invoice_lines.csv")] == ["il1"]


def test_the_chart_holds_the_clients_accounts_and_the_firm_level_ones_the_entries_may_use(files):
    chart = {r["id"]: r for r in _rows(files, "chart_of_accounts.csv")}
    assert set(chart) == {"a-cash", "a-sales", "a-firm"}, "another firm's firm-level account is not read"
    assert chart["a-firm"]["client_id"] == "", "a firm-level account is exported as such"


# ── every state, and a trial balance the recipient can recompute ─────────────────────────────────────────────

def test_a_draft_and_a_deleted_entry_are_exported_with_the_columns_that_say_so(files):
    entries = {r["id"]: r for r in _rows(files, "journal_entries.csv")}
    assert entries["e2"]["is_posted"] == "false" and entries["e3"]["deleted_at"] != "" and entries["e1"]["is_posted"] == "true"


def test_the_derived_trial_balance_counts_posted_non_deleted_entries_only_and_matches_a_recomputation(files):
    entries = {r["id"]: r for r in _rows(files, "journal_entries.csv")}
    expected: dict[str, list[int]] = {}
    for line in _rows(files, "journal_lines.csv"):
        entry = entries[line["journal_entry_id"]]
        if entry["is_posted"] == "true" and entry["deleted_at"] == "":
            acc = expected.setdefault(line["account_id"], [0, 0])
            acc[0] += int(line["debit_paise"])
            acc[1] += int(line["credit_paise"])
    derived = {r["account_id"]: [int(r["debit_paise"]), int(r["credit_paise"])] for r in _rows(files, "trial_balance_from_the_ledger_files.csv")}
    assert derived == expected == {"a-cash": [118000, 0], "a-sales": [0, 100000], "a-firm": [0, 18000]}
    names = {r["account_id"]: r["account_name"] for r in _rows(files, "trial_balance_from_the_ledger_files.csv")}
    assert names["a-firm"] == "Firm suspense"


def test_the_manifest_checks_say_the_posted_lines_balance(files):
    checks = json.loads(files["manifest.json"])["checks"]
    assert checks["posted_lines_debit_paise"] == checks["posted_lines_credit_paise"] == 118000
    assert checks["posted_lines_balance"] is True and checks["every_counted_file_matches_the_database"] is True


def test_books_that_do_not_balance_are_said_so_and_not_hidden():
    db = _books()
    next(r for r in db.rows("journal_lines") if r["id"] == "l1")["debit_paise"] = 117000
    out = svc.build(db, FIRM, CLIENT)
    assert out.manifest["checks"]["posted_lines_balance"] is False
    assert any("do not balance: debits ₹1,170.00, credits ₹1,180.00." in p for p in out.problems), "a person is told rupees and never a count of paise"
    assert not any(" paise" in p for p in out.problems)


# ── spreadsheets ─────────────────────────────────────────────────────────────────────────────────────────────

def test_a_text_cell_that_would_run_as_a_formula_is_prefixed_and_a_number_is_not(out, files):
    customers = _rows(files, "customers.csv")
    assert customers[0]["name"].startswith("'=HYPERLINK(")
    vendor = _rows(files, "vendors.csv")[0]
    assert vendor["name"] == "'+91 98765 43210", "a phone-like text is text"
    assert vendor["phone"] == "-5", "a plain negative number is a number and is left alone"
    assert _rows(files, "journal_entries.csv")[0]["narration"] in ("'@SUM(A1:A9)", "entry e2", "entry e3")
    assert _rows(files, "journal_lines.csv")[0]["debit_paise"].lstrip("-").isdigit()
    listed = {f["name"]: f for f in out.manifest["files"]}
    assert listed["customers.csv"]["text_cells_prefixed"] == 1 and listed["vendors.csv"]["text_cells_prefixed"] == 1


# ── never silently short ─────────────────────────────────────────────────────────────────────────────────────

def test_a_file_whose_rows_differ_from_the_count_at_the_start_says_so(monkeypatch):
    real = svc._count
    monkeypatch.setattr(svc, "_count", lambda db, section, f, c: (real(db, section, f, c) or 0) + (3 if section.file == "customers.csv" else 0))
    out = svc.build(_books(), FIRM, CLIENT)
    customers = next(f for f in out.manifest["files"] if f["name"] == "customers.csv")
    assert customers["matches_database_count"] is False and customers["database_rows_at_start"] == 4
    assert out.manifest["checks"]["every_counted_file_matches_the_database"] is False
    assert any(p.startswith("customers.csv: 1 rows were written but the database counted 4") for p in out.problems)
    assert out.problems == out.manifest["problems"], "the manifest inside the file carries the same words"


def test_an_empty_table_is_an_empty_file_and_a_row_count_of_zero():
    out = svc.build(_books(), FIRM, CLIENT)
    entry = next(f for f in out.manifest["files"] if f["name"] == "tds_challans.csv")
    assert entry["rows"] == 0 and entry["matches_database_count"] is True and entry["columns"] == []


# ── bounded, in words ────────────────────────────────────────────────────────────────────────────────────────

def test_a_client_with_more_entries_than_the_ceiling_is_refused_before_any_row_is_read():
    db = _books()
    reads: list[str] = []
    real = svc.iter_pages
    svc.iter_pages = lambda *a, **k: reads.append("read") or real(*a, **k)
    try:
        with pytest.raises(ExportRefused) as e:
            svc.build(db, FIRM, CLIENT, max_entries=2)
    finally:
        svc.iter_pages = real
    assert "3 journal entries" in str(e.value) and "nothing was read" in str(e.value) and reads == []


def test_a_client_with_more_rows_in_all_than_the_ceiling_is_refused():
    with pytest.raises(ExportRefused) as e:
        svc.build(_books(), FIRM, CLIENT, max_rows=5)
    assert "rows across the exported tables" in str(e.value)


def test_a_build_that_runs_out_of_time_is_stopped_with_a_sentence_and_the_archive_is_not_left_open():
    ticks = iter(range(0, 10_000, 40))
    with pytest.raises(svc.ExportStopped) as e:
        svc.build(_books(), FIRM, CLIENT, now=lambda: next(ticks), deadline_seconds=90)
    assert "could not finish within 90 seconds" in str(e.value) and "nothing was downloaded" in str(e.value)


def test_a_read_that_fails_in_the_middle_raises_its_own_error_and_not_a_zip_error():
    db = _books()
    real = db.table

    def table(name):
        if name == "journal_lines":
            raise RuntimeError("the database went away")
        return real(name)
    db.table = table
    with pytest.raises(RuntimeError, match="the database went away"):
        svc.build(db, FIRM, CLIENT)


def test_an_unknown_client_is_refused_in_words():
    with pytest.raises(ExportRefused, match="not found"):
        svc.build(_books(), FIRM, "nobody")


# ── a table larger than the row cap ──────────────────────────────────────────────────────────────────────────

def test_a_table_larger_than_the_row_cap_is_written_whole_in_pages_with_its_lines_in_chunks():
    n = DB_MAX_ROWS + 237
    entries = [{"id": f"e{i:05d}", "firm_id": FIRM, "client_id": CLIENT, "entry_date": "2026-04-05", "is_posted": True, "deleted_at": None} for i in range(n)]
    lines = []
    for i in range(n):
        lines.append({"id": f"d{i:05d}", "journal_entry_id": f"e{i:05d}", "account_id": "a1", "debit_paise": 10, "credit_paise": 0})
        lines.append({"id": f"c{i:05d}", "journal_entry_id": f"e{i:05d}", "account_id": "a2", "debit_paise": 0, "credit_paise": 10})
    db = CappedDB({"clients": [{"id": CLIENT, "firm_id": FIRM, "client_name": "Big"}], "journal_entries": entries, "journal_lines": lines,
                   "chart_of_accounts": [{"id": "a1", "firm_id": FIRM, "client_id": CLIENT, "account_code": "1", "account_name": "One"},
                                         {"id": "a2", "firm_id": FIRM, "client_id": CLIENT, "account_code": "2", "account_name": "Two"}]})
    out = svc.build(db, FIRM, CLIENT)
    files = _unzip(out.content)
    assert len(_rows(files, "journal_entries.csv")) == n
    assert len(_rows(files, "journal_lines.csv")) == 2 * n
    assert len(db.requests["journal_entries"]) >= 3, "the entries came in pages"
    assert all(("eq", "firm_id", FIRM) in ops and ("eq", "client_id", CLIENT) in ops for ops in db.requests["journal_entries"] if ("in", "journal_entry_id", None) not in ops)
    tb = {r["account_id"]: (int(r["debit_paise"]), int(r["credit_paise"])) for r in _rows(files, "trial_balance_from_the_ledger_files.csv")}
    assert tb == {"a1": (10 * n, 0), "a2": (0, 10 * n)}
    assert out.manifest["checks"]["posted_lines_balance"] is True


def test_the_service_reads_every_parent_table_through_the_pager_that_yields_pages_and_never_holds_a_table_whole():
    source = inspect.getsource(svc)
    tree = ast.parse(source)
    called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "iter_pages" in called and not ({"fetch_all", "fetch_all_in"} & called), "no table, parent or child, is gathered whole"
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module == "core.db_paging" for a in n.names}
    assert imported == {"IN_CHUNK", "iter_pages"}


# ── the door ─────────────────────────────────────────────────────────────────────────────────────────────────

PARTNER = {"id": "u1", "auth_user_id": "auth-1", "email": "p@firm.test", "firm_id": FIRM, "role": "Partner"}


@pytest.fixture
def door(monkeypatch):
    audit = FakeDB()
    import core.supabase_client as sc
    monkeypatch.setattr(sc, "get_service_supabase", lambda: audit)
    monkeypatch.setattr(route, "assert_client_access", lambda user, client_id: None)
    monkeypatch.setattr(route, "_prod_db", lambda: _books())
    logged: list[tuple] = []
    monkeypatch.setattr(route.audit_service, "log_event", lambda firm, kind, entity, action, **kw: logged.append((action, kw)))
    return audit, logged


def test_a_partner_gets_the_zip_with_an_audit_row_before_and_after(door):
    audit, logged = door
    response = route.export_client_books(client_id=CLIENT, current_user=PARTNER)
    assert response.media_type == "application/zip"
    assert response.headers["content-disposition"].startswith('attachment; filename="books-anand-textiles-')
    assert "x-export-problems" not in response.headers
    assert {"manifest.json", "journal_entries.csv"} <= set(_unzip(response.body))
    [first] = audit.rows("audit_log")
    assert (first["entity_type"], first["action"], first["entity_id"], first["actor_id"]) == ("client_books_export", "export_requested", CLIENT, "auth-1")
    assert [a for a, _ in logged] == ["export_completed"]
    assert logged[0][1]["actor_id"] == "auth-1" and logged[0][1]["metadata"] == {"client_id": CLIENT}
    assert logged[0][1]["new_data"]["problems"] == 0 and logged[0][1]["new_data"]["rows"] > 0


def test_the_download_is_refused_when_the_audit_row_cannot_be_written(monkeypatch):
    import core.supabase_client as sc

    class Broken:
        def table(self, name):
            raise RuntimeError("audit store down")
    monkeypatch.setattr(sc, "get_service_supabase", lambda: Broken())
    monkeypatch.setattr(route, "assert_client_access", lambda user, client_id: None)
    monkeypatch.setattr(route, "_prod_db", lambda: _books())
    monkeypatch.setattr(route.books, "build", lambda *a, **k: (_ for _ in ()).throw(AssertionError("read a row without an audit row")))
    with pytest.raises(HTTPException) as e:
        route.export_client_books(client_id=CLIENT, current_user=PARTNER)
    assert e.value.status_code == 503 and "Nothing was exported" in e.value.detail


def test_a_refusal_is_a_422_with_its_sentence_and_leaves_an_audit_row(door, monkeypatch):
    audit, logged = door
    monkeypatch.setattr(route.books, "build", lambda *a, **k: (_ for _ in ()).throw(ExportRefused("This client has 99,999 journal entries.")))
    with pytest.raises(HTTPException) as e:
        route.export_client_books(client_id=CLIENT, current_user=PARTNER)
    assert e.value.status_code == 422 and "99,999" in e.value.detail
    assert [a for a, _ in logged] == ["export_refused"] and len(audit.rows("audit_log")) == 1


def test_a_build_that_runs_out_of_time_is_a_503(door, monkeypatch):
    _, logged = door
    monkeypatch.setattr(route.books, "build", lambda *a, **k: (_ for _ in ()).throw(svc.ExportStopped("could not finish within 90 seconds")))
    with pytest.raises(HTTPException) as e:
        route.export_client_books(client_id=CLIENT, current_user=PARTNER)
    assert e.value.status_code == 503 and [a for a, _ in logged] == ["export_stopped"]


def test_an_unexpected_failure_is_a_500_in_words_and_is_logged(door, monkeypatch):
    _, logged = door
    monkeypatch.setattr(route.books, "build", lambda *a, **k: (_ for _ in ()).throw(KeyError("secret column name")))
    with pytest.raises(HTTPException) as e:
        route.export_client_books(client_id=CLIENT, current_user=PARTNER)
    assert e.value.status_code == 500 and "secret column name" not in e.value.detail and [a for a, _ in logged] == ["export_failed"]


def test_the_problems_the_build_found_travel_in_a_header(door, monkeypatch):
    real = svc._count
    monkeypatch.setattr(svc, "_count", lambda db, section, f, c: (real(db, section, f, c) or 0) + (1 if section.file == "vendors.csv" else 0))
    response = route.export_client_books(client_id=CLIENT, current_user=PARTNER)
    assert response.headers["x-export-problems"] == "1 problem(s) found; see manifest.json inside the file"


def test_without_a_database_it_is_a_503_and_writes_no_audit_row(door, monkeypatch):
    audit, logged = door
    monkeypatch.setattr(route, "_prod_db", lambda: None)
    with pytest.raises(HTTPException) as e:
        route.export_client_books(client_id=CLIENT, current_user=PARTNER)
    assert e.value.status_code == 503 and audit.rows("audit_log") == [] and logged == []


def test_a_client_the_caller_may_not_reach_is_refused_before_anything_is_written(door, monkeypatch):
    audit, logged = door

    def refuse(user, client_id):
        raise HTTPException(status_code=404, detail="Client not found")
    monkeypatch.setattr(route, "assert_client_access", refuse)
    with pytest.raises(HTTPException) as e:
        route.export_client_books(client_id=CLIENT, current_user=PARTNER)
    assert e.value.status_code == 404 and audit.rows("audit_log") == [] and logged == []


# ── who may ask ──────────────────────────────────────────────────────────────────────────────────────────────

def test_only_a_partner_holds_the_permission_the_door_asks():
    assert PERMISSIONS["firm"]["admin"] == {Role.PARTNER}
    tree = ast.parse(inspect.getsource(route))
    asks = [(n.args[0].value, n.args[1].value)
            for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "rbac"]
    assert asks == [("firm", "admin")]


def test_the_router_is_mounted_behind_the_client_scope_and_the_two_factor_guard():
    import pathlib
    main = pathlib.Path(__file__).resolve().parent.parent / "main.py"
    tree = ast.parse(main.read_text(encoding="utf-8"))
    mounts = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "include_router"
              and n.args and isinstance(n.args[0], ast.Name) and n.args[0].id == "data_export_router"]
    assert len(mounts) == 1
    dependencies = ast.unparse(next(k.value for k in mounts[0].keywords if k.arg == "dependencies"))
    assert dependencies == "_CLIENT_GUARD + _MFA_GUARD"
    assert '"X-Export-Problems"' in main.read_text(encoding="utf-8"), "a browser can read the header only if CORS exposes it"


# ── what the independent read found ──────────────────────────────────────────────────────────────────────────

def test_the_body_of_a_saved_tds_statement_is_left_out_because_it_names_employees(files):
    returns = _rows(files, "tds_returns.csv")
    assert [r["id"] for r in returns] == ["tr1"] and "fvu_json" not in returns[0]
    everything = b"".join(v for k, v in files.items() if k.endswith(".csv")).decode("utf-8-sig")
    assert "Ravi Employee" not in everything and "ABCDE1234F" not in everything
    entry = next(f for f in json.loads(files["manifest.json"])["files"] if f["name"] == "tds_returns.csv")
    assert entry["columns_not_exported"] == ["fvu_json"] and "fvu_json" not in entry["columns"]


def test_the_not_included_list_is_a_rule_and_names_the_tables_the_files_point_at(files):
    manifest = json.loads(files["manifest.json"])
    assert manifest["not_included"][0].startswith("Only the files listed in manifest.json are here")
    text = " ".join(manifest["not_included"])
    for named in ("customer and vendor advances", "loans", "cost centres", "service catalogue", "delivery challans", "section 192"):
        assert named in text, named
    assert any("cost_centre_id" in line for line in manifest["ids_that_lead_to_tables_not_in_the_export"])
    assert "IDS IN THESE FILES THAT LEAD TO TABLES THAT ARE NOT HERE" in files["README.txt"].decode("utf-8")


def test_a_posted_entry_with_no_line_is_named_because_it_is_damage_or_a_short_read():
    db = _books()
    db._tables["journal_lines"] = [r for r in db.rows("journal_lines") if r["journal_entry_id"] != "e1"]
    out = svc.build(db, FIRM, CLIENT)
    assert out.manifest["checks"]["posted_entries_without_a_line"] == 1
    assert any("1 posted entries have no line in journal_lines.csv" in p for p in out.problems)


def test_the_manifest_says_how_many_main_files_the_database_counted(files, monkeypatch):
    checks = json.loads(files["manifest.json"])["checks"]
    total = len(svc._SECTIONS)
    assert checks["main_files_counted_by_the_database"] == f"{total} of {total}"
    monkeypatch.setattr(svc, "_count", lambda db, section, f, c: None)
    out = svc.build(_books(), FIRM, CLIENT)
    assert out.manifest["checks"]["main_files_counted_by_the_database"] == f"0 of {total}"
    assert any(f"did not report a row count for {total} of the {total} main files" in p for p in out.problems)


def test_a_file_starts_with_a_byte_order_mark_so_a_spreadsheet_reads_the_rupee_sign(files):
    assert files["customers.csv"].startswith(b"\xef\xbb\xbf") and files["tds_challans.csv"] == b""


def test_only_ascii_digits_make_a_number_and_a_trailing_newline_does_not():
    assert svc._PLAIN_NUMBER.fullmatch("-5") and svc._PLAIN_NUMBER.fullmatch("+12.50")
    assert not svc._PLAIN_NUMBER.fullmatch("-5\n") and not svc._PLAIN_NUMBER.fullmatch("-\u0663")


def test_a_child_is_read_a_page_at_a_time_with_the_clock_asked_for_each_request():
    n = DB_MAX_ROWS + 5
    entries = [{"id": f"e{i:05d}", "firm_id": FIRM, "client_id": CLIENT, "is_posted": True, "deleted_at": None} for i in range(n)]
    lines = [{"id": f"l{i:05d}", "journal_entry_id": f"e{i:05d}", "account_id": "a1", "debit_paise": 1, "credit_paise": 1} for i in range(n)]
    db = CappedDB({"clients": [{"id": CLIENT, "firm_id": FIRM, "client_name": "Big"}], "journal_entries": entries, "journal_lines": lines})
    asked = []
    out = svc.build(db, FIRM, CLIENT, now=lambda: asked.append(1) or 0.0)
    assert len(_rows(_unzip(out.content), "journal_lines.csv")) == n
    assert len(db.requests["journal_lines"]) >= n // 150, "150 parents per request, as the filter list can hold"
    assert len(asked) > len(db.requests["journal_lines"]), "the deadline was asked at least once per request"


# ── the door: who, and one at a time ─────────────────────────────────────────────────────────────────────────

EXECUTIVE_WITH_A_GRANT = {"id": "u2", "auth_user_id": "auth-2", "email": "e@firm.test", "firm_id": FIRM, "role": "Executive"}


def test_a_member_who_was_granted_the_permission_but_is_not_a_partner_is_refused(door):
    audit, logged = door
    with pytest.raises(HTTPException) as e:
        route.export_client_books(client_id=CLIENT, current_user=EXECUTIVE_WITH_A_GRANT)
    assert e.value.status_code == 403 and "Partner" in e.value.detail
    assert audit.rows("audit_log") == [] and logged == [] and route._running == set()


def test_an_empty_client_id_is_a_422_before_anything_is_written():
    import main
    spec = main.app.openapi()["paths"]["/api/data-export/client-books"]["get"]["parameters"]
    [param] = [p for p in spec if p["name"] == "client_id"]
    assert param["required"] is True and param["schema"]["minLength"] == 1


def test_a_second_export_for_the_same_firm_is_refused_while_one_is_running_and_the_lock_is_always_let_go(door, monkeypatch):
    audit, _ = door
    route._running.add(FIRM)
    try:
        with pytest.raises(HTTPException) as e:
            route.export_client_books(client_id=CLIENT, current_user=PARTNER)
        assert e.value.status_code == 409 and audit.rows("audit_log") == []
    finally:
        route._running.discard(FIRM)
    route.export_client_books(client_id=CLIENT, current_user=PARTNER)
    assert route._running == set(), "released after a success"
    monkeypatch.setattr(route.books, "build", lambda *a, **k: (_ for _ in ()).throw(KeyError("x")))
    with pytest.raises(HTTPException):
        route.export_client_books(client_id=CLIENT, current_user=PARTNER)
    assert route._running == set(), "released after a failure"


def test_the_file_is_never_cached_and_the_audit_row_carries_the_files_own_hash(door):
    _, logged = door
    response = route.export_client_books(client_id=CLIENT, current_user=PARTNER)
    assert response.headers["cache-control"] == "private, no-store"
    assert logged[-1][1]["new_data"]["zip_sha256"] == hashlib.sha256(response.body).hexdigest()
