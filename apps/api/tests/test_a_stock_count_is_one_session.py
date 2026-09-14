"""A physical stock count is ONE session, not a hundred adjustments (INV-08).

WHAT WAS WRONG
    Stock adjustment was one item per API call and one item per modal, opened
    only from inside an item's ledger drill-down. Stock-taking at 31 March
    produces a sheet with a hundred variances, so the CA opened each item's
    ledger, retyped the quantity, chose a reason and confirmed the s.17(5)(h)
    checkbox — a hundred times — and the hundred journals that came out had no
    common reference tying them to the count.

WHAT IS PINNED HERE
    The variance rule and its direction; that the posted variance is measured
    against the position AS AT THE COUNT DATE rather than the snapshot on the
    line, and that a divergence between the two is SAID rather than hidden;
    the two refusals, both per LINE so ninety-eight post while two are named;
    that a blank count is not zero; and that posting runs through the ONE
    adjustment path under ONE reference and cannot run twice.
"""
from __future__ import annotations

import inspect
import re
from decimal import Decimal as D
from pathlib import Path

import pytest
from fastapi import HTTPException

import routers.inventory as inv
import services.stock_count_service as svc
from domain.inventory import count_session as cs
from models.inventory import ADJUSTMENT_REASONS, StockCountEntryIn

_MIG = Path(__file__).resolve().parent.parent / "migrations"
_M387 = "387_a_stock_count_is_one_session_not_a_hundred_adjustments.sql"
_M387_BACK = "387_a_stock_count_is_one_session_not_a_hundred_adjustments_rollback.sql"


def _line(counted=None, system="10", current=None, reverse_itc=None, **kw):
    return cs.CountLine(
        service_catalogue_id=kw.get("item_id", "i1"),
        item_name=kw.get("name", "Widget"),
        unit="NOS",
        system_qty_units=D(system),
        current_qty_units=D(current if current is not None else system),
        counted_qty_units=None if counted is None else D(counted),
        reverse_itc=reverse_itc,
        itc_reversal_is_interstate=kw.get("interstate", False),
    )


def _plan(*lines, count_date="2026-03-31", reference_no="PC-2026-03-31"):
    return cs.plan(count_date=count_date, reference_no=reference_no, lines=list(lines))


# ══ the variance ═════════════════════════════════════════════════════════════

def test_a_shortage_is_a_decrease_of_the_difference():
    p = _plan(_line(counted="7", system="10", reverse_itc=True)).lines[0]
    assert p.direction == cs.DECREASE
    assert p.quantity == D("3")
    assert p.reason == "physical_count_shortage"
    assert p.will_post is True


def test_a_surplus_is_an_increase():
    p = _plan(_line(counted="13", system="10")).lines[0]
    assert p.direction == cs.INCREASE
    assert p.quantity == D("3")
    assert p.reason == "physical_count_surplus"
    assert p.will_post is True


def test_a_line_that_agrees_posts_nothing():
    p = _plan(_line(counted="10", system="10")).lines[0]
    assert p.direction is None
    assert p.will_post is False
    assert p.gaps == []


def test_both_reasons_are_ones_the_adjustment_model_already_knows():
    """A count can only ever produce these two, and the single-item path has
    accepted both since it was written."""
    assert cs.REASON_SHORTAGE in ADJUSTMENT_REASONS
    assert cs.REASON_SURPLUS in ADJUSTMENT_REASONS


def test_three_decimals_survive_the_subtraction():
    """`NUMERIC(10,3)` is what the ledger keeps, and Decimal is why this is not
    a float — 10.1 - 10.0 in binary floating point is 0.09999999999999964."""
    p = _plan(_line(counted="10.1", system="10")).lines[0]
    assert p.quantity == D("0.1")


