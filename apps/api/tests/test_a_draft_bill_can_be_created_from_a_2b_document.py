"""gst-13 — a GSTR-2B document the books have no bill for can be turned into a
DRAFT purchase bill, and the draft never posts, never claims and never invents.

WHAT WAS MISSING
    For a `missing_in_books` row the screen said "chase the document" and
    stopped. The supplier had filed an invoice the client never entered, the 2B
    row carried everything the supplier knows, and the CA retyped it from the
    very screen that was holding the figures.

THE SHAPE OF THESE TESTS
    The whole path is exercised: a real upload through the real route (so the
    kept file and the stored rows are what production writes), then the draft
    through the real route and the real bill engine (`_create_purchase_bill_core`),
    over a database that records every table it was asked to write. The verify
    line has two halves — the draft carries the 2B figures and no journal, and
    receiving it then re-running the reconciliation moves the row to `matched` —
    and both are asserted end to end, with the receipt simulated by the one
    thing that matters to the matcher (the bill's status).

    Every refusal is preceded by the premise that the SAME document, when it is
    drafted from a right file, produces a draft. Otherwise "nothing was
    written" passes on a route that writes nothing for any input.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

import routers.gst_workspace as gw
import routers.purchase_bills as pb
from domain.gst import draft_bill_from_2b
from domain.gst.gstr2b import parse_gstr2b
from services import gst_2b_reconciliation_service as svc

FIRM, CLIENT = "firm-1", "client-1"
CLIENT_GSTIN = "29AAACX1234C1ZP"
SUPPLIER = "29AAAAA1111A1Z5"
OTHER_STATE_SUPPLIER = "27AAAAA1111A1Z5"
NUMBER = "INV/2025-26/0042"
USER = {"id": "u1", "firm_id": FIRM, "role": "Partner", "email": "ca@example.com"}


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

    def neq(self, k, v):
        self.rows = [r for r in self.rows if str(r.get(k)) != str(v)]
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
            payload = self._payload if isinstance(self._payload, list) else [self._payload]
            made = []
            for r in payload:
                row = dict(r)
                row.setdefault("id", str(uuid.uuid4()))
                made.append(row)
            self.db.store.setdefault(self.table, []).extend(made)
            self.db.writes.append(("insert", self.table))
            return _R([dict(r) for r in made])
        return _R(self.rows)


class _DB:
    def __init__(self, store):
        self.store, self.writes = store, []

    def table(self, name):
        return _Q(self, name)

    def written_tables(self):
        return {t for _op, t in self.writes}


class _Timeline:
    def log_timeline_event(self, **_k): pass
    def log(self, *_a, **_k): pass


class _Open:
    def validate_posting_date_cached(self, *_a, **_k): pass


# ── the file, the world, and the plumbing ────────────────────────────────────

def _inv(inum=NUMBER, items=None, rev=None, dt="24-04-2025", itcavl="Y"):
    inv = {"inum": inum, "dt": dt, "val": 1180.0, "itcavl": itcavl,
           "items": items or [{"num": 1, "rt": 18.0, "txval": 1000.0,
                               "cgst": 90.0, "sgst": 90.0, "igst": 0}]}
    if rev is not None:
        inv["rev"] = rev
    return inv


def _raw(invs=None, ctin=SUPPLIER, **sections):
    docdata = {"b2b": [{"ctin": ctin, "trdnm": "Acme Supplies", "supfildt": "10-05-2025",
                        "inv": invs if invs is not None else [_inv()]}]}
    docdata.update(sections)
    return {"data": {"gstin": CLIENT_GSTIN, "rtnprd": "042025",
                     "gendt": "14-05-2025", "docdata": docdata}}


def _world(vendors=None, bills=None):
    return {
        "clients": [{"id": CLIENT, "firm_id": FIRM, "client_name": "Acme Traders",
                     "legal_name": "Acme Traders Pvt Ltd", "gstin": CLIENT_GSTIN,
                     "state_code": "29"}],
        "client_gst_registrations": [],
        "vendors": vendors if vendors is not None else [
            {"id": "v1", "firm_id": FIRM, "client_id": CLIENT, "name": "Acme Supplies",
             "gstin": SUPPLIER, "state_code": "29", "is_active": True,
             "tds_applicable": False, "credit_days": 30}],
        "purchase_bills": list(bills or []),
        "purchase_bill_lines": [],
        "gstr2a_records": [], "gstr2b_reconciliations": [], "gstr2b_uploads": [],
    }


@pytest.fixture
def live(monkeypatch):
    import core.supabase_client as sc

    def build(store):
        db = _DB(store)
        monkeypatch.setattr(gw, "_USE_MOCK", False)
        monkeypatch.setattr(pb, "_USE_MOCK", False)
        monkeypatch.setattr(sc, "get_supabase", lambda: db)
        monkeypatch.setattr(gw, "assert_client_access", lambda *_a, **_k: None)
        monkeypatch.setattr(pb, "assert_client_access", lambda *_a, **_k: None)
        monkeypatch.setattr(gw, "timeline_service", _Timeline())
        monkeypatch.setattr(pb, "timeline_service", _Timeline())
        monkeypatch.setattr(pb, "period_validation_service", _Open())
        monkeypatch.setattr(pb.period_lock_service, "assert_open",
                            lambda *_a, **_k: None)
        monkeypatch.setattr(pb, "log_event", lambda *_a, **_k: None)
        return db
    return build


def _upload(raw):
    return gw.upload_gstr2b(gw.GSTR2BUploadRequest(client_id=CLIENT, raw_data=raw), USER)


def _draft(**over):
    body = dict(client_id=CLIENT, period="042025", section="b2b",
                document_type="invoice", supplier_gstin=SUPPLIER,
                document_number=NUMBER)
    body.update(over)
    return pb.create_bill_from_2b(pb.BillFrom2BIn(**body), USER)


def _setup(live, raw=None, **world):
    store = _world(**world)
    db = live(store)
    out = _upload(raw or _raw())
    assert out["success"] is True and out["data"]["persisted"] is True
    return store, db, out["data"]


# ═════════════════════════════════════════════════════════════════════════════
# THE PREMISE, THEN THE DRAFT
# ═════════════════════════════════════════════════════════════════════════════

def test_PREMISE_the_document_is_missing_in_books_and_the_screen_is_told_it_may_be_drafted(live):
    _store, _db, data = _setup(live)
    (row,) = [m for m in data["matches"] if m["status"] == "missing_in_books"]
    assert row["document_number"] == NUMBER and row["section"] == "b2b"
    assert row["draft_bill_offered"] is True
    assert row["draft_bill_refusal"] is None


def test_the_draft_carries_the_2b_figures_with_the_suppliers_own_number_and_no_journal(live):
    store, db, _data = _setup(live)
    writes_before = len(db.writes)

    out = _draft()
    assert out["success"] is True
    data = out["data"]

    (bill,) = store["purchase_bills"]
    assert bill["status"] == "draft" and data["status"] == "draft"
    # THE NUMBER IS THEIRS — exactly as filed, separators and all.
    assert bill["bill_no"] == NUMBER
    assert bill["bill_date"] == "2025-04-24"
    assert bill["vendor_id"] == "v1" and bill["client_id"] == CLIENT
    assert bill["taxable_amount_paise"] == 1_00_000
    assert bill["cgst_paise"] == 9_000 and bill["sgst_paise"] == 9_000
    assert bill["igst_paise"] == 0
    assert "GSTR-2B for April 2025" in bill["notes"]
    (line,) = store["purchase_bill_lines"]
    assert line["rate_paise"] == 1_00_000 and line["gst_rate_bps"] == 1800
    assert line["hsn_sac"] is None, "GSTR-2B carries no HSN and none is invented"
    assert line["service_catalogue_id"] is None

    assert data["agrees_with_2b"] is True and data["differences"] == []
    assert any("DRAFT" in c and "receive it" in c for c in data["caveats"])

    # NOTHING POSTED: only the bill and its lines were written.
    new_tables = {t for _op, t in db.writes[writes_before:]}
    assert new_tables == {"purchase_bills", "purchase_bill_lines"}, new_tables
    assert "journal_entries" not in db.written_tables()
    assert "journal_lines" not in db.written_tables()
    # and the 2B row was not touched — there is no stored link.
    (rec,) = store["gstr2a_records"]
    assert rec["purchase_bill_id"] is None and rec["match_status"] == "missing_in_books"


def test_a_draft_is_not_on_the_books_so_the_row_stays_missing_until_it_is_received(live):
    """The draft must not be able to settle the very row it came from: only a
    RECEIVED bill is a bill the supplier could have filed against."""
    store, _db, _data = _setup(live)
    _draft()
    again = svc.reconcile_2b(_db, firm_id=FIRM, client_id=CLIENT, period="042025",
                             raw=_raw())
    assert again["summary"]["matched_count"] == 0
    assert again["summary"]["missing_in_books_count"] == 1
    assert again["book_bill_count"] == 0


def test_receiving_the_draft_and_running_the_reconciliation_again_matches_the_row(live):
    store, db, _data = _setup(live)
    _draft()
    (bill,) = store["purchase_bills"]
    bill["status"] = "received"            # what /receive does, as far as 2B can see

    again = svc.reconcile_2b(db, firm_id=FIRM, client_id=CLIENT, period="042025",
                             raw=_raw())
    assert again["summary"]["matched_count"] == 1
    assert again["summary"]["missing_in_books_count"] == 0
    assert again["probable_matches"] == []
    (rec,) = store["gstr2a_records"]
    assert rec["purchase_bill_id"] == bill["id"] and rec["match_status"] == "matched"


def test_a_second_click_cannot_draft_the_same_invoice_twice(live):
    store, _db, _data = _setup(live)
    assert _draft()["success"] is True
    with pytest.raises(HTTPException) as dup:
        _draft()
    assert dup.value.status_code == 409
    assert len(store["purchase_bills"]) == 1


# ═════════════════════════════════════════════════════════════════════════════
# THE RATE COMES FROM THE FILE
# ═════════════════════════════════════════════════════════════════════════════

def test_a_two_rate_document_becomes_two_lines_each_at_its_own_rate(live):
    items = [{"num": 1, "rt": 5.0, "txval": 1000.0, "cgst": 25.0, "sgst": 25.0, "igst": 0},
             {"num": 2, "rt": 18.0, "txval": 2000.0, "cgst": 180.0, "sgst": 180.0, "igst": 0}]
    store, _db, _data = _setup(live, raw=_raw([_inv(items=items)]))
    out = _draft()["data"]
    assert out["agrees_with_2b"] is True, out["differences"]
    assert sorted(l["gst_rate_bps"] for l in store["purchase_bill_lines"]) == [500, 1800]
    (bill,) = store["purchase_bills"]
    assert bill["taxable_amount_paise"] == 3_00_000
    assert bill["cgst_paise"] == 20_500 and bill["sgst_paise"] == 20_500, (
        "an effective rate of 14.17% on one line would have been the guess")


def test_a_fractional_rate_survives_exactly(live):
    items = [{"num": 1, "rt": 0.25, "txval": 4000.0, "cgst": 5.0, "sgst": 5.0, "igst": 0}]
    store, _db, _data = _setup(live, raw=_raw([_inv(items=items)]))
    out = _draft()["data"]
    assert out["agrees_with_2b"] is True, out["differences"]
    assert store["purchase_bill_lines"][0]["gst_rate_bps"] == 25


def test_cess_is_carried_as_the_amount_the_file_states(live):
    items = [{"num": 1, "rt": 28.0, "txval": 1000.0, "cgst": 140.0, "sgst": 140.0,
              "igst": 0, "cess": 12.0}]
    store, _db, _data = _setup(live, raw=_raw([_inv(items=items)]))
    out = _draft()["data"]
    (bill,) = store["purchase_bills"]
    assert bill["cess_paise"] == 1_200
    assert out["agrees_with_2b"] is True, out["differences"]
    assert any("cess" in c and "lump sum" in c for c in out["caveats"])


def test_a_disagreement_between_the_engine_and_the_supplier_is_reported_never_corrected(live):
    """A vendor recorded in another State: the engine computes IGST, the supplier
    filed CGST + SGST. The draft keeps the engine's figure and says so."""
    wrong_state = {"id": "v1", "firm_id": FIRM, "client_id": CLIENT, "name": "Acme",
                   "gstin": SUPPLIER, "state_code": "27", "is_active": True,
                   "tds_applicable": False}
    store, _db, _data = _setup(live, vendors=[wrong_state])
    out = _draft()["data"]
    assert out["agrees_with_2b"] is False
    text = " ".join(out["differences"])
    assert "IGST" in text and "CGST" in text and "SGST" in text
    assert "inter-State" in text
    (bill,) = store["purchase_bills"]
    assert bill["igst_paise"] == 18_000 and bill["cgst_paise"] == 0, (
        "the engine's figure stands — overriding it to match the file would "
        "hide the thing the CA is there to look at")


