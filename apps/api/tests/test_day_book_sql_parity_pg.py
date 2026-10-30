"""
Migration 517: the SQL Day Book must equal the Python one, exactly (POST-A-091).

WHY THIS FILE IS THE POINT OF THE CHANGE
    The Day Book screen read `journal_entries` with every entry's lines embedded, in the browser, for the whole
    period, and summed a debit column out of them. `public.day_book_page` cuts one page in the database and sums each
    entry's lines there, so the lines never cross the wire, and `builders.day_book` stays as the no-database twin for
    mock mode and local development. Two implementations of one rule are safe only while something proves they agree.
    That is this file, and it is the shape of `test_account_ledger_sql_parity_pg.py`.

WHAT IS COMPARED
    The whole page, key for key: every entry with its id, its debit and credit totals, the window's entry count and totals,
    the documents the entries came from and the order. Both sides are given the same entry ids, so the order of the ids is
    what proves the same entries came back in the same places. The limit the SQL side applied is compared with the Python
    side's clamp.

WHAT A SCENARIO HAS TO DO TO COUNT
    Parity on a scenario nobody has reasoned about proves only that two functions are wrong together, so each one names the
    boundary it is about: a window end that is inclusive, an unposted or deleted entry the database excludes and the
    in-memory source never holds, two entries on one instant ordered by id alone, source names that a locale and a byte
    order sort differently (`Opening` against `manual`), an entry with no lines.

THE PAGING PROOF
    Page one is the same either way, so the pages are reassembled too: every page concatenated must equal the unpaged
    Python book, and the footer (count, totals, sources) must be the window's on every page and never the page's.
"""
from __future__ import annotations

import dataclasses
import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest
from tests._cross_tenant_rows import LEGACY_ROWS_ALLOWED

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="SQL/Python parity proof requires HARNESS_PG + psql",
)

from domain.reporting import (  # noqa: E402
    Account, InMemoryLedgerSource, JournalEntry, JournalLine, ReportingService,
)

FIRM = "f9000000-0000-0000-0000-000000000001"
OTHER_FIRM = "f9000000-0000-0000-0000-000000000002"
CLIENT = "c9000000-0000-0000-0000-000000000001"
OTHER_CLIENT = "c9000000-0000-0000-0000-000000000002"
START, END = "2026-04-01", "2027-03-31"

ACCOUNTS = [
    Account("bank", "1000", "Bank", "Asset", "Bank", system_key="bank"),
    Account("ar", "1100", "Trade Receivables", "Asset", "Receivable", system_key="ar"),
    Account("rev", "4000", "Sales Revenue", "Revenue", "Sales"),
]
AID = {a.id: str(uuid.uuid5(uuid.NAMESPACE_DNS, f"daybook.{a.id}")) for a in ACCOUNTS}
#: A journal line's account must belong to the entry's own firm (migration 360), so the other firm has its own chart.
AID_OTHER = {a.id: str(uuid.uuid5(uuid.NAMESPACE_DNS, f"daybook.other.{a.id}")) for a in ACCOUNTS}
_SRC = str(uuid.uuid5(uuid.NAMESPACE_DNS, "daybook.doc"))

AUTO = "AUTO"


def je(jid, date="2026-06-01", amount=1000, *, lines=None, source_type=None, source_id=None,
       reference_no=AUTO, narration=AUTO, created_at=None, client=CLIENT, firm=FIRM):
    built = lines if lines is not None else [("ar", amount, 0), ("rev", 0, amount)]
    return JournalEntry(
        id=jid, entry_date=date, client_id=client, firm_id=firm, entry_type="Journal",
        lines=tuple(JournalLine(*ln) for ln in built), reference_no=reference_no, narration=narration,
        created_at=created_at, source_type=source_type, source_id=source_id)


#: Entries the DATABASE holds and excludes, and the in-memory source never holds: it is built from
#: `is_posted` and `deleted_at` already, so the Python side is fed the rest.
UNPOSTED = {"draft-1"}
DELETED = {"gone-1"}


def _uuid_of(name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"daybook.entry.{name}"))


def _uuid(e) -> str:
    return _uuid_of(e.id)


_UNPOSTED_IDS = {_uuid_of(k) for k in UNPOSTED}
_DELETED_IDS = {_uuid_of(k) for k in DELETED}


