"""
Client-assignment scope on the THREE GST routers.

`gst_workspace` (13 endpoints, `/api/gst-workspace`), `gst_portal` (5,
`/api/gst-portal`) and `gst` (7, `/api/gst`) are one feature and three
registrations. `/api/gst` is a string prefix of the other two — the sweep takes
the longest match, which is why that had to be fixed before this phase.

WHAT WAS THERE
    `gst_workspace` called `assert_client_access` on its four POST bodies (task
    #231). Every endpoint taking its client from a QUERY PARAMETER and every one
    addressed by a ROW id was unguarded: any member of the firm could read any
    client's GSTR-1, GSTR-3B, GSTR-9 and GSTR-2B reconciliation, and could move
    any client's return to "submitted" (CGST §37/§39).

    `gst.py` and `gst_portal.py` imported no authz at all.

THE TWO STATUS ENDPOINTS HAD NO READ AT ALL
    `PATCH /gstr1/{id}/status` fired the UPDATE and used whatever came back.
    There is no way to check a client that way — by the time the row is in hand
    the return has already moved. A read was added so the refusal happens first.
"""
import pytest
from fastapi import HTTPException

import routers.gst_workspace as gw
import routers.gst_portal as gp
import routers.gst as g

FIRM = "firm-1"
MINE, THEIRS = "client-mine", "client-theirs"
USER = {"id": "u1", "firm_id": FIRM, "role": "Executive"}


@pytest.fixture
def deny(monkeypatch):
    """Refuse one client, allow the rest — a real assignment boundary, and it
    catches a guard that resolves the wrong row's client."""
    seen = []

    def _assert(user, client_id):
        seen.append(client_id)
        if client_id == THEIRS:
            raise HTTPException(status_code=404, detail="Not found")

    def _can(user, client_id):
        seen.append(client_id)
        return client_id != THEIRS

    monkeypatch.setattr(gw, "assert_client_access", _assert)
    monkeypatch.setattr(gw, "can_access_client", _can)
    monkeypatch.setattr(gp, "assert_client_access", _assert)
    monkeypatch.setattr(g, "assert_client_access", _assert)
    return seen


# ══════════════════════════════════════════════════════════════════════════════
# gst_workspace — endpoints that NAME a client
# ══════════════════════════════════════════════════════════════════════════════

NAMED = [
    ("gst_dashboard", {}),
    ("list_returns", {"limit": 50, "offset": 0}),
    ("filing_history", {"limit": 50, "offset": 0}),
    ("get_gstr9", {"financial_year": "2025-26"}),
]


@pytest.mark.parametrize("fn,kw", NAMED, ids=[f[0] for f in NAMED])
def test_naming_a_client_you_are_not_on_is_refused(fn, kw, deny):
    with pytest.raises(HTTPException) as e:
        getattr(gw, fn)(client_id=THEIRS, current_user=USER, **kw)
    assert e.value.status_code == 404
    assert deny == [THEIRS]


@pytest.mark.parametrize("fn,kw", NAMED, ids=[f[0] for f in NAMED])
def test_the_refusal_is_not_swallowed_into_a_200(fn, kw, deny):
    """Three of these four end in a bare `except Exception: return
    api_response(False, None, "Unable to complete GST operation. Please try
    again.")`. A guard inside that block would turn a 404 into a 200 — and into
    a message telling the caller to RETRY something that can never succeed.

    `get_gstr9` is the exception: it re-raises HTTPException first, so for that
    one endpoint the placement is not load-bearing and moving the guard inside
    its `try` is an EQUIVALENT mutant, not a defect. Saying so is more useful
    than pretending a uniform rule holds — the guards all sit before the `try`
    for uniformity, but only three of them depend on it.
    """
    try:
        getattr(gw, fn)(client_id=THEIRS, current_user=USER, **kw)
    except HTTPException:
        return
    pytest.fail(f"{fn} converted the refusal into a normal return value")


@pytest.mark.parametrize("fn,kw", NAMED, ids=[f[0] for f in NAMED])
def test_naming_a_client_you_are_on_still_works(fn, kw, deny):
    out = getattr(gw, fn)(client_id=MINE, current_user=USER, **kw)
    assert out["success"] is True
    assert deny == [MINE]


