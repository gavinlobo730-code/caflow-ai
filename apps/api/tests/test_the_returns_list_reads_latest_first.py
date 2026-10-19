"""A client's saved GST returns are listed latest period first, whatever order they were saved or approved in (found by seeding a filed year).

WHAT WAS WRONG
    `GET /api/gst-workspace/returns` read each store with `.range(offset, offset + limit - 1)` on a query with no ORDER BY.
    Postgres then returns rows in physical order, and a status change rewrites the row and moves it, so a return list
    showed April after November as soon as either was approved, January 2026 wherever it happened to land, and a client
    with more than fifty returns lost an arbitrary fifty with no word. The seeded firm's filing history, the first one
    to carry a year of approved returns, read: 04, 11, 05, 06 (2025). Paging by `.range()` over an unordered query is
    also the shape this repository has a rule against (a unique total ordering).

WHAT IS HELD
    * the stored period is put in time order by one function (`return_period.chronological_key`): 'MMYYYY' by year and
      then month, the annual 'FY2025-26' row after March of that year, anything unexpected before every real period and
      without raising;
    * the endpoint reads EVERY row the client has, orders them latest first with the id as the tie-break, and only then
      applies the window, so a window never repeats or skips a row between two requests;
    * the answer carries each store's total, so a screen showing a window can say "of N";
    * another client's and another firm's returns are not in it, and the return-type filter still filters;
    * the window is TWO reads, every row's id and period and then the full rows of the window only, because a return's
      payload grows with the client's volume and the first version read all of them to show fifty;
    * `GET /gst-workspace/filing-history` (the Filing History tab) had the same unordered `.range()` and is the same
      ordered window over the filed returns, with its own totals;
    * every row carries `period_order`, one integer, so the tab merges GSTR-1 and GSTR-3B on the server's ranking and
      does no period arithmetic (it used to sort by when each row was created, which is the order they were keyed in).
"""
from __future__ import annotations

import pytest

import routers.gst_workspace as gw
from domain.gst.return_period import chronological_key
from tests.e2e_harness import FakeDB, wire_e2e

FIRM, CLIENT = "FIRM-A", "CLIENT-1"
CALLER = {"firm_id": FIRM, "id": "u", "auth_user_id": "auth", "email": "ca@f.test", "role": "Partner"}


# ── the ordering rule ───────────────────────────────────────────────────────

@pytest.mark.parametrize("earlier,later", [
    ("042025", "112025"),        # within a year
    ("122025", "012026"),        # across the new year: '012026' is the LATER one though it sorts first as text
    ("032026", "FY2025-26"),     # the annual return belongs after the last month it covers
    ("FY2025-26", "042026"),
    ("garbage", "042025"),       # an unexpected period falls before every real one
    ("", "042025"),
    (None, "042025"),
])
def test_one_period_is_earlier_than_another(earlier, later):
    assert chronological_key(earlier) < chronological_key(later)


def test_an_unexpected_period_does_not_raise():
    for odd in ("13/2025", "2025-04", "FY", "FYabcd", 42, "00000"):
        assert isinstance(chronological_key(odd), tuple)


def test_the_text_order_of_a_period_is_not_its_time_order():
    periods = ["042025", "012026", "122025"]
    assert sorted(periods) != sorted(periods, key=chronological_key)


# ── the endpoint ────────────────────────────────────────────────────────────

@pytest.fixture
def db(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [gw])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    monkeypatch.setattr(gw, "_USE_MOCK", False)
    db.seed("clients", {"id": CLIENT, "firm_id": FIRM, "client_name": "Anand"})
    db.seed("clients", {"id": "CLIENT-2", "firm_id": FIRM, "client_name": "Other"})
    return db


def _row(table, period, client=CLIENT, firm=FIRM, **extra):
    return {"firm_id": firm, "client_id": client, "period": period, "status": "submitted", **extra}


def _periods(out, store):
    return [r["period"] for r in out["data"][store]]


def test_the_returns_come_back_latest_first_whatever_order_they_were_saved_in(db):
    # Saved scrambled, the way a year of approvals leaves a heap.
    for p in ("112025", "042025", "012026", "062025", "122025", "022026"):
        db.seed("gstr1_returns", _row("gstr1_returns", p, return_type="gstr1"))
        db.seed("gstr3b_returns", _row("gstr3b_returns", p))
    out = gw.list_returns(client_id=CLIENT, return_type=None, limit=50, offset=0, current_user=CALLER)
    assert out["success"] is True
    expected = ["022026", "012026", "122025", "112025", "062025", "042025"]
    assert _periods(out, "gstr1") == expected and _periods(out, "gstr3b") == expected


