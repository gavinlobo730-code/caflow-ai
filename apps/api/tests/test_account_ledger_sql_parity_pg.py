"""
Migration 283 — the SQL account ledger must equal the Python one, exactly.

WHY THIS FILE IS THE POINT OF THE CHANGE
    The drill-down fetched every posted entry touching the account. Measured on
    the live database for one client's Trade Receivables: 5,659 rows, and 44 ms
    of Postgres. The database was never the cost — moving those rows to
    Singapore, walking them in Python, and rendering them all was.

    Paging fixes that, and paging is exactly what makes a ledger hard: row 101's
    running balance depends on rows 1..100, so a page cannot compute its own.
    public.account_ledger_page runs the window over the account's whole history
    and slices afterwards. builders.ledger stays as the no-database fallback for
    mock mode and local dev — and now there are two implementations of one rule,
    which CLAUDE.md is right to warn about.

    They are safe only while something proves they agree. That is this file.

WHAT IS COMPARED
    The whole document, byte for byte: opening, closing, both totals, every line
    with its running balance and is_debit flag, and the foreign-currency memo
    fields. The single exception is exchange_rate, compared by value — see
    _comparable_line for why, and why the SQL side is the more faithful one.
    The SQL side additionally reports total_lines/limit/offset, which builders
    has no notion of — those are compared against the Python line count rather
    than ignored.

THE PAGING PROOF
    Parity on page 1 would pass even if paging were broken, because page 1 is
    the same either way. So the pages are also reassembled: every page
    concatenated must equal the unpaged Python ledger, line for line, running
    balance for running balance. That is what catches a window computed per
    page instead of per history.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="SQL/Python parity proof requires HARNESS_PG + psql",
)

from domain.reporting import (  # noqa: E402
    Account, JournalEntry, JournalLine, InMemoryLedgerSource, ReportingService,
)

FIRM = "f8000000-0000-0000-0000-000000000001"
CLIENT = "c8000000-0000-0000-0000-000000000001"
START, END = "2026-04-01", "2027-03-31"
PRE = "2026-03-02"          # before the window → opening balance only
POST = "2027-06-01"         # after the window → excluded from both

ACCOUNTS = [
    Account("bank", "1000", "Bank — HDFC",       "Asset",     "Bank",       system_key="bank"),
    Account("ar",   "1100", "Trade Receivables", "Asset",     "Receivable", system_key="ar"),
    Account("ap",   "2150", "Trade Payables",    "Liability", "Payable",    system_key="ap"),
    Account("rev",  "4000", "Sales Revenue",     "Revenue",   "Sales"),
    Account("exp",  "5000", "Office Rent",       "Expense",   "Operating Expense"),
    Account("cap",  "3000", "Partner Capital",   "Equity",    "Capital"),
]
AID = {a.id: str(uuid.uuid5(uuid.NAMESPACE_DNS, f"ledparity.{a.id}")) for a in ACCOUNTS}


def je(jid, lines, date="2026-06-01"):
    """`lines` entries are (account, debit, credit) or (account, debit, credit,
    currency, txn_debit, txn_credit, rate) for a foreign leg.

    reference_no / narration / created_at are filled in by _with_metadata once
    the scenario's order is known, because created_at is the ledger's tiebreak
    for same-day entries and has to match what the seed writes byte for byte —
    otherwise the two sides sort differently and the comparison is between two
    fixtures rather than two implementations."""
    built = []
    for l in lines:
        if len(l) == 3:
            built.append(JournalLine(l[0], l[1], l[2]))
        else:
            built.append(JournalLine(l[0], l[1], l[2], txn_currency=l[3],
                                     txn_debit=l[4], txn_credit=l[5], exchange_rate=l[6]))
    return JournalEntry(id=jid, entry_date=date, client_id=CLIENT, firm_id=FIRM,
                        entry_type="Journal", lines=tuple(built))


def _entry_uuid(e) -> str:
    """The entry's id, IDENTICAL on both sides.

    It has to be. `id` is the ledger's last tiebreak, and the Python side used
    to carry the scenario's short name ('t1') while Postgres carried a UUID —
    two different sort orders, so removing `id` from the SQL ORDER BY changed
    nothing this file could see. Verified: it passed with the tiebreak deleted
    until both sides were given the same id."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"ledparity.entry.{e.id}"))


