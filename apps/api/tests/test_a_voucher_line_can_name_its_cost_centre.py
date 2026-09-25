"""A voucher line can say which part of the business it belongs to (ACC-13).

WHAT THIS GUARDS, AND WHY EACH HALF EXISTS

  THE REPLACEMENT. Migration 418 does `CREATE OR REPLACE` on three functions,
  which overwrites whatever is there — so a replacement either carries every
  earlier change forward or silently REVERTS it, and the revert compiles,
  deploys and passes a mock suite. Migration 384 got exactly this wrong twice
  before the real-Postgres suite caught it: once by hand-writing the body, once
  by deriving it faithfully from the WRONG ANCESTOR (243 rather than 274, which
  would have reproduced a production incident). So this reconstructs each
  ancestor the way the database finds it — the highest-numbered migration
  defining the function BEFORE 418, excluding `_rollback` files, which define
  the OLD body and are the trap a `| tail -1` walks into — and asserts 418's
  version is that text plus the named cost-centre edits and nothing else.

  THE DIMENSION. A cost centre must change no figure. GST, TDS and the ITR are
  computed from documents and accounts, and a departmental P&L is management
  reporting rather than Schedule III — so a test asserts no return builder
  mentions the column at all. A dimension that leaked into a statutory total
  would be the worst possible version of this feature.

  THE EDIT PATH, which is the half that would have been forgotten.
  `edit_posted_journal` DELETEs every line and re-INSERTs the array it is
  given, so a key the payload does not carry is a value ERASED on the first
  correction — silently, because the report simply shows less. 384's own
  comment recorded that this payload carries four keys per line; it carries
  five now, and this pins both ends.
"""
from __future__ import annotations

import ast
import pathlib
import re

import pytest

from domain.accounting import cost_centre as rule
from services import cost_centre_service as svc

API = pathlib.Path(__file__).resolve().parents[1]
_MIG = API / "migrations"

_M418 = "418_a_voucher_line_can_name_its_cost_centre.sql"
_M418_BACK = "418_a_voucher_line_can_name_its_cost_centre_rollback.sql"

_HEAD_POST = "CREATE OR REPLACE FUNCTION public.post_journal_atomic"
_HEAD_EDIT = "CREATE OR REPLACE FUNCTION public.edit_posted_journal"
_HEAD_TRIG = "CREATE OR REPLACE FUNCTION public.assert_journal_lines_belong_to_the_client"


def _mig(name: str) -> str:
    return (_MIG / name).read_text(encoding="utf-8")


def _ancestor(head: str) -> str:
    """The migration that LAST defined this function BEFORE 418.

    By NUMBER, the way the database resolves it, rather than named — a named
    ancestor goes stale the day somebody replaces the function again, which is
    precisely how 384's first guard passed over a reverted SECURITY DEFINER.
    `_rollback` files are skipped because they define the OLD body: a
    `grep -l … | tail -1` picks one up and answers the previous version.
    """
    best = None
    for path in sorted(_MIG.glob("[0-9][0-9][0-9]_*.sql")):
        if path.name[:3] >= "418" or "rollback" in path.name:
            continue
        if head in path.read_text(encoding="utf-8"):
            best = path.name
    assert best, f"no migration defines {head} before 418"
    return best


def _fn(sql: str, head: str) -> str:
    """One function's text, from its CREATE to its closing dollar-quote."""
    start = sql.index(head)
    best = None
    for close in ("\n$function$;", "\n$$;", "\nEND $$;"):
        at = sql.find(close, start)
        if at != -1 and (best is None or at < best[0]):
            best = (at, close)
    assert best, f"{head} is not closed by a dollar-quote"
    at, close = best
    return sql[start:at + len(close)]


# ── THE REPLACEMENT ──────────────────────────────────────────────────────────

def test_the_ancestors_are_the_ones_the_database_would_have():
    """Belt and braces on the helper. 384 replaced both posting functions and
    360 is the trigger's only definer; a guard that named an earlier one would
    pass while 418 reverted whatever came between."""
    assert _ancestor(_HEAD_POST).startswith("384_")
    assert _ancestor(_HEAD_EDIT).startswith("384_")
    assert _ancestor(_HEAD_TRIG).startswith("360_")


