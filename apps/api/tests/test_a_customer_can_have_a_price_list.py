"""Price lists and a default list per customer (accounting-20).

THE VERIFY LINE, AS A TEST: a customer on the 'Dealer' list gets the dealer rate
pre-filled for a catalogue item, and editing the rate on the line still works and
is what posts.

WHAT ELSE IS HELD HERE

  * A price list is a PRE-FILL SOURCE and nothing else. The sales-invoice create
    path takes the rate from the request, so the invoice keeps whatever rate it
    was given — and no module outside the price-list files so much as mentions a
    price list, which is the rule that keeps it out of tax and posting.
  * The answer says where the rate came from, in three states that are not
    interchangeable: the customer's list, the catalogue, or neither (a rate of
    None, never 0). When the catalogue stands in for a list the CA might expect,
    the note says WHY (no list, an archived list, no price for this item).
  * A rate is whole paise and strictly positive; an item with no price on a list
    has NO ROW and falls back, it is not priced at 0.
  * A list belongs to one client; its catalogue items and its customers must too,
    and another client's anything is "not found", never "exists elsewhere".
  * `customers.price_list_id` has one writer.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from fastapi import HTTPException

from domain.sales import price_list as D

API = Path(__file__).resolve().parents[1]
WEB = API.parent / "web"


# ═════════════════════════════════════════════════════════════════════════════
# THE RULE (pure)
# ═════════════════════════════════════════════════════════════════════════════

def _resolve(**kw):
    base = dict(list_id="L1", list_name="Dealer", list_active=True,
                list_rate_paise=80_000, catalogue_rate_paise=100_000)
    return D.resolve(**{**base, **kw})


def test_the_customers_list_rate_wins_over_the_catalogue_rate():
    r = _resolve()
    assert (r["rate_paise"], r["source"]) == (80_000, D.SOURCE_PRICE_LIST)
    assert r["price_list_id"] == "L1" and r["price_list_name"] == "Dealer"
    assert "Dealer" in r["note"] and "Edit the rate on the line" in r["note"]


def test_no_list_is_the_catalogue_rate_with_nothing_to_explain():
    r = _resolve(list_id=None, list_name=None, list_rate_paise=None)
    assert (r["rate_paise"], r["source"], r["note"]) == (100_000, D.SOURCE_CATALOGUE, None)


def test_a_list_with_no_price_for_the_item_falls_back_and_names_the_list():
    r = _resolve(list_rate_paise=None)
    assert (r["rate_paise"], r["source"]) == (100_000, D.SOURCE_CATALOGUE)
    assert "Dealer" in r["note"] and "no price for this item" in r["note"]
    assert r["price_list_id"] == "L1", "the CA is told WHICH list had nothing"


def test_an_archived_list_falls_back_and_says_it_is_archived():
    r = _resolve(list_active=False)
    assert (r["rate_paise"], r["source"]) == (100_000, D.SOURCE_CATALOGUE)
    assert "archived" in r["note"]
    assert r["rate_paise"] != 80_000, "an archived list's rate is never used"


@pytest.mark.parametrize("catalogue", [0, None, -5, True])
def test_no_rate_anywhere_is_none_and_never_zero(catalogue):
    r = _resolve(list_id=None, list_name=None, list_rate_paise=None, catalogue_rate_paise=catalogue)
    assert r["rate_paise"] is None and r["source"] == D.SOURCE_NONE
    assert "No rate is recorded" in r["note"]


def test_the_three_explanations_are_three_different_sentences():
    notes = {
        _resolve(list_active=False)["note"],
        _resolve(list_rate_paise=None)["note"],
        _resolve(list_id=None, list_name=None, list_rate_paise=None,
                 catalogue_rate_paise=0)["note"],
    }
    assert len(notes) == 3


def test_a_list_rate_of_zero_is_not_a_price():
    """The catalogue's own '0 = no default price' is the precedent, so a list row
    that somehow held 0 reads as 'no price' and the catalogue stands in."""
    r = _resolve(list_rate_paise=0)
    assert r["source"] == D.SOURCE_CATALOGUE and r["rate_paise"] == 100_000


@pytest.mark.parametrize("rate,ok", [(1, True), (100_000, True), (0, False), (-1, False),
                                     (True, False), (1.5, False), ("100", False), (None, False)])
def test_a_rate_is_whole_paise_and_strictly_positive(rate, ok):
    assert (D.rate_problem(rate) is None) is ok


@pytest.mark.parametrize("name,ok", [("Dealer", True), ("  Retail  Gold ", True), ("", False),
                                     ("   ", False), (None, False), ("x" * 81, False),
                                     ("x" * 80, True)])
def test_a_name_is_present_and_bounded(name, ok):
    assert (D.name_problem(name) is None) is ok


def test_spacing_is_collapsed_so_two_spellings_are_one_name():
    assert D.normalise_name("  Dealer   A ") == "Dealer A"


def test_nothing_is_computed_a_rate_is_a_stated_number():
    """No discount, no mark-up: the module has no arithmetic on a rate."""
    tree = ast.parse((API / "domain" / "sales" / "price_list.py").read_text())
    ops = [n for n in ast.walk(tree)
           if isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Mult, ast.Div, ast.Add, ast.Sub, ast.FloorDiv))
           and not (isinstance(n.left, ast.Constant) and isinstance(n.left.value, str))]
    # The only `+` in the module joins two sentences; there is no numeric one.
    assert all(isinstance(n.op, ast.Add) for n in ops), [ast.unparse(n) for n in ops]


# ═════════════════════════════════════════════════════════════════════════════
# THE SERVICE, against the e2e double and the REAL sales engine
# ═════════════════════════════════════════════════════════════════════════════

import routers.sales_invoices as si                          # noqa: E402
from models.invoices import InvoiceLineIn, SalesInvoiceIn    # noqa: E402
from services import price_list_service as svc               # noqa: E402
from tests.e2e_harness import (                              # noqa: E402
    FakeDB, account_balance, coa_id, seed_standard_coa, trial_balance, wire_e2e)

FIRM, CLI, OTHER = "FIRM-A", "CLI", "CLI-2"
CALLER = {"firm_id": FIRM, "id": "u-pl-1", "auth_user_id": "auth-1",
          "email": "ca@f.test", "role": "Partner"}


def _book(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [si])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("clients", {"id": CLI, "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5"})
    db.seed("customers", {"id": "CUST", "firm_id": FIRM, "client_id": CLI, "name": "Dealer Co",
                          "state_code": "27", "gstin": "27XYZAB5678C1Z2", "is_active": True})
    db.seed("customers", {"id": "CUST-2", "firm_id": FIRM, "client_id": CLI, "name": "Walk-in",
                          "state_code": "27", "is_active": True})
    seed_standard_coa(db, FIRM, CLI)
    db.seed("service_catalogue", {"id": "ITEM", "firm_id": FIRM, "client_id": CLI, "name": "Widget",
                                  "kind": "service", "hsn_sac": "9982", "default_rate_paise": 100_000,
                                  "unit": "NOS", "is_active": True})
    db.seed("service_catalogue", {"id": "ITEM-2", "firm_id": FIRM, "client_id": CLI, "name": "Gadget",
                                  "kind": "service", "default_rate_paise": 0, "is_active": True})
    return db


def _dealer(db, rate=80_000):
    pl = svc.create_list(db, FIRM, CLI, "Dealer", "Trade customers", CALLER)
    svc.set_item(db, FIRM, CLI, pl["id"], "ITEM", rate, CALLER)
    svc.assign(db, FIRM, CLI, "CUST", pl["id"], CALLER)
    return pl


def test_a_customer_on_the_dealer_list_is_offered_the_dealer_rate(monkeypatch):
    """THE VERIFY LINE'S FIRST HALF."""
    db = _book(monkeypatch)
    _dealer(db)
    got = svc.resolve_rate(db, FIRM, CLI, "CUST", "ITEM")
    assert (got["rate_paise"], got["source"], got["price_list_name"]) == (
        80_000, D.SOURCE_PRICE_LIST, "Dealer")
    # A customer on no list is offered the catalogue rate, exactly as before.
    plain = svc.resolve_rate(db, FIRM, CLI, "CUST-2", "ITEM")
    assert (plain["rate_paise"], plain["source"]) == (100_000, D.SOURCE_CATALOGUE)


