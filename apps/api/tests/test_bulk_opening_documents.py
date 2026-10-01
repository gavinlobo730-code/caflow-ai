"""
ACC-05 — a client's open bills come over from a spreadsheet, in bulk.

WHAT WAS WRONG
    `routers/opening_documents` took ONE document per POST and the Opening
    Balances tab had no import, so a trading client with two hundred open
    invoices — a Busy, Marg or Excel history, the commonest migration there is —
    was a week of typing. Most CAs would have skipped it and lost the dated
    ageing the whole breakup exists to give; the trial-balance import cannot help
    because it has no dates.

WHAT THESE PIN
    * every row is judged before any is written, and a bad row names its NUMBER
      and ALL of its problems at once;
    * the good rows still land — "commit by named row", not all or nothing, so a
      typo on row 212 does not stop the other two hundred and ninety-nine;
    * UPLOADING THE SAME FILE AGAIN RECORDS NOTHING: the key is the one each
      table's unique index uses (migration 209: invoice number per client, exact;
      migration 313: vendor and number, without case), and the comparison is on
      the TOTAL the import wrote — a receipt allocated since must not turn the
      same file into a conflict;
    * a number recorded with a DIFFERENT amount is rejected and says so, never
      overwritten; a number that is already an ordinary invoice is rejected;
    * a date is read day-first and a two-digit year is refused, not guessed;
    * a party is matched by folded name, never fuzzily, and an ambiguous one is
      reported rather than picked;
    * the result carries the party-by-party RECONCILIATION against the ledger's
      opening balance — a difference is named, never absorbed;
    * a dry run writes nothing and projects that reconciliation;
    * the chunked insert falls back to row by row, so one refused document is
      attributed to its own row;
    * the insert writes exactly the columns `row_for` builds, in one statement.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from domain.accounting import opening_document_import as imp
from domain.accounting import opening_documents as od
from services import opening_document_service as svc

API_ROOT = Path(__file__).resolve().parents[1]

ACME = {"id": "P1", "name": "Acme Traders", "gstin": "27AABCU9603R1ZX", "opening_balance_paise": 0}
BOLT = {"id": "P2", "name": "Bolt  Industries", "gstin": None, "opening_balance_paise": 0}


def R(row, party="Acme Traders", no="INV/1", date="01-03-2026", due="30-04-2026",
      amt=100_000, gstin=None, notes=None):
    return imp.ImportRow(row=row, party=party, party_gstin=gstin, document_no=no,
                         document_date=date, due_date=due, outstanding_paise=amt,
                         notes=notes)


def plan(rows, parties=(ACME, BOLT), existing=(), kind=od.RECEIVABLE):
    return imp.plan(kind, rows, list(parties), list(existing))


# ── dates ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "2026-03-01", "01-03-2026", "1/3/2026", "01.03.2026", "01-Mar-2026",
    "1 March 2026", "2026-03-01 00:00:00",
])
def test_a_date_is_read_day_first_and_every_spelling_agrees(text):
    [v] = plan([R(1, date=text)])
    assert v.status == imp.NEW and v.document_date == "2026-03-01", v


@pytest.mark.parametrize("text", ["4/1/26", "01-03-26", "31-02-2026", "13/13/2026",
                                  "March first", "2026/03/01x"])
def test_a_date_that_cannot_be_read_with_certainty_is_refused_not_guessed(text):
    [v] = plan([R(1, date=text)])
    assert v.status == imp.REJECTED
    assert "not a date" in v.sentence and "two-digit year" in v.sentence, v.sentence
    # the one sentence, said once — the rule behind it must not repeat itself
    assert v.sentence.count("document date") <= 2


def test_a_due_date_before_the_document_is_refused_by_the_one_rule():
    [v] = plan([R(1, date="01-03-2026", due="01-02-2026")])
    assert v.status == imp.REJECTED
    assert "before the document date" in v.sentence


# ── parties ──────────────────────────────────────────────────────────────────

def test_a_name_is_matched_without_case_or_runs_of_spaces():
    [v] = plan([R(1, party="  ACME   traders. ")])
    assert v.status == imp.NEW and v.party_id == "P1"
    [v2] = plan([R(1, party="bolt industries")])
    assert v2.party_id == "P2", "the master's double space folds to one"


def test_a_name_that_is_a_different_word_is_never_matched_fuzzily():
    [v] = plan([R(1, party="Acme Trading Co")])
    assert v.status == imp.REJECTED
    assert "No customer named" in v.sentence and "Add it first" in v.sentence


def test_an_ambiguous_name_is_reported_and_a_gstin_settles_it():
    twin = dict(ACME, id="P9", gstin="27AAACB1234C1Z5")
    [v] = plan([R(1)], parties=(ACME, twin))
    assert v.status == imp.REJECTED and "2 customers" in v.sentence
    [ok] = plan([R(1, gstin="27AABCU9603R1ZX")], parties=(ACME, twin))
    assert ok.status == imp.NEW and ok.party_id == "P1"


def test_a_name_and_a_gstin_that_name_two_parties_are_refused():
    [v] = plan([R(1, party="Acme Traders", gstin="27AAACB1234C1Z5")],
               parties=(ACME, dict(BOLT, gstin="27AAACB1234C1Z5")))
    assert v.status == imp.REJECTED and "two different customers" in v.sentence


def test_a_gstin_no_party_holds_is_refused_naming_it():
    [v] = plan([R(1, gstin="29ABCDE1234F1Z5")])
    assert v.status == imp.REJECTED and "29ABCDE1234F1Z5" in v.sentence


# ── what a row may be ────────────────────────────────────────────────────────

def test_a_bad_row_lists_every_problem_at_once():
    """A file corrected one error at a time is a file uploaded nineteen times."""
    [v] = plan([R(7, party="Nobody Ltd", no="", date="soon", due="later", amt=0)])
    assert v.status == imp.REJECTED
    s = v.sentence
    assert s.startswith("Row 7")
    for fragment in ("No customer named", "The document's own number is required",
                     "The document date", "The due date", "STILL OWED"):
        assert fragment in s, (fragment, s)


def test_an_amount_the_browser_could_not_read_arrives_and_is_refused_with_its_row():
    [v] = plan([R(4, amt=None)])
    assert v.status == imp.REJECTED and "Row 4" in v.sentence
    assert "STILL OWED" in v.sentence


def test_a_negative_or_zero_amount_is_refused_by_the_one_rule():
    for amt in (0, -500):
        [v] = plan([R(1, amt=amt)])
        assert v.status == imp.REJECTED


def test_the_rule_is_od_problem_with_and_not_a_copy_of_it():
    src = (API_ROOT / "domain" / "accounting" / "opening_document_import.py").read_text()
    assert "od.problem_with(" in src
    assert "STILL OWED" not in src, "the sentence belongs to opening_documents"


def test_a_repeat_inside_the_file_is_rejected_naming_the_first_row():
    a, b = plan([R(1, no="INV/9"), R(5, no="INV/9")])
    assert a.status == imp.NEW
    assert b.status == imp.REJECTED and "row 1" in b.sentence


def test_a_sales_number_is_one_per_client_whoever_it_belongs_to():
    a, b = plan([R(1, party="Acme Traders", no="X/1"), R(2, party="Bolt Industries", no="X/1")])
    assert a.status == imp.NEW and b.status == imp.REJECTED


def test_a_purchase_number_is_one_per_vendor_without_case():
    rows = [R(1, party="Acme Traders", no="B-1"), R(2, party="Bolt Industries", no="B-1"),
            R(3, party="Acme Traders", no=" b-1 ")]
    one, two, three = plan(rows, kind=od.PAYABLE)
    assert one.status == imp.NEW and two.status == imp.NEW, "another vendor may share it"
    assert three.status == imp.REJECTED and "row 1" in three.sentence


# ── a re-upload ──────────────────────────────────────────────────────────────

def _recorded(no="INV/1", party="P1", total=100_000, opening=True, **extra):
    return {"id": f"doc-{no}", od.NUMBER_COLUMN[od.RECEIVABLE]: no,
            od.PARTY_COLUMN[od.RECEIVABLE]: party, "is_opening": opening,
            "total_paise": total, **extra}


def test_the_same_document_again_is_already_recorded_not_an_error():
    [v] = plan([R(1)], existing=[_recorded()])
    assert v.status == imp.ALREADY_RECORDED and v.existing_id == "doc-INV/1"
    assert not v.problems


def test_it_stays_the_same_document_after_a_receipt_has_been_allocated_to_it():
    """The comparison is on the TOTAL the import wrote. Outstanding falls as
    receipts land; reading it would make the same file a conflict the day after
    the first receipt."""
    [v] = plan([R(1)], existing=[_recorded(outstanding_paise=40_000, paid_paise=60_000)])
    assert v.status == imp.ALREADY_RECORDED


def test_the_same_number_with_a_different_amount_is_rejected_and_not_overwritten():
    [v] = plan([R(1, amt=150_000)], existing=[_recorded()])
    assert v.status == imp.REJECTED
    assert "already recorded with" in v.sentence and "1,000.00" in v.sentence
    assert "1,500.00" in v.sentence and "remove the recorded document first" in v.sentence


def test_an_ordinary_invoice_with_that_number_is_not_an_opening_document():
    [v] = plan([R(1)], existing=[_recorded(opening=False)])
    assert v.status == imp.REJECTED and "ordinary invoice" in v.sentence


def test_the_number_recorded_against_another_customer_is_named():
    [v] = plan([R(1)], existing=[_recorded(party="P2")])
    assert v.status == imp.REJECTED and "Bolt  Industries" in v.sentence


# ── the service, run against a database double ───────────────────────────────

class _Q:
    def __init__(self, db, table):
        self._db, self._table = db, table
        self._rows = list(db.store.get(table, []))

    def select(self, *a, **k): return self

    def insert(self, payload):
        rows = payload if isinstance(payload, list) else [payload]
        self._db.inserts.append((self._table, [dict(r) for r in rows]))
        if self._db.refuse and any(self._db.refuse(self._table, r) for r in rows):
            raise RuntimeError("duplicate key value violates unique constraint")
        out = []
        for r in rows:
            r = dict(r)
            r["id"] = f"{self._table}-{sum(len(v) for v in self._db.store.values()) + 1}"
            r.setdefault("paid_paise", 0)
            base = (int(r.get("net_payable_paise") or 0) if self._table == "purchase_bills"
                    else int(r.get("total_paise") or 0))
            r["outstanding_paise"] = base - int(r.get("paid_paise") or 0)
            self._db.store.setdefault(self._table, []).append(r)
            out.append(r)
        self._rows = out
        return self

    def eq(self, col, val):
        self._rows = [r for r in self._rows if r.get(col) == val]; return self

    def neq(self, col, val):
        self._rows = [r for r in self._rows if r.get(col) != val]; return self

    def is_(self, col, _null):
        self._rows = [r for r in self._rows if r.get(col) is None]; return self

    def in_(self, col, vals):
        self._rows = [r for r in self._rows if r.get(col) in list(vals)]; return self

    def gt(self, col, val):
        self._rows = [r for r in self._rows if str(r.get(col)) > str(val)]; return self

    def order(self, col, **k):
        self._rows.sort(key=lambda r: str(r.get(col))); return self

    def limit(self, n):
        self._rows = self._rows[:n]; return self

    def execute(self):
        return type("R", (), {"data": self._rows})()


class _DB:
    def __init__(self, **tables):
        self.store = tables
        self.inserts: list = []
        self.refuse = None

    def table(self, name):
        return _Q(self, name)


def _db(n_customers=3, opening=None):
    return _DB(
        customers=[{"id": f"C{i}", "firm_id": "F1", "client_id": "K1",
                    "name": f"Customer {i}", "gstin": None, "is_active": True,
                    "opening_balance_paise": (opening or {}).get(f"C{i}", 0)}
                   for i in range(1, n_customers + 1)]
                  # a namesake belonging to ANOTHER client must never be matched
                  + [{"id": "OTHER", "firm_id": "F1", "client_id": "K2",
                      "name": "Customer 1", "gstin": None, "is_active": True,
                      "opening_balance_paise": 0}],
        vendors=[{"id": "V1", "firm_id": "F1", "client_id": "K1", "name": "Bolt",
                  "gstin": None, "is_active": True, "opening_balance_paise": 0}],
        client_sales_invoices=[], purchase_bills=[])


def _file(n=300):
    """n rows over three customers, with three deliberately bad ones."""
    rows = []
    for i in range(1, n + 1):
        rows.append(R(i, party=f"Customer {1 + i % 3}", no=f"INV/{i:04d}",
                      date="15-03-2026", due="14-04-2026", amt=100_00 + i * 100))
    rows[9] = R(10, party="Nobody At All", no="INV/0010", amt=500_00)       # unknown party
    rows[99] = R(100, party="Customer 2", no="INV/0100", date="3/4/26")     # ambiguous year
    rows[199] = R(200, party="Customer 3", no="INV/0200", amt=0)            # nothing owed
    return rows


def test_a_300_row_file_lands_its_good_rows_and_names_its_bad_ones():
    db = _db()
    out = svc.bulk_create(db, "F1", "K1", kind=od.RECEIVABLE, rows=_file(), actor_id="u1")
    assert out["received"] == 300
    assert out["created"] == 297 and out["rejected"] == 3 and out["already_recorded"] == 0
    bad = {r["row"]: r for r in out["rows"] if r["status"] == imp.REJECTED}
    assert sorted(bad) == [10, 100, 200]
    assert "No customer named" in bad[10]["problems"][0]
    assert "two-digit year" in " ".join(bad[100]["problems"])
    assert "STILL OWED" in " ".join(bad[200]["problems"])
    assert len(db.store["client_sales_invoices"]) == 297
    # In chunks of 100 — three statements, each atomic.
    assert [len(rows) for _t, rows in db.inserts] == [100, 100, 97]


def test_uploading_the_same_file_again_records_nothing_twice():
    db = _db()
    first = svc.bulk_create(db, "F1", "K1", kind=od.RECEIVABLE, rows=_file())
    count = len(db.store["client_sales_invoices"])
    again = svc.bulk_create(db, "F1", "K1", kind=od.RECEIVABLE, rows=_file())
    assert first["created"] == 297
    assert again["created"] == 0 and again["already_recorded"] == 297 and again["rejected"] == 3
    assert len(db.store["client_sales_invoices"]) == count, "a duplicate was written"


def test_a_re_upload_after_a_receipt_has_landed_is_still_not_a_conflict():
    db = _db()
    svc.bulk_create(db, "F1", "K1", kind=od.RECEIVABLE, rows=_file())
    # a receipt allocates against the first invoice: paid up, outstanding down
    inv = db.store["client_sales_invoices"][0]
    inv["paid_paise"] = inv["total_paise"] // 2
    inv["outstanding_paise"] = inv["total_paise"] - inv["paid_paise"]
    again = svc.bulk_create(db, "F1", "K1", kind=od.RECEIVABLE, rows=_file())
    assert again["created"] == 0
    assert all(r["status"] != imp.REJECTED or r["row"] in (10, 100, 200) for r in again["rows"])


def test_the_written_documents_are_opening_nil_tax_and_this_clients_own():
    db = _db()
    svc.bulk_create(db, "F1", "K1", kind=od.RECEIVABLE,
                    rows=[R(1, party="Customer 1", no="INV/A", amt=2_500_00,
                            notes="Busy migration")], actor_id="u7")
    [row] = db.store["client_sales_invoices"]
    assert row["is_opening"] is True and row["status"] == "issued"
    assert row["firm_id"] == "F1" and row["client_id"] == "K1"
    assert row["customer_id"] == "C1", "the namesake of ANOTHER client must not be matched"
    assert row["total_paise"] == 2_500_00 and row["outstanding_paise"] == 2_500_00
    for col in od.NO_TAX_FIELDS:
        assert row[col] == 0
    assert row["created_by"] == "u7" and row["notes"] == "Busy migration"
    assert row["invoice_date"] == "2026-03-01" and row["due_date"] == "2026-04-30"


def test_a_purchase_bill_is_outstanding_in_full_not_at_nil():
    """Migration 278 generates a bill's outstanding from net_payable_paise."""
    db = _db()
    out = svc.bulk_create(db, "F1", "K1", kind=od.PAYABLE,
                          rows=[R(1, party="Bolt", no="B/1", amt=7_000_00)])
    assert out["created"] == 1
    [bill] = db.store["purchase_bills"]
    assert bill["net_payable_paise"] == 7_000_00 and bill["outstanding_paise"] == 7_000_00
    assert bill["tds_paise"] == 0 and bill["is_opening"] is True


