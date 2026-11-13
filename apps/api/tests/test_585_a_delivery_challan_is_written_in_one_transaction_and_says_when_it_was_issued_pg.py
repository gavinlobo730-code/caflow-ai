"""Migration 585 — a delivery challan is written in ONE transaction, and the moment it was issued is stored (ledger POST-A-419).

WHAT WAS WRONG
    The API wrote a challan as several statements, each its own request: the header and then each line; a job-work lot and then the stamp
    "received back"; the correction of a draft's lines as a compare-and-set of the header and then one statement per line. A failure or a
    competing request in the gaps left a draft whose totals are more than its lines, a lot recorded on a challan that was not marked back,
    two lots that each fitted the line alone and not together, and an issued challan whose HSN code was changed after it was issued. The
    moment a challan was issued lived in `updated_at`, which any amendment overwrites.

WHAT THIS HOLDS (real Postgres; the migrations are applied once to a template and each test clones it)
    * `issued_at`: a nullable timestamptz with no default, not backfilled; a draft cannot carry one; once written it is never changed
      (the same value written again is not a change); a row issued before the column may be given one once.
    * `create_delivery_challan_atomic`: the header and every line, or nothing (a line that violates a constraint leaves no header; a
      duplicate number leaves nothing); the header may not choose an id, name a status other than draft, a moment of issue or a day
      back; a line takes the header's own id, firm and client whatever an element says, and a line that does not name a column takes
      its default (each line is inserted with its own keys).
    * `record_challan_lot_atomic`: records the lot; refuses in words a challan that is not issued or not a job-work challan, one that is
      not the client's and a line that is not the challan's (or is no id at all); refuses a lot that is more than the line has left,
      counting goods already lost or wasted and judged on the quantities as the column will store them, and records nothing; stamps the
      challan received back on ITS OWN latest day when ITS OWN lines have all come back in full (lost or wasted goods are not goods that
      came back, and another challan's lots and lines are not in the count); and two lots in flight at once cannot both fit (the second
      waits for the first and is refused).
    * A CHALLAN WITH A LOT IS NOT CANCELLED, in the database as well as in the API (a lot committed between the API's read and its write):
      the trigger refuses it, in words, and a cancel that arrives while a lot is being recorded waits for it and is refused.
    * `correct_draft_challan_lines_atomic`: applies the header's fields and each line's description and HSN together or not at all (a
      correction naming a line the challan does not hold undoes the header's too); a present key writes (null included) and an absent one
      leaves the column; a correction naming anything but a line's id, description and HSN code, no id, or one line twice is refused in
      its own words; refuses a challan that is not a draft; and a correction that arrives while the draft is being issued waits for the
      issue and is refused.
    * THE FUNCTIONS: SECURITY INVOKER, not executable by PUBLIC, anon or authenticated (including on a platform whose default privileges
      grant EXECUTE on a new function to the signed-in roles, which is Supabase's: the migration is applied again under them), executable
      by service_role, callable by it; the migration is idempotent; its rollback drops everything, refuses while a challan holds a moment
      of issue, and can be run twice.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode job.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import time
import uuid

import pytest

_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(not _ADMIN or not shutil.which("psql"), reason="needs HARNESS_PG and psql on PATH")

FIRM = "11111111-1111-1111-1111-111111111111"
CLIENT = "22222222-2222-2222-2222-222222222222"
OTHER_CLIENT = "33333333-3333-3333-3333-333333333333"
_STEM = "585_a_delivery_challan_is_written_in_one_transaction_and_says_when_it_was_issued"
_MIGRATIONS = pathlib.Path(__file__).resolve().parent.parent / "migrations"
_UP = _MIGRATIONS / f"{_STEM}.sql"
_DOWN = _MIGRATIONS / f"{_STEM}_rollback.sql"
CREATE = "public.create_delivery_challan_atomic(jsonb, jsonb)"
LOT = "public.record_challan_lot_atomic(uuid, uuid, uuid, jsonb)"
CORRECT = "public.correct_draft_challan_lines_atomic(uuid, uuid, uuid, jsonb, jsonb)"


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql], capture_output=True, text=True)


def _run_file(dsn: str, path: pathlib.Path) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"], input=path.read_text(encoding="utf-8"),
                          capture_output=True, text=True)


def _rows(dsn: str, sql: str) -> list:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [line for line in r.stdout.strip().splitlines() if line]


def _wait_until_a_session_sleeps(dsn: str, timeout: float = 15.0) -> None:
    """Block until another session is inside its `pg_sleep(2)`, i.e. the transaction the race needs open is open (not a guess at how long
    psql takes to start)."""
    stop = time.time() + timeout
    while time.time() < stop:
        if _rows(dsn, "SELECT count(*) FROM pg_stat_activity WHERE pid <> pg_backend_pid() AND state = 'active' "
                      "AND query LIKE '%pg_sleep(2)%' AND query NOT LIKE '%pg_stat_activity%';") != ["0"]:
            return
        time.sleep(0.05)
    raise AssertionError("the first session never reached its sleep")


def _json(value) -> str:
    return "'" + json.dumps(value).replace("'", "''") + "'::jsonb"


def _call(dsn: str, sql: str, *, role: str = "service_role") -> subprocess.CompletedProcess:
    """A single call made as the role the API uses (a privileged client), its answer on stdout."""
    return subprocess.run(["psql", dsn, "-X", "-q", "-tA", "-c", f"SET ROLE {role}; {sql}"], capture_output=True, text=True)


def _answer(done: subprocess.CompletedProcess):
    assert done.returncode == 0, done.stderr
    lines = [ln for ln in done.stdout.strip().splitlines() if ln and ln != "SET"]
    return json.loads(lines[-1]) if lines and lines[-1][:1] in "{[" else (lines[-1] if lines else "")


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"challan585_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F1', 'f1@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type, pan)
            VALUES ('{CLIENT}', '{FIRM}', 'C1', 'Private Limited', 'AAACA1234A'),
                   ('{OTHER_CLIENT}', '{FIRM}', 'C2', 'Private Limited', 'AAACB1234B');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _challan(dsn: str, *, no: str = "JW/1", status: str = "issued", client: str = CLIENT, quantity=10, lines: int = 1, reason: str = "job_work") -> tuple[str, list[str]]:
    """A job-work challan with `lines` lines of `quantity` each. Returns (challan id, line ids)."""
    cid = str(uuid.uuid4())
    lids = [str(uuid.uuid4()) for _ in range(lines)]
    stamp = ", issued_at" if status in ("issued", "received_back") else ""
    stamp_value = ", now()" if status in ("issued", "received_back") else ""
    sql = (f"INSERT INTO delivery_challans (id, firm_id, client_id, document_no, document_date, reason, status, goods_kind{stamp}) "
           f"VALUES ('{cid}', '{FIRM}', '{client}', '{no}', DATE '2026-05-10', '{reason}', '{status}', {'NULL' if reason != 'job_work' else chr(39) + 'inputs' + chr(39)}{stamp_value});")
    for i, lid in enumerate(lids):
        sql += (f"INSERT INTO delivery_challan_lines (id, firm_id, client_id, challan_id, line_order, description, quantity, unit) "
                f"VALUES ('{lid}', '{FIRM}', '{client}', '{cid}', {i}, 'Steel bar {i}', {quantity}, 'NOS');")
    done = _psql(dsn, sql)
    assert done.returncode == 0, done.stderr
    return cid, lids


def _lot(line: str, *, back="4", lost="0", on="2026-08-20", **more) -> dict:
    return {"challan_line_id": line, "returned_on": on, "quantity_returned": back, "quantity_lost_or_wasted": lost,
            "job_worker_challan_no": "JW/22", **more}


def _lot_call(dsn: str, cid: str, lot: dict, *, client: str = CLIENT) -> subprocess.CompletedProcess:
    return _call(dsn, f"SELECT {LOT.split('(')[0]}('{FIRM}', '{client}', '{cid}', {_json(lot)});")


def _header(**more) -> dict:
    return {"firm_id": FIRM, "client_id": CLIENT, "document_no": "DC/1", "document_date": "2026-05-10", "reason": "job_work",
            "status": "draft", "goods_kind": "inputs", "taxable_paise": 5000, "total_paise": 5000, **more}


def _create_call(dsn: str, header: dict, lines: list) -> subprocess.CompletedProcess:
    return _call(dsn, f"SELECT {CREATE.split('(')[0]}({_json(header)}, {_json(lines)});")


def _line(description: str = "Steel bar", **more) -> dict:
    return {"description": description, "quantity": 10, "unit": "NOS", "hsn_sac": "7214", "taxable_amount_paise": 2500, **more}


# ── the moment of issue ───────────────────────────────────────────────────────────────────────────────────

def test_issued_at_is_a_nullable_timestamp_with_no_default(db):
    assert _rows(db, """SELECT data_type || '|' || is_nullable || '|' || coalesce(column_default, '-') FROM information_schema.columns
                         WHERE table_name = 'delivery_challans' AND column_name = 'issued_at';""") == ["timestamp with time zone|YES|-"]


def test_no_challan_is_given_a_moment_it_did_not_record(db):
    """Not backfilled: a challan that existed before the column has none, and updated_at is not that moment."""
    cid, _ = _challan(db, status="draft")
    assert _rows(db, f"SELECT issued_at IS NULL FROM delivery_challans WHERE id = '{cid}';") == ["t"]


def test_a_draft_cannot_carry_a_moment_of_issue(db):
    cid, _ = _challan(db, status="draft")
    done = _psql(db, f"UPDATE delivery_challans SET issued_at = now() WHERE id = '{cid}';")
    assert done.returncode != 0 and "a draft challan has no moment of issue" in done.stderr
    bad = _psql(db, f"INSERT INTO delivery_challans (firm_id, client_id, document_no, document_date, reason, status, issued_at) "
                    f"VALUES ('{FIRM}', '{CLIENT}', 'D/9', DATE '2026-05-10', 'job_work', 'draft', now());")
    assert bad.returncode != 0 and "a draft challan has no moment of issue" in bad.stderr


def test_the_moment_is_written_with_the_issue_and_never_changed(db):
    cid, _ = _challan(db, status="draft")
    assert _psql(db, f"UPDATE delivery_challans SET status = 'issued', issued_at = TIMESTAMPTZ '2026-08-01 10:00:00+05:30' WHERE id = '{cid}';").returncode == 0
    moved = _psql(db, f"UPDATE delivery_challans SET issued_at = TIMESTAMPTZ '2026-08-02 10:00:00+05:30' WHERE id = '{cid}';")
    assert moved.returncode != 0 and "written once" in moved.stderr
    cleared = _psql(db, f"UPDATE delivery_challans SET issued_at = NULL WHERE id = '{cid}';")
    assert cleared.returncode != 0 and "written once" in cleared.stderr
    # the same value written again is not a change, and an amendment that does not name the column leaves it
    assert _psql(db, f"UPDATE delivery_challans SET issued_at = issued_at, notes = 'x' WHERE id = '{cid}';").returncode == 0
    assert _rows(db, f"SELECT to_char(issued_at AT TIME ZONE 'Asia/Kolkata', 'YYYY-MM-DD HH24:MI') FROM delivery_challans WHERE id = '{cid}';") == ["2026-08-01 10:00"]


def test_a_challan_issued_before_the_column_may_be_given_its_moment_once(db):
    cid, _ = _challan(db, status="draft")
    assert _psql(db, f"UPDATE delivery_challans SET status = 'issued' WHERE id = '{cid}';").returncode == 0
    assert _rows(db, f"SELECT issued_at IS NULL FROM delivery_challans WHERE id = '{cid}';") == ["t"]
    assert _psql(db, f"UPDATE delivery_challans SET issued_at = now() WHERE id = '{cid}';").returncode == 0


# ── (a) the header and its lines ──────────────────────────────────────────────────────────────────────────

def test_the_header_and_every_line_are_written_and_the_header_is_returned(db):
    done = _create_call(db, _header(), [_line("Bar A", line_order=0), _line("Bar B", line_order=1)])
    out = _answer(done)
    assert out["document_no"] == "DC/1" and out["status"] == "draft" and out["id"]
    assert _rows(db, f"SELECT description FROM delivery_challan_lines WHERE challan_id = '{out['id']}' ORDER BY line_order;") == ["Bar A", "Bar B"]


def test_a_line_takes_the_headers_id_firm_and_client_whatever_an_element_says(db):
    other, _ = _challan(db, no="OTHER/1", status="draft")
    done = _create_call(db, _header(), [_line("Moved?", challan_id=other, client_id=OTHER_CLIENT, firm_id=str(uuid.uuid4()))])
    out = _answer(done)
    assert _rows(db, f"SELECT challan_id = '{out['id']}' AND client_id = '{CLIENT}' AND firm_id = '{FIRM}' FROM delivery_challan_lines WHERE description = 'Moved?';") == ["t"]
    assert _rows(db, f"SELECT count(*) FROM delivery_challan_lines WHERE challan_id = '{other}' AND description = 'Moved?';") == ["0"]


def test_a_line_that_fails_leaves_no_header(db):
    """The reason for the function: the header and the lines are one transaction."""
    done = _create_call(db, _header(), [_line("fine"), {"description": None, "quantity": 1}])
    assert done.returncode != 0 and "null value" in done.stderr
    assert _rows(db, "SELECT count(*) FROM delivery_challans WHERE document_no = 'DC/1';") == ["0"]
    assert _rows(db, "SELECT count(*) FROM delivery_challan_lines WHERE description = 'fine';") == ["0"]


def test_a_duplicate_number_leaves_nothing(db):
    assert _create_call(db, _header(), [_line()]).returncode == 0
    again = _create_call(db, _header(document_no="dc/1"), [_line("second")])
    assert again.returncode != 0 and "duplicate key" in again.stderr
    assert _rows(db, "SELECT count(*) FROM delivery_challan_lines WHERE description = 'second';") == ["0"]


@pytest.mark.parametrize("key,value", [("id", "99999999-9999-4999-8999-999999999999"), ("issued_at", "2026-08-01T10:00:00+05:30"), ("received_back_on", "2026-08-01")])
def test_a_challan_is_made_as_a_draft_with_no_id_moment_or_back_day_of_its_choosing(db, key, value):
    done = _create_call(db, _header(**{key: value}), [_line()])
    assert done.returncode != 0 and "a challan is made as a draft" in done.stderr
    assert _rows(db, "SELECT count(*) FROM delivery_challans WHERE document_no = 'DC/1';") == ["0"]


@pytest.mark.parametrize("status", ["issued", "received_back", "cancelled"])
def test_a_status_other_than_draft_is_refused(db, status):
    done = _create_call(db, _header(status=status), [_line()])
    assert done.returncode != 0 and "challan_not_a_draft" in done.stderr


def test_a_header_with_no_owner_and_lines_that_are_not_an_array_are_refused(db):
    no_client = {k: v for k, v in _header().items() if k != "client_id"}
    assert "names no firm or no client" in _create_call(db, no_client, [_line()]).stderr
    assert "the lines must be a JSON array" in _call(db, f"SELECT {CREATE.split('(')[0]}({_json(_header())}, {_json({'a': 1})});").stderr


def test_a_line_that_does_not_name_a_column_takes_its_default(db):
    """Each line is inserted with its own keys: one that omits the quantity takes the column's default of 1, not NULL."""
    out = _answer(_create_call(db, _header(), [{"description": "a", "quantity": 2}, {"description": "b"}]))
    assert _rows(db, f"SELECT description || '|' || quantity FROM delivery_challan_lines WHERE challan_id = '{out['id']}' ORDER BY description;") == ["a|2.000", "b|1.000"]


