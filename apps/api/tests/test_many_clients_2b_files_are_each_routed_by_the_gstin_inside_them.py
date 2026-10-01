"""gst-10 — a drop of GSTR-2B files for many clients, each routed by the GSTIN
inside it, and no file ever routed to a client the caller may not see.

WHAT WAS MISSING
    A 2B was reconciled one client at a time, from that client's tab. Every file
    already carries the recipient GSTIN, so a CA with sixty clients opened sixty
    tabs to use files that said whose they were.

THE VERIFY LINE, AND HOW IT IS HELD
    "Upload 5 files for 5 clients plus one for an unknown GSTIN and one corrupt
    file in one action; the result lists 5 reconciled, 1 unmatched GSTIN and 1
    unreadable, each persisted only for the right client and firm. A test
    asserts no file can be routed to a client outside the caller's assigned
    book."  Both halves are below, over a database that records what it was
    asked to write, and the second is asserted three ways — the routing's own
    scope, the second access check, and an empty scope reading as NOTHING and not
    as "no filter".

THE SHAPE OF THESE TESTS
    Every refusal is preceded by the premise that the SAME file, for a client the
    caller may see, reconciles and persists. Otherwise "nothing was written"
    passes on a route that writes nothing for any file.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

import routers.gst_workspace as gw
from domain.gst import gstr2b_routing as routing
from domain.gst.gstin import checksum_char
from domain.gst.gstr2b import parse_gstr2b
from domain.gst.gstr2b_routing import Holder, route
from services import gst_2b_bulk_service as bulk
from services import gst_2b_reconciliation_service as recon

FIRM, OTHER_FIRM = "firm-1", "firm-2"


def gstin(state="29", pan="AAACX1234C", entity="1"):
    base = f"{state}{pan}{entity}Z"
    return base + checksum_char(base)


SUPPLIER = gstin("29", "AAAAA1111A")
CLIENTS = {  # id -> (name, GSTIN)
    "c1": ("Acme Traders", gstin("29", "AAACA1111C")),
    "c2": ("Bharat Mills", gstin("27", "AAACB2222C")),
    "c3": ("Chola Exports", gstin("33", "AAACC3333C")),
    "c4": ("Delta Foods", gstin("07", "AAACD4444C")),
    "c5": ("Eastern Steel", gstin("19", "AAACE5555C")),
}
UNKNOWN = gstin("24", "AAACZ9999C")
MANAGER = {"id": "u-mgr", "firm_id": FIRM, "role": "Manager"}


def _raw(recipient, period="042025", number="INV-001"):
    return {"data": {"gstin": recipient, "rtnprd": period, "gendt": "14-05-2025",
                     "docdata": {"b2b": [
                         {"ctin": SUPPLIER, "trdnm": "Acme Supplies", "supfildt": "10-05-2025",
                          "inv": [{"inum": number, "dt": "24-04-2025", "val": 1180.0,
                                   "itcavl": "Y",
                                   "items": [{"num": 1, "rt": 18.0, "txval": 1000.0,
                                              "cgst": 90.0, "sgst": 90.0, "igst": 0}]}]}]}}}


def _file(name, recipient, **kw):
    return {"name": name, "raw": _raw(recipient, **kw)}


# ── a database that records what it was asked to write ───────────────────────

class _R:
    def __init__(self, data):
        self.data = data


class _Q:
    def __init__(self, db, table):
        self.db, self.table = db, table
        self.rows = list(db.store.get(table, []))
        self._op, self._payload = None, None

    def select(self, *_a, **_k): return self

    def order(self, k, desc=False, **_k):
        self.rows = sorted(self.rows, key=lambda r: str(r.get(k) or ""), reverse=desc)
        return self

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
            self.db.writes.append(("delete", self.table, None))
            return _R([])
        if self._op == "insert":
            rows = self._payload if isinstance(self._payload, list) else [self._payload]
            self.db.store.setdefault(self.table, []).extend(dict(r) for r in rows)
            for r in rows:
                self.db.writes.append(("insert", self.table, r.get("client_id")))
            return _R([])
        return _R(self.rows)


class _DB:
    def __init__(self, store):
        self.store, self.writes = store, []

    def table(self, name):
        return _Q(self, name)

    def clients_written(self):
        return {c for _op, _t, c in self.writes if c}


class _Timeline:
    def __init__(self):
        self.events = []

    def log_timeline_event(self, **k):
        self.events.append(k)


def _world(firm_clients=CLIENTS, extra_clients=(), registrations=()):
    clients = [{"id": cid, "firm_id": FIRM, "client_name": name, "legal_name": name,
                "gstin": g, "state_code": g[:2], "deleted_at": None}
               for cid, (name, g) in firm_clients.items()]
    clients.extend(extra_clients)
    bills, vendors = [], [{"id": "v1", "firm_id": FIRM, "gstin": SUPPLIER}]
    for cid in firm_clients:
        bills.append({"id": f"b-{cid}", "firm_id": FIRM, "client_id": cid,
                      "vendor_id": "v1", "bill_no": "INV-001",
                      "bill_date": "2025-04-24", "taxable_amount_paise": 1_00_000,
                      "cgst_paise": 9_000, "sgst_paise": 9_000, "igst_paise": 0,
                      "status": "received", "deleted_at": None})
    return {
        "clients": clients,
        "client_gst_registrations": list(registrations),
        "vendors": vendors, "purchase_bills": bills,
        "gstr2a_records": [], "gstr2b_reconciliations": [], "gstr2b_uploads": [],
    }


def _run(store, files, *, visible=None, can_access=lambda _cid: True, timeline=None):
    db = _DB(store)
    out = bulk.process(db, firm_id=FIRM, files=files, visible=visible,
                       can_access=can_access, created_by="u1",
                       timeline=timeline or _Timeline())
    return db, out


def _by_name(out):
    return {r["name"]: r for r in out["results"]}


# ═════════════════════════════════════════════════════════════════════════════
# THE VERIFY LINE
# ═════════════════════════════════════════════════════════════════════════════

def _the_verify_files():
    files = [_file(f"2b-{cid}.json", g) for cid, (_n, g) in CLIENTS.items()]
    files.append(_file("2b-stranger.json", UNKNOWN))
    files.append({"name": "not-a-2b.json", "raw": {"invoices": [{"inum": "X"}]}})
    return files


def test_five_files_for_five_clients_plus_a_stranger_and_a_corrupt_one_in_one_action():
    store = _world()
    db, out = _run(store, _the_verify_files())

    assert out["totals"] == {"reconciled": 5, "unmatched_gstin": 1, "ambiguous_gstin": 0,
                             "refused": 0, "unreadable": 1, "failed": 0}
    rows = _by_name(out)
    for cid, (name, g) in CLIENTS.items():
        r = rows[f"2b-{cid}.json"]
        assert r["status"] == "reconciled", r
        assert r["client_id"] == cid and r["client_name"] == name
        assert r["gstin"] == g and r["period"] == "042025"
        assert r["summary"]["matched_count"] == 1
    assert rows["2b-stranger.json"]["status"] == "unmatched_gstin"
    assert rows["not-a-2b.json"]["status"] == "unreadable"

    # PERSISTED ONLY FOR THE RIGHT CLIENT: each client holds its own one row.
    for cid in CLIENTS:
        mine = [r for r in store["gstr2a_records"] if r["client_id"] == cid]
        assert len(mine) == 1 and mine[0]["firm_id"] == FIRM
        assert mine[0]["return_period"] == "042025"
        assert mine[0]["purchase_bill_id"] == f"b-{cid}", (
            "matched against THAT client's own bill and no other's")
        assert len([u for u in store["gstr2b_uploads"] if u["client_id"] == cid]) == 1
    assert len(store["gstr2a_records"]) == 5
    assert len(store["gstr2b_uploads"]) == 5
    assert {h["client_id"] for h in store["gstr2b_reconciliations"]} == set(CLIENTS)
    # nothing at all was written for the stranger or the corrupt file
    assert db.clients_written() == set(CLIENTS)


def test_the_result_is_a_summary_per_file_and_never_the_per_document_matches():
    _db, out = _run(_world(), _the_verify_files())
    for r in out["results"]:
        assert "matches" not in r and "defaulters" not in r
        assert set(r) == {"name", "status", "reason", "gstin", "period", "client_id",
                          "client_name", "needs_attention", "summary", "problems",
                          "registration_caveat", "replaced_earlier"}, (
            "every key is ALWAYS present and null where it does not apply")


def test_each_clients_rows_are_exactly_what_the_single_upload_writes():
    """It is the single upload repeated, not a second reconciler: the same
    function writes the same rows."""
    bulk_store = _world()
    _run(bulk_store, [_file("a.json", CLIENTS["c1"][1])])
    single_store = _world()
    recon.reconcile_2b(_DB(single_store), firm_id=FIRM, client_id="c1",
                       period="042025", raw=_raw(CLIENTS["c1"][1]))

    def norm(rows):
        return [{k: v for k, v in r.items() if k not in ("reconciled_at", "updated_at")}
                for r in rows if r["client_id"] == "c1"]

    assert norm(bulk_store["gstr2a_records"]) == norm(single_store["gstr2a_records"])
    assert ([h["document_count"] for h in bulk_store["gstr2b_reconciliations"]]
            == [h["document_count"] for h in single_store["gstr2b_reconciliations"]])


def test_a_reconciliation_that_found_something_leaves_the_same_timeline_notice():
    store = _world()
    store["purchase_bills"] = []                    # nothing to match → missing_in_books
    tl = _Timeline()
    # a bill the supplier has not filed:
    store["purchase_bills"] = [{
        "id": "b-x", "firm_id": FIRM, "client_id": "c1", "vendor_id": "v1",
        "bill_no": "NOT-FILED", "bill_date": "2025-04-20",
        "taxable_amount_paise": 50_000, "cgst_paise": 4_500, "sgst_paise": 4_500,
        "igst_paise": 0, "status": "received", "deleted_at": None}]
    _run(store, [_file("a.json", CLIENTS["c1"][1])], timeline=tl)
    (event,) = tl.events
    assert event["client_id"] == "c1" and event["event_type"] == "gst_mismatch_detected"
    assert "1 bills the supplier has not filed" in event["title"]


# ═════════════════════════════════════════════════════════════════════════════
# A FILE THAT BELONGS TO NOBODY YOU MAY SEE IS REPORTED AND NOT KEPT
# ═════════════════════════════════════════════════════════════════════════════

def test_PREMISE_a_client_inside_the_callers_book_is_routed():
    store = _world()
    _db, out = _run(store, [_file("b.json", CLIENTS["c2"][1])], visible={"c2"})
    assert out["results"][0]["status"] == "reconciled"
    assert out["results"][0]["client_id"] == "c2"


def test_a_file_for_a_client_outside_the_assigned_book_is_not_routed_and_writes_nothing():
    store = _world()
    db, out = _run(store, [_file("mine.json", CLIENTS["c1"][1]),
                           _file("theirs.json", CLIENTS["c2"][1])], visible={"c1"})
    rows = _by_name(out)
    assert rows["mine.json"]["status"] == "reconciled"
    assert rows["theirs.json"]["status"] == "unmatched_gstin"
    assert rows["theirs.json"]["client_id"] is None, (
        "the row must not name a client the caller may not see")
    assert db.clients_written() == {"c1"}
    assert [r["client_id"] for r in store["gstr2a_records"]] == ["c1"]
    assert [u["client_id"] for u in store["gstr2b_uploads"]] == ["c1"]


def test_an_out_of_scope_client_reads_exactly_like_a_gstin_nobody_holds():
    """A different sentence for 'exists but is not yours' would be an oracle for
    the existence of another person's client — why assert_client_access says 404."""
    _db, out = _run(_world(), [_file("theirs.json", CLIENTS["c2"][1]),
                               _file("nobody.json", UNKNOWN)], visible={"c1"})
    theirs, nobody = out["results"]
    assert theirs["status"] == nobody["status"] == "unmatched_gstin"
    assert theirs["reason"].replace(CLIENTS["c2"][1], "<G>") == \
        nobody["reason"].replace(UNKNOWN, "<G>")
    assert theirs["client_name"] is None and nobody["client_name"] is None