def test_a_dry_run_writes_nothing_and_projects_the_reconciliation():
    db = _db(opening={"C1": 3_00_000})
    rows = [R(1, party="Customer 1", no="A", amt=2_00_000),
            R(2, party="Customer 1", no="B", amt=1_00_000)]
    out = svc.bulk_create(db, "F1", "K1", kind=od.RECEIVABLE, rows=rows, dry_run=True)
    assert db.inserts == [] and db.store["client_sales_invoices"] == []
    assert out["dry_run"] and out["created"] == 0
    assert out["would_create"] == 2 and out["would_create_paise"] == 3_00_000
    assert {r["status"] for r in out["rows"]} == {"would_create"}
    [rec] = out["reconciliation"]
    assert rec["agrees"] and rec["documents_paise"] == 3_00_000, (
        "the projection must show the parties footing BEFORE anything is written")


def test_the_reconciliation_names_a_difference_rather_than_absorbing_it():
    db = _db(opening={"C1": 3_00_000})
    out = svc.bulk_create(db, "F1", "K1", kind=od.RECEIVABLE,
                          rows=[R(1, party="Customer 1", no="A", amt=2_50_000)])
    [rec] = out["reconciliation"]
    assert rec["agrees"] is False and rec["difference_paise"] == 50_000
    assert "no document behind it" in rec["sentence"]
    assert out["unreconciled_parties"] == 1
    # and the documents carry exactly what the file said — nothing was topped up
    assert db.store["client_sales_invoices"][0]["total_paise"] == 2_50_000


