"""
A live Tally import starts, finishes, and says in words why it did not.

WHAT WAS WRONG (sweep-clients-admin-01)
    POST /api/tally-migration/jobs/{id}/import with is_dry_run=false answered
    500 "Internal server error" on EVERY real import, while the dry run of the
    same job answered 200. The router queued the background import and then
    wrote a timeline note as

        timeline_service.log(client_id="", category=..., action="...",
                             metadata={...})

    against a function whose parameters are `title` and no `metadata`. That is
    a TypeError at the call, raised BEFORE the handler returned — and a
    FastAPI background task is attached to the RESPONSE, so the import it had
    just queued was never run. The job stayed `previewing` for ever (the
    import's first act is to write `importing`, and it never happened), and the
    page, which checked `if (res.success)` with no else, showed nothing at all.

    Two production jobs are in exactly that state (tally_migration_jobs,
    27-09-2026, both `previewing` with imported_items 0 after a live import).

AND THREE THINGS BEHIND IT, which the 500 was hiding
    * a job of one plain LEDGER would have finished `completed · 1 imported`
      with nothing created anywhere — `_import_single_item` writes customers and
      vendors only and returns (None, None) for everything else, which was
      counted as a success;
    * a failed item stored `str(e)`, which for a database refusal is the whole
      APIError payload with the sentence buried in a dict repr;
    * a crashed detached import marked itself failed through the SAME client
      that had just failed (the caller's, whose JWT the background task still
      carries), and put the raw exception in `import_audit_log` as a DICT —
      in a column that holds a per-run LIST — where no screen looked.

    The run's sentence is now the audit log's last entry, served on the job as
    `run_message`. Not `tally_migration_jobs.error_message`: production has
    that column but the migrations do not declare it, so naming it fails the
    real-Postgres column check (see migration_service._summary_entry).

Each test below fails against the code as it was.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import domain.tally.migration_service as svc
import routers.tally_migration as tm
from core.auth import get_current_user
from services import timeline_service as tl

FIRM = "firm-1"
PARTNER = {"id": "u-partner", "auth_user_id": "a-partner", "firm_id": FIRM,
           "email": "p@f.test", "role": "Partner"}

ONE_LEDGER = """<ENVELOPE><BODY><DATA>
<TALLYMESSAGE><LEDGER NAME="Office Rent"><PARENT>Indirect Expenses</PARENT>
<OPENINGBALANCE>0</OPENINGBALANCE></LEDGER></TALLYMESSAGE>
</DATA></BODY></ENVELOPE>"""


@pytest.fixture(autouse=True)
def _clean_mock_store(monkeypatch):
    # Mock mode, whatever the environment says: these tests exercise the
    # router, and the service's real branch is covered below on a fake.
    monkeypatch.setattr(svc, "_USE_MOCK", True)
    svc._MOCK_JOBS.clear()
    svc._MOCK_ITEMS.clear()
    yield
    svc._MOCK_JOBS.clear()
    svc._MOCK_ITEMS.clear()


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(tm.router)
    app.dependency_overrides[get_current_user] = lambda: PARTNER
    # raise_server_exceptions=False: the defect WAS a 500, and a test that
    # re-raised it would report a TypeError instead of the status a CA saw.
    return TestClient(app, raise_server_exceptions=False)


def _job(client, **overrides) -> str:
    body = {"name": "FY26 import", "source_file_name": "tally.xml",
            "target_financial_year": "2025-26", "import_types": ["ledgers"]}
    body.update(overrides)
    r = client.post("/api/tally-migration/jobs", json=body)
    assert r.status_code == 200, r.text
    job_id = r.json()["data"]["id"]
    r = client.post(f"/api/tally-migration/jobs/{job_id}/parse",
                    json={"xml_content": ONE_LEDGER})
    assert r.status_code == 200, r.text
    return job_id


# ── The 500 ──────────────────────────────────────────────────────────────────

def test_a_live_import_answers_200_and_its_background_import_actually_runs(client):
    job_id = _job(client)

    dry = client.post(f"/api/tally-migration/jobs/{job_id}/import", json={"is_dry_run": True})
    assert dry.status_code == 200, "premise: the dry run always worked"

    live = client.post(f"/api/tally-migration/jobs/{job_id}/import", json={"is_dry_run": False})

    assert live.status_code == 200, (
        f"a live import answered {live.status_code}: {live.text} — the request "
        "raised after queuing the import, so the import never ran")
    assert live.json()["data"]["status"] == "importing"
    # TestClient runs the response's background tasks before returning, so the
    # job has been through the whole detached import by now.
    job = client.get(f"/api/tally-migration/jobs/{job_id}").json()["data"]
    assert job["status"] == "completed", (
        f"job is {job['status']!r} — the background import did not run")


def test_a_client_job_records_its_start_on_that_clients_timeline(client, monkeypatch):
    """The timeline note is written in the shape log() accepts, onto the
    client's timeline, naming the job — and only where there IS a client."""
    monkeypatch.setattr(tm, "assert_client_access", lambda user, cid: None)
    monkeypatch.setattr(tm, "can_access_client", lambda user, cid: True)
    tl.MOCK_TIMELINE_EVENTS.clear()

    job_id = _job(client, client_id="client-1")
    r = client.post(f"/api/tally-migration/jobs/{job_id}/import", json={"is_dry_run": False})

    assert r.status_code == 200, r.text
    notes = [e for e in tl.MOCK_TIMELINE_EVENTS if e["entity_id"] == job_id]
    assert len(notes) == 1, tl.MOCK_TIMELINE_EVENTS
    assert notes[0]["client_id"] == "client-1"
    assert notes[0]["firm_id"] == FIRM, "client_timeline_events.firm_id is NOT NULL"
    assert notes[0]["title"] == "Tally import started"