def test_a_quantity_is_read_through_its_string_and_never_through_a_float():
    """`Decimal(float("10.1"))` is 10.0999999999999996447…, so a count of 10.1
    against books of 10.1 would come out as a variance of -3.55e-15 and the
    sheet would post an adjustment of nothing."""
    assert svc._qty("10.1") == D("10.1")
    assert svc._qty(10.1) == D("10.1")
    assert svc._qty("10.1") - svc._qty(10.1) == 0
    assert svc._qty(None) == D(0)
    assert svc._qty("not a number") == D(0)


# ══ the count date is what the variance is measured against ══════════════════

def test_the_variance_is_against_the_books_as_at_the_count_date():
    """The snapshot on the line is what the sheet was PRINTED against. A 30
    March purchase bill entered on 2 April changes what the books say for 31
    March, and the count is a fact about 31 March — posting the snapshot's
    variance would re-introduce the very difference the bill corrected."""
    p = _plan(_line(counted="7", system="10", current="12", reverse_itc=True)).lines[0]
    assert p.quantity == D("5")
    assert p.direction == cs.DECREASE


def test_a_divergence_between_the_two_is_said():
    p = _plan(_line(counted="7", system="10", current="12", reverse_itc=True)).lines[0]
    assert any("10" in c and "12" in c for c in p.caveats), p.caveats


def test_no_caveat_where_the_books_did_not_move():
    p = _plan(_line(counted="7", system="10", reverse_itc=True)).lines[0]
    assert p.caveats == []


# ══ the two refusals, both per LINE ══════════════════════════════════════════

def test_a_line_not_yet_counted_cannot_post_and_blank_is_not_zero():
    p = _plan(_line(counted=None, system="10")).lines[0]
    assert p.will_post is False
    assert any("Blank is not zero" in g for g in p.gaps)
    # And it is NOT read as a total write-off.
    assert p.quantity is None and p.direction is None


def test_a_zero_count_is_a_real_answer_and_writes_the_stock_off():
    p = _plan(_line(counted="0", system="10", reverse_itc=True)).lines[0]
    assert p.will_post is True
    assert p.quantity == D("10")
    assert p.direction == cs.DECREASE


def test_a_shortage_with_no_section_17_5_h_decision_cannot_post():
    """Whether the credit must be reversed is a judgement only the CA can make
    — damaged stock might still be sold at a discount."""
    p = _plan(_line(counted="7", system="10", reverse_itc=None)).lines[0]
    assert p.will_post is False
    assert any("s.17(5)(h)" in g for g in p.gaps)


def test_a_surplus_needs_no_decision():
    """Stock found is not stock lost."""
    p = _plan(_line(counted="13", system="10", reverse_itc=None)).lines[0]
    assert p.will_post is True
    assert p.gaps == []


def test_a_surplus_claiming_a_reversal_is_refused():
    p = _plan(_line(counted="13", system="10", reverse_itc=True)).lines[0]
    assert p.will_post is False
    assert any("stock FOUND" in g for g in p.gaps)


def test_ninety_eight_post_while_two_are_named():
    """Refusing the whole batch for two lines would send the CA back to the
    hundred-clicks path they came from."""
    lines = [_line(counted="7", system="10", reverse_itc=True, item_id=f"i{i}",
                   name=f"Item {i:03d}") for i in range(98)]
    lines.append(_line(counted=None, system="10", item_id="x1", name="Uncounted"))
    lines.append(_line(counted="7", system="10", reverse_itc=None, item_id="x2",
                       name="Undecided"))
    p = _plan(*lines)
    assert len(p.postable) == 98
    assert p.blocked_count == 2
    # 99 variances, not 100: the uncounted line has no variance to have.
    assert p.variance_count == 99
    assert p.counted_count == 99


def test_a_sheet_with_no_reference_or_no_date_is_refused_whole():
    assert any("no reference" in g for g in _plan(_line(), reference_no=" ").gaps)
    assert any("no date" in g for g in _plan(_line(), count_date="").gaps)


# ══ the service ══════════════════════════════════════════════════════════════

#: What PostgREST will answer with at most, and the reason every read of one
#: row per stock ITEM has to be paged.
DB_MAX_ROWS = 1000


class _Res:
    def __init__(self, data):
        self.data = data