_SUBS = {
    _HEAD_POST: [
        ("rate_date, line_order, cost_centre_id\n  )", "rate_date, line_order\n  )"),
        ("(ord - 1)::integer),\n", "(ord - 1)::integer)\n"),
        ("    NULLIF(l->>'cost_centre_id', '')::uuid\n", ""),
    ],
    _HEAD_EDIT: [
        ("narration, line_order,\n         cost_centre_id)", "narration, line_order)"),
        ("           (ord - 1)::integer,\n", "           (ord - 1)::integer\n"),
        ("           NULLIF(ln->>'cost_centre_id', '')::uuid\n", ""),
    ],
    # ⚠️ THE TRIGGER'S EDIT IS A BLOCK, NOT TWO TOKENS, and it is removed by
    # its own markers rather than by a literal: 418 ADDS a whole second
    # anti-join between the first RAISE and `RETURN NULL`, so a token-pair
    # substitution would leave it behind and this comparison would be
    # asserting nothing.
    _HEAD_TRIG: [
        ("    v_bad text;\n    v_bad_cc text;\n", "    v_bad text;\n"),
    ],
}

_TRIG_ADDED_FROM = "\n\n    -- ACC-13, migration 418."
_TRIG_ADDED_TO = "    RETURN NULL;"


def _strip_trigger_addition(text: str) -> str:
    start = text.index(_TRIG_ADDED_FROM)
    end = text.index(_TRIG_ADDED_TO, start)
    return text[:start] + "\n" + text[end:]


@pytest.mark.parametrize("head", [_HEAD_POST, _HEAD_EDIT, _HEAD_TRIG])
def test_418s_functions_are_their_predecessors_plus_the_cost_centre_edits(head):
    """Only the intended edits happened. Comments added by 418 are stripped
    first — they carry no behaviour — so what is compared is the CODE."""
    rebuilt = _fn(_mig(_M418), head)
    if head == _HEAD_TRIG:
        rebuilt = _strip_trigger_addition(rebuilt)
    for new, old in _SUBS[head]:
        assert rebuilt.count(new) >= 1, f"substitution not found — {new[:52]!r}"
        rebuilt = rebuilt.replace(new, old, 1)
    # The ADDED comment blocks, removed by their own marker so a change to the
    # code itself cannot hide inside one.
    rebuilt = re.sub(r"^\s*--.*ACC-13.*(\n\s*--.*)*\n", "", rebuilt, flags=re.M)
    rebuilt = "\n".join(l for l in rebuilt.splitlines() if l.strip() != "-- ")
    prev = _fn(_mig(_ancestor(head)), head)
    assert rebuilt.strip() == prev.strip(), (
        f"418's {head} is no longer its predecessor plus the cost-centre edits "
        "— something else changed with it"
    )


@pytest.mark.parametrize("clause", [
    # post_journal_atomic — the privilege model (271), the reversal stamp (274)
    # and the line order (384), all of which a careless rewrite drops.
    "SECURITY DEFINER",
    "post_journal_atomic: caller has no user record in this database",
    "only a Partner may post to the firm''s internal client",
    "v_reversed := NULLIF(p_entry->>'reversal_of', '')::uuid;",
    "COALESCE(is_reversed, false) = false",
    "post_journal_atomic: journal imbalance",
    "refusing to post a zero-value journal entry",
    "jsonb_populate_record(NULL::public.journal_entries, $1)",
    "COALESCE((l->>'line_order')::integer, (ord - 1)::integer)",
    # edit_posted_journal — ACC-04's manual-only gate, the period locks, the
    # passbook rebuild and its assertion.
    "IF COALESCE(v_entry.source_type, '') <> 'manual' THEN",
    "public.journal_period_lock_reason(p_firm, p_client, v_entry.entry_date)",
    "PERFORM public.apb_assert_no_drift();",
    # the trigger — 360's own anti-join must survive beside the new one.
    "do not belong to this entry''s firm and client",
    "LEFT JOIN public.chart_of_accounts coa",
])
def test_418_keeps_every_load_bearing_clause(clause):
    assert clause in _mig(_M418)


@pytest.mark.parametrize("head", [_HEAD_POST, _HEAD_EDIT, _HEAD_TRIG])
def test_the_rollback_restores_each_predecessor_exactly(head):
    back = _mig(_M418_BACK)
    assert _fn(back, head).strip() == _fn(_mig(_ancestor(head)), head).strip()
    assert "cost_centre" not in _fn(back, head)