def test_a_firm_level_job_writes_no_timeline_note(client):
    """client_timeline_events.client_id is a NOT NULL uuid, so a job with no
    client has nowhere to put one — the old call sent client_id=""."""
    tl.MOCK_TIMELINE_EVENTS.clear()
    job_id = _job(client)
    client.post(f"/api/tally-migration/jobs/{job_id}/import", json={"is_dry_run": False})
    assert not [e for e in tl.MOCK_TIMELINE_EVENTS if e.get("entity_id") == job_id]


def test_a_ledger_only_job_does_not_claim_to_have_imported_the_ledger(client):
    job_id = _job(client)
    client.post(f"/api/tally-migration/jobs/{job_id}/import", json={"is_dry_run": False})

    job = client.get(f"/api/tally-migration/jobs/{job_id}").json()["data"]
    assert job["imported_items"] == 0, "nothing was written, so nothing was imported"
    assert "not written" in (job.get("run_message") or ""), job


def test_a_customer_or_vendor_job_must_name_its_client_before_it_is_created(client):
    r = client.post("/api/tally-migration/jobs", json={
        "name": "Parties", "source_file_name": "tally.xml",
        "target_financial_year": "2025-26",
        "import_types": ["ledgers", "customers", "vendors"],
    })
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert "customers and vendors" in detail and "client" in detail
    assert not svc._MOCK_JOBS, "a job that can only fail must not be created"


# ── The write path, on a fake PostgREST ──────────────────────────────────────

class _Res:
    def __init__(self, data):
        self.data = data


class _Q:
    def __init__(self, store, table):
        self.store, self.table, self.filters = store, table, []
        self.op, self.payload = "select", None

    def select(self, *_a, **_k):
        return self

    def insert(self, payload):
        self.op, self.payload = "insert", payload
        return self

    def update(self, payload):
        self.op, self.payload = "update", payload
        return self

    def eq(self, col, val):
        self.filters.append((col, val))
        return self

    def gt(self, *_a):
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a):
        return self

    def execute(self):
        rows = [r for r in self.store.rows.get(self.table, [])
                if all(r.get(c) == v for c, v in self.filters)]
        if self.op == "update":
            self.store.updates.append((self.table, dict(self.payload), list(self.filters)))
            for r in rows:
                r.update(self.payload)
            return _Res(rows)
        if self.op == "insert":
            self.store.inserts.append((self.table, self.payload))
            return _Res([{"id": "new-1"}])
        return _Res([dict(r) for r in rows])


class _Store:
    def __init__(self, items, job):
        self.rows = {"tally_migration_items": items, "tally_migration_jobs": [job]}
        self.updates: list = []
        self.inserts: list = []

    def table(self, name):
        return _Q(self, name)

    def job_updates(self):
        return [p for (t, p, _f) in self.updates if t == "tally_migration_jobs"]


def _item(i, item_type, status="validated", **data):
    return {"id": f"it-{i}", "job_id": "job-1", "firm_id": FIRM, "status": status,
            "item_type": item_type, "tally_id": data.get("name"), "tally_data": data}


@pytest.fixture
def real(monkeypatch):
    def _make(items, client_id="client-1"):
        st = _Store(items, {"id": "job-1", "firm_id": FIRM, "client_id": client_id})
        monkeypatch.setattr(svc, "_USE_MOCK", False)
        monkeypatch.setattr(svc, "_supabase", lambda: st)
        return st
    return _make