def test_documents_for_a_party_with_no_opening_balance_are_reported_as_more_than_the_ledger():
    db = _db()
    out = svc.bulk_create(db, "F1", "K1", kind=od.RECEIVABLE,
                          rows=[R(1, party="Customer 2", no="A", amt=90_000)])
    [rec] = out["reconciliation"]
    assert rec["difference_paise"] == -90_000 and "MORE than" in rec["sentence"]


def test_a_refused_chunk_is_retried_one_at_a_time_so_the_fault_has_a_row():
    db = _db()
    db.refuse = lambda table, r: r.get("invoice_no") == "INV/0003"
    out = svc.bulk_create(db, "F1", "K1", kind=od.RECEIVABLE,
                          rows=[R(i, party="Customer 1", no=f"INV/{i:04d}") for i in range(1, 6)])
    assert out["created"] == 4 and out["rejected"] == 1
    [bad] = [r for r in out["rows"] if r["status"] == imp.REJECTED]
    assert bad["row"] == 3 and bad["problems"], "the fault must name its own row"
    assert len(db.store["client_sales_invoices"]) == 4
    assert out["created_paise"] == 4 * 100_000, "the refused row's amount is not counted"


def test_an_empty_file_and_a_file_over_the_ceiling_are_refused_with_a_sentence():
    from fastapi import HTTPException
    for rows in ([], [R(i) for i in range(imp.MAX_ROWS + 1)]):
        with pytest.raises(HTTPException) as ei:
            svc.bulk_create(_db(), "F1", "K1", kind=od.RECEIVABLE, rows=rows)
        assert ei.value.status_code == 422 and ei.value.detail


