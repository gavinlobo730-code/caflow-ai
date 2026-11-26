"""gst-15 — a radar of the credit not yet claimed, each row with the date CGST
§16(4) takes it away, nearest first.

WHAT WAS MISSING
    `correction_window` has answered "when does this year's window close" since
    GST-09, and says in its own docstring that one window governs amendments and
    unclaimed credit alike. Nothing laid that date against the credit. A CA could
    see, bill by bill, that a supplier had not filed; nothing said which of those
    credits would be GONE on 30 November if they still had not.

THE VERIFY LINE
    "A test with an FY 2025-26 bill unmatched asserts a lapse date of 30-11-2026,
    or the GSTR-9 furnished date if earlier, and lists it ahead of a later one; a
    matched and claimed bill does not appear."  Both halves are below, over rows
    written by the REAL reconciliation (so the radar reads what production
    stores) and the real §16(2)(aa) pass.

THE SHAPE OF THESE TESTS
    Each exclusion is preceded by the premise that the SAME bill, unmatched, is on
    the radar. Otherwise "does not appear" passes on a radar that lists nothing.
"""
from __future__ import annotations

import ast
import inspect
from datetime import date

import pytest

import routers.gst_workspace as gw
from domain.gst import correction_window as cw
from domain.gst import itc_time_bar as bar
from services import gst_2b_reconciliation_service as recon
from services import itc_time_bar_service as svc

FIRM, CLIENT = "firm-1", "client-1"
CLIENT_GSTIN = "29AAACX1234C1ZP"
SUPPLIER = "29AAAAA1111A1Z5"
AS_OF = date(2026, 10, 1)


class _R:
    def __init__(self, data):
        self.data = data


class _Q:
    def __init__(self, db, table):
        self.db, self.table = db, table
        self.rows = list(db.store.get(table, []))
        self._op, self._payload = None, None
        self.filters = []

    def select(self, cols="*", *_a, **_k):
        self.filters.append(("select", cols))
        return self

    def order(self, *_a, **_k): return self

    def limit(self, n):
        self.rows = self.rows[:n]
        return self

    def eq(self, k, v):
        self.filters.append(("eq", k))
        self.rows = [r for r in self.rows if str(r.get(k)) == str(v)]
        return self

    def in_(self, k, vals):
        self.filters.append(("in_", k))
        vals = {str(v) for v in vals}
        self.rows = [r for r in self.rows if str(r.get(k)) in vals]
        return self

    def is_(self, k, _v):
        self.filters.append(("is_", k))
        self.rows = [r for r in self.rows if r.get(k) is None]
        return self

    def gte(self, k, v):
        self.filters.append(("gte", k))
        self.rows = [r for r in self.rows if str(r.get(k) or "") >= v]
        return self

    def lte(self, k, v):
        self.filters.append(("lte", k))
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
        self.db.queries.append((self.table, list(self.filters)))
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
        self.store, self.writes, self.queries = store, [], []

    def table(self, name):
        return _Q(self, name)


def _bill(bid, number, bill_date, *, cgst=9_000, sgst=9_000, status="received",
          created="2025-01-01T00:00:00+00:00", **extra):
    return {"id": bid, "firm_id": FIRM, "client_id": CLIENT, "vendor_id": "v1",
            "bill_no": number, "bill_date": bill_date, "status": status,
            "taxable_amount_paise": 1_00_000, "cgst_paise": cgst, "sgst_paise": sgst,
            "igst_paise": 0, "cess_paise": 0, "is_opening": False,
            "is_reverse_charge": False, "deleted_at": None, "created_at": created,
            "ineligible_itc_igst_paise": 0, "ineligible_itc_cgst_paise": 0,
            "ineligible_itc_sgst_paise": 0, "ineligible_itc_cess_paise": 0, **extra}


def _file(period, docs):
    """docs: [(number, dd-mm-yyyy, itcavl)] — each Rs 1,000 + 18%."""
    invs = [{"inum": n, "dt": dt, "val": 1180.0, "itcavl": avl,
             "items": [{"num": 1, "rt": 18.0, "txval": 1000.0, "cgst": 90.0,
                        "sgst": 90.0, "igst": 0}]} for n, dt, avl in docs]
    return {"data": {"gstin": CLIENT_GSTIN, "rtnprd": period, "gendt": "14-07-2025",
                     "docdata": {"b2b": [{"ctin": SUPPLIER, "trdnm": "Acme Supplies",
                                          "supfildt": "10-07-2025", "inv": invs}]}}}


def _world(bills, gstr9=None):
    return {
        "vendors": [{"id": "v1", "firm_id": FIRM, "name": "Acme Supplies",
                     "gstin": SUPPLIER}],
        "purchase_bills": list(bills),
        "gstr2a_records": [], "gstr2b_reconciliations": [],
        "gstr1_returns": list(gstr9 or []),
    }


def _reconcile(store, period, docs):
    out = recon.reconcile_2b(_DB(store), firm_id=FIRM, client_id=CLIENT,
                             period=period, raw=_file(period, docs))
    assert out["persisted"] is True
    return out


