"""
Batch 3 (Amendment v1.1) — billing DB-guarantee verification.

Splices the REAL migrations (073 + 074 + 075 forward, then 075 rollback) into
tests/sql/batch3_billing_verify.sql and runs it against a local PostgreSQL.
Proves duplicate-invoice safety (unique index), G3 single-link uniqueness,
restrictive G1 RLS on client_sales_invoices, the collections lifecycle at the
data layer, and a clean 075 rollback. Skips when no local PostgreSQL is reachable.
"""
import os
import shutil
import subprocess
import tempfile
import pathlib

import pytest

HERE = pathlib.Path(__file__).resolve().parent
MIGRATIONS = HERE.parent / "migrations"
HARNESS = HERE / "sql" / "batch3_billing_verify.sql"
TEST_DB = "batch3_ci"

MARKERS = {
    "--__FWD_073__": MIGRATIONS / "073_revenue_ops_foundation.sql",
    "--__FWD_074__": MIGRATIONS / "074_internal_client_rls_guardrails.sql",
    "--__FWD_075__": MIGRATIONS / "075_billing_traceability.sql",
    "--__RB_075__":  MIGRATIONS / "075_billing_traceability_rollback.sql",
}


def _pg_available() -> bool:
    if shutil.which("psql") is None or shutil.which("su") is None:
        return False
    r = subprocess.run(["su", "postgres", "-c", "psql -tAc 'select 1'"], capture_output=True, text=True)
    return r.returncode == 0


def _su_psql(sql_args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["su", "postgres", "-c", f"psql {sql_args}"], capture_output=True, text=True)


@pytest.mark.skipif(not _pg_available(), reason="local PostgreSQL/su not available")
def test_batch3_billing_db_guarantees():
    contents = {m: p.read_text() for m, p in MARKERS.items()}
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
            "Batch 3 billing verification failed:\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
        assert "ALL ASSERTIONS PASSED" in result.stdout, result.stdout
    finally:
        os.remove(path)
        _su_psql(f"-c 'DROP DATABASE IF EXISTS {TEST_DB};'")