def _at(entry, hms: str):
    """Pin an entry's created_at, so a scenario can make it disagree with
    insertion order."""
    import dataclasses
    return dataclasses.replace(entry, created_at=f"2026-01-01T{hms}+00:00")


def _created_at(i: int) -> str:
    """The i-th entry's created_at, identical on both sides. Distinct per entry
    so the same-day tiebreak is actually exercised; left to now() every row in a
    batch could share a timestamp and that scenario would prove nothing."""
    return f"2026-01-01T00:{i // 60:02d}:{i % 60:02d}+00:00"


def _with_metadata(entries: list) -> list:
    """Stamp the display/ordering metadata the seed writes onto the in-memory
    entries. The SQL side reads these columns; without this the Python side
    reports None for both and the comparison passes over them.

    An entry that already carries created_at keeps it. That matters: derived
    from the index it always AGREES with insertion order, so Postgres returning
    rows physically would look correct and an ORDER BY missing its tiebreak
    would pass. Verified — deleting the tiebreak left this file green until a
    scenario pinned created_at against insertion order."""
    import dataclasses
    return [dataclasses.replace(e, id=_entry_uuid(e),
                                reference_no=f"REF-{i}", narration=f"narr {i}",
                                created_at=e.created_at or _created_at(i))
            for i, e in enumerate(entries)]


# ── Scenarios ────────────────────────────────────────────────────────────────
# Each names the boundary it is about. Parity on a scenario nobody has reasoned
# about proves only that two functions are wrong together.