def _create(rate_paise, customer="CUST", n=1):
    return si.create_invoice(SalesInvoiceIn(
        client_id=CLI, customer_id=customer, invoice_date="2026-04-10", due_date="2026-05-10",
        invoice_no=f"PL-{n:03d}",
        lines=[InvoiceLineIn(service_catalogue_id="ITEM", description="Widget", hsn_sac="9982",
                             quantity=1, rate_paise=rate_paise, gst_rate_percent=18.0)]), CALLER)


def test_editing_the_rate_on_the_line_is_what_posts(monkeypatch):
    """THE VERIFY LINE'S SECOND HALF: the customer is on the Dealer list (80,000)
    and the catalogue says 1,00,000, and the CA types 65,000 on the line. The
    invoice, its tax and its journal all carry 65,000."""
    db = _book(monkeypatch)
    _dealer(db)
    assert svc.resolve_rate(db, FIRM, CLI, "CUST", "ITEM")["rate_paise"] == 80_000

    inv = _create(65_000)["data"]

    assert inv["taxable_amount_paise"] == 65_000
    assert inv["cgst_paise"] == inv["sgst_paise"] == 5_850                    # 9% each
    assert inv["total_paise"] == 65_000 + 11_700
    line, = [ln for ln in db.rows("client_sales_invoice_lines") if ln["sales_invoice_id"] == inv["id"]]
    assert line["rate_paise"] == 65_000, "the line keeps the rate it was given"
    assert si.issue_invoice(inv["id"], CALLER)["success"]
    assert account_balance(db, coa_id(db, FIRM, "ar")) == 65_000 + 11_700
    assert account_balance(db, coa_id(db, FIRM, "revenue")) == -65_000