def test_a_2b_marked_unavailable_is_still_draftable_and_says_the_credit_is_not(live):
    _store, _db, _data = _setup(live, raw=_raw([_inv(itcavl="N")]))
    out = _draft()["data"]
    assert any("UNAVAILABLE" in c for c in out["caveats"])


# ═════════════════════════════════════════════════════════════════════════════
# WHAT IS REFUSED, EACH WITH ITS OWN REASON — after the premise above
# ═════════════════════════════════════════════════════════════════════════════

def _refused(status, contains, **over):
    with pytest.raises(HTTPException) as e:
        _draft(**over)
    assert e.value.status_code == status, e.value.detail
    assert contains in e.value.detail, e.value.detail
    return e.value


def test_a_reverse_charge_document_is_refused_not_booked_as_an_ordinary_purchase(live):
    store, db, _data = _setup(live, raw=_raw([_inv(rev="Y")]))
    _refused(422, "REVERSE CHARGE")
    assert store["purchase_bills"] == [] and "purchase_bills" not in db.written_tables()


def test_the_reverse_charge_flag_is_read_off_the_file():
    assert parse_gstr2b(_raw([_inv(rev="Y")])).documents[0].reverse_charge is True
    assert parse_gstr2b(_raw([_inv(rev="N")])).documents[0].reverse_charge is False
    assert parse_gstr2b(_raw([_inv()])).documents[0].reverse_charge is False


