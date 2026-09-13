"""The Rule 43 working reads the register, and the endpoint that serves it.

FA-19's second half. `domain/gst/rule_43.py` is the arithmetic and is tested in
tests/test_rule_43_capital_goods_apportionment.py. These are about the two
things a domain test cannot see:

  * that the SERVICE fetches the right rows and hands them over unchanged —
    every live asset of the client, its tax split, whether the credit was
    taken and which of Rule 43(1)'s uses it is put to;
  * that the ENDPOINT is wired, guarded and refuses a half-supplied turnover.

The turnover is deliberately NOT re-derived here. It comes from
`gst_return_service.outward_turnover`, which reads the same posted documents
through the same computer that builds GSTR-3B Table 3.1 — the point being that
a Rule 43 working and the return it belongs to cannot disagree about what was
supplied. Its own arithmetic is pinned in
tests/test_outward_turnover_is_the_returns_own_figure.py.
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException

import routers.gst_workspace as gw
import services.gst_rule_43_service as svc
from domain.gst import rule_43

FIRM, CLIENT, PERIOD = "firm-1", "client-1", "062025"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "a1",
        "email": "p@f.in", "role": "Partner"}


# ── a store that records the filters, so the fetch itself can be asserted ────

class _Q:
    def __init__(self, store, table, calls):
        self.store, self.table, self.calls = store, table, calls
        self.f, self.isnull, self.gt = {}, {}, None
        self.selected = ""

    def select(self, cols="*", **k):
        self.selected = cols
        self.calls.append({"table": self.table, "select": cols})
        return self

    def eq(self, k, v): self.f[k] = v; return self
    def is_(self, k, v): self.isnull[k] = v; return self
    def gt(self, k, v): self.gt = (k, v); return self
    def order(self, *a, **k): return self
    def limit(self, n): return self

    def execute(self):
        rows = [r for r in self.store.get(self.table, [])
                if all(r.get(k) == v for k, v in self.f.items())]
        for k in self.isnull:
            rows = [r for r in rows if r.get(k) is None]
        if self.gt:
            rows = [r for r in rows if str(r.get(self.gt[0])) > str(self.gt[1])]
        rows = sorted(rows, key=lambda r: str(r.get("id")))
        # Only the columns asked for, so a projection that omits one is visible
        # here rather than at the thousandth row in production.
        if self.selected and self.selected != "*":
            keep = [c.strip() for c in self.selected.split(",")]
            rows = [{k: v for k, v in r.items() if k in keep} for r in rows]
        self.calls[-1]["filters"] = dict(self.f)
        return type("R", (), {"data": rows})()


class _DB:
    def __init__(self, store): self.store, self.calls = store, []
    def table(self, name): return _Q(self.store, name, self.calls)


def _asset(aid, *, name="Lathe", bought="2025-04-10", cgst=90_000, sgst=90_000,
           igst=0, eligible=True, use="common", client=CLIENT, firm=FIRM,
           deleted=None):
    return {"id": aid, "firm_id": firm, "client_id": client, "asset_name": name,
            "asset_code": None, "purchase_date": bought, "igst_paise": igst,
            "cgst_paise": cgst, "sgst_paise": sgst, "itc_eligible": eligible,
            "rule_43_use": use, "deleted_at": deleted}


@pytest.fixture
def db():
    return _DB({"fixed_assets": [_asset("a1")]})


def _turnover(exempt=20_00_000, total=1_00_00_000):
    return {"exempt_paise": exempt, "total_paise": total}


# ── the service ──────────────────────────────────────────────────────────────

def test_it_computes_te_from_the_register(db):
    out = svc.for_period(db, FIRM, CLIENT, PERIOD, turnover=_turnover())
    # 90,000 paise of CGST over 60 months = 1,500 a month; 20% exempt = 300.
    assert out["te_paise"]["cgst"] == 300
    assert out["te_total_paise"] == 600
    assert out["refused"] is False


def test_it_reads_only_this_firm_and_this_client(db):
    """The service-role key bypasses RLS, so the app-layer filter is the
    isolation control. An asset of another client in the same firm is another
    client's credit."""
    db.store["fixed_assets"].append(_asset("a2", client="other", cgst=6_00_000))
    db.store["fixed_assets"].append(_asset("a3", firm="other-firm", cgst=6_00_000))
    out = svc.for_period(db, FIRM, CLIENT, PERIOD, turnover=_turnover())
    assert [a["asset_id"] for a in out["assets"]] == ["a1"]
    fa = [c for c in db.calls if c["table"] == "fixed_assets"][0]
    assert fa["filters"]["firm_id"] == FIRM
    assert fa["filters"]["client_id"] == CLIENT


