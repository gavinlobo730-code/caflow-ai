"""
A partial schema read must never be reported as drift.

THE INCIDENT
    get_public_columns() (migration 242) returned one row per column. This
    database has 3531 columns in the public schema; PostgREST caps a response at
    1000 rows. So the guard asked for the schema, got the first 1000 rows, and
    diffed against them as though they were the whole thing.

    Measured on the live database, in the order that function returns rows:

        bank_reconciliations.reopen_count      row  218   -> "present"
        form_26as_uploads.parse_errors         row  922   -> "present"
        clients.firm_id                        row 1277   -> "MISSING"
        bank_reconciliations.reopen_reason     row 2791   -> "MISSING"
        form_26as_uploads.parse_status         row 3073   -> "MISSING"

    401 columns were reported missing. All 401 exist. clients.firm_id is among
    them, and every tenant-isolation policy in the database is built on it. The
    cut lands MID-TABLE — two columns of form_26as_uploads on opposite sides of
    it — which is the signature of a row limit, not of an unapplied migration.

    /health therefore returned 503 on every boot from the day the guard shipped.
    A permanently-red check cannot be acted on: real drift would have been
    indistinguishable from the standing noise, and a deploy gate wired to it
    could never have passed.

WHAT ACTUALLY WENT WRONG
    Not the truncation. The code already had a `checked: False` path for "I
    could not read the schema" and did not use it, because a truncated read is
    indistinguishable from a complete one unless you check. It stated a
    confident conclusion from partial data.

    So the fix is two-part, and both halves are tested here:
      * migration 265 returns ONE row, which a row limit cannot cut, and
      * the payload carries total_columns computed independently of the map, so
        completeness is PROVEN on every read rather than assumed.
"""
from __future__ import annotations

import pytest

from core.schema_guard import check_schema_drift, live_columns
from tests.test_schema_guard import _FakeDb

EXPECTED = {"clients": {"firm_id", "phone"}, "users": {"is_active"}}


@pytest.fixture(autouse=True)
def _expected(monkeypatch):
    monkeypatch.setattr(
        "core.schema_guard.expected_columns_from_migrations", lambda *a, **k: dict(EXPECTED))


def _full():
    return {"clients": ["firm_id", "phone"], "users": ["is_active"], "other": ["id"]}


def test_a_complete_read_reports_no_drift():
    """Control. Everything below asserts a partial read is refused; this proves
    a whole one is still diffed normally, so the refusal is not just 'always
    give up'."""
    assert check_schema_drift(_FakeDb(_full())) == {"checked": True, "missing": []}


def test_a_truncated_read_is_refused_rather_than_called_drift():
    """The incident, in one assertion. The map is short of what the database
    says it holds — exactly what a row cap produces — so the answer is 'not
    checked', NOT a list of columns that exist."""
    truncated = {"clients": ["firm_id"]}          # 'phone' and all of users lost
    db = _FakeDb(truncated, total=4)              # database says there are 4

    result = check_schema_drift(db)

    assert result == {"checked": False, "missing": []}, (
        "a partial read was reported as drift — this is the 401-false-positives bug")


def test_the_mid_table_cut_is_caught():
    """The specific shape that made the bug hard to see: a table present in the
    payload but missing some of its columns. A table-level check would pass this
    and still report clients.phone as drift."""
    db = _FakeDb({"clients": ["firm_id"], "users": ["is_active"], "other": ["id"]}, total=4)

    assert check_schema_drift(db)["checked"] is False


def test_a_count_that_exceeds_the_map_is_also_refused():
    """Symmetry: any disagreement between the two independently-computed numbers
    means the read is untrustworthy, in either direction."""
    assert live_columns(_FakeDb(_full(), total=99)) is None


@pytest.mark.parametrize("raw", [
    None,                                   # nothing came back
    [],                                     # empty list
    [{"tables": {}}, {"tables": {}}],       # more than one row: not a scalar return
    "a string",                             # not JSON at all
    {"tables": {"clients": ["firm_id"]}},   # no total to verify against
    {"total_columns": 4},                   # no map
    {"total_columns": "four", "tables": {}},
    {"total_columns": 1, "tables": {"clients": "firm_id"}},   # columns not a list
])
def test_any_unusable_payload_is_refused(raw):
    """Every malformed shape must land on 'not checked'. A guard that guesses at
    a payload it does not recognise is how this failed the first time."""
    assert live_columns(_FakeDb({}, raw=raw)) is None


def test_a_single_element_list_wrapper_is_accepted():
    """Some PostgREST client versions wrap a scalar return in a one-element
    list. That is a real complete response, not a malformed one, and refusing it
    would disable the guard on those versions."""
    payload = {"total_columns": 4, "tables": _full()}
    assert live_columns(_FakeDb({}, raw=[payload])) is not None


def test_genuine_drift_still_fails_health():
    """The point of all this. Completeness checking must not become a way to
    never report anything: a full read that is genuinely short a column still
    reports it."""
    full_minus_one = {"clients": ["firm_id"], "users": ["is_active"], "other": ["id"]}
    db = _FakeDb(full_minus_one)   # total computed from the map -> read IS complete

    assert check_schema_drift(db) == {"checked": True, "missing": ["clients.phone"]}


def test_the_old_row_per_column_rpc_is_no_longer_called():
    """Names the regression directly. Calling get_public_columns() again would
    reintroduce the 1000-row cap; _FakeDb asserts on the RPC name, so this fails
    loudly if the call site reverts."""
    class _OldOnlyDb:
        def rpc(self, name, params):
            assert name != "get_public_columns", "reverted to the truncatable RPC"
            raise ConnectionError("only the new function exists here")

    assert check_schema_drift(_OldOnlyDb()) == {"checked": False, "missing": []}