def _radar(store, as_of=AS_OF):
    db = _DB(store)
    return svc.radar(db, firm_id=FIRM, client_id=CLIENT, as_of=as_of), db


def _labels(out):
    return [i["label"] for i in out["items"]]


def _standard():
    """FY 2025-26 (lapses 30 Nov 2026) and FY 2026-27 (30 Nov 2027), one unfiled
    bill in each, a matched bill and the rest of the cast."""
    bills = [
        _bill("b-unfiled-a", "A-UNFILED", "2025-06-10"),                 # FY 2025-26
        _bill("b-matched", "A-MATCHED", "2025-06-12"),
        _bill("b-unfiled-b", "B-UNFILED", "2026-05-05"),                 # FY 2026-27
    ]
    store = _world(bills)
    _reconcile(store, "062025", [("A-MATCHED", "12-06-2025", "Y")])
    _reconcile(store, "052026", [])
    return store


# ═════════════════════════════════════════════════════════════════════════════
# THE VERIFY LINE
# ═════════════════════════════════════════════════════════════════════════════

def test_an_unmatched_bill_of_fy_2025_26_lapses_on_30_november_2026_and_leads_a_later_one():
    out, _db = _radar(_standard())
    rows = {i["label"]: i for i in out["items"]}

    early = rows["A-UNFILED"]
    assert early["closes_on"] == "2026-11-30"
    assert early["financial_year"] == "2025-26"
    assert early["days_left"] == 60 and early["status"] == "open"
    assert early["shortened_by_annual_return"] is False
    assert early["credit_at_risk_paise"] == 18_000
    assert early["verdict"] == "not_in_2b" and early["kind"] == "withheld_bill"

    later = rows["B-UNFILED"]
    assert later["closes_on"] == "2027-11-30" and later["financial_year"] == "2026-27"

    # nearest first
    assert _labels(out) == ["A-UNFILED", "B-UNFILED"]


def test_a_matched_and_claimed_bill_does_not_appear():
    out, _db = _radar(_standard())
    assert "A-MATCHED" not in _labels(out)
    # the premise: the SAME bill, left unmatched, IS on the radar
    store = _world([_bill("b-matched", "A-MATCHED", "2025-06-12")])
    _reconcile(store, "062025", [])
    assert "A-MATCHED" in _labels(_radar(store)[0])


def test_the_gstr9_date_wins_when_it_is_earlier():
    filed = [{"firm_id": FIRM, "client_id": CLIENT, "return_type": "gstr9",
              "status": "submitted", "financial_year": "2025-26",
              "submitted_at": "2026-08-14T05:00:00+00:00"}]
    store = _standard()
    store["gstr1_returns"] = filed
    out, _db = _radar(store)
    rows = {i["label"]: i for i in out["items"]}
    assert rows["A-UNFILED"]["closes_on"] == "2026-08-14"
    assert rows["A-UNFILED"]["shortened_by_annual_return"] is True
    assert rows["A-UNFILED"]["status"] == "closed" and rows["A-UNFILED"]["days_left"] < 0
    # the other year is NOT shortened by this year's return
    assert rows["B-UNFILED"]["closes_on"] == "2027-11-30"
    assert rows["B-UNFILED"]["shortened_by_annual_return"] is False
    assert out["totals"]["lapsed_paise"] == 18_000 and out["totals"]["open_paise"] == 18_000


def test_a_gstr9_filed_AFTER_30_november_does_not_extend_the_window():
    store = _standard()
    store["gstr1_returns"] = [{"firm_id": FIRM, "client_id": CLIENT, "return_type": "gstr9",
                               "status": "submitted", "financial_year": "2025-26",
                               "submitted_at": "2026-12-31T05:00:00+00:00"}]
    rows = {i["label"]: i for i in _radar(store)[0]["items"]}
    assert rows["A-UNFILED"]["closes_on"] == "2026-11-30"


def test_a_gstr9_furnished_late_at_night_utc_is_the_next_day_in_india():
    """20:00 UTC on 29 November is 01:30 IST on 30 November: the window closes on
    the Indian date, and a UTC read would put it a day early."""
    store = _standard()
    store["gstr1_returns"] = [{"firm_id": FIRM, "client_id": CLIENT, "return_type": "gstr9",
                               "status": "submitted", "financial_year": "2025-26",
                               "submitted_at": "2026-11-29T20:00:00+00:00"}]
    rows = {i["label"]: i for i in _radar(store)[0]["items"]}
    # 30 November IST equals the statutory date, so it is NOT 'shortened' — and
    # a UTC read (29 November) would have been.
    assert rows["A-UNFILED"]["closes_on"] == "2026-11-30"
    assert rows["A-UNFILED"]["shortened_by_annual_return"] is False


# ═════════════════════════════════════════════════════════════════════════════
# THE YEAR IS THE DOCUMENT'S
# ═════════════════════════════════════════════════════════════════════════════

def test_31_march_and_1_april_fall_in_different_years_with_different_dates():
    bills = [_bill("m", "MARCH", "2026-03-31"), _bill("a", "APRIL", "2026-04-01")]
    store = _world(bills)
    _reconcile(store, "032026", [])
    _reconcile(store, "042026", [])
    rows = {i["label"]: i for i in _radar(store)[0]["items"]}
    assert rows["MARCH"]["closes_on"] == "2026-11-30"
    assert rows["APRIL"]["closes_on"] == "2027-11-30"