def test_a_soft_deleted_asset_is_not_in_the_working(db):
    """Migration 351 makes a soft-deleted row one created by mistake. Reversing
    credit on it would declare a figure against an asset the register says does
    not exist."""
    db.store["fixed_assets"].append(
        _asset("a2", cgst=60_00_000, deleted="2025-05-01T00:00:00Z"))
    out = svc.for_period(db, FIRM, CLIENT, PERIOD, turnover=_turnover())
    assert [a["asset_id"] for a in out["assets"]] == ["a1"]


def _projection() -> set:
    """The columns `_capital_goods` actually asks PostgREST for.

    Read off the source with `ast` rather than off a module constant, because
    the query has to spell them as a LITERAL: tests/_backend_query_parser reads
    `.select("…")` the same way and cannot follow a name, so a constant would
    put this query in the unreadable budget and stop
    test_backend_columns_exist_pg from checking `rule_43_use` — the newest
    column in it — against the real schema.
    """
    import ast
    import inspect
    import textwrap
    tree = ast.parse(textwrap.dedent(inspect.getsource(svc._capital_goods)))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "select" and node.args
                and isinstance(node.args[0], ast.Constant)):
            return {c.strip() for c in node.args[0].value.split(",")}
    raise AssertionError("the fetch no longer has a literal projection")


def test_the_projection_carries_the_paging_cursor(db):
    """`fetch_all` pages on `id`, and a select that omits it works perfectly
    until the thousandth row and then cannot advance."""
    assert "id" in _projection()


def test_the_projection_carries_every_column_the_rule_reads(db):
    cols = _projection()
    for needed in ("purchase_date", "igst_paise", "cgst_paise", "sgst_paise",
                   "itc_eligible", "rule_43_use"):
        assert needed in cols, needed


def test_EVERY_asset_is_reported_not_only_the_commons(db):
    """An asset outside its five years, one used exclusively for taxable
    supplies and one nobody has classified are three different answers. An
    asset silently absent reads as one with nothing to reverse."""
    db.store["fixed_assets"] += [
        _asset("a2", name="Van", use="exclusively_taxable"),
        _asset("a3", name="Unmarked", use=None),
        _asset("a4", name="Old", bought="2018-01-01"),
    ]
    out = svc.for_period(db, FIRM, CLIENT, PERIOD, turnover=_turnover())
    assert len(out["assets"]) == 4
    assert sum(1 for a in out["assets"] if a["included"]) == 1
    assert len(out["gaps"]) == 1


def test_the_assets_come_back_oldest_first(db):
    db.store["fixed_assets"] += [
        _asset("a2", name="Newer", bought="2025-05-01"),
        _asset("a0", name="Older", bought="2025-01-01"),
    ]
    out = svc.for_period(db, FIRM, CLIENT, PERIOD, turnover=_turnover())
    assert [a["asset_name"] for a in out["assets"]] == ["Older", "Lathe", "Newer"]


