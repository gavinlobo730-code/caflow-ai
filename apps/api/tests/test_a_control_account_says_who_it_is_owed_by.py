"""ACC-13's other half — the party breakdown's rule, in mock mode.

The SQL/Python parity and the invariant that the parts sum to the account are
proved against a real database in `test_party_ledger_parity_pg.py`. This file
holds what does not need one: the vocabulary, the refusals, and the two places
where a shortcut would silently take a read out of a guard.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from domain.accounting import party_ledger as rule
from domain.accounting import journal_source as js

API = pathlib.Path(__file__).resolve().parents[1]


# ── The vocabulary ───────────────────────────────────────────────────────────

def test_every_mapped_source_is_a_real_source_type():
    """A map keyed on a spelling nothing stamps resolves nobody, for ever."""
    assert set(rule.PARTY_SOURCES) <= js.ALL_SOURCES
    assert set(rule.NO_PARTY_REASON) <= js.ALL_SOURCES


def test_a_source_is_either_mapped_or_has_a_reason_but_never_both():
    overlap = set(rule.PARTY_SOURCES) & set(rule.NO_PARTY_REASON)
    assert not overlap, f"{overlap} both resolves a party and explains having none"


def test_every_source_type_is_accounted_for():
    """No source may fall through to the generic sentence unnoticed. A path
    added later must be mapped or explained — which is the choice this test
    exists to force somebody to make."""
    # `bill_of_entry` is in neither map and is NOT generic — it carries its
    # own sentence, because customs is not the supplier (PUR-18) and a reader
    # told only "this report cannot attribute it" would go looking for a
    # mapping to add. Excluded here and asserted separately below.
    unexplained = (js.ALL_SOURCES - set(rule.PARTY_SOURCES)
                   - set(rule.NO_PARTY_REASON) - {"bill_of_entry"})
    # The ones deliberately left to the generic answer, each recorded:
    #   bill_of_entry   — has its OWN sentence, see below
    #   the fixed-asset, CWIP, payroll and settlement sources — they never
    #   touch a party control account, so they are not expected here and get
    #   the generic sentence if they somehow do.
    assert "bill_of_entry" not in set(rule.PARTY_SOURCES), \
        "customs is not the supplier (PUR-18) — a bill of entry names no party"
    assert rule.reason_for("bill_of_entry") == rule.BILL_OF_ENTRY_IS_NOT_A_PARTY
    for src in unexplained:
        assert rule.reason_for(src) == rule.UNKNOWN_SOURCE_REASON


def test_the_five_reasons_are_five_different_sentences():
    """A screen rendering one sentence for five causes tells the CA nothing
    about which to go and look at. Asserted on the ANSWERS, not on the data,
    so moving one in or out cannot make this vacuous."""
    said = [rule.reason_for(s) for s in
            ("manual", "Opening", "TrialBalance", "year_end_adjustment", "bank_transaction")]
    assert len(set(said)) == 5
    assert rule.reason_for(None) not in said
    assert rule.reason_for("bill_of_entry") not in said


# ── The grouping ─────────────────────────────────────────────────────────────

def _ln(source_type, debit=0, credit=0, party=None, kind=None, name=None):
    return {"source_type": source_type, "debit_paise": debit, "credit_paise": credit,
            "party_id": party, "party_kind": kind, "party_name": name}


def test_the_parts_sum_to_the_whole():
    b = rule.breakdown([
        _ln("sales_invoice", 11800000, 0, "c1", rule.CUSTOMER, "Acme"),
        _ln("receipt", 0, 5000000, "c1", rule.CUSTOMER, "Acme"),
        _ln("manual", 0, 700000),
        _ln("Opening", 2500000, 0),
    ])
    assert b.attributed_paise == 6800000
    assert b.unattributed_paise == 1800000
    assert b.total_paise == 8600000 == 11800000 - 5000000 - 700000 + 2500000


def test_a_line_whose_party_could_not_be_resolved_is_not_dropped():
    """It falls to the unattributed side under its OWN source. Dropping it
    would break the invariant silently, which is the one thing that must not
    happen — the report's whole value is that the parts foot."""
    b = rule.breakdown([_ln("sales_invoice", 500000, 0)])
    assert b.total_paise == 500000
    assert len(b.rows) == 1 and b.rows[0].unattributed_source == "sales_invoice"