def test_an_EMPTY_scope_is_nothing_and_never_no_filter():
    store = _world()
    db, out = _run(store, [_file(f"{cid}.json", g) for cid, (_n, g) in CLIENTS.items()],
                   visible=set())
    assert out["totals"]["unmatched_gstin"] == 5 and out["totals"]["reconciled"] == 0
    assert db.writes == [] and store["gstr2a_records"] == []


def test_the_second_access_check_is_asked_of_every_routed_client():
    store = _world()
    asked = []

    def can_access(cid):
        asked.append(cid)
        return cid != "c2"

    db, out = _run(store, [_file("a.json", CLIENTS["c1"][1]),
                           _file("b.json", CLIENTS["c2"][1])], can_access=can_access)
    rows = _by_name(out)
    assert asked == ["c1", "c2"]
    assert rows["a.json"]["status"] == "reconciled"
    assert rows["b.json"]["status"] == "unmatched_gstin"
    assert db.clients_written() == {"c1"}


def test_a_gstin_held_only_by_another_firm_is_not_found():
    foreign = {"id": "f1", "firm_id": OTHER_FIRM, "client_name": "Foreign Co",
               "legal_name": "Foreign Co", "gstin": UNKNOWN, "state_code": "24",
               "deleted_at": None}
    store = _world(extra_clients=[foreign])
    db, out = _run(store, [_file("x.json", UNKNOWN)])
    assert out["results"][0]["status"] == "unmatched_gstin"
    assert db.writes == [], "another firm's client is not a place to file anything"


