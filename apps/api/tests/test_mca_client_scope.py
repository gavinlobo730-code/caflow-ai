"""
Client-assignment scope on the MCA workspace router.

The third router in a row with the same shape: `assert_client_access` on the
three POST bodies and nothing on the endpoints that take their client from a
QUERY PARAMETER or address a row by id. Any member of the firm could read any
client's company master, its directors and DINs, and every MCA filing with its
SRN — and could write KYC status onto a director or mark a filing FILED.

TWO REFUSAL SHAPES, SAME REASONING AS TDS AND GST
    An endpoint that NAMES a client gets a 404. An endpoint addressed by a row
    id reports a missing row as a 200 carrying {"success": false, "error":
    "... not found"}, so a 404 refusal there would make the STATUS CODE the
    oracle for which ids are real. Those go through `_load_or_none`.

BOTH PATCH ENDPOINTS HAD NO READ AT ALL
    `PATCH /directors/{id}` and `PATCH /filings/{id}/status` fired the UPDATE and
    used whatever came back. By then the director's KYC status or the filing's
    MCA21 SRN has already been written, so there is nothing left to refuse.
"""
import pytest
from fastapi import HTTPException

import routers.mca_workspace as mw

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

    monkeypatch.setattr(mw, "assert_client_access", _assert)
    monkeypatch.setattr(mw, "can_access_client", _can)
    return seen


# ══════════════════════════════════════════════════════════════════════════════
# Endpoints that NAME a client
# ══════════════════════════════════════════════════════════════════════════════

NAMED = [
    ("list_companies", {}),
    ("list_directors", {}),
    ("list_filings", {"company_id": None, "form_type": None, "status": None,
                      "limit": 50, "offset": 0}),
    ("filing_history", {"limit": 50, "offset": 0}),
    ("mca_calendar", {"agm_date": "2026-09-30"}),
]


@pytest.mark.parametrize("fn,kw", NAMED, ids=[f[0] for f in NAMED])
def test_naming_a_client_you_are_not_on_is_refused(fn, kw, deny):
    with pytest.raises(HTTPException) as e:
        getattr(mw, fn)(client_id=THEIRS, current_user=USER, **kw)
    assert e.value.status_code == 404
    assert deny == [THEIRS]


@pytest.mark.parametrize("fn,kw", NAMED, ids=[f[0] for f in NAMED])
def test_the_refusal_is_not_swallowed_into_a_200(fn, kw, deny):
    """Every handler here ends in a bare `except Exception: return
    api_response(False, None, "Unable to complete MCA operation. Please try
    again.")`. A guard inside that block would turn a 404 into a 200 — and into
    a message telling the caller to RETRY something that can never succeed.
    This is why the guards sit before the `try`, and this fails if one moves
    back inside."""
    try:
        getattr(mw, fn)(client_id=THEIRS, current_user=USER, **kw)
    except HTTPException:
        return
    pytest.fail(f"{fn} converted the refusal into a normal return value")


@pytest.mark.parametrize("fn,kw", NAMED, ids=[f[0] for f in NAMED])
def test_naming_a_client_you_are_on_still_works(fn, kw, deny):
    out = getattr(mw, fn)(client_id=MINE, current_user=USER, **kw)
    assert out["success"] is True
    assert deny == [MINE]


def test_the_calendar_is_guarded_even_though_it_reads_nothing(deny):
    """The arithmetic needs no database — but the caller is asking for a named
    client's statutory calendar (Companies Act §92/§137/§139) and the id is
    echoed through the response. Guarded on the same reasoning as the TDS
    /compute pair: the field is required by the signature, so an exemption
    would be true today and silently false the first time somebody reads
    stored data here."""
    with pytest.raises(HTTPException):
        mw.mca_calendar(client_id=THEIRS, agm_date="2026-09-30", current_user=USER)
    out = mw.mca_calendar(client_id=MINE, agm_date="2026-09-30", current_user=USER)
    assert [e["form_type"] for e in out["data"]["calendar"]] == \
        ["ADT-1", "AOC-4", "MGT-7"]


# ── The three POST bodies that were already guarded — pinned, not assumed ────

def test_registering_a_company_under_another_client_is_refused(deny):
    with pytest.raises(HTTPException):
        mw.create_company(mw.CreateCompanyRequest(
            client_id=THEIRS, cin="U72900MH2020PTC123456", company_name="X",
            company_type="PVT"), current_user=USER)


def test_adding_a_director_under_another_client_is_refused(deny):
    """A DIN, PAN and KYC record for a real person. Companies Act 2013 §165."""
    with pytest.raises(HTTPException):
        mw.create_director(mw.CreateDirectorRequest(
            client_id=THEIRS, din="12345678", name="A Director",
            designation="Director", date_of_appointment="2025-04-01"),
            current_user=USER)


