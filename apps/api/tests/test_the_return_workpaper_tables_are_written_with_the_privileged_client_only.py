"""The twelve return-workpaper and stock-count tables are written with the privileged client, and by nothing else (ledger POST-A-323).

THE DEFECT
    GSTR-4 annual (four tables), GSTR-9C (three), the e-commerce operator's two, `rcm_documents` and the two stock-count tables were
    created with `GRANT SELECT ... TO authenticated` and `ALL ... TO service_role` and nothing else. Read from production on
    28-10-2026: the signed-in role holds no INSERT, UPDATE or DELETE on any of the twelve, at table level or column level, and each
    has one write policy that only the service role reaches. Their routers, however, wrote with `get_supabase()`, which under
    `USE_USER_JWT` (on in production since 15-08-2026) is the CALLER's session, so every save, withdrawal, issue and count on
    those screens would be refused with 42501 the first time a CA used it while every double accepts any caller. None of the twelve
    holds a row in production, which is why nobody had seen it: no practice has used them yet. The ledger worried about the
    opposite direction (a signed-in member writing them directly); the grants already rule that out, so this is the other half:
    the writers have to be on the client that can write.

WHAT IS HELD (no database)
    * (source, derived from the AST of every module of the API, `scripts/` included) the only code that writes the twelve tables is
      the five services named below, and EVERY write in them is made on `privileged_for(db)`, the client that is privileged
      wherever a database is configured, is labelled with the person of the request so the audit trigger still names them, and is
      the caller's own only where there is no database (mock mode); a query kept in a variable, a table name held in a constant,
      `.from_`, a module-level statement and SQL text are each shown to the detector and each must fire;
    * the privileged client carries no row security, so each write names the firm AND the client: an insert carries both in its row,
      an update or a delete filters on both;
    * driven through a request client that REFUSES these tables' writes the way `authenticated` does, a save, a correction, a
      withdrawal and an issue on each table still lands, on the privileged client, with the firm and the client on the row, and the
      request's client is never asked to write.

THE TWO GSTR-8 AMENDMENT TABLES CANNOT EVEN BE READ BY A SIGNED-IN SESSION (POST-A-056, migration 617)
    The twelve keep `SELECT` for `authenticated`; migration 617 revokes ALL on Table 4's and Table 4.1's tables and grants the service
    role alone. A first version still READ them on the caller's session (the two lists, the GSTR-8 build and the upsert's own lookup),
    which every double accepted and production would have refused with 42501, taking the Table 3 and 3.1 rows that work today down
    with the screen and the statement. So for those two the rule is every query, a read as well as a write: each starts at
    `privileged_for(db)` and filters on the firm and the client, and the refusing double refuses a read of them as the database would.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

import core.db_provider
from tests._table_uses import WRITE_VERBS, sources as _sources, uses as _uses
from tests.e2e_harness import FakeDB

TABLES = (
    "gstr4_annual_b2b_supplies", "gstr4_annual_b2b_rc_supplies", "gstr4_annual_urp_supplies", "gstr4_annual_import_of_services",
    "gstr9c_reconciliations", "gstr9c_rate_wise_lines", "gstr9c_expense_lines",
    "ecommerce_operator_supplies", "ecommerce_operator_unregistered_supplies",
    "ecommerce_operator_supply_amendments", "ecommerce_operator_unregistered_supply_amendments",
    "rcm_documents", "stock_count_sessions", "stock_count_lines",
)
#: The two tables migration 617 gives NO privilege at all to a signed-in session (the other twelve keep SELECT): a read is refused too.
UNREADABLE_TO_A_SIGNED_IN_SESSION = ("ecommerce_operator_supply_amendments", "ecommerce_operator_unregistered_supply_amendments")
WRITER_FILES = {
    "services/gstr4_annual_service.py", "services/gstr9c_service.py", "services/ecommerce_operator_service.py",
    "services/rcm_document_service.py", "services/stock_count_service.py",
}
API = Path(__file__).resolve().parent.parent
FIRM, CLIENT, OTHER = "firm-wp-1", "client-wp-1", "client-wp-2"


# ── the source ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
def _writes() -> tuple[list[tuple[str, str, str, int, str]], list]:
    """(file, function, table, line, receiver) for every write, and the places the detector cannot read."""
    found, hidden = [], []
    for rel, text in _sources():
        lines = text.splitlines()
        for table in TABLES:
            if table not in text:
                continue
            for kind, fn, line, receiver, _verbs in _uses(text, table):
                if kind == "write":
                    found.append((rel, fn, table, line, ast.unparse(receiver)))
                elif kind == "named" and any(mark in lines[line - 1] for mark in ("label=", "tags=")):
                    continue                  # `fetch_all(..., label="<table>")` and a router's `tags=[...]` are labels, not handles
                elif kind in {"unchained", "named", "raw_write"}:
                    hidden.append((rel, line, table, kind))
    return found, hidden


def test_only_the_five_services_write_the_twelve_tables_and_no_spelling_hides_a_write():
    found, hidden = _writes()
    assert not hidden, (f"these places name a return-workpaper table in a way the guard cannot read ({hidden}): a query kept in a "
                        "variable, the name held in a constant, or SQL text. Chain the verb off `.table(\"<table>\")` where it is used.")
    assert {rel for rel, *_ in found} == WRITER_FILES, sorted({rel for rel, *_ in found})
    assert {t for _r, _f, t, *_ in found} == set(TABLES), "a table in the list is written by nothing, or the scan has gone blind"
    assert len(found) >= 29, f"{len(found)} writes found; the scan has stopped reading the services"


def test_the_guard_sees_every_shape_a_write_can_take():
    for table in TABLES:
        shapes = {
            "a query kept in a variable": f'def f(db):\n    q = db.table("{table}")\n    q.update({{}}).execute()\n',
            "the name held in a constant": f'T = "{table}"\n\ndef f(db):\n    db.table(T).delete().execute()\n',
            "from_ instead of table": f'def f(db):\n    db.from_("{table}").insert({{}}).execute()\n',
            "a statement at module level": f'client.table("{table}").update({{}}).execute()\n',
            "an upsert": f'def f(db):\n    db.table("{table}").upsert({{}}).execute()\n',
            "raw SQL": f'def f(cur):\n    cur.execute("DELETE FROM public.{table} WHERE true")\n',
        }
        for label, source in shapes.items():
            kinds = {k for k, *_ in _uses(source, table)}
            assert kinds & {"write", "unchained", "named", "raw_write"}, f"the guard is blind to: {label} ({table})"


def test_every_write_is_made_on_the_privileged_client():
    found, _ = _writes()
    wrong = [(rel, fn, table, line, receiver) for rel, fn, table, line, receiver in found if receiver != "privileged_for(db)"]
    assert not wrong, f"these writes use the caller's own session, which the signed-in role has no grant to write with: {wrong}"


def test_a_write_on_the_callers_session_is_what_the_check_above_reports():
    text = 'def f(db):\n    db.table("gstr9c_reconciliations").update({}).eq("id", 1).execute()\n'
    receivers = [ast.unparse(r) for kind, _fn, _l, r, _v in _uses(text, "gstr9c_reconciliations") if kind == "write"]
    assert receivers == ["db"] and receivers != ["privileged_for(db)"]


def _statements():
    """(file, line, function, table, verb, the source of the whole chain the write sits in) for every write of the five services."""
    out = []
    for rel in sorted(WRITER_FILES):
        tree = ast.parse((API / rel).read_text(encoding="utf-8"))
        parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef):
                continue
            for node in ast.walk(fn):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in WRITE_VERBS:
                    probe, table = node.func.value, None
                    while isinstance(probe, ast.Call) and isinstance(probe.func, ast.Attribute):
                        if probe.func.attr == "table" and probe.args and isinstance(probe.args[0], ast.Constant) \
                                and probe.args[0].value in TABLES:
                            table = probe.args[0].value
                        probe = probe.func.value
                    if table:
                        top = node                      # `.insert({...}).execute()`, `.update({...}).eq(..).eq(..).execute()`
                        while top in parents and isinstance(parents[top], (ast.Attribute, ast.Call)):
                            top = parents[top]
                        out.append((rel, node.lineno, fn.name, table, node.func.attr, ast.unparse(top)))
    return out


def test_each_write_names_the_firm_and_the_client_because_the_privileged_client_has_no_row_security():
    statements = _statements()
    assert len(statements) >= 29, len(statements)
    for rel, line, fn, table, verb, whole in statements:
        assert "firm_id" in whole and "client_id" in whole, f"{rel}:{line} {fn} writes {table} without naming both: {whole[:160]}"
        if verb in {"update", "delete"}:
            assert ".eq('firm_id'" in whole and ".eq('client_id'" in whole, f"{rel}:{line} {fn}: a filter is missing on this {verb}"


def _reads_of_the_unreadable_tables() -> list[tuple[str, str, str, int, str]]:
    """(file, function, table, line, receiver) for every read of the two tables no signed-in session may read, in every module."""
    found = []
    for rel, text in _sources():
        for table in UNREADABLE_TO_A_SIGNED_IN_SESSION:
            if table in text:
                found += [(rel, fn, table, line, ast.unparse(receiver))
                          for kind, fn, line, receiver, _verbs in _uses(text, table) if kind == "read"]
    return found


def test_every_read_of_the_two_gstr_8_amendment_tables_is_made_on_the_privileged_client():
    found = _reads_of_the_unreadable_tables()
    assert {t for _r, _f, t, *_ in found} == set(UNREADABLE_TO_A_SIGNED_IN_SESSION), "a table is read by nothing, or the scan is blind"
    assert len(found) >= 4, f"{len(found)} reads found; the scan has stopped reading the service"
    wrong = [row for row in found if row[4] != "privileged_for(db)"]
    assert not wrong, ("these reads use the caller's own session, on a table migration 617 gives a signed-in session no privilege on "
                       f"at all, so production refuses them with 42501 (read with `privileged_for(db)`): {wrong}")


def test_a_read_on_the_callers_session_is_what_the_check_above_reports():
    for text in ('def f(db):\n    return db.table("ecommerce_operator_supply_amendments").select("id").eq("id", 1).execute()\n',
                 'def f(db):\n    return fetch_all(lambda: db.table("ecommerce_operator_unregistered_supply_amendments").select("id"),'
                 ' key="id", label="ecommerce_operator_unregistered_supply_amendments")\n'):
        table = next(t for t in UNREADABLE_TO_A_SIGNED_IN_SESSION if f'"{t}"' in text)
        assert [ast.unparse(r) for kind, _fn, _l, r, _v in _uses(text, table) if kind == "read"] == ["db"]


def test_each_read_of_the_two_amendment_tables_names_the_firm_and_the_client_because_the_privileged_client_has_no_row_security():
    rel = "services/ecommerce_operator_service.py"
    tree = ast.parse((API / rel).read_text(encoding="utf-8"))
    parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    reads = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "table"
                and node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value in UNREADABLE_TO_A_SIGNED_IN_SESSION):
            continue
        top = node
        while top in parents and isinstance(parents[top], (ast.Attribute, ast.Call)):
            top = parents[top]
        whole = ast.unparse(top)
        if not any(f".{verb}(" in whole for verb in WRITE_VERBS):
            reads.append((node.lineno, whole))
    assert len(reads) >= 4, reads
    for line, whole in reads:
        assert ".eq('firm_id'" in whole and ".eq('client_id'" in whole, f"{rel}:{line} reads without naming both: {whole[:160]}"


# ── the behaviour ──────────────────────────────────────────────────────────────────────────────────────────────────────────
class _Authenticated(FakeDB):
    """The request's client: shares the store with the privileged one and refuses the twelve tables' writes the way the signed-in role
    is refused in production, and a READ of the two amendment tables too, on which migration 617 leaves it no privilege at all. A
    refusal is recorded BEFORE it raises, so a query left on this client is seen even where the caller swallows the error."""

    def __init__(self, shared: FakeDB):
        super().__init__()
        self._tables = shared._tables
        self.refused: list[tuple[str, str]] = []

    def table(self, name):
        query = super().table(name)
        if name in TABLES:
            for verb in WRITE_VERBS | ({"select"} if name in UNREADABLE_TO_A_SIGNED_IN_SESSION else set()):
                def refuse(*_a, _verb=verb, **_k):
                    self.refused.append((name, _verb))
                    raise RuntimeError(f"permission denied for table {name}")
                setattr(query, verb, refuse)
        return query


@pytest.fixture()
def world(monkeypatch):
    privileged = FakeDB()
    request = _Authenticated(privileged)
    monkeypatch.setattr(core.db_provider, "service_db_or_none", lambda: privileged)
    return privileged, request


def _only(db: FakeDB, table: str) -> list[dict]:
    return [r for r in db.rows(table) if not r.get("deleted_at")]


def test_the_refusing_double_refuses_every_write_verb_on_these_tables_and_only_there():
    shared = FakeDB()
    request = _Authenticated(shared)
    for table in TABLES:
        for verb in sorted(WRITE_VERBS):
            with pytest.raises(RuntimeError, match="permission denied"):
                getattr(request.table(table), verb)({})
    request.table("vendors").insert({"id": "v1", "firm_id": FIRM}).execute()          # not protected: allowed
    assert [r["id"] for r in shared.rows("vendors")] == ["v1"]
    for table in UNREADABLE_TO_A_SIGNED_IN_SESSION:                                   # migration 617: not even a read
        with pytest.raises(RuntimeError, match="permission denied"):
            request.table(table).select("id")
    assert request.table("ecommerce_operator_supplies").select("id").execute().data == []   # the twelve keep SELECT: allowed


GSTIN = "27AAPFU0939F1ZV"
FOUR = [
    ("gstr4_annual_b2b_supplies", "record_b2b_supply", "delete_b2b_supply",
     dict(supplier_gstin="29ABCDE1234F1Z5", place_of_supply="29", rate_bps=1800, taxable_value_paise=1000)),
    ("gstr4_annual_b2b_rc_supplies", "record_b2b_rc_supply", "delete_b2b_rc_supply",
     dict(supplier_gstin="29ABCDE1234F1Z5", place_of_supply="29", rate_bps=1800, taxable_value_paise=1000)),
    ("gstr4_annual_urp_supplies", "record_urp_supply", "delete_urp_supply",
     dict(counterparty_pan="ABCDE1234F", place_of_supply="29", rate_bps=1800, taxable_value_paise=1000)),
    ("gstr4_annual_import_of_services", "record_import_of_service", "delete_import_of_service",
     dict(place_of_supply="96", rate_bps=1800, taxable_value_paise=1000)),
]


@pytest.mark.parametrize("table,record,delete,extra", FOUR, ids=[f[0] for f in FOUR])
def test_a_gstr4_annual_entry_is_saved_corrected_and_withdrawn_on_the_privileged_client(world, table, record, delete, extra):
    from services import gstr4_annual_service as svc
    privileged, request = world
    save, withdraw = getattr(svc, record), getattr(svc, delete)
    first = save(request, FIRM, CLIENT, gstin=GSTIN, financial_year="2025-26", **extra)
    again = save(request, FIRM, CLIENT, gstin=GSTIN, financial_year="2025-26", **{**extra, "taxable_value_paise": 2000})
    assert first["id"] == again["id"] and len(_only(privileged, table)) == 1
    assert _only(privileged, table)[0]["taxable_value_paise"] == 2000
    assert (_only(privileged, table)[0]["firm_id"], _only(privileged, table)[0]["client_id"]) == (FIRM, CLIENT)
    withdraw(request, FIRM, CLIENT, first["id"])
    assert _only(privileged, table) == []
    assert request.refused == [], "a writer used the request's own client"


def test_a_gstr9c_reconciliation_and_its_lines_are_written_on_the_privileged_client(world):
    from services import gstr9c_service as svc
    privileged, request = world
    rec = svc.save_reconciliation(request, FIRM, CLIENT, gstin=GSTIN, financial_year="2025-26", turnover_per_audited_fs_paise=100)
    svc.save_reconciliation(request, FIRM, CLIENT, gstin=GSTIN, financial_year="2025-26", turnover_per_audited_fs_paise=200)
    assert [r["turnover_per_audited_fs_paise"] for r in _only(privileged, "gstr9c_reconciliations")] == [200]
    rate = svc.add_rate_wise_line(request, FIRM, CLIENT, rec["id"], table_ref="9", rate_description="18%", taxable_value_paise=5)
    expense = svc.add_expense_line(request, FIRM, CLIENT, rec["id"], expense_head="Rent", value_paise=5)
    assert len(_only(privileged, "gstr9c_rate_wise_lines")) == len(_only(privileged, "gstr9c_expense_lines")) == 1
    svc.delete_rate_wise_line(request, FIRM, CLIENT, rate["id"])
    svc.delete_expense_line(request, FIRM, CLIENT, expense["id"])
    assert _only(privileged, "gstr9c_rate_wise_lines") == [] and _only(privileged, "gstr9c_expense_lines") == []
    for table in ("gstr9c_reconciliations", "gstr9c_rate_wise_lines", "gstr9c_expense_lines"):
        assert all((r["firm_id"], r["client_id"]) == (FIRM, CLIENT) for r in privileged.rows(table))
    assert request.refused == []


def test_an_ecommerce_operator_entry_is_written_on_the_privileged_client(world):
    from services import ecommerce_operator_service as svc
    privileged, request = world
    supply = svc.record_supply(request, FIRM, CLIENT, gstin=GSTIN, period="2026-04", supplier_gstin="29ABCDE1234F1Z5",
                               place_of_supply="29", gross_registered_paise=100)
    svc.record_supply(request, FIRM, CLIENT, gstin=GSTIN, period="2026-04", supplier_gstin="29ABCDE1234F1Z5",
                      place_of_supply="29", gross_registered_paise=300)
    assert [r["gross_registered_paise"] for r in _only(privileged, "ecommerce_operator_supplies")] == [300]
    unreg = svc.record_unregistered_supply(request, FIRM, CLIENT, gstin=GSTIN, period="2026-04", enrolment_id="E1", gross_value_paise=10)
    svc.record_unregistered_supply(request, FIRM, CLIENT, gstin=GSTIN, period="2026-04", enrolment_id="E1", gross_value_paise=30)
    assert [r["gross_value_paise"] for r in _only(privileged, "ecommerce_operator_unregistered_supplies")] == [30]
    svc.delete_supply(request, FIRM, CLIENT, supply["id"])
    svc.delete_unregistered_supply(request, FIRM, CLIENT, unreg["id"])
    assert _only(privileged, "ecommerce_operator_supplies") == [] and _only(privileged, "ecommerce_operator_unregistered_supplies") == []
    assert request.refused == []


def test_a_gstr_8_amendment_is_written_on_the_privileged_client(world):
    """POST-A-056, migration 617: the two amendment tables hold no signed-in privilege at all, so the one writer is the privileged client."""
    from services import ecommerce_operator_service as svc
    privileged, request = world
    keys = dict(gstin=GSTIN, period="062026", original_period="042026", original_supplier_gstin="29ABCDE1234F1Z5",
                original_place_of_supply="29", supplier_gstin="29ABCDE1234F1Z5", place_of_supply="29", action="add")
    amend = svc.record_amendment(request, FIRM, CLIENT, gross_registered_paise=100, **keys)
    svc.record_amendment(request, FIRM, CLIENT, gross_registered_paise=300, **keys)
    assert [r["gross_registered_paise"] for r in _only(privileged, "ecommerce_operator_supply_amendments")] == [300], "same key updates"
    other = svc.record_amendment(request, FIRM, CLIENT, gross_registered_paise=7, **{**keys, "original_supplier_gstin": "27AAAAA0000A1Z5"})
    assert len(_only(privileged, "ecommerce_operator_supply_amendments")) == 2 and other["id"] != amend["id"]
    ukeys = dict(gstin=GSTIN, period="062026", original_period="042026", original_enrolment_id="E1", enrolment_id="E1", action="delete")
    unreg = svc.record_unregistered_amendment(request, FIRM, CLIENT, gross_value_paise=10, **ukeys)
    svc.record_unregistered_amendment(request, FIRM, CLIENT, gross_value_paise=30, **ukeys)
    assert [r["gross_value_paise"] for r in _only(privileged, "ecommerce_operator_unregistered_supply_amendments")] == [30]
    svc.delete_amendment(request, FIRM, CLIENT, amend["id"])
    svc.delete_amendment(request, FIRM, CLIENT, other["id"])
    svc.delete_unregistered_amendment(request, FIRM, CLIENT, unreg["id"])
    assert _only(privileged, "ecommerce_operator_supply_amendments") == []
    assert _only(privileged, "ecommerce_operator_unregistered_supply_amendments") == []
    assert request.refused == []


def test_a_gstr_8_amendment_is_listed_and_the_statement_built_on_the_privileged_client(world, monkeypatch):
    """The screen's list (`GET /supplies`) and the GSTR-8 build read the two tables a signed-in session cannot read at all, so both
    read them on the privileged client, naming the firm and the client: a sibling client's row is not in either answer."""
    from types import SimpleNamespace

    import services.client_gst_registration_service as regs
    from domain.gst.registrations import TCS_COLLECTOR
    from services import ecommerce_operator_service as svc
    from services import gst_return_service as grs
    privileged, request = world
    keys = dict(gstin=GSTIN, period="062026", original_period="042026", original_supplier_gstin="29ABCDE1234F1Z5",
                original_place_of_supply="29", supplier_gstin="29ABCDE1234F1Z5", place_of_supply="29", action="add")
    svc.record_amendment(request, FIRM, CLIENT, gross_registered_paise=1_000, igst_paise=10, **keys)
    svc.record_amendment(request, FIRM, OTHER, gross_registered_paise=9_999, igst_paise=99, **keys)
    ukeys = dict(gstin=GSTIN, period="062026", original_period="042026", original_enrolment_id="E1", enrolment_id="E1", action="add")
    svc.record_unregistered_amendment(request, FIRM, CLIENT, gross_value_paise=500, **ukeys)
    svc.record_supply(request, FIRM, CLIENT, gstin=GSTIN, period="062026", supplier_gstin="29ABCDE1234F1Z5",
                      place_of_supply="29", gross_registered_paise=100)

    listed = svc.list_amendments(request, FIRM, CLIENT, GSTIN, "062026")
    assert [(r["client_id"], r["net_liable_paise"]) for r in listed] == [(CLIENT, 1_000)]
    unlisted = svc.list_unregistered_amendments(request, FIRM, CLIENT, GSTIN, "062026")
    assert [(r["client_id"], r["net_liable_paise"]) for r in unlisted] == [(CLIENT, 500)]

    monkeypatch.setattr(regs, "resolve", lambda _db, _firm, _client, gstin=None: SimpleNamespace(
        gstin=gstin or GSTIN, registration_type=TCS_COLLECTOR))
    out = grs.gstr8_statement(request, FIRM, CLIENT, "062026", GSTIN)
    assert (out["amendment_count"], out["unregistered_amendment_count"], out["supplier_count"]) == (1, 1, 1)
    assert request.refused == [], "a query of a table the signed-in role cannot read was made on the request's own client"