def test_a_file_is_never_defaulted_to_the_only_client_there_is():
    one = {"c1": CLIENTS["c1"]}
    store = _world(firm_clients=one)
    db, out = _run(store, [_file("x.json", UNKNOWN)])
    assert out["results"][0]["status"] == "unmatched_gstin"
    assert db.writes == [] and store["gstr2a_records"] == []


def test_a_gstin_two_clients_hold_is_refused_not_given_to_the_first():
    twin = {"id": "c1-twin", "firm_id": FIRM, "client_name": "Acme (duplicate)",
            "legal_name": "Acme (duplicate)", "gstin": CLIENTS["c1"][1],
            "state_code": "29", "deleted_at": None}
    store = _world(extra_clients=[twin])
    db, out = _run(store, [_file("x.json", CLIENTS["c1"][1])])
    r = out["results"][0]
    assert r["status"] == "ambiguous_gstin" and "More than one of your clients" in r["reason"]
    assert db.writes == []


def test_a_gstin_held_twice_but_visible_once_goes_to_the_one_the_caller_may_see():
    twin = {"id": "c1-twin", "firm_id": FIRM, "client_name": "Acme (duplicate)",
            "legal_name": "Acme (duplicate)", "gstin": CLIENTS["c1"][1],
            "state_code": "29", "deleted_at": None}
    store = _world(extra_clients=[twin])
    _db, out = _run(store, [_file("x.json", CLIENTS["c1"][1])], visible={"c1"})
    assert out["results"][0]["status"] == "reconciled"
    assert out["results"][0]["client_id"] == "c1"