def test_creating_a_filing_under_another_client_is_refused(deny):
    with pytest.raises(HTTPException):
        mw.create_filing(mw.CreateFilingRequest(
            client_id=THEIRS, form_type="AOC-4", financial_year="2025-26",
            due_date="2026-10-30"), current_user=USER)


# ══════════════════════════════════════════════════════════════════════════════
# Endpoints addressed by a ROW id
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def rows(monkeypatch):
    for store, pfx in ((mw._MOCK_COMPANIES, "CO"), (mw._MOCK_DIRECTORS, "DIR"),
                       (mw._MOCK_FILINGS, "FIL")):
        monkeypatch.setitem(store, f"{pfx}-MINE",
                            {"id": f"{pfx}-MINE", "client_id": MINE,
                             "status": "not_started", "form_type": "AOC-4",
                             "financial_year": "2025-26"})
        monkeypatch.setitem(store, f"{pfx}-THEIRS",
                            {"id": f"{pfx}-THEIRS", "client_id": THEIRS,
                             "status": "not_started", "form_type": "AOC-4",
                             "financial_year": "2025-26"})


READS = [("get_company", "CO", "Company not found"),
         ("get_filing", "FIL", "Filing not found")]


@pytest.mark.parametrize("fn,pfx,msg", READS, ids=[r[0] for r in READS])
def test_a_row_belonging_to_another_client_reads_as_not_found(fn, pfx, msg, rows, deny):
    out = getattr(mw, fn)(f"{pfx}-THEIRS", current_user=USER)
    assert out["success"] is False
    assert out["error"] == msg


@pytest.mark.parametrize("fn,pfx,msg", READS, ids=[r[0] for r in READS])
def test_forbidden_and_nonexistent_are_byte_for_byte_identical(fn, pfx, msg, rows, deny):
    """If they differed, the response itself would confirm which ids are real."""
    forbidden = getattr(mw, fn)(f"{pfx}-THEIRS", current_user=USER)
    absent = getattr(mw, fn)(f"{pfx}-NOPE", current_user=USER)
    assert forbidden == absent


@pytest.mark.parametrize("fn,pfx,msg", READS, ids=[r[0] for r in READS])
def test_your_own_row_still_reads(fn, pfx, msg, rows, deny):
    out = getattr(mw, fn)(f"{pfx}-MINE", current_user=USER)
    assert out["success"] is True
    assert out["data"]["id"] == f"{pfx}-MINE"


def test_the_directors_ride_along_on_the_companys_own_check(rows, deny, monkeypatch):
    """get_company returns the company AND its directors. The directors are the
    same client by construction, so one check covers both — but only if the
    company check actually runs before they are gathered."""
    monkeypatch.setitem(mw._MOCK_DIRECTORS, "D-IN-CO",
                        {"id": "D-IN-CO", "client_id": MINE, "company_id": "CO-MINE"})
    out = mw.get_company("CO-MINE", current_user=USER)
    assert [d["id"] for d in out["data"]["directors"]] == ["D-IN-CO"]


# ── The two writes that had no read at all ───────────────────────────────────

def test_another_clients_director_cannot_be_updated(rows, deny):
    """KYC status and cessation dates on a real person's DIN."""
    out = mw.update_director("DIR-THEIRS",
                             mw.UpdateDirectorRequest(kyc_status="verified"),
                             current_user=USER)
    assert out["success"] is False
    assert out["error"] == "Director not found"
    assert "kyc_status" not in mw._MOCK_DIRECTORS["DIR-THEIRS"], \
        "the KYC status was written anyway"


def test_your_own_director_can_still_be_updated(rows, deny):
    out = mw.update_director("DIR-MINE",
                             mw.UpdateDirectorRequest(kyc_status="verified"),
                             current_user=USER)
    assert out["success"] is True
    assert mw._MOCK_DIRECTORS["DIR-MINE"]["kyc_status"] == "verified"


def _filed():
    return mw.UpdateFilingStatusRequest(status="filed", ca_approved=True,
                                        srn="R99999999")


def test_another_clients_filing_cannot_be_marked_filed(rows, deny, monkeypatch):
    """The SRN is MCA21's proof-of-filing receipt. Companies Act §92/§137/§139."""
    monkeypatch.setattr("core.permissions.can", lambda *a, **k: True)
    out = mw.update_filing_status("FIL-THEIRS", _filed(), current_user=USER)
    assert out["success"] is False
    assert out["error"] == "Filing not found"
    assert mw._MOCK_FILINGS["FIL-THEIRS"]["status"] == "not_started"
    assert "srn" not in mw._MOCK_FILINGS["FIL-THEIRS"], "the SRN was written anyway"