def test_a_stock_count_sheet_is_opened_saved_and_posted_on_the_privileged_client(world, monkeypatch):
    from services import stock_count_service as svc
    privileged, request = world
    privileged.seed("service_catalogue", {"id": "item-1", "firm_id": FIRM, "client_id": CLIENT, "name": "Widget", "kind": "goods"})
    monkeypatch.setattr("services.stock_position_service.position",
                        lambda db, firm, client, date: {"items": [{"service_catalogue_id": "item-1", "qty_units": "10"}]})
    sheet = svc.open_session(request, firm_id=FIRM, client_id=CLIENT, count_date="2026-03-31", reference_no="PC-1",
                             notes=None, created_by=None)
    assert len(_only(privileged, "stock_count_sessions")) == 1 and len(_only(privileged, "stock_count_lines")) == 1
    saved = svc.save_counts(request, firm_id=FIRM, session_id=sheet["id"],
                            entries=[{"service_catalogue_id": "item-1", "counted_qty_units": "10"}])
    assert saved == 1 and _only(privileged, "stock_count_lines")[0]["counted_qty_units"] == "10"
    # a count with no variance posts nothing to the ledger, and the sheet is still marked posted, by the privileged client
    monkeypatch.setattr("services.period_validation_service.period_validation_service.validate_posting_date", lambda *a, **k: None)
    posted = svc.post_session(request, firm_id=FIRM, session_id=sheet["id"], actor_id=None)
    assert posted["posted_count"] == 0 and _only(privileged, "stock_count_sessions")[0]["status"] == "posted"
    assert request.refused == []


