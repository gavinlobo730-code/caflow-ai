"""
Client-assignment scope on the TWO TDS routers.

`tds_workspace` (12 endpoints, `/api/tds-workspace`) and `tds` (8 endpoints,
`/api/tds`) are one feature and two registrations — and `/api/tds` is a string
PREFIX of `/api/tds-workspace`, which is why the sweep now matches the longest
prefix rather than the first.

WHAT WAS THERE
    `tds_workspace` imported `core.authz` and called `assert_client_access` four
    times — on the four POST bodies. Every endpoint taking its client from a
    QUERY PARAMETER, and every one addressed by a ROW id, was unguarded. Any
    member of the firm could read any client's challans, filed returns, Form
    16/16A certificates and Form 26AS reconciliation, and could mark any
    client's statutory return FILED with a PRN of their choosing.

    `tds.py` imported no authz at all.

TWO REFUSAL SHAPES, BECAUSE THIS ROUTER REPORTS "NOT FOUND" TWO WAYS
    An endpoint that NAMES a client gets the 404 every other audited router
    gives. An endpoint addressed by a row id reports a missing row as a 200
    carrying {"success": false, "error": "Not found"} — so a 404 refusal there
    would make the STATUS CODE the oracle: 404 means the id is real and belongs
    to someone else, 200 means it does not exist. Those go through
    `_visible_or_none` and come back down the router's own not-found path.

THE SWALLOWING TRY
    Every handler in `tds_workspace` ends in a bare
    `except Exception: return api_response(False, None, str(e))`. A guard placed
    inside that block would have its 404 caught and returned as a 200. The
    query-param guards therefore sit BEFORE the `try`, and there is a test that
    fails if one moves back inside.
"""
import pytest
from fastapi import HTTPException

import routers.tds_workspace as tw
import routers.tds as td

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

    monkeypatch.setattr(tw, "assert_client_access", _assert)
    monkeypatch.setattr(tw, "can_access_client", _can)
    monkeypatch.setattr(td, "assert_client_access", _assert)
    return seen


# ══════════════════════════════════════════════════════════════════════════════
# tds_workspace — endpoints that NAME a client
# ══════════════════════════════════════════════════════════════════════════════

NAMED = [
    ("tds_dashboard", {}),
    ("list_deductions", {"quarter": None, "limit": 50, "offset": 0}),
    ("list_challans", {"from_date": None, "to_date": None, "limit": 50, "offset": 0}),
    ("list_returns", {"limit": 50, "offset": 0}),
    ("list_certificates", {"limit": 50, "offset": 0}),
]


@pytest.mark.parametrize("fn,kw", NAMED, ids=[f[0] for f in NAMED])
def test_naming_a_client_you_are_not_on_is_refused(fn, kw, deny):
    with pytest.raises(HTTPException) as e:
        getattr(tw, fn)(client_id=THEIRS, current_user=USER, **kw)
    assert e.value.status_code == 404
    assert deny == [THEIRS]


@pytest.mark.parametrize("fn,kw", NAMED, ids=[f[0] for f in NAMED])
def test_the_refusal_is_not_swallowed_into_a_200(fn, kw, deny):
    """Every handler here ends in `except Exception: return api_response(False,
    ...)`. A guard inside that block would turn a 404 into a 200 body nobody
    checks the status of. This test is the reason the guards sit before the
    `try` — it fails the moment one moves back inside.
    """
    try:
        getattr(tw, fn)(client_id=THEIRS, current_user=USER, **kw)
    except HTTPException:
        return
    pytest.fail(f"{fn} converted the refusal into a normal return value")


@pytest.mark.parametrize("fn,kw", NAMED, ids=[f[0] for f in NAMED])
def test_naming_a_client_you_are_on_still_works(fn, kw, deny):
    out = getattr(tw, fn)(client_id=MINE, current_user=USER, **kw)
    assert out["success"] is True
    assert deny == [MINE]


# ── The four POST bodies that were already guarded — pinned, not assumed ─────

