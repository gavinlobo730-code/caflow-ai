"""A supplier's earlier bills propose the next bill's coding (ai-23).

THE CLAIM
    After three bills from one supplier coded to Rent, the fourth is shown Rent
    with the note "Coded this way 3 of 3 times" — per HSN/SAC and per supplier,
    for the expense account, the §17(5) treatment and (as a notice) the TDS
    section; **never applied without a click, and never learned across a firm or
    a client**.

WHAT THIS FILE HOLDS, AND WHY A FETCHING SERVICE GETS A FETCHING TEST
    `domain/purchases/bill_history` is pure and tested as such. The service is
    the half that can be wrong in ways a unit test cannot see — a missing
    `firm_id`, a status filter that lets a draft teach, a read that stops at the
    first thousand lines — so it runs here against `tests.e2e_harness.FakeDB`
    with rows from two firms and two clients in it. The tenant checks are asserted
    by what the answer CONTAINS, not by reading the source: a source scan cannot
    tell a filter that is there from one that works.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from domain.banking import history as bank_history
from domain.purchases import bill_history as bh
from services import purchase_history_service as svc
from tests.e2e_harness import FakeDB

API = Path(__file__).resolve().parent.parent
FIRM = "11111111-1111-4111-8111-111111111111"
OTHER_FIRM = "22222222-2222-4222-8222-222222222222"
CLIENT = "33333333-3333-4333-8333-333333333333"
OTHER_CLIENT = "44444444-4444-4444-8444-444444444444"


# ── the domain rule ──────────────────────────────────────────────────────────

def _line(account, *, hsn="9972", date="2026-05-01", itc=True, reason=None):
    return {"hsn_sac": hsn, "expense_account_id": account, "itc_eligible": itc,
            "blocked_credit_reason": reason, "bill_date": date}


RENT = {"acc-rent": "5100 · Rent"}


def test_three_bills_coded_to_rent_propose_rent_with_the_evidence():
    """The item's own verification, word for word."""
    lines = [_line("acc-rent", date=f"2026-0{m}-01") for m in (1, 2, 3)]
    out = bh.line_suggestions(lines, RENT, ["9972"])
    s = out["by_hsn"]["9972"]["expense_account"]
    assert s["value"] == "acc-rent" and s["label"] == "5100 · Rent"
    assert (s["times_seen"], s["total_seen"]) == (3, 3)
    assert "Coded this way 3 of 3 times" in s["sentence"]
    assert s["share_bps"] == 10000 and s["last_seen"] == "2026-03-01"
    assert s["alternatives"] == []


def test_one_earlier_bill_says_once_and_is_not_dressed_up_as_a_pattern():
    s = bh.line_suggestions([_line("acc-rent")], RENT, ["9972"])["by_hsn"]["9972"]["expense_account"]
    assert s["sentence"].startswith("Coded this way once before")
    assert (s["times_seen"], s["total_seen"]) == (1, 1)


def test_the_losing_alternatives_travel_with_the_winner():
    lines = [_line("acc-rent")] * 8 + [_line("acc-repairs", date="2026-06-01")]
    usable = {"acc-rent": "5100 · Rent", "acc-repairs": "5200 · Repairs"}
    s = bh.line_suggestions(lines, usable, ["9972"])["by_hsn"]["9972"]["expense_account"]
    assert (s["times_seen"], s["total_seen"], s["share_bps"]) == (8, 9, 8888)
    assert [(a["label"], a["times"]) for a in s["alternatives"]] == [("5200 · Repairs", 1)]


def test_a_tie_goes_to_the_more_recent_decision_and_the_loser_is_still_shown():
    lines = ([_line("acc-a", date="2026-01-01")] * 4) + ([_line("acc-b", date="2026-04-01")] * 4)
    usable = {"acc-a": "A", "acc-b": "B"}
    s = bh.line_suggestions(lines, usable, ["9972"])["by_hsn"]["9972"]["expense_account"]
    assert s["value"] == "acc-b"
    assert [a["value"] for a in s["alternatives"]] == ["acc-a"]


