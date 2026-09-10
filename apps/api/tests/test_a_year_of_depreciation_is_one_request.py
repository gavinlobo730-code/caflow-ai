"""
FA-04: depreciation was monthly-only, and the only bulk path was the browser.

WHAT WAS WRONG

`POST /{asset_id}/depreciate` charges exactly ONE month for ONE asset. There was
no annual mode, no from/to range, and no job — a grep of jobs/*.py for 'deprec'
returned nothing. The only way to depreciate a register was a loop in
app/clients/[id]/fixed-assets/page.tsx: one HTTP request per asset for one
month, with every error swallowed.

A CA closing a year on a 200-asset register made 2,400 requests from a browser
tab and could not tell which of them had failed. If one asset had no statutory
rate, or one period was locked, that asset silently did not move and the register
was short for the year with nothing saying so.

WHAT IT IS NOW

`POST /api/fixed-assets/run-depreciation` takes a client and a from/to range and
posts every unposted month, in order, for every live asset — through the SAME
`_post_one_month` the single endpoint calls, not a second copy of the rules. It
reports per asset what it posted and, where it stopped, the month and the reason
in the words the single endpoint would have used.

WHAT IT IS NOT

It is not a way round the no-skip refusal. That refusal exists because posting
April–August and then October leaves September permanently unpostable, and each
month is its own journal needing its own CA review. The runner walks months IN
ORDER from each asset's earliest unposted one, so it never presents a gap — and
a CA who names a RANGE is asking for those months, which is a different act from
a click that asked for one.

IT ALSO PAYS A DEBT. `post_depreciation` was on the acknowledged list of posting
paths that check the FY lock but not the CLIENT's (a filed GSTR-3B, a finalised
year). Posting twelve months in one call rather than one behind a click is what
made that worth paying now.
"""
import pytest
from fastapi import HTTPException

import routers.fixed_assets as fa
from models.accounting import DepreciationRunIn
from tests.test_r232_fixed_asset_depreciation import FakeDB, _seed_asset

FIRM, CLIENT = "firm-1", "client-1"
USER = {"firm_id": FIRM, "id": "u-1", "auth_user_id": "auth-1", "role": "Partner",
        "assigned_client_ids": None}


@pytest.fixture(autouse=True)
def _no_side_effects(monkeypatch):
    monkeypatch.setattr(fa.period_validation_service, "validate_posting_date", lambda *a: None)
    monkeypatch.setattr(fa.timeline_service, "log", lambda *a, **k: None)
    monkeypatch.setattr(fa._journal_svc, "journal_for_depreciation",
                        lambda asset, amount, period, firm, client: f"je-{asset['id']}-{period}")


def _run(db, monkeypatch, **kw):
    monkeypatch.setattr(fa, "_db", lambda: db)
    monkeypatch.setattr(fa, "assert_client_access", lambda *a, **k: None)
    return fa.run_depreciation(
        DepreciationRunIn(client_id=kw.pop("client_id", CLIENT),
                          from_period=kw.pop("from_period", "2026-04"),
                          to_period=kw.pop("to_period", "2027-03")),
        USER)["data"]


# ══════════════════════════════════════════════════════════════════════════════
# The months
# ══════════════════════════════════════════════════════════════════════════════

def test_the_range_is_inclusive_and_in_order():
    assert fa._months_in_range("2026-04", "2026-06") == ["2026-04", "2026-05", "2026-06"]
    assert fa._months_in_range("2026-11", "2027-02") == [
        "2026-11", "2026-12", "2027-01", "2027-02"]
    assert fa._months_in_range("2026-04", "2026-04") == ["2026-04"]
    assert fa._months_in_range("2026-05", "2026-04") == []


def test_twelve_months_land_in_one_call(monkeypatch):
    db = FakeDB()
    _seed_asset(db, purchase_date="2026-04-01", wdv_rate_percent=24.0)
    got = _run(db, monkeypatch)
    assert got["months_posted"] == 12
    assert [m["period"] for m in got["assets"][0]["months"]] == [
        f"2026-{m:02d}" for m in range(4, 13)] + [f"2027-{m:02d}" for m in range(1, 4)]
    assert got["assets"][0]["stopped_at"] is None


