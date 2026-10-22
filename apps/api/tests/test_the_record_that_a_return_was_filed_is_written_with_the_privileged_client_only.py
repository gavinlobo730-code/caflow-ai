"""`filings` is written by one function, with the privileged client (ledger POST-A-319; a migration that follows this change takes the signed-in write away).

THE DEFECT
    `filings` is the evidence the period lock reads to refuse a posting inside a filed month. It was writable by every signed-in
    member (`authenticated` held INSERT, UPDATE and DELETE; the policies were the firm and the assignment scope), so an assigned
    Reviewer deleted the record and the lock answered open. The migration that follows revokes the verbs; the one writer
    now uses the privileged client. That migration's own test is the real-Postgres one.

WHAT IS HELD (no database)
    * (source, derived from the AST of the whole API) the only code that writes the table is
      `gst_filing_record_service.record_filing`, and it writes only after `db = _filings_db(db)`;
    * `_filings_db` hands out the privileged client where there is one and the request's own where there is none (mock mode),
      and `None` stays `None`; with a privileged client in play the function asks first that the client is the firm's, and writes
      nothing for a client of another firm;
    * the browser (`apps/web`) does not `.from()` the table.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

import core.db_provider
import services.gst_filing_record_service as svc
from tests._table_uses import sources as _sources, uses as _uses

API_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = API_ROOT.parents[1] / "apps" / "web"
TABLE = "filings"


def test_only_record_filing_writes_the_table_and_nobody_keeps_a_query_on_it_in_a_variable():
    writers, hidden = {}, {}
    for rel, text in _sources():
        if TABLE not in text:
            continue
        for kind, name, line, _receiver, _verbs in _uses(text, TABLE):
            if kind == "write":
                writers.setdefault(rel, []).append((name, line, kind))
            elif kind in {"unchained", "named", "raw_write"}:
                hidden.setdefault(rel, []).append((name, line, kind))
    assert not hidden, (f"these modules keep a query on {TABLE} in a variable, hold its name in a constant or write it in SQL text, "
                        f"which the guard cannot read: {hidden}. Chain the verb off `.table(\"{TABLE}\")` where it is used.")
    assert set(writers) == {"services/gst_filing_record_service.py"}, sorted(writers)
    assert {name for name, _l, _k in writers["services/gst_filing_record_service.py"]} == {"record_filing"}


def test_the_guard_sees_every_shape_a_write_can_take():
    shapes = {
        "a query kept in a variable": 'def f(db):\n    q = db.table("filings")\n    q.delete().execute()\n',
        "from_ instead of table": 'def f(db):\n    db.from_("filings").update({}).execute()\n',
        "a statement at module level": 'client.table("filings").insert({}).execute()\n',
        "an upsert": 'def f(db):\n    db.table("filings").upsert({}).execute()\n',
        "the name held in a constant": 'T = "filings"\n\ndef f(db):\n    db.table(T).delete().execute()\n',
        "the name as a keyword": 'def f(db):\n    db.table(name="filings").delete().execute()\n',
        "an alias for the method": 'def f(db):\n    t = db.table\n    t("filings").delete().execute()\n',
        "a tuple of tables": 'def f(db):\n    for name in ("filings", "x"):\n        db.table(name).delete().execute()\n',
        "a helper argument": 'def f(db):\n    wipe(db, "filings")\n',
        "a dict value": 'def f(db):\n    spec = {"table": "filings"}\n    db.table(spec["table"]).delete().execute()\n',
        "raw SQL": 'def f(cur):\n    cur.execute("DELETE FROM public.filings WHERE true")\n',
        "raw SQL, lower case": 'SQL = "update filings set status = 1"\n',
    }
    for label, source in shapes.items():
        kinds = {k for k, *_ in _uses(source, TABLE)}
        assert kinds & {"write", "unchained", "named", "raw_write"}, f"the guard is blind to: {label}"
    assert [k for k, *_ in _uses('def f(db):\n    return db.table("filings").select("*").execute()\n', TABLE)] == ["read"]
    assert list(_uses('def f():\n    """DELETE FROM filings is what nobody does."""\n', TABLE)) == []
    # a label is not a table handle: a dict KEY (the payroll screens' "filings" section) and a comparison are not uses
    assert list(_uses('def f(x):\n    return {"filings": x, "other": 1}\n', TABLE)) == []
    assert list(_uses('def f(x):\n    return x == "filings"\n', TABLE)) == []


def test_the_walk_reads_enough_modules_to_mean_something():
    rels = [rel for rel, _ in _sources()]
    assert len(rels) > 300, len(rels)
    assert any(r.startswith("scripts/") for r in rels), "the scripts directory is not walked: a one-off writer would pass"
    assert "services/gst_filing_record_service.py" in rels


def test_record_filing_writes_only_after_it_has_swapped_to_the_privileged_client():
    """From the AST, not from text: every statement on the table inside record_filing comes after `db = _filings_db(db)`."""
    tree = ast.parse((API_ROOT / "services" / "gst_filing_record_service.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "record_filing")
    swaps = [a.lineno for a in ast.walk(fn) if isinstance(a, ast.Assign) and isinstance(a.value, ast.Call)
             and isinstance(a.value.func, ast.Name) and a.value.func.id == "_filings_db"
             and any(isinstance(t, ast.Name) and t.id == "db" for t in a.targets)]
    assert len(swaps) == 1, swaps
    touches = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "table"
               and n.args and isinstance(n.args[0], ast.Constant) and n.args[0].value in {TABLE, "clients"}]
    assert touches and min(touches) > swaps[0], (swaps, touches)


class _Marker:
    pass


def test_the_swap_hands_out_the_privileged_client_and_keeps_none_none(monkeypatch):
    privileged = _Marker()
    monkeypatch.setattr(core.db_provider, "service_db_or_none", lambda: privileged)
    request = _Marker()
    assert svc._filings_db(request) is privileged
    assert svc._filings_db(None) is None
    monkeypatch.setattr(core.db_provider, "service_db_or_none", lambda: None)
    assert svc._filings_db(request) is request


class _Q:
    def __init__(self, db, table):
        self.db, self.table, self.op = db, table, "select"
        self.filters = []

    def select(self, *a, **k):
        self.db.selects.append((self.table, self.filters))
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def is_(self, column, value):
        # `.is_("deleted_at", "null")` keeps only rows where the column is null; recorded as a filter so a lookup that adds
        # it stops finding a soft-deleted row (the defect the revival test is named for)
        self.filters.append((column, None if value == "null" else value))
        return self

    def insert(self, row):
        self.db.writes.append((self.table, "insert", row, self.filters))
        return self

    def update(self, row):
        self.db.writes.append((self.table, "update", row, self.filters))
        return self

    def __getattr__(self, name):
        return lambda *a, **k: self

    def execute(self):
        # the rows a table is seeded with are answered only to a query whose equality filters they satisfy (a row that does not
        # carry the column is not filtered on it), so a statement that forgets to name the firm is seen by the test
        rows = [r for r in self.db.answers.get(self.table, []) if all(r.get(c, v) == v for c, v in self.filters)]

        class R:
            data = rows
        return R()


class _Db:
    def __init__(self, answers=None):
        self.writes, self.selects, self.answers = [], [], answers or {}

    def table(self, name):
        return _Q(self, name)


def test_a_client_of_another_firm_is_refused_and_nothing_is_written(monkeypatch):
    from core.exceptions import ValidationError
    request, privileged = _Db(), _Db(answers={"clients": [{"id": "c-other", "firm_id": "f2"}]})
    monkeypatch.setattr(core.db_provider, "service_db_or_none", lambda: privileged)
    with pytest.raises(ValidationError):
        svc.record_filing(request, firm_id="f1", client_id="c-other", filing_type="GSTR-3B", period="072025", filed_date="2025-08-11")
    assert privileged.writes == [] and request.writes == []


def test_the_write_goes_to_the_privileged_client_and_not_the_requests(monkeypatch):
    request, privileged = _Db(), _Db(answers={"clients": [{"id": "c1", "firm_id": "f1"}]})
    monkeypatch.setattr(core.db_provider, "service_db_or_none", lambda: privileged)
    svc.record_filing(request, firm_id="f1", client_id="c1", filing_type="GSTR-3B", period="072025", filed_date="2025-08-11")
    assert [w[:2] for w in privileged.writes] == [("filings", "insert")]
    assert request.writes == []


_LOOKUP = dict(filing_type="GSTR-3B", period_start="2025-07-01", period_end="2025-07-31")


def _filing(row_id, **over):
    return {"id": row_id, "firm_id": "f1", "client_id": "c1", "deleted_at": None, **_LOOKUP, **over}


def test_re_recording_a_return_revives_a_soft_deleted_row_and_every_statement_names_the_firm_and_the_client(monkeypatch):
    """The lookup finds a row even when it was soft-deleted (until the signed-in write is taken away an assigned member can do
    that), and the update writes `deleted_at` back to null: the period functions read live rows only, so updating a row they
    cannot see would report a lock that is not there. The privileged client carries no row security, so the lookup and the
    update name the firm and the client. The seeded row IS soft-deleted, and the double honours `.is_()`, so a lookup that
    started to ask for live rows only would find nothing and insert a second row: this test fails."""
    request = _Db()
    privileged = _Db(answers={"clients": [{"id": "c1", "firm_id": "f1"}], "filings": [_filing("F1", deleted_at="2025-09-01T00:00:00+00:00")]})
    monkeypatch.setattr(core.db_provider, "service_db_or_none", lambda: privileged)
    row = svc.record_filing(request, firm_id="f1", client_id="c1", filing_type="GSTR-3B", period="072025", filed_date="2025-08-11")
    assert [w[:2] for w in privileged.writes] == [("filings", "update")], privileged.writes
    update = privileged.writes[0]
    assert update[2]["deleted_at"] is None, update
    cols = dict(update[3])
    assert cols["id"] == "F1" and cols["firm_id"] == "f1" and cols["client_id"] == "c1", cols
    lookup = [f for t, f in privileged.selects if t == "filings"]
    keys = dict(lookup[0])
    assert keys.get("firm_id") == "f1" and keys.get("client_id") == "c1" and "deleted_at" not in keys, lookup
    assert row["id"] == "F1"
    assert request.writes == []


def test_a_live_row_is_refreshed_before_a_soft_deleted_twin(monkeypatch):
    """The table has no unique key: when a soft-deleted twin and a live row both match, refreshing the dead one would leave two
    live rows claiming the period."""
    privileged = _Db(answers={"clients": [{"id": "c1", "firm_id": "f1"}], "filings": [
        _filing("DEAD", deleted_at="2025-09-01T00:00:00+00:00"), _filing("LIVE")]})
    monkeypatch.setattr(core.db_provider, "service_db_or_none", lambda: privileged)
    row = svc.record_filing(_Db(), firm_id="f1", client_id="c1", filing_type="GSTR-3B", period="072025", filed_date="2025-08-11")
    assert row["id"] == "LIVE" and dict(privileged.writes[0][3])["id"] == "LIVE", privileged.writes


def test_the_lookup_matches_the_return_it_records_and_no_other(monkeypatch):
    """A GSTR-3B record must not overwrite the GSTR-1 row of the same period, another period's row, or another client's."""
    privileged = _Db(answers={"clients": [{"id": "c1", "firm_id": "f1"}], "filings": [
        _filing("OTHER-TYPE", filing_type="GSTR-1"),
        _filing("OTHER-PERIOD", period_start="2025-06-01", period_end="2025-06-30"),
        _filing("OTHER-CLIENT", client_id="c2"),
        _filing("OTHER-FIRM", firm_id="f2")]})
    monkeypatch.setattr(core.db_provider, "service_db_or_none", lambda: privileged)
    svc.record_filing(_Db(), firm_id="f1", client_id="c1", filing_type="GSTR-3B", period="072025", filed_date="2025-08-11")
    assert [w[:2] for w in privileged.writes] == [("filings", "insert")], privileged.writes
    lookup = dict([f for t, f in privileged.selects if t == "filings"][0])
    assert set(lookup) >= {"firm_id", "client_id", "filing_type", "period_start", "period_end"}, lookup


def test_a_client_the_firm_does_not_hold_is_refused_even_when_the_firm_holds_others(monkeypatch):
    """The ownership question names the client AND the firm: with the client dropped it would read 'does this firm have any
    client', and a made-up client id would pass."""
    from core.exceptions import ValidationError
    privileged = _Db(answers={"clients": [{"id": "c1", "firm_id": "f1"}]})
    monkeypatch.setattr(core.db_provider, "service_db_or_none", lambda: privileged)
    with pytest.raises(ValidationError):
        svc.record_filing(_Db(), firm_id="f1", client_id="c-made-up", filing_type="GSTR-3B", period="072025", filed_date="2025-08-11")
    assert privileged.writes == []


def test_the_browser_does_not_read_or_write_the_table_directly():
    pattern = re.compile(r"""\.from\(\s*["'`]%s["'`]""" % TABLE)
    hits = []
    for path in WEB_ROOT.rglob("*"):
        if path.suffix not in {".ts", ".tsx"} or "node_modules" in path.parts or ".next" in path.parts:
            continue
        if pattern.search(path.read_text(encoding="utf-8", errors="ignore")):
            hits.append(path.relative_to(WEB_ROOT).as_posix())
    assert not hits, hits