def test_an_additional_registration_routes_to_its_client():
    second = gstin("27", "AAACA1111C")
    reg = {"id": "r1", "firm_id": FIRM, "client_id": "c1", "gstin": second,
           "state_code": "27", "deleted_at": None, "registration_type": "regular"}
    store = _world(registrations=[reg])
    _db, out = _run(store, [_file("depot.json", second)])
    r = out["results"][0]
    assert r["status"] == "reconciled" and r["client_id"] == "c1"
    assert r["registration_caveat"] and "REPLACES" in r["registration_caveat"]
    assert r["needs_attention"] is True


def test_a_deleted_client_and_a_deleted_registration_hold_nothing():
    gone = {"id": "cg", "firm_id": FIRM, "client_name": "Gone", "legal_name": "Gone",
            "gstin": UNKNOWN, "state_code": "24", "deleted_at": "2025-01-01T00:00:00+00:00"}
    reg = {"id": "r1", "firm_id": FIRM, "client_id": "c1", "gstin": gstin("24", "AAACQ7777C"),
           "state_code": "24", "deleted_at": "2025-01-01T00:00:00+00:00"}
    store = _world(extra_clients=[gone], registrations=[reg])
    db, out = _run(store, [_file("a.json", UNKNOWN), _file("b.json", reg["gstin"])])
    assert [r["status"] for r in out["results"]] == ["unmatched_gstin"] * 2
    assert db.writes == []


