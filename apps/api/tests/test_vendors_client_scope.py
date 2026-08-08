"""
Client-assignment scope on the vendors router.

Mirrors `test_customers_client_scope.py` exactly — `vendors.py` is a
structural copy of `customers.py` (`VendorIn.client_id` is required, same as
`CustomerIn`'s), and the fix is the same shape: `create_vendor` and
`bulk_create_vendors` already checked the client on the way in (task #231);
every other endpoint — including a write that can post a real opening-balance
GL journal, a soft delete, and a PERMANENT delete that CASCADEs across bills
and payments — checked only the firm.

TWO ENDPOINTS THIS ROUTER HAS THAT `customers.py` DOES NOT
    `ap_aging` and `vendor_statement` both take `client_id` as a query param
    and are guarded the same way. `vendor_statement` also takes `vendor_id` in
    the path — `vendor_statement_service._vendor` already ties vendor_id to
    client_id server-side (both columns must match one row), so the client
    check on `client_id` is sufficient without a second vendor-level check;
    a test drives that tie-together for real rather than assuming the
    service's own docstring is still accurate.
"""
import pytest
from fastapi import HTTPException

import routers.vendors as ve
from models.parties import VendorIn, VendorUpdateIn

FIRM = "firm-1"
MINE, THEIRS = "client-mine", "client-theirs"
USER = {"id": "u1", "firm_id": FIRM, "role": "Executive"}


@pytest.fixture
def deny(monkeypatch):
    """Refuse one client, allow the rest — a real assignment boundary, and it
    catches a guard that resolves the wrong row's client."""
    seen = []

    def _assert(user, client_id):
        seen.append(client_id)
        if client_id == THEIRS:
            raise HTTPException(status_code=404, detail="Not found")

    def _can(user, client_id):
        seen.append(client_id)
        return client_id != THEIRS

    monkeypatch.setattr(ve, "assert_client_access", _assert)
    monkeypatch.setattr(ve, "can_access_client", _can)
    return seen


# ══════════════════════════════════════════════════════════════════════════════
# Query-param endpoints
# ══════════════════════════════════════════════════════════════════════════════

def test_listing_another_clients_vendors_is_refused(deny):
    with pytest.raises(HTTPException) as e:
        ve.list_vendors(client_id=THEIRS, include_inactive=False,
                        current_user=USER)
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_the_refusal_is_not_swallowed_into_a_200(deny):
    """list_vendors ends in a bare `except Exception:` with no
    `except HTTPException: raise` ahead of it — a guard inside that block
    would turn the 404 into a 200 nobody checks the status of."""
    try:
        ve.list_vendors(client_id=THEIRS, include_inactive=False,
                        current_user=USER)
    except HTTPException:
        return
    pytest.fail("list_vendors converted the refusal into a normal return value")


def test_listing_your_own_vendors_still_works(deny, monkeypatch):
    monkeypatch.setattr(ve, "MOCK_VENDORS",
                        [{"id": "V1", "firm_id": FIRM, "client_id": MINE,
                          "is_active": True}])
    out = ve.list_vendors(client_id=MINE, include_inactive=False,
                          current_user=USER)
    assert [v["id"] for v in out["data"]] == ["V1"]
    assert deny == [MINE]


def test_ap_aging_refuses_another_client(deny, monkeypatch):
    reached = []
    monkeypatch.setattr("services.vendor_statement_service.vendor_statement_service.ap_aging",
                        lambda *a, **k: reached.append(a) or {})
    with pytest.raises(HTTPException):
        ve.ap_aging(client_id=THEIRS, as_of=None, current_user=USER)
    assert reached == [], "the aging report ran despite the refusal"


def test_ap_aging_still_works_for_your_own_client(deny, monkeypatch):
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: object())
    monkeypatch.setattr("services.vendor_statement_service.vendor_statement_service.ap_aging",
                        lambda *a, **k: {"buckets": {}})
    out = ve.ap_aging(client_id=MINE, as_of=None, current_user=USER)
    assert out["success"] is True


def test_vendor_statement_refuses_another_client(deny, monkeypatch):
    reached = []
    monkeypatch.setattr("services.vendor_statement_service.vendor_statement_service.generate",
                        lambda *a, **k: reached.append(a) or {})
    with pytest.raises(HTTPException):
        ve.vendor_statement("V-ANY", client_id=THEIRS, start_date="2026-04-01",
                            end_date="2026-04-30", current_user=USER)
    assert reached == [], "the statement was generated despite the refusal"