class _Table:
    """A PostgREST-shaped double, INCLUDING its row ceiling.

    The cap is the point. PostgREST answers at most `db-max-rows` (~1000) and
    says nothing when it does, so a double that hands back every row cannot
    fail on a truncation — which is how an unpaged read of one-row-per-item
    passes every test and is wrong on the only clients that matter.
    """
    def __init__(self, name, store, sink):
        self.name, self.store, self.sink = name, store, sink
        self._rows = list(store.get(name, []))
        self._patch = None
        self._limit = None

    def select(self, *_a, **_k):
        return self

    def eq(self, c, v):
        self._rows = [r for r in self._rows if str(r.get(c)) == str(v)]
        return self

    def gt(self, c, v):
        self._rows = [r for r in self._rows if str(r.get(c)) > str(v)]
        return self

    def order(self, col=None, desc=False, **_k):
        if col:
            self._rows = sorted(self._rows, key=lambda r: str(r.get(col) or ""),
                                reverse=bool(desc))
        return self

    def limit(self, n):
        self._limit = n
        return self

    def update(self, patch):
        self._patch = patch
        return self

    def insert(self, rows):
        rows = rows if isinstance(rows, list) else [rows]
        self.sink.append((self.name, "insert", rows))
        for r in rows:
            r.setdefault("id", f"{self.name}-{len(self.store.get(self.name, []))}")
            self.store.setdefault(self.name, []).append(r)
        self._rows = rows
        return self

    def execute(self):
        if self._patch is not None:
            self.sink.append((self.name, "update", dict(self._patch)))
            for r in self._rows:
                r.update(self._patch)
        cap = min(self._limit or DB_MAX_ROWS, DB_MAX_ROWS)
        return _Res([dict(r) for r in self._rows[:cap]])


class _DB:
    def __init__(self, store):
        self.store, self.writes = store, []

    def table(self, name):
        return _Table(name, self.store, self.writes)


def _store(**over):
    base = {
        "stock_count_sessions": [{
            "id": "S1", "firm_id": "F1", "client_id": "C1", "count_date": "2026-03-31",
            "reference_no": "PC-1", "status": "open", "notes": None,
            "created_at": "t", "created_by": "u", "posted_at": None, "posted_by": None,
        }],
        "stock_count_lines": [{
            "id": "L1", "firm_id": "F1", "client_id": "C1", "session_id": "S1",
            "service_catalogue_id": "i1", "system_qty_units": "10",
            "counted_qty_units": "7", "reverse_itc": True,
            "itc_reversal_is_interstate": False, "notes": None,
        }],
        "service_catalogue": [{"id": "i1", "firm_id": "F1", "client_id": "C1",
                               "kind": "good", "name": "Widget", "unit": "NOS"}],
    }
    base.update(over)
    return base


@pytest.fixture
def wired(monkeypatch):
    def _wire(store, position_items=(("i1", "10"),)):
        db = _DB(store)
        import services.stock_position_service as sps
        monkeypatch.setattr(sps, "position", lambda *_a, **_k: {
            "items": [{"service_catalogue_id": i, "qty_units": q} for i, q in position_items]})
        return db
    return _wire


def test_the_service_reads_the_position_as_at_the_count_date(monkeypatch):
    """As at the COUNT DATE, not as at today — a sheet keyed in on 3 April for
    a 31 March count must be measured against 31 March."""
    asked = []
    import services.stock_position_service as sps
    monkeypatch.setattr(sps, "position", lambda db, f, c, at, *a, **k: (
        asked.append(at) or {"items": [{"service_catalogue_id": "i1", "qty_units": "12"}]}))
    db = _DB(_store())
    _, plan = svc.read_plan(db, firm_id="F1", session_id="S1")
    assert asked == ["2026-03-31"]
    assert plan.lines[0].line.current_qty_units == D("12")
    assert plan.lines[0].quantity == D("5")