SCENARIOS: list[tuple[str, list]] = [
    ("empty ledger", []),
    ("one debit", [je("a", [("ar", 10000, 0), ("rev", 0, 10000)])]),
    ("one credit — balance goes negative", [
        je("b", [("bank", 10000, 0), ("ar", 0, 10000)]),
    ]),
    ("debit then credit — running balance walks back to zero", [
        je("c1", [("ar", 10000, 0), ("rev", 0, 10000)], "2026-06-01"),
        je("c2", [("bank", 10000, 0), ("ar", 0, 10000)], "2026-07-01"),
    ]),
    ("opening balance carried in from before the window", [
        je("o1", [("ar", 50000, 0), ("rev", 0, 50000)], PRE),
        je("o2", [("ar", 10000, 0), ("rev", 0, 10000)], "2026-06-01"),
    ]),
    ("an entry AFTER the window is excluded from lines AND from opening", [
        je("p1", [("ar", 10000, 0), ("rev", 0, 10000)], "2026-06-01"),
        je("p2", [("ar", 99999, 0), ("rev", 0, 99999)], POST),
    ]),
    ("same-day entries — created_at ordering, AGAINST insertion order", [
        # Three entries on one date whose created_at DESCENDS as they are
        # inserted. Ordering by entry_date alone would hand back insertion
        # order — which is 100, 200, 300 — where the ledger's own order is
        # 300, 200, 100. Without the disagreement the scan's physical order
        # happens to be right and the test proves nothing.
        _at(je("s1", [("ar", 100, 0), ("rev", 0, 100)], "2026-06-01"), "00:00:30"),
        _at(je("s2", [("ar", 200, 0), ("rev", 0, 200)], "2026-06-01"), "00:00:20"),
        _at(je("s3", [("ar", 300, 0), ("rev", 0, 300)], "2026-06-01"), "00:00:10"),
    ]),
    ("same-day entries with the SAME created_at — the id tiebreak alone", [
        # created_at cannot separate these, so only the id can — and the names
        # are chosen so their uuid5 order is NOT insertion order (1ba7…, 6565…,
        # 1d66… sorts a, c, b). Dropping the id tiebreak leaves Postgres in
        # physical order, which is a different answer; with ids that happened to
        # sort as inserted the two coincided and the test proved nothing.
        _at(je("tie-a", [("ar", 100, 0), ("rev", 0, 100)], "2026-06-01"), "00:00:05"),
        _at(je("tie-b", [("ar", 200, 0), ("rev", 0, 200)], "2026-06-01"), "00:00:05"),
        _at(je("tie-c", [("ar", 300, 0), ("rev", 0, 300)], "2026-06-01"), "00:00:05"),
    ]),
    ("a backdated entry lands in date order, not insertion order", [
        je("b1", [("ar", 100, 0), ("rev", 0, 100)], "2026-09-01"),
        je("b2", [("ar", 200, 0), ("rev", 0, 200)], "2026-05-01"),
    ]),
    ("two lines of the SAME entry hit the account", [
        # One journal, two legs on Trade Receivables. The ledger shows both.
        je("d1", [("ar", 500, 0), ("ar", 0, 200), ("rev", 0, 300)]),
    ]),
    ("a zero-amount line still appears", [
        je("z1", [("ar", 0, 0), ("rev", 0, 0)]),
    ]),
    ("balance lands exactly on zero — is_debit is >= 0, so Dr", [
        je("q1", [("ar", 10000, 0), ("rev", 0, 10000)], "2026-05-01"),
        je("q2", [("bank", 10000, 0), ("ar", 0, 10000)], "2026-06-01"),
    ]),
    ("a foreign leg carries the txn memo fields", [
        je("f1", [("ar", 830000, 0, "USD", 10000, 0, "83.00"),
                  ("rev", 0, 830000)]),
    ]),
    ("an INR leg carries none of them", [
        je("i1", [("ar", 10000, 0, "INR", 10000, 0, "1.00"), ("rev", 0, 10000)]),
    ]),
    ("a long ledger — more rows than one page", [
        je(f"m{i}", [("ar", 1000 + i, 0), ("rev", 0, 1000 + i)],
           f"2026-{(i % 12) + 4:02d}-01" if (i % 12) + 4 <= 12 else "2026-12-01")
        for i in range(40)
    ]),
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
INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'LedParity', 'l@parity.in');
INSERT INTO clients (id, firm_id, client_name, entity_type)
  VALUES ('{CLIENT}', '{FIRM}', 'Ledger Co', 'Proprietorship');
