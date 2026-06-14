"""
Batch 1 (Amendment v1.1) — migration foundation verification.

Splices the REAL migration files (073 forward applied twice for idempotency,
plus the rollback) into the SQL harness at tests/sql/batch1_foundation_verify.sql
and runs it against a local PostgreSQL via `su postgres -c psql`.

It validates: additive columns + defaults, the five new tables, indexes, FK,
the partner-role helper, RLS (partner-only billing tables; firm-isolated KB),
the clients_external G2 exclusion view, idempotent internal-client provisioning,
and a clean rollback that preserves existing data.

Skips automatically when a local PostgreSQL (and `su`) is not reachable, e.g.
in CI without a database — the migration is also exercised on the real Supabase
project at deploy time.
"""
import os
import shutil
import subprocess
import tempfile
import pathlib

import pytest

HERE = pathlib.Path(__file__).resolve().parent
MIGRATIONS = HERE.parent / "migrations"
FORWARD = MIGRATIONS / "073_revenue_ops_foundation.sql"
ROLLBACK = MIGRATIONS / "073_revenue_ops_foundation_rollback.sql"
HARNESS = HERE / "sql" / "batch1_foundation_verify.sql"
TEST_DB = "batch1_ci"


def _pg_available() -> bool:
    if shutil.which("psql") is None or shutil.which("su") is None:
        return False
    r = subprocess.run(
        ["su", "postgres", "-c", "psql -tAc 'select 1'"],
        capture_output=True, text=True,
    )
    return r.returncode == 0


def _su_psql(sql_args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["su", "postgres", "-c", f"psql {sql_args}"],
        capture_output=True, text=True,
    )


@pytest.mark.skipif(not _pg_available(), reason="local PostgreSQL/su not available")
def test_batch1_foundation_forward_rollback_and_rls():
    forward = FORWARD.read_text()
    rollback = ROLLBACK.read_text()
    harness = HARNESS.read_text()

    spliced_lines = []
    for line in harness.splitlines():
        token = line.strip()
        if token == "--__FORWARD__":
            spliced_lines.append(forward)
        elif token == "--__ROLLBACK__":
            spliced_lines.append(rollback)
        else:
            spliced_lines.append(line)
    sql = "\n".join(spliced_lines)

    # Fresh, isolated database for the run.
    _su_psql(f"-c 'DROP DATABASE IF EXISTS {TEST_DB};' -c 'CREATE DATABASE {TEST_DB};'")

    fd, path = tempfile.mkstemp(suffix=".sql", dir="/tmp")
    os.close(fd)
    pathlib.Path(path).write_text(sql)
    os.chmod(path, 0o644)  # readable by the postgres OS user
    try:
        result = _su_psql(f"-v ON_ERROR_STOP=1 -d {TEST_DB} -f {path}")
        assert result.returncode == 0, (
            "Batch 1 migration verification failed:\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
        assert "ALL ASSERTIONS PASSED" in result.stdout, result.stdout
    finally:
        os.remove(path)
        _su_psql(f"-c 'DROP DATABASE IF EXISTS {TEST_DB};'")
