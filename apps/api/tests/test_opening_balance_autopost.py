"""
Automatic opening-balance posting (replaces the manual "Post to Ledger" banner).

The idempotent regeneration (post_opening_balances) is unchanged — only WHEN it
runs changed: it now fires automatically on the backend whenever a customer/vendor
opening balance is created or edited. Verifies:
  * create customer/vendor with an opening balance auto-posts to the GL
  * create with zero opening balance posts nothing
  * editing the opening balance re-syncs the GL
  * editing an UNRELATED field (email) does NOT regenerate the journal
  * if posting fails, the customer create is rolled back (no partial save)
"""
import routers.customers as cust
import routers.vendors as ven
import services.opening_balance_service as obs
from models.parties import CustomerIn, CustomerUpdateIn, VendorIn
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa, coa_id, account_balance

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "auth_user_id": "u1", "email": "ca@firma.test", "role": "Partner"}


def _seed_coa(db):
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("chart_of_accounts", {"firm_id": FIRM, "client_id": "CLI",
                                  "account_name": "Opening Balance Equity", "is_active": True})


def _setup(monkeypatch, mods):
    db = FakeDB()
    wire_e2e(monkeypatch, db, mods)
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "financial_year_start": "2025-04-01"})
    _seed_coa(db)
    return db


def _create_customer(**over):
    kw = dict(client_id="CLI", name="Acme")
    kw.update(over)
    return cust.create_customer(CustomerIn(**kw), CALLER)


# ── customers ────────────────────────────────────────────────────────────────

def test_create_customer_with_opening_balance_autoposts(monkeypatch):
    db = _setup(monkeypatch, [cust, obs])
    res = _create_customer(opening_balance_paise=500_000)
    assert res["success"] is True
    assert account_balance(db, coa_id(db, FIRM, "ar")) == 500_000          # in the GL now
    assert obs.opening_balance_status(FIRM, "CLI")["needs_posting"] is False  # reconciled


def test_create_customer_without_opening_balance_posts_nothing(monkeypatch):
    db = _setup(monkeypatch, [cust, obs])
    res = _create_customer(opening_balance_paise=0)
    assert res["success"] is True
    assert not any(e.get("entry_type") == obs.OPENING_ENTRY_TYPE for e in db.rows("journal_entries"))


def test_edit_opening_balance_resyncs_gl(monkeypatch):
    db = _setup(monkeypatch, [cust, obs])
    cid = _create_customer(opening_balance_paise=500_000)["data"]["id"]
    res = cust.update_customer(cid, CustomerUpdateIn(opening_balance_paise=800_000), CALLER)
    assert res["success"] is True
    assert account_balance(db, coa_id(db, FIRM, "ar")) == 800_000


def test_edit_unrelated_field_does_not_regenerate(monkeypatch):
    db = _setup(monkeypatch, [cust, obs])
    cid = _create_customer(opening_balance_paise=500_000)["data"]["id"]
    jid_before = next(e["id"] for e in db.rows("journal_entries") if e.get("entry_type") == obs.OPENING_ENTRY_TYPE)

    cust.update_customer(cid, CustomerUpdateIn(email="new@firma.test"), CALLER)

    opening = [e for e in db.rows("journal_entries") if e.get("entry_type") == obs.OPENING_ENTRY_TYPE]
    assert len(opening) == 1 and opening[0]["id"] == jid_before   # untouched → not regenerated
    assert account_balance(db, coa_id(db, FIRM, "ar")) == 500_000


def test_create_rolls_back_when_autopost_fails(monkeypatch):
    db = _setup(monkeypatch, [cust, obs])
    # Remove the contra account so posting raises (missing Opening Balance Equity).
    db._tables["chart_of_accounts"] = [
        a for a in db.rows("chart_of_accounts") if a.get("account_name") != "Opening Balance Equity"
    ]
    res = _create_customer(opening_balance_paise=500_000)
    assert res["success"] is False
    assert "Unable to save customer" in (res["error"] or "")
    assert not any(c.get("name") == "Acme" for c in db.rows("customers"))   # rolled back
    assert not any(e.get("entry_type") == obs.OPENING_ENTRY_TYPE for e in db.rows("journal_entries"))


# ── vendors ──────────────────────────────────────────────────────────────────

def test_create_vendor_with_opening_balance_autoposts(monkeypatch):
    db = _setup(monkeypatch, [ven, obs])
    res = ven.create_vendor(VendorIn(client_id="CLI", name="Supplier Co",
                                     opening_balance_paise=200_000), CALLER)
    assert res["success"] is True
    assert account_balance(db, coa_id(db, FIRM, "ap")) == -200_000   # AP credit balance