def test_the_window_is_the_invoices_not_the_months_it_would_be_claimed_in():
    """A March invoice recorded in June still lapses with the year it pertains to."""
    store = _world([_bill("m", "MARCH-LATE", "2026-03-31", created="2026-06-20T00:00:00+00:00")])
    _reconcile(store, "032026", [])
    # reconcile stamps now(); the bill was created BEFORE it, so it was examined
    store["gstr2b_reconciliations"][0]["reconciled_at"] = "2026-07-01T00:00:00+00:00"
    (row,) = _radar(store)[0]["items"]
    assert row["financial_year"] == "2025-26" and row["closes_on"] == "2026-11-30"


# ═════════════════════════════════════════════════════════════════════════════
# STATUS, AND WHAT IS READ AT ALL
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("as_of,status,days", [
    (date(2026, 10, 1), "open", 60),
    (date(2026, 11, 1), "closing_soon", 29),
    (date(2026, 11, 30), "closing_soon", 0),
    (date(2026, 12, 1), "closed", -1),
])
def test_status_follows_the_one_window_authority(as_of, status, days):
    out, _db = _radar(_standard(), as_of=as_of)
    row = next(i for i in out["items"] if i["label"] == "A-UNFILED")
    assert (row["status"], row["days_left"]) == (status, days)
    # and it agrees with correction_window, which is where the rule lives
    win = cw.window_for("062025", as_of=as_of)
    assert (win["status"], win["days_left"]) == (status, days)


def test_a_window_that_closed_just_now_is_still_reported_not_hidden():
    out, _db = _radar(_standard(), as_of=date(2026, 12, 15))
    row = next(i for i in out["items"] if i["label"] == "A-UNFILED")
    assert row["status"] == "closed"
    assert out["totals"]["lapsed_paise"] == 18_000


def test_a_window_that_closed_long_ago_is_history_and_is_not_read():
    out, db = _radar(_standard(), as_of=date(2027, 3, 1))
    assert "A-UNFILED" not in _labels(out)
    assert out["scanned_financial_years"] == ["2026-27"]
    # and the books were not even asked for the old year's bills
    for table, filters in db.queries:
        if table == "purchase_bills":
            assert ("gte", "bill_date") in filters and ("lte", "bill_date") in filters


def test_the_reads_are_bounded_scoped_and_narrow():
    _out, db = _radar(_standard())
    bills_reads = [f for t, f in db.queries if t == "purchase_bills"]
    assert bills_reads, "the radar must read the bills"
    for f in bills_reads:
        assert ("eq", "firm_id") in f and ("eq", "client_id") in f
        assert ("gte", "bill_date") in f and ("lte", "bill_date") in f
        assert not any(k == "select" and v.strip() == "*" for k, v in f), (
            "a purchase-bill read is a narrow projection, never `*`")
    for table in ("gstr2a_records", "gstr2b_reconciliations"):
        for t, f in db.queries:
            if t == table:
                assert ("eq", "firm_id") in f and ("eq", "client_id") in f


def test_the_radar_writes_nothing():
    store = _standard()
    out, db = _radar(store)
    assert out["items"]
    assert db.writes == []


# ═════════════════════════════════════════════════════════════════════════════
# WHAT IS NOT A DEADLINE
# ═════════════════════════════════════════════════════════════════════════════

def test_a_bill_the_portal_itself_blocked_is_counted_and_carries_no_date():
    bills = [_bill("b-blocked", "BLOCKED", "2025-06-10")]
    store = _world(bills)
    _reconcile(store, "062025", [("BLOCKED", "10-06-2025", "N")])
    out, _db = _radar(store)
    assert out["items"] == []
    assert out["blocked_by_2b_count"] == 1
    assert any("marks their credit unavailable" in n for n in out["notes"])


def test_a_bill_recorded_after_its_months_reconciliation_is_named_not_counted_at_risk():
    bills = [_bill("late", "LATE", "2025-06-10", created="2099-01-01T00:00:00+00:00")]
    store = _world(bills)
    _reconcile(store, "062025", [])
    out, _db = _radar(store)
    assert out["items"] == [] and out["not_assessed_count"] == 1
    assert any("recorded after" in n for n in out["notes"])


def test_a_reverse_charge_bill_is_self_assessed_and_not_on_the_radar():
    store = _world([_bill("rc", "RCM", "2025-06-10", is_reverse_charge=True)])
    _reconcile(store, "062025", [])
    assert _labels(_radar(store)[0]) == []


def test_credit_section_17_5_blocks_was_never_credit_and_is_not_at_risk():
    blocked = _bill("b17", "BLOCKED-17-5", "2025-06-10",
                    ineligible_itc_cgst_paise=9_000, ineligible_itc_sgst_paise=9_000)
    half = _bill("h17", "HALF-17-5", "2025-06-11", ineligible_itc_cgst_paise=4_000)
    store = _world([blocked, half])
    _reconcile(store, "062025", [])
    out, _db = _radar(store)
    assert _labels(out) == ["HALF-17-5"], "a bill whose whole tax is §17(5) has nothing to lose"
    assert out["items"][0]["credit_at_risk_paise"] == 14_000, "net of the blocked 4,000"


