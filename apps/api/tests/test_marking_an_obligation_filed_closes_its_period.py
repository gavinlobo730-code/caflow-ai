"""
Mark Filed on /deadlines and on a client's Compliance tab closes the period —
gst-27, practice_management-15, frontend_ux-26.

WHAT WAS WRONG
    GST-14 made the `/gst` tracker's tick write `public.filings`, the only table
    `journal_period_lock_reason` reads, so a return the CA said was filed stopped
    the books moving under it. That fixed ONE of the two trackers. The other —
    `compliance_records`, which is what /deadlines, a client's Compliance tab and
    Practice → Compliance all show — walked the obligation to "Filed" through
    `compliance_record_service.update_record` and wrote nothing else. So the same
    GSTR-3B was "filed" on one screen, locked nothing, and stayed a draft on the
    other, and the two doors a CA actually uses were the two that did not lock.

WHAT THIS ASSERTS
    * Every way to Filed — `mark-filed`, `transition`, `PATCH /compliance-records`
      — records the filing for a GSTR-1 or GSTR-3B and the period closes.
    * The window is the obligation's OWN bounds, so a QRMP quarter locks all
      three months.
    * The date is REQUIRED for those two, never defaulted — and a refusal does
      not leave the obligation half-walked.
    * A type that closes no period says so, per type, instead of ticking silently.
    * A failure to write the filing leaves the obligation open, not "Filed but
      unlocked".
    * There is no second way to Filed: a record cannot be created filed.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import get_current_user
from core.ist_clock import ist_today
from domain import compliance_record_service as crs
from mock_data import MOCK_COMPLIANCE_RECORDS
from repositories.compliance_records_repository import compliance_records_repo
from services import gst_filing_record_service as filings
from services import period_lock_service
from tests.e2e_harness import FakeDB

PARTNER = {"id": "u1", "firm_id": "F1", "role": "Partner",
           "email": "p@f1.test", "auth_user_id": "auth-partner"}


@pytest.fixture
def world(monkeypatch):
    import routers.compliance_ops as ops
    import routers.compliance_records as recs
    import services.audit_service as au
    import services.timeline_service as ts
    MOCK_COMPLIANCE_RECORDS.clear()
    db = FakeDB()
    db.seed("firms", {"id": "F1", "name": "F1", "locked_financial_years": []})
    monkeypatch.setattr(crs, "_filing_db", lambda: db)
    monkeypatch.setattr(au, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(ts.timeline_service, "log", lambda *a, **k: None)
    app = FastAPI()
    app.include_router(ops.router)
    app.include_router(recs.router)
    app.dependency_overrides[get_current_user] = lambda: PARTNER
    yield TestClient(app, raise_server_exceptions=False), db
    MOCK_COMPLIANCE_RECORDS.clear()


def _obl(obligation_type="GSTR3B", start="2026-06-01", end="2026-06-30",
         status="Ready To File", compliance_type="GST"):
    return compliance_records_repo.create({
        "firm_id": "F1", "client_id": "C1", "compliance_type": compliance_type,
        "obligation_type": obligation_type, "period_label": f"{obligation_type} {start}",
        "period_start": start, "period_end": end, "due_date": "2026-07-20",
        "status": status})


def _mark(client, rec, **body):
    return client.post(f"/api/compliance/obligations/{rec['id']}/mark-filed", json=body)


def _status(rec):
    return compliance_records_repo.find_by_id(rec["id"])["status"]


# ── the defect ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("otype,label", [("GSTR3B", "GSTR-3B"), ("GSTR1", "GSTR-1")])
def test_marking_a_gst_return_filed_closes_its_period(world, otype, label):
    """THE FINDING. Before this the tick moved a status and nothing else; the June
    books stayed editable under a June return that was already at the portal."""
    client, db = world
    rec = _obl(otype)
    assert period_lock_service.lock_reason(db, "F1", "C1", "2026-06-15") is None

    r = _mark(client, rec, filed_date="2026-07-20", acknowledgement_no="AA2706260000001")

    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["obligation"]["status"] == "Filed"
    assert data["filing_recorded"] is True
    assert data["filing_not_recorded_reason"] is None
    assert (data["period_locked_from"], data["period_locked_to"]) == ("2026-06-01", "2026-06-30")
    reason = period_lock_service.lock_reason(db, "F1", "C1", "2026-06-15")
    assert reason is not None and label in reason


def test_the_filings_row_is_the_one_the_lock_reads(world):
    client, db = world
    _mark(client, _obl("GSTR3B"), filed_date="2026-07-20", acknowledgement_no="AA2706260000001")

    rows = db.rows("filings")
    assert len(rows) == 1
    row = rows[0]
    assert row["firm_id"] == "F1" and row["client_id"] == "C1"
    assert row["filing_type"] == "GSTR-3B"
    assert row["filed_date"] == "2026-07-20"
    assert (row["period_start"], row["period_end"]) == ("2026-06-01", "2026-06-30")
    assert row["status"] == "filed"
    # The ARN rides on the same step: writing it afterwards is too late for the
    # record that carries it.
    assert row["acknowledgement_number"] == "AA2706260000001"


def test_a_quarterly_return_locks_the_whole_quarter(world):
    """GST-11: a QRMP client's GSTR-1 obligation covers a quarter, and locking
    only its first month would leave two filed months editable."""
    client, db = world
    _mark(client, _obl("GSTR1", start="2026-04-01", end="2026-06-30"), filed_date="2026-07-13")

    for d in ("2026-04-10", "2026-05-15", "2026-06-30"):
        assert period_lock_service.lock_reason(db, "F1", "C1", d), d
    assert period_lock_service.lock_reason(db, "F1", "C1", "2026-07-01") is None


def test_the_lock_is_the_clients_own(world):
    """Another client's June is untouched by this client's filing."""
    client, db = world
    _mark(client, _obl("GSTR3B"), filed_date="2026-07-20")

    assert period_lock_service.lock_reason(db, "F1", "C1", "2026-06-15")
    assert period_lock_service.lock_reason(db, "F1", "C2", "2026-06-15") is None


# ── the date is asked for, never made up ─────────────────────────────────────

@pytest.mark.parametrize("otype", ["GSTR1", "GSTR3B"])
def test_a_gst_return_without_a_filed_date_is_refused(world, otype):
    client, db = world
    rec = _obl(otype, status="Not Started")

    r = _mark(client, rec)

    assert r.status_code == 422, r.text
    assert "filed_date" in r.text
    assert db.rows("filings") == []


def test_a_refusal_does_not_leave_the_obligation_half_walked(world):
    """`mark_filed` walks four steps. The refusal is asked BEFORE the first, so a
    missing date does not strand the obligation at 'Ready To File'."""
    client, _ = world
    rec = _obl("GSTR3B", status="Not Started")

    _mark(client, rec)

    assert _status(rec) == "Not Started"


def test_a_filed_date_in_the_future_is_refused(world):
    client, db = world
    rec = _obl("GSTR3B")

    r = _mark(client, rec, filed_date="2999-01-01")

    assert r.status_code == 422, r.text
    assert _status(rec) == "Ready To File" and db.rows("filings") == []


def test_a_malformed_filed_date_is_a_422_not_a_500(world):
    client, _ = world
    r = _mark(client, _obl("GSTR3B"), filed_date="20/07/2026")
    assert r.status_code == 422, r.text


def test_a_return_cannot_have_been_filed_before_its_period_ended(world):
    client, db = world
    rec = _obl("GSTR3B")

    r = _mark(client, rec, filed_date="2026-06-10")

    assert r.status_code == 422, r.text
    assert "before" in r.text
    assert _status(rec) == "Ready To File" and db.rows("filings") == []


# ── a type that closes no period says so ─────────────────────────────────────

@pytest.mark.parametrize("otype", ["GSTR9", "GSTR9C", "TDS26Q", "TDS24Q", "TDS27Q", "TDS27EQ", "ITR"])
def test_a_return_that_locks_nothing_says_why(world, otype):
    client, db = world
    rec = _obl(otype, compliance_type="Other")

    r = _mark(client, rec, filed_date="2026-07-20")

    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["obligation"]["status"] == "Filed"
    assert data["filing_recorded"] is False
    assert data["filing_not_recorded_reason"] == filings.not_recorded_reason(otype)
    assert data["period_locked_from"] is None
    assert db.rows("filings") == []
    assert period_lock_service.lock_reason(db, "F1", "C1", "2026-06-15") is None


def test_the_reasons_are_per_type_not_one_sentence(world):
    assert filings.not_recorded_reason("GSTR9") != filings.not_recorded_reason("ITR")
    assert filings.not_recorded_reason("GSTR9") != filings.not_recorded_reason("PMT06")


def test_an_obligation_that_locks_nothing_keeps_its_old_default_date(world):
    """Only GSTR-1/3B REQUIRE the date. Every other obligation closes no period,
    so omitting it still records today — unchanged."""
    client, _ = world
    rec = _obl("TDS26Q", compliance_type="TDS")

    r = _mark(client, rec)

    assert r.status_code == 200, r.text
    assert r.json()["data"]["obligation"]["filed_date"] == ist_today().isoformat()


# ── every way to Filed records the filing ────────────────────────────────────

def test_the_transition_door_records_the_filing_too(world):
    client, db = world
    rec = _obl("GSTR3B")

    r = client.post(f"/api/compliance/obligations/{rec['id']}/transition",
                    json={"status": "Filed", "filed_date": "2026-07-20"})

    assert r.status_code == 200, r.text
    assert r.json()["data"]["filing_recorded"] is True
    assert period_lock_service.lock_reason(db, "F1", "C1", "2026-06-15")


def test_the_transition_door_needs_the_date_as_well(world):
    client, db = world
    rec = _obl("GSTR3B")

    r = client.post(f"/api/compliance/obligations/{rec['id']}/transition",
                    json={"status": "Filed"})

    assert r.status_code == 422, r.text
    assert _status(rec) == "Ready To File" and db.rows("filings") == []


def test_a_transition_to_any_other_status_records_nothing(world):
    """A stale date in a body cannot stamp a filing on an obligation that has not
    been filed."""
    client, db = world
    rec = _obl("GSTR3B", status="In Progress")

    r = client.post(f"/api/compliance/obligations/{rec['id']}/transition",
                    json={"status": "Ready For Review", "filed_date": "2026-07-20"})

    assert r.status_code == 200, r.text
    assert "filing_recorded" not in r.json()["data"]
    assert not compliance_records_repo.find_by_id(rec["id"]).get("filed_date")
    assert db.rows("filings") == []


def test_the_compliance_records_patch_door_records_the_filing_too(world):
    client, db = world
    rec = _obl("GSTR3B")

    r = client.patch(f"/api/compliance-records/{rec['id']}",
                     json={"status": "Filed", "filed_date": "2026-07-20"})

    assert r.status_code == 200, r.text
    assert "filing_lock" not in r.json()["data"]
    assert period_lock_service.lock_reason(db, "F1", "C1", "2026-06-15")


def test_the_old_filing_date_spelling_is_honoured_not_dropped(world):
    """`filing_date` was declared on this model and never read, so a caller that
    sent it got a 200 and lost the date. It is the old spelling of `filed_date`."""
    client, db = world
    rec = _obl("GSTR3B")

    r = client.patch(f"/api/compliance-records/{rec['id']}",
                     json={"status": "Filed", "filing_date": "2026-07-20"})

    assert r.status_code == 200, r.text
    assert db.rows("filings")[0]["filed_date"] == "2026-07-20"


def test_the_patch_door_needs_the_date_for_a_gst_return(world):
    client, _ = world
    rec = _obl("GSTR3B")

    r = client.patch(f"/api/compliance-records/{rec['id']}", json={"status": "Filed"})

    assert r.status_code == 422, r.text
    assert _status(rec) == "Ready To File"


def test_a_record_cannot_be_created_already_filed(world):
    """There is one place an obligation becomes Filed. Creating one already filed
    would write no filing and lock nothing."""
    client, db = world
    r = client.post("/api/compliance-records", json={
        "client_id": "C1", "compliance_type": "GST", "period_start": "2026-06-01",
        "period_end": "2026-06-30", "due_date": "2026-07-20", "status": "Filed"})

    assert r.status_code == 422, r.text
    assert db.rows("filings") == []


# ── failure and repetition ───────────────────────────────────────────────────

def test_a_failure_to_record_the_filing_leaves_the_obligation_open(world, monkeypatch):
    """'Filed but unlocked' is the defect. An obligation still open, which the CA
    can retry, is not — so the filing is written BEFORE the status moves."""
    client, db = world
    rec = _obl("GSTR3B")

    def boom(*a, **k):
        raise RuntimeError("database unavailable")
    monkeypatch.setattr(filings, "record_obligation_filing", boom)

    r = _mark(client, rec, filed_date="2026-07-20")

    assert r.status_code == 500
    assert _status(rec) == "Ready To File"
    assert db.rows("filings") == []


def test_marking_the_same_obligation_twice_writes_one_filing(world):
    client, db = world
    rec = _obl("GSTR3B")
    _mark(client, rec, filed_date="2026-07-20")

    again = _mark(client, rec, filed_date="2026-07-20")

    assert again.status_code == 200, again.text
    data = again.json()["data"]
    assert data["filing_recorded"] is False
    assert "already" in data["filing_not_recorded_reason"]
    assert len(db.rows("filings")) == 1


def test_a_retry_after_a_failure_writes_the_same_row(world, monkeypatch):
    """record_filing is idempotent on the period, which is what makes writing
    the filing first safe."""
    client, db = world
    rec = _obl("GSTR3B")
    real = filings.record_obligation_filing
    calls = {"n": 0}

    def once_then_fail_the_status(*a, **k):
        calls["n"] += 1
        return real(*a, **k)
    monkeypatch.setattr(filings, "record_obligation_filing", once_then_fail_the_status)
    monkeypatch.setattr(compliance_records_repo, "update",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("write failed")))
    assert _mark(client, rec, filed_date="2026-07-20").status_code == 500
    assert len(db.rows("filings")) == 1           # locked, obligation still open
    monkeypatch.undo()
    monkeypatch.setattr(crs, "_filing_db", lambda: db)
    monkeypatch.setattr(filings, "record_obligation_filing", real)

    assert _mark(client, rec, filed_date="2026-07-20").status_code == 200
    assert len(db.rows("filings")) == 1           # the retry refreshed it


def test_without_a_database_the_response_says_no_period_was_locked(monkeypatch):
    """Mock mode has no `filings`. The tick still records and the answer is
    honest about it, rather than claiming a lock."""
    MOCK_COMPLIANCE_RECORDS.clear()
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    rec = _obl("GSTR3B")
    out = crs.compliance_record_service.mark_filed(
        rec["id"], firm_id="F1", filed_date="2026-07-20")
    MOCK_COMPLIANCE_RECORDS.clear()
    assert out["status"] == "Filed"
    assert out["filing_lock"]["recorded"] is False
    assert "database" in out["filing_lock"]["reason"]


# ── the rule, not a spelling ─────────────────────────────────────────────────

def test_the_two_doors_share_one_map_of_which_returns_lock():
    """The calendar door and the obligation door used to keep a map each. One map
    means they cannot disagree about which returns close a period."""
    import routers.compliance as cal
    assert cal._CALENDAR_TYPE_TO_FILING_TYPE is filings.FILING_TYPE_FOR_RETURN
    assert cal._NO_FILING_ROW_REASON is filings.NO_FILING_ROW_REASON
    assert set(filings.FILING_TYPE_FOR_RETURN) == {"GSTR1", "GSTR3B"}


def test_only_update_record_moves_an_obligation_to_filed():
    """No module may write a `compliance_records` status other than through
    `update_record`: it is where the filing is recorded. The other writers of the
    table are listed with what each writes, so a NEW one has to be read against
    this rule rather than slipping past it."""
    import ast
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    allowed = {
        # (file, enclosing function) → what it writes
        ("domain/compliance_record_service.py", "update_record"): "the one Filed path",
        ("domain/compliance_record_service.py", "create_record"): "born open; Filed is refused",
        ("services/compliance_obligation_service.py", "assign"): "assignee columns only",
        ("services/compliance_obligation_service.py", "escalate"): "escalation tier columns only",
        ("services/compliance_obligation_service.py", "generate_for_engagement"): "born 'Not Started'",
        ("services/compliance_obligation_service.py", "generate_default_for_client"): "born 'Not Started'",
    }
    found: set[tuple[str, str]] = set()
    for path in list(root.glob("**/*.py")):
        rel = path.relative_to(root).as_posix()
        if rel.startswith(("tests/", "migrations/", "scripts/")) or rel == "mock_data.py":
            continue
        tree = ast.parse(path.read_text())
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for call in ast.walk(fn):
                if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                        and call.func.attr in ("update", "create")
                        and isinstance(call.func.value, ast.Name)
                        and call.func.value.id == "compliance_records_repo"):
                    found.add((rel, fn.name))
    unexpected = {k for k in found if k[0] != "repositories/compliance_records_repository.py"} - set(allowed)
    assert not unexpected, (
        f"{sorted(unexpected)} write compliance_records. Moving an obligation to Filed must go "
        f"through compliance_record_service.update_record, which records the filing and closes "
        f"the period; add the new writer to `allowed` with what it writes if it cannot touch status.")
    # Not vacuous, and not stale: every entry in the list is a writer that still
    # exists, so a renamed function cannot leave a dead exemption behind.
    assert set(allowed) == found - {k for k in found
                                    if k[0] == "repositories/compliance_records_repository.py"}
