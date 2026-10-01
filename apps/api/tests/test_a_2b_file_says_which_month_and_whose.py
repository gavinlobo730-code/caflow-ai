"""gst-09 — a GSTR-2B says which month it is for and whose it is, and the upload
believes the FILE.

WHAT WAS WRONG
    The client GST tab asked the CA to type the period (MMYYYY) and to paste a
    multi-megabyte JSON into a textarea. The file already says both things that
    matter — `data.rtnprd` is the month and `data.gstin` the recipient's
    registration — and the parser returned both and used neither:

      * a typed month that disagreed with the file was WARNED about in
        `problems` and the documents were written under the TYPED month anyway:
        April's documents replaced May's reconciliation and were matched against
        May's bills, so the month's Rule 36(4) working (and with it the credit
        §16(2)(aa) allows) was computed from another month's file;
      * the file's GSTIN was never compared with anything, so a file downloaded
        for another client was reconciled against this client's bills and
        reported, bill by bill, as the supplier not having filed.

    `domain/gst/gstr2b_intake.assess` is the rule. The router asks it twice —
    `POST /gstr2b/inspect` (writes nothing; so the screen can say it beside the
    file's name) and `POST /gstr2b/upload` (which acts on it) — and the service
    that WRITES asks the period half again.

THE SHAPE OF THESE TESTS
    Every refusal test is preceded by a premise test that the SAME file, when it
    is right, reconciles and persists. Otherwise "nothing was written" passes on
    an endpoint that writes nothing for any file.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import routers.gst_workspace as gw
from domain.gst import gstr2b_intake
from domain.gst.gstr2b import parse_gstr2b
from domain.gst.registrations import Registration

FIRM, CLIENT = "firm-1", "client-1"
PRIMARY = "29AAACX1234C1ZP"
SECOND = "27AAACX1234C1ZQ"
STRANGER = "07AAAPL1234C1ZX"
SUPPLIER = "29AAAAA1111A1Z5"
USER = {"id": "u1", "firm_id": FIRM, "role": "Manager"}


def _raw(gstin=PRIMARY, rtnprd="042025", docs=True):
    data = {"gendt": "14-05-2025", "docdata": {"b2b": [
        {"ctin": SUPPLIER, "trdnm": "Acme Supplies", "supfildt": "10-05-2025",
         "inv": [{"inum": "INV-001", "dt": "24-04-2025", "val": 1180.0, "itcavl": "Y",
                  "items": [{"num": 1, "rt": 18.0, "txval": 1000.0,
                             "cgst": 90.0, "sgst": 90.0, "igst": 0}]}]}]
        if docs else []}}
    if gstin is not None:
        data["gstin"] = gstin
    if rtnprd is not None:
        data["rtnprd"] = rtnprd
    return {"data": data}


def _reg(gstin, primary=False):
    return Registration(gstin=gstin, state_code=gstin[:2], is_primary=primary)


# ═════════════════════════════════════════════════════════════════════════════
# THE RULE — domain/gst/gstr2b_intake.assess, pure
# ═════════════════════════════════════════════════════════════════════════════

def test_the_month_is_read_off_the_file_when_nothing_was_typed():
    got = gstr2b_intake.assess(parse_gstr2b(_raw()), registrations=[_reg(PRIMARY, True)])
    assert got.can_reconcile and got.period == "042025"
    assert got.period_source == gstr2b_intake.FROM_FILE
    assert got.refusals == ()


def test_a_typed_month_that_agrees_is_only_a_check():
    got = gstr2b_intake.assess(parse_gstr2b(_raw()), typed_period="042025",
                               registrations=[_reg(PRIMARY, True)])
    assert got.can_reconcile and got.period == "042025"
    assert got.period_source == gstr2b_intake.FROM_FILE


def test_a_typed_month_that_disagrees_refuses_the_file_and_picks_neither():
    """The defect: the typed month used to WIN and a sentence apologised."""
    got = gstr2b_intake.assess(parse_gstr2b(_raw()), typed_period="052025",
                               registrations=[_reg(PRIMARY, True)])
    assert not got.can_reconcile
    assert got.period is None, "a refused file resolves NO month — neither one"
    (why,) = got.refusals
    assert "042025" in why and "052025" in why
    assert "April 2025" in why and "May 2025" in why
    assert "replace" in why


def test_a_file_naming_no_month_falls_back_to_the_typed_one_and_says_so():
    got = gstr2b_intake.assess(parse_gstr2b(_raw(rtnprd=None)), typed_period="042025",
                               registrations=[_reg(PRIMARY, True)])
    assert got.can_reconcile and got.period == "042025"
    assert got.period_source == gstr2b_intake.FROM_REQUEST
    assert any("could not be checked against the file" in n for n in got.notes)


def test_no_month_anywhere_is_refused_not_guessed():
    got = gstr2b_intake.assess(parse_gstr2b(_raw(rtnprd=None)),
                               registrations=[_reg(PRIMARY, True)])
    assert not got.can_reconcile and got.period is None
    assert "no return period" in got.refusals[0]


@pytest.mark.parametrize("bad", ["2025-04", "13 2025", "132025", "42025", "AB2025"])
def test_a_period_that_is_not_a_month_is_refused_wherever_it_came_from(bad):
    in_file = gstr2b_intake.assess(parse_gstr2b(_raw(rtnprd=bad)),
                                   registrations=[_reg(PRIMARY, True)])
    typed = gstr2b_intake.assess(parse_gstr2b(_raw(rtnprd=None)), typed_period=bad,
                                 registrations=[_reg(PRIMARY, True)])
    for got in (in_file, typed):
        assert not got.can_reconcile and got.period is None
        assert "MMYYYY" in got.refusals[0]


def test_the_files_gstin_must_be_one_the_client_holds():
    held = [_reg(PRIMARY, True), _reg(SECOND)]
    ok = gstr2b_intake.assess(parse_gstr2b(_raw(gstin=SECOND)), registrations=held)
    assert ok.can_reconcile and ok.registration.gstin == SECOND

    bad = gstr2b_intake.assess(parse_gstr2b(_raw(gstin=STRANGER)), registrations=held)
    assert not bad.can_reconcile
    assert bad.registration is None and bad.period is None
    (why,) = bad.refusals
    assert STRANGER in why and PRIMARY in why and SECOND in why
    assert "not a registration recorded for this client" in why


def test_a_gstin_that_differs_only_in_case_or_padding_is_the_same_gstin():
    raw = _raw(gstin=f"  {PRIMARY.lower()} ")
    got = gstr2b_intake.assess(parse_gstr2b(raw), registrations=[_reg(PRIMARY, True)])
    assert got.can_reconcile and got.gstin == PRIMARY


def test_a_file_naming_no_gstin_is_refused_because_it_cannot_be_checked():
    got = gstr2b_intake.assess(parse_gstr2b(_raw(gstin=None)),
                               registrations=[_reg(PRIMARY, True)])
    assert not got.can_reconcile
    assert "no recipient GSTIN" in got.refusals[0]


def test_a_client_with_no_registration_cannot_have_a_2b_reconciled():
    got = gstr2b_intake.assess(parse_gstr2b(_raw()), registrations=[])
    assert not got.can_reconcile
    assert "no GST registration recorded" in got.refusals[0]


def test_no_registrations_supplied_is_NOT_CHECKED_and_never_reads_as_matched():
    """Mock mode has no table to read. The answer must not say the GSTIN matched."""
    got = gstr2b_intake.assess(parse_gstr2b(_raw(gstin=STRANGER)), registrations=None)
    assert got.can_reconcile, "nothing to refuse on — the check was not made"
    assert got.registration is None
    assert gstr2b_intake.GSTIN_NOT_CHECKED in got.notes


def test_a_file_that_is_not_a_2b_is_not_this_rules_question():
    got = gstr2b_intake.assess(parse_gstr2b({"invoices": [{"inum": "X"}]}),
                               typed_period="042025", registrations=[_reg(PRIMARY, True)])
    assert got.is_gstr2b is False and not got.can_reconcile
    assert got.refusals == (), "the parser's own sentences say what is wrong with it"


def test_a_2b_with_no_documents_is_still_a_2b():
    """Nobody filed anything is an answer, recorded — the service's rule stands."""
    got = gstr2b_intake.assess(parse_gstr2b(_raw(docs=False)),
                               registrations=[_reg(PRIMARY, True)])
    assert got.is_gstr2b and got.can_reconcile


