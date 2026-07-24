"""
Task #241 — fixed_assets.py's depreciation-schedule IDOR.

GET /api/fixed-assets/depreciation-schedule took a caller-supplied
?client_id= and queried the fixed_assets table filtered ONLY by client_id
and is_disposed=False -- no firm_id filter at all, even though every other
endpoint in this router (list_assets, create_asset, post_depreciation,
dispose_asset) already scopes by current_user["firm_id"]. Any authenticated
user in ANY firm could read another firm's full fixed-asset register
(purchase costs, WDV, depreciation schedule) by supplying its client_id.
"""
import routers.fixed_assets as fa_router
from routers.fixed_assets import depreciation_schedule

FIRM_A, CLIENT_A = "firm-A", "client-A"
FIRM_B, CLIENT_B = "firm-B", "client-B"

USER_A = {"id": "u1", "firm_id": FIRM_A, "role": "Partner", "auth_user_id": "auth-1", "email": "a@a.test"}
USER_B = {"id": "u2", "firm_id": FIRM_B, "role": "Partner", "auth_user_id": "auth-2", "email": "b@b.test"}


class _Resp:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count


class _Q:
    def __init__(self, store, table):
        self.s, self.t = store, table
        self.f = []

    def select(self, *_a, **_k):
        return self

    def eq(self, k, v):
        self.f.append((k, v))
        return self

    def execute(self):
        rows = self.s.setdefault(self.t, [])
        return _Resp([r for r in rows if all(r.get(k) == v for k, v in self.f)])


class FakeDB:
    def __init__(self):
        self.store = {}

    def table(self, name):
        return _Q(self.store, name)


def _seed_asset(db, firm_id, client_id, asset_id, **overrides):
    asset = {
        "id": asset_id, "firm_id": firm_id, "client_id": client_id,
        "asset_name": "Machine", "asset_code": asset_id.upper(),
        "asset_category": "Plant & Machinery", "is_disposed": False,
        "purchase_date": "2025-04-10",
        "purchase_cost_paise": 500_000_00, "salvage_value_paise": 0,
        "depreciation_method": "WDV", "wdv_rate_percent": 24.0,
        "accumulated_depreciation_paise": 0,
        "depreciation_posted_through": None,
        "depreciation_fy": None, "depreciation_fy_start_accum_paise": None,
    }
    asset.update(overrides)
    db.store.setdefault("fixed_assets", []).append(asset)
    return asset


def test_depreciation_schedule_excludes_another_firms_assets_for_the_same_client_id(monkeypatch):
    """Firm A and Firm B both happen to have a client using the id
    "client-A" (a plausible real-world collision, or simply Firm B's own
    client_id chosen to guess/enumerate Firm A's). Firm B's user must never
    see Firm A's asset register."""
    db = FakeDB()
    monkeypatch.setattr(fa_router, "_db", lambda: db)
    _seed_asset(db, FIRM_A, CLIENT_A, "asset-a1", asset_name="Firm A's Machine")

    resp = depreciation_schedule(client_id=CLIENT_A, current_user=USER_B)
    assert resp["data"] == []


def test_depreciation_schedule_returns_own_firms_assets(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(fa_router, "_db", lambda: db)
    _seed_asset(db, FIRM_A, CLIENT_A, "asset-a1", asset_name="Firm A's Machine")

    resp = depreciation_schedule(client_id=CLIENT_A, current_user=USER_A)
    assert len(resp["data"]) == 1
    assert resp["data"][0]["asset_name"] == "Firm A's Machine"


def test_depreciation_schedule_scopes_by_firm_even_with_matching_client_and_disposed_flag(monkeypatch):
    """Two firms both have a non-disposed asset under the SAME client_id --
    each firm must only ever see its own."""
    db = FakeDB()
    monkeypatch.setattr(fa_router, "_db", lambda: db)
    _seed_asset(db, FIRM_A, CLIENT_A, "asset-a1", asset_name="Firm A's Machine")
    _seed_asset(db, FIRM_B, CLIENT_A, "asset-b1", asset_name="Firm B's Machine")

    resp_a = depreciation_schedule(client_id=CLIENT_A, current_user=USER_A)
    resp_b = depreciation_schedule(client_id=CLIENT_A, current_user=USER_B)

    assert [a["asset_name"] for a in resp_a["data"]] == ["Firm A's Machine"]
    assert [a["asset_name"] for a in resp_b["data"]] == ["Firm B's Machine"]