# ── The four POST bodies that were already guarded — pinned, not assumed ─────

def _gstr1_body(client_id):
    return gw.SaveGSTR1Request(client_id=client_id, period="012026",
                               gstin="27AAPFU0939F1ZV", payload_json={},
                               summary_json={})


def _gstr3b_body(client_id):
    return gw.SaveGSTR3BRequest(client_id=client_id, period="012026",
                                gstin="27AAPFU0939F1ZV", payload_json={},
                                summary_json={})


def test_saving_a_gstr1_into_another_clients_books_is_refused(deny):
    """CGST Act §37."""
    with pytest.raises(HTTPException):
        gw.save_gstr1(_gstr1_body(THEIRS), current_user=USER)
    assert not [r for r in gw._MOCK_GSTR1.values() if r["client_id"] == THEIRS]


def test_saving_a_gstr3b_into_another_clients_books_is_refused(deny):
    """CGST Act §39."""
    with pytest.raises(HTTPException):
        gw.save_gstr3b(_gstr3b_body(THEIRS), current_user=USER)


def test_saving_a_gstr9_into_another_clients_books_is_refused(deny):
    """CGST Act §44 — the annual return."""
    with pytest.raises(HTTPException):
        gw.save_gstr9(gw.GSTR9In(client_id=THEIRS, financial_year="2025-26",
                                 gstin="27AAPFU0939F1ZV", payload_json={},
                                 summary_json={}), current_user=USER)


def test_uploading_gstr2b_against_another_client_is_refused(deny):
    """CGST Act §38 — the portal's inward-supply statement."""
    with pytest.raises(HTTPException):
        gw.upload_gstr2b(gw.GSTR2BUploadRequest(
            client_id=THEIRS, period="012026"), current_user=USER)


# ══════════════════════════════════════════════════════════════════════════════
# gst_workspace — endpoints addressed by a ROW id
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def rows(monkeypatch):
    for store, prefix in ((gw._MOCK_GSTR1, "G1"), (gw._MOCK_GSTR3B, "G3"),
                          (gw._MOCK_GSTR2B, "B2")):
        monkeypatch.setitem(store, f"{prefix}-MINE",
                            {"id": f"{prefix}-MINE", "client_id": MINE,
                             "status": "draft", "period": "012026"})
        monkeypatch.setitem(store, f"{prefix}-THEIRS",
                            {"id": f"{prefix}-THEIRS", "client_id": THEIRS,
                             "status": "draft", "period": "012026"})


READS = [("get_gstr1", "G1"), ("get_gstr3b", "G3"), ("get_gstr2b", "B2")]


@pytest.mark.parametrize("fn,pfx", READS, ids=[r[0] for r in READS])
def test_a_return_belonging_to_another_client_reads_as_not_found(fn, pfx, rows, deny):
    out = getattr(gw, fn)(f"{pfx}-THEIRS", current_user=USER)
    assert out["success"] is False
    assert out["error"] == "Not found"


@pytest.mark.parametrize("fn,pfx", READS, ids=[r[0] for r in READS])
def test_forbidden_and_nonexistent_are_byte_for_byte_identical(fn, pfx, rows, deny):
    """If they differed, the response itself would confirm which ids are real."""
    forbidden = getattr(gw, fn)(f"{pfx}-THEIRS", current_user=USER)
    absent = getattr(gw, fn)(f"{pfx}-NOPE", current_user=USER)
    assert forbidden == absent


@pytest.mark.parametrize("fn,pfx", READS, ids=[r[0] for r in READS])
def test_your_own_return_still_reads(fn, pfx, rows, deny):
    out = getattr(gw, fn)(f"{pfx}-MINE", current_user=USER)
    assert out["success"] is True
    assert out["data"]["id"] == f"{pfx}-MINE"


# ── Moving a return to "submitted" — the write these endpoints exist to gate ──

def _submit():
    return gw.UpdateStatusRequest(status="submitted", ca_approved=True)


STATUS = [("update_gstr1_status", gw._MOCK_GSTR1, "G1"),
          ("update_gstr3b_status", gw._MOCK_GSTR3B, "G3")]