def test_a_gstin_in_lower_case_with_padding_is_the_same_gstin():
    _db, out = _run(_world(), [_file("a.json", f"  {CLIENTS['c1'][1].lower()} ")])
    assert out["results"][0]["status"] == "reconciled"


# ═════════════════════════════════════════════════════════════════════════════
# THE INTAKE RULES STILL APPLY, PER FILE
# ═════════════════════════════════════════════════════════════════════════════

def test_a_file_naming_no_gstin_is_refused_and_writes_nothing():
    raw = _raw(CLIENTS["c1"][1])
    del raw["data"]["gstin"]
    db, out = _run(_world(), [{"name": "x.json", "raw": raw}])
    r = out["results"][0]
    assert r["status"] == "refused" and "no recipient GSTIN" in r["reason"]
    assert db.writes == []


def test_a_file_whose_month_is_not_a_month_is_refused_with_the_intakes_own_sentence():
    db, out = _run(_world(), [_file("x.json", CLIENTS["c1"][1], period="132025")])
    r = out["results"][0]
    assert r["status"] == "refused" and "MMYYYY" in r["reason"]
    assert r["client_id"] == "c1"
    assert db.writes == []


def test_a_file_naming_no_month_at_all_is_refused_there_being_none_to_type():
    raw = _raw(CLIENTS["c1"][1])
    del raw["data"]["rtnprd"]
    db, out = _run(_world(), [{"name": "x.json", "raw": raw}])
    assert out["results"][0]["status"] == "refused"
    assert "names no return period" in out["results"][0]["reason"]
    assert db.writes == []


def test_a_file_that_is_not_json_shaped_like_a_2b_is_unreadable_in_the_parsers_words():
    db, out = _run(_world(), [{"name": "x.json", "raw": {"hello": 1}},
                              {"name": "y.json", "raw": {"data": {"docdata": "no"}}},
                              {"name": "z.json", "raw": None}])
    assert [r["status"] for r in out["results"]] == ["unreadable"] * 3
    assert all(r["reason"] for r in out["results"])
    assert db.writes == []


# ═════════════════════════════════════════════════════════════════════════════
# THE BATCH
# ═════════════════════════════════════════════════════════════════════════════

def test_two_files_for_one_client_and_month_in_one_upload_replace_nothing_second():
    store = _world()
    g = CLIENTS["c1"][1]
    _db, out = _run(store, [_file("first.json", g, number="INV-001"),
                            _file("second.json", g, number="OTHER-9")])
    first, second = out["results"]
    assert first["status"] == "reconciled"
    assert second["status"] == "refused" and "first.json" in second["reason"]
    assert "Nothing was replaced" in second["reason"]
    # the first survives untouched — the order dropped is not the winner by accident
    assert [r["invoice_number"] for r in store["gstr2a_records"]] == ["INV-001"]
    assert len(store["gstr2b_uploads"]) == 1


