"""
Batch 2 (Amendment v1.1) — RLS guardrail verification.

Splices the REAL migration files (073 + 074 forward, then 074 + 073 rollback)
into tests/sql/batch2_guardrails_verify.sql and runs it against a local
PostgreSQL via `su postgres -c psql`. Proves the RESTRICTIVE G1 policies hide
the internal client's row and financial rows from non-Partners while Partners
retain access, and that removing 074 restores visibility.

Skips automatically when a local PostgreSQL (and `su`) is not reachable.
"""
import os
import shutil
import subprocess
import tempfile
import pathlib

import pytest

HERE = pathlib.Path(__file__).resolve().parent
MIGRATIONS = HERE.parent / "migrations"
HARNESS = HERE / "sql" / "batch2_guardrails_verify.sql"
TEST_DB = "batch2_ci"

MARKERS = {
    "--__FWD_073__": MIGRATIONS / "073_revenue_ops_foundation.sql",
    "--__FWD_074__": MIGRATIONS / "074_internal_client_rls_guardrails.sql",
    "--__RB_074__":  MIGRATIONS / "074_internal_client_rls_guardrails_rollback.sql",
    "--__RB_073__":  MIGRATIONS / "073_revenue_ops_foundation_rollback.sql",
}


def _pg_available() -> bool:
    if shutil.which("psql") is None or shutil.which("su") is None:
        return False
    r = subprocess.run(["su", "postgres", "-c", "psql -tAc 'select 1'"],
                       capture_output=True, text=True)
    return r.returncode == 0


def _su_psql(sql_args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["su", "postgres", "-c", f"psql {sql_args}"],
                          capture_output=True, text=True)


@pytest.mark.skipif(not _pg_available(), reason="local PostgreSQL/su not available")
def test_batch2_internal_client_rls_guardrails():
    contents = {marker: path.read_text() for marker, path in MARKERS.items()}
    spliced = []
    for line in HARNESS.read_text().splitlines():
        token = line.strip()
        spliced.append(contents[token] if token in contents else line)
    sql = "\n".join(spliced)

    _su_psql(f"-c 'DROP DATABASE IF EXISTS {TEST_DB};' -c 'CREATE DATABASE {TEST_DB};'")
    fd, path = tempfile.mkstemp(suffix=".sql", dir="/tmp")
    os.close(fd)
    pathlib.Path(path).write_text(sql)
    os.chmod(path, 0o644)
    try:
        result = _su_psql(f"-v ON_ERROR_STOP=1 -d {TEST_DB} -f {path}")
        assert result.returncode == 0, (
            "Batch 2 RLS verification failed:\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
        assert "ALL ASSERTIONS PASSED" in result.stdout, result.stdout
    finally:
        os.remove(path)
        _su_psql(f"-c 'DROP DATABASE IF EXISTS {TEST_DB};'")