def test_the_register_moves_and_the_charge_is_the_engines(monkeypatch):
    """Not a re-derivation. The runner calls the same `_post_one_month` the
    single endpoint calls, so a month posted either way is the same figure."""
    db = FakeDB()
    _seed_asset(db, purchase_date="2026-04-01", wdv_rate_percent=24.0,
                purchase_cost_paise=100_000_00)
    got = _run(db, monkeypatch, to_period="2026-04")
    asset = db.store["fixed_assets"][0]
    charge = got["assets"][0]["months"][0]["depreciation_paise"]
    assert asset["accumulated_depreciation_paise"] == charge
    assert asset["current_wdv_paise"] == 100_000_00 - charge
    assert str(asset["depreciation_posted_through"]) == "2026-04-30"


def test_it_resumes_from_where_the_asset_already_is(monkeypatch):
    db = FakeDB()
    _seed_asset(db, purchase_date="2026-04-01")
    _run(db, monkeypatch, to_period="2026-06")
    again = _run(db, monkeypatch, to_period="2026-09")
    assert [m["period"] for m in again["assets"][0]["months"]] == [
        "2026-07", "2026-08", "2026-09"], "already-posted months are not re-charged"


def test_running_the_same_range_twice_posts_nothing_the_second_time(monkeypatch):
    db = FakeDB()
    _seed_asset(db, purchase_date="2026-04-01")
    first = _run(db, monkeypatch)
    second = _run(db, monkeypatch)
    assert first["months_posted"] == 12 and second["months_posted"] == 0
    assert second["assets"][0]["stopped_at"] is None, (
        "nothing to do is not an error")


def test_months_before_the_asset_existed_are_skipped_not_refused(monkeypatch):
    """A register holds assets bought at different times. Refusing the whole run
    because one asset was bought in October would be the browser loop's problem
    with a server-side accent."""
    db = FakeDB()
    _seed_asset(db, purchase_date="2026-10-15")
    got = _run(db, monkeypatch)
    periods = [m["period"] for m in got["assets"][0]["months"]]
    assert periods[0] == "2026-10" and len(periods) == 6
    assert got["assets"][0]["stopped_at"] is None


# ══════════════════════════════════════════════════════════════════════════════
# One asset must not stop the others
# ══════════════════════════════════════════════════════════════════════════════

def test_an_asset_with_no_statutory_basis_stops_only_itself(monkeypatch):
    db = FakeDB()
    _seed_asset(db, purchase_date="2026-04-01")
    other = _seed_asset(db, purchase_date="2026-04-01")
    other["id"], other["asset_code"] = "asset-2", "FA-002"
    # Intangibles has no Schedule II life, and the row records no rate: the
    # engine refuses rather than charging a made-up rate to the ledger.
    other["asset_category"], other["wdv_rate_percent"] = "Intangibles", None

    got = _run(db, monkeypatch, to_period="2026-06")
    by_code = {a["asset_code"]: a for a in got["assets"]}
    assert by_code["FA-001"]["months_posted"] == 3
    assert by_code["FA-002"]["months_posted"] == 0
    assert by_code["FA-002"]["stopped_at"] == "2026-04"
    assert by_code["FA-002"]["reason"], "a refusal must never be silent"
    assert got["months_posted"] == 3


def test_a_locked_period_stops_that_asset_and_says_why(monkeypatch):
    """The client lock this commit started asking. A filed GSTR-3B covers exactly
    the period-end date a depreciation entry carries."""
    db = FakeDB()
    _seed_asset(db, purchase_date="2026-04-01")
    db.lock_reason = "GSTR-3B for April 2026 was filed on 18-05-2026."
    got = _run(db, monkeypatch, to_period="2026-06")
    assert got["months_posted"] == 0
    assert got["assets"][0]["stopped_at"] == "2026-04"
    assert "GSTR-3B" in got["assets"][0]["reason"]