@pytest.mark.parametrize("given", [80_000, 100_000, 123_456])
def test_the_invoice_keeps_whatever_rate_it_was_given_whatever_the_list_says(monkeypatch, given):
    """The list rate, the catalogue rate and a third number all land unchanged:
    the create path does not read a price list."""
    db = _book(monkeypatch)
    _dealer(db, rate=80_000)
    inv = _create(given)["data"]
    assert inv["taxable_amount_paise"] == given


def test_pricing_an_item_changes_no_invoice_already_raised(monkeypatch):
    db = _book(monkeypatch)
    pl = svc.create_list(db, FIRM, CLI, "Dealer", None, CALLER)
    svc.assign(db, FIRM, CLI, "CUST", pl["id"], CALLER)
    inv = _create(100_000)["data"]
    before = trial_balance(db, FIRM, CLI)
    svc.set_item(db, FIRM, CLI, pl["id"], "ITEM", 50_000, CALLER)
    svc.set_item(db, FIRM, CLI, pl["id"], "ITEM", 60_000, CALLER)
    again = next(r for r in db.rows("client_sales_invoices") if r["id"] == inv["id"])
    assert again["taxable_amount_paise"] == 100_000
    assert trial_balance(db, FIRM, CLI) == before


def test_a_list_with_no_price_for_the_item_falls_back_and_the_service_names_it(monkeypatch):
    db = _book(monkeypatch)
    _dealer(db)
    got = svc.resolve_rate(db, FIRM, CLI, "CUST", "ITEM-2")        # Gadget: no list price, no catalogue
    assert got["source"] == D.SOURCE_NONE and got["rate_paise"] is None
    assert "Dealer" in got["note"]


def test_archiving_a_list_sends_its_customers_back_to_the_catalogue_rate(monkeypatch):
    db = _book(monkeypatch)
    pl = _dealer(db)
    svc.update_list(db, FIRM, CLI, pl["id"], {"is_active": False}, CALLER)
    got = svc.resolve_rate(db, FIRM, CLI, "CUST", "ITEM")
    assert (got["rate_paise"], got["source"]) == (100_000, D.SOURCE_CATALOGUE)
    assert "archived" in got["note"]
    row, = [c for c in svc.customer_assignments(db, FIRM, CLI) if c["customer_id"] == "CUST"]
    assert row["price_list_archived"] is True and row["price_list_name"] == "Dealer"


def test_a_dangling_pointer_is_no_list(monkeypatch):
    db = _book(monkeypatch)
    db.table("customers").update({"price_list_id": "GONE"}).eq("id", "CUST").execute()
    got = svc.resolve_rate(db, FIRM, CLI, "CUST", "ITEM")
    assert (got["rate_paise"], got["source"]) == (100_000, D.SOURCE_CATALOGUE)