def test_several_registrations_name_what_a_month_holds_one_of():
    held = [_reg(PRIMARY, True), _reg(SECOND)]
    for which in (PRIMARY, SECOND):
        got = gstr2b_intake.assess(parse_gstr2b(_raw(gstin=which)), registrations=held)
        assert got.registration_caveat, "the primary's 2B over-reports exactly as much"
        assert "REPLACES" in got.registration_caveat
        assert "2" in got.registration_caveat
        assert (SECOND if which == PRIMARY else PRIMARY) in got.registration_caveat


def test_one_registration_owes_no_caveat():
    got = gstr2b_intake.assess(parse_gstr2b(_raw()), registrations=[_reg(PRIMARY, True)])
    assert got.registration_caveat is None


# ═════════════════════════════════════════════════════════════════════════════
# THE DOORS — over a database that records what was written
# ═════════════════════════════════════════════════════════════════════════════

class _R:
    def __init__(self, data):
        self.data = data


class _Q:
    def __init__(self, db, table):
        self.db, self.table = db, table
        self.rows = list(db.store.get(table, []))
        self._op, self._payload = None, None

    def select(self, *_a, **_k): return self
    def order(self, *_a, **_k): return self

    def limit(self, n):
        self.rows = self.rows[:n]
        return self

    def eq(self, k, v):
        self.rows = [r for r in self.rows if str(r.get(k)) == str(v)]
        return self

    def in_(self, k, vals):
        vals = {str(v) for v in vals}
        self.rows = [r for r in self.rows if str(r.get(k)) in vals]
        return self

    def is_(self, k, _v):
        self.rows = [r for r in self.rows if r.get(k) is None]
        return self

    def gte(self, k, v):
        self.rows = [r for r in self.rows if str(r.get(k) or "") >= v]
        return self

    def lte(self, k, v):
        self.rows = [r for r in self.rows if str(r.get(k) or "") <= v]
        return self

    def gt(self, k, v):
        self.rows = [r for r in self.rows if str(r.get(k) or "") > str(v)]
        return self

    def delete(self):
        self._op = "delete"
        return self

    def insert(self, rows):
        self._op, self._payload = "insert", rows
        return self

    def execute(self):
        if self._op == "delete":
            gone = {id(r) for r in self.rows}
            self.db.store[self.table] = [r for r in self.db.store.get(self.table, [])
                                         if id(r) not in gone]
            self.db.writes.append(("delete", self.table))
            return _R([])
        if self._op == "insert":
            rows = self._payload if isinstance(self._payload, list) else [self._payload]
            self.db.store.setdefault(self.table, []).extend(dict(r) for r in rows)
            self.db.writes.append(("insert", self.table))
            return _R([])
        return _R(self.rows)