def test_an_asset_with_no_purchase_date_does_not_break_the_sort(db):
    """`purchase_date` is nullable, and comparing None to a date raises
    TypeError in Python where Postgres sorted it happily."""
    db.store["fixed_assets"].append(_asset("a2", name="Undated", bought=None))
    out = svc.for_period(db, FIRM, CLIENT, PERIOD, turnover=_turnover())
    assert out["assets"][0]["asset_name"] == "Undated"
    assert out["assets"][0]["reason"] == rule_43.GAP_NO_INVOICE_DATE


def test_an_unparseable_purchase_date_is_a_gap_not_a_crash(db):
    db.store["fixed_assets"] = [_asset("a1", bought="10-04-2025")]
    out = svc.for_period(db, FIRM, CLIENT, PERIOD, turnover=_turnover())
    assert out["assets"][0]["reason"] == rule_43.GAP_NO_INVOICE_DATE


def test_the_period_start_is_the_first_of_the_month(db):
    assert svc._period_start("062025") == date(2025, 6, 1)
    assert svc._period_start("122026") == date(2026, 12, 1)


@pytest.mark.parametrize("bad", ["2025-06", "132025", "0620251", "abcdef", ""])
def test_a_malformed_period_is_refused(db, bad):
    with pytest.raises(svc.Rule43Error):
        svc.for_period(db, FIRM, CLIENT, bad, turnover=_turnover())


def test_a_supplied_turnover_is_used_and_labelled(db):
    """The proviso to Rule 43(1)(g) sends the CA to the LAST period for which
    turnover is available. Those are a different period's figures, so the
    answer says where they came from."""
    out = svc.for_period(db, FIRM, CLIENT, PERIOD,
                         turnover={"exempt_paise": 1_00_00_000,
                                   "total_paise": 1_00_00_000})
    assert out["te_paise"]["cgst"] == 1500
    assert out["turnover_source"] == "supplied by the caller"
    assert out["turnover_breakdown"] is None


def test_the_books_turnover_is_read_through_the_returns_own_function(db, monkeypatch):
    """One implementation. If this ever stops calling `outward_turnover`, the
    working and the GSTR-3B it belongs to can declare different supplies."""
    seen = {}

    def _fake(dbx, firm, client, period):
        seen.update(firm=firm, client=client, period=period)
        return {"period": period, "exempt_paise": 50_00_000,
                "total_paise": 1_00_00_000,
                "breakdown": {"taxable_paise": 50_00_000, "zero_rated_paise": 0,
                              "nil_exempt_paise": 50_00_000, "non_gst_paise": 0}}

    import services.gst_return_service as grs
    monkeypatch.setattr(grs, "outward_turnover", _fake)
    out = svc.for_period(db, FIRM, CLIENT, PERIOD)
    assert seen == {"firm": FIRM, "client": CLIENT, "period": PERIOD}
    assert out["te_paise"]["cgst"] == 750          # 1500 * 50%
    assert out["turnover_source"] == "this period's posted outward supplies"
    assert out["turnover_breakdown"]["nil_exempt_paise"] == 50_00_000


def test_the_answer_says_how_to_declare_it(db):
    """A figure with no route onto a return is the defect this finding is
    about. Te reaches Table 4(B)(1) through the ITC reversal register's
    'rule_43' ground, and nothing else."""
    out = svc.for_period(db, FIRM, CLIENT, PERIOD, turnover=_turnover())
    assert "rule_43" in out["how_to_declare"]
    assert "4(B)(1)" in out["how_to_declare"]
    assert out["ca_review_required"] is True


def test_rule_43_is_a_ground_the_register_already_accepts():
    """The route the working points at has to exist. It has since migration
    362 — the register accepted the ground and nothing could produce a figure
    for it."""
    from services.itc_register_service import ALL_REASONS, is_reclaimable
    assert "rule_43" in ALL_REASONS
    # Permanent — Circular 170/02/2022-GST. A Rule 43 reversal is never
    # reclaimed into Table 4(D)(1).
    assert is_reclaimable("rule_43") is False


