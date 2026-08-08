"""
Client-assignment scope on the customers router.

`create_customer` and `bulk_create_customers` already checked the client on
the way in (task #231). Every OTHER endpoint — including a write that can post
a real opening-balance journal, a soft delete, and a PERMANENT delete that
CASCADEs across invoices/receipts/credit notes — checked only the firm.
`customers.client_id` is required by `CustomerIn`, so it is never absent on a
real row: nothing here is a template or firm-level resource in disguise.

TWO SHAPES

  * query-param endpoints (list / outstanding-summary / ar-aging) get
    assert_client_access BEFORE the `try` — several handlers in this file end
    in a bare `except Exception:` with no `except HTTPException: raise` ahead
    of it, so a guard placed inside would have its refusal caught and turned
    into a 200. Placed uniformly, not just on the handlers that need it.
  * row-addressed endpoints resolve through `_load_customer_or_404`, which
    always selects the WHOLE row — several call sites here originally selected
    only `opening_balance_paise`, and a guard reading `client_id` off a row
    that never fetched it would silently pass (the F1/FakeDB lesson from the
    reconciliation phase, applied for real this time: a missing client_id
    reads as "firm-level" and is let through).

THE MOCK BRANCHES WERE INCONSISTENT WITH EACH OTHER, TOO
    `list_customers`'s mock branch already filtered by firm_id. `get_customer`,
    `update_customer`, `get_customer_dependencies` and `delete_customer`'s mock
    branches did not — they matched on id alone. Centralizing every
    row-addressed lookup through one helper fixes that as the same change.
"""
import pytest
from fastapi import HTTPException

import routers.customers as cu
from models.parties import CustomerIn, CustomerUpdateIn

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

    monkeypatch.setattr(cu, "assert_client_access", _assert)
    monkeypatch.setattr(cu, "can_access_client", _can)
    return seen


# ══════════════════════════════════════════════════════════════════════════════
# Query-param endpoints
# ══════════════════════════════════════════════════════════════════════════════

def test_listing_another_clients_customers_is_refused(deny):
    with pytest.raises(HTTPException) as e:
        cu.list_customers(client_id=THEIRS, include_inactive=False,
                          current_user=USER)
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_the_refusal_is_not_swallowed_into_a_200(deny):
    """list_customers ends in a bare `except Exception:` with no
    `except HTTPException: raise` ahead of it — a guard inside that block
    would turn the 404 into a 200 nobody checks the status of."""
    try:
        cu.list_customers(client_id=THEIRS, include_inactive=False,
                          current_user=USER)
    except HTTPException:
        return
    pytest.fail("list_customers converted the refusal into a normal return value")


def test_listing_your_own_customers_still_works(deny, monkeypatch):
    monkeypatch.setattr(cu, "MOCK_CUSTOMERS",
                        [{"id": "C1", "firm_id": FIRM, "client_id": MINE,
                          "is_active": True}])
    out = cu.list_customers(client_id=MINE, include_inactive=False,
                            current_user=USER)
    assert [c["id"] for c in out["data"]] == ["C1"]
    assert deny == [MINE]


def test_outstanding_summary_refuses_another_client(deny):
    with pytest.raises(HTTPException):
        cu.get_outstanding_summary(client_id=THEIRS, current_user=USER)


def test_ar_aging_refuses_another_client(deny):
    with pytest.raises(HTTPException):
        cu.ar_aging(client_id=THEIRS, as_of=None, current_user=USER)


# ══════════════════════════════════════════════════════════════════════════════
# The row-addressed helper itself
# ══════════════════════════════════════════════════════════════════════════════

CUSTOMERS = {
    "C-MINE": {"id": "C-MINE", "firm_id": FIRM, "client_id": MINE,
               "name": "Acme", "opening_balance_paise": 50000, "is_active": True},
    "C-MINE-CLEAN": {"id": "C-MINE-CLEAN", "firm_id": FIRM, "client_id": MINE,
                     "name": "Acme Clean", "opening_balance_paise": 0,
                     "is_active": True},
    "C-THEIRS": {"id": "C-THEIRS", "firm_id": FIRM, "client_id": THEIRS,
                 "name": "Beta", "opening_balance_paise": 0, "is_active": True},
    "C-ALIEN": {"id": "C-ALIEN", "firm_id": "firm-2", "client_id": "c-x",
                "name": "Gamma", "opening_balance_paise": 0, "is_active": True},
}