def test_the_order_is_total_so_the_same_history_reads_the_same_every_time():
    """Equal count, equal date: the value decides, so a request cannot flip."""
    lines = [_line("acc-a"), _line("acc-b")]
    usable = {"acc-a": "A", "acc-b": "B"}
    answers = {bh.line_suggestions(list(reversed(lines)) if i % 2 else lines, usable,
                                   ["9972"])["by_hsn"]["9972"]["expense_account"]["value"]
               for i in range(6)}
    assert len(answers) == 1


def test_the_tie_rule_is_the_bank_histories_and_a_test_holds_the_two_together():
    """Same history, one through `domain/banking/history.summarise` and one
    through this module: the same winner, the same counts. Two implementations of
    "most used, then most recent" are how the two would drift apart."""
    obs = [("a", "2026-01-01"), ("b", "2026-02-01"), ("a", "2026-03-01"),
           ("b", "2026-04-01"), ("c", "2026-05-01")]
    bank = bank_history.summarise(
        [{"account_id": v, "posted_at": d} for v, d in obs], ("payee_id", "p"))
    mine = bh._ranked(obs)
    assert bank.account_id == mine[0].value
    assert (bank.times_seen, bank.total_seen) == (mine[0].times, sum(o.times for o in mine))
    assert [(o.account_id, o.times) for o in bank.alternatives] == \
        [(o.value, o.times) for o in mine[1:]]


def test_the_specific_hsn_wins_and_the_supplier_stands_in_only_where_the_hsn_has_no_history():
    lines = ([_line("acc-rent", hsn="9972")] * 3) + ([_line("acc-fuel", hsn="2710")] * 2)
    usable = {"acc-rent": "Rent", "acc-fuel": "Fuel"}
    out = bh.line_suggestions(lines, usable, ["9972", "2710", "9999", ""])
    assert out["by_hsn"]["9972"]["expense_account"]["value"] == "acc-rent"
    assert out["by_hsn"]["9972"]["expense_account"]["basis"] == "hsn"
    assert out["by_hsn"]["2710"]["expense_account"]["value"] == "acc-fuel"
    # An HSN this supplier was never billed under: the supplier-wide winner, labelled as such.
    unseen = out["by_hsn"]["9999"]["expense_account"]
    assert unseen["value"] == "acc-rent" and unseen["basis"] == "supplier"
    assert "across this supplier's earlier bills" in unseen["sentence"]
    assert "" not in out["by_hsn"], "a blank HSN is the supplier-level answer, never a key"
    assert out["vendor"]["expense_account"]["value"] == "acc-rent"


def test_a_winner_the_client_can_no_longer_use_is_not_suggested_and_is_not_replaced_by_the_runner_up():
    """Five of six lines went to an account that has since been deactivated.
    Dropping those rows and tallying the rest would say "Repairs, 1 of 1" about a
    supplier whose lines were nearly all coded elsewhere."""
    lines = ([_line("acc-gone")] * 5) + [_line("acc-repairs")]
    out = bh.line_suggestions(lines, {"acc-repairs": "Repairs"}, ["9972"])
    assert out["vendor"]["expense_account"] is None
    assert out["by_hsn"]["9972"]["expense_account"] is None
    assert any("no longer an active account" in g for g in out["gaps"])


def test_an_hsn_with_an_unusable_winner_does_not_borrow_the_suppliers_answer():
    lines = ([_line("acc-gone", hsn="9972")] * 3) + ([_line("acc-rent", hsn="2710")] * 5)
    out = bh.line_suggestions(lines, {"acc-rent": "Rent"}, ["9972"])
    assert out["vendor"]["expense_account"]["value"] == "acc-rent"
    assert out["by_hsn"]["9972"]["expense_account"] is None, \
        "a scope with evidence of its own is not silently replaced by a broader one"


def test_no_lines_means_no_suggestion_and_no_invented_one():
    out = bh.build([], [], {}, ["9972"], None)
    assert out["vendor"] == {"expense_account": None, "itc": None}
    assert out["by_hsn"]["9972"] == {"expense_account": None, "itc": None}
    assert out["tds"] is None and out["bills_considered"] == 0


# ── ITC: only a BLOCKED winner is information ────────────────────────────────

def test_an_eligible_winner_is_not_surfaced_because_it_restates_the_default():
    lines = [_line("acc-rent", itc=True)] * 5
    assert bh.line_suggestions(lines, RENT, ["9972"])["by_hsn"]["9972"]["itc"] is None


