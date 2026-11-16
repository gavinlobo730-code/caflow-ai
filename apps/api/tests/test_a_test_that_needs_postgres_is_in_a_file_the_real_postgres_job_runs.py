"""A test that needs a real Postgres sits in a file the real-Postgres job collects (POST-A-438, the pattern).

WHAT WAS WRONG
    The real-Postgres job runs `tests/test_migrations_apply.py tests/test_atomic_journal_posting.py tests/test_*_pg.py`, and the
    mock job skips anything gated on HARNESS_PG. A test gated on HARNESS_PG (or taking the `pg_template` fixture) in a file whose
    name is none of those runs NOWHERE: it is skipped in one job and never collected by the other, and nothing says so. The
    users-key sweep sat that way and went red on main without anyone seeing it (POST-A-438). The same search found two more:
    `test_per_client_numbering` (then without the `_pg`), whose docstring said "the dedicated `migrations` CI job runs it" while the job's command
    never named it, and the database half of `test_the_member_check_rests_on_two_premises_that_a_test_holds`. Both are
    `_pg` files now.

THE RULE
    Read from the workflow itself (the job's own pytest line, its globs expanded), not from a copy of it: every `tests/test_*.py`
    that takes `pg_template` in a function or reads HARNESS_PG from the environment is a file that line collects.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

API = Path(__file__).resolve().parents[1]
WORKFLOW = API.parents[1] / ".github" / "workflows" / "backend-ci.yml"


def collected_by_the_real_postgres_job(workflow: str = "") -> set[str]:
    """The file names the real-Postgres job's pytest line collects, its globs expanded against tests/."""
    text = workflow or WORKFLOW.read_text(encoding="utf-8")
    job = text[text.index("name: migration apply — real Postgres 16"):]
    lines = [ln for ln in job.splitlines() if re.search(r"\bpytest\b", ln) and "test_*_pg.py" in ln and not ln.lstrip().startswith("#")]
    assert len(lines) == 1, f"expected one pytest line in the real-Postgres job, found {lines}"
    names: set[str] = set()
    for token in lines[0].split():
        if token.startswith("tests/"):
            names |= {p.name for p in API.glob(token)}
    return names


def needs_postgres(source: str) -> bool:
    """Whether a test module needs a real Postgres: a function taking `pg_template`, or HARNESS_PG read from the environment."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if "pg_template" in {a.arg for a in node.args.posonlyargs + node.args.args + node.args.kwonlyargs}:
                return True
        elif isinstance(node, ast.Call):
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if (name in ("get", "getenv") and node.args and isinstance(node.args[0], ast.Constant)
                    and node.args[0].value == "HARNESS_PG"):
                return True
        elif isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) and node.slice.value == "HARNESS_PG":
            return True
    return False


def test_every_test_that_needs_postgres_is_collected_by_the_real_postgres_job():
    collected = collected_by_the_real_postgres_job()
    needing = {p.name for p in sorted((API / "tests").glob("test_*.py")) if needs_postgres(p.read_text(encoding="utf-8"))}
    assert len(collected) >= 150 and len(needing) >= 150, (len(collected), len(needing))
    stranded = sorted(needing - collected)
    assert not stranded, (
        "these modules need a real Postgres but the real-Postgres job does not collect them, and the mock job skips them, so they "
        "run nowhere: name the file `*_pg.py` (or move the database tests into one):\n  " + "\n  ".join(stranded))


def test_the_rule_sees_each_way_a_module_asks_for_postgres_and_reads_the_jobs_own_line():
    assert needs_postgres("def test_x(pg_template):\n    pass\n")
    assert needs_postgres("import os\n_PG = os.environ.get('HARNESS_PG')\n")
    assert needs_postgres("import os\nX = os.getenv('HARNESS_PG')\n")
    assert needs_postgres("import os\nX = os.environ['HARNESS_PG']\n")
    assert not needs_postgres('"""It only runs where HARNESS_PG is set; see pg_template."""\nfixture = "def pg_template():"\n')
    job = ("  migrations:\n    name: migration apply — real Postgres 16\n    steps:\n"
           "      # pytest tests/test_*_pg.py in a comment is not the command\n"
           "      - run: pytest tests/test_migrations_apply.py tests/test_*_pg.py -q\n")
    names = collected_by_the_real_postgres_job(job)
    assert "test_migrations_apply.py" in names and "test_users_fk_columns_take_the_internal_id_pg.py" in names
    assert "test_atomic_journal_posting.py" not in names, "a file the line does not name is not collected"
