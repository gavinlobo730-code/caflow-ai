"""The homepage's four figures are COUNTED FACTS, the two copies of them agree, and the
ledger figure is held to the code that makes it true (PRE-B-015 part b, POST-A-120).

THE FIGURES live twice: `HERO_FACTS` in `components/home/Hero.tsx` and the `counters`
array in the "Control & trust" panel of `app/(site)/page.tsx`. A comment in the hero says
"a figure that appears twice had better agree with itself" and nothing checked it, which
is how the page came to say "4 separate tools replaced by one login" in both places and
how the next edit would have changed one. This holds the pair equal, value and label and
order, and holds the one figure whose truth is a fact about the code.

WHAT "1 LEDGER" MAY SAY. The first draft of the replacement figure was "one path that
every posting goes through", pinned by a scan for the one caller of `post_journal_atomic`.
That is NOT true and the scan would have passed anyway: an ordinary rupee receipt is
posted by the `settle_receipt_atomic` database function (migration 160, last restated by
235), which inserts its own `journal_entries` and `journal_lines` inside the transaction
that also writes the receipt and settles its invoices, and never reaches
`post_journal_atomic` or `_create_journal`. Both doors write the SAME two tables and both
refuse an unbalanced entry, so "one ledger" is true and "one path" is not. The figure
therefore says what is on the ledger ("sales, purchases, banking and payroll") and this
file asserts, from the code:

  1. each module the label names posts through the posting kernel
     (`journal_for_*` calls `_create_journal`);
  2. the set of things that WRITE the ledger is closed and named: three database
     functions (two that post an entry, one that rewrites a manual journal's lines)
     and three Python services; a fourth writer fails here with the sentence that
     says the figure has to be re-read before it is allowed to stay;
  3. while more than one database function inserts a journal header, the site does
     not say there is one posting path, however it is spelled.

WHAT THIS DOES NOT REACH, and says so. A chain built across statements
(`q = db.table("journal_lines")` ... `q.insert(...)`) or a table named by a variable is
not seen by the Python scan; the SQL scan reads migrations, not the production catalogue
(`core/schema_guard` and the real-Postgres suite are what tie the two). "11+ modules" is
still not counted against the module directories.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from tests._marketing_copy import MARKETING, blank_comments, sources

API_ROOT = Path(__file__).resolve().parents[1]
HERO = MARKETING / "components" / "home" / "Hero.tsx"
HOME = MARKETING / "app" / "(site)" / "page.tsx"

LEDGER_TABLES = ("journal_entries", "journal_lines")

# The modules the ledger figure names, and the kernel method that posts each. A module
# added to the label with no row here fails below instead of being believed.
MODULE_POSTERS = {
    "sales": "journal_for_sales_invoice",
    "purchases": "journal_for_purchase_bill",
    "banking": "journal_for_bank_transaction",
    "payroll": "journal_for_payroll",
    # named by the Accounting module's description (components/home/Ecosystem.tsx)
    "depreciation": "journal_for_depreciation",
}

# Every database function that inserts into a ledger table, with the tables it writes.
# `edit_posted_journal` writes lines only: it rewrites a MANUAL journal's lines while its
# period is open (migration 266) and never creates a header.
EXPECTED_SQL_WRITERS = {
    "post_journal_atomic": {"journal_entries", "journal_lines"},
    "settle_receipt_atomic": {"journal_entries", "journal_lines"},
    "edit_posted_journal": {"journal_lines"},
}

# Python code that writes a ledger table directly, or calls one of those functions, and
# why. The kernel's own non-RPC fallback and the draft-journal line rewrite are the only
# direct table writes.
EXPECTED_PYTHON_TABLE_WRITERS = {
    ("services/phase2_journal_service.py", "journal_entries"),
    ("services/phase2_journal_service.py", "journal_lines"),
    ("services/manual_journal_service.py", "journal_lines"),
}
EXPECTED_PYTHON_RPC_CALLERS = {
    ("services/phase2_journal_service.py", "post_journal_atomic"),
    ("services/receipt_service.py", "settle_receipt_atomic"),
    ("services/manual_journal_service.py", "edit_posted_journal"),
}


# ── the two copies of the figures ─────────────────────────────────────────────

def _hero_facts(src: str) -> list[tuple[str, str]]:
    block = re.search(r"const HERO_FACTS\s*=\s*\[(.*?)\n\];", blank_comments(src), re.S)
    assert block, "HERO_FACTS not found in Hero.tsx — the figures moved and this guard is blind"
    return re.findall(r'\{\s*value:\s*"([^"]*)"\s*,\s*label:\s*"([^"]*)"\s*\}', block.group(1))


def _page_counters(src: str) -> list[tuple[str, str]]:
    rows = re.findall(
        r'\{\s*n:\s*(\d+)\s*,\s*suffix:\s*"([^"]*)"\s*,\s*label:\s*"([^"]*)"\s*\}',
        blank_comments(src),
    )
    return [(f"{n}{suffix}", label) for n, suffix, label in rows]


def test_the_sweep_reads_both_copies():
    assert len(_hero_facts(HERO.read_text(encoding="utf-8"))) == 4
    assert len(_page_counters(HOME.read_text(encoding="utf-8"))) == 4


def test_the_hero_and_the_control_and_trust_panel_state_the_same_figures():
    hero = _hero_facts(HERO.read_text(encoding="utf-8"))
    page = _page_counters(HOME.read_text(encoding="utf-8"))
    assert hero == page, (
        "the hero's figures and the 'Control & trust' panel's differ — a figure that "
        "appears twice has to agree with itself (value and label, in the same order):\n"
        f"  Hero.tsx HERO_FACTS: {hero}\n  app/(site)/page.tsx counters: {page}"
    )


def test_a_figure_that_lists_things_counts_them_right():
    """'4 Compliance domains — GST, ITR, TDS, MCA' is a count and a list in one string."""
    facts = _hero_facts(HERO.read_text(encoding="utf-8"))
    listed = [(v, label) for v, label in facts if "—" in label and "," in label.split("—", 1)[1]
              and "Compliance domains" in label]
    assert listed, "the compliance-domains figure moved; re-point this check"
    for value, label in listed:
        names = [n for n in re.split(r"\s*,\s*", label.split("—", 1)[1].strip()) if n]
        assert str(len(names)) == value, f"{label!r} names {len(names)} but states {value}"


# ── the ledger figure ─────────────────────────────────────────────────────────

# Words that name a module of the product. A word in the ledger figure's label that is on
# this list has to be one the code is shown to post for.
MODULE_WORDS = {
    "sales", "purchases", "banking", "payroll", "receipts", "payments", "assets",
    "inventory", "accounting", "gst", "tds", "documents", "clients", "compliance",
    "depreciation",
}


def test_the_ledger_figure_is_one_and_names_modules_the_code_posts_for():
    ledger_rows = [(v, lab) for v, lab in _hero_facts(HERO.read_text(encoding="utf-8"))
                   if re.search(r"\bledger\b", lab, re.I)]
    assert len(ledger_rows) == 1, f"expected exactly one ledger figure on the hero, found {ledger_rows}"
    value, label = ledger_rows[0]
    assert value == "1", f"the ledger figure states {value}, and the books are one ledger"
    named = [w for w in re.findall(r"[a-z]+", label.lower()) if w in MODULE_WORDS]
    assert named, f"the ledger figure {label!r} names no module; say what sits on the ledger"
    unproven = [w for w in named if w not in MODULE_POSTERS]
    assert not unproven, (
        f"the ledger figure names {unproven} but no proof here reaches them. Add the "
        f"kernel method that posts for each to MODULE_POSTERS, or take the word out."
    )


def _calls_of(method: ast.FunctionDef) -> set[str]:
    return {n.func.attr for n in ast.walk(method)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}


def test_each_module_the_figure_names_posts_through_the_kernel():
    tree = ast.parse((API_ROOT / "services" / "phase2_journal_service.py").read_text(encoding="utf-8"))
    methods = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    for module, poster in MODULE_POSTERS.items():
        assert poster in methods, f"{module}: {poster} is gone from the posting service"
        assert "_create_journal" in _calls_of(methods[poster]), (
            f"{module}: {poster} no longer posts through _create_journal, so the books of "
            f"{module} are no longer on the ledger the hero figure counts"
        )


# ── who may write the ledger ──────────────────────────────────────────────────

def _tables_in_chain(expr: ast.AST):
    """Every `.table("x")` on the receiver chain of a call, however it is nested."""
    while isinstance(expr, (ast.Call, ast.Attribute)):
        if isinstance(expr, ast.Call):
            fn = expr.func
            if (isinstance(fn, ast.Attribute) and fn.attr == "table" and expr.args
                    and isinstance(expr.args[0], ast.Constant) and isinstance(expr.args[0].value, str)):
                yield expr.args[0].value
            expr = fn
        else:
            expr = expr.value


def python_ledger_writes(source: str) -> tuple[set[str], set[str]]:
    """(ledger tables this module inserts into, ledger-writing RPCs it calls)."""
    tables: set[str] = set()
    rpcs: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr in ("insert", "upsert"):
            tables |= {t for t in _tables_in_chain(node.func.value) if t in LEDGER_TABLES}
        elif (node.func.attr == "rpc" and node.args and isinstance(node.args[0], ast.Constant)
                and node.args[0].value in EXPECTED_SQL_WRITERS):
            rpcs.add(node.args[0].value)
    return tables, rpcs


def _non_test_python() -> list[Path]:
    skip = {"tests", "node_modules", ".hypothesis", "venv", ".venv", "__pycache__"}
    return sorted(p for p in API_ROOT.rglob("*.py") if not skip & set(p.relative_to(API_ROOT).parts))


def _python_writers() -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    table_writers: set[tuple[str, str]] = set()
    rpc_callers: set[tuple[str, str]] = set()
    seen = 0
    for path in _non_test_python():
        src = path.read_text(encoding="utf-8")
        if "journal_" not in src and ".rpc(" not in src:
            continue
        seen += 1
        rel = path.relative_to(API_ROOT).as_posix()
        tables, rpcs = python_ledger_writes(src)
        table_writers |= {(rel, t) for t in tables}
        rpc_callers |= {(rel, r) for r in rpcs}
    assert seen > 20, "the scan read almost nothing; it would pass for any code"
    return table_writers, rpc_callers


def test_only_the_named_python_services_write_the_ledger():
    table_writers, rpc_callers = _python_writers()
    assert table_writers == EXPECTED_PYTHON_TABLE_WRITERS, (
        "a Python module writes a ledger table that is not on the list (or one on the list "
        "stopped). The hero says the books sit on ONE ledger; a new writer is either another "
        "door into it (add it here with its reason) or a second set of books (do not):\n"
        f"  found: {sorted(table_writers)}\n  expected: {sorted(EXPECTED_PYTHON_TABLE_WRITERS)}"
    )
    assert rpc_callers == EXPECTED_PYTHON_RPC_CALLERS, (
        f"the callers of the ledger-writing database functions changed:\n  found: "
        f"{sorted(rpc_callers)}\n  expected: {sorted(EXPECTED_PYTHON_RPC_CALLERS)}"
    )


_SQL_INSERT = re.compile(r"INSERT\s+INTO\s+(?:public\.)?\"?(journal_entries|journal_lines)\"?\b", re.I)
_SQL_FUNCTION = re.compile(r"CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+(?:public\.)?\"?([A-Za-z_0-9]+)", re.I)


_DOLLAR_TAG = re.compile(r"\$([A-Za-z_][A-Za-z_0-9]*)?\$")


def _dollar_quoted_bodies(sql: str) -> list[tuple[int, int]]:
    """(start, end) of every `$tag$ ... $tag$` body, the way the server reads them."""
    spans: list[tuple[int, int]] = []
    open_tag: str | None = None
    start = 0
    for m in _DOLLAR_TAG.finditer(sql):
        tag = m.group(1) or ""
        if open_tag is None:
            open_tag, start = tag, m.end()
        elif tag == open_tag:
            spans.append((start, m.start()))
            open_tag = None
    return spans


def sql_ledger_writers(sql: str) -> dict[str | None, set[str]]:
    """Ledger tables inserted into, by the function whose body holds the INSERT.

    `None` is an INSERT that is NOT inside a CREATE FUNCTION body — a data fix or a DO
    block — which is a writer too, and the one a closed list most needs to see. An INSERT
    after a function in the same file is not credited to that function."""
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    sql = re.sub(r"--[^\n]*", " ", sql)
    bodies = _dollar_quoted_bodies(sql)
    out: dict[str | None, set[str]] = {}
    for m in _SQL_INSERT.finditer(sql):
        owner: str | None = None
        for start, end in bodies:
            if start <= m.start() < end:
                header = [f for f in _SQL_FUNCTION.finditer(sql, 0, start)]
                # the body belongs to the last CREATE FUNCTION only if no statement ended
                # between that header and the opening quote (a DO block has no header)
                if header and ";" not in sql[header[-1].start():start]:
                    owner = header[-1].group(1)
                break
        out.setdefault(owner, set()).add(m.group(1).lower())
    return out


def _migration_ledger_writers() -> dict[str | None, set[str]]:
    files = [p for p in sorted((API_ROOT / "migrations").glob("*.sql"))
             if not p.name.endswith("_rollback.sql") and not p.name.startswith("_")]
    assert len(files) > 300, "the migrations were not found; the scan would pass for any SQL"
    merged: dict[str | None, set[str]] = {}
    for p in files:
        for fn, tables in sql_ledger_writers(p.read_text(encoding="utf-8")).items():
            merged.setdefault(fn, set()).update(tables)
    return merged


def test_only_the_named_database_functions_write_the_ledger():
    found = _migration_ledger_writers()
    assert found == EXPECTED_SQL_WRITERS, (
        "the set of database functions (or data fixes, shown as None) that insert into "
        "journal_entries or journal_lines changed. Re-read the hero's '1 Ledger' figure "
        "and the homepage's 'one ledger' before adding to this list:\n"
        f"  found: { {k: sorted(v) for k, v in found.items()} }\n"
        f"  expected: { {k: sorted(v) for k, v in EXPECTED_SQL_WRITERS.items()} }"
    )


# ── what the site may say about the PATH ──────────────────────────────────────

# However it is spelled: "one posting path", "a single path", "the only door", "every
# posting goes through". The rule is that the site does not claim a single entrance while
# the code has more than one.
SINGLE_PATH = re.compile(
    r"\b(one|single|only|sole)\s+(posting\s+)?(path|door|route|entrance)\b"
    r"|\bevery\s+(posting|entry|transaction)\s+(goes|go|passes|pass|is\s+posted)\s+through\b",
    re.I,
)


def _header_writing_functions(found: dict[str | None, set[str]]) -> list[str]:
    return sorted(str(fn) for fn, tables in found.items() if "journal_entries" in tables)


def test_the_site_does_not_claim_one_posting_path_while_there_are_two_doors():
    doors = _header_writing_functions(_migration_ledger_writers())
    assert len(doors) >= 1, "no function writes a journal header; the scan is broken"
    if len(doors) == 1:
        return  # one function writes a journal header: a single-path claim would be true
    hits = []
    for path in sources():
        for m in SINGLE_PATH.finditer(blank_comments(path.read_text(encoding="utf-8"))):
            hits.append(f"{path.relative_to(MARKETING).as_posix()}: {m.group(0)!r}")
    assert hits == [], (
        f"the site says there is one posting path but {doors} each insert a journal header "
        "(an ordinary receipt is posted by settle_receipt_atomic, everything else by "
        "post_journal_atomic). Say 'one ledger', which is true, not 'one path':\n"
        + "\n".join(hits)
    )


# ── negative controls: the detectors detect ───────────────────────────────────

def test_the_python_scan_sees_a_second_writer():
    src = (
        "def f(db):\n"
        "    db.table('journal_lines').insert([{'a': 1}]).execute()\n"
        "    (db.table('journal_entries')\n"
        "       .upsert({'b': 2}))\n"
        "    db.rpc('settle_receipt_atomic', {})\n"
        "    db.table('invoices').insert({})\n"
    )
    assert python_ledger_writes(src) == ({"journal_lines", "journal_entries"}, {"settle_receipt_atomic"})
    assert python_ledger_writes("def f(db):\n    db.table('journal_lines').select('*')\n") == (set(), set())


def test_the_sql_scan_sees_a_second_writer_and_ignores_comments():
    sql = (
        "-- INSERT INTO journal_entries (nothing)\n"
        "CREATE OR REPLACE FUNCTION public.a() RETURNS void AS $$ BEGIN\n"
        "  INSERT INTO public.journal_entries (x) VALUES (1);\n"
        "END $$ LANGUAGE plpgsql;\n"
        "CREATE FUNCTION b() RETURNS void AS $$ BEGIN\n"
        "  INSERT INTO journal_lines (x) VALUES (1);\n"
        "END $$ LANGUAGE plpgsql;\n"
        "INSERT INTO public.journal_lines (x) SELECT 1;\n"
    )
    # the trailing INSERT sits AFTER function b() and outside its body: it is a data fix
    # (None), not b's, so a closed list sees it.
    assert sql_ledger_writers(sql) == {
        "a": {"journal_entries"}, "b": {"journal_lines"}, None: {"journal_lines"},
    }
    assert sql_ledger_writers("INSERT INTO journal_lines (x) SELECT 1;") == {None: {"journal_lines"}}
    assert sql_ledger_writers("-- INSERT INTO journal_lines\nSELECT 1;") == {}
    # a DO block is a statement, not a function body, whatever precedes it
    do_block = (
        "CREATE FUNCTION c() RETURNS void AS $$ BEGIN NULL; END $$ LANGUAGE plpgsql;\n"
        "DO $fix$ BEGIN INSERT INTO public.journal_entries (x) VALUES (1); END $fix$;\n"
    )
    assert sql_ledger_writers(do_block) == {None: {"journal_entries"}}


@pytest.mark.parametrize("sentence", [
    "Books — one ledger, one posting path",
    "every posting goes through a single door",
    "the only route into the books",
    "Every entry passes through the kernel",
])
def test_the_single_path_rule_detects_what_it_is_for(sentence):
    assert SINGLE_PATH.search(sentence), sentence


@pytest.mark.parametrize("sentence", [
    "one ledger under every module",
    "Ledger under sales, purchases, banking and payroll",
    "one workspace on one ledger",
])
def test_the_single_path_rule_leaves_a_one_ledger_claim_alone(sentence):
    assert not SINGLE_PATH.search(sentence), sentence
