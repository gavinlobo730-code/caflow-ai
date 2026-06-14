"""
Batch 5 — capture-layer migration (078) verification against local PostgreSQL.
Proves the system-controlled GENERATED is_billed (manual write rejected) and the
unbilled query. Skips when no local PostgreSQL is reachable.
"""
import os
import shutil
import subprocess
import tempfile
import pathlib

import pytest

HERE = pathlib.Path(__file__).resolve().parent
MIGRATIONS = HERE.parent / "migrations"
HARNESS = HERE / "sql" / "batch5_capture_verify.sql"
TEST_DB = "batch5_ci"

MARKERS = {
    "--__FWD_078__": MIGRATIONS / "078_billable_capture.sql",
    "--__RB_078__":  MIGRATIONS / "078_billable_capture_rollback.sql",
}


def _pg_available() -> bool:
    if shutil.which("psql") is None or shutil.which("su") is None:
        return False
    r = subprocess.run(["su", "postgres", "-c", "psql -tAc 'select 1'"], capture_output=True, text=True)
    return r.returncode == 0


def _su_psql(sql_args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["su", "postgres", "-c", f"psql {sql_args}"], capture_output=True, text=True)


@pytest.mark.skipif(not _pg_available(), reason="local PostgreSQL/su not available")
def test_batch5_capture_db_guarantees():
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
        assert result.returncode == 0, f"failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        assert "ALL ASSERTIONS PASSED" in result.stdout, result.stdout
    finally:
        os.remove(path)
        _su_psql(f"-c 'DROP DATABASE IF EXISTS {TEST_DB};'")