def test_opening_a_sheet_snapshots_the_position_as_at_the_count_date(monkeypatch):
    asked = []
    import services.stock_position_service as sps
    monkeypatch.setattr(sps, "position", lambda db, f, c, at, *a, **k: (
        asked.append(at) or {"items": [{"service_catalogue_id": "i1", "qty_units": "10"}]}))
    store = {"stock_count_sessions": [], "stock_count_lines": [], "service_catalogue": []}
    db = _DB(store)
    svc.open_session(db, firm_id="F1", client_id="C1", count_date="2026-03-31",
                     reference_no=None, notes=None, created_by="u")
    assert asked == ["2026-03-31"]
    assert store["stock_count_sessions"][0]["reference_no"] == "PC-2026-03-31"
    assert store["stock_count_lines"][0]["system_qty_units"] == "10"


def test_saving_a_count_does_not_clear_the_decision_made_earlier(wired):
    """A caller sending only the counted quantity must not wipe the CGST Act
    s.17(5)(h) answer the CA gave on a previous save."""
    store = _store()
    db = wired(store)
    svc.save_counts(db, firm_id="F1", session_id="S1",
                    entries=[{"service_catalogue_id": "i1", "counted_qty_units": 6}])
    line = store["stock_count_lines"][0]
    assert line["counted_qty_units"] == "6"
    assert line["reverse_itc"] is True


def test_saving_an_item_the_sheet_does_not_have_adds_nothing(wired):
    """The count covers the items the sheet was opened with."""
    store = _store()
    db = wired(store)
    written = svc.save_counts(db, firm_id="F1", session_id="S1",
                              entries=[{"service_catalogue_id": "nope",
                                        "counted_qty_units": 1}])
    assert written == 0
    assert len(store["stock_count_lines"]) == 1


def test_a_posted_sheet_cannot_be_edited(wired):
    store = _store()
    store["stock_count_sessions"][0]["status"] = "posted"
    db = wired(store)
    with pytest.raises(HTTPException) as e:
        svc.save_counts(db, firm_id="F1", session_id="S1", entries=[])
    assert e.value.status_code == 409


def test_posting_runs_the_one_adjustment_path_under_one_reference(monkeypatch, wired):
    store = _store()
    db = wired(store)
    calls = []
    import domain.inventory_service as isvc
    monkeypatch.setattr(isvc, "apply_stock_adjustment",
                        lambda *a, **kw: calls.append(kw) or {"id": "m1"})
    import services.period_validation_service as pvs
    monkeypatch.setattr(pvs.period_validation_service, "validate_posting_date",
                        lambda *_a, **_k: None)

    out = svc.post_session(db, firm_id="F1", session_id="S1", actor_id="u1")
    assert out["posted_count"] == 1 and out["failed_count"] == 0
    assert len(calls) == 1
    assert calls[0]["reference_no"] == "PC-1"
    assert calls[0]["movement_date"] == "2026-03-31"
    assert calls[0]["direction"] == "decrease"
    assert float(calls[0]["quantity"]) == 3.0
    assert calls[0]["reverse_itc"] is True
    assert store["stock_count_sessions"][0]["status"] == "posted"


def test_posting_twice_is_refused(monkeypatch, wired):
    store = _store()
    store["stock_count_sessions"][0]["status"] = "posted"
    db = wired(store)
    with pytest.raises(HTTPException) as e:
        svc.post_session(db, firm_id="F1", session_id="S1", actor_id="u1")
    assert e.value.status_code == 409


def test_a_line_that_fails_is_named_rather_than_swallowed(monkeypatch, wired):
    """The batch is not atomic and cannot be — each adjustment is its own
    journal through the posting kernel — so a line that could not post leaves
    the books disagreeing with the count and the CA has to be told which."""
    db = wired(_store())
    import domain.inventory_service as isvc
    def _boom(*_a, **_k):
        raise RuntimeError("ledger said no")
    monkeypatch.setattr(isvc, "apply_stock_adjustment", _boom)
    import services.period_validation_service as pvs
    monkeypatch.setattr(pvs.period_validation_service, "validate_posting_date",
                        lambda *_a, **_k: None)
    out = svc.post_session(db, firm_id="F1", session_id="S1", actor_id="u1")
    assert out["posted_count"] == 0
    assert out["failed_count"] == 1
    assert "ledger said no" in out["failed"][0]["why"]