def test_the_annual_return_sits_after_the_last_month_of_its_year(db):
    for p in ("032026", "FY2025-26", "042025"):
        db.seed("gstr1_returns", _row("gstr1_returns", p, return_type="gstr9" if p.startswith("FY") else "gstr1"))
    out = gw.list_returns(client_id=CLIENT, return_type=None, limit=50, offset=0, current_user=CALLER)
    assert _periods(out, "gstr1") == ["FY2025-26", "032026", "042025"]


def test_a_window_is_taken_from_the_ordered_answer_and_never_repeats_or_skips(db):
    for m in range(4, 13):
        db.seed("gstr3b_returns", _row("gstr3b_returns", f"{m:02d}2025"))
    pages = [gw.list_returns(client_id=CLIENT, return_type=None, limit=4, offset=off, current_user=CALLER)
             for off in (0, 4, 8)]
    seen = [p for page in pages for p in _periods(page, "gstr3b")]
    assert seen == [f"{m:02d}2025" for m in range(12, 3, -1)], seen
    assert all(page["data"]["gstr3b_total"] == 9 for page in pages)


def test_a_client_with_more_returns_than_the_window_still_reports_how_many_it_has(db):
    for m in range(1, 13):
        db.seed("gstr1_returns", _row("gstr1_returns", f"{m:02d}2025", return_type="gstr1"))
        db.seed("gstr1_returns", _row("gstr1_returns", f"{m:02d}2026", return_type="gstr1"))
    out = gw.list_returns(client_id=CLIENT, return_type="gstr1", limit=10, offset=0, current_user=CALLER)
    assert len(out["data"]["gstr1"]) == 10 and out["data"]["gstr1_total"] == 24
    # the ten shown are the NEWEST ten, not an arbitrary ten
    assert _periods(out, "gstr1")[0] == "122026" and _periods(out, "gstr1")[-1] == "032026"


def test_another_clients_and_another_firms_returns_are_not_in_it(db):
    db.seed("gstr1_returns", _row("gstr1_returns", "042025", return_type="gstr1"))
    db.seed("gstr1_returns", _row("gstr1_returns", "052025", client="CLIENT-2", return_type="gstr1"))
    db.seed("gstr1_returns", _row("gstr1_returns", "062025", firm="FIRM-B", return_type="gstr1"))
    out = gw.list_returns(client_id=CLIENT, return_type=None, limit=50, offset=0, current_user=CALLER)
    assert _periods(out, "gstr1") == ["042025"] and out["data"]["gstr1_total"] == 1


def test_the_return_type_filter_still_filters(db):
    db.seed("gstr1_returns", _row("gstr1_returns", "042025", return_type="gstr1"))
    db.seed("gstr1_returns", _row("gstr1_returns", "FY2025-26", return_type="gstr9"))
    only9 = gw.list_returns(client_id=CLIENT, return_type="gstr9", limit=50, offset=0, current_user=CALLER)
    only1 = gw.list_returns(client_id=CLIENT, return_type="gstr1", limit=50, offset=0, current_user=CALLER)
    assert _periods(only9, "gstr1") == ["FY2025-26"] and _periods(only1, "gstr1") == ["042025"]


# ── the rank a screen merging the two lists sorts by ────────────────────────

def test_every_row_carries_the_rank_a_merging_screen_sorts_by(db):
    for p in ("042025", "012026", "FY2025-26"):
        db.seed("gstr1_returns", _row("gstr1_returns", p, return_type="gstr9" if p.startswith("FY") else "gstr1"))
    out = gw.list_returns(client_id=CLIENT, return_type=None, limit=50, offset=0, current_user=CALLER)
    ranks = {r["period"]: r["period_order"] for r in out["data"]["gstr1"]}
    assert ranks["042025"] < ranks["012026"] < ranks["FY2025-26"]
    assert all(isinstance(v, int) and v > 0 for v in ranks.values())