def _stamp(entries: list) -> list:
    """The identity and the metadata the seed writes, identical on both sides. `created_at` is the book's
    second sort key, so it is distinct per entry unless a scenario pins it."""
    out = []
    for i, e in enumerate(entries):
        out.append(dataclasses.replace(
            e, id=_uuid(e),
            reference_no=f"REF-{i}" if e.reference_no == AUTO else e.reference_no,
            narration=f"narr {i}" if e.narration == AUTO else e.narration,
            created_at=e.created_at or f"2026-01-01T00:{i // 60:02d}:{i % 60:02d}+00:00"))
    return out


def _at(entry, hms: str):
    return dataclasses.replace(entry, created_at=f"2026-01-01T{hms}+00:00")


SCENARIOS: list[tuple[str, list]] = [
    ("empty book", []),
    ("one entry", [je("a")]),
    ("an entry of several lines sums its debits and its credits", [
        je("multi", lines=[("ar", 700, 0), ("bank", 300, 0), ("rev", 0, 400), ("rev", 0, 600)])]),
    ("both ends of the window are inclusive", [
        je("first", START), je("last", END)]),
    ("an entry before the window and one after are excluded", [
        je("before", "2026-03-31"), je("inside", "2026-06-01"), je("after", "2027-04-01")]),
    ("a draft and a deleted entry are not in the book", [
        je("ok-1", "2026-06-01"), je("draft-1", "2026-06-02"), je("gone-1", "2026-06-03"),
        je("ok-2", "2026-06-04")]),
    ("another client's entry and another firm's are not in the book", [
        je("mine", "2026-06-01"),
        je("theirs", "2026-06-02", client=OTHER_CLIENT),
        je("another-firm", "2026-06-03", firm=OTHER_FIRM)]),
    ("same-day entries, created_at AGAINST insertion order", [
        _at(je("s1", "2026-06-01", 100), "00:00:30"),
        _at(je("s2", "2026-06-01", 200), "00:00:20"),
        _at(je("s3", "2026-06-01", 300), "00:00:10")]),
    ("same-day entries with the SAME created_at: the id tiebreak alone", [
        _at(je("tie-a", "2026-06-01", 100), "00:00:05"),
        _at(je("tie-b", "2026-06-01", 200), "00:00:05"),
        _at(je("tie-c", "2026-06-01", 300), "00:00:05")]),
    ("a backdated entry lands in date order, not insertion order", [
        je("b1", "2026-09-01"), je("b2", "2026-05-01")]),
    ("an entry with no lines is listed with nothing in either column", [
        je("empty-lines", lines=[])]),
    ("a missing reference comes back null and an empty narration stays empty", [
        # `journal_entries.narration` is NOT NULL, so the narration can only be empty; the reference can be absent.
        je("nulls", reference_no=None, narration="")]),
    ("the documents behind the entries, in a byte order a locale would not give", [
        # `Opening` and `TrialBalance` begin with capitals, which sort BEFORE `manual` as bytes and AFTER it in an
        # English locale; `sales_credit_note` and `sales_invoice` differ only after an underscore a locale ignores.
        je("m1", "2026-05-01", source_type="manual"),
        je("o1", "2026-05-02", source_type="Opening"),
        je("t1", "2026-05-03", source_type="TrialBalance"),
        je("i1", "2026-05-04", source_type="sales_invoice", source_id=_SRC),
        je("c1", "2026-05-05", source_type="sales_credit_note", source_id=_SRC),
        je("i2", "2026-05-06", source_type="sales_invoice", source_id=_SRC),
        je("n1", "2026-05-07")]),
    ("a long book, more entries than one page", [
        je(f"m{i}", f"2026-{(i % 9) + 4:02d}-{(i % 27) + 1:02d}", 1000 + i,
           source_type=("manual" if i % 3 == 0 else "sales_invoice" if i % 3 == 1 else None))
        for i in range(45)]),
]


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


def _q(v) -> str:
    return "NULL" if v is None else "'" + str(v).replace("'", "''") + "'"