def test_a_line_that_is_not_an_object_is_refused_and_nothing_is_left(db):
    done = _create_call(db, _header(), [_line("fine"), "not an object"])
    assert done.returncode != 0 and "every line must be a JSON object" in done.stderr
    assert _rows(db, "SELECT count(*) FROM delivery_challans WHERE document_no = 'DC/1';") == ["0"]


def test_a_null_header_or_null_lines_are_refused(db):
    assert "the header must be a JSON object" in _call(db, f"SELECT {CREATE.split('(')[0]}(NULL, {_json([_line()])});").stderr
    assert "the lines must be a JSON array" in _call(db, f"SELECT {CREATE.split('(')[0]}({_json(_header())}, NULL);").stderr
    assert _rows(db, "SELECT count(*) FROM delivery_challans;") == ["0"]


def test_a_challan_with_no_lines_is_made(db):
    out = _answer(_create_call(db, _header(), []))
    assert _rows(db, f"SELECT count(*) FROM delivery_challan_lines WHERE challan_id = '{out['id']}';") == ["0"]


# ── (b) one lot, and the stamp it may complete ────────────────────────────────────────────────────────────

def test_a_lot_is_recorded_and_the_challan_stays_issued_while_goods_are_out(db):
    cid, (lid,) = _challan(db)
    out = _answer(_lot_call(db, cid, _lot(lid, back="4")))
    assert out["challan_marked_received_back"] is False and out["lot"]["quantity_returned"] == 4.0
    assert _rows(db, f"SELECT status, received_back_on IS NULL FROM delivery_challans WHERE id = '{cid}';") == ["issued|t"]


