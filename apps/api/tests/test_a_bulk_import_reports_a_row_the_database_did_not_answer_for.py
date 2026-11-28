"""A bulk import reports a row the database did not answer for, and never inserts it a second time (ledger POST-A-573).

WHAT WAS WRONG
    Four places pair the rows a batch insert SENT with the rows it ANSWERED for, by position. Three of them did it with a bare `zip`,
    which stops at the shorter list without a word: a customer the bulk import sent and got no answer for was in neither `created` nor
    `errors`, and an opening document or an opening asset was reported as new with no id and no failure. The fourth (the vendors' bulk
    create) noticed the short answer and did worse: it sent the whole batch again one row at a time, so every vendor the first insert
    HAD stored was inserted twice (or refused as a duplicate of itself). Found on 27-11-2026 by the independent review of the lint
    sweep that gave those `zip`s the rule `strict=False`, which is what they always did and says unequal is fine, which it is not.

WHAT IS HELD
    `core.exceptions.confirmed_pairs` pairs what was answered and names the rest; each of the four reports the rest in the person's
    words ("did not confirm ... check before importing it again") and sends nothing again. A full answer behaves as before. The source
    is read too: none of the four pairs a batch's answer with a `zip` that tolerates unequal lengths.
"""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.exceptions import ROW_NOT_CONFIRMED, confirmed_pairs

API = Path(__file__).resolve().parents[1]


def test_the_pairing_never_reaches_past_the_answer_and_names_what_was_not_answered():
    assert confirmed_pairs(["a", "b", "c"], [{"id": 1}, {"id": 2}, {"id": 3}]) == ([("a", {"id": 1}), ("b", {"id": 2}), ("c", {"id": 3})], [])
    assert confirmed_pairs(["a", "b", "c"], [{"id": 1}]) == ([("a", {"id": 1})], ["b", "c"])
    assert confirmed_pairs(["a", "b"], None) == ([], ["a", "b"])
    assert confirmed_pairs(["a"], [{"id": 1}, {"id": 2}]) == ([("a", {"id": 1})], []), "an answer longer than what was sent is not paired with nothing"
    assert "did not confirm" in ROW_NOT_CONFIRMED and "before importing it again" in ROW_NOT_CONFIRMED


@pytest.mark.parametrize("rel", ["routers/vendors.py", "routers/customers.py", "services/opening_document_service.py",
                                 "services/opening_register_service.py"])
