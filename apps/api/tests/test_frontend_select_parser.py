"""
Unit tests for the PostgREST select parser.

The checker built on this parser (test_frontend_columns_exist_pg.py) reports
problems by NOT finding things, so a parser that quietly stops matching turns
it into a green light. These tests exercise the parser directly on the shapes
that actually appear in apps/web, without a database, so they run everywhere —
including the mock-mode CI job where the pg checker skips entirely.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _frontend_select_parser import parse_select, split_top_level  # noqa: E402


def test_plain_columns():
    cols, _ = parse_select("clients", "id, client_name, gstin")
    assert cols == [("clients", "id"), ("clients", "client_name"), ("clients", "gstin")]


def test_star_is_not_a_column():
    """`select("*")` cannot name a wrong column, so it must not produce one —
    a literal "*" would be reported as missing against every table."""
    assert parse_select("clients", "*")[0] == []


def test_alias_resolves_to_the_real_column():
    """`alias:real` renames in the RESPONSE; the database still has to have
    `real`. Taking the left side would check a name that never reaches SQL."""
    cols, _ = parse_select("clients", "name:client_name")
    assert cols == [("clients", "client_name")]


def test_embed_columns_are_attributed_to_the_embedded_table():
    """The bug that motivated the whole file lived in an embed. Attributing
    `month` to payroll_slips instead of payroll_runs would check the wrong
    table and pass while the query was broken."""
    cols, rels = parse_select("payroll_slips", "id, gross_paise, payroll_runs!inner(month)")
    assert ("payroll_runs", "month") in cols
    assert ("payroll_slips", "id") in cols
    assert ("payroll_slips", "month") not in cols
    assert set(rels) == {"payroll_slips", "payroll_runs"}


def test_aliased_embed_with_join_hint():
    cols, rels = parse_select("a", "run:payroll_runs!left(month, status)")
    assert cols == [("payroll_runs", "month"), ("payroll_runs", "status")]
    assert "payroll_runs" in rels


def test_nested_embeds():
    cols, _ = parse_select("a", "id, b(x, c(y))")
    assert ("a", "id") in cols and ("b", "x") in cols and ("c", "y") in cols


def test_commas_inside_an_embed_do_not_split_the_outer_list():
    """The single thing most likely to silently mis-parse: a naive
    `split(",")` turns `b(x, y)` into `b(x` and `y)` and loses both."""
    assert split_top_level("id, b(x, y), z") == ["id", "b(x, y)", "z"]


def test_casts_and_json_accessors_reduce_to_the_base_column():
    cols, _ = parse_select("t", "payload->>name, amount::text")
    assert cols == [("t", "payload"), ("t", "amount")]


def test_whitespace_and_newlines_are_tolerated():
    cols, _ = parse_select("t", "\n  id,\n  name\n")
    assert cols == [("t", "id"), ("t", "name")]


def test_empty_select_yields_nothing_rather_than_a_blank_column():
    assert parse_select("t", "")[0] == []
    assert parse_select("t", "   ")[0] == []


def test_the_two_real_bugs_this_parser_had_to_see():
    """Regression pin: these exact selects shipped and failed at runtime."""
    cols, _ = parse_select(
        "payroll_employees",
        "id, name, designation, department, pan, bank_account_number, bank_name, ifsc_code")
    assert ("payroll_employees", "bank_account_number") in cols
    assert ("payroll_employees", "ifsc_code") in cols

    cols, _ = parse_select("leave_balances", "id, leave_type, total_days, used_days, year")
    assert ("leave_balances", "leave_type") in cols
    assert ("leave_balances", "total_days") in cols


# ── filter arguments ────────────────────────────────────────────────────────

from _frontend_select_parser import (  # noqa: E402
    parse_chain_filters, parse_write_keys, first_argument,
)


def test_a_filter_column_is_attributed_to_the_table():
    assert parse_chain_filters("clients", '.select("id").eq("status", "active")') == [
        ("clients", "status")]


def test_every_step_of_the_chain_is_walked_not_just_the_first():
    """Regression: the step pattern carried a \\A, which anchors to the start of
    the whole string rather than the current position, so the walk stopped after
    one step and the scan silently returned nothing."""
    got = parse_chain_filters("t", '.select("*").eq("a", 1).gte("b", 2).order("c")')
    assert got == [("t", "a"), ("t", "b"), ("t", "c")]


def test_the_walk_stops_at_the_end_of_the_chain():
    """A filter from a LATER, unrelated query must not be attributed here — the
    reason this walks steps instead of scanning a fixed character window."""
    src = '.select("id").eq("a", 1);\n  const x = sb.from("other").eq("b", 2);'
    assert parse_chain_filters("t", src) == [("t", "a")]


def test_a_dotted_filter_names_the_embedded_relation():
    assert parse_chain_filters("payroll_slips", '.eq("payroll_runs.month", m)') == [
        ("payroll_runs", "month")]


def test_or_expressions_contribute_their_columns():
    got = parse_chain_filters("t", '.or("client_id.eq.5,client_id.is.null")')
    assert got == [("t", "client_id"), ("t", "client_id")]


def test_a_value_containing_a_dot_is_not_read_as_a_column():
    """Only an identifier at the start or just after a comma is a column."""
    assert parse_chain_filters("t", '.or("name.eq.a.b.c")') == [("t", "name")]


def test_a_non_literal_filter_argument_is_skipped_not_guessed():
    assert parse_chain_filters("t", '.eq(colName, 1).eq(`${x}`, 2)') == []


def test_a_paren_inside_a_string_argument_does_not_end_the_call():
    got = parse_chain_filters("t", '.ilike("name", "%a)b%").eq("z", 1)')
    assert got == [("t", "name"), ("t", "z")]


# ── write payloads ──────────────────────────────────────────────────────────

def test_payload_keys_are_read():
    assert parse_write_keys('{ firm_id: f, file_name: n }') == ["firm_id", "file_name"]


def test_shorthand_keys_are_read():
    """Regression: requiring `key:` missed `{ category }` entirely."""
    assert parse_write_keys('{ category, file_size: 1 }') == ["category", "file_size"]


def test_nested_object_keys_are_not_columns():
    assert parse_write_keys('{ a: 1, meta: { inner: 2 } }') == ["a", "meta"]


def test_a_spread_is_not_a_column():
    """Regression: `{ ...input, x: 1 }` reported `input` as a column on three
    different tables."""
    assert parse_write_keys('{ ...input, x: 1 }') == ["x"]


def test_a_comment_inside_a_payload_is_not_a_column():
    """Regression: a `// CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT` line produced
    a phantom `DB` column."""
    assert parse_write_keys('{ // DB: check this\n  a: 1 }') == ["a"]


def test_a_key_like_string_value_is_not_a_column():
    assert parse_write_keys('{ note: "x: 1, y: 2" }') == ["note"]


def test_only_the_payload_argument_is_read():
    """Regression: `.upsert({...}, { onConflict: "..." })` made `onConflict`
    look like a column on six tables."""
    assert first_argument('{ a: 1 }, { onConflict: "firm_id" }') == '{ a: 1 }'
    assert parse_write_keys(first_argument('{ a: 1 }, { onConflict: "x" }')) == ["a"]


def test_first_argument_is_not_confused_by_a_comma_inside_the_payload():
    assert first_argument('{ a: 1, b: 2 }, { onConflict: "x" }') == '{ a: 1, b: 2 }'