def test_the_lot_that_completes_the_challan_stamps_it_on_the_latest_day(db):
    cid, (lid,) = _challan(db)
    assert _lot_call(db, cid, _lot(lid, back="4", on="2026-08-20")).returncode == 0
    out = _answer(_lot_call(db, cid, _lot(lid, back="6", on="2026-08-12")))
    assert out["challan_marked_received_back"] is True and out["received_back_on"] == "2026-08-20"
    assert _rows(db, f"SELECT status || '|' || received_back_on FROM delivery_challans WHERE id = '{cid}';") == ["received_back|2026-08-20"]


def test_a_challan_of_two_lines_is_stamped_only_when_both_are_back(db):
    cid, (a, b) = _challan(db, lines=2)
    assert _answer(_lot_call(db, cid, _lot(a, back="10")))["challan_marked_received_back"] is False
    assert _rows(db, f"SELECT status FROM delivery_challans WHERE id = '{cid}';") == ["issued"]
    assert _answer(_lot_call(db, cid, _lot(b, back="10")))["challan_marked_received_back"] is True


def test_goods_lost_or_wasted_are_not_goods_that_came_back(db):
    cid, (lid,) = _challan(db)
    assert _lot_call(db, cid, _lot(lid, back="4")).returncode == 0
    out = _answer(_lot_call(db, cid, _lot(lid, back="0", lost="6")))
    assert out["challan_marked_received_back"] is False
    assert _rows(db, f"SELECT status FROM delivery_challans WHERE id = '{cid}';") == ["issued"]


