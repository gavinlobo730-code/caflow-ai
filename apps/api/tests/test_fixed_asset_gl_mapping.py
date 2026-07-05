"""
Fixed Asset GL category mapping — regression tests (H2).

journal_for_asset_acquisition / journal_for_asset_disposal previously mapped
categories using abbreviated keys ("Furniture", "Computer", "Vehicle", ...)
that never match the frontend's actual category strings ("Furniture &
Fixtures", "Computer & IT Equipment", "Vehicles", ...) — so 7 of the 9 real
categories silently fell through to the "Plant & Machinery" default GL
account. This asserts every one of the 9 frontend categories now resolves to
its own correct account.
"""
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import services.phase2_journal_service as pjs
from services.phase2_journal_service import Phase2JournalService

FIRM, CLIENT = "firm-1", "client-1"


# ── Fake Supabase with real ILIKE matching (needed to prove which account a
#    given category pattern actually resolves to — a no-op ilike, as used by
#    other tests' fakes, would hide exactly the bug this test targets) ──────

def _ilike_match(value, pattern):
    if value is None:
        return False
    regex = "^" + "".join(".*" if c == "%" else re.escape(c) for c in pattern) + "$"
    return re.match(regex, value, re.IGNORECASE) is not None


class _Resp:
    def __init__(self, data):
        self.data = data


class _Q:
    def __init__(self, store, table):
        self.s, self.t = store, table
        self.op = "select"
        self.payload = None
        self.f = []
        self.ilike_ = None
        self.single_ = False

    def insert(self, p):
        self.op, self.payload = "insert", p
        return self

    def select(self, *a, **k):
        self.op = "select"
        return self

    def eq(self, k, v):
        self.f.append((k, v))
        return self

    def or_(self, *_a, **_k):
        return self

    def ilike(self, k, pattern):
        self.ilike_ = (k, pattern)
        return self

    def limit(self, _n):
        return self

    def single(self):
        self.single_ = True
        return self

    def _match(self):
        rows = self.s.setdefault(self.t, [])
        out = []
        for r in rows:
            if not all(r.get(k) == v for k, v in self.f):
                continue
            if self.ilike_ and not _ilike_match(r.get(self.ilike_[0]), self.ilike_[1]):
                continue
            out.append(r)
        return out

    def execute(self):
        if self.op == "insert":
            rows = self.s.setdefault(self.t, [])
            items = self.payload if isinstance(self.payload, list) else [self.payload]
            ins = []
            for p in items:
                rec = dict(p)
                rec.setdefault("id", f"{self.t}-{len(rows) + 1}")
                rows.append(rec)
                ins.append(rec)
            return _Resp(ins)
        m = self._match()
        if self.single_:
            return _Resp(m[0] if m else None)
        return _Resp(m)


class FakeDB:
    def __init__(self):
        self.store = {}

    def table(self, name):
        return _Q(self.store, name)


ACCOUNTS = [
    ("acc-pm",   "Plant & Machinery"),
    ("acc-ff",   "Furniture & Fixtures"),
    ("acc-cs",   "Computers & Software"),
    ("acc-oe",   "Office Equipment"),
    ("acc-veh",  "Vehicles"),
    ("acc-lb",   "Land & Building"),
    ("acc-ia",   "Intangible Assets"),
    ("acc-bank", "Bank Account"),
    ("acc-adep", "Accumulated Depreciation"),
    ("acc-gain", "Profit on Asset Disposal"),
    ("acc-loss", "Loss on Asset Disposal"),
]


def _db_with_accounts():
    db = FakeDB()
    db.store["chart_of_accounts"] = [
        {"id": i, "firm_id": FIRM, "client_id": None, "account_name": n,
         "system_account_key": ("bank" if n == "Bank Account" else None), "is_active": True}
        for (i, n) in ACCOUNTS
    ]
    return db


def _asset(category):
    return {
        "id": "asset-1", "asset_name": "Test Asset", "asset_code": "FA-001",
        "asset_category": category, "purchase_cost_paise": 100_000_00,
        "purchase_date": "2026-04-01",
    }


CATEGORY_TO_EXPECTED_ACCOUNT = {
    "Plant & Machinery":       "acc-pm",
    "Furniture & Fixtures":    "acc-ff",
    "Computer & IT Equipment": "acc-cs",
    "Office Equipment":        "acc-oe",
    "Vehicles":                "acc-veh",
    "Building":                "acc-lb",
    "Land":                    "acc-lb",
    "Intangibles":             "acc-ia",
    "Other":                   "acc-pm",  # falls back to the Plant & Machinery default
}


def _asset_account_line(db, je_id):
    lines = [l for l in db.store.get("journal_lines", []) if l["journal_entry_id"] == je_id]
    return next(l for l in lines if l["debit_paise"] > 0)  # asset acquisition Dr line


def test_every_frontend_category_maps_to_its_own_gl_account(monkeypatch):
    monkeypatch.setattr(pjs, "_USE_MOCK", False)
    svc = Phase2JournalService()

    for category, expected_account_id in CATEGORY_TO_EXPECTED_ACCOUNT.items():
        db = _db_with_accounts()
        monkeypatch.setattr("core.supabase_client.get_supabase", lambda db=db: db)

        je_id = svc.journal_for_asset_acquisition(_asset(category), FIRM, CLIENT)

        assert je_id is not None, f"category={category!r} failed to post a journal"
        line = _asset_account_line(db, je_id)
        assert line["account_id"] == expected_account_id, (
            f"category={category!r} resolved to account "
            f"{line['account_id']!r}, expected {expected_account_id!r}"
        )


def test_disposal_journal_uses_the_same_corrected_mapping(monkeypatch):
    """journal_for_asset_disposal carries its own (duplicate) cat_map — verify
    it was fixed too, not just the acquisition side."""
    monkeypatch.setattr(pjs, "_USE_MOCK", False)
    svc = Phase2JournalService()

    for category, expected_account_id in CATEGORY_TO_EXPECTED_ACCOUNT.items():
        db = _db_with_accounts()
        monkeypatch.setattr("core.supabase_client.get_supabase", lambda db=db: db)

        asset = _asset(category)
        asset["accumulated_depreciation_paise"] = 40_000_00
        je_id = svc.journal_for_asset_disposal(asset, 50_000_00, FIRM, CLIENT)

        assert je_id is not None, f"category={category!r} failed to post a disposal journal"
        lines = [l for l in db.store.get("journal_lines", []) if l["journal_entry_id"] == je_id]
        fixed_asset_line = next(l for l in lines if l["credit_paise"] == 100_000_00)
        assert fixed_asset_line["account_id"] == expected_account_id, (
            f"category={category!r} resolved to account "
            f"{fixed_asset_line['account_id']!r}, expected {expected_account_id!r}"
        )