def test_a_carried_over_opening_bill_is_not_on_the_radar():
    store = _world([_bill("op", "OPENING", "2025-06-10", is_opening=True)])
    _reconcile(store, "062025", [])
    assert _labels(_radar(store)[0]) == []
    store2 = _world([_bill("op", "OPENING", "2025-06-10")])
    _reconcile(store2, "062025", [])
    assert _labels(_radar(store2)[0]) == ["OPENING"], "premise: an ordinary bill is"


def test_a_cancelled_and_a_draft_bill_are_not_credit_at_all():
    store = _world([_bill("c", "CANCELLED", "2025-06-10", status="cancelled"),
                    _bill("d", "DRAFT", "2025-06-11", status="draft")])
    _reconcile(store, "062025", [])
    assert _labels(_radar(store)[0]) == []


def test_a_bill_over_what_the_supplier_filed_is_on_the_radar_for_the_excess_only():
    bills = [_bill("over", "OVER", "2025-06-10", cgst=12_000, sgst=12_000)]
    store = _world(bills)
    _reconcile(store, "062025", [("OVER", "10-06-2025", "Y")])   # 2B carries 9,000 + 9,000
    (row,) = _radar(store)[0]["items"]
    assert row["verdict"] == "more_than_2b"
    assert row["credit_at_risk_paise"] == 6_000


# ═════════════════════════════════════════════════════════════════════════════
# CREDIT THE SUPPLIER FILED AND NOBODY BOOKED
# ═════════════════════════════════════════════════════════════════════════════

def test_a_2b_document_with_no_bill_is_on_the_radar_with_the_same_date():
    store = _world([])
    _reconcile(store, "062025", [("NOBODY-BOOKED", "12-06-2025", "Y")])
    (row,) = _radar(store)[0]["items"]
    assert row["kind"] == "not_booked" and row["label"] == "NOBODY-BOOKED"
    assert row["closes_on"] == "2026-11-30" and row["credit_at_risk_paise"] == 18_000
    assert row["supplier_gstin"] == SUPPLIER and row["return_period"] == "062025"


def test_an_unbooked_document_the_portal_marks_unavailable_is_not_offered():
    store = _world([])
    _reconcile(store, "062025", [("BLOCKED-DOC", "12-06-2025", "N")])
    assert _radar(store)[0]["items"] == []


def test_credit_notes_and_imports_are_not_credit_to_lose():
    raw = _file("062025", [])
    raw["data"]["docdata"]["cdnr"] = [{"ctin": SUPPLIER, "nt": [
        {"ntnum": "CN-1", "ntdt": "20-06-2025", "typ": "C", "val": 118.0,
         "itms": [{"rt": 18.0, "txval": 100.0, "cgst": 9.0, "sgst": 9.0}]}]}]
    raw["data"]["docdata"]["impg"] = [{"boenum": "7654321", "boedt": "21-06-2025",
                                       "txval": 50000, "igst": 9000}]
    store = _world([])
    recon.reconcile_2b(_DB(store), firm_id=FIRM, client_id=CLIENT, period="062025", raw=raw)
    assert {r["document_type"] for r in store["gstr2a_records"]} == {"credit_note", "bill_of_entry"}
    assert _radar(store)[0]["items"] == []


# ═════════════════════════════════════════════════════════════════════════════
# MONTHS NOBODY RECONCILED
# ═════════════════════════════════════════════════════════════════════════════

def test_a_month_with_no_reconciliation_is_listed_as_a_month_with_its_own_date():
    out, _db = _radar(_standard())
    months = {m["period"]: m for m in out["periods_not_reconciled"]}
    assert "072025" in months and "062025" not in months and "052026" not in months
    assert months["072025"]["closes_on"] == "2026-11-30"
    assert months["072025"]["financial_year"] == "2025-26"
    assert months["042026"]["closes_on"] == "2027-11-30"
    assert any("no GSTR-2B reconciled" in n for n in out["notes"])
    # sorted by the date they lapse, then chronologically within it
    dates = [m["closes_on"] for m in out["periods_not_reconciled"]]
    assert dates == sorted(dates)


def test_a_month_whose_2b_does_not_exist_yet_is_not_called_unreconciled():
    out, _db = _radar(_standard())                       # as at 1 Oct 2026
    periods = {m["period"] for m in out["periods_not_reconciled"]}
    assert "082026" in periods                           # generated on 14 Sep
    assert "092026" not in periods and "102026" not in periods   # not yet
    out, _db = _radar(_standard(), as_of=date(2026, 10, 14))
    assert "092026" in {m["period"] for m in out["periods_not_reconciled"]}


def test_bills_in_an_unreconciled_month_are_not_judged():
    store = _world([_bill("u", "UNJUDGED", "2025-07-10")])
    out, _db = _radar(store)
    assert out["items"] == [], "nobody asked §16(2)(aa) of it, so it is neither safe nor at risk"
    assert "072025" in {m["period"] for m in out["periods_not_reconciled"]}