def test_a_lot_more_than_the_line_has_left_is_refused_and_records_nothing(db):
    cid, (lid,) = _challan(db)
    assert _lot_call(db, cid, _lot(lid, back="4")).returncode == 0
    done = _lot_call(db, cid, _lot(lid, back="5", lost="2"))
    assert done.returncode != 0 and "lot_exceeds_line" in done.stderr and "sent 10.000, back 4.000, lost 0.000" in done.stderr
    assert _rows(db, f"SELECT count(*) FROM delivery_challan_returns WHERE challan_id = '{cid}';") == ["1"]


@pytest.mark.parametrize("status", ["draft", "cancelled", "received_back"])
def test_a_challan_that_is_not_issued_takes_no_lot(db, status):
    cid, (lid,) = _challan(db, status=status)
    done = _lot_call(db, cid, _lot(lid))
    assert done.returncode != 0 and "challan_not_issued" in done.stderr and f"status is {status}" in done.stderr
    assert _rows(db, f"SELECT count(*) FROM delivery_challan_returns WHERE challan_id = '{cid}';") == ["0"]


def test_another_clients_challan_and_another_challans_line_are_not_found(db):
    cid, (lid,) = _challan(db)
    other, (other_line,) = _challan(db, no="JW/2")
    assert "challan_not_found" in _lot_call(db, cid, _lot(lid), client=OTHER_CLIENT).stderr
    assert "challan_not_found" in _call(db, f"SELECT {LOT.split('(')[0]}('{FIRM}', '{CLIENT}', '{uuid.uuid4()}', {_json(_lot(lid))});").stderr
    assert "line_not_found" in _lot_call(db, cid, _lot(other_line)).stderr
    assert _rows(db, "SELECT count(*) FROM delivery_challan_returns;") == ["0"]