@pytest.mark.parametrize("fn,store,pfx", STATUS, ids=[s[0] for s in STATUS])
def test_another_clients_return_cannot_be_submitted(fn, store, pfx, rows, deny,
                                                    monkeypatch):
    """These endpoints had NO read before the update — they fired it and used
    whatever came back, which is too late to refuse anything."""
    monkeypatch.setattr("core.permissions.can", lambda *a, **k: True)
    out = getattr(gw, fn)(f"{pfx}-THEIRS", _submit(), current_user=USER)
    assert out["success"] is False
    assert out["error"] == "Not found"
    assert store[f"{pfx}-THEIRS"]["status"] == "draft", "the return moved anyway"


@pytest.mark.parametrize("fn,store,pfx", STATUS, ids=[s[0] for s in STATUS])
def test_your_own_return_can_still_be_submitted(fn, store, pfx, rows, deny,
                                                monkeypatch):
    monkeypatch.setattr("core.permissions.can", lambda *a, **k: True)
    out = getattr(gw, fn)(f"{pfx}-MINE", _submit(), current_user=USER)
    assert out["success"] is True
    assert store[f"{pfx}-MINE"]["status"] == "submitted"


@pytest.mark.parametrize("fn,store,pfx", STATUS, ids=[s[0] for s in STATUS])
def test_a_missing_return_looks_the_same_as_a_forbidden_one(fn, store, pfx, rows,
                                                            deny, monkeypatch):
    monkeypatch.setattr("core.permissions.can", lambda *a, **k: True)
    forbidden = getattr(gw, fn)(f"{pfx}-THEIRS", _submit(), current_user=USER)
    absent = getattr(gw, fn)(f"{pfx}-NOPE", _submit(), current_user=USER)
    assert forbidden == absent


# ── The same write, down the REAL query path ─────────────────────────────────
# The mock store holds whole rows, so a live SELECT that stopped asking for
# client_id would still pass every test above — and can_access_client(user,
# None) reads a missing client as "firm-level" and returns True. That is the
# guard failing OPEN, and only the real path can see it.

class _Res:
    def __init__(self, data):
        self.data = data


class _FakeQ:
    def __init__(self, name, rows, log):
        self.name, self.rows, self.log = name, rows, log
        self.cols, self.op, self.filters = "*", "select", []

    def select(self, cols="*"):
        self.cols = cols
        return self

    def update(self, payload):
        self.op, self.payload = "update", payload
        return self

    def eq(self, col, val):
        self.filters.append((col, val))
        return self

    def limit(self, _n):
        return self

    def execute(self):
        self.log.append((self.name, self.op, self.cols))
        out = self.rows
        for col, val in self.filters:
            out = [r for r in out if r.get(col) == val]
        keep = None if self.cols == "*" else [c.strip() for c in self.cols.split(",")]
        return _Res([{k: v for k, v in r.items() if keep is None or k in keep}
                     for r in out])


class _FakeDb:
    def __init__(self, rows):
        self.rows, self.log = rows, []

    def table(self, name):
        return _FakeQ(name, self.rows, self.log)


@pytest.fixture
def live_db(monkeypatch):
    db = _FakeDb([
        {"id": "G1-MINE", "firm_id": FIRM, "client_id": MINE, "status": "draft"},
        {"id": "G1-THEIRS", "firm_id": FIRM, "client_id": THEIRS, "status": "draft"},
        # Another firm's return, reachable only if the firm filter comes off.
        {"id": "G1-OTHER-FIRM", "firm_id": "firm-2", "client_id": "c-x",
         "status": "draft"},
    ])
    monkeypatch.setattr(gw, "_USE_MOCK", False)
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: db)
    return db


def test_the_live_read_happens_before_the_update(live_db, deny, monkeypatch):
    monkeypatch.setattr("core.permissions.can", lambda *a, **k: True)
    out = gw.update_gstr1_status("G1-THEIRS", _submit(), current_user=USER)
    assert out["success"] is False and out["error"] == "Not found"
    assert [op for _n, op, _c in live_db.log] == ["select"], \
        "the update ran despite the refusal"
    assert deny == [THEIRS], \
        "the guard was handed no client_id — a missing one reads as firm-level"