def test_creating_a_challan_in_another_clients_books_is_refused(deny):
    with pytest.raises(HTTPException):
        tw.create_challan(tw.CreateChallanRequest(
            client_id=THEIRS, bsr_code="0510308", challan_date="2026-01-05",
            amount_paise=100000, challan_no="12345", section="194A",
            financial_year="2025-26", quarter="Q3"), current_user=USER)
    assert THEIRS not in tw._MOCK_CHALLANS


def test_creating_a_return_in_another_clients_books_is_refused(deny):
    with pytest.raises(HTTPException):
        tw.create_return(tw.CreateReturnRequest(
            client_id=THEIRS, return_type="26Q", quarter="Q3",
            financial_year="2025-26"), current_user=USER)


def test_creating_a_certificate_for_another_clients_deductee_is_refused(deny):
    """Form 16A carries a deductee's name and PAN. IT Act §203."""
    with pytest.raises(HTTPException):
        tw.create_certificate(tw.CreateCertificateRequest(
            client_id=THEIRS, deductee_pan="ABCDE1234F", deductee_name="X",
            financial_year="2025-26", certificate_type="Form 16A",
            tds_amount_paise=1000, section="194A"), current_user=USER)


def test_uploading_form26as_against_another_client_is_refused(deny):
    with pytest.raises(HTTPException):
        tw.upload_form26as(tw.Form26ASUploadRequest(
            client_id=THEIRS, financial_year="2025-26"), current_user=USER)


# ══════════════════════════════════════════════════════════════════════════════
# tds_workspace — endpoints addressed by a ROW id
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def rows(monkeypatch):
    """Seeded mock stores. These handlers read the module-level dicts when
    SUPABASE_URL is unset, which is the path the test suite runs on."""
    monkeypatch.setitem(tw._MOCK_CHALLANS, "CH-MINE",
                        {"id": "CH-MINE", "client_id": MINE, "total_paise": 100})
    monkeypatch.setitem(tw._MOCK_CHALLANS, "CH-THEIRS",
                        {"id": "CH-THEIRS", "client_id": THEIRS, "total_paise": 999})
    monkeypatch.setitem(tw._MOCK_FORM26AS, "F-MINE",
                        {"id": "F-MINE", "client_id": MINE})
    monkeypatch.setitem(tw._MOCK_FORM26AS, "F-THEIRS",
                        {"id": "F-THEIRS", "client_id": THEIRS})
    monkeypatch.setitem(tw._MOCK_RETURNS, "R-MINE",
                        {"id": "R-MINE", "client_id": MINE, "status": "prepared"})
    monkeypatch.setitem(tw._MOCK_RETURNS, "R-THEIRS",
                        {"id": "R-THEIRS", "client_id": THEIRS, "status": "prepared"})


@pytest.mark.parametrize("fn,rid", [
    ("get_challan", "CH-THEIRS"),
    ("get_form26as", "F-THEIRS"),
])
def test_a_row_belonging_to_another_client_reads_as_not_found(fn, rid, rows, deny):
    out = getattr(tw, fn)(rid, current_user=USER)
    assert out["success"] is False
    assert out["error"] == "Not found"


@pytest.mark.parametrize("fn,mine,missing", [
    ("get_challan", "CH-MINE", "CH-NOPE"),
    ("get_form26as", "F-MINE", "F-NOPE"),
])
def test_forbidden_and_nonexistent_are_byte_for_byte_identical(fn, mine, missing,
                                                               rows, deny):
    """If they differed, the response itself would confirm which ids are real."""
    forbidden = getattr(tw, fn)(mine.replace("MINE", "THEIRS"), current_user=USER)
    absent = getattr(tw, fn)(missing, current_user=USER)
    assert forbidden == absent


@pytest.mark.parametrize("fn,rid", [
    ("get_challan", "CH-MINE"),
    ("get_form26as", "F-MINE"),
])
def test_your_own_row_still_reads(fn, rid, rows, deny):
    out = getattr(tw, fn)(rid, current_user=USER)
    assert out["success"] is True
    assert out["data"]["id"] == rid