def test_an_item_type_the_importer_does_not_write_is_reported_not_imported(real):
    st = real([_item(1, "ledger", name="Office Rent"),
               _item(2, "journal", name="JV-1"),
               _item(3, "customer", name="Acme Traders")])

    report = svc.execute_import(FIRM, "job-1", "actor", is_dry_run=False)

    assert report["imported"] == 1, report
    assert report["not_written"] == 2
    final = st.job_updates()[-1]
    assert final["status"] == "completed"
    assert final["imported_items"] == 1
    assert "2 items (1 journal, 1 ledger) were not written" in svc.run_message(final)
    written = [t for (t, _p) in st.inserts]
    assert written == ["customers"], f"only the customer is a record: {written}"
    items = {r["id"]: r for r in st.rows["tally_migration_items"]}
    assert items["it-1"]["status"] != "imported", "a ledger nobody wrote is not imported"


def test_the_dry_run_says_up_front_what_a_live_run_will_not_write(real):
    real([_item(1, "ledger", name="Office Rent")])
    report = svc.execute_import(FIRM, "job-1", "actor", is_dry_run=True)
    assert report["not_written"] == 1
    assert "not written" in report["message"]


class _Refused(Exception):
    """What supabase-py raises for a refused write: a code and a message."""

    def __init__(self):
        super().__init__({"code": "42501",
                          "message": "permission denied for table customers"})
        self.code = "42501"
        self.message = "permission denied for table customers"


def test_a_failed_item_is_named_in_a_sentence_and_a_run_that_wrote_nothing_is_an_error(
        real, monkeypatch):
    st = real([_item(1, "customer", name="Acme Traders")])

    def _refuse(*_a, **_k):
        raise _Refused()

    monkeypatch.setattr(svc, "_import_single_item", _refuse)
    svc.execute_import(FIRM, "job-1", "actor", is_dry_run=False)

    final = st.job_updates()[-1]
    assert final["status"] == "error", "a run that imported nothing and failed is not `completed`"
    msg = svc.run_message(final)
    assert msg.startswith("1 item could not be imported."), msg
    assert "Acme Traders" in msg
    assert "not permitted to write this table" in msg, (
        "the reason is core.exceptions' sentence for 42501, not the raw payload")
    item = st.rows["tally_migration_items"][0]
    assert item["status"] == "failed"
    assert "{'code'" not in item["error_message"], item["error_message"]


def test_a_rerun_clears_the_last_runs_failure_sentence(real):
    job = {"id": "job-1", "firm_id": FIRM, "client_id": "client-1",
           "import_audit_log": [{"run_summary": "1 item could not be imported.",
                                 "status": "error"}]}
    st = real([_item(1, "customer", name="Acme Traders")])
    st.rows["tally_migration_jobs"] = [job]
    assert svc.run_message(job), "premise: the last run left a sentence"

    svc.execute_import(FIRM, "job-1", "actor", is_dry_run=False)

    starting = st.job_updates()[0]
    assert starting["status"] == "importing" and starting["import_audit_log"] == []
    assert job["status"] == "completed"
    assert svc.run_message(job) is None, "a run that went fine says nothing"


# ── A detached import that crashes ───────────────────────────────────────────

class _Expired:
    """The caller's client after its JWT has lapsed: every use fails."""

    def table(self, _name):
        raise RuntimeError("JWT expired")


def test_a_crashed_detached_import_marks_the_job_error_through_the_service_client(monkeypatch):
    service = _Store([], {"id": "job-1", "firm_id": FIRM})
    monkeypatch.setattr(svc, "_USE_MOCK", False)
    monkeypatch.setattr(svc, "_supabase", lambda: _Expired())
    monkeypatch.setattr(svc, "_service_supabase", lambda: service)

    svc.run_import_detached(FIRM, "job-1", "actor")   # must not raise

    marks = service.job_updates()
    assert marks, ("the failure was marked through the caller's client — the one "
                   "that had just failed — so it was never recorded")
    assert marks[-1]["status"] == "error"
    assert isinstance(marks[-1]["import_audit_log"], list), (
        "import_audit_log holds a per-run LIST; the old handler wrote a dict")
    assert "JWT expired" in svc.run_message(marks[-1])
    (_t, _p, filters), = [u for u in service.updates if u[0] == "tally_migration_jobs"]
    assert ("id", "job-1") in filters and ("firm_id", FIRM) in filters