def test_posting_asks_the_period_lock_once_for_the_count_date(monkeypatch, wired):
    db = wired(_store())
    asked = []
    import services.period_validation_service as pvs
    monkeypatch.setattr(pvs.period_validation_service, "validate_posting_date",
                        lambda firm, date: asked.append((firm, date)))
    import domain.inventory_service as isvc
    monkeypatch.setattr(isvc, "apply_stock_adjustment", lambda *a, **kw: {"id": "m1"})
    svc.post_session(db, firm_id="F1", session_id="S1", actor_id="u1")
    assert asked == [("F1", "2026-03-31")]


def _big_store(n=1500):
    """A client with more stock items than PostgREST will return in one read.

    1,500 is not a stress test — it is one warehouse. A hardware distributor or
    a pharmacy has thousands of SKUs, and a physical count is precisely the
    task that touches every one of them.
    """
    return {
        "stock_count_sessions": [{
            "id": "S1", "firm_id": "F1", "client_id": "C1", "count_date": "2026-03-31",
            "reference_no": "PC-1", "status": "open", "notes": None,
            "created_at": "t", "created_by": "u", "posted_at": None, "posted_by": None,
        }],
        "stock_count_lines": [{
            "id": f"L{i:05d}", "firm_id": "F1", "client_id": "C1", "session_id": "S1",
            "service_catalogue_id": f"i{i:05d}", "system_qty_units": "10",
            "counted_qty_units": None, "reverse_itc": None,
            "itc_reversal_is_interstate": False, "notes": None,
        } for i in range(n)],
        "service_catalogue": [{"id": f"i{i:05d}", "firm_id": "F1", "client_id": "C1",
                               "kind": "good", "name": f"Item {i:05d}", "unit": "NOS"}
                              for i in range(n)],
    }


def test_a_sheet_with_more_items_than_one_page_is_read_whole(monkeypatch):
    """PostgREST caps a response at ~1000 rows and says nothing when it does.

    An unpaged read of one-row-per-item gives a sheet that is 500 lines short
    and looks complete — the missing items simply have no variance, so the CA
    posts a count that is not the count they took. Both reads are paged
    through `core.db_paging.fetch_all`, and the double above enforces the cap
    so this test fails if either stops being.
    """
    store = _big_store()
    db = _DB(store)
    import services.stock_position_service as sps
    monkeypatch.setattr(sps, "position", lambda *_a, **_k: {
        "items": [{"service_catalogue_id": f"i{i:05d}", "qty_units": "10"}
                  for i in range(1500)]})
    _, plan = svc.read_plan(db, firm_id="F1", session_id="S1")
    assert len(plan.lines) == 1500
    # The NAMES are the SECOND paged read, and this has to be asserted over
    # EVERY line rather than the last one. The plan sorts by name, and an
    # unnamed line falls back to its raw id — which sorts BEFORE the named
    # ones, so `lines[-1]` is named even when five hundred others are not.
    # A negative control caught exactly that.
    assert all(p.line.item_name.startswith("Item ") for p in plan.lines)


def test_saving_onto_a_sheet_longer_than_one_page_merges_every_line(monkeypatch):
    """`save_counts` reads the existing lines once and merges each entry onto
    its row. A truncated read makes every entry past the thousandth 'a line
    the sheet does not have', so the count is silently dropped."""
    store = _big_store()
    db = _DB(store)
    written = svc.save_counts(db, firm_id="F1", session_id="S1", entries=[
        {"service_catalogue_id": "i01400", "counted_qty_units": "7"}])
    assert written == 1