# ═════════════════════════════════════════════════════════════════════════════
# ORDER, SUMMARY, AND WHERE THE RULE LIVES
# ═════════════════════════════════════════════════════════════════════════════

def test_the_order_is_nearest_date_then_larger_credit_then_older_and_is_total():
    bills = [
        _bill("s", "SMALL", "2025-06-10", cgst=1_000, sgst=1_000),
        _bill("l", "LARGE", "2025-06-11", cgst=50_000, sgst=50_000),
        _bill("n", "NEXT-YEAR", "2026-05-05", cgst=90_000, sgst=90_000),
    ]
    store = _world(bills)
    _reconcile(store, "062025", [])
    _reconcile(store, "052026", [])
    assert _labels(_radar(store)[0]) == ["LARGE", "SMALL", "NEXT-YEAR"]
    again = _labels(_radar(store)[0])
    assert again == ["LARGE", "SMALL", "NEXT-YEAR"], "the same register reads the same each time"


def test_the_summary_adds_up_by_year_and_by_status():
    out, _db = _radar(_standard())
    years = {y["financial_year"]: y for y in out["by_financial_year"]}
    assert years["2025-26"]["count"] == 1 and years["2025-26"]["closes_on"] == "2026-11-30"
    assert years["2026-27"]["credit_at_risk_paise"] == 18_000
    assert out["totals"]["credit_at_risk_paise"] == 36_000
    assert out["totals"]["open_paise"] == 36_000
    assert out["totals"]["closing_soon_paise"] == 0 and out["totals"]["lapsed_paise"] == 0
    assert out["scanned_financial_years"] == ["2025-26", "2026-27"]
    assert [y["closes_on"] for y in out["by_financial_year"]] == ["2026-11-30", "2027-11-30"]


def test_the_matching_is_per_month_and_the_answer_says_so():
    out, _db = _radar(_standard())
    assert any("OWN month" in n for n in out["notes"])


def test_the_date_is_never_restated_here_the_one_window_authority_answers():
    tree = ast.parse(inspect.getsource(bar))
    calls = {n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
             for n in ast.walk(tree) if isinstance(n, ast.Call)}
    assert "window_for" in calls
    assert "november_30_cutoff" not in calls
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "date":
            args = [a.value for a in n.args if isinstance(a, ast.Constant)]
            assert args[-2:] != [11, 30], "30 November is correction_window's to know"
    service_src = inspect.getsource(svc)
    assert "november_30" not in service_src and "11, 30" not in service_src


def test_a_gstr9_lookup_failure_falls_back_to_the_statutory_date_and_does_not_500(monkeypatch):
    filed = [{"firm_id": FIRM, "client_id": CLIENT, "return_type": "gstr9",
              "status": "submitted", "financial_year": "2025-26",
              "submitted_at": "2026-08-14T05:00:00+00:00"}]
    store = _standard()
    store["gstr1_returns"] = filed
    # PREMISE: with the lookup working, the early GSTR-9 shortens the window.
    assert next(i for i in _radar(store)[0]["items"]
                if i["label"] == "A-UNFILED")["closes_on"] == "2026-08-14"

    from services import gst_amendment_service as gas

    def boom(*_a, **_k):
        raise RuntimeError("down")

    monkeypatch.setattr(gas, "annual_returns_filed", boom)
    out, _db = _radar(store)            # does not raise
    assert next(i for i in out["items"] if i["label"] == "A-UNFILED")["closes_on"] == "2026-11-30"


# ═════════════════════════════════════════════════════════════════════════════
# THE ROUTE
# ═════════════════════════════════════════════════════════════════════════════

def test_the_route_is_registered_scoped_and_needs_gst_read():
    paths = {(m, r.path) for r in gw.router.routes for m in getattr(r, "methods", ())}
    assert ("GET", "/api/gst-workspace/itc/time-bar") in paths
    src = inspect.getsource(gw.itc_time_bar)
    assert "assert_client_access(current_user, client_id)" in src
    dep = inspect.signature(gw.itc_time_bar).parameters["current_user"].default
    assert dep.dependency.__qualname__.startswith("rbac")


def test_the_route_answers_for_the_indian_date_and_the_callers_firm(monkeypatch):
    import core.supabase_client as sc
    store = _standard()
    db = _DB(store)
    monkeypatch.setattr(gw, "_USE_MOCK", False)
    monkeypatch.setattr(sc, "get_supabase", lambda: db)
    monkeypatch.setattr(gw, "assert_client_access", lambda *_a, **_k: None)
    monkeypatch.setattr(gw, "ist_today", lambda: AS_OF)
    out = gw.itc_time_bar(client_id=CLIENT, current_user={"firm_id": FIRM, "role": "Partner"})
    assert out["success"] is True
    assert out["data"]["as_of"] == "2026-10-01"
    assert [i["label"] for i in out["data"]["items"]] == ["A-UNFILED", "B-UNFILED"]


def test_another_firms_data_is_never_read(monkeypatch):
    store = _standard()
    for b in store["purchase_bills"]:
        b["firm_id"] = "firm-2"
    out, _db = _radar(store)
    assert out["items"] == []