def test_two_months_for_one_client_are_not_a_collision():
    store = _world()
    g = CLIENTS["c1"][1]
    _db, out = _run(store, [_file("apr.json", g, period="042025"),
                            _file("may.json", g, period="052025")])
    assert [r["status"] for r in out["results"]] == ["reconciled", "reconciled"]
    assert {r["return_period"] for r in store["gstr2a_records"]} == {"042025", "052025"}


def test_replacing_an_earlier_reconciliation_is_said_and_asks_for_a_look():
    store = _world()
    g = CLIENTS["c1"][1]
    _run(store, [_file("first.json", g)])
    assert _run(store, [_file("again.json", g)])[1]["results"][0]["replaced_earlier"]

    store2 = _world()
    first = _run(store2, [_file("first.json", g)])[1]["results"][0]
    assert first["replaced_earlier"] is None
    again = _run(store2, [_file("again.json", g)])[1]["results"][0]
    assert again["replaced_earlier"]["reconciled_at"]
    assert again["needs_attention"] is True


def test_one_files_failure_is_one_row_and_not_the_batch(monkeypatch):
    real = recon.reconcile_2b

    def flaky(db, *, firm_id, client_id, period, raw):
        if client_id == "c2":
            raise RuntimeError("relation \"gstr2a_records\" does not exist (secret detail)")
        return real(db, firm_id=firm_id, client_id=client_id, period=period, raw=raw)

    monkeypatch.setattr(recon, "reconcile_2b", flaky)
    store = _world()
    _db, out = _run(store, [_file("a.json", CLIENTS["c1"][1]),
                            _file("b.json", CLIENTS["c2"][1]),
                            _file("c.json", CLIENTS["c3"][1])])
    rows = _by_name(out)
    assert rows["a.json"]["status"] == rows["c.json"]["status"] == "reconciled"
    assert rows["b.json"]["status"] == "failed"
    assert "secret detail" not in rows["b.json"]["reason"], (
        "an exception's text names tables and ids and is never shown")
    assert {r["client_id"] for r in store["gstr2a_records"]} == {"c1", "c3"}


def test_a_clean_reconciliation_does_not_ask_for_attention():
    store = _world()
    _db, out = _run(store, [_file("a.json", CLIENTS["c1"][1])])
    r = out["results"][0]
    assert r["needs_attention"] is False and out["needs_attention"] == 0


def test_a_reconciliation_with_a_document_the_books_lack_asks_for_attention():
    store = _world()
    store["purchase_bills"] = []
    _db, out = _run(store, [_file("a.json", CLIENTS["c1"][1])])
    r = out["results"][0]
    assert r["needs_attention"] is True and out["needs_attention"] == 1
    assert r["summary"]["missing_in_books_count"] == 1


# ═════════════════════════════════════════════════════════════════════════════
# THE ROUTE
# ═════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def live(monkeypatch):
    import core.supabase_client as sc

    def build(store, *, visible=None, can=lambda *_a, **_k: True):
        db = _DB(store)
        monkeypatch.setattr(gw, "_USE_MOCK", False)
        monkeypatch.setattr(sc, "get_supabase", lambda: db)
        monkeypatch.setattr(gw, "effective_client_ids", lambda _u: visible)
        monkeypatch.setattr(gw, "can_access_client", lambda _u, cid: can(cid))
        monkeypatch.setattr(gw, "timeline_service", _Timeline())
        return db
    return build


def _post(files):
    return gw.bulk_gstr2b(gw.GSTR2BBulkRequest(
        files=[gw.GSTR2BBulkFile(name=f["name"], raw_data=f["raw"]) for f in files]),
        MANAGER)


def test_the_route_answers_per_file_and_confines_a_manager_to_the_assigned_book(live):
    store = _world()
    db = live(store, visible={"c1", "c3"})
    out = _post([_file("a.json", CLIENTS["c1"][1]), _file("b.json", CLIENTS["c2"][1]),
                 _file("c.json", CLIENTS["c3"][1])])
    assert out["success"] is True
    rows = _by_name(out["data"])
    assert [rows[n]["status"] for n in ("a.json", "b.json", "c.json")] == \
        ["reconciled", "unmatched_gstin", "reconciled"]
    assert db.clients_written() == {"c1", "c3"}