def test_vendor_statement_ties_vendor_to_the_named_client(deny, monkeypatch):
    """Guarding only client_id would be wrong if the SERVICE ever stopped
    verifying vendor_id belongs to that same client — this drives the real
    service function rather than trusting its docstring."""
    from services.vendor_statement_service import vendor_statement_service

    class _FakeQ:
        def __init__(self, rows):
            self.rows, self.filters = rows, []
        def select(self, *_a, **_k): return self
        def eq(self, col, val):
            self.filters.append((col, val))
            return self
        def is_(self, *_a, **_k): return self
        def limit(self, *_a, **_k): return self
        def execute(self):
            out = self.rows
            for col, val in self.filters:
                out = [r for r in out if r.get(col) == val]
            class _R: pass
            r = _R(); r.data = out
            return r

    class _FakeDb:
        def __init__(self, vendor_row):
            self.vendor_row = vendor_row
        def table(self, name):
            rows = [self.vendor_row] if name == "vendors" else []
            return _FakeQ(rows)

    # A real vendor, but it belongs to a DIFFERENT client than the one named —
    # vendor_id and client_id disagree, so the service's own _vendor lookup
    # (id + firm_id + client_id, all three) must refuse it regardless of RBAC.
    db = _FakeDb({"id": "V-1", "firm_id": FIRM, "client_id": THEIRS})
    with pytest.raises(HTTPException) as e:
        vendor_statement_service._vendor(db, FIRM, MINE, "V-1")
    assert e.value.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# The row-addressed helper itself
# ══════════════════════════════════════════════════════════════════════════════

VENDORS = {
    "V-MINE": {"id": "V-MINE", "firm_id": FIRM, "client_id": MINE,
               "name": "Acme Supplies", "opening_balance_paise": 50000,
               "is_active": True},
    "V-MINE-CLEAN": {"id": "V-MINE-CLEAN", "firm_id": FIRM, "client_id": MINE,
                     "name": "Acme Clean", "opening_balance_paise": 0,
                     "is_active": True},
    "V-THEIRS": {"id": "V-THEIRS", "firm_id": FIRM, "client_id": THEIRS,
                 "name": "Beta Traders", "opening_balance_paise": 0,
                 "is_active": True},
    "V-ALIEN": {"id": "V-ALIEN", "firm_id": "firm-2", "client_id": "c-x",
                "name": "Gamma Corp", "opening_balance_paise": 0,
                "is_active": True},
}


@pytest.fixture
def vendors(monkeypatch):
    monkeypatch.setattr(ve, "MOCK_VENDORS", [dict(v) for v in VENDORS.values()])
    return ve.MOCK_VENDORS


def test_load_refuses_another_clients_vendor(deny, vendors):
    with pytest.raises(HTTPException) as e:
        ve._load_vendor_or_404(USER, "V-THEIRS")
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_load_returns_your_own_vendor(deny, vendors):
    row = ve._load_vendor_or_404(USER, "V-MINE")
    assert row["name"] == "Acme Supplies"
    assert deny == [MINE]


def test_load_refuses_another_firms_vendor_before_the_client_check(deny, vendors):
    """Tenancy first: a foreign firm's row must be refused without its client
    ever being looked at."""
    with pytest.raises(HTTPException) as e:
        ve._load_vendor_or_404(USER, "V-ALIEN")
    assert e.value.status_code == 404
    assert deny == [], "the client guard was reached for another firm's row"


def test_missing_and_hidden_vendors_use_the_identical_message_template(deny, vendors):
    """The message echoes back the id the CALLER supplied, which discloses
    nothing new — but the underlying REASON must never otherwise leak.
    Checked against each id's own expected template rather than against each
    other, since two different ids always differ in the echoed portion."""
    with pytest.raises(HTTPException) as missing:
        ve._load_vendor_or_404(USER, "V-NOPE")
    with pytest.raises(HTTPException) as hidden:
        ve._load_vendor_or_404(USER, "V-THEIRS")
    assert missing.value.status_code == hidden.value.status_code == 404
    assert missing.value.detail == "Vendor V-NOPE not found"
    assert hidden.value.detail == "Vendor V-THEIRS not found"


# ══════════════════════════════════════════════════════════════════════════════
# Every row-addressed endpoint, driven for real
# ══════════════════════════════════════════════════════════════════════════════

def test_reading_another_clients_vendor_is_refused(deny, vendors):
    with pytest.raises(HTTPException):
        ve.get_vendor("V-THEIRS", current_user=USER)


def test_reading_your_own_vendor_still_works(deny, vendors):
    out = ve.get_vendor("V-MINE", current_user=USER)
    assert out["data"]["name"] == "Acme Supplies"


def test_updating_another_clients_vendor_is_refused(deny, vendors):
    """This can post a real opening-balance GL journal — the refusal has to
    land before the update, not just before the journal-sync branch."""
    with pytest.raises(HTTPException):
        ve.update_vendor("V-THEIRS", VendorUpdateIn(name="Renamed"),
                         current_user=USER)
    assert [v["name"] for v in vendors if v["id"] == "V-THEIRS"] == ["Beta Traders"]