def test_rows_of_one_period_keep_a_stable_order_across_windows(db):
    """Two stores' worth of rows can share a period (two registrations, or a revised row); the id decides, so a window
    boundary falling between them neither repeats nor drops one."""
    for i in range(6):
        db.seed("gstr3b_returns", _row("gstr3b_returns", "082025", id=f"R{i}"))
    seen = []
    for off in (0, 2, 4):
        page = gw.list_returns(client_id=CLIENT, return_type=None, limit=2, offset=off, current_user=CALLER)
        seen += [r["id"] for r in page["data"]["gstr3b"]]
    assert seen == [f"R{i}" for i in range(5, -1, -1)] and len(set(seen)) == 6


def test_the_window_reads_every_key_but_the_full_rows_of_the_window_only(db, monkeypatch):
    for m in range(1, 13):
        db.seed("gstr1_returns", _row("gstr1_returns", f"{m:02d}2025", return_type="gstr1",
                                      payload_json={"b2b": ["x" * 50] * 20}))
    reads = []
    real_table = db.table

    def spy(name):
        q = real_table(name)
        real_select = q.select

        def select(cols="*", *a, **k):
            reads.append((name, cols))
            return real_select(cols, *a, **k)
        q.select = select
        return q
    monkeypatch.setattr(db, "table", spy)

    out = gw.list_returns(client_id=CLIENT, return_type="gstr1", limit=3, offset=0, current_user=CALLER)
    assert [r["period"] for r in out["data"]["gstr1"]] == ["122025", "112025", "102025"]
    assert out["data"]["gstr1_total"] == 12
    gstr1_reads = [c for t, c in reads if t == "gstr1_returns"]
    assert gstr1_reads == ["id, period", "*"], gstr1_reads


# ── the filing history is the same ordered window ───────────────────────────

def _history(db, **kw):
    return gw.filing_history(client_id=kw.pop("client_id", CLIENT), limit=kw.pop("limit", 50),
                             offset=kw.pop("offset", 0), current_user=CALLER)


def test_the_filing_history_is_latest_period_first_and_holds_only_filed_returns(db):
    for p, status in (("112025", "submitted"), ("042025", "submitted"), ("012026", "submitted"),
                      ("062025", "draft"), ("092025", "ca_approved")):
        db.seed("gstr1_returns", _row("gstr1_returns", p, status=status, return_type="gstr1"))
        db.seed("gstr3b_returns", _row("gstr3b_returns", p, status=status))
    out = _history(db)
    assert out["success"] is True
    assert [r["period"] for r in out["data"]["gstr1_filed"]] == ["012026", "112025", "042025"]
    assert [r["period"] for r in out["data"]["gstr3b_filed"]] == ["012026", "112025", "042025"]
    assert out["data"]["gstr1_filed_total"] == 3 and out["data"]["gstr3b_filed_total"] == 3


def test_a_client_with_more_filed_returns_than_the_window_gets_the_newest_and_the_count(db):
    for y in (2024, 2025, 2026):
        for m in range(1, 13):
            db.seed("gstr3b_returns", _row("gstr3b_returns", f"{m:02d}{y}"))
    first = _history(db, limit=10)["data"]
    second = _history(db, limit=10, offset=10)["data"]
    assert first["gstr3b_filed_total"] == 36
    assert [r["period"] for r in first["gstr3b_filed"]][:2] == ["122026", "112026"]
    assert [r["period"] for r in first["gstr3b_filed"] + second["gstr3b_filed"]] == \
        [f"{m:02d}{y}" for y in (2026, 2025, 2024) for m in range(12, 0, -1)][:20]


def test_the_filing_history_rows_carry_the_rank_the_tab_merges_on(db):
    db.seed("gstr1_returns", _row("gstr1_returns", "042025", return_type="gstr1"))
    db.seed("gstr3b_returns", _row("gstr3b_returns", "112025"))
    data = _history(db)["data"]
    assert data["gstr1_filed"][0]["period_order"] < data["gstr3b_filed"][0]["period_order"]


def test_another_clients_filed_returns_are_not_in_the_history(db):
    db.seed("gstr1_returns", _row("gstr1_returns", "042025", return_type="gstr1"))
    db.seed("gstr1_returns", _row("gstr1_returns", "052025", client="CLIENT-2", return_type="gstr1"))
    db.seed("gstr1_returns", _row("gstr1_returns", "062025", firm="FIRM-B", return_type="gstr1"))
    out = _history(db)
    assert [r["period"] for r in out["data"]["gstr1_filed"]] == ["042025"]