def test_an_unknown_kind_is_refused():
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        svc.bulk_create(_db(), "F1", "K1", kind="sideways", rows=[R(1)])


def test_an_archived_party_is_not_a_party_a_new_document_files_against():
    db = _db()
    db.store["customers"][0]["is_active"] = False
    out = svc.bulk_create(db, "F1", "K1", kind=od.RECEIVABLE,
                          rows=[R(1, party="Customer 1")])
    assert out["created"] == 0 and out["rejected"] == 1


# ── the insert writes what row_for builds ────────────────────────────────────

def _insert_keys(func_name: str) -> set[str]:
    tree = ast.parse((API_ROOT / "services" / "opening_document_service.py").read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == func_name)
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "insert":
            comp = node.args[0]
            assert isinstance(comp, ast.ListComp) and isinstance(comp.elt, ast.Dict), (
                f"{func_name} must insert a comprehension over a LITERAL dict — the "
                f"column scanners read nothing else, and both budgets say to write "
                f"the payload inline rather than raise them")
            return {k.value for k in comp.elt.keys}
    raise AssertionError(f"{func_name} has no insert")


@pytest.mark.parametrize("kind,func,extra", [
    (od.RECEIVABLE, "_write_receivables", {"created_by"}),
    (od.PAYABLE, "_write_payables", set()),
])
def test_the_bulk_insert_writes_exactly_the_columns_row_for_builds(kind, func, extra):
    """`row_for` is the definition ("built ONCE here so the two kinds cannot
    drift"); the insert spells the same columns out because a payload built in a
    function the scanner cannot see is invisible to it. This is the pin that
    keeps the two spellings one."""
    built = od.row_for(kind=kind, firm_id="F", client_id="C", party_id="P",
                       document_no="N", document_date="2026-03-01", due_date=None,
                       outstanding_paise=1, notes="n")
    assert _insert_keys(func) == set(built) | extra