def test_a_lot_naming_another_challan_or_client_is_recorded_on_the_one_judged(db):
    cid, (lid,) = _challan(db)
    other, _ = _challan(db, no="JW/2")
    assert _lot_call(db, cid, _lot(lid, challan_id=other, client_id=OTHER_CLIENT)).returncode == 0
    assert _rows(db, f"SELECT challan_id = '{cid}' AND client_id = '{CLIENT}' FROM delivery_challan_returns;") == ["t"]


def test_two_lots_in_flight_at_once_cannot_both_fit(db):
    """The reason for the lock: 6 and 6 against a line of 10 each fit alone. The second waits for the first and is refused."""
    cid, (lid,) = _challan(db)
    first = subprocess.Popen(["psql", db, "-X", "-q", "-tA", "-c",
        f"SET ROLE service_role; BEGIN; SELECT {LOT.split('(')[0]}('{FIRM}', '{CLIENT}', '{cid}', {_json(_lot(lid, back='6'))}); SELECT pg_sleep(2); COMMIT;"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    _wait_until_a_session_sleeps(db)
    started = time.time()
    second = _lot_call(db, cid, _lot(lid, back="6", on="2026-08-25"))
    waited = time.time() - started
    first.communicate(timeout=30)
    assert first.returncode == 0
    assert second.returncode != 0 and "lot_exceeds_line" in second.stderr, second.stderr
    assert waited >= 0.5, f"the second lot did not wait for the first ({waited:.2f}s)"
    assert _rows(db, f"SELECT count(*) FROM delivery_challan_returns WHERE challan_id = '{cid}';") == ["1"]


def test_goods_already_lost_count_against_what_the_next_lot_may_take(db):
    """The room is what was sent less what came back AND what was lost or wasted."""
    cid, (lid,) = _challan(db)
    assert _lot_call(db, cid, _lot(lid, back="0", lost="6")).returncode == 0
    done = _lot_call(db, cid, _lot(lid, back="5"))
    assert done.returncode != 0 and "lot_exceeds_line" in done.stderr and "lost 6.000" in done.stderr
    assert _lot_call(db, cid, _lot(lid, back="4")).returncode == 0       # exactly what is left


def test_the_room_is_judged_on_the_quantities_as_the_column_stores_them(db):
    """1.0005 and 1.0005 against 2.001 would store 1.001 + 1.001 = 2.002."""
    cid, (lid,) = _challan(db, quantity="2.001")
    done = _lot_call(db, cid, _lot(lid, back="1.0005", lost="1.0005"))
    assert done.returncode != 0 and "lot_exceeds_line" in done.stderr
    assert _rows(db, f"SELECT count(*) FROM delivery_challan_returns WHERE challan_id = '{cid}';") == ["0"]


def test_another_challans_lines_and_lots_are_not_in_this_challans_count_or_stamp(db):
    """Two challans of one client, lots on both: the completing lot of X stamps X while Y is still open, on X's own latest day."""
    x, (xl,) = _challan(db, no="JW/X")
    y, (yl,) = _challan(db, no="JW/Y")
    assert _lot_call(db, y, _lot(yl, back="3", on="2026-09-30")).returncode == 0      # Y: open, and a later day than X's
    assert _lot_call(db, x, _lot(xl, back="4", on="2026-08-10")).returncode == 0
    out = _answer(_lot_call(db, x, _lot(xl, back="6", on="2026-08-15")))
    assert out["challan_marked_received_back"] is True and out["received_back_on"] == "2026-08-15", out
    assert _rows(db, f"SELECT status || '|' || received_back_on FROM delivery_challans WHERE id = '{x}';") == ["received_back|2026-08-15"]
    assert _rows(db, f"SELECT status FROM delivery_challans WHERE id = '{y}';") == ["issued"]


def test_the_stamp_moves_updated_at(db):
    cid, (lid,) = _challan(db)
    assert _psql(db, f"UPDATE delivery_challans SET updated_at = TIMESTAMPTZ '2020-01-01 00:00:00+00' WHERE id = '{cid}';").returncode == 0
    assert _lot_call(db, cid, _lot(lid, back="10")).returncode == 0
    assert _rows(db, f"SELECT updated_at > TIMESTAMPTZ '2025-01-01 00:00:00+00' FROM delivery_challans WHERE id = '{cid}';") == ["t"]


def test_a_challan_that_is_not_job_work_takes_no_lot(db):
    cid, (lid,) = _challan(db, no="AP/1", reason="sale_on_approval")
    done = _lot_call(db, cid, _lot(lid))
    assert done.returncode != 0 and "challan_not_job_work" in done.stderr and "reason is sale_on_approval" in done.stderr


@pytest.mark.parametrize("line", [None, "not-a-uuid", ""])
def test_a_lot_that_names_no_real_line_is_a_line_not_found(db, line):
    cid, _ = _challan(db)
    lot = {k: v for k, v in _lot("x").items() if k != "challan_line_id"}
    if line is not None:
        lot["challan_line_id"] = line
    done = _lot_call(db, cid, lot)
    assert done.returncode != 0 and "line_not_found" in done.stderr, done.stderr


# ---- a challan with a lot is not cancelled ------------------------------------------------------------------------------

def test_a_challan_with_a_lot_is_not_cancelled_by_the_database(db):
    cid, (lid,) = _challan(db)
    assert _lot_call(db, cid, _lot(lid, back="4")).returncode == 0
    done = _psql(db, f"UPDATE delivery_challans SET status = 'cancelled' WHERE id = '{cid}';")
    assert done.returncode != 0 and "challan_has_lots" in done.stderr
    assert _rows(db, f"SELECT status FROM delivery_challans WHERE id = '{cid}';") == ["issued"]


def test_a_challan_with_no_lot_is_cancelled_and_a_cancelled_one_is_saved_again(db):
    cid, _ = _challan(db)
    assert _psql(db, f"UPDATE delivery_challans SET status = 'cancelled' WHERE id = '{cid}';").returncode == 0
    assert _psql(db, f"UPDATE delivery_challans SET status = 'cancelled', notes = 'again' WHERE id = '{cid}';").returncode == 0


def test_a_cancel_that_arrives_while_a_lot_is_being_recorded_waits_and_is_refused(db):
    cid, (lid,) = _challan(db)
    first = subprocess.Popen(["psql", db, "-X", "-q", "-tA", "-c",
        f"SET ROLE service_role; BEGIN; SELECT {LOT.split('(')[0]}('{FIRM}', '{CLIENT}', '{cid}', {_json(_lot(lid, back='4'))}); SELECT pg_sleep(2); COMMIT;"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    _wait_until_a_session_sleeps(db)
    done = _psql(db, f"UPDATE delivery_challans SET status = 'cancelled' WHERE id = '{cid}';")
    first.communicate(timeout=30)
    assert first.returncode == 0
    assert done.returncode != 0 and "challan_has_lots" in done.stderr, done.stderr
    assert _rows(db, f"SELECT status FROM delivery_challans WHERE id = '{cid}';") == ["issued"]


def test_a_cancel_in_flight_wins_and_the_lot_is_refused(db):
    cid, (lid,) = _challan(db)
    cancel = subprocess.Popen(["psql", db, "-X", "-q", "-tA", "-c",
        f"BEGIN; UPDATE delivery_challans SET status = 'cancelled' WHERE id = '{cid}'; SELECT pg_sleep(2); COMMIT;"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    _wait_until_a_session_sleeps(db)
    done = _lot_call(db, cid, _lot(lid, back="4"))
    cancel.communicate(timeout=30)
    assert done.returncode != 0 and "challan_not_issued" in done.stderr and "status is cancelled" in done.stderr
    assert _rows(db, f"SELECT count(*) FROM delivery_challan_returns WHERE challan_id = '{cid}';") == ["0"]


# ── (d) a draft's corrections, header and lines together ──────────────────────────────────────────────────

def _correct_call(dsn: str, cid: str, header: dict, fixes: list, *, client: str = CLIENT) -> subprocess.CompletedProcess:
    return _call(dsn, f"SELECT {CORRECT.split('(')[0]}('{FIRM}', '{client}', '{cid}', {_json(header)}, {_json(fixes)});")


def test_the_header_and_the_lines_are_corrected_together(db):
    cid, (a, b) = _challan(db, status="draft", lines=2)
    done = _correct_call(db, cid, {"notes": "corrected", "vehicle_no": "MH12AB1234"}, [{"id": a, "description": "Bar A2", "hsn_sac": "7228"}, {"id": b, "description": "Bar B2"}])
    assert _answer(done) == "2"
    assert _rows(db, f"SELECT notes || '|' || vehicle_no FROM delivery_challans WHERE id = '{cid}';") == ["corrected|MH12AB1234"]
    assert _rows(db, f"SELECT description || '|' || coalesce(hsn_sac, '-') FROM delivery_challan_lines WHERE challan_id = '{cid}' ORDER BY line_order;") == ["Bar A2|7228", "Bar B2|-"]


def test_a_key_that_is_absent_leaves_the_column_and_one_that_is_present_writes_it(db):
    cid, (a, b) = _challan(db, status="draft", lines=2)
    _psql(db, f"UPDATE delivery_challan_lines SET hsn_sac = '7214' WHERE challan_id = '{cid}';")
    assert _correct_call(db, cid, {}, [{"id": a, "description": "only the description"}, {"id": b, "hsn_sac": None}]).returncode == 0
    assert _rows(db, f"SELECT description || '|' || coalesce(hsn_sac, 'NULL') FROM delivery_challan_lines WHERE id = '{a}';") == ["only the description|7214"]
    assert _rows(db, f"SELECT description || '|' || coalesce(hsn_sac, 'NULL') FROM delivery_challan_lines WHERE id = '{b}';") == ["Steel bar 1|NULL"]


def test_a_correction_naming_a_line_the_challan_does_not_hold_undoes_the_headers_too(db):
    """The reason for the function: a write that fails part-way leaves nothing."""
    cid, (a,) = _challan(db, status="draft")
    other, (stranger,) = _challan(db, no="JW/2", status="draft")
    done = _correct_call(db, cid, {"notes": "should not stay"}, [{"id": a, "description": "changed"}, {"id": stranger, "description": "stolen"}])
    assert done.returncode != 0 and "line_not_found" in done.stderr and "1 of 2 corrections" in done.stderr
    assert _rows(db, f"SELECT coalesce(notes, '-') FROM delivery_challans WHERE id = '{cid}';") == ["-"]
    assert _rows(db, f"SELECT description FROM delivery_challan_lines WHERE id = '{a}';") == ["Steel bar 0"]
    assert _rows(db, f"SELECT description FROM delivery_challan_lines WHERE id = '{stranger}';") == ["Steel bar 0"]


@pytest.mark.parametrize("status", ["issued", "received_back", "cancelled"])
def test_a_challan_that_is_not_a_draft_is_not_corrected(db, status):
    cid, (a,) = _challan(db, status=status)
    done = _correct_call(db, cid, {"notes": "no"}, [{"id": a, "description": "no"}])
    assert done.returncode != 0 and "challan_not_draft" in done.stderr and f"status is {status}" in done.stderr
    assert _rows(db, f"SELECT description FROM delivery_challan_lines WHERE id = '{a}';") == ["Steel bar 0"]


@pytest.mark.parametrize("key", ["status", "id", "firm_id", "client_id", "issued_at", "received_back_on"])
def test_a_correction_of_a_draft_does_not_name_its_status_owner_or_a_day(db, key):
    cid, (a,) = _challan(db, status="draft")
    done = _correct_call(db, cid, {key: "x"}, [{"id": a, "description": "d"}])
    assert done.returncode != 0 and "does not name its id, its owner, its status or a day" in done.stderr


def test_a_fix_naming_anything_but_the_description_and_the_hsn_code_is_refused(db):
    cid, (a,) = _challan(db, status="draft")
    for fix in ({"id": a, "quantity": 99}, {"id": a, "description": "ok", "unit": "KGS"}, {"description": "no id"}, "not an object"):
        done = _correct_call(db, cid, {"notes": "should not stay"}, [fix])
        assert done.returncode != 0 and "names a line by id and gives its description and/or its HSN code" in done.stderr, (fix, done.stderr)
    assert _rows(db, f"SELECT quantity FROM delivery_challan_lines WHERE id = '{a}';") == ["10.000"]
    assert _rows(db, f"SELECT coalesce(notes, '-') FROM delivery_challans WHERE id = '{cid}';") == ["-"]


def test_a_line_corrected_twice_in_one_request_is_refused_in_its_own_words(db):
    cid, (a,) = _challan(db, status="draft")
    done = _correct_call(db, cid, {"notes": "no"}, [{"id": a, "description": "one"}, {"id": a, "description": "two"}])
    assert done.returncode != 0 and "duplicate_fix" in done.stderr and "line_not_found" not in done.stderr
    assert _rows(db, f"SELECT description FROM delivery_challan_lines WHERE id = '{a}';") == ["Steel bar 0"]


def test_null_arguments_to_the_correction_are_refused(db):
    cid, _ = _challan(db, status="draft")
    assert "the fixes must be a JSON array" in _call(db, f"SELECT {CORRECT.split('(')[0]}('{FIRM}', '{CLIENT}', '{cid}', {_json({'notes': 'x'})}, NULL);").stderr
    assert "the header patch must be a JSON object" in _call(db, f"SELECT {CORRECT.split('(')[0]}('{FIRM}', '{CLIENT}', '{cid}', NULL, {_json([])});").stderr
    assert _rows(db, f"SELECT coalesce(notes, '-') FROM delivery_challans WHERE id = '{cid}';") == ["-"]


def test_another_clients_draft_is_not_found(db):
    cid, (a,) = _challan(db, status="draft")
    assert "challan_not_found" in _correct_call(db, cid, {}, [{"id": a, "description": "d"}], client=OTHER_CLIENT).stderr


def test_a_correction_that_arrives_while_the_draft_is_being_issued_waits_and_is_refused(db):
    cid, (a,) = _challan(db, status="draft")
    issuing = subprocess.Popen(["psql", db, "-X", "-q", "-tA", "-c",
        f"BEGIN; UPDATE delivery_challans SET status = 'issued', issued_at = now() WHERE id = '{cid}'; SELECT pg_sleep(2); COMMIT;"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    _wait_until_a_session_sleeps(db)
    started = time.time()
    done = _correct_call(db, cid, {}, [{"id": a, "hsn_sac": "9999"}])
    issuing.communicate(timeout=30)
    assert done.returncode != 0 and "challan_not_draft" in done.stderr and "status is issued" in done.stderr
    assert time.time() - started >= 0.5, "the correction did not wait for the issue"
    assert _rows(db, f"SELECT coalesce(hsn_sac, '-') FROM delivery_challan_lines WHERE id = '{a}';") == ["-"]


# ── the functions, their rights and the migration ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("function", [CREATE, LOT, CORRECT])
def test_each_function_is_security_invoker_and_only_service_role_may_call_it(db, function):
    assert _rows(db, f"SELECT prosecdef FROM pg_proc WHERE oid = '{function}'::regprocedure;") == ["f"]
    for role in ("anon", "authenticated"):
        assert _rows(db, f"SELECT has_function_privilege('{role}', '{function}', 'EXECUTE');") == ["f"], role
    assert _rows(db, f"SELECT has_function_privilege('service_role', '{function}', 'EXECUTE');") == ["t"]
    assert _rows(db, f"SELECT count(*) FROM information_schema.routine_privileges WHERE grantee = 'PUBLIC' AND specific_name LIKE '{function.split('.')[1].split('(')[0]}%';") == ["0"]


def test_a_signed_in_session_cannot_call_the_functions(db):
    done = _call(db, f"SELECT {CREATE.split('(')[0]}({_json(_header())}, {_json([_line()])});", role="authenticated")
    assert done.returncode != 0 and "permission denied" in done.stderr
    assert _rows(db, "SELECT count(*) FROM delivery_challans;") == ["0"]


def test_the_migration_is_idempotent(db):
    again = _run_file(db, _UP)
    assert again.returncode == 0, again.stderr


def test_the_rollback_drops_everything_and_refuses_while_a_moment_of_issue_is_held(db):
    cid, _ = _challan(db)          # issued, with a moment
    refused = _run_file(db, _DOWN)
    assert refused.returncode != 0 and "rollback of 585 refused" in refused.stderr
    assert _rows(db, f"SELECT to_regprocedure('{CREATE}') IS NOT NULL;") == ["t"]
    assert _psql(db, f"DELETE FROM delivery_challan_lines; DELETE FROM delivery_challans WHERE id = '{cid}';").returncode == 0
    ok = _run_file(db, _DOWN)
    assert ok.returncode == 0, ok.stderr
    for function in (CREATE, LOT, CORRECT):
        assert _rows(db, f"SELECT to_regprocedure('{function}') IS NULL;") == ["t"], function
    assert _rows(db, "SELECT count(*) FROM information_schema.columns WHERE table_name = 'delivery_challans' AND column_name = 'issued_at';") == ["0"]
    assert _run_file(db, _UP).returncode == 0       # and it can be applied again


def test_the_migration_applies_where_the_platform_grants_new_functions_to_the_signed_in_roles(db):
    """Supabase grants EXECUTE on a new public function to anon and authenticated by default; a revoke from PUBLIC alone leaves both, and the
    migration's own self-check then refused to apply (found by the independent read). Applied again under those default privileges, the
    functions are closed to the signed-in roles and a signed-in session is refused."""
    assert _run_file(db, _DOWN).returncode == 0
    assert _psql(db, "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO anon, authenticated;").returncode == 0
    applied = _run_file(db, _UP)
    assert applied.returncode == 0, applied.stderr
    for function in (CREATE, LOT, CORRECT, "public.delivery_challans_issued_at_is_written_once()", "public.delivery_challans_with_lots_are_not_cancelled()"):
        for role in ("anon", "authenticated", "public"):
            assert _rows(db, f"SELECT has_function_privilege('{role}', '{function}', 'EXECUTE');") == ["f"], (function, role)
    done = _call(db, f"SELECT {CREATE.split('(')[0]}({_json(_header())}, {_json([_line()])});", role="authenticated")
    assert done.returncode != 0 and "permission denied" in done.stderr


def test_the_rollback_can_be_run_twice(db):
    assert _run_file(db, _DOWN).returncode == 0
    again = _run_file(db, _DOWN)
    assert again.returncode == 0, again.stderr
