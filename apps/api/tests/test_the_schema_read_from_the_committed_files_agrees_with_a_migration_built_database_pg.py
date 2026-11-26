"""
The schema read from the committed files agrees with a migration-built database, in the direction each mock guard needs (POST-A-038).

WHY THIS EXISTS
    `tests/test_frontend_schema_guards_read_the_committed_files.py` asks the three frontend schema questions of
    `tests/_schema_from_files.py` (the production snapshot and the migrations read as text) so that a frontend-only pull request,
    which runs no Postgres, is still checked. A reader of SQL text can misread a migration, and then the mock guard either fails a
    screen the real guard passes (noise, the thing that gets a guard deleted) or passes one it fails (a hole). This holds the
    reading to the database the real guards read, in the real-Postgres job, with the real guards' own fixtures and query, so a
    migration whose shape the reader does not know fails HERE, on the pull request that adds it.

WHAT IS HELD, AND IN WHICH DIRECTION
    * Every column the real guard sees is known to the reading (the reading may know more: the snapshot holds production, and a
      view is read as every word of its definition). So the mock column guard cannot fail where the real one passes.
    * The tables with a CHECK on `status` are the SAME set, and each real value is allowed by the reading (the reading may allow
      more: it unites every CHECK a table's `status` has had). So the mock status guard measures the same files, never reports a
      value the real guard allows, and never measures a file the real guard calls blind.
    * The keys to users are the same set both ways round, so the mock auth-id guard answers exactly as the real one does.
"""
from __future__ import annotations

from tests import _schema_from_files as files
from tests.test_frontend_columns_exist_pg import _NEEDS_PG, schema  # noqa: F401  (`schema` is the real guard's fixture)
from tests.test_frontend_never_writes_an_auth_id_into_a_users_fk_pg import _users_fk_columns
from tests.test_frontend_status_values_match_the_check_pg import allowed_status  # noqa: F401  (the real guard's fixture)

_TEACH = "teach tests/_schema_from_files.py the statement shape that declares it"


@_NEEDS_PG
def test_every_column_the_real_guard_reads_is_known_to_the_files(schema):  # noqa: F811
    assert len(schema) >= 5000, "the migration-built database has almost no columns — the template did not build"
    missing = sorted(schema - files.known_columns())
    assert not missing, (
        "these columns are in the migration-built database and neither in the production snapshot nor in the reading of the "
        f"migrations, so the mock column guard would refuse a screen the real guard accepts; {_TEACH}:\n  " + "\n  ".join(missing))


@_NEEDS_PG
def test_the_status_checks_are_on_the_same_tables_and_the_files_allow_every_real_value(allowed_status):  # noqa: F811
    read = files.status_values()
    assert set(read) == set(allowed_status), (
        "the tables with a CHECK on `status` differ between the database and the reading of the migrations; "
        f"{_TEACH}.\n  only in the database: {sorted(set(allowed_status) - set(read))}"
        f"\n  only in the reading:  {sorted(set(read) - set(allowed_status))}")
    narrower = {t: sorted(v - read[t]) for t, v in allowed_status.items() if v - read[t]}
    assert not narrower, (
        f"the reading of the migrations misses these values a CHECK allows, so the mock status guard would report a value the "
        f"real one accepts; {_TEACH}: {narrower}")


@_NEEDS_PG
def test_the_keys_to_users_are_the_same_set_both_ways_round(pg_template):
    real = {(t, c) for t, cols in _users_fk_columns(pg_template.name).items() for c in cols}
    read = {(t, c) for t, cols in files.users_keys().items() for c in cols}
    assert len(real) >= 100, "the migration-built database has almost no keys to users — the template did not build"
    assert read == real, (
        f"the keys to users differ between the database and the reading of the migrations; {_TEACH}."
        f"\n  only in the database: {sorted(real - read)}\n  only in the reading:  {sorted(read - real)}")