def test_the_bulk_statements_are_one_per_chunk_not_one_per_document():
    src = (API_ROOT / "services" / "opening_document_service.py").read_text()
    assert "_INSERT_CHUNK = 100" in src
    body = src[src.index("def bulk_create"):]
    assert "for i in range(0, len(new), _INSERT_CHUNK)" in body


# ── the door ─────────────────────────────────────────────────────────────────

@pytest.fixture
def client(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import routers.opening_documents as rod
    from core.auth import get_current_user
    app = FastAPI()
    app.include_router(rod.router)
    user = {"id": "u1", "firm_id": "F1", "role": "Partner", "email": "p@f1.test",
            "auth_user_id": "auth-1"}
    app.dependency_overrides[get_current_user] = lambda: user
    app.state.user = user
    return TestClient(app, raise_server_exceptions=False), app


def test_the_door_is_rbac_gated_on_accounting_write_and_scoped_to_the_client():
    src = (API_ROOT / "routers" / "opening_documents.py").read_text()
    block = src[src.index('@router.post("/bulk")'):src.index('@router.delete("/{document_id}")')]
    assert 'rbac("accounting", "write")' in block
    assert "assert_client_access(current_user, data.client_id)" in block
    assert src.index('@router.post("/bulk")') < src.index('@router.delete("/{document_id}")'), (
        "registered after /{document_id}, 'bulk' could be read as an id")


def test_the_door_drives_the_service_end_to_end_and_audits_once(client, monkeypatch):
    http, _app = client
    db = _db()
    monkeypatch.setenv("SUPABASE_URL", "http://fake")
    import core.supabase_client as sc
    monkeypatch.setattr(sc, "get_supabase", lambda: db)
    events = []
    import services.audit_service as aud
    monkeypatch.setattr(aud, "log_event", lambda *a, **k: events.append((a, k)))

    body = {"client_id": "K1", "kind": "receivable",
            "rows": [dict(row=1, party="Customer 1", document_no="INV/1",
                          document_date="01-03-2026", outstanding_paise=100_000),
                     dict(row=2, party="Ghost", document_no="INV/2",
                          document_date="01-03-2026", outstanding_paise=100_000)]}
    res = http.post("/api/opening-documents/bulk", json=body)
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["created"] == 1 and data["rejected"] == 1
    assert [r["row"] for r in data["rows"] if r["status"] == "rejected"] == [2]
    assert len(events) == 1
    (args, kwargs) = events[0]
    assert args[1] == "opening_document" and args[3] == "bulk_import"
    assert kwargs["actor_id"] == "auth-1", "the audit log takes the AUTH id"

    again = http.post("/api/opening-documents/bulk", json=body).json()["data"]
    assert again["created"] == 0 and again["already_recorded"] == 1
    assert len(events) == 1, "a re-upload that wrote nothing is not an audit event"


def test_a_dry_run_through_the_door_writes_nothing_and_audits_nothing(client, monkeypatch):
    http, _app = client
    db = _db()
    monkeypatch.setenv("SUPABASE_URL", "http://fake")
    import core.supabase_client as sc
    monkeypatch.setattr(sc, "get_supabase", lambda: db)
    import services.audit_service as aud
    monkeypatch.setattr(aud, "log_event",
                        lambda *a, **k: pytest.fail("a dry run is not an audit event"))
    res = http.post("/api/opening-documents/bulk", json={
        "client_id": "K1", "kind": "receivable", "dry_run": True,
        "rows": [dict(row=1, party="Customer 1", document_no="INV/1",
                      document_date="01-03-2026", outstanding_paise=100_000)]})
    assert res.status_code == 200, res.text
    assert db.inserts == [] and res.json()["data"]["would_create"] == 1