class _DB:
    def __init__(self, store):
        self.store, self.writes = store, []

    def table(self, name):
        return _Q(self, name)


class _Timeline:
    def log_timeline_event(self, **_k):
        pass


def _world(extra_registrations=(), primary=PRIMARY):
    return {
        "clients": [{"id": CLIENT, "firm_id": FIRM, "client_name": "Acme Traders",
                     "legal_name": "Acme Traders Pvt Ltd", "gstin": primary,
                     "state_code": (primary or "")[:2] or None}],
        "client_gst_registrations": [
            {"id": f"reg-{i}", "firm_id": FIRM, "client_id": CLIENT, "gstin": g,
             "state_code": g[:2], "deleted_at": None}
            for i, g in enumerate(extra_registrations)],
        "vendors": [{"id": "v1", "firm_id": FIRM, "gstin": SUPPLIER}],
        "purchase_bills": [
            {"id": "b1", "firm_id": FIRM, "client_id": CLIENT, "vendor_id": "v1",
             "bill_no": "INV-001", "bill_date": "2025-04-24",
             "taxable_amount_paise": 1_00_000, "cgst_paise": 9_000,
             "sgst_paise": 9_000, "igst_paise": 0, "status": "received",
             "deleted_at": None}],
        "gstr2a_records": [], "gstr2b_reconciliations": [], "gstr2b_uploads": [],
    }


@pytest.fixture
def live(monkeypatch):
    """The REAL path: not mock mode, a database that records its writes, the
    access check stubbed open (it is asserted separately below)."""
    import core.supabase_client as sc

    def build(store):
        db = _DB(store)
        monkeypatch.setattr(gw, "_USE_MOCK", False)
        monkeypatch.setattr(sc, "get_supabase", lambda: db)
        monkeypatch.setattr(gw, "assert_client_access", lambda *_a, **_k: None)
        monkeypatch.setattr(gw, "timeline_service", _Timeline())
        return db
    return build


def _upload(raw, period=None):
    return gw.upload_gstr2b(
        gw.GSTR2BUploadRequest(client_id=CLIENT, period=period, raw_data=raw), USER)


def _inspect(raw, period=None):
    return gw.inspect_gstr2b(
        gw.GSTR2BUploadRequest(client_id=CLIENT, period=period, raw_data=raw), USER)