def _seed_sql(entries: list) -> str:
    out = [f"""
INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'DayBook', 'd@daybook.in'), ('{OTHER_FIRM}', 'Other', 'o@daybook.in');
INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
  ('{CLIENT}', '{FIRM}', 'Book Co', 'Proprietorship'),
  ('{OTHER_CLIENT}', '{FIRM}', 'Other Co', 'Proprietorship');
"""]
    for firm, ids in ((FIRM, AID), (OTHER_FIRM, AID_OTHER)):
        for a in ACCOUNTS:
            out.append(
                "INSERT INTO chart_of_accounts (id, firm_id, client_id, account_code, account_name, account_type, "
                " account_subtype, system_account_key) VALUES ("
                f"'{ids[a.id]}', '{firm}', NULL, {_q(a.code)}, {_q(a.name)}, {_q(a.type)}, {_q(a.subtype)}, {_q(a.system_key)});")
    for e in entries:
        posted = "false" if e.id in _UNPOSTED_IDS else "true"
        deleted = "now()" if e.id in _DELETED_IDS else "NULL"
        out.append(
            "INSERT INTO journal_entries (id, firm_id, client_id, entry_date, reference_no, narration, entry_type, "
            " is_posted, status, created_at, source_type, source_id, deleted_at) VALUES ("
            f"'{e.id}', '{e.firm_id}', '{e.client_id}', '{e.entry_date}', {_q(e.reference_no)}, {_q(e.narration)}, "
            f"'{e.entry_type}', {posted}, 'posted', TIMESTAMPTZ '{e.created_at}', "
            f"{_q(e.source_type)}, {_q(e.source_id)}::uuid, {deleted});")
        ids = AID_OTHER if e.firm_id == OTHER_FIRM else AID
        for ln in e.lines:
            out.append(
                "INSERT INTO journal_lines (journal_entry_id, account_id, debit_paise, credit_paise) VALUES ("
                f"'{e.id}', '{ids[ln.account_id]}', {ln.debit_paise}, {ln.credit_paise});")
    return "\n".join(out)


def _the_source_holds(entries: list) -> list:
    """What `ReportingService` is handed in memory: the source filters `is_posted` and `deleted_at` before
    anything is built, so those two kinds of entry are not given to it."""
    return [e for e in entries if e.id not in _UNPOSTED_IDS | _DELETED_IDS]


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"daybk_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not clone the migrated template")
    dsn = f"{admin} dbname={name}"
    try:
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _sql_book(dsn: str, *, start=START, end=END, newest_first=False, limit=1000, offset=0) -> dict:
    s = "NULL" if start is None else f"'{start}'::date"
    e = "NULL" if end is None else f"'{end}'::date"
    r = _psql(dsn, f"SELECT public.day_book_page('{FIRM}'::uuid, '{CLIENT}'::uuid, {s}, {e}, "
                   f"{'true' if newest_first else 'false'}, {limit}, {offset});", tuples=True)
    assert r.returncode == 0, f"day_book_page failed: {r.stderr}"
    return json.loads(r.stdout.strip())


def _python_book(entries: list, *, start=START, end=END, newest_first=False, limit=1000, offset=0) -> dict:
    svc = ReportingService(InMemoryLedgerSource(accounts=ACCOUNTS, entries=_the_source_holds(entries)))
    return svc.day_book(FIRM, CLIENT, start, end, newest_first=newest_first, limit=limit, offset=offset)


def _comparable(book: dict) -> dict:
    """The book as plain JSON. Both sides are given the SAME entry ids (a uuid5 of the scenario's short name), so the
    ids are compared too: it is the order of the ids that proves the same entries came back in the same places."""
    return json.loads(json.dumps(book))


# ── the parity proof ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("name,entries", SCENARIOS, ids=[s[0] for s in SCENARIOS])
def test_sql_matches_python(db, name, entries):
    stamped = _stamp(entries)
    # Plants a row migration 565 refuses (a row naming another firm's client): LEGACY_ROWS_ALLOWED switches its six triggers off in this throwaway database; see tests/_cross_tenant_rows.py.
    seed = _psql(db, LEGACY_ROWS_ALLOWED + _seed_sql(stamped))
    assert seed.returncode == 0, f"seed failed: {seed.stderr}"
    for newest_first in (False, True):
        sql = _sql_book(db, newest_first=newest_first)
        py = _python_book(stamped, newest_first=newest_first)
        assert _comparable(sql) == _comparable(py), (
            f"SQL and Python disagree on '{name}' (newest_first={newest_first}).\n"
            f"  SQL:    {json.dumps(_comparable(sql), indent=2, sort_keys=True)}\n"
            f"  Python: {json.dumps(_comparable(py), indent=2, sort_keys=True)}")