"""]
    for a in ACCOUNTS:
        out.append(
            "INSERT INTO chart_of_accounts "
            "(id, firm_id, client_id, account_code, account_name, account_type, "
            " account_subtype, system_account_key) VALUES ("
            f"'{AID[a.id]}', '{FIRM}', '{CLIENT}', {_q(a.code)}, {_q(a.name)}, "
            f"{_q(a.type)}, {_q(a.subtype)}, {_q(a.system_key)});"
        )
    for i, e in enumerate(entries):
        eid = _entry_uuid(e)
        # created_at is the ledger's second sort key, so it is seeded EXPLICITLY
        # and in insertion order. Left to now() every row in a batch could share
        # a timestamp, and the tiebreak scenario would prove nothing.
        out.append(
            "INSERT INTO journal_entries "
            "(id, firm_id, client_id, entry_date, reference_no, narration, entry_type, "
            " is_posted, status, created_at) VALUES ("
            f"'{eid}', '{FIRM}', '{CLIENT}', '{e.entry_date}', 'REF-{i}', 'narr {i}', "
            f"'Journal', true, 'posted', "
            f"TIMESTAMPTZ '{e.created_at or _created_at(i)}');"
        )
        for ln in e.lines:
            cur = getattr(ln, "txn_currency", None)
            if cur:
                out.append(
                    "INSERT INTO journal_lines (journal_entry_id, account_id, debit_paise, "
                    " credit_paise, txn_currency, txn_debit, txn_credit, exchange_rate) VALUES ("
                    f"'{eid}', '{AID[ln.account_id]}', {ln.debit_paise}, {ln.credit_paise}, "
                    f"{_q(cur)}, {ln.txn_debit or 0}, {ln.txn_credit or 0}, "
                    f"{ln.exchange_rate or 'NULL'});"
                )
            else:
                out.append(
                    "INSERT INTO journal_lines (journal_entry_id, account_id, debit_paise, credit_paise) "
                    f"VALUES ('{eid}', '{AID[ln.account_id]}', {ln.debit_paise}, {ln.credit_paise});"
                )
    return "\n".join(out)


# builders reports entry_id as the JournalEntry's id (the short name in the
# in-memory source, a UUID in Postgres), so it is dropped from the comparison —
# it is an identity, not a number, and the two sides legitimately name it
# differently. Everything that carries meaning is compared.
_DROP = {"entry_id", "account_id"}
# Paging fields the SQL side adds and builders has no notion of. Asserted
# separately rather than ignored.
_PAGING = {"total_lines", "limit", "offset"}


def _comparable(doc: dict) -> dict:
    out = json.loads(json.dumps(doc))
    out = {k: v for k, v in out.items() if k not in _PAGING and k not in _DROP}
    out["lines"] = [_comparable_line(ln) for ln in out.get("lines", [])]
    return out


def _comparable_line(ln: dict) -> dict:
    out = {k: v for k, v in ln.items() if k not in _DROP}
    # exchange_rate is the ONE field compared by VALUE rather than by string,
    # and the reason is a pre-existing wart worth naming.
    #
    #   SQL     numeric::text            -> "83.00000000"  (the column's scale)
    #   Python  str(l["exchange_rate"])  -> "83.0"
    #
    # Python's value has already been through PostgREST, which serialises
    # numeric as a JSON number, so json.loads makes it a float and the declared
    # scale is gone before sources.py ever sees it. The SQL string is therefore
    # strictly MORE faithful to what is stored, not less — the two agree on the
    # rate and differ only on how many zeros survive the wire.
    #
    # Normalising here rather than forcing one side to imitate the other keeps
    # the contract honest: the rate is a number, and neither its padding nor a
    # float round-trip is part of the answer. Everything else in this file is
    # compared byte for byte.
    if out.get("exchange_rate") is not None:
        from decimal import Decimal
        out["exchange_rate"] = str(Decimal(str(out["exchange_rate"])).normalize())
    return out


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"ledpar_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not clone the migrated template")
    dsn = f"{admin} dbname={name}"
    try:
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _sql_ledger(dsn: str, account: str = "ar", *, start: str = START, end: str = END,
                limit: int = 1000, offset: int = 0) -> dict:
    r = _psql(dsn, f"""
        SELECT public.account_ledger_page(
            '{FIRM}'::uuid, '{CLIENT}'::uuid, '{AID[account]}'::uuid,
            '{start}'::date, '{end}'::date, {limit}, {offset});
    """, tuples=True)
    assert r.returncode == 0, f"account_ledger_page failed: {r.stderr}"
    return json.loads(r.stdout.strip())


def _python_ledger(entries: list, account: str = "ar", *,
                   start: str = START, end: str = END) -> dict:
    # The in-memory source keys accounts by the SHORT id, Postgres by the seeded
    # UUID — the same account under two names. Each side is asked in its own
    # terms and `account_id` is dropped from the comparison; code, name and type
    # still have to agree, which is what proves both found the right account.
    svc = ReportingService(
        InMemoryLedgerSource(accounts=ACCOUNTS, entries=_with_metadata(entries)))
    return svc.ledger(FIRM, CLIENT, account, start, end)


# ── The parity proof ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("name,entries", SCENARIOS, ids=[s[0] for s in SCENARIOS])
def test_sql_matches_python(db, name, entries):
    seed = _psql(db, _seed_sql(entries))
    assert seed.returncode == 0, f"seed failed: {seed.stderr}"

    sql = _sql_ledger(db)
    py = _python_ledger(entries)

    assert _comparable(sql) == _comparable(py), (
        f"SQL and Python disagree on '{name}'.\n"
        f"  SQL:    {json.dumps(_comparable(sql), indent=2, sort_keys=True)}\n"
        f"  Python: {json.dumps(_comparable(py), indent=2, sort_keys=True)}"
    )
    assert sql["total_lines"] == len(py["lines"]), \
        f"total_lines {sql['total_lines']} != {len(py['lines'])} Python lines"


def test_the_comparison_can_actually_fail(db):
    """Vacuity guard. If either side returned the same empty shape for every
    scenario they would agree forever and prove nothing."""
    assert _psql(db, _seed_sql(SCENARIOS[4][1])).returncode == 0   # opening balance
    a = _sql_ledger(db)
    b = _python_ledger(SCENARIOS[2][1])                            # one credit
    assert _comparable(a) != _comparable(b), \
        "two unrelated scenarios produced identical ledgers"


# ── The paging proof ─────────────────────────────────────────────────────────

_LONG = SCENARIOS[-1][1]          # 40 entries, more than one page


def test_the_pages_reassemble_into_the_unpaged_ledger(db):
    """The one that catches a running balance computed per PAGE.

    Page 1 is identical either way, so parity alone would not notice. Every
    page concatenated must equal the whole ledger — same lines, same order,
    and crucially the same running_balance_paise, which for row 11 depends on
    rows 1..10 that page 2 never sees."""
    assert _psql(db, _seed_sql(_LONG)).returncode == 0
    whole = _python_ledger(_LONG)
    assert len(whole["lines"]) > 25, \
        f"the fixture must exceed one page to prove anything, got {len(whole['lines'])}"

    got: list[dict] = []
    for offset in range(0, len(whole["lines"]) + 10, 10):
        page = _sql_ledger(db, limit=10, offset=offset)
        got += page["lines"]
        if not page["lines"]:
            break

    assert len(got) == len(whole["lines"]), \
        f"pages yielded {len(got)} lines, unpaged has {len(whole['lines'])}"
    for i, (a, b) in enumerate(zip(got, whole["lines"])):
        assert a["running_balance_paise"] == b["running_balance_paise"], (
            f"line {i}: paged balance {a['running_balance_paise']} != "
            f"unpaged {b['running_balance_paise']} — the window is being computed "
            "per page instead of over the account's history")
        assert a["debit_paise"] == b["debit_paise"]
        assert a["credit_paise"] == b["credit_paise"]


def test_the_footer_describes_the_window_not_the_page(db):
    """Opening, closing and both totals must be identical on every page. A
    footer that summed only the visible rows would be a different document."""
    assert _psql(db, _seed_sql(_LONG)).returncode == 0
    first = _sql_ledger(db, limit=10, offset=0)
    third = _sql_ledger(db, limit=10, offset=20)
    for key in ("opening_balance_paise", "closing_balance_paise",
                "total_debit_paise", "total_credit_paise", "total_lines"):
        assert first[key] == third[key], \
            f"{key} changed between pages: {first[key]} vs {third[key]}"
    assert len(first["lines"]) == 10 and len(third["lines"]) == 10


def test_an_offset_past_the_end_is_empty_but_keeps_its_footer(db):
    assert _psql(db, _seed_sql(_LONG)).returncode == 0
    page = _sql_ledger(db, limit=10, offset=9999)
    assert page["lines"] == []
    assert page["total_lines"] > 0, "the footer must still describe the window"
    assert page["closing_balance_paise"] == _sql_ledger(db)["closing_balance_paise"]


def test_the_limit_is_clamped_rather_than_trusted(db):
    assert _psql(db, _seed_sql(_LONG)).returncode == 0
    assert _sql_ledger(db, limit=0)["limit"] == 1
    assert _sql_ledger(db, limit=99999)["limit"] == 1000
    assert _sql_ledger(db, limit=10, offset=-5)["offset"] == 0


def test_an_account_with_no_activity_still_returns_a_document(db):
    assert _psql(db, _seed_sql(SCENARIOS[1][1])).returncode == 0
    sql = _sql_ledger(db, "cap")
    py = _python_ledger(SCENARIOS[1][1], "cap")
    assert _comparable(sql) == _comparable(py)
    assert sql["lines"] == [] and sql["total_lines"] == 0