# ── the lists ────────────────────────────────────────────────────────────────

def test_a_list_name_is_unique_per_client_whatever_its_case_or_spacing(monkeypatch):
    db = _book(monkeypatch)
    svc.create_list(db, FIRM, CLI, "Dealer", None, CALLER)
    for clash in ("DEALER", "  dealer ", "Dealer"):
        with pytest.raises(HTTPException) as e:
            svc.create_list(db, FIRM, CLI, clash, None, CALLER)
        assert e.value.status_code == 409 and "already has a price list" in e.value.detail
    # Another client may use the name.
    db.seed("clients", {"id": OTHER, "firm_id": FIRM})
    assert svc.create_list(db, FIRM, OTHER, "Dealer", None, CALLER)["client_id"] == OTHER


def test_a_blank_name_is_refused_and_a_name_is_stored_with_its_spacing_collapsed(monkeypatch):
    db = _book(monkeypatch)
    with pytest.raises(HTTPException) as e:
        svc.create_list(db, FIRM, CLI, "   ", None, CALLER)
    assert e.value.status_code == 422
    assert svc.create_list(db, FIRM, CLI, "  Retail   Gold ", None, CALLER)["name"] == "Retail Gold"


def test_renaming_a_list_to_another_lists_name_is_refused(monkeypatch):
    db = _book(monkeypatch)
    a = svc.create_list(db, FIRM, CLI, "Dealer", None, CALLER)
    svc.create_list(db, FIRM, CLI, "Retail", None, CALLER)
    with pytest.raises(HTTPException) as e:
        svc.update_list(db, FIRM, CLI, a["id"], {"name": "retail"}, CALLER)
    assert e.value.status_code == 409
    assert svc.update_list(db, FIRM, CLI, a["id"], {"name": "Dealer"}, CALLER)["name"] == "Dealer", \
        "keeping its own name is not a clash"


def test_archived_lists_are_listed_only_when_asked_for(monkeypatch):
    db = _book(monkeypatch)
    keep = svc.create_list(db, FIRM, CLI, "Dealer", None, CALLER)
    gone = svc.create_list(db, FIRM, CLI, "Old", None, CALLER)
    svc.update_list(db, FIRM, CLI, gone["id"], {"is_active": False}, CALLER)
    assert [r["name"] for r in svc.list_lists(db, FIRM, CLI)] == ["Dealer"]
    assert [r["name"] for r in svc.list_lists(db, FIRM, CLI, include_archived=True)] == ["Dealer", "Old"]
    assert keep["id"]


# ── the rates ────────────────────────────────────────────────────────────────

def test_an_item_has_one_rate_per_list_and_a_second_set_changes_it(monkeypatch):
    db = _book(monkeypatch)
    pl = svc.create_list(db, FIRM, CLI, "Dealer", None, CALLER)
    svc.set_item(db, FIRM, CLI, pl["id"], "ITEM", 80_000, CALLER)
    svc.set_item(db, FIRM, CLI, pl["id"], "ITEM", 75_000, CALLER)
    rows = db.rows("price_list_items")
    assert len(rows) == 1 and rows[0]["rate_paise"] == 75_000
    shown = svc.list_items(db, FIRM, CLI, pl["id"])["items"]
    assert shown == [{
        "id": rows[0]["id"], "service_catalogue_id": "ITEM", "name": "Widget", "hsn_sac": "9982",
        "unit": "NOS", "is_active": True, "rate_paise": 75_000, "catalogue_rate_paise": 100_000}]


@pytest.mark.parametrize("rate", [0, -1, True, 1.5, "100"])
def test_a_rate_that_is_not_positive_whole_paise_is_refused(monkeypatch, rate):
    db = _book(monkeypatch)
    pl = svc.create_list(db, FIRM, CLI, "Dealer", None, CALLER)
    with pytest.raises(HTTPException) as e:
        svc.set_item(db, FIRM, CLI, pl["id"], "ITEM", rate, CALLER)
    assert e.value.status_code == 422 and "remove it" in e.value.detail
    assert db.rows("price_list_items") == []