def test_your_own_filing_can_still_be_marked_filed(rows, deny, monkeypatch):
    monkeypatch.setattr("core.permissions.can", lambda *a, **k: True)
    out = mw.update_filing_status("FIL-MINE", _filed(), current_user=USER)
    assert out["success"] is True
    assert mw._MOCK_FILINGS["FIL-MINE"]["srn"] == "R99999999"


def test_a_missing_filing_looks_the_same_as_a_forbidden_one(rows, deny, monkeypatch):
    monkeypatch.setattr("core.permissions.can", lambda *a, **k: True)
    forbidden = mw.update_filing_status("FIL-THEIRS", _filed(), current_user=USER)
    absent = mw.update_filing_status("FIL-NOPE", _filed(), current_user=USER)
    assert forbidden == absent


def test_the_complete_shortcut_inherits_the_guard(rows, deny, monkeypatch):
    """`PUT /filings/{id}/complete` is a one-line delegation to
    update_filing_status. That is why the sweep FOLLOWs this module — but a
    delegation that stopped delegating would be a hole, so it is checked
    directly rather than trusted."""
    monkeypatch.setattr("core.permissions.can", lambda *a, **k: True)
    out = mw.complete_filing("FIL-THEIRS", _filed(), current_user=USER)
    assert out["success"] is False
    assert out["error"] == "Filing not found"
    assert mw._MOCK_FILINGS["FIL-THEIRS"]["status"] == "not_started"


# ── The live query path, where the firm filter actually exists ───────────────
# The mock stores have no firm filter at all, so tenancy on these row lookups
# can only be tested against the real query.

class _Res:
    def __init__(self, data):
        self.data = data


class _FakeQ:
    def __init__(self, name, rows, log):
        self.name, self.rows, self.log = name, rows, log
        self.op, self.filters = "select", []

    def select(self, *_a, **_k):
        return self

    def update(self, payload):
        self.op, self.payload = "update", payload
        return self

    def eq(self, col, val):
        self.filters.append((col, val))
        return self

    def execute(self):
        self.log.append((self.name, self.op))
        out = self.rows
        for col, val in self.filters:
            out = [r for r in out if r.get(col) == val]
        return _Res(list(out))


class _FakeDb:
    def __init__(self, rows):
        self.rows, self.log = rows, []

    def table(self, name):
        return _FakeQ(name, self.rows, self.log)


@pytest.fixture
def live_db(monkeypatch):
    db = _FakeDb([
        {"id": "FIL-MINE", "firm_id": FIRM, "client_id": MINE, "status": "not_started"},
        {"id": "FIL-THEIRS", "firm_id": FIRM, "client_id": THEIRS, "status": "not_started"},
        # Another firm's filing, reachable only if the firm filter comes off.
        {"id": "FIL-ALIEN", "firm_id": "firm-2", "client_id": "c-x",
         "status": "not_started"},
    ])
    monkeypatch.setattr(mw, "_USE_MOCK", False)
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: db)
    return db


def test_the_live_read_happens_before_the_update(live_db, deny, monkeypatch):
    monkeypatch.setattr("core.permissions.can", lambda *a, **k: True)
    out = mw.update_filing_status("FIL-THEIRS", _filed(), current_user=USER)
    assert out["success"] is False and out["error"] == "Filing not found"
    assert [op for _n, op in live_db.log] == ["select"], \
        "the update ran despite the refusal"
    assert deny == [THEIRS], \
        "the guard was handed no client_id — a missing one reads as firm-level"


def test_another_firms_filing_is_not_reachable_on_the_live_path(live_db, deny,
                                                                monkeypatch):
    """Tenancy is not left to the client check to catch — the firm filter is on
    the same query. The mock store has none, so only the live path shows this."""
    monkeypatch.setattr("core.permissions.can", lambda *a, **k: True)
    out = mw.update_filing_status("FIL-ALIEN", _filed(), current_user=USER)
    assert out["success"] is False and out["error"] == "Filing not found"
    assert [op for _n, op in live_db.log] == ["select"]
    assert deny == [], "the client guard was reached for another firm's row"


def test_the_live_path_still_files_your_own(live_db, deny, monkeypatch):
    monkeypatch.setattr("core.permissions.can", lambda *a, **k: True)
    out = mw.update_filing_status("FIL-MINE", _filed(), current_user=USER)
    assert out["success"] is True
    assert "update" in [op for _n, op in live_db.log]