def test_mock_mode_says_nothing_was_read(monkeypatch):
    monkeypatch.setattr(gw, "_USE_MOCK", True)
    monkeypatch.setattr(gw, "assert_client_access", lambda *_a, **_k: None)
    out = gw.itc_time_bar(client_id=CLIENT, current_user={"firm_id": FIRM, "role": "Partner"})
    assert out["data"]["items"] == []
    assert "without a database" in out["data"]["notes"][0]


# ═════════════════════════════════════════════════════════════════════════════
# A BILL FURNISHED IN A LATER MONTH'S 2B IS ONE ROW (POST-A-062)
# ═════════════════════════════════════════════════════════════════════════════
#
# The reconciliation matches a 2B month against that month's bills only, so an April bill the supplier furnished in June's 2B reads
# `not_in_2b` in April and its document reads `missing_in_books` in June. The radar listed both and counted the credit twice.

def _late_store(*, june_docs=(("A-LATE", "10-04-2025", "Y"),), april_bills=None):
    bills = april_bills if april_bills is not None else [_bill("b-late", "A-LATE", "2025-04-10")]
    store = _world(bills)
    _reconcile(store, "042025", [])
    _reconcile(store, "062025", list(june_docs))
    return store


def test_a_bill_furnished_in_a_later_months_2b_is_one_row_that_names_the_month():
    out, _db = _radar(_late_store())
    (row,) = out["items"]
    assert row["kind"] == bar.KIND_FURNISHED_LATER and row["verdict"] == bar.KIND_FURNISHED_LATER
    assert row["label"] == "A-LATE" and row["document_id"] == "b-late"
    assert row["document_date"] == "2025-04-10" and row["closes_on"] == "2026-11-30", "the bill's own date decides the year"
    assert row["return_period"] == "062025" and row["supplier_gstin"] == SUPPLIER
    assert row["credit_at_risk_paise"] == 18_000 and row["furnished_credit_paise"] == 18_000
    assert "June 2025" in row["reason"] and "paise" not in row["reason"]
    assert out["totals"]["credit_at_risk_paise"] == 18_000, "the credit is counted once"


def test_the_premise_without_a_later_document_the_bill_is_withheld_and_without_a_bill_the_document_is_unbooked():
    alone = _late_store(june_docs=())
    assert [(i["kind"], i["label"]) for i in _radar(alone)[0]["items"]] == [("withheld_bill", "A-LATE")]
    unbooked = _late_store(april_bills=[])
    assert [(i["kind"], i["label"]) for i in _radar(unbooked)[0]["items"]] == [("not_booked", "A-LATE")]


def test_the_number_is_folded_the_way_the_reconciliation_folds_it():
    store = _late_store(june_docs=(("a/late", "10-04-2025", "Y"),), april_bills=[_bill("b-late", "A-LATE", "2025-04-10")])
    (row,) = _radar(store)[0]["items"]
    assert row["kind"] == bar.KIND_FURNISHED_LATER


@pytest.mark.parametrize("june_docs, why", [
    ((("A-LATE", "10-04-2025", "N"),), "a document 2B marks unavailable is not credit on offer"),
    ((("A-OTHER", "10-04-2025", "Y"),), "another number"),
])
def test_a_document_that_is_not_the_bills_is_not_joined(june_docs, why):
    labels = sorted((i["kind"], i["label"]) for i in _radar(_late_store(june_docs=june_docs))[0]["items"])
    assert ("withheld_bill", "A-LATE") in labels, why


def test_another_suppliers_document_of_the_same_number_is_not_joined():
    store = _late_store()
    store["vendors"][0]["gstin"] = "27BBBBB2222B1Z5"
    kinds = sorted(i["kind"] for i in _radar(store)[0]["items"])
    assert kinds == ["not_booked", "withheld_bill"]


def test_two_bills_of_one_number_are_ambiguous_and_both_stay_withheld():
    store = _late_store(april_bills=[_bill("b-late", "A-LATE", "2025-04-10"), _bill("b-late-2", "A-LATE", "2025-04-20")])
    kinds = sorted(i["kind"] for i in _radar(store)[0]["items"])
    assert kinds == ["not_booked", "withheld_bill", "withheld_bill"]


def test_a_document_in_an_earlier_month_than_the_bill_is_not_its_late_filing():
    bills = [_bill("b-may", "A-LATE", "2025-05-10")]
    store = _world(bills)
    _reconcile(store, "042025", [("A-LATE", "10-04-2025", "Y")])
    _reconcile(store, "052025", [])
    kinds = sorted(i["kind"] for i in _radar(store)[0]["items"])
    assert kinds == ["not_booked", "withheld_bill"]


def test_a_document_of_another_financial_year_that_reuses_the_bills_number_is_not_its_late_filing():
    """Rule 46(b) keeps a number unique within ONE financial year, and the scan spans two: a June 2025 bill '15' and the supplier's
    May 2026 invoice '15' are two documents. Joined, the CA was told the June 2025 credit is communicated when it is not."""
    store = _world([_bill("b-15", "15", "2025-06-10")])
    _reconcile(store, "062025", [])
    _reconcile(store, "052026", [("15", "10-05-2026", "Y")])
    rows = sorted((i["kind"], i["label"], i["document_date"], i["closes_on"]) for i in _radar(store)[0]["items"])
    assert rows == [("not_booked", "15", "2026-05-10", "2027-11-30"),
                    ("withheld_bill", "15", "2025-06-10", "2026-11-30")]