def test_the_request_names_no_client_and_no_period_and_is_bounded():
    assert set(gw.GSTR2BBulkRequest.model_fields) == {"files"}
    assert set(gw.GSTR2BBulkFile.model_fields) == {"name", "raw_data"}
    one = gw.GSTR2BBulkFile(name="a", raw_data={})
    gw.GSTR2BBulkRequest(files=[one] * bulk.MAX_FILES_PER_REQUEST)
    with pytest.raises(ValidationError):
        gw.GSTR2BBulkRequest(files=[one] * (bulk.MAX_FILES_PER_REQUEST + 1))
    with pytest.raises(ValidationError):
        gw.GSTR2BBulkRequest(files=[])


def test_the_route_is_registered_and_needs_the_gst_compute_permission():
    import inspect
    paths = {(m, r.path) for r in gw.router.routes for m in getattr(r, "methods", ())}
    assert ("POST", "/api/gst-workspace/gstr2b/bulk") in paths
    dep = inspect.signature(gw.bulk_gstr2b).parameters["current_user"].default
    assert dep.dependency.__qualname__.startswith("rbac")


def test_mock_mode_reads_the_files_and_routes_none(monkeypatch):
    monkeypatch.setattr(gw, "_USE_MOCK", True)
    out = _post([_file("a.json", CLIENTS["c1"][1]),
                 {"name": "b.json", "raw": {"x": 1}}])["data"]
    assert [r["status"] for r in out["results"]] == ["failed", "unreadable"]
    assert "Running without a database" in out["results"][0]["reason"]
    assert out["needs_attention"] == 0


# ═════════════════════════════════════════════════════════════════════════════
# THE RULE — pure
# ═════════════════════════════════════════════════════════════════════════════

H = [Holder("c1", CLIENTS["c1"][1], True), Holder("c2", CLIENTS["c2"][1], True),
     Holder("c1", gstin("27", "AAACA1111C"), False)]


def _p(g):
    return parse_gstr2b(_raw(g))


def test_the_rule_routes_by_gstin_primary_or_additional():
    assert route(_p(CLIENTS["c1"][1]), H, None).client_id == "c1"
    assert route(_p(gstin("27", "AAACA1111C")), H, None).client_id == "c1"


def test_the_rule_answers_each_way_a_file_cannot_be_routed():
    assert route(_p(UNKNOWN), H, None).verdict == routing.UNMATCHED_GSTIN
    assert route(parse_gstr2b({"x": 1}), H, None).verdict == routing.NOT_A_GSTR2B
    no_gstin = _raw(CLIENTS["c1"][1])
    del no_gstin["data"]["gstin"]
    assert route(parse_gstr2b(no_gstin), H, None).verdict == routing.NO_GSTIN
    dup = H + [Holder("c9", CLIENTS["c1"][1], True)]
    assert route(_p(CLIENTS["c1"][1]), dup, None).verdict == routing.AMBIGUOUS_GSTIN


def test_the_rule_scope_none_is_everyone_a_set_is_those_and_empty_is_nobody():
    f = _p(CLIENTS["c2"][1])
    assert route(f, H, None).routed
    assert route(f, H, {"c2"}).routed
    assert route(f, H, {"c1"}).verdict == routing.UNMATCHED_GSTIN
    assert route(f, H, set()).verdict == routing.UNMATCHED_GSTIN


def test_the_rule_reads_no_client_id_off_the_file_or_a_request():
    """A file that CLAIMS a client is not believed: `client_id` is not a thing
    the parser or the router reads, so there is nothing to tamper with."""
    raw = _raw(CLIENTS["c1"][1])
    raw["client_id"] = "c2"
    raw["data"]["client_id"] = "c2"
    assert route(parse_gstr2b(raw), H, None).client_id == "c1"
    import inspect
    assert "client_id" not in inspect.signature(route).parameters