def test_a_null_itc_flag_reads_as_eligible_like_migration_240():
    lines = [_line("acc-rent", itc=None)] * 4
    assert bh.line_suggestions(lines, RENT, ["9972"])["by_hsn"]["9972"]["itc"] is None


def test_a_blocked_winner_carries_the_clause_and_the_evidence():
    lines = ([_line("acc-car", itc=False, reason="motor_vehicles", date="2026-03-01")] * 3
             + [_line("acc-car", itc=True, date="2026-01-01")])
    s = bh.line_suggestions(lines, {"acc-car": "Car"}, ["9972"])["by_hsn"]["9972"]["itc"]
    assert s["value"] is False and s["reason"] == "motor_vehicles"
    assert (s["times_seen"], s["total_seen"]) == (3, 4)
    assert [(a["value"], a["times"]) for a in s["alternatives"]] == [(True, 1)]


def test_the_clause_offered_is_the_most_recent_one_recorded():
    lines = [_line("acc-car", itc=False, reason="food", date="2026-01-01"),
             _line("acc-car", itc=False, reason="motor_vehicles", date="2026-05-01"),
             _line("acc-car", itc=False, reason=None, date="2026-06-01")]
    s = bh.line_suggestions(lines, {"acc-car": "Car"}, ["9972"])["by_hsn"]["9972"]["itc"]
    assert s["reason"] == "motor_vehicles", "a newer line with no clause is not a clause"


def test_an_hsn_with_eligible_history_does_not_inherit_the_suppliers_blocked_treatment():
    lines = ([_line("acc-car", hsn="8703", itc=False, reason="motor_vehicles")] * 4
             + [_line("acc-rent", hsn="9972", itc=True)] * 2)
    out = bh.line_suggestions(lines, {"acc-car": "Car", "acc-rent": "Rent"}, ["9972", "8703", "0000"])
    assert out["by_hsn"]["9972"]["itc"] is None
    assert out["by_hsn"]["8703"]["itc"]["value"] is False
    # Never billed under this HSN: the supplier-wide position (4 blocked of 6) stands in.
    assert out["by_hsn"]["0000"]["itc"]["basis"] == "supplier"


# ── the TDS notice ───────────────────────────────────────────────────────────

def _bill(section, date="2026-04-01"):
    return {"tds_section": section, "bill_date": date}


def test_a_section_the_supplier_record_has_since_lost_is_a_notice_that_says_what_the_bill_will_do():
    n = bh.tds_notice([_bill("194J")] * 3, None)
    assert n["section"] == "194J" and (n["times_seen"], n["total_seen"]) == (3, 3)
    assert n["supplier_record_section"] is None
    assert "3 of 3 times" in n["sentence"]
    assert "This bill follows the supplier record" in n["sentence"]


def test_an_agreeing_section_says_nothing():
    assert bh.tds_notice([_bill("194J")] * 3, "194J") is None
    assert bh.tds_notice([_bill("194j")] * 3, " 194J ") is None, "compared as the engine compares"


def test_a_bill_with_no_section_is_not_a_vote_for_no_section():
    n = bh.tds_notice([_bill("194J"), _bill(None), _bill(""), _bill(None)], None)
    assert (n["times_seen"], n["total_seen"]) == (1, 1)
    assert bh.tds_notice([_bill(None), _bill("")], "194J") is None


def test_a_different_section_on_the_record_is_named_beside_the_one_used_before():
    n = bh.tds_notice([_bill("194C")] * 2, "194J")
    assert n["supplier_record_section"] == "194J" and "the supplier record says 194J" in n["sentence"]


# ── the service, against a database holding two firms and two clients ───────

def _seed_supplier(db, *, firm=FIRM, client=CLIENT, name="Landlord LLP", tds_section=None):
    return db.seed("vendors", {"firm_id": firm, "client_id": client, "name": name,
                               "gstin": "27AAAAA0000A1Z5", "tds_section": tds_section})


def _seed_account(db, name="Rent", *, firm=FIRM, client=CLIENT, active=True, code="5100"):
    return db.seed("chart_of_accounts", {"firm_id": firm, "client_id": client,
                                         "account_name": name, "account_code": code,
                                         "is_active": active})


