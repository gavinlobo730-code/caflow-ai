"""A test that finds a migration by a pattern finds exactly one file (ledger POST-A-574).

WHAT WAS WRONG
    `MIGRATION = next(API_ROOT.glob("migrations/660_*.sql"))` matches two files: the migration and its `_rollback.sql`. `glob` gives them
    in the order the directory lists them, which is the filesystem's and differs between machines, so the "migration" was the rollback on
    some of them. On 27-11-2026 the real-database job ran the rollback where the test meant the migration, the table was gone, and the
    check failed on a pull request that had not touched the test. Four tests chose a file this way (660 twice, 391, 414); two of them
    read the file's text in the mock-mode suite, where the same accident reads the wrong file.

THE RULE
    Wherever a test takes the FIRST match of a pattern over the migrations directory (`next(<path>.glob("...sql"))`, with or without a
    default), the pattern matches exactly one file today. A pattern that is filtered (`next(p for p in ....glob(...) if ...)`) has said
    which file it wants and is not judged here. The scan reads every test module, so a new one is covered the day it is written.
"""
from __future__ import annotations

import ast
from pathlib import Path

API = Path(__file__).resolve().parents[1]
MIGRATIONS = API / "migrations"


def _first_of_a_glob(tree: ast.AST):
    """Every `next(X.glob("<literal>") [, default])`: (line, the literal pattern)."""
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "next" and node.args):
            continue
        source = node.args[0]
        if (isinstance(source, ast.Call) and isinstance(source.func, ast.Attribute) and source.func.attr in ("glob", "rglob")
                and source.args and isinstance(source.args[0], ast.Constant) and isinstance(source.args[0].value, str)):
            yield node.lineno, source.args[0].value


def _matches(pattern: str) -> list[str]:
    """The files of the migrations directory the pattern names, whether it was written from the API root or from the directory."""
    name = pattern.split("/")[-1]
    return sorted(p.name for p in MIGRATIONS.glob(name))


def test_the_first_match_of_a_migration_pattern_is_the_only_match():
    two_or_more, seen = [], 0
    for path in sorted((API / "tests").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if ".sql" not in text or "glob(" not in text:
            continue
        for line, pattern in _first_of_a_glob(ast.parse(text)):
            if not pattern.endswith(".sql"):
                continue
            seen += 1
            found = _matches(pattern)
            if len(found) > 1:
                two_or_more.append(f"{path.relative_to(API).as_posix()}:{line} {pattern!r} matches {found}")
    assert not two_or_more, (
        "these tests take the first match of a pattern that matches more than one migration file, so which file they read depends on the "
        "order a directory is listed in (it differs between machines). Name the file in full, or filter the rollback out: "
        + "; ".join(two_or_more))
    assert seen >= 15, f"the scan found only {seen} such choices: it has stopped seeing them"


def test_the_scan_sees_the_shape_that_failed_and_leaves_a_filtered_choice_alone():
    old = 'M = next(API_ROOT.glob("migrations/660_*.sql"))\nN = next(api.glob("migrations/414_*.sql"), None)\n'
    assert [p for _l, p in _first_of_a_glob(ast.parse(old))] == ["migrations/660_*.sql", "migrations/414_*.sql"]
    assert len(_matches("migrations/660_*.sql")) == 2, "the pattern that failed no longer matches two files: the control is stale"
    filtered = 'M = next(p for p in MIGRATIONS.glob("660_*.sql") if not p.name.endswith("_rollback.sql"))\n'
    assert list(_first_of_a_glob(ast.parse(filtered))) == []