# ── Marking a return FILED is the write that matters most ────────────────────

def _file_it(return_id):
    return tw.UpdateReturnStatusRequest(
        status="filed", ca_approved=True, prn="PRN-999", ack_number="ACK-1")


def test_another_clients_return_cannot_be_marked_filed(rows, deny, monkeypatch):
    """A PRN is the government's proof-of-filing record. Writing one onto
    another client's return is the worst thing this router can do."""
    monkeypatch.setattr("core.permissions.can", lambda *a, **k: True)
    out = tw.update_return_status("R-THEIRS", _file_it("R-THEIRS"), current_user=USER)
    assert out["success"] is False
    assert out["error"] == "Not found"
    assert tw._MOCK_RETURNS["R-THEIRS"].get("prn") is None, "the PRN was written anyway"
    assert tw._MOCK_RETURNS["R-THEIRS"]["status"] == "prepared"


def test_your_own_return_can_still_be_marked_filed(rows, deny, monkeypatch):
    monkeypatch.setattr("core.permissions.can", lambda *a, **k: True)
    out = tw.update_return_status("R-MINE", _file_it("R-MINE"), current_user=USER)
    assert out["success"] is True
    assert tw._MOCK_RETURNS["R-MINE"]["prn"] == "PRN-999"


def test_a_return_that_does_not_exist_looks_the_same_as_a_forbidden_one(rows, deny,
                                                                        monkeypatch):
    monkeypatch.setattr("core.permissions.can", lambda *a, **k: True)
    forbidden = tw.update_return_status("R-THEIRS", _file_it("x"), current_user=USER)
    absent = tw.update_return_status("R-NOPE", _file_it("x"), current_user=USER)
    assert forbidden == absent


# ── The same write, driven down the REAL query path ──────────────────────────
# The mock store holds whole rows, so it would still carry a client_id even if
# the live SELECT stopped asking for one — and `can_access_client(user, None)`
# reads a missing client as "firm-level resource" and returns True. That is the
# guard failing OPEN, and only the real path can see it.

class _Res:
    def __init__(self, data):
        self.data = data


class _FakeQ:
    def __init__(self, name, rows, log):
        self.name, self.rows, self.log = name, rows, log
        self.cols, self.op, self.filters = "", "select", []

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
        return _Res([{k: v for k, v in r.items()
                      if self.cols == "*" or k in
                      [c.strip() for c in self.cols.split(",")]} for r in out])


class _FakeDb:
    def __init__(self, rows):
        self.rows, self.log = rows, []

    def table(self, name):
        return _FakeQ(name, self.rows, self.log)


@pytest.fixture
def live_db(monkeypatch):
    db = _FakeDb([
        {"id": "R-MINE", "firm_id": FIRM, "client_id": MINE, "status": "prepared"},
        {"id": "R-THEIRS", "firm_id": FIRM, "client_id": THEIRS, "status": "prepared"},
    ])
    monkeypatch.setattr(tw, "_USE_MOCK", False)
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: db)
    return db


def test_the_live_query_asks_for_the_column_the_guard_needs(live_db, deny, monkeypatch):
    monkeypatch.setattr("core.permissions.can", lambda *a, **k: True)
    out = tw.update_return_status("R-THEIRS", _file_it("x"), current_user=USER)
    assert out["success"] is False and out["error"] == "Not found"
    assert [op for _n, op, _c in live_db.log] == ["select"], \
        "the update ran despite the refusal"
    assert deny == [THEIRS], \
        "the guard was handed no client_id — a missing one reads as firm-level"


def test_the_live_path_still_files_your_own_return(live_db, deny, monkeypatch):
    monkeypatch.setattr("core.permissions.can", lambda *a, **k: True)
    out = tw.update_return_status("R-MINE", _file_it("x"), current_user=USER)
    assert out["success"] is True
    assert "update" in [op for _n, op, _c in live_db.log]