def _seed_bill(db, vendor, *, firm=FIRM, client=CLIENT, status="received",
               date="2026-04-01", tds_section=None, deleted=False, opening=False, lines=()):
    bill = db.seed("purchase_bills", {
        "firm_id": firm, "client_id": client, "vendor_id": vendor["id"], "status": status,
        "bill_date": date, "tds_section": tds_section, "is_opening": opening,
        "deleted_at": "2026-05-01T00:00:00Z" if deleted else None})
    for ln in lines:
        db.seed("purchase_bill_lines", {"bill_id": bill["id"], "hsn_sac": "9972",
                                        "itc_eligible": True, **ln})
    return bill


@pytest.fixture()
def world():
    db = FakeDB()
    supplier = _seed_supplier(db)
    rent = _seed_account(db)
    for month in (1, 2, 3):
        _seed_bill(db, supplier, date=f"2026-0{month}-01",
                   lines=[{"expense_account_id": rent["id"]}])
    return db, supplier, rent


def _ask(db, supplier, hsns=("9972",), *, firm=FIRM, client=CLIENT):
    return svc.vendor_history(db, firm, client, supplier["id"], hsns)


def test_the_service_proposes_rent_after_three_rent_bills(world):
    db, supplier, rent = world
    out = _ask(db, supplier)
    s = out["by_hsn"]["9972"]["expense_account"]
    assert s["value"] == rent["id"] and s["label"] == "5100 · Rent"
    assert "Coded this way 3 of 3 times" in s["sentence"]
    assert out["bills_considered"] == 3 and out["checked"] is True


def test_the_service_writes_nothing(world, monkeypatch):
    """A proposal. Every write verb on the database double raises, so a service
    that wrote anything — a cache, a counter, an audit row — fails here rather
    than being noticed in production. (Comparing table contents before and after
    would not do: the double derives generated columns on first read.)"""
    from tests import e2e_harness
    db, supplier, _ = world

    def forbidden(verb):
        def _raise(self, *a, **k):
            raise AssertionError(f"the history lookup called {verb}() on {self.table}")
        return _raise

    for verb in ("insert", "update", "upsert", "delete"):
        monkeypatch.setattr(e2e_harness._Query, verb, forbidden(verb))
    out = _ask(db, supplier)
    assert out["bills_considered"] == 3


def test_another_firms_bills_for_the_same_supplier_id_do_not_teach(world):
    db, supplier, rent = world
    other_acc = _seed_account(db, "Fuel", firm=OTHER_FIRM)
    for m in range(1, 8):
        _seed_bill(db, supplier, firm=OTHER_FIRM, date=f"2026-0{m}-15",
                   lines=[{"expense_account_id": other_acc["id"]}])
    s = _ask(db, supplier)["by_hsn"]["9972"]["expense_account"]
    assert s["value"] == rent["id"] and (s["times_seen"], s["total_seen"]) == (3, 3)


def test_another_clients_supplier_with_the_same_gstin_and_name_does_not_teach(world):
    """Same legal entity, a different CLIENT's books: a different `vendors` row, a
    different chart, a different decision."""
    db, supplier, rent = world
    twin = _seed_supplier(db, client=OTHER_CLIENT)           # same name, same GSTIN
    fuel = _seed_account(db, "Fuel", client=OTHER_CLIENT)
    for m in range(1, 8):
        _seed_bill(db, twin, client=OTHER_CLIENT, date=f"2026-0{m}-20",
                   lines=[{"expense_account_id": fuel["id"]}])
    assert twin["gstin"] == supplier["gstin"] and twin["name"] == supplier["name"]
    s = _ask(db, supplier)["by_hsn"]["9972"]["expense_account"]
    assert s["value"] == rent["id"] and s["total_seen"] == 3


def test_a_bill_under_this_supplier_id_but_another_clients_id_is_not_counted(world):
    """A row whose `client_id` disagrees with the supplier's: the bills query
    carries client_id as well as vendor_id, so it is excluded either way."""
    db, supplier, rent = world
    _seed_bill(db, supplier, client=OTHER_CLIENT,
               lines=[{"expense_account_id": rent["id"]}] * 20)
    assert _ask(db, supplier)["bills_considered"] == 3