# ── the endpoint ─────────────────────────────────────────────────────────────

@pytest.fixture
def _wired(monkeypatch, db):
    monkeypatch.setattr(gw, "assert_client_access", lambda *a, **k: None)
    monkeypatch.setattr(gw, "_USE_MOCK", False)
    import core.supabase_client as sc
    monkeypatch.setattr(sc, "get_supabase", lambda: db)
    return db


def test_the_endpoint_serves_the_working(_wired):
    out = gw.rule43_capital_goods(
        client_id=CLIENT, period=PERIOD, exempt_turnover_paise=20_00_000,
        total_turnover_paise=1_00_00_000, current_user=USER)
    assert out["success"] is True
    assert out["data"]["te_paise"]["cgst"] == 300


def test_the_endpoint_refuses_half_a_turnover(_wired):
    """E without F is a fraction with no denominator; F without E reads as nil
    exempt turnover, which is a Te of zero that looks computed."""
    for e, f in ((20_00_000, None), (None, 1_00_00_000)):
        with pytest.raises(HTTPException) as exc:
            gw.rule43_capital_goods(client_id=CLIENT, period=PERIOD,
                                    exempt_turnover_paise=e,
                                    total_turnover_paise=f, current_user=USER)
        assert exc.value.status_code == 422
        assert "both" in str(exc.value.detail)


def test_the_endpoint_turns_a_bad_period_into_422(_wired):
    with pytest.raises(HTTPException) as exc:
        gw.rule43_capital_goods(client_id=CLIENT, period="2025-06",
                                exempt_turnover_paise=None,
                                total_turnover_paise=None, current_user=USER)
    assert exc.value.status_code == 422


def test_the_endpoint_is_client_scoped(monkeypatch, db):
    monkeypatch.setattr(gw, "_USE_MOCK", True)
    called = {}
    monkeypatch.setattr(gw, "assert_client_access",
                        lambda user, cid: called.setdefault("cid", cid))
    gw.rule43_capital_goods(client_id=CLIENT, period=PERIOD,
                            exempt_turnover_paise=None,
                            total_turnover_paise=None, current_user=USER)
    assert called["cid"] == CLIENT


def test_the_endpoint_says_it_files_nothing():
    import inspect
    src = inspect.getsource(gw.rule43_capital_goods)
    assert "CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT" in src


# ── the classification the whole thing rests on ──────────────────────────────

def test_the_asset_model_validates_the_rule_43_use():
    from models.accounting import FixedAssetIn
    base = dict(client_id=CLIENT, asset_name="Lathe", purchase_date="2025-04-10",
                purchase_cost_paise=1_00_000)
    assert FixedAssetIn(**base).rule_43_use is None
    assert FixedAssetIn(**base, rule_43_use="common").rule_43_use == "common"
    with pytest.raises(Exception) as e:
        FixedAssetIn(**base, rule_43_use="mixed")
    assert "rule_43_use must be" in str(e.value)


def test_the_edit_path_validates_it_too():
    """A validator only at the create door is one PATCH from being none."""
    from models.accounting import FixedAssetUpdateIn
    assert FixedAssetUpdateIn(rule_43_use="exclusively_exempt").rule_43_use \
        == "exclusively_exempt"
    with pytest.raises(Exception):
        FixedAssetUpdateIn(rule_43_use="partly")


def test_changing_it_is_a_classification_not_an_estimate():
    """Tier A — no GL, no journal, no Companies Act figure. Same as the two IT
    Act §32 facts: a different system reads it itself. Putting it in Tier B
    would reverse and re-post the acquisition journal for a GST classification
    that moves no money."""
    import routers.fixed_assets as fa
    assert "rule_43_use" in fa._TIER_A_FIELDS
    assert "rule_43_use" not in fa._TIER_B_FIELDS
    assert "rule_43_use" not in fa._TIER_C_FIELDS


