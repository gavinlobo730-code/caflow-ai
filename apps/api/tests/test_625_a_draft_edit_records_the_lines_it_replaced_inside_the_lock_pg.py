"""Migration 625: a draft's edit records the lines it replaced from inside the transaction that holds the header's lock (POST-A-429).

WHAT IS HELD, against a migration-built database
    * the function answers `{"count": n, "replaced": [...]}`, and `replaced` is exactly the lines its own DELETE removed;
    * two saves of one draft each name, as replaced, the lines the save before them wrote (the second save's answer is the first's lines,
      not the lines a read made before either took the lock would have found);
    * it is still SECURITY INVOKER, executable by `authenticated` and `service_role` and by nobody else, and a refusal changes nothing;
    * its rollback puts back migration 560's function, whose answer is the bare count.
The service side (what `replace_draft_lines` records from that answer) is held in
`tests/test_an_edit_of_a_document_records_what_it_replaced.py`.
"""
from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
_m560 = importlib.import_module("test_560_a_draft_documents_lines_are_replaced_in_one_transaction_that_locks_the_header_first_pg")
seeded = _m560.seeded
world = _m560.world
_call, _el, _draft_of, _answer, _rows = _m560._call, _m560._el, _m560._draft_of, _m560._answer, _m560._rows
FUNCTION, KINDS = _m560.FUNCTION, _m560.KINDS
MIGRATION, ROLLBACK = _m560.LATER, _m560.LATER_ROLLBACK

pytestmark = pytest.mark.skipif(_m560._m539._ADMIN is None, reason="the replaced-lines proof requires HARNESS_PG + psql")


def _replaced_hsn(done: subprocess.CompletedProcess) -> list[str]:
    answer = json.loads(_answer(done))
    return sorted(r.get("hsn_sac") or "-" for r in answer["replaced"])


@pytest.mark.parametrize("kind", KINDS)
def test_the_answer_names_the_lines_the_call_removed(world, kind):
    doc = _draft_of(world, kind)
    first = _call(world.dsn, "service_role", kind, doc, [_el(kind, "6101"), _el(kind, "6102")])
    assert first.returncode == 0, first.stderr
    second = _call(world.dsn, "service_role", kind, doc, [_el(kind, "6201")])
    assert second.returncode == 0, second.stderr
    answer = json.loads(_answer(second))
    assert answer["count"] == 1
    assert _replaced_hsn(second) == ["6101", "6102"], "the second save names the first save's lines as the ones it replaced"
    assert all(str(r.get(_m560._fk(kind))) == doc for r in answer["replaced"]), "a replaced line is the document's own"


def test_a_draft_with_no_lines_names_none(world):
    doc = _draft_of(world, "sales_invoice")
    assert _call(world.dsn, "service_role", "sales_invoice", doc, []).returncode == 0
    done = _call(world.dsn, "service_role", "sales_invoice", doc, [_el("sales_invoice", "6301")])
    assert done.returncode == 0, done.stderr
    assert json.loads(_answer(done))["replaced"] == []


def test_the_function_is_still_the_callers_and_answers_jsonb(world):
    assert _rows(world.dsn, f"SELECT prosecdef, prorettype::regtype::text FROM pg_proc WHERE oid = '{FUNCTION}'::regprocedure") == [["f", "jsonb"]]
    got = {r: _rows(world.dsn, f"SELECT has_function_privilege('{r}', '{FUNCTION}', 'EXECUTE')")[0][0]
           for r in ("anon", "authenticated", "service_role", "public")}
    assert got == {"anon": "f", "authenticated": "t", "service_role": "t", "public": "f"}, got


def test_the_rollback_puts_back_the_count_and_the_migration_comes_back_again(world):
    def run(path):
        done = subprocess.run(["psql", world.dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-1", "-f", str(path)], capture_output=True, text=True)
        assert done.returncode == 0, done.stderr
    doc = _draft_of(world, "purchase_bill")
    run(ROLLBACK)
    done = _call(world.dsn, "service_role", "purchase_bill", doc, [_el("purchase_bill", "6401")])
    assert done.returncode == 0 and _answer(done) == "1", done.stderr
    run(MIGRATION)
    run(MIGRATION)
    done = _call(world.dsn, "service_role", "purchase_bill", doc, [_el("purchase_bill", "6402")])
    assert done.returncode == 0, done.stderr
    assert _replaced_hsn(done) == ["6401"]