def test_a_supplier_that_is_not_this_clients_is_a_404_not_an_empty_answer(world):
    db, supplier, _ = world
    with pytest.raises(HTTPException) as e:
        svc.vendor_history(db, FIRM, OTHER_CLIENT, supplier["id"], ["9972"])
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        svc.vendor_history(db, OTHER_FIRM, CLIENT, supplier["id"], ["9972"])
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        svc.vendor_history(db, FIRM, CLIENT, "no-such-supplier", ["9972"])
    assert e.value.status_code == 404


@pytest.mark.parametrize("kind,kwargs", [
    ("a draft", {"status": "draft"}),
    ("a cancelled bill", {"status": "cancelled"}),
    ("a deleted bill", {"deleted": True}),
    ("a carried-over opening bill", {"opening": True}),
])
def test_only_a_bill_somebody_committed_to_teaches(world, kind, kwargs):
    db, supplier, rent = world
    fuel = _seed_account(db, "Fuel", code="5300")
    _seed_bill(db, supplier, **kwargs, lines=[{"expense_account_id": fuel["id"]}] * 10)
    out = _ask(db, supplier)
    s = out["by_hsn"]["9972"]["expense_account"]
    assert s["value"] == rent["id"] and s["total_seen"] == 3, kind
    assert out["bills_considered"] == 3, kind


def test_a_carried_over_bills_default_itc_flag_is_not_a_judgement():
    """The opening bill's lines carry itc_eligible=true by the column default; had
    it been counted, a supplier whose real bills were blocked would read as
    eligible."""
    db = FakeDB()
    supplier = _seed_supplier(db)
    car = _seed_account(db, "Car")
    for m in (1, 2):
        _seed_bill(db, supplier, date=f"2026-0{m}-01", lines=[
            {"expense_account_id": car["id"], "itc_eligible": False,
             "blocked_credit_reason": "motor_vehicles"}])
    _seed_bill(db, supplier, opening=True, lines=[
        {"expense_account_id": car["id"], "itc_eligible": True}] * 5)
    itc = _ask(db, supplier)["by_hsn"]["9972"]["itc"]
    assert itc["value"] is False and (itc["times_seen"], itc["total_seen"]) == (2, 2)


def test_a_line_whose_parent_is_not_in_the_scoped_set_is_never_read(world):
    """`purchase_bill_lines` has no firm_id; the tenant check is the parent. A line
    pointing at another firm's bill must not be reachable."""
    db, supplier, rent = world
    foreign = _seed_bill(db, supplier, firm=OTHER_FIRM,
                         lines=[{"expense_account_id": rent["id"]}] * 30)
    assert foreign["id"] not in {b["id"] for b in svc._bills(db, FIRM, CLIENT, supplier["id"])}
    assert _ask(db, supplier)["by_hsn"]["9972"]["expense_account"]["total_seen"] == 3


def test_an_account_of_another_client_or_another_firm_is_never_suggested():
    db = FakeDB()
    supplier = _seed_supplier(db)
    foreign_client = _seed_account(db, "Their rent", client=OTHER_CLIENT)
    foreign_firm = _seed_account(db, "Alien rent", firm=OTHER_FIRM)
    _seed_bill(db, supplier, lines=[{"expense_account_id": foreign_client["id"]}] * 2
                                   + [{"expense_account_id": foreign_firm["id"]}])
    out = _ask(db, supplier)
    assert out["by_hsn"]["9972"]["expense_account"] is None
    assert out["gaps"], "the unusable winner is reported, not silently skipped"


def test_a_firm_level_account_is_usable_on_any_clients_bills():
    """`client_id IS NULL` is a firm-level account (migration 360's line)."""
    db = FakeDB()
    supplier = _seed_supplier(db)
    shared = _seed_account(db, "Firm-wide rent", client=None)
    _seed_bill(db, supplier, lines=[{"expense_account_id": shared["id"]}])
    assert _ask(db, supplier)["by_hsn"]["9972"]["expense_account"]["value"] == shared["id"]


def test_a_deactivated_account_is_not_suggested(world):
    db, supplier, rent = world
    for r in db.rows("chart_of_accounts"):
        r["is_active"] = False
    out = _ask(db, supplier)
    assert out["by_hsn"]["9972"]["expense_account"] is None and out["gaps"]