def test_a_document_with_a_line_that_states_no_rate_is_refused_not_read_as_nil(live):
    items = [{"num": 1, "txval": 1000.0, "cgst": 90.0, "sgst": 90.0, "igst": 0}]
    store, _db, _data = _setup(live, raw=_raw([_inv(items=items)]))
    _refused(422, "states no GST rate")
    assert store["purchase_bills"] == []


def test_the_kept_file_must_agree_with_the_stored_row_to_the_paisa(live):
    store, _db, _data = _setup(live)
    store["gstr2a_records"][0]["cgst_paise"] += 1
    _refused(422, "does not agree")
    assert store["purchase_bills"] == []


def test_no_kept_file_means_no_draft_and_says_to_upload_again(live):
    store, _db, _data = _setup(live)
    store["gstr2b_uploads"].clear()
    _refused(422, "No copy of the GSTR-2B file is kept")


def test_a_kept_file_that_does_not_contain_the_document_is_refused(live):
    store, _db, _data = _setup(live)
    other = _raw([_inv(inum="INV-OTHER")])
    store["gstr2b_uploads"][0]["raw_data"] = other
    _refused(422, "does not contain this document")


def test_the_newest_reconciled_upload_is_the_one_used(live):
    store, db, _data = _setup(live, raw=_raw([_inv(inum="OLD-1")]))
    # the CA uploads a corrected file for the same month: it replaces the rows
    _upload(_raw([_inv(inum=NUMBER)]))
    assert [u["status"] for u in store["gstr2b_uploads"]] == ["reconciled", "reconciled"]
    assert _draft()["success"] is True