# ── the create path actually stores it ───────────────────────────────────────
#
# MISSED ON THE FIRST NEGATIVE-CONTROL PASS. Every test above proves the model
# ACCEPTS `rule_43_use` and that the working reads the column — and all of them
# still passed with the router's insert hard-coded to None, so a CA could
# classify an asset on the form and have it silently discarded. The whole
# working then reports every asset as unclassified, which reads like a data
# problem rather than a dropped field.

def _harness(monkeypatch):
    import routers.fixed_assets as fa
    from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa
    db = FakeDB()
    wire_e2e(monkeypatch, db, [fa])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("firms", {"id": "F", "name": "Test & Co", "locked_financial_years": []})
    db.seed("clients", {"id": "CLI", "firm_id": "F",
                        "financial_year_start": "2025-04-01"})
    seed_standard_coa(db, "F", "CLI")
    db.seed("chart_of_accounts", {
        "firm_id": "F", "client_id": "CLI", "account_name": "Plant & Machinery",
        "account_code": "FA1001", "account_type": "Asset", "is_active": True})
    return db, fa


def _make(fa, **kw):
    from models.accounting import FixedAssetIn
    caller = {"firm_id": "F", "id": "u1", "auth_user_id": "a",
              "email": "ca@f.test", "role": "Partner"}
    res = fa.create_asset(FixedAssetIn(
        client_id="CLI", asset_name="Lathe", asset_category="Plant & Machinery",
        purchase_date="2025-04-05", purchase_cost_paise=1_50_000_00,
        useful_life_years=15, acquisition_mode="paid", **kw), caller)
    assert res["success"] is True, res
    return res["data"]


def test_the_classification_the_CA_types_reaches_the_register(monkeypatch):
    db, fa = _harness(monkeypatch)
    asset = _make(fa, rule_43_use="common", cgst_paise=9_000_00,
                  sgst_paise=9_000_00, itc_eligible=True)
    row = next(r for r in db.rows("fixed_assets") if r["id"] == asset["id"])
    assert row["rule_43_use"] == "common"


def test_an_asset_created_without_one_is_stored_unclassified(monkeypatch):
    """NULL, not a default. A default would classify every asset the moment
    it is created, which is exactly the guess the column exists to avoid."""
    db, fa = _harness(monkeypatch)
    asset = _make(fa)
    row = next(r for r in db.rows("fixed_assets") if r["id"] == asset["id"])
    assert row["rule_43_use"] is None


def test_the_stored_classification_is_what_the_working_apportions(monkeypatch):
    """End to end: create → the working reads it back and reverses on it."""
    db, fa = _harness(monkeypatch)
    _make(fa, rule_43_use="common", cgst_paise=9_000_00, sgst_paise=9_000_00,
          itc_eligible=True)
    out = svc.for_period(db, "F", "CLI", "042025",
                         turnover={"exempt_paise": 20_00_000,
                                   "total_paise": 1_00_00_000})
    # 9,00,000 paise of CGST / 60 = 15,000 a month; 20% exempt = 3,000.
    assert out["te_paise"]["cgst"] == 3_000
    assert out["assets"][0]["included"] is True


def test_correcting_the_classification_reaches_the_register_too(monkeypatch):
    db, fa = _harness(monkeypatch)
    from models.accounting import FixedAssetUpdateIn
    caller = {"firm_id": "F", "id": "u1", "auth_user_id": "a",
              "email": "ca@f.test", "role": "Partner"}
    asset = _make(fa)
    res = fa.correct_asset(asset["id"],
                           FixedAssetUpdateIn(rule_43_use="exclusively_taxable",
                                              reason="CA determination"), caller)
    assert res["success"] is True
    # Tier A — no reversal, no re-post.
    assert res["data"]["acquisition_reposted"] is False
    row = next(r for r in db.rows("fixed_assets") if r["id"] == asset["id"])
    assert row["rule_43_use"] == "exclusively_taxable"