def test_a_disposed_asset_is_not_in_the_run(monkeypatch):
    db = FakeDB()
    a = _seed_asset(db, purchase_date="2026-04-01")
    a["is_disposed"] = True
    got = _run(db, monkeypatch)
    assert got["assets_considered"] == 0 and got["months_posted"] == 0


def test_a_fully_depreciated_asset_stops_and_says_so(monkeypatch):
    db = FakeDB()
    _seed_asset(db, purchase_date="2026-04-01", purchase_cost_paise=100_000_00,
                accumulated_depreciation_paise=100_000_00)
    got = _run(db, monkeypatch, to_period="2026-06")
    assert got["assets"][0]["months_posted"] == 0
    assert "fully depreciated" in got["assets"][0]["reason"].lower()


# ══════════════════════════════════════════════════════════════════════════════
# The chunk, and the refusals the request itself gets
# ══════════════════════════════════════════════════════════════════════════════

def test_the_run_is_chunked_and_says_what_is_left(monkeypatch):
    """`lib/api` aborts a request at 45 seconds and deliberately never retries
    it, so a 6,000-journal run cannot be one call. It stops at the cap and the
    screen calls again — each asset's own posted-through says where to resume."""
    monkeypatch.setattr(fa, "DEPRECIATION_RUN_CHUNK", 5)
    db = FakeDB()
    _seed_asset(db, purchase_date="2026-04-01")
    got = _run(db, monkeypatch)
    assert got["months_posted"] == 5
    assert got["remaining_months"] == 7
    assert got["chunk_limit"] == 5

    rest = _run(db, monkeypatch)
    assert rest["months_posted"] == 5 and rest["remaining_months"] == 2


def test_a_backwards_range_is_refused(monkeypatch):
    db = FakeDB()
    with pytest.raises(HTTPException) as e:
        _run(db, monkeypatch, from_period="2026-06", to_period="2026-04")
    assert e.value.status_code == 422
    assert "before from_period" in str(e.value.detail)


def test_a_malformed_period_is_refused(monkeypatch):
    db = FakeDB()
    for bad in ("2026-13", "2026", "26-04", "2026-4"):
        with pytest.raises(HTTPException) as e:
            _run(db, monkeypatch, from_period=bad)
        assert e.value.status_code == 422, bad


# ══════════════════════════════════════════════════════════════════════════════
# The single endpoint is unchanged
# ══════════════════════════════════════════════════════════════════════════════

def test_the_single_endpoint_still_refuses_a_skipped_month(monkeypatch):
    """The runner exists beside this rule, not instead of it. A click that asks
    for October is not asking for September."""
    from models.accounting import DepreciationIn
    db = FakeDB()
    _seed_asset(db, purchase_date="2026-04-01")
    monkeypatch.setattr(fa, "_db", lambda: db)
    monkeypatch.setattr(fa, "can_access_client", lambda *a, **k: True)
    fa.post_depreciation("asset-1", DepreciationIn(period="2026-04"), USER)
    with pytest.raises(HTTPException) as e:
        fa.post_depreciation("asset-1", DepreciationIn(period="2026-07"), USER)
    assert "2026-05, 2026-06" in str(e.value.detail)


def test_the_single_endpoint_and_the_runner_charge_the_same_month(monkeypatch):
    from models.accounting import DepreciationIn
    single_db = FakeDB()
    _seed_asset(single_db, purchase_date="2026-04-01", wdv_rate_percent=24.0)
    monkeypatch.setattr(fa, "_db", lambda: single_db)
    monkeypatch.setattr(fa, "can_access_client", lambda *a, **k: True)
    single = fa.post_depreciation("asset-1", DepreciationIn(period="2026-04"), USER)["data"]

    run_db = FakeDB()
    _seed_asset(run_db, purchase_date="2026-04-01", wdv_rate_percent=24.0)
    ran = _run(run_db, monkeypatch, to_period="2026-04")
    assert ran["assets"][0]["months"][0]["depreciation_paise"] == single["depreciation_paise"]
