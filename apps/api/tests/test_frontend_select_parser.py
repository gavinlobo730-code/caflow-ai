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