def test_another_firms_return_is_not_reachable_on_the_live_path(live_db, deny,
                                                                monkeypatch):
    """Tenancy is not left to the client check to catch. The firm filter is on
    the same query, and the mock store has no firm filter at all — so this can
    only be tested on the live path."""
    monkeypatch.setattr("core.permissions.can", lambda *a, **k: True)
    out = gw.update_gstr1_status("G1-OTHER-FIRM", _submit(), current_user=USER)
    assert out["success"] is False and out["error"] == "Not found"
    assert [op for _n, op, _c in live_db.log] == ["select"]
    assert deny == [], "the client guard was reached for another firm's row"


def test_the_live_path_still_submits_your_own_return(live_db, deny, monkeypatch):
    monkeypatch.setattr("core.permissions.can", lambda *a, **k: True)
    out = gw.update_gstr1_status("G1-MINE", _submit(), current_user=USER)
    assert out["success"] is True
    assert "update" in [op for _n, op, _c in live_db.log]


# ══════════════════════════════════════════════════════════════════════════════
# gst_portal — read-only against the portal, but every row names a client
# ══════════════════════════════════════════════════════════════════════════════

def test_creating_a_sync_job_for_another_clients_gstin_is_refused(deny, monkeypatch):
    created = []
    monkeypatch.setattr("domain.gst.portal_service.create_sync_job",
                        lambda **k: created.append(k) or {})
    with pytest.raises(HTTPException) as e:
        gp.create_sync_job(gp.CreateSyncJobRequest(
            client_id=THEIRS, gstin="27AAPFU0939F1ZV"), current_user=USER)
    assert e.value.status_code == 404
    assert created == []


def test_saving_a_snapshot_against_another_client_is_refused(deny, monkeypatch):
    saved = []
    monkeypatch.setattr("domain.gst.portal_service.save_manual_snapshot",
                        lambda **k: saved.append(k) or {})
    with pytest.raises(HTTPException):
        gp.save_manual_snapshot(gp.ManualSnapshotRequest(
            client_id=THEIRS, gstin="27AAPFU0939F1ZV",
            snapshot_type="gstr2b", data={}), current_user=USER)
    assert saved == []


@pytest.mark.parametrize("fn,kw", [
    ("list_sync_jobs", {}),
    ("list_snapshots", {"snapshot_type": None}),
])
def test_listing_another_clients_portal_data_is_refused(fn, kw, deny, monkeypatch):
    listed = []
    for name in ("list_sync_jobs", "list_snapshots"):
        monkeypatch.setattr(f"domain.gst.portal_service.{name}",
                            lambda *a, **k: listed.append(a) or [])
    with pytest.raises(HTTPException) as e:
        getattr(gp, fn)(client_id=THEIRS, current_user=USER, **kw)
    assert e.value.status_code == 404
    assert listed == []


# ── Running a sync job is addressed by the JOB, so the job is resolved first ──

@pytest.fixture
def jobs(monkeypatch):
    store = {
        "J-MINE": {"id": "J-MINE", "firm_id": FIRM, "client_id": MINE},
        "J-THEIRS": {"id": "J-THEIRS", "firm_id": FIRM, "client_id": THEIRS},
        "J-OTHER-FIRM": {"id": "J-OTHER-FIRM", "firm_id": "firm-2",
                         "client_id": "c-x"},
    }
    monkeypatch.setattr(
        "domain.gst.portal_service.get_sync_job",
        lambda firm_id, job_id: (lambda j: j if j and j["firm_id"] == firm_id
                                 else None)(store.get(job_id)))
    return store


def test_get_sync_job_will_not_hand_over_another_firms_job(monkeypatch):
    """The `jobs` fixture below STUBS get_sync_job, so every test using it
    checks my stand-in rather than the function. This one drives the real
    thing — otherwise the firm filter inside it is asserted by nothing."""
    import domain.gst.portal_service as ps
    monkeypatch.setitem(ps._MOCK_SYNC_JOBS, "J-OURS",
                        {"id": "J-OURS", "firm_id": FIRM, "client_id": MINE})
    monkeypatch.setitem(ps._MOCK_SYNC_JOBS, "J-ALIEN",
                        {"id": "J-ALIEN", "firm_id": "firm-2", "client_id": "c-x"})
    assert ps.get_sync_job(FIRM, "J-OURS")["client_id"] == MINE
    assert ps.get_sync_job(FIRM, "J-ALIEN") is None
    assert ps.get_sync_job(FIRM, "J-NOPE") is None