def test_the_history_is_read_past_the_first_thousand_lines():
    """100 bills x 11 lines = 1,100 lines, more than one PostgREST page. A read
    that stopped at the first page would count 1,000."""
    db = FakeDB()
    supplier = _seed_supplier(db)
    rent = _seed_account(db)
    for i in range(100):
        _seed_bill(db, supplier, date=f"2026-01-{(i % 28) + 1:02d}",
                   lines=[{"expense_account_id": rent["id"]}] * 11)
    s = _ask(db, supplier)["by_hsn"]["9972"]["expense_account"]
    assert (s["times_seen"], s["total_seen"]) == (1100, 1100)


def test_only_the_newest_hundred_bills_are_considered():
    db = FakeDB()
    supplier = _seed_supplier(db)
    old, new = _seed_account(db, "Old"), _seed_account(db, "New", code="5200")
    for i in range(5):
        _seed_bill(db, supplier, date="2020-01-01", lines=[{"expense_account_id": old["id"]}])
    for i in range(bh.HISTORY_BILLS):
        _seed_bill(db, supplier, date="2026-02-01", lines=[{"expense_account_id": new["id"]}])
    out = _ask(db, supplier)
    assert out["bills_considered"] == bh.HISTORY_BILLS
    s = out["by_hsn"]["9972"]["expense_account"]
    assert s["value"] == new["id"] and s["total_seen"] == bh.HISTORY_BILLS


def test_the_tds_notice_reads_the_supplier_record_and_the_bills(world):
    db, supplier, _ = world
    for b in db.rows("purchase_bills"):
        b["tds_section"] = "194I"
    out = _ask(db, supplier)
    assert out["tds"]["section"] == "194I" and out["tds"]["supplier_record_section"] is None
    for v in db.rows("vendors"):
        v["tds_section"] = "194I"
    assert _ask(db, supplier)["tds"] is None


def test_more_hsns_than_a_bill_has_lines_is_refused(world):
    db, supplier, _ = world
    with pytest.raises(HTTPException) as e:
        _ask(db, supplier, hsns=[str(1000 + i) for i in range(bh.MAX_HSNS + 1)])
    assert e.value.status_code == 422


# ── every column the service names is a real one ─────────────────────────────

def _columns_named(path: Path) -> dict[str, set[str]]:
    """table -> every column its query chains name (select, eq, neq, is_, in_, order)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: dict[str, set[str]] = {}

    def chain_table(node):
        while isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "table" and node.args and isinstance(node.args[0], ast.Constant):
                return node.args[0].value
            node = node.func.value
        return None

    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        table = chain_table(node)
        if not table or not node.args or not isinstance(node.args[0], ast.Constant):
            continue
        first = node.args[0].value
        if not isinstance(first, str):
            continue
        if node.func.attr == "select":
            out.setdefault(table, set()).update(c.strip() for c in first.split(","))
        elif node.func.attr in ("eq", "neq", "is_", "in_", "order", "gt"):
            out.setdefault(table, set()).add(first)
    return out


def test_every_column_the_service_names_exists():
    """The class of defect that made whole features dead: a column named in code
    that no migration created, which PostgREST refuses at parse time and a broad
    `except` then hides. Checked against production's own column list; the one
    column newer than that snapshot (`is_opening`, migration 391) is checked
    against its migration."""
    prod = json.loads((API / "tests/fixtures/production_schema_2026-09-03.json").read_text())
    named = _columns_named(API / "services/purchase_history_service.py")
    assert set(named) == {"vendors", "purchase_bills", "purchase_bill_lines", "chart_of_accounts"}
    migration_391 = next((API / "migrations").glob("391_*.sql")).read_text()
    for table, cols in named.items():
        for col in cols:
            if table == "purchase_bills" and col == "is_opening":
                assert re.search(r"purchase_bills[\s\S]*?is_opening", migration_391)
                continue
            assert col in prod[table], f"{table}.{col} is not a production column"


def test_the_line_table_is_read_by_bill_id_and_never_asked_for_a_firm_id():
    """`purchase_bill_lines` has NO firm_id: naming it is PGRST204 and no read at
    all, so the tenant check is the parent bill (PUR-25's own note)."""
    prod = json.loads((API / "tests/fixtures/production_schema_2026-09-03.json").read_text())
    assert "firm_id" not in prod["purchase_bill_lines"] and "bill_id" in prod["purchase_bill_lines"]
    cols = _columns_named(API / "services/purchase_history_service.py")["purchase_bill_lines"]
    assert "firm_id" not in cols and "bill_id" in cols


# ── the route ────────────────────────────────────────────────────────────────

@pytest.fixture()
def api(monkeypatch, world):
    import core.supabase_client as sc
    from core.auth import get_current_user
    from routers import purchase_bills as pb

    db, supplier, rent = world
    monkeypatch.setattr(pb, "_USE_MOCK", False)
    monkeypatch.setattr(sc, "get_supabase", lambda: db)
    seen: list[str] = []
    monkeypatch.setattr(pb, "assert_client_access", lambda user, cid: seen.append(cid))

    app = FastAPI()
    app.include_router(pb.router)
    user = {"id": "u-1", "auth_user_id": "a-1", "firm_id": FIRM,
            "email": "p@f.test", "role": "Partner"}
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app, raise_server_exceptions=False), supplier, rent, seen, user, app