def test_PREMISE_a_right_file_reconciles_with_no_period_typed(live):
    """The thing every refusal below is the absence of."""
    store = _world()
    live(store)
    out = _upload(_raw())
    assert out["success"] is True
    data = out["data"]
    assert data["persisted"] is True
    assert data["period"] == "042025" and data["period_source"] == "file"
    assert data["summary"]["matched_count"] == 1
    assert [r["return_period"] for r in store["gstr2a_records"]] == ["042025"]
    assert [r["period"] for r in store["gstr2b_uploads"]] == ["042025"]
    assert data["registration_caveat"] is None


def test_a_month_typed_against_a_different_file_is_refused_and_writes_nothing(live):
    store = _world()
    store["gstr2a_records"] = [{"id": "kept", "firm_id": FIRM, "client_id": CLIENT,
                                "return_period": "052025"}]
    db = live(store)
    with pytest.raises(HTTPException) as refused:
        _upload(_raw(), period="052025")
    assert refused.value.status_code == 422
    assert "042025" in refused.value.detail and "052025" in refused.value.detail
    assert db.writes == [], "a refused file must not delete or insert anything"
    assert [r["id"] for r in store["gstr2a_records"]] == ["kept"], (
        "May's reconciliation was replaced by April's documents — the defect")
    assert store["gstr2b_uploads"] == [], (
        "a refused file is not kept: it is not this client's")


def test_a_file_for_a_registration_the_client_does_not_hold_is_refused(live):
    store = _world()
    db = live(store)
    with pytest.raises(HTTPException) as refused:
        _upload(_raw(gstin=STRANGER))
    assert refused.value.status_code == 422
    assert STRANGER in refused.value.detail and PRIMARY in refused.value.detail
    assert db.writes == []
    assert store["gstr2a_records"] == [] and store["gstr2b_uploads"] == []


def test_a_file_with_no_gstin_is_refused_on_the_live_path(live):
    store = _world()
    db = live(store)
    with pytest.raises(HTTPException) as refused:
        _upload(_raw(gstin=None))
    assert "no recipient GSTIN" in refused.value.detail
    assert db.writes == []


def test_a_client_with_no_gstin_recorded_refuses_every_file(live):
    store = _world(primary=None)
    store["clients"][0]["gstin"] = None
    db = live(store)
    with pytest.raises(HTTPException) as refused:
        _upload(_raw())
    assert "no GST registration recorded" in refused.value.detail
    assert db.writes == []


def test_a_second_registrations_file_is_accepted_and_carries_the_caveat(live):
    store = _world(extra_registrations=[SECOND])
    live(store)
    data = _upload(_raw(gstin=SECOND))["data"]
    assert data["persisted"] is True
    assert "REPLACES" in data["registration_caveat"]
    assert data["registration_caveat"] in data["problems"], (
        "a caveat the screen's problem box does not show is served and rendered "
        "by nothing")


def test_a_file_that_is_not_a_2b_is_reported_and_still_persists_no_reconciliation(live):
    store = _world()
    live(store)
    data = _upload({"invoices": [{"inum": "X", "sgstin": SUPPLIER}]}, period="042025")["data"]
    assert data["persisted"] is False and data["summary"] is None
    assert store["gstr2a_records"] == [] and store["gstr2b_reconciliations"] == []
    assert [u["status"] for u in store["gstr2b_uploads"]] == ["parse_failed"]


def test_the_typed_period_still_works_for_a_caller_that_sends_the_one_the_file_names(live):
    live(_world())
    data = _upload(_raw(), period="042025")["data"]
    assert data["persisted"] is True and data["period"] == "042025"


# ── inspect: the same question, asked without acting ─────────────────────────

def test_inspect_reads_the_month_and_the_registration_and_writes_nothing(live):
    store = _world(extra_registrations=[SECOND])
    db = live(store)
    data = _inspect(_raw(gstin=SECOND, rtnprd="062025"))["data"]
    assert data["ok"] is True and data["is_gstr2b"] is True
    assert data["period"] == "062025" and data["period_source"] == "file"
    assert data["registration"]["gstin"] == SECOND
    assert data["registration"]["is_primary"] is False
    assert data["document_count"] == 1
    assert data["refusals"] == []
    assert data["registration_caveat"]
    assert db.writes == [], "inspect is a POST only because of the file's size"