def test_the_comparison_can_actually_fail(db):
    """Vacuity guard: two unrelated scenarios must not produce the same book."""
    assert _psql(db, _seed_sql(_stamp(SCENARIOS[2][1]))).returncode == 0
    assert _comparable(_sql_book(db)) != _comparable(_python_book(_stamp(SCENARIOS[1][1])))


def _scenario(name: str) -> list:
    for n, entries in SCENARIOS:
        if n == name:
            return _stamp(entries)
    raise AssertionError(f"no scenario named {name!r}")


# ── what the book holds and what it does not ─────────────────────────────────

def test_a_draft_and_a_deleted_entry_are_not_in_the_database_book(db):
    stamped = _scenario("a draft and a deleted entry are not in the book")
    assert _psql(db, _seed_sql(stamped)).returncode == 0
    book = _sql_book(db)
    assert book["total_entries"] == 2
    assert [e["reference_no"] for e in book["entries"]] == ["REF-0", "REF-3"]


def test_the_totals_are_the_windows_and_each_entry_carries_its_own(db):
    stamped = _scenario("an entry of several lines sums its debits and its credits")
    assert _psql(db, _seed_sql(stamped)).returncode == 0
    book = _sql_book(db)
    only = book["entries"][0]
    assert (only["debit_paise"], only["credit_paise"]) == (1000, 1000)
    assert book["total_debit_paise"] == book["total_credit_paise"] == 1000


def test_the_sources_are_counted_over_the_window_in_byte_order_with_none_last(db):
    stamped = _scenario("the documents behind the entries, in a byte order a locale would not give")
    assert _psql(db, _seed_sql(stamped)).returncode == 0
    sources = _sql_book(db)["sources"]
    assert [s["source_type"] for s in sources] == [
        "Opening", "TrialBalance", "manual", "sales_credit_note", "sales_invoice", None]
    assert {s["source_type"]: s["entries"] for s in sources}["sales_invoice"] == 2


def test_an_entry_with_no_source_keeps_both_keys(db):
    stamped = _scenario("the documents behind the entries, in a byte order a locale would not give")
    assert _psql(db, _seed_sql(stamped)).returncode == 0
    for doc in (_sql_book(db), _python_book(stamped)):
        for e in doc["entries"]:
            assert "source_type" in e and "source_id" in e
        assert doc["entries"][-1]["source_type"] is None and doc["entries"][-1]["source_id"] is None


# ── the order does not depend on the session's time zone ─────────────────────

def _sql_book_in_zone(dsn: str, zone: str) -> dict:
    r = _psql(dsn, f"SET timezone = '{zone}'; SELECT public.day_book_page('{FIRM}'::uuid, '{CLIENT}'::uuid, "
                   f"'{START}'::date, '{END}'::date, false, 1000, 0);", tuples=True)
    assert r.returncode == 0, f"day_book_page failed in {zone}: {r.stderr}"
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_the_order_of_two_same_day_entries_does_not_depend_on_the_sessions_time_zone(db):
    """`timestamptz::text` is written in the SESSION's zone. In New York on 2026-11-01 the clock repeats 01:00-02:00, so the
    later of two instants (06:10Z = 01:10 EST) writes a SMALLER text than the earlier one (05:30Z = 01:30 EDT). The ordering
    renders the instant in UTC first, so the chronological order holds in every zone."""
    entries = [
        dataclasses.replace(je("late", "2026-06-01"), created_at="2026-11-01T06:10:00+00:00"),
        dataclasses.replace(je("early", "2026-06-01"), created_at="2026-11-01T05:30:00+00:00"),
    ]
    stamped = _stamp(entries)
    assert _psql(db, _seed_sql(stamped)).returncode == 0
    trap = _psql(db, "SET timezone = 'America/New_York'; SELECT (TIMESTAMPTZ '2026-11-01 05:30:00+00')::text "
                     "> (TIMESTAMPTZ '2026-11-01 06:10:00+00')::text;", tuples=True)
    assert trap.returncode == 0 and trap.stdout.strip().splitlines()[-1] == "t", (
        "the scenario no longer shows the trap it exists for: the earlier instant should write the LARGER text in New York")
    wanted = [_uuid_of("early"), _uuid_of("late")]
    for zone in ("UTC", "America/New_York", "Asia/Kolkata"):
        assert [e["entry_id"] for e in _sql_book_in_zone(db, zone)["entries"]] == wanted, zone
    assert [e["entry_id"] for e in _python_book(stamped)["entries"]] == wanted