def test_the_route_answers_and_checks_the_clients_access(api):
    client, supplier, rent, seen, *_ = api
    r = client.get("/api/purchase-bills/vendor-history",
                   params={"client_id": CLIENT, "vendor_id": supplier["id"], "hsn": ["9972", "9983"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    assert body["data"]["by_hsn"]["9972"]["expense_account"]["value"] == rent["id"]
    assert set(body["data"]["by_hsn"]) == {"9972", "9983"}
    assert seen == [CLIENT], "the client's access was asked before anything was read"


def test_the_route_is_not_swallowed_by_the_bill_id_route(api):
    """`/{bill_id}` would take "vendor-history" as an id and answer 404/"not
    found"; declaring it first is what makes this a different endpoint."""
    client, supplier, *_ = api
    r = client.get("/api/purchase-bills/vendor-history",
                   params={"client_id": CLIENT, "vendor_id": supplier["id"]})
    assert r.status_code == 200 and "by_hsn" in r.json()["data"]


def test_a_client_the_caller_may_not_see_reads_nothing(api, monkeypatch):
    client, supplier, rent, seen, user, app = api
    from routers import purchase_bills as pb

    def refuse(user, cid):
        raise HTTPException(status_code=404, detail="Not found")

    monkeypatch.setattr(pb, "assert_client_access", refuse)
    called = []
    monkeypatch.setattr(svc, "vendor_history", lambda *a, **k: called.append(a))
    r = client.get("/api/purchase-bills/vendor-history",
                   params={"client_id": OTHER_CLIENT, "vendor_id": supplier["id"]})
    assert r.status_code == 404 and not called


def test_a_role_without_accounting_read_is_refused(api):
    from core.auth import get_current_user
    client, supplier, rent, seen, user, app = api
    app.dependency_overrides[get_current_user] = lambda: {**user, "role": "Client"}
    r = client.get("/api/purchase-bills/vendor-history",
                   params={"client_id": CLIENT, "vendor_id": supplier["id"]})
    assert r.status_code == 403


def test_mock_mode_says_it_did_not_check_rather_than_that_there_is_no_history(monkeypatch, api):
    from routers import purchase_bills as pb
    client, supplier, *_ = api
    monkeypatch.setattr(pb, "_USE_MOCK", True)
    r = client.get("/api/purchase-bills/vendor-history",
                   params={"client_id": CLIENT, "vendor_id": supplier["id"]})
    assert r.json()["data"] == {"checked": False}


def test_the_route_is_a_get_that_writes_nothing_and_calls_no_model():
    """No `ai_limit` is needed because there is no model here, and a test says so
    rather than leaving it to look like an omission."""
    src = (API / "routers/purchase_bills.py").read_text(encoding="utf-8")
    start = src.index('@router.get("/vendor-history")')
    end = src.index('@router.post("/tds-preview")')
    body = src[start:end]
    for banned in ("groq", "gemini", ".insert(", ".update(", ".upsert(", ".delete("):
        assert banned not in body.lower(), banned
    assert "ai_limit" not in body
    for module in ("domain/purchases/bill_history.py", "services/purchase_history_service.py"):
        text = (API / module).read_text(encoding="utf-8")
        assert "httpx" not in text and "groq_text" not in text, module
        for write in (".insert(", ".update(", ".upsert(", ".delete("):
            assert write not in text, (module, write)
