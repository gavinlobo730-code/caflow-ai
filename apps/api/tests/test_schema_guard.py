"""
core/schema_guard.py — boot-time schema-drift guard (task #244).

Pure unit tests for the migration-file parser and the drift-diff logic;
no real Postgres needed (that's what get_public_columns()/migration 242
supplies in production — here we fake its return shape directly).
"""
from pathlib import Path

from core.schema_guard import check_schema_drift, expected_columns_from_migrations


def test_parses_single_add_column_if_not_exists(tmp_path):
    (tmp_path / "001_x.sql").write_text(
        "ALTER TABLE public.mca_filings\n"
        "    ADD COLUMN IF NOT EXISTS company_id UUID;\n"
    )
    expected = expected_columns_from_migrations(tmp_path)
    assert expected == {"mca_filings": {"company_id"}}


def test_parses_multiple_comma_separated_add_columns_one_statement(tmp_path):
    (tmp_path / "001_x.sql").write_text(
        "ALTER TABLE public.gstr3b_returns\n"
        "  ADD COLUMN IF NOT EXISTS tax_liability_paise BIGINT NOT NULL DEFAULT 0,\n"
        "  ADD COLUMN IF NOT EXISTS gstin TEXT;\n"
    )
    expected = expected_columns_from_migrations(tmp_path)
    assert expected == {"gstr3b_returns": {"tax_liability_paise", "gstin"}}


def test_merges_columns_for_the_same_table_across_multiple_files(tmp_path):
    (tmp_path / "001_x.sql").write_text(
        "ALTER TABLE public.purchase_bills ADD COLUMN IF NOT EXISTS a TEXT;\n"
    )
    (tmp_path / "002_y.sql").write_text(
        "ALTER TABLE public.purchase_bills ADD COLUMN IF NOT EXISTS b TEXT;\n"
    )
    expected = expected_columns_from_migrations(tmp_path)
    assert expected == {"purchase_bills": {"a", "b"}}


def test_ignores_add_column_without_if_not_exists(tmp_path):
    # Not the pattern this guard covers (see module docstring) — must not
    # false-flag a column added a different way as "missing".
    (tmp_path / "001_x.sql").write_text(
        "ALTER TABLE public.foo ADD COLUMN bar TEXT;\n"
    )
    assert expected_columns_from_migrations(tmp_path) == {}


def test_ignores_helper_files_starting_with_underscore(tmp_path):
    (tmp_path / "_bootstrap.sql").write_text(
        "ALTER TABLE public.foo ADD COLUMN IF NOT EXISTS bar TEXT;\n"
    )
    assert expected_columns_from_migrations(tmp_path) == {}


def test_no_migrations_dir_returns_empty(tmp_path):
    assert expected_columns_from_migrations(tmp_path / "does_not_exist") == {}


class _FakeResp:
    def __init__(self, data):
        self.data = data


class _FakeRpc:
    def __init__(self, payload):
        self._payload = payload

    def execute(self):
        return _FakeResp(self._payload)


class _FakeDb:
    """Speaks get_public_schema_columns() (migration 265): ONE row carrying the
    whole map plus an independently-computed total, so a caller can prove it
    received everything."""

    # Sentinel, not None: `raw=None` is a real case to test (the RPC returned
    # nothing) and must not be confused with "raw wasn't supplied".
    _UNSET = object()

    def __init__(self, tables: dict, total=None, raw=_UNSET):
        self._payload = raw if raw is not _FakeDb._UNSET else {
            "total_columns": total if total is not None else sum(len(c) for c in tables.values()),
            "tables": tables,
        }

    def rpc(self, name, params):
        assert name == "get_public_schema_columns", f"unexpected RPC {name}"
        return _FakeRpc(self._payload)


class _FailingDb:
    def rpc(self, name, params):
        raise ConnectionError("boom")


def test_check_schema_drift_reports_missing_column(monkeypatch):
    monkeypatch.setattr(
        "core.schema_guard.expected_columns_from_migrations",
        lambda *a, **k: {"service_catalogue": {"stock_version"}},
    )
    db = _FakeDb({"service_catalogue": ["name"]})
    result = check_schema_drift(db)
    assert result == {"checked": True, "missing": ["service_catalogue.stock_version"]}


def test_check_schema_drift_clean_when_column_present(monkeypatch):
    monkeypatch.setattr(
        "core.schema_guard.expected_columns_from_migrations",
        lambda *a, **k: {"service_catalogue": {"stock_version"}},
    )
    db = _FakeDb({"service_catalogue": ["stock_version"]})
    result = check_schema_drift(db)
    assert result == {"checked": True, "missing": []}


def test_check_schema_drift_unreachable_rpc_is_not_reported_as_missing(monkeypatch):
    monkeypatch.setattr(
        "core.schema_guard.expected_columns_from_migrations",
        lambda *a, **k: {"service_catalogue": {"stock_version"}},
    )
    result = check_schema_drift(_FailingDb())
    assert result == {"checked": False, "missing": []}


def test_real_migrations_directory_parses_without_error():
    # Smoke test against the actual repo migrations/ dir — must not raise,
    # and the known 233-241 additions must be discoverable.
    expected = expected_columns_from_migrations()
    assert "stock_version" in expected.get("service_catalogue", set())
    assert "company_id" in expected.get("mca_filings", set())
    assert "itc_eligible" in expected.get("purchase_bill_lines", set())