def test_a_march_bill_furnished_in_aprils_2b_is_still_its_late_filing_because_the_year_is_the_documents():
    """The year compared is the DOCUMENT's date, not the 2B month that carries it: a 20 March 2026 invoice furnished in April 2026's
    GSTR-2B is FY 2025-26 on both sides, and is joined."""
    store = _world([_bill("b-mar", "A-MAR", "2026-03-20")])
    _reconcile(store, "032026", [])
    _reconcile(store, "042026", [("A-MAR", "20-03-2026", "Y")])
    (row,) = _radar(store)[0]["items"]
    assert row["kind"] == bar.KIND_FURNISHED_LATER and row["return_period"] == "042026"
    assert row["financial_year"] == "2025-26" and row["closes_on"] == "2026-11-30"


def test_a_later_document_whose_date_cannot_be_read_is_not_joined_and_stays_unbooked():
    bill = {"kind": bar.KIND_WITHHELD, "verdict": "not_in_2b", "document_id": "b-1", "document_date": "2025-04-10",
            "credit_at_risk_paise": 18_000}
    doc = {"document_type": "invoice", "supplier_gstin": SUPPLIER, "invoice_number": "A-1", "return_period": "062025",
           "itc_available": "Y", "cgst_paise": 9_000, "sgst_paise": 9_000}
    keys = {"b-1": (SUPPLIER, "A-1")}
    for unreadable in (None, "", "10-04-2025", "not a date"):
        rows, unbooked = bar.join_furnished_later([bill], [{**doc, "invoice_date": unreadable}], keys)
        assert [r["kind"] for r in rows] == [bar.KIND_WITHHELD] and len(unbooked) == 1, unreadable
    rows, unbooked = bar.join_furnished_later([bill], [{**doc, "invoice_date": "2025-04-10"}], keys)   # the premise: a date joins
    assert [r["kind"] for r in rows] == [bar.KIND_FURNISHED_LATER] and unbooked == []


def test_a_document_of_another_year_does_not_make_the_bills_own_years_late_filing_ambiguous():
    """The other year's document is skipped BEFORE the one-bill/one-document test, so it neither joins nor blocks the one that does."""
    bill = {"kind": bar.KIND_WITHHELD, "verdict": "not_in_2b", "document_id": "b-1", "document_date": "2025-06-10",
            "credit_at_risk_paise": 18_000}
    base = {"document_type": "invoice", "supplier_gstin": SUPPLIER, "invoice_number": "15", "itc_available": "Y",
            "cgst_paise": 9_000, "sgst_paise": 9_000}
    this_year = {**base, "return_period": "092025", "invoice_date": "2025-06-10"}
    next_year = {**base, "return_period": "052026", "invoice_date": "2026-05-10"}
    rows, unbooked = bar.join_furnished_later([bill], [next_year, this_year], {"b-1": (SUPPLIER, "15")})
    assert [(r["kind"], r["return_period"]) for r in rows] == [(bar.KIND_FURNISHED_LATER, "092025")]
    assert unbooked == [next_year]


def test_a_later_document_for_less_tax_says_both_figures():
    bills = [_bill("b-late", "A-LATE", "2025-04-10", cgst=12_000, sgst=12_000)]
    store = _late_store(april_bills=bills)
    (row,) = _radar(store)[0]["items"]
    assert row["kind"] == bar.KIND_FURNISHED_LATER
    assert row["credit_at_risk_paise"] == 24_000 and row["furnished_credit_paise"] == 18_000
    assert "₹180.00" in row["reason"] and "₹240.00" in row["reason"]


# ═════════════════════════════════════════════════════════════════════════════
# THE DATABASE KEEPS ONLY WHAT COULD BE WITHHELD (POST-A-062, migration 616)
# ═════════════════════════════════════════════════════════════════════════════

class _RpcDB(_DB):
    """The double with the database function: it answers with the candidates it is given, as the function would."""

    def __init__(self, store, candidates, *, fail=False):
        super().__init__(store)
        self.candidates, self.fail, self.calls = candidates, fail, []

    def rpc(self, name, params):
        self.calls.append((name, params))
        db = self

        class _Call:
            def execute(self):
                if db.fail:
                    raise RuntimeError("function not found")
                return _R(db.candidates)
        return _Call()


def _candidate(bid, number, bill_date, **over):
    row = {"id": bid, "vendor_id": "v1", "vendor_name": "Acme Supplies", "vendor_gstin": SUPPLIER, "bill_no": number,
           "our_reference": None, "bill_date": bill_date, "is_reverse_charge": False, "examined": True,
           "igst_paise": 0, "cgst_paise": 9_000, "sgst_paise": 9_000, "cess_paise": 0,
           "matched": False, "blocked": False, "reason_code": "",
           "filed_igst_paise": 0, "filed_cgst_paise": 0, "filed_sgst_paise": 0, "filed_cess_paise": 0}
    row.update(over)
    return row