@pytest.fixture
def customers(monkeypatch):
    monkeypatch.setattr(cu, "MOCK_CUSTOMERS", [dict(c) for c in CUSTOMERS.values()])
    return cu.MOCK_CUSTOMERS


def test_load_refuses_another_clients_customer(deny, customers):
    with pytest.raises(HTTPException) as e:
        cu._load_customer_or_404(USER, "C-THEIRS")
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_load_returns_your_own_customer(deny, customers):
    row = cu._load_customer_or_404(USER, "C-MINE")
    assert row["name"] == "Acme"
    assert deny == [MINE]


def test_load_refuses_another_firms_customer_before_the_client_check(deny, customers):
    """Tenancy first: a foreign firm's row must be refused without its client
    ever being looked at."""
    with pytest.raises(HTTPException) as e:
        cu._load_customer_or_404(USER, "C-ALIEN")
    assert e.value.status_code == 404
    assert deny == [], "the client guard was reached for another firm's row"


def test_missing_and_hidden_customers_use_the_identical_message_template(deny,
                                                                        customers):
    """The message echoes back the id the CALLER supplied — which they already
    know, so it discloses nothing new — but must never otherwise distinguish
    "does not exist" from "exists, but you cannot see it". Comparing across two
    DIFFERENT ids would always differ in the echoed portion regardless of
    whether the underlying reason leaks, so this checks each against its own
    f"Customer {id} not found" template instead of against each other."""
    with pytest.raises(HTTPException) as missing:
        cu._load_customer_or_404(USER, "C-NOPE")
    with pytest.raises(HTTPException) as hidden:
        cu._load_customer_or_404(USER, "C-THEIRS")
    assert missing.value.status_code == hidden.value.status_code == 404
    assert missing.value.detail == "Customer C-NOPE not found"
    assert hidden.value.detail == "Customer C-THEIRS not found"


# ══════════════════════════════════════════════════════════════════════════════
# Every row-addressed endpoint, driven for real
# ══════════════════════════════════════════════════════════════════════════════

def test_reading_another_clients_customer_is_refused(deny, customers):
    with pytest.raises(HTTPException):
        cu.get_customer("C-THEIRS", current_user=USER)


def test_reading_your_own_customer_still_works(deny, customers):
    out = cu.get_customer("C-MINE", current_user=USER)
    assert out["data"]["name"] == "Acme"


def test_updating_another_clients_customer_is_refused(deny, customers):
    """This can post a real opening-balance GL journal — the refusal has to
    land before the update, not just before the journal-sync branch."""
    with pytest.raises(HTTPException):
        cu.update_customer("C-THEIRS", CustomerUpdateIn(name="Renamed"),
                           current_user=USER)
    assert [c["name"] for c in customers if c["id"] == "C-THEIRS"] == ["Beta"]


def test_updating_your_own_customer_still_works(deny, customers):
    out = cu.update_customer("C-MINE", CustomerUpdateIn(name="Renamed"),
                             current_user=USER)
    assert out["data"]["name"] == "Renamed"


def test_dependencies_refuses_another_clients_customer(deny, customers):
    with pytest.raises(HTTPException):
        cu.get_customer_dependencies("C-THEIRS", current_user=USER)


def test_dependencies_still_works_for_your_own_customer(deny, customers):
    out = cu.get_customer_dependencies("C-MINE", current_user=USER)
    assert out["data"]["can_delete"] is False  # opening balance present