# ── the paging proof ─────────────────────────────────────────────────────────

def _long() -> list:
    return _scenario("a long book, more entries than one page")


@pytest.mark.parametrize("newest_first", [False, True])
def test_the_pages_reassemble_into_the_unpaged_book(db, newest_first):
    stamped = _long()
    assert _psql(db, _seed_sql(stamped)).returncode == 0
    whole = _python_book(stamped, newest_first=newest_first)
    assert len(whole["entries"]) > 25, "the fixture must exceed one page to prove anything"
    got: list[dict] = []
    for offset in range(0, len(whole["entries"]) + 10, 10):
        page = _sql_book(db, newest_first=newest_first, limit=10, offset=offset)
        got += page["entries"]
        if not page["entries"]:
            break
    assert [e["entry_id"] for e in got] == [e["entry_id"] for e in whole["entries"]]


def test_the_footer_describes_the_window_not_the_page(db):
    stamped = _long()
    assert _psql(db, _seed_sql(stamped)).returncode == 0
    first = _sql_book(db, limit=10, offset=0)
    third = _sql_book(db, limit=10, offset=20)
    for key in ("total_entries", "total_debit_paise", "total_credit_paise", "sources"):
        assert first[key] == third[key], f"{key} changed between pages"
    assert len(first["entries"]) == 10 and len(third["entries"]) == 10
    assert first["total_entries"] == len(stamped)


def test_an_offset_past_the_end_is_empty_but_keeps_its_footer(db):
    stamped = _long()
    assert _psql(db, _seed_sql(stamped)).returncode == 0
    page = _sql_book(db, limit=10, offset=9999)
    assert page["entries"] == [] and page["total_entries"] == len(stamped)


def test_the_limit_and_the_offset_are_clamped_rather_than_trusted(db):
    assert _psql(db, _seed_sql(_long())).returncode == 0
    assert _sql_book(db, limit=0)["limit"] == 1
    assert _sql_book(db, limit=99999)["limit"] == 1000
    assert _sql_book(db, limit=10, offset=-5)["offset"] == 0
    py = _python_book(_long(), limit=99999)
    assert py["limit"] == 1000


def test_an_open_ended_window_reads_everything_there_is(db):
    """The FUNCTION and the builder take a missing bound as no bound. (`ReportingService.day_book` is the layer that
    turns a missing bound into the financial year and today, as the ledger does, so it is not asked here.)"""
    from domain.reporting import builders
    stamped = _the_source_holds(_scenario("an entry before the window and one after are excluded"))
    assert _psql(db, _seed_sql(stamped)).returncode == 0
    sql = _sql_book(db, start=None, end=None)
    py = builders.day_book({e.id: e for e in stamped}, None, None, limit=1000)
    assert _comparable(sql) == _comparable(py)
    assert sql["total_entries"] == 3


def test_the_service_turns_a_missing_bound_into_the_financial_year_and_today(db):
    from core.ist_clock import ist_today
    stamped = _scenario("an entry before the window and one after are excluded")
    svc = ReportingService(InMemoryLedgerSource(accounts=ACCOUNTS, entries=stamped))
    book = svc.day_book(FIRM, CLIENT, None, None, limit=1000)
    assert book["end_date"] == ist_today().isoformat()
    assert book["start_date"] and book["start_date"] <= book["end_date"]


def test_the_function_is_not_open_to_the_public_and_runs_as_its_caller(db):
    r = _psql(db, "SELECT prosecdef, has_function_privilege('anon', "
                  "'public.day_book_page(uuid,uuid,date,date,boolean,integer,integer)', 'EXECUTE'), "
                  "has_function_privilege('authenticated', "
                  "'public.day_book_page(uuid,uuid,date,date,boolean,integer,integer)', 'EXECUTE'), "
                  "has_function_privilege('service_role', "
                  "'public.day_book_page(uuid,uuid,date,date,boolean,integer,integer)', 'EXECUTE') "
                  "FROM pg_proc WHERE proname = 'day_book_page';", tuples=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "f|f|t|t", (
        "SECURITY INVOKER (so row security covers the tables it reads), no anon, signed-in and service roles may run it")