def test_a_row_is_a_party_or_an_unattributed_source_never_both():
    b = rule.breakdown([
        _ln("purchase_bill", 0, 400000, "v1", rule.VENDOR, "Sharma"),
        _ln("manual", 100000, 0),
    ])
    for r in b.rows:
        assert (r.party_id is None) != (r.unattributed_source is None)
        assert r.is_attributed == (r.party_id is not None)


def test_the_order_is_total_so_one_account_renders_the_same_every_read():
    """`line_order`'s property, applied to a report: ties break on the name
    and then the id, so there is no read where two equal balances swap."""
    lines = [
        _ln("sales_invoice", 100000, 0, "c2", rule.CUSTOMER, "Bravo"),
        _ln("sales_invoice", 100000, 0, "c1", rule.CUSTOMER, "Alpha"),
    ]
    first = [r.party_id for r in rule.breakdown(lines).rows]
    assert first == [r.party_id for r in rule.breakdown(list(reversed(lines))).rows]
    assert first == ["c1", "c2"], "equal balances must order by name"


def test_an_empty_account_answers_a_shape_not_an_error():
    b = rule.breakdown([])
    assert b.rows == [] and b.total_paise == 0
    assert rule.THE_PARTS_SUM_TO_THE_ACCOUNT in b.notes


def test_the_invariant_is_stated_on_every_answer():
    """Not a caveat — the invariant IS the reason to trust the screen, so it
    is said wherever the figures are."""
    assert rule.THE_PARTS_SUM_TO_THE_ACCOUNT in rule.breakdown([_ln("manual", 1, 0)]).notes


# ── THE READS ARE LITERAL, AND THIS KEEPS THEM PINNED TO THE MAP ─────────────
#
# `test_backend_columns_exist_pg` checks every `.select()` against the real
# schema AS A STRING and cannot see a table reached through a VARIABLE. A loop
# over PARTY_SOURCES cost seven unreadable references and took all eight
# document reads out of that check — on the resolution a breakdown that must
# foot depends on. The budget is exact with no headroom, so it was a CI failure
# as well as a coverage hole, and CLAUDE.md records that raising it is the
# wrong answer where the coverage is recoverable.

def _literal_selects(module: str) -> dict[str, str]:
    """{table: projection} for every `.table("x").select("…")` literal pair."""
    tree = ast.parse((API / module).read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "select"):
            continue
        inner = node.func.value
        if not (isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute)
                and inner.func.attr == "table" and inner.args
                and isinstance(inner.args[0], ast.Constant)):
            continue
        assert node.args and isinstance(node.args[0], ast.Constant), (
            f"{module}: the projection for {inner.args[0].value} is not a literal"
        )
        out[inner.args[0].value] = node.args[0].value
    return out


def test_the_eight_document_reads_are_exactly_the_map():
    got = _literal_selects("services/party_ledger_service.py")
    for source, (table, column, _kind) in rule.PARTY_SOURCES.items():
        assert table in got, f"{source}: {table} is not read with a literal projection"
        assert column in got[table], \
            f"{table}: the projection does not name {column}, so the party cannot resolve"


def test_the_party_masters_are_read_with_a_literal_too():
    got = _literal_selects("services/party_ledger_service.py")
    assert "name" in got.get("customers", "") and "name" in got.get("vendors", "")


def test_no_read_in_the_service_reaches_a_table_through_a_variable():
    """The rule, not a spelling of it: measured with the guard's OWN parser, so
    a new dynamic read anywhere in this module fails HERE with a sentence
    rather than 25 minutes later as a bare number in a pg job."""
    import sys
    sys.path.insert(0, str(API / "tests"))
    import _backend_query_parser as parser
    _found, unreadable = parser.scan_file(API / "services" / "party_ledger_service.py")
    assert unreadable == 0, (
        f"{unreadable} unreadable reference(s) — the column budget has no headroom"
    )


# ── The service refuses what it cannot answer ────────────────────────────────

def test_a_breakdown_without_a_client_is_refused():
    """A control account belongs to one client; summing parties across
    unrelated books is not a balance of anything."""
    from fastapi import HTTPException
    from services import party_ledger_service as svc
    with pytest.raises(HTTPException) as e:
        svc.breakdown(None, "f1", "", "acct")
    assert e.value.status_code == 422
    with pytest.raises(HTTPException):
        svc.breakdown(None, "f1", "c1", "")


def test_mock_mode_answers_an_empty_breakdown_rather_than_inventing_one():
    from services import party_ledger_service as svc
    out = svc.breakdown(None, "f1", "c1", "acct", as_of="2026-06-30")
    assert out["rows"] == [] and out["total_paise"] == 0
    assert out["as_of"] == "2026-06-30"
