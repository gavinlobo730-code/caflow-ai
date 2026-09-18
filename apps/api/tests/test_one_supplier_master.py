"""
There is one supplier master, and it is public.vendors. PUR-16.

WHAT WAS WRONG
    `apps/web/app/accounting/suppliers/page.tsx` read and wrote
    `public.suppliers` (migration 030) straight over PostgREST. Every purchase
    path in the product reads `public.vendors`: bill creation, TDS withholding,
    the AP ageing, the Schedule III payables note, GSTR-2B matching and
    s.43B(h). Two masters, and no join between them.

    The credit limit was the harmless half — nothing anywhere reads one, on a
    vendor or on a client. The TDS SECTION was not. A CA who opened Supplier
    Master, picked 194J against a professional firm and saved it wrote
    `suppliers.tds_section`; the bill path read `vendors.tds_section`, found
    NULL, and withheld nothing. IT Act s.40(a)(ia) disallows the WHOLE
    expenditure for an under-deduction, and s.201(1) makes the deductor liable
    for the tax with s.201(1A) interest on top.

WHAT THIS HOLDS
    Three things, because the fix has three halves that can regress apart: the
    dead table stays dead, the column that let the screen move carries the
    right shape, and the screen speaks the surviving master's vocabulary —
    which is not the retired one's, on three fields, one of them a different
    UNIT (tds_rate_percent -> tds_rate_bps).

    Same shape as tests/test_the_dead_tds_rate_master_has_no_readers.py, which
    holds migration 371's half of the same pattern.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from tests._python_source import blank_python_docstrings

TABLE = "suppliers"

_API = Path(".")
_WEB = Path("../web")

_MIGRATION = Path("migrations/378_one_supplier_master_and_the_other_one_says_it_is_dead.sql")

#: Where the name is allowed to appear.
#:
#: The last three are POLICY CATALOGUES, not readers. Migration 261 gave
#: `suppliers` role-scoped write policies and those policies still exist in the
#: database, so all three tests must keep naming it or they stop describing the
#: schema — test_sql_role_tiers_match_python reads the SQL and compares, and
#: dropping the entry would fail it. Naming a table in a catalogue of its own
#: policies is not reading it.
_ALLOWED_SUFFIXES = (
    "migrations/030_supplier_tds_and_credit.sql",
    "migrations/041_grant_all_tables_to_authenticated.sql",
    "migrations/261_role_write_policies_batch_two.sql",
    "migrations/378_one_supplier_master_and_the_other_one_says_it_is_dead.sql",
    "migrations/378_one_supplier_master_and_the_other_one_says_it_is_dead_rollback.sql",
    "tests/test_one_supplier_master.py",
    "tests/test_direct_write_tables_are_role_guarded.py",
    "tests/test_sql_role_tiers_match_python.py",
    "tests/test_role_write_policies_pg.py",
)

#: The production snapshots record the table because it IS in production. They
#: are a picture of the database, not a reader of it — see docs/schema-drift.md.
_ALLOWED_PREFIXES = ("tests/fixtures/",)

_SEARCHED = ("*.py", "*.ts", "*.tsx", "*.sql", "*.json")

#: The word appears in prose all over the product — "supplier" is what a CA
#: calls a vendor. Only a QUERY against the table is the defect, and these are
#: the two ways to write one.
_QUERY_SHAPES = ('from("suppliers")', "from('suppliers')",
                 'table("suppliers")', "table('suppliers')",
                 "public.suppliers", "FROM suppliers", "INTO suppliers")


def _sql_string_after(sql: str, start: int) -> str:
    """The concatenated string literal of the statement beginning at `start`.

    SQL adjacent literals are one value, so a comment written over several
    lines is a single stored string; this joins them and unescapes `''`.
    """
    out, i, n = [], start, len(sql)
    while i < n:
        ch = sql[i]
        if ch == "'":
            j = i + 1
            buf = []
            while j < n:
                if sql[j] == "'":
                    if j + 1 < n and sql[j + 1] == "'":
                        buf.append("'")
                        j += 2
                        continue
                    break
                buf.append(sql[j])
                j += 1
            out.append("".join(buf))
            i = j + 1
            continue
        if ch == ";":
            break
        i += 1
    return "".join(out)


def _strip_comments(body: str, suffix: str) -> str:
    """Comments blanked, so a scan does not report the documentation of its own
    fix. Every hit on the first run of this module was one of its own comments
    naming the thing it bans, which is the same trap
    test_frontend_status_values_match_the_check_pg.py records."""
    if suffix in (".ts", ".tsx"):
        body = re.sub(r"/\*[\s\S]*?\*/", "", body)
        # `//` is only a comment when not preceded by a colon, so `https://`
        # inside a string survives.
        return re.sub(r'(^|[^:])//[^\n]*', r"\1", body)
    if suffix == ".py":
        return blank_python_docstrings(re.sub(r"(?m)#[^\n]*", "", body))
    if suffix == ".sql":
        return re.sub(r"(?m)--[^\n]*", "", body)
    return body


def _files():
    for root in (_API, _WEB):
        if not root.exists():
            continue
        for pattern in _SEARCHED:
            for path in root.rglob(pattern):
                text = str(path).replace("\\", "/")
                if any(part in text for part in
                       ("/node_modules/", "/.next/", "/__pycache__/", "/.git/")):
                    continue
                yield path, text


# ── 1. The dead table stays dead ─────────────────────────────────────────────

def test_no_code_queries_the_retired_supplier_table():
    offenders = []
    for path, text in _files():
        if any(text.endswith(suffix) for suffix in _ALLOWED_SUFFIXES):
            continue
        if any(text.startswith(prefix) for prefix in _ALLOWED_PREFIXES):
            continue
        try:
            body = path.read_text(errors="ignore")
        except OSError:
            continue
        if any(shape in _strip_comments(body, path.suffix) for shape in _QUERY_SHAPES):
            offenders.append(text)
    assert offenders == [], (
        f"public.{TABLE} is retired (migration 378) and no purchase path reads "
        "it. A TDS section recorded there withholds nothing, and s.40(a)(ia) "
        "disallows the whole expenditure. The supplier master is "
        f"public.vendors, through /api/vendors: {offenders}")


def test_the_table_says_in_the_database_that_it_is_retired():
    """A guard in the test suite is invisible to somebody reading the schema in
    a SQL client, which is where the temptation starts."""
    sql = _MIGRATION.read_text()
    start = sql.find("COMMENT ON TABLE public.suppliers IS")
    assert start >= 0, "the retired table must carry a COMMENT"
    stored = _sql_string_after(sql, start)
    assert "RETIRED" in stored
    assert "public.vendors" in stored
    assert "s.40(a)(ia)" in stored


def test_the_migration_does_not_drop_it():
    """A DROP moves both sides of the production-fixture comparison at once and
    is a separate change — migration 371 took the same decision for the dead
    TDS rate master, and docs/schema-drift.md says how to do it."""
    sql = _MIGRATION.read_text()
    assert "DROP TABLE" not in sql.upper()


# ── 2. The column that let the screen move ───────────────────────────────────

def test_the_credit_limit_column_is_nullable_with_no_default():
    """Migration 202 took NOT NULL DEFAULT 30 off `credit_days` because "no
    terms confirmed" and "Due on Receipt" are different facts. A credit limit
    is the same: an untouched row means nobody recorded a limit, and a recorded
    ZERO means no credit at all."""
    sql = _MIGRATION.read_text()
    assert "ADD COLUMN IF NOT EXISTS credit_limit_paise BIGINT" in sql
    add = sql[sql.index("ADD COLUMN IF NOT EXISTS credit_limit_paise"):]
    stmt = add[:add.index(";")]
    assert "NOT NULL" not in stmt.upper(), "a limit nobody recorded is not zero"
    assert "DEFAULT" not in stmt.upper(), "a limit nobody recorded is not zero"


def test_the_column_comment_does_not_claim_a_control_that_does_not_exist():
    """Nothing in apps/api or apps/web blocks or warns on a bill that would
    exceed a credit limit — not for a vendor and not for a client. The comment
    has to say so, or the next reader builds a report on top of an enforcement
    that was never written."""
    sql = _MIGRATION.read_text()
    start = sql.find("COMMENT ON COLUMN public.vendors.credit_limit_paise IS")
    assert start >= 0
    stored = _sql_string_after(sql, start)
    assert "RECORDED, NOT ENFORCED" in stored


def test_nothing_enforces_a_credit_limit_yet():
    """The premise of the comment above, asserted so it cannot go stale
    silently. If a limit ever IS enforced, this test fails and the comment gets
    corrected in the same change."""
    readers = []
    for path, text in _files():
        if text.endswith("tests/test_one_supplier_master.py"):
            continue
        if any(text.startswith(prefix) for prefix in _ALLOWED_PREFIXES):
            continue
        if text.endswith(".sql"):
            continue          # the column has to be declared somewhere
        try:
            body = path.read_text(errors="ignore")
        except OSError:
            continue
        if "credit_limit_paise" in _strip_comments(body, path.suffix):
            readers.append(text)
    # The vendor models declare it, the api client types it and the screen
    # renders it. None of those is an enforcement.
    #
    # `tests/production_types.py` was a fourth entry and is gone, exactly as
    # the note it carried predicted: it named the column as added after the
    # snapshot, and the snapshot was refreshed to migration 381 on the evening
    # of 13 September 2026, so the entry went with it.
    assert sorted(readers) == [
        "../web/app/accounting/suppliers/page.tsx",
        "../web/lib/api/index.ts",
        "models/parties.py",
    ], (
        "something new touches credit_limit_paise. If a bill is now blocked or "
        "flagged by it, migration 378's column comment says RECORDED, NOT "
        f"ENFORCED and has to be corrected: {sorted(readers)}")


# ── 3. The models carry it, and refuse a negative ────────────────────────────

def test_both_vendor_models_accept_a_credit_limit():
    from models.parties import VendorIn, VendorUpdateIn
    assert VendorIn(client_id="c", name="X", credit_limit_paise=500000).credit_limit_paise == 500000
    assert VendorUpdateIn(credit_limit_paise=0).credit_limit_paise == 0
    # Unset is a real third state, distinct from zero.
    assert VendorIn(client_id="c", name="X").credit_limit_paise is None
    assert VendorUpdateIn().credit_limit_paise is None


@pytest.mark.parametrize("model_name", ["VendorIn", "VendorUpdateIn"])
def test_a_negative_credit_limit_is_refused_at_both_doors(model_name):
    """The DB CHECK refuses it; mock mode has no CHECK, so without the model
    validator a test written in mock mode passes against a request production
    rejects. A validator only at the create door is one PATCH from being none."""
    import models.parties as parties
    model = getattr(parties, model_name)
    kwargs = {"credit_limit_paise": -1}
    if model_name == "VendorIn":
        kwargs |= {"client_id": "c", "name": "X"}
    with pytest.raises(Exception) as exc:
        model(**kwargs)
    assert "negative" in str(exc.value).lower()


def test_the_database_refuses_it_too():
    """The model and the CHECK have to agree about the same boundary."""
    sql = _MIGRATION.read_text()
    assert "vendors_credit_limit_paise_check" in sql
    assert "credit_limit_paise IS NULL OR credit_limit_paise >= 0" in sql


# ── 4. The screen speaks the surviving master's vocabulary ───────────────────

_SCREEN = _WEB / "app/accounting/suppliers/page.tsx"

#: The three fields whose names differ between the two masters. The third is
#: also a different UNIT, which is the one that would have been wrong silently:
#: writing a percentage into a basis-points column stores 10 where 1000 is
#: meant, withholding 0.1% instead of 10%.
_RETIRED_SPELLINGS = ("supplier_name", "payment_terms_days", "tds_rate_percent")


@pytest.mark.skipif(not _SCREEN.exists(), reason="apps/web not present")
def test_the_screen_does_not_use_the_retired_column_names():
    body = _strip_comments(_SCREEN.read_text(), ".tsx")
    used = [name for name in _RETIRED_SPELLINGS if name in body]
    assert used == [], (
        "these are public.suppliers' column names; public.vendors calls them "
        f"name, credit_days and tds_rate_bps (BASIS POINTS): {used}")


@pytest.mark.skipif(not _SCREEN.exists(), reason="apps/web not present")
def test_the_screen_goes_through_the_api_not_postgrest():
    """Direct PostgREST writes skip rbac() entirely — CLAUDE.md's second data
    path. This screen sets a TDS section, which decides what is withheld."""
    body = _strip_comments(_SCREEN.read_text(), ".tsx")
    assert "api.vendors" in body
    assert 'from("suppliers")' not in body
    assert 'from("vendors")' not in body, (
        "the vendor master is reached through /api/vendors so rbac() runs, not "
        "over PostgREST")


@pytest.mark.skipif(not _SCREEN.exists(), reason="apps/web not present")
def test_the_screen_records_a_section_and_not_a_rate():
    """INVERTED on 17-09-2026, and the inversion is the finding (PUR-06 = TDS-13).

    This used to assert the TDS Rate box converted its percentage to basis
    points through lib/money's parser — right about the CONVERSION and wrong
    about the box, which should not have existed. Nothing in this package reads
    `vendors.tds_rate_bps`: `services/vendor_tds.resolve_resident_tds` resolves
    the rate from `domain/tds/section_rates.py` for the bill's own financial
    year, with the individual/company split and s.206AA's floor. So the box
    showed a CA a rate, stored it, and withheld at a different one — and the
    list column showed the stale figure without anything being opened.

    A rate BELOW the section's is a s.197 certificate, which s.197(1) has the
    Assessing Officer issue for a specified amount and a specified period. Four
    facts; `domain/tds/lower_deduction.py` holds them and names this screen in
    its own docstring.

    `apps/web/scripts/a-screen-does-not-set-a-vendors-tds-rate.test.ts` states
    the rule for every screen at once and is where a third copy fails. This
    test stays because it is about THIS screen, which is where the second copy
    lived after the first was removed.
    """
    body = _strip_comments(_SCREEN.read_text(), ".tsx")
    assert "tds_rate_bps" not in body, (
        "the supplier master mentions the vendor's TDS rate again. It is not "
        "read by any withholding path — see domain/tds/lower_deduction.py.")
    assert "bpsFromPercentInput" not in body, (
        "a percentage-to-basis-points conversion is back on this screen; the "
        "only basis-points column it wrote was the dead one.")
    # The money rule survives the inversion: the screen still takes a credit
    # limit in rupees, and `parseFloat(x) * 100` is banned there too.
    assert "parseFloat" not in body


def test_a_docstring_is_prose_but_a_sql_constant_is_a_read():
    """The blanking above is what lets a module EXPLAIN this ban, and it is one
    careless widening away from hiding a real query.

    A triple-quoted module-level constant holding SQL is quoted exactly like a
    docstring and IS a read of the table, so the blanking goes through the AST
    node by node rather than over every triple-quoted string. Both halves are
    asserted here, because only the second one can fail silently.
    """
    q = chr(34) * 3
    prose = f"{q}Its hazard is public.suppliers' shape.{q}\nx = 1\n"
    assert "public.suppliers" not in _strip_comments(prose, ".py")

    constant = f"SQL = {q}\n    SELECT id FROM suppliers\n{q}\n"
    assert "FROM suppliers" in _strip_comments(constant, ".py"), (
        "a triple-quoted SQL constant is not a docstring and must stay visible "
        "to the scan")

    nested = (f"def f():\n    {q}reads public.suppliers{q}\n\n"
              f"class C:\n    {q}also public.suppliers{q}\n")
    assert "public.suppliers" not in _strip_comments(nested, ".py")

    # A file that does not parse keeps its whole body: the scan must never go
    # quiet on a file it could not read.
    broken = 'def f(:\n    x = supabase.table("suppliers")\n'
    assert 'table("suppliers")' in _strip_comments(broken, ".py")