def test_with_the_function_the_bills_are_not_read_and_the_answer_is_the_same():
    store = _standard()
    expected = _radar(store)[0]
    db = _RpcDB(store, [_candidate("b-unfiled-a", "A-UNFILED", "2025-06-10"),
                        _candidate("b-unfiled-b", "B-UNFILED", "2026-05-05")])
    got = svc.radar(db, firm_id=FIRM, client_id=CLIENT, as_of=AS_OF)
    assert got == expected
    (name, params), = db.calls
    assert name == "itc_time_bar_candidates" and params["p_firm_id"] == FIRM and params["p_client_id"] == CLIENT
    assert params["p_periods"] == ["062025", "052026"] and params["p_from"] == "2025-04-01"
    assert not [t for t, _f in db.queries if t in ("purchase_bills", "vendors")], "the bills are the function's to read"


def test_the_functions_verdict_inputs_reach_the_same_pass():
    """A blocked candidate is counted and a candidate recorded after its reconciliation is named, from the function's own flags."""
    store = _standard()
    db = _RpcDB(store, [
        _candidate("b-blocked", "BLK", "2025-06-10", matched=True, blocked=True, reason_code="P",
                   filed_cgst_paise=9_000, filed_sgst_paise=9_000),
        _candidate("b-late-entry", "LATE-ENTRY", "2025-06-11", examined=False)])
    out = svc.radar(db, firm_id=FIRM, client_id=CLIENT, as_of=AS_OF)
    assert out["items"] == [] and out["blocked_by_2b_count"] == 1 and out["not_assessed_count"] == 1


def test_a_function_that_cannot_be_called_falls_back_to_reading_the_bills_and_says_so(caplog):
    store = _standard()
    expected = _radar(store)[0]
    db = _RpcDB(store, [], fail=True)
    with caplog.at_level("ERROR", logger="caflow.itc_time_bar"):
        got = svc.radar(db, firm_id=FIRM, client_id=CLIENT, as_of=AS_OF)
    assert got == expected
    assert any("itc_time_bar_candidates failed" in r.getMessage() for r in caplog.records)
    assert [t for t, _f in db.queries if t == "purchase_bills"], "the fallback reads the bills"


def test_every_kind_the_radar_answers_with_has_a_label_on_the_screen():
    """The screen indexes its label map by the row's kind, so a kind the server adds and the screen does not name renders as blank.
    Held from the side that owns the vocabulary."""
    import pathlib
    web = pathlib.Path(__file__).resolve().parents[2] / "web"
    screen = (web / "components" / "gst" / "ItcTimeBarRadar.tsx").read_text()
    types = (web / "lib" / "api" / "index.ts").read_text()
    kinds = {v for k, v in vars(bar).items() if k.startswith("KIND_")}
    assert kinds == {"withheld_bill", "not_booked", "furnished_later"}
    for kind in kinds:
        assert f'"{kind}"' in types, kind
        assert f"{kind}: \"" in screen, kind


def test_two_withheld_bills_of_one_number_in_different_years_each_join_only_their_own_years_document():
    """POST-A-460: the BILL side is keyed by its own financial year too. A June 2025 bill '15' and a June 2026 bill '15' of one supplier
    are two documents; when only the 2025 one is furnished late, it joins and the 2026 one stays withheld, and the credit is counted
    once. Keyed by supplier and number alone, the pair 'shared a key' and joined nothing, so the 2025 bill and its later 2B document
    both stayed as rows and that credit was counted twice."""
    store = _world([_bill("b-15a", "15", "2025-06-10"), _bill("b-15b", "15", "2026-06-10")])
    _reconcile(store, "062025", [])
    _reconcile(store, "082025", [("15", "10-06-2025", "Y")])
    _reconcile(store, "062026", [])
    out = _radar(store)[0]
    rows = sorted((i["kind"], i["document_date"]) for i in out["items"])
    assert rows == [(bar.KIND_FURNISHED_LATER, "2025-06-10"), ("withheld_bill", "2026-06-10")]
    assert out["totals"]["credit_at_risk_paise"] == 2 * 18_000, "each bill's credit once, the 2B document not again"


def test_two_withheld_bills_of_one_number_in_the_same_year_still_join_nothing():
    bill = {"kind": bar.KIND_WITHHELD, "verdict": "not_in_2b", "document_date": "2025-06-10", "credit_at_risk_paise": 18_000}
    doc = {"document_type": "invoice", "supplier_gstin": SUPPLIER, "invoice_number": "15", "return_period": "082025",
           "invoice_date": "2025-06-10", "itc_available": "Y", "cgst_paise": 9_000, "sgst_paise": 9_000}
    bills = [{**bill, "document_id": "b-1"}, {**bill, "document_id": "b-2", "document_date": "2025-07-01"}]
    rows, unbooked = bar.join_furnished_later(bills, [doc], {"b-1": (SUPPLIER, "15"), "b-2": (SUPPLIER, "15")})
    assert [r["kind"] for r in rows] == [bar.KIND_WITHHELD, bar.KIND_WITHHELD] and unbooked == [doc]