@pytest.mark.parametrize("sec,typ,words", [
    ("b2ba", "invoice", "AMENDMENT"),
    ("cdnr", "credit_note", "CREDIT NOTE"),
    ("cdnr", "debit_note", "DEBIT NOTE"),
    ("impg", "bill_of_entry", "Bill of Entry"),
])
def test_a_document_that_is_not_an_ordinary_invoice_is_refused_with_its_own_reason(
        live, sec, typ, words):
    _setup(live)
    assert words in draft_bill_from_2b.refusal_for_kind(sec, typ)
    _refused(422, words, section=sec, document_type=typ)


def test_the_screen_is_told_which_rows_are_not_offered_a_draft(live):
    raw = _raw(cdnr=[{"ctin": SUPPLIER, "nt": [
        {"ntnum": "CN-1", "ntdt": "28-04-2025", "typ": "C", "val": 118.0,
         "itms": [{"rt": 18.0, "txval": 100.0, "cgst": 9.0, "sgst": 9.0}]}]}])
    _store, _db, data = _setup(live, raw=raw)
    by_doc = {m["document_number"]: m for m in data["matches"]
              if m["status"] == "missing_in_books"}
    assert by_doc[NUMBER]["draft_bill_offered"] is True
    assert by_doc["CN-1"]["draft_bill_offered"] is False
    assert "CREDIT NOTE" in by_doc["CN-1"]["draft_bill_refusal"]
    # and a row that is not missing_in_books is never offered one
    for m in data["matches"]:
        if m["status"] != "missing_in_books":
            assert m["draft_bill_offered"] is False and m["draft_bill_refusal"] is None