def test_removing_an_item_sends_it_back_to_the_catalogue_rate(monkeypatch):
    db = _book(monkeypatch)
    pl = _dealer(db)
    svc.remove_item(db, FIRM, CLI, pl["id"], "ITEM", CALLER)
    assert db.rows("price_list_items") == []
    assert svc.resolve_rate(db, FIRM, CLI, "CUST", "ITEM")["source"] == D.SOURCE_CATALOGUE
    with pytest.raises(HTTPException) as e:
        svc.remove_item(db, FIRM, CLI, pl["id"], "ITEM", CALLER)
    assert e.value.status_code == 404


def test_another_clients_item_list_and_customer_are_not_found(monkeypatch):
    db = _book(monkeypatch)
    db.seed("service_catalogue", {"id": "ITEM-X", "firm_id": FIRM, "client_id": OTHER, "name": "X",
                                  "default_rate_paise": 5, "is_active": True})
    db.seed("customers", {"id": "CUST-X", "firm_id": FIRM, "client_id": OTHER, "name": "Elsewhere"})
    foreign = db.seed("price_lists", {"firm_id": FIRM, "client_id": OTHER, "name": "Theirs",
                                      "is_active": True})
    mine = svc.create_list(db, FIRM, CLI, "Dealer", None, CALLER)
    acts = [
        lambda: svc.set_item(db, FIRM, CLI, mine["id"], "ITEM-X", 100, CALLER),
        lambda: svc.set_item(db, FIRM, CLI, foreign["id"], "ITEM", 100, CALLER),
        lambda: svc.list_items(db, FIRM, CLI, foreign["id"]),
        lambda: svc.update_list(db, FIRM, CLI, foreign["id"], {"name": "x"}, CALLER),
        lambda: svc.assign(db, FIRM, CLI, "CUST-X", mine["id"], CALLER),
        lambda: svc.assign(db, FIRM, CLI, "CUST", foreign["id"], CALLER),
        lambda: svc.resolve_rate(db, FIRM, CLI, "CUST-X", "ITEM"),
        lambda: svc.resolve_rate(db, FIRM, CLI, "CUST", "ITEM-X"),
        lambda: svc.set_item(db, "FIRM-B", CLI, mine["id"], "ITEM", 100, CALLER),
    ]
    for act in acts:
        with pytest.raises(HTTPException) as e:
            act()
        assert e.value.status_code == 404, e.value.detail
    assert db.rows("price_list_items") == []
    assert all(c.get("price_list_id") is None for c in db.rows("customers"))


# ── the assignment ───────────────────────────────────────────────────────────

def test_assigning_clears_and_refuses_an_archived_list(monkeypatch):
    db = _book(monkeypatch)
    pl = svc.create_list(db, FIRM, CLI, "Dealer", None, CALLER)
    svc.assign(db, FIRM, CLI, "CUST", pl["id"], CALLER)
    assert next(c for c in db.rows("customers") if c["id"] == "CUST")["price_list_id"] == pl["id"]
    svc.assign(db, FIRM, CLI, "CUST", None, CALLER)
    assert next(c for c in db.rows("customers") if c["id"] == "CUST")["price_list_id"] is None
    svc.update_list(db, FIRM, CLI, pl["id"], {"is_active": False}, CALLER)
    with pytest.raises(HTTPException) as e:
        svc.assign(db, FIRM, CLI, "CUST", pl["id"], CALLER)
    assert e.value.status_code == 409 and "archived" in e.value.detail


def test_the_assignment_screen_lists_every_customer_with_the_list_they_are_on(monkeypatch):
    db = _book(monkeypatch)
    _dealer(db)
    rows = {r["customer_name"]: r for r in svc.customer_assignments(db, FIRM, CLI)}
    assert rows["Dealer Co"]["price_list_name"] == "Dealer"
    assert rows["Walk-in"]["price_list_id"] is None and rows["Walk-in"]["price_list_name"] is None


# ═════════════════════════════════════════════════════════════════════════════
# THE DOOR
# ═════════════════════════════════════════════════════════════════════════════

from fastapi import FastAPI                                  # noqa: E402
from fastapi.testclient import TestClient                    # noqa: E402

import routers.price_lists as door                           # noqa: E402
from core.auth import get_current_user                       # noqa: E402

REVIEWER = {**CALLER, "role": "Reviewer"}