def test_a_count_dated_inside_a_filed_return_is_refused(monkeypatch, wired):
    """The FY switch is the firm's; the filed return is the client's.

    A shortage posts a CGST Act s.17(5)(h) reversal onto GSTR-3B Table 4(B)(1)
    (INV-06), so a count sheet IS a document that feeds a return — and a March
    3B filed on 20 April cannot be recalled. `validate_posting_date` takes no
    client_id and cannot see the filing at all.
    """
    store = _store(filings=[{
        "id": "f1", "client_id": "C1", "filing_type": "GSTR-3B",
        "filed_date": "2026-04-20", "period_start": "2026-03-01",
        "period_end": "2026-03-31", "deleted_at": None,
    }])
    db = wired(store)
    posted = []
    import domain.inventory_service as isvc
    monkeypatch.setattr(isvc, "apply_stock_adjustment",
                        lambda *a, **kw: posted.append(kw) or {"id": "m1"})
    import services.period_validation_service as pvs
    monkeypatch.setattr(pvs.period_validation_service, "validate_posting_date",
                        lambda *_a, **_k: None)

    with pytest.raises(HTTPException) as e:
        svc.post_session(db, firm_id="F1", session_id="S1", actor_id="u1")
    assert e.value.status_code == 422
    assert "GSTR-3B" in str(e.value.detail)
    # Nothing posted, and the sheet is still open — a refusal that had already
    # written half the lines would be worse than no check.
    assert posted == []
    assert store["stock_count_sessions"][0]["status"] == "open"


def test_a_filed_return_outside_the_count_month_does_not_refuse(monkeypatch, wired):
    """A February 3B says nothing about a 31 March count. The lock is asked
    for the COUNT DATE, so a return covering another period leaves it open."""
    store = _store(filings=[{
        "id": "f1", "client_id": "C1", "filing_type": "GSTR-3B",
        "filed_date": "2026-03-20", "period_start": "2026-02-01",
        "period_end": "2026-02-28", "deleted_at": None,
    }])
    db = wired(store)
    import domain.inventory_service as isvc
    monkeypatch.setattr(isvc, "apply_stock_adjustment", lambda *a, **kw: {"id": "m1"})
    import services.period_validation_service as pvs
    monkeypatch.setattr(pvs.period_validation_service, "validate_posting_date",
                        lambda *_a, **_k: None)
    out = svc.post_session(db, firm_id="F1", session_id="S1", actor_id="u1")
    assert out["posted_count"] == 1


def test_the_count_path_is_not_on_the_firm_only_debt_list():
    """The guard in test_every_dated_posting_path_asserts_the_client_lock.py
    fails a NEW path that asks only the FY switch. Asserted here too, from the
    feature's own side, so deleting the call is a failure in this file rather
    than only in a guard nobody reading this feature would look at."""
    src = inspect.getsource(svc.post_session)
    assert "validate_posting_date" in src
    assert "period_lock_service.assert_open" in src


def test_the_projections_match_what_the_service_documents():
    """The query has to be a literal — the column guard reads every
    `.select()` against the real schema — but the constants are what say why
    each column is needed, and the two must not drift."""
    src = inspect.getsource(svc.read_plan)
    literal = src.split('stock_count_lines").select(')[1].split(")")[0]
    assert "".join(re.findall(r'"([^"]*)"', literal)) == svc.LINE_COLUMNS
    src = inspect.getsource(svc._session)
    literal = src.split('stock_count_sessions").select(')[1].split(")")[0]
    assert "".join(re.findall(r'"([^"]*)"', literal)) == svc.SESSION_COLUMNS


# ══ the model ════════════════════════════════════════════════════════════════

def test_a_blank_count_is_none_and_a_zero_is_zero():
    assert StockCountEntryIn(service_catalogue_id="i1").counted_qty_units is None
    assert StockCountEntryIn(service_catalogue_id="i1",
                             counted_qty_units=0).counted_qty_units == 0


def test_a_negative_count_is_refused():
    with pytest.raises(Exception):
        StockCountEntryIn(service_catalogue_id="i1", counted_qty_units=-1)