def test_the_rollback_drops_the_column_before_the_table():
    """Order matters: the trigger must stop reading `cost_centres` before it is
    dropped, and the column must go before the master it references."""
    back = _mig(_M418_BACK)
    col = back.index("DROP COLUMN IF EXISTS cost_centre_id")
    tbl = back.index("DROP TABLE IF EXISTS public.cost_centres")
    trig = back.index(_HEAD_TRIG)
    assert trig < col < tbl


# ── THE COLUMN ───────────────────────────────────────────────────────────────

def test_the_column_is_nullable_with_no_default_and_is_not_backfilled():
    sql = _mig(_M418)
    add = sql[sql.index("ADD COLUMN IF NOT EXISTS cost_centre_id"):]
    head = add[:add.index(";")]
    assert "NOT NULL" not in head and "DEFAULT" not in head
    assert "UPDATE public.journal_lines SET cost_centre_id" not in sql, \
        "418 must not backfill — every line already posted came through a door " \
        "that did not know the column"


def test_the_fk_restricts_rather_than_cascading():
    """CASCADE would delete POSTED JOURNAL LINES when somebody tidied a master,
    and SET NULL would silently un-allocate history a management report was
    built on. RESTRICT is the only sound choice, and is what `is_active` exists
    to make unnecessary."""
    sql = _mig(_M418)
    add = sql[sql.index("ADD COLUMN IF NOT EXISTS cost_centre_id"):]
    head = add[:add.index(";")]
    assert "ON DELETE RESTRICT" in head
    assert "CASCADE" not in head and "SET NULL" not in head


def test_the_trigger_lets_a_null_cost_centre_through():
    """NULL is the NORM, not an omission: a bank leg and a tax leg belong to no
    department. A trigger that refused one would refuse most postings."""
    trig = _fn(_mig(_M418), _HEAD_TRIG)
    assert "WHERE nl.cost_centre_id IS NOT NULL" in trig


def test_the_trigger_matches_the_client_exactly():
    """No `IS NULL` arm, unlike the account join beside it: a firm-level cost
    centre would be a department of the PRACTICE, and `client_id NOT NULL`
    forbids one anyway."""
    trig = _fn(_mig(_M418), _HEAD_TRIG)
    cc = trig[trig.index("LEFT JOIN public.cost_centres"):]
    cc = cc[:cc.index("WHERE")]
    assert "AND cc.client_id = je.client_id" in cc
    assert "IS NULL" not in cc


# ── IT CHANGES NO FIGURE ─────────────────────────────────────────────────────

_STATUTORY = [
    "domain/gst/gstr1_builder.py",
    "domain/gst/gstr3b_computer.py",
    "domain/gst/gstr9_builder.py",
    "domain/reporting/builders.py",
    "domain/reporting/schedule_iii.py",
    "domain/income_tax/itr_json.py",
    "domain/tds/section_rates.py",
]


@pytest.mark.parametrize("path", _STATUTORY)
def test_no_statutory_engine_mentions_the_dimension(path):
    """A cost centre is MANAGEMENT reporting. If one ever reached a return or a
    Schedule III caption, a departmental label would be moving a statutory
    figure — the worst possible version of this feature."""
    p = API / path
    if not p.exists():
        pytest.skip(f"{path} has moved; the rule is unchanged")
    assert "cost_centre" not in p.read_text(encoding="utf-8"), \
        f"{path} reads the cost-centre dimension"


def test_the_posting_kernel_carries_it_and_decides_nothing():
    """The kernel does not resolve, refuse or default it — the door that built
    the line did that, and the database refuses a foreign centre whatever
    reaches here. A branch in the kernel would turn a typo on one screen into a
    500 on every one of the twenty-six posting paths."""
    src = (API / "services" / "phase2_journal_service.py").read_text(encoding="utf-8")
    assert '"cost_centre_id": l.get("cost_centre_id")' in src
    assert "cost_centre_service" not in src, "the kernel resolves the dimension"


# ── THE EDIT PATH ────────────────────────────────────────────────────────────

def test_both_manual_journal_write_paths_carry_the_dimension():
    """The create path, the DRAFT rewrite and the POSTED correction. The third
    is the one that would have been forgotten: it replaces every line, so a key
    it does not carry is a value erased on the first correction."""
    src = (API / "services" / "manual_journal_service.py").read_text(encoding="utf-8")
    assert src.count('"cost_centre_id": _cost_centre(') == 3, (
        "one of the three manual-journal write paths does not carry the "
        "cost centre — a correction there would silently erase it"
    )