def _http(monkeypatch, user=CALLER, *, db="x"):
    app = FastAPI()
    app.include_router(door.router)
    app.dependency_overrides[get_current_user] = lambda: user
    if db is None:
        monkeypatch.delenv("SUPABASE_URL", raising=False)
    else:
        monkeypatch.setenv("SUPABASE_URL", "test://db")
        monkeypatch.setattr("core.supabase_client.get_service_supabase", lambda: db)
    return TestClient(app, raise_server_exceptions=False)


def test_the_door_runs_the_whole_flow(monkeypatch):
    db = _book(monkeypatch)
    http = _http(monkeypatch, db=db)
    made = http.post("/api/price-lists", json={"client_id": CLI, "name": "Dealer"})
    assert made.status_code == 200, made.text
    lid = made.json()["data"]["id"]
    put = http.put(f"/api/price-lists/{lid}/items/ITEM", json={"client_id": CLI, "rate_paise": 80_000})
    assert put.status_code == 200, put.text
    assert http.put("/api/price-lists/assign", json={
        "client_id": CLI, "customer_id": "CUST", "price_list_id": lid}).status_code == 200
    got = http.get("/api/price-lists/resolve", params={
        "client_id": CLI, "customer_id": "CUST", "service_catalogue_id": "ITEM"}).json()["data"]
    assert (got["rate_paise"], got["source"]) == (80_000, "price_list")
    items = http.get(f"/api/price-lists/{lid}/items", params={"client_id": CLI}).json()["data"]
    assert [i["rate_paise"] for i in items["items"]] == [80_000]
    assert http.delete(f"/api/price-lists/{lid}/items/ITEM", params={"client_id": CLI}).status_code == 200
    assert http.patch(f"/api/price-lists/{lid}", json={"client_id": CLI, "is_active": False}).status_code == 200
    listed = http.get("/api/price-lists", params={"client_id": CLI}).json()["data"]["price_lists"]
    assert listed == [], "archived lists are not listed unless asked for"
    assert http.get("/api/price-lists/customers", params={"client_id": CLI}).status_code == 200


def test_a_zero_rate_is_a_422_with_a_sentence(monkeypatch):
    db = _book(monkeypatch)
    http = _http(monkeypatch, db=db)
    lid = http.post("/api/price-lists", json={"client_id": CLI, "name": "Dealer"}).json()["data"]["id"]
    r = http.put(f"/api/price-lists/{lid}/items/ITEM", json={"client_id": CLI, "rate_paise": 0})
    assert r.status_code == 422 and "positive" in r.text


def test_a_reviewer_may_neither_read_nor_change_a_list(monkeypatch):
    db = _book(monkeypatch)
    http = _http(monkeypatch, REVIEWER, db=db)
    p = {"client_id": CLI}
    assert http.get("/api/price-lists", params=p).status_code == 403
    assert http.get("/api/price-lists/resolve", params={
        **p, "customer_id": "CUST", "service_catalogue_id": "ITEM"}).status_code == 403
    assert http.post("/api/price-lists", json={**p, "name": "x"}).status_code == 403
    assert http.patch("/api/price-lists/x", json=p).status_code == 403
    assert http.put("/api/price-lists/x/items/ITEM", json={**p, "rate_paise": 5}).status_code == 403
    assert http.delete("/api/price-lists/x/items/ITEM", params=p).status_code == 403
    assert http.put("/api/price-lists/assign", json={**p, "customer_id": "CUST"}).status_code == 403


def test_no_database_is_a_503_not_a_silent_nothing(monkeypatch):
    r = _http(monkeypatch, db=None).get("/api/price-lists", params={"client_id": CLI})
    assert r.status_code == 503


# ═════════════════════════════════════════════════════════════════════════════
# THE RULES, READ OFF THE SOURCE
# ═════════════════════════════════════════════════════════════════════════════

_OWN_FILES = {"domain/sales/price_list.py", "services/price_list_service.py",
              "routers/price_lists.py", "main.py"}


def _code_files():
    skip = {"tests", "migrations", "__pycache__", "node_modules", ".venv", "venv"}
    for p in API.rglob("*.py"):
        rel = p.relative_to(API)
        if rel.parts[0] in skip:
            continue
        yield rel.as_posix(), p