class _FakeQ:
    """Just enough of the Supabase query builder for get_customer_outstanding:
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
    def __init__(self, customer_row):
        self.customer_row, self.log = customer_row, []
    def table(self, name):
        rows = [self.customer_row] if name == "customers" else []
        return _FakeQ(name, rows, self.log)


def test_outstanding_by_id_refuses_another_clients_customer(deny, monkeypatch):
    db = _FakeDb({"id": "C-THEIRS", "firm_id": FIRM, "client_id": THEIRS,
                  "opening_balance_paise": 0})
    monkeypatch.setattr(cu, "_USE_MOCK", False)
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: db)
    with pytest.raises(HTTPException):
        cu.get_customer_outstanding("C-THEIRS", current_user=USER)
    assert db.log == ["customers"], \
        "the invoice ledger was read despite the refusal"


# ── delete_customer: soft delete and permanent, both branches ────────────────

def test_soft_deleting_another_clients_customer_is_refused(deny, customers):
    with pytest.raises(HTTPException):
        cu.delete_customer("C-THEIRS", current_user=USER, permanent=False)
    assert [c["is_active"] for c in customers if c["id"] == "C-THEIRS"] == [True]


def test_soft_deleting_your_own_customer_still_works(deny, customers):
    out = cu.delete_customer("C-MINE", current_user=USER, permanent=False)
    assert out["data"]["is_active"] is False


def test_permanently_deleting_another_clients_customer_is_refused(deny, customers):
    """The heaviest write in the router — CASCADE FKs would otherwise destroy
    the client's invoices, receipts and credit notes silently."""
    with pytest.raises(HTTPException):
        cu.delete_customer("C-THEIRS", current_user=USER, permanent=True)
    assert any(c["id"] == "C-THEIRS" for c in customers), \
        "the customer was permanently deleted despite the refusal"


def test_permanently_deleting_your_own_clean_customer_still_works(deny, customers):
    """C-MINE-CLEAN has no opening balance and no dependencies, so it clears
    the router's own has_any check — proving the M2 guard steps aside for a
    legitimate call rather than merely refusing everything."""
    out = cu.delete_customer("C-MINE-CLEAN", current_user=USER, permanent=True)
    assert out["data"]["deleted"] is True
    assert not any(c["id"] == "C-MINE-CLEAN" for c in customers)


def test_permanently_deleting_your_own_customer_with_a_balance_hits_the_business_rule(
        deny, customers):
    """C-MINE carries an opening balance. The M2 guard must run and let this
    through to the router's OWN 409 — not swallow it into another 404."""
    with pytest.raises(HTTPException) as e:
        cu.delete_customer("C-MINE", current_user=USER, permanent=True)
    assert e.value.status_code == 409


def test_delete_uses_the_same_message_template_for_missing_and_hidden(deny,
                                                                     customers):
    with pytest.raises(HTTPException) as missing:
        cu.delete_customer("C-NOPE", current_user=USER, permanent=False)
    with pytest.raises(HTTPException) as hidden:
        cu.delete_customer("C-THEIRS", current_user=USER, permanent=False)
    assert missing.value.status_code == hidden.value.status_code == 404
    assert missing.value.detail == "Customer C-NOPE not found"
    assert hidden.value.detail == "Customer C-THEIRS not found"


# ── The live query path, where the firm filter actually lives ────────────────
# `test_load_refuses_another_firms_customer_before_the_client_check` above
# drives the mock branch, where MOCK_CUSTOMERS has no firm filter of its own to
# accidentally drop — the mutant that deletes _load_customer_or_404's live
# .eq("firm_id", ...) call survives every mock-path test because nothing in
# the mock store depends on it. Only a real query can show this.

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


def test_live_load_refuses_another_firms_customer_before_the_client_check(deny,
                                                                          monkeypatch):
    """A row wearing FIRM's own id-space but actually owned by firm-2. Only
    reachable if BOTH the firm filter on the query and the client check hold —
    this is what confirms the firm filter is not decorative."""
    db = _ScopeFakeDb([{"id": "C-ALIEN", "firm_id": "firm-2", "client_id": "c-x"}])
    monkeypatch.setattr(cu, "_USE_MOCK", False)
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: db)
    with pytest.raises(HTTPException) as e:
        cu._load_customer_or_404(USER, "C-ALIEN")
    assert e.value.status_code == 404
    assert deny == [], "the client guard was reached for another firm's row"
    assert db.log and ("firm_id", FIRM) in db.log[0], \
        "the live query never filtered by the caller's own firm_id"
