"""The reporting architecture document names every read path the reporting code uses.

WHY THIS EXISTS

    `docs/architecture/08-reporting-engine.md` opened "One code path, one source",
    said reports are built from `SupabaseLedgerSource._entries`, that the cache is
    three request-scoped memoizations with "no DB-backed report-cache table", and
    that a materialized `ledger_balances` table "is not read". Every one of those
    stopped being true when the passbook (`account_period_balances`, migrations
    227/228), `public.cash_flow_report` (277) and `public.account_ledger_page`
    (283) were built, and the document named none of them, nor the
    `REPORTING_PASSBOOK_MODE` switch that decides which path serves a report.
    CLAUDE.md's Reporting performance rule is that a report reads a
    trigger-maintained table or a SQL function; a design record that does not say
    which report reads which is the one place a reviewer would look to check.

    The rule is derived from the code, not listed here:

      * every SQL function the reporting package calls through `db.rpc(...)` is
        named in the document, together with the number of the migration that
        LAST defines it (found by scanning the migration directory, the rule
        CLAUDE.md gives for any `CREATE OR REPLACE FUNCTION`): a later migration
        that replaces the function and leaves the document naming an older one
        fails here;
      * every table `ReportingService` reads and every environment switch it
        consults is named;
      * every test file the document points at exists.

    It cannot say a description is RIGHT, only that nothing the code reads through
    is missing from it, which is the half that went stale.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
API = REPO / "apps" / "api"
DOC = REPO / "docs" / "architecture" / "08-reporting-engine.md"
REPORTING = API / "domain" / "reporting"
MIGRATIONS = API / "migrations"


def _calls(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                yield node, first.value


def called_names(source: str, attr: str) -> set[str]:
    """First string argument of every `<anything>.<attr>("name", ...)` call."""
    return {name for node, name in _calls(ast.parse(source))
            if isinstance(node.func, ast.Attribute) and node.func.attr == attr}


def env_switches(source: str) -> set[str]:
    out: set[str] = set()
    for node, name in _calls(ast.parse(source)):
        f = node.func
        label = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
        if label in {"env_or_default", "getenv", "get"} and re.fullmatch(r"[A-Z][A-Z0-9_]{5,}", name):
            out.add(name)
    return out


def last_definer(function: str, migrations: Path = MIGRATIONS) -> int | None:
    """Number of the highest migration that CREATEs (or replaces) `function`."""
    rx = re.compile(
        rf"CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+(?:public\.)?{re.escape(function)}\s*\(",
        re.IGNORECASE)
    best: int | None = None
    for path in migrations.glob("*.sql"):
        if path.stem.endswith("_rollback"):
            continue
        m = re.match(r"(\d+)_", path.name)
        if m and rx.search(path.read_text(encoding="utf-8")):
            best = max(best or 0, int(m.group(1)))
    return best


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def reporting_sources() -> list[Path]:
    return sorted(REPORTING.glob("*.py"))


def rpc_names() -> set[str]:
    return {n for p in reporting_sources() for n in called_names(_read(p), "rpc")}


def tables_read_by_the_service() -> set[str]:
    return called_names(_read(REPORTING / "service.py"), "table")


def switches_read_by_the_service() -> set[str]:
    return env_switches(_read(REPORTING / "service.py"))


def mentions(doc: str, name: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", doc) is not None


def missing(doc: str) -> list[str]:
    out = []
    for fn in sorted(rpc_names()):
        if not mentions(doc, fn):
            out.append(f"the SQL function {fn} is called by domain/reporting and the document does not name it")
            continue
        last = last_definer(fn)
        if last is None:
            out.append(f"{fn}: no migration defines it")
        elif not any(re.search(rf"(?<![0-9]){last}(?![0-9])", line)
                     for line in doc.splitlines() if mentions(line, fn)):
            out.append(f"{fn}: the line naming it does not cite migration {last}, which last defines it")
    for table in sorted(tables_read_by_the_service()):
        if not mentions(doc, table):
            out.append(f"ReportingService reads the table {table} and the document does not name it")
    for env in sorted(switches_read_by_the_service()):
        if not mentions(doc, env):
            out.append(f"ReportingService consults {env} and the document does not name it")
    return out


def test_the_document_names_every_read_path_the_reporting_code_uses():
    found = missing(_read(DOC))
    assert not found, "\n".join(found)


def test_every_test_file_the_document_points_at_exists():
    names = set(re.findall(r"`(tests/test_[A-Za-z0-9_]+\.py)`", _read(DOC)))
    assert len(names) >= 2, "the document stopped naming the tests it points at"
    gone = sorted(n for n in names if not (API / n).is_file())
    assert not gone, f"the document names tests that do not exist: {gone}"


def test_the_collector_is_not_vacuous():
    assert {"cash_flow_report", "account_ledger_page"} <= rpc_names(), rpc_names()
    assert "account_period_balances" in tables_read_by_the_service()
    assert "REPORTING_PASSBOOK_MODE" in switches_read_by_the_service()
    assert last_definer("cash_flow_report") and last_definer("account_ledger_page")
    assert last_definer("cash_flow_report") >= 277


def test_the_rule_fires_on_each_way_the_document_can_be_wrong(tmp_path):
    src = 'db.rpc("a_function", {}); db.table("a_table"); x = env_or_default("A_SWITCH_NAME", "on")'
    assert called_names(src, "rpc") == {"a_function"}
    assert called_names(src, "table") == {"a_table"}
    assert env_switches(src) == {"A_SWITCH_NAME"}
    # the migration scan finds the LAST definer and skips a rollback twin
    (tmp_path / "010_make.sql").write_text("CREATE OR REPLACE FUNCTION public.a_function(x int) ...")
    (tmp_path / "020_change.sql").write_text("create function a_function (x int) ...")
    (tmp_path / "030_change_rollback.sql").write_text("CREATE FUNCTION a_function(x int) ...")
    (tmp_path / "040_other.sql").write_text("CREATE FUNCTION another_function(x int) ...")
    assert last_definer("a_function", tmp_path) == 20
    assert last_definer("nothing", tmp_path) is None
    # a function named as a prefix of another is not that function
    assert not mentions("see cash_flow_report_v2", "cash_flow_report")
    assert mentions("`public.cash_flow_report` (277)", "cash_flow_report")
    # the migration must be cited on the line that names the function, not anywhere
    doc = "| Cash Flow | `public.cash_flow_report` | 277 |\n\nelsewhere: 434\n"
    assert any(not re.search(r"(?<![0-9])434(?![0-9])", ln) for ln in doc.splitlines() if mentions(ln, "cash_flow_report"))