def test_updating_your_own_vendor_still_works(deny, vendors):
    out = ve.update_vendor("V-MINE", VendorUpdateIn(name="Renamed"),
                           current_user=USER)
    assert out["data"]["name"] == "Renamed"


def test_dependencies_refuses_another_clients_vendor(deny, vendors):
    with pytest.raises(HTTPException):
        ve.get_vendor_dependencies("V-THEIRS", current_user=USER)


def test_dependencies_still_works_for_your_own_vendor(deny, vendors):
    out = ve.get_vendor_dependencies("V-MINE", current_user=USER)
    assert out["data"]["can_delete"] is False  # opening balance present


class _FakeQ:
    """Just enough of the Supabase query builder for get_vendor_outstanding:
    records which TABLE each call touched, then returns canned rows."""
    def __init__(self, name, rows, log):
        self.name, self.rows, self.log = name, rows, log
    def select(self, *_a, **_k): return self
    def eq(self, *_a, **_k): return self
    def not_(self): return self
    def in_(self, *_a, **_k): return self
    def limit(self, *_a, **_k): return self
    def execute(self):
        self.log.append(self.name)
        class _R: pass
        r = _R(); r.data = self.rows
        return r


class _FakeDb:
    def __init__(self, vendor_row):
        self.vendor_row, self.log = vendor_row, []
    def table(self, name):
        rows = [self.vendor_row] if name == "vendors" else []
        return _FakeQ(name, rows, self.log)


def test_outstanding_by_id_refuses_another_clients_vendor(deny, monkeypatch):
    db = _FakeDb({"id": "V-THEIRS", "firm_id": FIRM, "client_id": THEIRS,
                  "opening_balance_paise": 0})
    monkeypatch.setattr(ve, "_USE_MOCK", False)
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: db)
    with pytest.raises(HTTPException):
        ve.get_vendor_outstanding("V-THEIRS", current_user=USER)
    assert db.log == ["vendors"], \
        "the bill ledger was read despite the refusal"


# ── delete_vendor: soft delete and permanent, both branches ──────────────────

def test_soft_deleting_another_clients_vendor_is_refused(deny, vendors):
    with pytest.raises(HTTPException):
        ve.delete_vendor("V-THEIRS", current_user=USER, permanent=False)
    assert [v["is_active"] for v in vendors if v["id"] == "V-THEIRS"] == [True]


def test_soft_deleting_your_own_vendor_still_works(deny, vendors):
    out = ve.delete_vendor("V-MINE", current_user=USER, permanent=False)
    assert out["data"]["is_active"] is False


def test_permanently_deleting_another_clients_vendor_is_refused(deny, vendors):
    """The heaviest write in the router — CASCADE FKs would otherwise destroy
    the client's bills and payments silently."""
    with pytest.raises(HTTPException):
        ve.delete_vendor("V-THEIRS", current_user=USER, permanent=True)
    assert any(v["id"] == "V-THEIRS" for v in vendors), \
        "the vendor was permanently deleted despite the refusal"


def test_permanently_deleting_your_own_clean_vendor_still_works(deny, vendors):
    """V-MINE-CLEAN has no opening balance and no dependencies, so it clears
    the router's own has_any check — proving the M2 guard steps aside for a
    legitimate call rather than merely refusing everything."""
    out = ve.delete_vendor("V-MINE-CLEAN", current_user=USER, permanent=True)
    assert out["data"]["deleted"] is True
    assert not any(v["id"] == "V-MINE-CLEAN" for v in vendors)


def test_permanently_deleting_your_own_vendor_with_a_balance_hits_the_business_rule(
        deny, vendors):
    """V-MINE carries an opening balance. The M2 guard must run and let this
    through to the router's OWN 409 — not swallow it into another 404."""
    with pytest.raises(HTTPException) as e:
        ve.delete_vendor("V-MINE", current_user=USER, permanent=True)
    assert e.value.status_code == 409


def test_delete_uses_the_same_message_template_for_missing_and_hidden(deny, vendors):
    with pytest.raises(HTTPException) as missing:
        ve.delete_vendor("V-NOPE", current_user=USER, permanent=False)
    with pytest.raises(HTTPException) as hidden:
        ve.delete_vendor("V-THEIRS", current_user=USER, permanent=False)
    assert missing.value.status_code == hidden.value.status_code == 404
    assert missing.value.detail == "Vendor V-NOPE not found"
    assert hidden.value.detail == "Vendor V-THEIRS not found"


# ── The live query path, where the firm filter actually lives ────────────────
# The mock branch has no firm filter of its own to accidentally drop — the
# mutant that deletes _load_vendor_or_404's live .eq("firm_id", ...) call
# survives every mock-path test because nothing in the mock store depends on
# it. Only a real query can show this (same lesson as customers/relationships).