def test_no_supplier_with_that_gstin_is_refused_and_named_not_invented(live):
    store, db, _data = _setup(live, vendors=[])
    _refused(422, f"No supplier on this client's books carries GSTIN {SUPPLIER}")
    assert store["purchase_bills"] == [] and "vendors" not in db.written_tables()


def test_two_live_suppliers_with_the_gstin_refuse_rather_than_pick_one(live):
    twin = lambda i: {"id": f"v{i}", "firm_id": FIRM, "client_id": CLIENT,
                      "name": f"Acme {i}", "gstin": SUPPLIER, "state_code": "29",
                      "is_active": True, "tds_applicable": False}
    store, _db, _data = _setup(live, vendors=[twin(1), twin(2)])
    _refused(422, "More than one supplier")
    assert store["purchase_bills"] == []


def test_a_vendor_of_another_client_is_not_used(live):
    foreign = {"id": "v9", "firm_id": FIRM, "client_id": "client-2", "name": "Acme",
               "gstin": SUPPLIER, "state_code": "29", "is_active": True,
               "tds_applicable": False}
    store, _db, _data = _setup(live, vendors=[foreign])
    _refused(422, "No supplier on this client's books")


def test_a_document_already_matched_to_a_bill_has_nothing_to_draft(live):
    bill = {"id": "b1", "firm_id": FIRM, "client_id": CLIENT, "vendor_id": "v1",
            "bill_no": NUMBER, "bill_date": "2025-04-24",
            "taxable_amount_paise": 1_00_000, "cgst_paise": 9_000, "sgst_paise": 9_000,
            "igst_paise": 0, "status": "received", "deleted_at": None}
    store, _db, data = _setup(live, bills=[bill])
    assert data["summary"]["matched_count"] == 1
    _refused(409, "already matched to bill", )
    assert len(store["purchase_bills"]) == 1


def test_a_locked_period_refuses_the_draft_through_the_ordinary_bill_engine(live, monkeypatch):
    store, _db, _data = _setup(live)

    def locked(*_a, **_k):
        raise HTTPException(status_code=422, detail="April 2025's GSTR-3B has been filed.")

    monkeypatch.setattr(pb.period_lock_service, "assert_open", locked)
    _refused(422, "GSTR-3B has been filed")
    assert store["purchase_bills"] == [], "the lock is the bill engine's, and it applies"


def test_a_document_on_another_clients_reconciliation_is_not_found(live):
    store, _db, _data = _setup(live)
    with pytest.raises(HTTPException) as e:
        _draft(client_id="client-2")
    assert e.value.status_code == 404


def test_a_row_of_another_firm_is_not_found(live):
    store, _db, _data = _setup(live)
    store["gstr2a_records"][0]["firm_id"] = "firm-2"
    _refused(404, "No such document")


def test_the_request_names_the_document_and_never_an_amount():
    """A caller cannot draft a bill for a figure the portal never carried."""
    assert set(pb.BillFrom2BIn.model_fields) == {
        "client_id", "period", "section", "document_type",
        "supplier_gstin", "document_number"}


def test_a_period_that_is_not_a_month_is_refused(live):
    _setup(live)
    _refused(422, "MMYYYY", period="2025-04")


def test_the_route_needs_the_accounting_write_permission_and_the_client_scope():
    import inspect
    src = inspect.getsource(pb.create_bill_from_2b)
    assert "assert_client_access(current_user, data.client_id)" in src
    dep = inspect.signature(pb.create_bill_from_2b).parameters["current_user"].default
    assert dep.dependency.__qualname__.startswith("rbac"), dep.dependency
    assert "receive" not in src.replace("receive it", "").replace(
        "received", "").replace("/receive", "").replace("receiving", ""), (
        "drafting must never call the receive path")


def test_no_purchase_bill_receive_is_ever_called_by_drafting(live, monkeypatch):
    _setup(live)

    def boom(*_a, **_k):
        raise AssertionError("the draft path received a bill")

    monkeypatch.setattr(pb, "receive_purchase_bill", boom)
    assert _draft()["success"] is True