def test_a_fourth_decimal_is_refused():
    """NUMERIC(10,3) is what the ledger keeps (INV-09)."""
    with pytest.raises(Exception):
        StockCountEntryIn(service_catalogue_id="i1", counted_qty_units=1.0001)


def test_the_itc_decision_is_tri_state_on_the_wire():
    assert StockCountEntryIn(service_catalogue_id="i1").reverse_itc is None
    assert StockCountEntryIn(service_catalogue_id="i1", reverse_itc=False).reverse_itc is False


# ══ the router ═══════════════════════════════════════════════════════════════

def test_every_count_endpoint_checks_the_clients_scope():
    for fn in (inv.open_count_session, inv.list_count_sessions,
               inv.get_count_session, inv.save_count_session, inv.post_count_session):
        assert "assert_client_access(" in inspect.getsource(fn), fn.__name__


def test_the_save_path_refuses_a_client_that_does_not_own_the_sheet():
    src = inspect.getsource(inv.save_count_session)
    assert 'session["client_id"] != data.client_id' in src


def test_the_router_posts_nothing_itself():
    """One write path: the service calls apply_stock_adjustment, which is what
    the single-item screen calls."""
    src = inspect.getsource(inv.post_count_session)
    assert "apply_stock_adjustment" not in src
    assert "stock_count_service.post_session(" in src
    assert "CA REVIEW REQUIRED" in src


def test_the_response_carries_both_figures_and_every_refusal():
    src = inspect.getsource(inv._count_plan_response)
    for key in ("system_qty_units", "current_qty_units", "variance_qty_units",
                "will_post", "gaps", "caveats", "postable_count", "blocked_count"):
        assert f'"{key}"' in src, key


# ══ the migration ════════════════════════════════════════════════════════════

def _sql(name: str) -> str:
    text = (_MIG / name).read_text(encoding="utf-8")
    return "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("--"))


def test_a_counted_quantity_is_nullable_and_a_decision_has_no_default():
    """Both are the same rule: NULL means the CA has not answered, and neither
    zero nor false may stand in for that."""
    sql = _sql(_M387)
    counted = next(l for l in sql.splitlines() if "counted_qty_units NUMERIC" in l)
    assert "NOT NULL" not in counted and "DEFAULT" not in counted
    reverse = next(l for l in sql.splitlines() if l.strip().startswith("reverse_itc"))
    assert "NOT NULL" not in reverse and "DEFAULT" not in reverse


def test_no_variance_is_stored():
    """It is a function of the count date's position, which moves. A stored
    figure would be right on the day it was written."""
    sql = _sql(_M387)
    assert "variance" not in sql.lower()


def test_only_one_open_sheet_per_client_per_date():
    sql = _sql(_M387)
    assert "uq_stock_count_open_per_client_date" in sql
    assert "WHERE status = 'open'" in sql, (
        "narrowed to the open ones — an abandoned sheet must not block a redo "
        "and a posted one stays on the record")


def test_both_tables_are_read_only_from_the_browser_and_assignment_scoped():
    sql = _sql(_M387)
    grants = [l.strip() for l in sql.splitlines() if l.strip().startswith("GRANT")]
    to_browser = sorted(g for g in grants if "authenticated" in g)
    assert to_browser == [
        "GRANT SELECT ON public.stock_count_lines    TO authenticated;",
        "GRANT SELECT ON public.stock_count_sessions TO authenticated;",
    ], to_browser
    for table in ("stock_count_sessions", "stock_count_lines"):
        assert f"{table}_assignment_scope" in sql
    assert sql.count("AS RESTRICTIVE FOR ALL") == 2


def test_the_status_check_accepts_exactly_what_the_engine_knows():
    sql = _sql(_M387)
    line = next(l for l in sql.splitlines() if "status IN" in l)
    assert set(re.findall(r"'([^']*)'", line)) == set(cs.STATUSES)


def test_the_rollback_drops_the_lines_before_the_sessions():
    back = _sql(_M387_BACK)
    assert back.index("stock_count_lines") < back.index("stock_count_sessions")