def test_nothing_outside_the_price_list_files_so_much_as_mentions_one():
    """THE RULE THAT KEEPS IT OUT OF TAX AND POSTING. The sales-invoice create
    path, the GST engines, the journal kernel and every other writer of a rate
    are untouched, and a test that listed them would go stale the day a seventh
    appeared: so the rule is that the set of files naming a price list is exactly
    the three that own it, plus the line that mounts the router."""
    pattern = re.compile(r"price_list|priceList|price list", re.I)
    mentioning = set()
    for rel, p in _code_files():
        src = re.sub(r'"""[\s\S]*?"""|#[^\n]*', "", p.read_text())
        if pattern.search(src):
            mentioning.add(rel)
    assert mentioning == _OWN_FILES, mentioning ^ _OWN_FILES


def test_the_invoice_create_path_does_not_read_a_price_list():
    for rel in ("routers/sales_invoices.py", "models/invoices.py", "domain/sales/line_tax.py",
                "services/phase2_journal_service.py"):
        src = (API / rel).read_text()
        assert "price_list" not in src.lower(), rel


def test_customers_price_list_id_has_one_writer():
    tree = ast.parse((API / "services" / "price_list_service.py").read_text())
    payloads = []
    for n in ast.walk(tree):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "update"
                and isinstance(n.func.value, ast.Call) and n.func.value.args
                and isinstance(n.func.value.args[0], ast.Constant)
                and n.func.value.args[0].value == "customers"):
            payloads.append(sorted(k.value for k in n.args[0].keys))
    assert payloads == [["price_list_id"]], (
        "exactly one customers update, in `assign`, writing only price_list_id")


def test_the_service_writes_only_its_own_tables_and_the_one_customer_column():
    tree = ast.parse((API / "services" / "price_list_service.py").read_text())
    written = {ast.unparse(n.func.value.args[0]) for n in ast.walk(tree)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr in {"insert", "update", "delete", "upsert"}
               and isinstance(n.func.value, ast.Call) and n.func.value.args}
    assert written == {"'price_lists'", "'price_list_items'", "'customers'"}, written


def test_the_router_is_mounted_behind_the_client_guard():
    src = (API / "main.py").read_text()
    assert re.search(r"include_router\(price_lists_router,\s*dependencies=_CLIENT_GUARD\)", src)


# ═════════════════════════════════════════════════════════════════════════════
# THE BROWSER — held from this side
# ═════════════════════════════════════════════════════════════════════════════

_PANEL = WEB / "components" / "sales" / "PriceListsPanel.tsx"
_EDITOR = WEB / "components" / "invoices" / "InvoiceEditor.tsx"


def _web_code(path: Path) -> str:
    src = path.read_text()
    src = re.sub(r"/\*[\s\S]*?\*/", "", src)
    return re.sub(r"(^|[^:])//.*$", r"\1", src, flags=re.M)


def test_the_panel_reaches_the_api_only_through_the_price_list_namespace_and_computes_nothing():
    src = _web_code(_PANEL)
    calls = set(re.findall(r"\bapi\.(\w+)\.(\w+)\(", src))
    assert calls and all(ns == "priceLists" for ns, _ in calls), calls
    assert not re.search(r"\bfetch\(|\.from\(|supabase|parseFloat", src)
    assert not re.search(r"\*\s*(rate|price|percent|markup|discount)|(rate|price)\w*\s*\*", src, re.I)


def test_the_editor_applies_the_resolved_rate_only_to_an_untouched_prefill():
    """The line stays editable and the invoice keeps what it is given: the
    resolved rate is applied inside a functional update that checks the line is
    still the one picked AND that its rate is still the catalogue pre-fill — so a
    rate the CA has already typed is never overwritten by a slower answer."""
    src = _web_code(_EDITOR)
    assert src.count("api.priceLists.resolve(") == 1
    start = src.index("function onPickProduct")
    end = src.index("function addLine")
    body = src[start:end]
    assert "api.priceLists.resolve(" in body
    assert re.search(r"l\.serviceCatalogueId\s*===\s*item\.id", body)
    assert re.search(r"l\.rate\s*===\s*prefill", body)
    # And the save path never asks: the payload is built from the lines as they are.
    save = src[src.index("async function save("):]
    assert "priceLists" not in save[:save.index("\n  }\n")]


def test_the_panel_is_reachable_from_the_customers_tab():
    page = (WEB / "app" / "clients" / "[id]" / "sales" / "page.tsx").read_text()
    assert "PriceListsPanel" in page and re.search(r"<PriceListsPanel clientId=\{clientId\}", page)