# ══════════════════════════════════════════════════════════════════════════════
# routers/tds.py — the second router, which imported no authz at all
# ══════════════════════════════════════════════════════════════════════════════

def test_another_clients_filed_returns_are_refused(deny, monkeypatch):
    reached = []
    monkeypatch.setattr(td.tds_repo, "get_returns",
                        lambda **k: reached.append(k) or [])
    with pytest.raises(HTTPException) as e:
        td.get_tds_returns(THEIRS, user=USER)
    assert e.value.status_code == 404
    assert reached == []


def test_another_clients_deductions_are_refused(deny, monkeypatch):
    reached = []
    monkeypatch.setattr(td.tds_repo, "get_deductions",
                        lambda **k: reached.append(k) or [])
    with pytest.raises(HTTPException) as e:
        td.get_tds_deductions(THEIRS, financial_year=None, quarter=None, user=USER)
    assert e.value.status_code == 404
    assert reached == []


def test_your_own_deductions_still_load(deny, monkeypatch):
    monkeypatch.setattr(td.tds_repo, "get_deductions", lambda **k: [{"id": "d1"}])
    out = td.get_tds_deductions(MINE, financial_year=None, quarter=None, user=USER)
    assert out["success"] is True and out["data"] == [{"id": "d1"}]


def _from_books(client_id):
    return td.FromBooksRequest(
        client_id=client_id, financial_year="2025-26", quarter="Q3",
        tan="MUMT12345A", deductor_name="D", deductor_pan="ABCDE1234F",
        deductor_address="Addr")


@pytest.mark.parametrize("fn,service", [
    ("compute_26q_from_books", "tds_26q_from_books"),
    ("compute_24q_from_books", "tds_24q_from_books"),
])
def test_building_a_return_from_another_clients_books_is_refused(fn, service,
                                                                 deny, monkeypatch):
    """These read a client's posted purchase bills / finalized payroll runs
    straight out of the ledger."""
    reached = []
    monkeypatch.setattr(f"services.tds_return_service.{service}",
                        lambda *a, **k: reached.append(service) or {})
    with pytest.raises(HTTPException) as e:
        getattr(td, fn)(_from_books(THEIRS), user=USER)
    assert e.value.status_code == 404
    assert reached == [], f"{fn} read the ledger despite the refusal"


def _compute_req(client_id, cls):
    return cls(client_id=client_id, tan="MUMT12345A", deductor_name="D",
               deductor_pan="ABCDE1234F", deductor_address="Addr",
               financial_year="2025-26", quarter="Q3", deductees=[], challans=[])


@pytest.mark.parametrize("fn,cls", [
    ("compute_26q", "Compute26QRequest"),
    ("compute_24q", "Compute24QRequest"),
])
def test_the_compute_endpoints_are_guarded_on_the_client_they_claim(fn, cls, deny):
    """These are pure functions over caller-supplied rows TODAY — they never
    read req.client_id. They are guarded anyway, because the field is required
    by the request model and an exemption would go silently false the first
    time somebody starts using it.
    """
    with pytest.raises(HTTPException) as e:
        getattr(td, fn)(_compute_req(THEIRS, getattr(td, cls)), user=USER)
    assert e.value.status_code == 404


@pytest.mark.parametrize("fn,cls", [
    ("compute_26q", "Compute26QRequest"),
    ("compute_24q", "Compute24QRequest"),
])
def test_the_compute_endpoints_still_compute_for_your_own_client(fn, cls, deny):
    out = getattr(td, fn)(_compute_req(MINE, getattr(td, cls)), user=USER)
    assert out["success"] is True


def test_the_rate_table_is_not_client_scoped(deny):
    """Over-guarding is a real failure mode. `/sections` is the statutory rate
    table from the IT Act — identical for every firm and every client, and
    exempt for that reason. This fails if somebody "fixes" it."""
    out = td.list_tds_sections(fy="2025-26", user=USER)
    assert out["success"] is True
    assert out["data"]["sections"]
    assert deny == [], "the rate table asked about a client"