def test_none_of_the_four_pairs_a_batch_answer_with_a_zip_that_tolerates_unequal_lengths(rel):
    tree = ast.parse((API / rel).read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
    assert any(c.func.id == "confirmed_pairs" for c in calls), f"{rel} no longer pairs its batch answer through confirmed_pairs"
    tolerant = [c.lineno for c in calls if c.func.id == "zip"
                and any(k.arg == "strict" and isinstance(k.value, ast.Constant) and k.value.value is False for k in c.keywords)
                and any(isinstance(a, ast.Name) and a.id in {"got", "batch_rows", "data_rows"} for a in c.args)]
    assert tolerant == [], f"{rel} pairs a batch insert's answer with zip(strict=False) at {tolerant}"


# ── the two opening imports, driven: a short answer is a failure for the rest, and nothing is written one at a time ─────────────────

def test_an_opening_document_the_database_did_not_answer_for_is_rejected_in_words_and_the_chunk_is_written_once(monkeypatch):
    import services.opening_document_service as svc
    from domain.accounting import opening_document_import as imp
    from domain.accounting import opening_documents as od
    verdicts = [imp.Verdict(row=n, document_no=f"OLD-{n}", status=imp.NEW, party_id="P1", outstanding_paise=100) for n in (1, 2, 3)]
    calls = []

    def write(db, firm_id, client_id, kind, chunk, actor_id):
        calls.append([v.row for v in chunk])
        return [{"id": "doc-1"}]                       # the database answered for one of three

    monkeypatch.setattr(svc, "_write", write)
    monkeypatch.setattr(svc, "_import_parties", lambda *a, **k: [])
    monkeypatch.setattr(svc, "_existing_for_import", lambda *a, **k: [])
    monkeypatch.setattr(svc, "_documents", lambda *a, **k: [])
    monkeypatch.setattr(imp, "plan", lambda *a, **k: verdicts)
    rows = [SimpleNamespace(document_no=f"OLD-{n}") for n in (1, 2, 3)]
    out = svc.bulk_create(None, "F", "C", kind=od.RECEIVABLE, rows=rows, actor_id="u1")
    assert calls == [[1, 2, 3]], f"the rows the database did not answer for were sent again: {calls}"
    by_row = {r["row"]: r for r in out["rows"]}
    assert (by_row[1]["status"], by_row[1]["id"]) == (imp.NEW, "doc-1")
    for n in (2, 3):
        assert by_row[n]["status"] == imp.REJECTED and by_row[n]["problems"] == [ROW_NOT_CONFIRMED] and not by_row[n]["id"]
    assert (out["created"], out["rejected"]) == (1, 2)


def test_an_opening_asset_the_database_did_not_answer_for_is_rejected_in_words_and_the_chunk_is_written_once(monkeypatch):
    import services.opening_register_service as svc
    reg = svc.reg
    verdicts = [reg.AssetVerdict(row=n, asset_code=f"A{n}", status=reg.NEW) for n in (1, 2, 3)]
    calls = []

    def write(db, firm_id, client_id, planned):
        calls.append(len(planned))
        return [{"id": "asset-1"}]

    monkeypatch.setattr(svc, "_write", write)
    monkeypatch.setattr(svc, "_existing", lambda *a, **k: [])
    monkeypatch.setattr(reg, "plan", lambda *a, **k: verdicts)
    monkeypatch.setattr(reg, "summarise", lambda final: SimpleNamespace(
        received=len(final), new=sum(1 for v in final if v.status == reg.NEW), already_recorded=0,
        rejected=sum(1 for v in final if v.status == reg.REJECTED), cost_paise=0, accumulated_paise=0, net_paise=0, by_category={}, gaps=[]))
    rows = [SimpleNamespace(asset_code=f"A{n}") for n in (1, 2, 3)]
    out = svc.import_register(None, "F", "C", as_at="2026-03-31", rows=rows)
    assert calls == [3], f"the assets the database did not answer for were sent again: {calls}"
    by_row = {r["row"]: r for r in out["rows"]}
    assert (by_row[1]["status"], by_row[1]["id"]) == (reg.NEW, "asset-1")
    for n in (2, 3):
        assert by_row[n]["status"] == reg.REJECTED and by_row[n]["problems"] == [ROW_NOT_CONFIRMED] and not by_row[n]["id"]


# ── the two bulk party imports ─────────────────────────────────────────────────────────────────────────────────────────

def test_the_customers_bulk_import_names_the_rows_the_database_did_not_answer_for():
    """The pairing the route makes, on its own shapes: what was sent is (index, payload) and the answer is the stored rows."""
    to_insert = [(0, {"name": "A"}), (1, {"name": "B"}), (2, {"name": "C"})]
    pairs, unanswered = confirmed_pairs(to_insert, [{"id": "c-1", "name": "A"}])
    assert [(idx, row["id"]) for (idx, _payload), row in pairs] == [(0, "c-1")]
    assert [(idx, payload["name"]) for idx, payload in unanswered] == [(1, "B"), (2, "C")]
    source = (API / "routers" / "customers.py").read_text(encoding="utf-8")
    import routers.customers as customers
    errors: list = []
    assert customers._rows_the_batch_answered_for(to_insert, [{"id": "c-1", "name": "A"}], errors) == [(0, {"id": "c-1", "name": "A"})]
    assert errors == [{"index": 1, "name": "B", "error": ROW_NOT_CONFIRMED}, {"index": 2, "name": "C", "error": ROW_NOT_CONFIRMED}]
    assert "inserted_rows = _rows_the_batch_answered_for(to_insert, data_rows, errors)" in source


def test_the_vendors_bulk_create_never_sends_an_accepted_batch_again():
    """A short answer used to fail the `len(resp.data) == len(valid_items)` test and fall to the per-row path, which inserts every row a
    second time. The batch's answer is used whenever there is one, and the per-row path is reached only when the batch RAISED."""
    source = (API / "routers" / "vendors.py").read_text(encoding="utf-8")
    assert "len(resp.data) == len(valid_items)" not in source
    assert "if resp.data:\n                batch_rows = resp.data" in source
    assert "_vendors_the_batch_answered_for(valid_items, batch_rows, errors)" in source
    import routers.vendors as vendors
    errors: list = []
    pairs = vendors._vendors_the_batch_answered_for([(0, {"name": "A"}), (1, {"name": "B"})], [{"id": "v-1"}], errors)
    assert pairs == [((0, {"name": "A"}), {"id": "v-1"})]
    assert errors == [{"index": 1, "name": "B", "error": ROW_NOT_CONFIRMED}]
