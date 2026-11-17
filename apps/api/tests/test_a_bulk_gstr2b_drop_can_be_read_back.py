"""A bulk GSTR-2B drop is recorded with what it did to each file, and reads back after the screen is closed (POST-A-057, migration 715).

The per-file answer lived only in the browser that sent the files. These hold the record: the first request opens a drop and every
later one names it; a drop that is not the caller's is refused before any file is touched; every row the server answered is kept
as the answer carried it; the read-back is the caller's own drops only, newest first, files in the order answered, and a row for a
client the reader cannot see now says nothing about that client; and a database without the tables is "not recorded", never "no drops".
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from services import gst_2b_bulk_service as bulk
from services import gst_2b_drop_record as rec
from tests.e2e_harness import FakeDB

FIRM = "firm-1"
OTHER_FIRM = "firm-2"
ME = "user-1"
SOMEONE = "user-2"
MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / \
    "715_a_bulk_gstr2b_drop_is_recorded_with_what_it_did_to_each_file.sql"


@pytest.fixture
def db():
    d = FakeDB()
    d.seed("clients", {"id": "c-1", "firm_id": FIRM, "client_name": "Asha Traders", "legal_name": "Asha Traders Pvt Ltd"})
    d.seed("clients", {"id": "c-2", "firm_id": FIRM, "client_name": "Bina", "legal_name": None})
    return d


def _reconciled(name, client_id="c-1", period="062026"):
    return bulk._result(name, bulk.RECONCILED, gstin="27AAAAA0000A1Z5", period=period, client_id=client_id,
                        client_name="whatever the answer said",
                        summary={"matched_count": 3, "missing_in_2b_count": 1, "itc_at_risk_paise": 1_800_00},
                        problems=["a note"])


def _refused(name):
    return bulk._result(name, bulk.UNMATCHED_GSTIN, gstin="29BBBBB1111B1Z5", reason="No client of yours holds it.")


def _number(db):
    for i, r in enumerate(db.rows("gstr2b_bulk_drop_files"), start=1):
        r.setdefault("seq", i)


def test_the_first_request_opens_a_drop_and_a_later_one_names_it(db):
    drop = rec.open_drop(db, firm_id=FIRM, member_id=ME, drop_id=None)
    assert drop
    assert rec.open_drop(db, firm_id=FIRM, member_id=ME, drop_id=drop) == drop
    assert len(db.rows("gstr2b_bulk_drops")) == 1
    assert db.rows("gstr2b_bulk_drops")[0]["created_by"] == ME


@pytest.mark.parametrize("member,firm", [(SOMEONE, FIRM), (ME, OTHER_FIRM)])
def test_a_drop_that_is_not_the_callers_is_refused_in_words(db, member, firm):
    drop = rec.open_drop(db, firm_id=FIRM, member_id=ME, drop_id=None)
    with pytest.raises(rec.DropRefused) as e:
        rec.open_drop(db, firm_id=firm, member_id=member, drop_id=drop)
    assert "not one of yours" in str(e.value) and "Nothing was reconciled" in str(e.value)


def test_every_answered_file_is_kept_as_the_answer_carried_it(db):
    drop = rec.open_drop(db, firm_id=FIRM, member_id=ME, drop_id=None)
    assert rec.record(db, firm_id=FIRM, drop_id=drop, results=[_reconciled("a.json"), _refused("b.json")])
    rows = db.rows("gstr2b_bulk_drop_files")
    assert [r["name"] for r in rows] == ["a.json", "b.json"]
    assert all(r["firm_id"] == FIRM and r["drop_id"] == drop for r in rows)
    assert rows[0]["summary"]["itc_at_risk_paise"] == 1_800_00
    assert rows[1]["client_id"] is None and rows[1]["reason"] == "No client of yours holds it."
    # The client's NAME is not stored: it is read when the drop is read back.
    assert all("client_name" not in r for r in rows)


def test_without_a_drop_nothing_is_recorded_and_the_answer_says_so(db):
    assert rec.record(db, firm_id=FIRM, drop_id=None, results=[_refused("b.json")]) is False
    assert db.rows("gstr2b_bulk_drop_files") == []


def test_the_read_back_is_the_callers_own_drops_newest_first_in_answer_order(db):
    first = rec.open_drop(db, firm_id=FIRM, member_id=ME, drop_id=None)
    rec.record(db, firm_id=FIRM, drop_id=first, results=[_reconciled("a.json")])
    rec.record(db, firm_id=FIRM, drop_id=first, results=[_refused("b.json")])
    second = rec.open_drop(db, firm_id=FIRM, member_id=ME, drop_id=None)
    rec.record(db, firm_id=FIRM, drop_id=second, results=[_reconciled("c.json", client_id="c-2")])
    theirs = rec.open_drop(db, firm_id=FIRM, member_id=SOMEONE, drop_id=None)
    rec.record(db, firm_id=FIRM, drop_id=theirs, results=[_reconciled("z.json")])
    db.rows("gstr2b_bulk_drops")[0]["created_at"] = "2026-11-17T04:00:00+00:00"
    db.rows("gstr2b_bulk_drops")[1]["created_at"] = "2026-11-17T05:00:00+00:00"
    db.rows("gstr2b_bulk_drops")[2]["created_at"] = "2026-11-17T06:00:00+00:00"
    _number(db)

    out = rec.read_back(db, firm_id=FIRM, member_id=ME, may_see=lambda cid: True)

    assert out["recorded"] is True
    assert [d["id"] for d in out["drops"]] == [second, first]
    assert [r["name"] for r in out["drops"][1]["results"]] == ["a.json", "b.json"]
    assert out["drops"][1]["totals"] == {"reconciled": 1, "unmatched_gstin": 1}
    assert out["drops"][1]["file_count"] == 2
    # Names are read now, legal name first, and never the stored answer's.
    assert out["drops"][1]["results"][0]["client_name"] == "Asha Traders Pvt Ltd"
    assert out["drops"][0]["results"][0]["client_name"] == "Bina"
    assert "never reached the server" in out["browser_only"]


def test_a_row_for_a_client_the_reader_cannot_see_now_says_nothing_about_it(db):
    drop = rec.open_drop(db, firm_id=FIRM, member_id=ME, drop_id=None)
    rec.record(db, firm_id=FIRM, drop_id=drop, results=[_reconciled("a.json"), _reconciled("c.json", client_id="c-2")])
    _number(db)

    out = rec.read_back(db, firm_id=FIRM, member_id=ME, may_see=lambda cid: cid == "c-2")

    hidden, shown = out["drops"][0]["results"]
    assert hidden["client_hidden"] is True
    assert hidden["client_id"] is None and hidden["client_name"] is None
    assert hidden["summary"] is None and hidden["problems"] == [] and hidden["needs_attention"] is False
    assert hidden["reason"] == rec.NOT_SEEN_NOW
    assert hidden["status"] == "reconciled"
    assert shown["client_id"] == "c-2" and shown["summary"] is not None


def test_the_access_check_is_asked_once_per_client(db):
    drop = rec.open_drop(db, firm_id=FIRM, member_id=ME, drop_id=None)
    rec.record(db, firm_id=FIRM, drop_id=drop, results=[_reconciled(f"{i}.json") for i in range(6)])
    _number(db)
    asked: list[str] = []

    rec.read_back(db, firm_id=FIRM, member_id=ME, may_see=lambda cid: asked.append(cid) or True)

    assert asked == ["c-1"]


def test_a_missing_table_is_not_recorded_and_never_no_drops(db, monkeypatch):
    class Missing(Exception):
        pass

    def boom(*_a, **_k):
        raise Missing('relation "public.gstr2b_bulk_drops" does not exist')

    monkeypatch.setattr(rec.db_errors, "is_missing_store", lambda exc, **_k: isinstance(exc, Missing))
    monkeypatch.setattr(db, "table", boom)

    assert rec.open_drop(db, firm_id=FIRM, member_id=ME, drop_id=None) is None
    out = rec.read_back(db, firm_id=FIRM, member_id=ME, may_see=lambda cid: True)
    assert out["recorded"] is False and out["drops"] == []
    assert "not recorded" in out["not_recorded"]


def test_another_read_failure_is_raised_not_read_as_no_drops(db, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(db, "table", boom)
    with pytest.raises(RuntimeError):
        rec.read_back(db, firm_id=FIRM, member_id=ME, may_see=lambda cid: True)


def test_the_migration_holds_the_service_status_list():
    sql = MIGRATION.read_text()
    held = sql.split("CHECK (status IN (", 1)[1].split(")", 1)[0]
    assert [s.strip(" '") for s in held.split(",")] == list(bulk.STATUSES)


def test_the_answer_fields_kept_are_the_answers_own():
    sample = _reconciled("a.json")
    assert set(rec._KEPT) <= set(sample)
    assert "client_name" not in rec._KEPT


def test_the_route_records_on_the_privileged_client_and_asks_the_drop_first():
    from routers import gst_workspace
    src = inspect.getsource(gst_workspace.bulk_gstr2b)
    assert "get_service_supabase()" in src
    assert src.index("open_drop") < src.index("gst_2b_bulk_service.process(")
    assert src.index("gst_2b_bulk_service.process(") < src.index("gst_2b_drop_record.record(")


def test_every_read_and_write_of_the_two_tables_names_the_firm():
    tree = ast.parse(inspect.getsource(rec))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "table":
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and arg.value.startswith("gstr2b_bulk_drop"):
                chain = ast.unparse(_outermost(tree, node))
                assert (".eq('firm_id'" in chain) or ("'firm_id': firm_id" in chain) or ('_row(firm_id' in chain), chain


def _outermost(tree, call):
    best = call
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and call in ast.walk(node):
            if len(ast.unparse(node)) > len(ast.unparse(best)) and ast.unparse(node).count(".table(") == 1:
                best = node
    return best