class _ScopeFakeQ:
    def __init__(self, rows, log):
        self.rows, self.log, self.filters = rows, log, []
    def select(self, *_a, **_k): return self
    def eq(self, col, val):
        self.filters.append((col, val))
        return self
    def limit(self, *_a, **_k): return self
    def execute(self):
        self.log.append(list(self.filters))
        out = self.rows
        for col, val in self.filters:
            out = [r for r in out if r.get(col) == val]
        class _R: pass
        r = _R(); r.data = out
        return r


class _ScopeFakeDb:
    def __init__(self, rows):
        self.rows, self.log = rows, []
    def table(self, _name):
        return _ScopeFakeQ(self.rows, self.log)


def test_live_load_refuses_another_firms_vendor_before_the_client_check(deny,
                                                                        monkeypatch):
    """A row wearing FIRM's own id-space but actually owned by firm-2. Only
    reachable if BOTH the firm filter on the query and the client check hold —
    this is what confirms the firm filter is not decorative."""
    db = _ScopeFakeDb([{"id": "V-ALIEN", "firm_id": "firm-2", "client_id": "c-x"}])
    monkeypatch.setattr(ve, "_USE_MOCK", False)
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: db)
    with pytest.raises(HTTPException) as e:
        ve._load_vendor_or_404(USER, "V-ALIEN")
    assert e.value.status_code == 404
    assert deny == [], "the client guard was reached for another firm's row"
    assert db.log and ("firm_id", FIRM) in db.log[0], \
        "the live query never filtered by the caller's own firm_id"


# ══════════════════════════════════════════════════════════════════════════════
# The real e2e harness, where PostgREST column projection actually applies
# ══════════════════════════════════════════════════════════════════════════════
# customers.py has test_customer_lifecycle.py driving delete_customer/
# update_customer through the real FakeDB (which honours SELECT column lists,
# per the reconciliation-phase fix) — that harness, not the client-scope unit
# tests, is what proves _load_customer_or_404 fetches ENOUGH of the row for
# opening_balance_paise to survive a live query. vendors.py has no lifecycle
# test file at all, so nothing exercised the equivalent path here. Two tests,
# not a whole mirror file — enough to close the two mutants that survived.

from tests.e2e_harness import FakeDB, wire_e2e

_E2E_FIRM = "FIRM-A"
_E2E_CALLER = {"firm_id": _E2E_FIRM, "auth_user_id": "u1", "email": "ca@f.test",
              "role": "Partner"}


def _e2e_setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [ve])
    db.seed("clients", {"id": "CLI", "firm_id": _E2E_FIRM})
    return db


def test_e2e_the_live_load_carries_the_opening_balance(monkeypatch):
    """If _load_vendor_or_404's live SELECT narrowed its column list back down
    to id/name, this would still pass by accident (opening_balance_paise would
    just read as 0, which is also this fixture's true starting value) — so the
    balance is set to a value that could not arise from a dropped column
    silently defaulting to falsy."""
    db = _e2e_setup(monkeypatch)
    db.seed("vendors", {"id": "VEND", "firm_id": _E2E_FIRM, "client_id": "CLI",
                        "name": "Acme", "is_active": True,
                        "opening_balance_paise": 12345})
    out = ve.get_vendor_dependencies("VEND", current_user=_E2E_CALLER)
    assert out["data"]["dependencies"]["opening_balance"] == 1
    assert out["data"]["can_delete"] is False


def test_e2e_permanent_delete_is_blocked_by_a_real_opening_balance(monkeypatch):
    """The mutant this closes: the permanent-delete branch reusing a stale
    opening figure of 0 regardless of the row's actual balance, which would
    let a vendor with real money owed be permanently deleted."""
    db = _e2e_setup(monkeypatch)
    db.seed("vendors", {"id": "VEND", "firm_id": _E2E_FIRM, "client_id": "CLI",
                        "name": "Acme", "is_active": True,
                        "opening_balance_paise": 500_00})
    with pytest.raises(HTTPException) as e:
        ve.delete_vendor("VEND", current_user=_E2E_CALLER, permanent=True)
    assert e.value.status_code == 409
    assert any(r["id"] == "VEND" for r in db.rows("vendors")), \
        "the vendor was deleted despite carrying a real opening balance"


def test_e2e_permanent_delete_succeeds_when_genuinely_clean(monkeypatch):
    db = _e2e_setup(monkeypatch)
    db.seed("vendors", {"id": "VEND", "firm_id": _E2E_FIRM, "client_id": "CLI",
                        "name": "Acme", "is_active": True,
                        "opening_balance_paise": 0})
    out = ve.delete_vendor("VEND", current_user=_E2E_CALLER, permanent=True)
    assert out["success"] is True
    assert not any(r["id"] == "VEND" for r in db.rows("vendors"))
