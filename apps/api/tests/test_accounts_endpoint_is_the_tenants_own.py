"""
/api/accounting/accounts serves the caller's chart, not a demo one.

WHAT WAS WRONG
    list_accounts() returned accounting_service.list_accounts() — the
    module-level MOCK_ACCOUNTS list. No firm_id, no client_id, no database.
    Driving a client through a full financial year found it returning 22
    accounts for a client whose chart_of_accounts table held zero rows.

    create_account and update_account were the same shape from the other
    direction: they wrote to MOCK_ACCOUNTS and reported success, so an account
    "created" through the API existed until the process restarted and never for
    the firm that asked.

    Nothing in the frontend calls any of the three — the screens read
    chart_of_accounts directly through PostgREST — so what it cost was an
    endpoint that lied rather than a screen that did. An endpoint that lies is
    worth less than no endpoint.
"""
import pytest
from fastapi import HTTPException

import routers.accounting as ac

USER = {"id": "u1", "firm_id": "f1", "auth_user_id": "a1", "email": "p@f.in", "role": "Partner"}
CLIENT = "11111111-1111-1111-1111-111111111111"


class DB:
    """Records the query the handler built."""

    def __init__(self, rows=None):
        self.rows = rows if rows is not None else [{"id": "a1", "account_code": "1001"}]
        self.filters = {}
        self.payload = None
        self.ors = []
        self.table_name = None

    def table(self, name):
        self.table_name = name
        return self

    def select(self, cols):
        self.cols = cols
        return self

    def eq(self, col, val):
        self.filters[col] = val
        return self

    def or_(self, expr):
        self.ors.append(expr)
        return self

    def order(self, _c):
        return self

    def limit(self, _n):
        return self

    def insert(self, payload):
        self.payload = payload
        return self

    def update(self, payload):
        self.payload = payload
        return self

    def execute(self):
        return type("R", (), {"data": self.rows})()


@pytest.fixture()
def db(monkeypatch):
    d = DB()
    monkeypatch.setattr(ac, "_prod_db", lambda: d)
    monkeypatch.setattr(ac, "assert_client_access", lambda *a, **k: None)
    monkeypatch.setattr(ac, "can_access_client", lambda *a, **k: True)
    return d


# ── Reading ──────────────────────────────────────────────────────────────────

def test_the_list_is_read_from_the_database_scoped_to_the_firm(db):
    out = ac.list_accounts(client_id=None, current_user=USER)
    assert out["success"]
    assert db.table_name == "chart_of_accounts"
    assert db.filters["firm_id"] == "f1"


def test_a_client_gets_its_own_accounts_and_the_firm_level_ones(db):
    """chart_of_accounts.client_id NULL is a firm-level account every client
    shares (migration 057), and seed_firm_coa creates exactly those. Filtering
    to the client's own rows alone would show an empty chart for every client
    of a normally-seeded firm — a different wrong answer from the one this
    replaces. Transcribed from SupabaseLedgerSource._accounts so the endpoint
    and the ledger cannot disagree about what a client's chart is."""
    ac.list_accounts(client_id=CLIENT, current_user=USER)
    assert db.ors == [f"client_id.eq.{CLIENT},client_id.is.null"]


def test_no_database_still_serves_the_in_memory_seed(monkeypatch):
    """Dev and demo, the same gate _reporting_service() uses."""
    monkeypatch.setattr(ac, "_prod_db", lambda: None)
    out = ac.list_accounts(client_id=None, current_user=USER)
    assert out["success"] and out["data"]


# ── Writing ──────────────────────────────────────────────────────────────────

def test_creating_an_account_writes_the_real_table(db):
    from models.accounting import AccountIn
    out = ac.create_account(
        AccountIn(name="Unbilled Revenue", code="1450", account_type="Asset"),
        client_id=None, current_user=USER)
    assert out["success"]
    assert db.table_name == "chart_of_accounts"
    assert db.payload["account_name"] == "Unbilled Revenue"
    assert db.payload["account_code"] == "1450"
    assert db.payload["firm_id"] == "f1"
    assert db.payload["client_id"] is None, "omitting client_id means firm-level"


def test_an_account_can_be_created_for_one_client(db):
    from models.accounting import AccountIn
    ac.create_account(AccountIn(name="Job Work", code="5310", account_type="Expense"),
                      client_id=CLIENT, current_user=USER)
    assert db.payload["client_id"] == CLIENT


def test_a_code_is_required_because_the_chart_is_keyed_by_it(db):
    from models.accounting import AccountIn
    with pytest.raises(HTTPException) as e:
        ac.create_account(AccountIn(name="No code", account_type="Asset"),
                          client_id=None, current_user=USER)
    assert e.value.status_code == 422
    assert "account code is required" in e.value.detail


def test_updating_an_account_maps_to_the_real_column_names(db):
    from models.accounting import AccountUpdateIn
    out = ac.update_account("a1", AccountUpdateIn(name="Renamed", code="1451"), current_user=USER)
    assert out["success"]
    assert db.payload == {"account_name": "Renamed", "account_code": "1451"}


def test_a_field_with_no_column_is_refused_rather_than_dropped(db):
    """AccountUpdateIn accepts `description` and chart_of_accounts has no such
    column. Accepting it and silently discarding it is the same lie this
    endpoint is being fixed for."""
    from models.accounting import AccountUpdateIn
    with pytest.raises(HTTPException) as e:
        ac.update_account("a1", AccountUpdateIn(description="notes"), current_user=USER)
    assert e.value.status_code == 422
    assert "name, code and is_active" in e.value.detail


def test_an_account_of_another_firm_is_not_found(monkeypatch):
    """Firm-scoped on the read AND the write: the service-role key bypasses
    RLS, so this filter is the isolation."""
    empty = DB(rows=[])
    monkeypatch.setattr(ac, "_prod_db", lambda: empty)
    with pytest.raises(HTTPException) as e:
        ac.update_account("someone-elses", __import__(
            "models.accounting", fromlist=["AccountUpdateIn"]).AccountUpdateIn(name="X"),
            current_user=USER)
    assert e.value.status_code == 404
    assert empty.filters["firm_id"] == "f1"


def test_nothing_to_change_is_refused(db):
    from models.accounting import AccountUpdateIn
    with pytest.raises(HTTPException) as e:
        ac.update_account("a1", AccountUpdateIn(), current_user=USER)
    assert e.value.status_code == 422