def test_the_rpc_payload_and_the_function_agree_about_the_key():
    """The Python side sends `cost_centre_id`; the SQL reads `ln->>'cost_centre_id'`.
    A key spelled differently is silently NULL, which is the erasure again."""
    src = (API / "services" / "manual_journal_service.py").read_text(encoding="utf-8")
    edit = _fn(_mig(_M418), _HEAD_EDIT)
    assert '"cost_centre_id"' in src
    assert "ln->>'cost_centre_id'" in edit


def test_one_resolver_for_both_paths():
    tree = ast.parse((API / "services" / "manual_journal_service.py").read_text(encoding="utf-8"))
    names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "_cost_centre" in names


# ── THE RULE ─────────────────────────────────────────────────────────────────

def test_a_code_is_normalised_so_two_spellings_are_one_centre():
    assert rule.normalise_code(" factory ") == "FACTORY"
    assert rule.normalise_code(None) == ""


@pytest.mark.parametrize("code", ["", "   ", "x" * (rule.CODE_MAX + 1)])
def test_a_bad_code_is_refused_with_a_sentence(code):
    assert rule.problem_with_code(code)


def test_the_unallocated_balance_is_its_own_row_and_is_never_dropped():
    L = rule.AllocatedLine
    out = rule.allocate([
        L("a", "Factory", "e1", "Wages", "expense", 100_000, 0),
        L(None, None, "e1", "Wages", "expense", 7_000, 0),
    ])
    assert out.unallocated is not None
    assert out.unallocated.name == rule.UNALLOCATED
    assert out.unallocated.expense_paise == 7_000
    assert [c.name for c in out.centres] == ["Factory"], \
        "the unallocated row must not be one of the centres"


def test_an_asset_line_is_dropped_even_when_it_carries_a_centre():
    """A CA may legitimately tag the bank leg of a departmental payment.
    Including it would put a bank balance in a departmental result."""
    L = rule.AllocatedLine
    out = rule.allocate([
        L("a", "Factory", "b1", "Bank", "asset", 0, 100_000),
        L("a", "Factory", "e1", "Wages", "expense", 100_000, 0),
    ])
    assert out.centres[0].expense_paise == 100_000
    assert [a.account_name for a in out.centres[0].accounts] == ["Wages"]


def test_a_centre_with_no_activity_is_reported_rather_than_invisible():
    """"The Kolkata branch spent nothing" and "somebody forgot to tag Kolkata"
    are different facts."""
    out = rule.allocate([], {"a": "Factory", "b": "Kolkata"})
    assert out.centres_with_no_activity == ("Factory", "Kolkata")


def test_income_and_expense_are_each_read_the_way_their_own_side_is():
    L = rule.AllocatedLine
    out = rule.allocate([
        L("a", "F", "i1", "Sales", "income", 0, 500_000),
        L("a", "F", "e1", "Wages", "expense", 120_000, 0),
    ])
    c = out.centres[0]
    assert (c.income_paise, c.expense_paise, c.result_paise) == (500_000, 120_000, 380_000)


def test_the_report_refuses_a_balance_sheet_by_cost_centre_and_says_why():
    assert rule.NO_BALANCE_SHEET_BY_COST_CENTRE
    out = rule.allocate([])
    assert rule.NO_BALANCE_SHEET_BY_COST_CENTRE in out.notes
    assert rule.A_DIMENSION_NOT_A_LEDGER in out.notes


# ── THE DOORS ────────────────────────────────────────────────────────────────

def test_a_centre_that_is_not_this_clients_is_refused_never_defaulted():
    c = svc.create_centre(None, "f1", "c1", {"code": "FAC", "name": "Factory"})
    assert svc.resolve(None, "f1", "c1", c["id"]) == c["id"]
    with pytest.raises(ValueError):
        svc.resolve(None, "f1", "c1", "00000000-0000-4000-8000-000000000000")
    assert svc.resolve(None, "f1", "c1", None) is None, \
        "no cost centre is the norm and must not raise"


def test_both_doors_validate_the_code():
    """A validator on the create door only is one PATCH from being none."""
    from routers.cost_centres import CostCentreIn, CostCentreUpdateIn
    with pytest.raises(Exception):
        CostCentreIn(client_id="c", code="", name="x")
    with pytest.raises(Exception):
        CostCentreUpdateIn(code="")
    assert CostCentreUpdateIn().code is None, "None means unchanged"