def test_inspect_says_what_is_wrong_as_data_and_not_as_an_error(live):
    db = live(_world())
    data = _inspect(_raw(gstin=STRANGER))["data"]
    assert data["ok"] is False and data["period"] is None
    assert data["registration"] is None
    assert STRANGER in data["refusals"][0]
    assert db.writes == []


def test_inspect_and_upload_agree_on_every_file(live):
    """The preview is the upload's own walk. If they could disagree, the screen
    would enable a button the server then refuses."""
    files = [
        (_raw(), None), (_raw(), "042025"), (_raw(), "052025"),
        (_raw(gstin=STRANGER), None), (_raw(gstin=None), None),
        (_raw(rtnprd=None), "042025"), (_raw(rtnprd=None), None),
        (_raw(rtnprd="2025-04"), None),
    ]
    for raw, typed in files:
        live(_world())
        ok = _inspect(raw, typed)["data"]["ok"]
        live(_world())
        try:
            _upload(raw, typed)
            uploaded = True
        except HTTPException:
            uploaded = False
        assert ok is uploaded, (raw["data"].get("gstin"), raw["data"].get("rtnprd"), typed)


def test_inspect_of_a_file_that_is_not_a_2b_gives_the_parsers_sentences(live):
    live(_world())
    data = _inspect({"invoices": [{"inum": "X"}]})["data"]
    assert data["ok"] is False and data["is_gstr2b"] is False
    assert any("docdata" in r or "data" in r for r in data["refusals"])


def test_both_doors_check_the_client_first(monkeypatch, live):
    live(_world())
    asked = []

    def deny(user, client_id):
        asked.append(client_id)
        raise HTTPException(status_code=404, detail="Not found")

    monkeypatch.setattr(gw, "assert_client_access", deny)
    for door in (_upload, _inspect):
        with pytest.raises(HTTPException) as e:
            door(_raw())
        assert e.value.status_code == 404
    assert asked == [CLIENT, CLIENT]


def test_inspect_needs_the_same_permission_as_the_upload_it_previews():
    """Not a read-level action: the file is another taxpayer's data in flight."""
    import main

    want = {}
    for route in main.app.routes:
        path = getattr(route, "path", "")
        if path in ("/api/gst-workspace/gstr2b/inspect",
                    "/api/gst-workspace/gstr2b/upload"):
            want[path] = {
                getattr(getattr(d, "call", None), "__name__", "")
                for d in getattr(getattr(route, "dependant", None), "dependencies", [])
                if getattr(getattr(d, "call", None), "__name__", "").startswith("rbac_")}
    assert set(want) == {"/api/gst-workspace/gstr2b/inspect",
                         "/api/gst-workspace/gstr2b/upload"}
    assert want["/api/gst-workspace/gstr2b/inspect"] == want[
        "/api/gst-workspace/gstr2b/upload"] == {"rbac_gst_compute"}


# ── mock mode: nothing to read registrations from, and it says so ────────────

def test_mock_mode_takes_the_month_from_the_file_and_says_the_gstin_was_not_checked(monkeypatch):
    monkeypatch.setattr(gw, "_USE_MOCK", True)
    monkeypatch.setattr(gw, "assert_client_access", lambda *_a, **_k: None)
    data = _upload(_raw())["data"]
    assert data["period"] == "042025"
    assert gstr2b_intake.GSTIN_NOT_CHECKED in data["problems"]
    assert data["persisted"] is False
    with pytest.raises(HTTPException) as refused:
        _upload(_raw(), period="052025")
    assert refused.value.status_code == 422


# ── the read that feeds the rule ─────────────────────────────────────────────

def test_held_lists_the_primary_first_and_leaves_out_a_withdrawn_one():
    from services import client_gst_registration_service as svc

    store = _world(extra_registrations=[SECOND])
    store["client_gst_registrations"].append(
        {"id": "gone", "firm_id": FIRM, "client_id": CLIENT, "gstin": STRANGER,
         "state_code": "07", "deleted_at": "2025-01-01T00:00:00+00:00"})
    got = svc.held(_DB(store), FIRM, CLIENT)
    assert [r.gstin for r in got] == [PRIMARY, SECOND]
    assert got[0].is_primary and not got[1].is_primary


def test_held_does_not_read_another_firms_registrations():
    from services import client_gst_registration_service as svc

    store = _world()
    store["client_gst_registrations"].append(
        {"id": "x", "firm_id": "firm-2", "client_id": CLIENT, "gstin": SECOND,
         "state_code": "27", "deleted_at": None})
    assert [r.gstin for r in svc.held(_DB(store), FIRM, CLIENT)] == [PRIMARY]