def test_a_reverse_charge_document_is_issued_on_the_privileged_client(world, monkeypatch):
    """The preview and the period questions are the module's own and are tested elsewhere; this drives the one write."""
    from services import rcm_document_service as svc
    privileged, request = world
    privileged.seed("purchase_bills", {"id": "bill-1", "firm_id": FIRM, "client_id": CLIENT, "vendor_id": "vendor-1", "deleted_at": None})
    monkeypatch.setattr(svc, "preview_self_invoice", lambda *a, **k: {
        "existing": None, "due": True, "reasons": [], "gaps": [],
        "particulars": {"document_no": "RCM-1", "document_date": "2026-04-10", "taxes": [{"head": "IGST", "amount_paise": 180}],
                        "taxable_paise": 1000, "amount_paid_paise": 0}})
    monkeypatch.setattr("services.period_validation_service.period_validation_service.validate_posting_date", lambda *a, **k: None)
    monkeypatch.setattr("services.period_lock_service.assert_open", lambda *a, **k: None)
    out = svc.issue(request, firm_id=FIRM, client_id=CLIENT, kind="self_invoice", bill_id="bill-1")
    assert out.get("id") or out.get("document_no"), out
    rows = privileged.rows("rcm_documents")
    assert [(r["firm_id"], r["client_id"], r["igst_paise"]) for r in rows] == [(FIRM, CLIENT, 180)]
    assert request.refused == []


def test_a_row_of_another_client_is_not_touched_by_a_withdrawal_that_names_this_one(world):
    from services import gstr4_annual_service as svc
    privileged, request = world
    theirs = svc.record_b2b_supply(request, FIRM, OTHER, gstin=GSTIN, financial_year="2025-26", supplier_gstin="29ABCDE1234F1Z5",
                                   place_of_supply="29", rate_bps=1800)
    with pytest.raises(Exception) as e:
        svc.delete_b2b_supply(request, FIRM, CLIENT, theirs["id"])
    assert getattr(e.value, "status_code", None) == 404
    assert len(_only(privileged, "gstr4_annual_b2b_supplies")) == 1