def test_the_endpoints_are_mounted_and_client_scoped():
    import main
    paths = {r.path for r in main.app.routes}
    assert "/api/cost-centres" in paths
    assert "/api/cost-centres/allocation" in paths
    src = (API / "routers" / "cost_centres.py").read_text(encoding="utf-8")
    # CALL SITES, not mentions: the import line would otherwise make the
    # count pass with one endpoint unguarded.
    assert src.count("assert_client_access(current_user") == 4, \
        "an endpoint does not check the caller may read this client"


# ── THE INSERT PAYLOAD IS A LITERAL, AND THESE KEEP IT ONE ───────────────────
#
# `tests/test_backend_inserts_supply_every_required_column_pg` reads an insert
# payload as a dict LITERAL and cannot see one bound to a NAME, and
# `test_backend_columns_exist_pg` reads a projection the same way. BOTH their
# budgets are EXACT with no headroom, so `insert(row)` here was a CI failure
# as well as a coverage hole — on the only write to `cost_centres`.
#
# So `create_centre` names the six columns twice: once building `row` (which
# the mock branch returns and the fallback uses) and once in the literal the
# real insert is given. Duplication is the price the column guard charges for
# being able to check the write at all — `domain/tally/party_identifiers`
# records paying it for the same reason, and records that RAISING the budget
# would have been the wrong answer where the coverage is recoverable.
#
# ⚠️ `update_centre` still passes a NAME (`patch`) and that one is NOT
# recoverable: the endpoint is PATCH-shaped, so the payload holds only the keys
# the caller supplied, and a literal would have to send every column and NULL
# the ones nobody touched. That is the class the column guard's own comments
# already accept as unreadable by construction. It consumes the last unit of
# that budget, which is why these tests exist rather than a raised number.


def _insert_literal_keys(module: str, table: str) -> set[str]:
    """Keys of the dict literal passed to `.table(<table>).insert(...)`."""
    tree = ast.parse((API / module).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "insert"):
            continue
        inner = node.func.value
        if not (isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Attribute)
                and inner.func.attr == "table"
                and inner.args and isinstance(inner.args[0], ast.Constant)
                and inner.args[0].value == table):
            continue
        assert node.args and isinstance(node.args[0], ast.Dict), (
            f"{module}: the insert payload for {table} is not a dict literal — "
            "test_backend_inserts_supply_every_required_column_pg cannot read "
            "it, and both its budget and the column budget are exact"
        )
        return {k.value for k in node.args[0].keys if isinstance(k, ast.Constant)}
    raise AssertionError(f"{module}: no insert on {table}")


def test_the_cost_centre_insert_names_its_columns_rather_than_spreading():
    keys = _insert_literal_keys("services/cost_centre_service.py", "cost_centres")
    assert keys == {"firm_id", "client_id", "code", "name",
                    "description", "is_active"}, (
        "the literal and the six NOT NULL / defaulted columns have drifted"
    )


def test_the_literal_and_the_row_it_duplicates_cannot_drift():
    """Two spellings of one payload, asserted equal — that is the whole cost."""
    made = svc.create_centre(None, "f-drift", "c-drift",
                             {"code": "fac", "name": "Factory"})
    literal = _insert_literal_keys("services/cost_centre_service.py", "cost_centres")
    # `row` gains an `id` only on the mock branch; every other key must match
    # the literal exactly, or the real insert writes a different set of columns
    # from the one the mock path returns and the tests exercise.
    assert set(made) - {"id"} == literal, (
        "what create_centre RETURNS and what it INSERTS name different columns"
    )


def test_the_write_paths_stay_inside_the_two_exact_budgets():
    """A premise test: this module's own contribution to both, measured.

    Not a copy of those guards — it asserts the SHAPE they read, so this file
    fails here with a sentence about cost centres rather than 25 minutes later
    with a bare number in a pg job.
    """
    import sys
    sys.path.insert(0, str(API / "tests"))
    import _backend_query_parser as parser
    _found, unreadable = parser.scan_file(API / "services" / "cost_centre_service.py")
    assert unreadable == 1, (
        f"expected exactly the PATCH-shaped update to be unreadable, got "
        f"{unreadable} — the column budget has no headroom left"
    )