def test_running_another_clients_sync_job_is_refused(jobs, deny, monkeypatch):
    """Running it WRITES snapshots into that client's record, so resolving the
    job's client afterwards — which is all run_sync_job itself could do — is
    too late."""
    ran = []
    monkeypatch.setattr("domain.gst.portal_service.run_sync_job",
                        lambda *a, **k: ran.append(a) or {})
    with pytest.raises(HTTPException) as e:
        gp.run_sync_job("J-THEIRS", current_user=USER)
    assert e.value.status_code == 404
    assert ran == [], "the sync ran despite the refusal"


def test_running_a_job_from_another_firm_is_refused_before_the_client_check(jobs, deny):
    with pytest.raises(HTTPException) as e:
        gp.run_sync_job("J-OTHER-FIRM", current_user=USER)
    assert e.value.status_code == 404
    assert deny == [], "the client guard was reached for another firm's job"


def test_an_unknown_job_and_a_forbidden_one_are_the_same_404(jobs, deny):
    with pytest.raises(HTTPException) as missing:
        gp.run_sync_job("J-NOPE", current_user=USER)
    with pytest.raises(HTTPException) as hidden:
        gp.run_sync_job("J-THEIRS", current_user=USER)
    assert missing.value.status_code == hidden.value.status_code == 404


def test_running_your_own_job_still_works(jobs, deny, monkeypatch):
    monkeypatch.setattr("domain.gst.portal_service.run_sync_job",
                        lambda *a, **k: {"status": "completed",
                                         "snapshots_created": 1})
    monkeypatch.setattr(gp.timeline_service, "log", lambda **k: None)
    out = gp.run_sync_job("J-MINE", current_user=USER)
    assert out["success"] is True


# ══════════════════════════════════════════════════════════════════════════════
# gst.py — from-books reads the ledger; everything else is a pure function
# ══════════════════════════════════════════════════════════════════════════════

def _from_books(client_id):
    return g.FromBooksRequest(client_id=client_id, period="012026")


@pytest.mark.parametrize("fn,service", [
    ("gstr3b_from_books_endpoint", "gstr3b_from_books"),
    ("gstr1_from_books_endpoint", "gstr1_from_books"),
])
def test_building_a_return_from_another_clients_books_is_refused(fn, service, deny,
                                                                 monkeypatch):
    """These read a client's posted invoices, credit notes and GL control
    accounts — and resolve that client's own GSTIN on the way."""
    reached = []
    monkeypatch.setattr("core.supabase_client.get_supabase",
                        lambda: reached.append("db") or object())
    monkeypatch.setattr(g, "_client_gstin",
                        lambda *a, **k: reached.append("gstin") or "27AAPFU0939F1ZV")
    monkeypatch.setattr(g.gst_return_service, service,
                        lambda *a, **k: reached.append(service) or {})
    with pytest.raises(HTTPException) as e:
        getattr(g, fn)(_from_books(THEIRS), current_user=USER)
    assert e.value.status_code == 404
    assert reached == [], f"{fn} read the ledger despite the refusal"


@pytest.mark.parametrize("fn,service", [
    ("gstr3b_from_books_endpoint", "gstr3b_from_books"),
    ("gstr1_from_books_endpoint", "gstr1_from_books"),
])
def test_building_from_your_own_books_still_works(fn, service, deny, monkeypatch):
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: object())
    monkeypatch.setattr(g, "_client_gstin", lambda *a, **k: "27AAPFU0939F1ZV")
    monkeypatch.setattr(g.gst_return_service, service, lambda *a, **k: {"ok": True})
    out = getattr(g, fn)(_from_books(MINE), current_user=USER)
    assert out["success"] is True


def test_the_pure_validators_are_not_client_scoped(deny):
    """`/validate/gstr1` runs the CGST §37 validators over a payload in the
    request body. Its model has no client_id and it reads nothing stored.
    Over-guarding is a real failure mode — this fails if somebody "fixes" it."""
    out = g.validate_gstr1_endpoint(
        g.ValidateGSTR1Request(gstin="27AAPFU0939F1ZV", period="012026",
                               invoices=[]), current_user=USER)
    assert out["success"] is True
    assert deny == [], "a pure validator asked about a client"
