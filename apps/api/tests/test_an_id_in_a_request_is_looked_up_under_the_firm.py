"""
An id that arrives in a request is looked up UNDER THE FIRM, never by itself
(engineering-28: three unscoped reads, and one more of the same kind found in review).

`test_every_query_on_a_firm_table_carries_its_firm_scope.py` reads every query in the
tree. Of the reads fixed here it flags TWO of its own accord (the kanban and the mapping's
account name); the FIRST, the inventory posting paths, it does not: those four lookups
are keyed on ids read off a firm's own document lines, which the reader treats as having
come out of a scoped read (`flow` / `callers`), so with the filter removed the guard stays
green. That one was found by reading the code and THIS FILE IS ITS ONLY REGRESSION
PROTECTION. Each is one `.eq("firm_id", ...)` short of a cross-tenant read or write when
the API runs on the service-role key (which bypasses row-level security; with the per-user
JWT the database already refuses the foreign row), and each is tested here against the
behaviour.

  1. A DOCUMENT LINE NAMES ITS ITEM. `service_catalogue_id` is a field of the invoice,
     bill, credit note or debit note body, and nothing at create time checks it belongs
     to the caller's firm. Posting the document resolved those ids with no firm filter,
     so a line naming another firm's item moved THAT firm's stock, wrote the movement
     under this firm's ledger and priced the cost of goods sold off the other firm's
     average cost. (Four functions: sale, purchase, credit note, debit note.) The line is
     now simply not a goods line here, and the log says how many ids did not resolve.
     The same read in `landed_cost_service.read_for_bill` returned a foreign item's NAME
     to the screen that previews a bill's landed cost; it is scoped too.
  2. A MAPPING NAMES ITS ACCOUNT. `account_id` is a field of the year-end mapping body;
     the display name was read from `accounts` by id alone, so any member who may write a
     year-end mapping (Executive and above) and named another firm's account got its NAME
     written into their own mapping and returned.
  3. A KANBAN FOR ONE FIRM. `get_kanban` with no client asked the repository for the
     grouped tasks with no firm at all, so the board carried every firm's cards. (No
     route calls it today; it was one call from being reachable. The repository method
     now REQUIRES a firm and refuses an empty one.)
"""
from __future__ import annotations

import types
from decimal import Decimal

import pytest

import domain.inventory_service as inv
from tests.test_inventory_service import _FakeDB, _seed_catalogue_item

OWN, THEIRS = "firm-1", "firm-2"


def _foreign_item(db):
    """Another firm's goods item, holding ten units it paid Rs 1,000 each for."""
    _seed_catalogue_item(db, item_id="foreign-1", firm_id=THEIRS, client_id="client-9",
                         kind="good", name="Their Widget")
    inv.record_stock_in(
        db, firm_id=THEIRS, client_id="client-9", service_catalogue_id="foreign-1",
        movement_date="2026-04-01", quantity=Decimal("10"), total_cost_paise=10_000_00,
        movement_type="opening")


def _own_item(db):
    _seed_catalogue_item(db, item_id="own-1", kind="good", name="Our Widget")
    inv.record_stock_in(
        db, firm_id=OWN, client_id="client-1", service_catalogue_id="own-1",
        movement_date="2026-04-01", quantity=Decimal("10"), total_cost_paise=10_000_00,
        movement_type="opening")


def _item_row(db, item_id):
    return next(r for r in db.store["service_catalogue"] if r["id"] == item_id)


# One row per document kind: (store key for its lines, the extra columns a line needs,
# the function that posts it, how to call it, what the ledger records).
def _sale(db, item):
    db.store["client_sales_invoice_lines"] = [
        {"id": "l1", "sales_invoice_id": "inv-1", "description": "x", "quantity": "3",
         "service_catalogue_id": item}]
    inv.apply_sale_to_inventory(
        db, firm_id=OWN, client_id="client-1",
        invoice={"id": "inv-1", "invoice_no": "INV-1", "invoice_date": "2026-04-20",
                 "client_id": "client-1"})


def _purchase(db, item):
    db.store["purchase_bill_lines"] = [
        {"id": "p1", "bill_id": "bill-1", "description": "x", "quantity": "3",
         "taxable_amount_paise": 3_000_00, "expense_account_id": None,
         "service_catalogue_id": item}]
    inv.apply_purchase_to_inventory(
        db, firm_id=OWN, client_id="client-1",
        bill={"id": "bill-1", "bill_no": "BILL-1", "bill_date": "2026-04-05", "client_id": "client-1"})


def _credit_note(db, item):
    db.store["credit_note_lines"] = [
        {"id": "c1", "credit_note_id": "cn-1", "description": "x", "quantity": "3",
         "taxable_amount_paise": 3_000_00, "service_catalogue_id": item}]
    inv.apply_credit_note_to_inventory(
        db, firm_id=OWN, client_id="client-1",
        credit_note={"id": "cn-1", "credit_note_no": "CN-1", "credit_note_date": "2026-04-15",
                     "client_id": "client-1"})


def _debit_note(db, item):
    db.store["debit_note_lines"] = [
        {"id": "d1", "debit_note_id": "dn-1", "description": "x", "quantity": "3",
         "service_catalogue_id": item}]
    inv.apply_debit_note_to_inventory(
        db, firm_id=OWN, client_id="client-1",
        debit_note={"id": "dn-1", "debit_note_no": "DN-1", "debit_note_date": "2026-04-10",
                    "client_id": "client-1"})


DOCUMENTS = [("sale", _sale), ("purchase", _purchase), ("credit note", _credit_note),
             ("debit note", _debit_note)]


@pytest.mark.parametrize("kind, post", DOCUMENTS, ids=[k for k, _ in DOCUMENTS])
def test_a_line_naming_another_firms_item_moves_none_of_its_stock(kind, post):
    db = _FakeDB()
    _foreign_item(db)
    before_ledger = [dict(r) for r in db.store["inventory_stock_ledger"]]
    before_item = dict(_item_row(db, "foreign-1"))

    post(db, "foreign-1")

    assert db.store["inventory_stock_ledger"] == before_ledger, (
        f"a {kind} line naming another firm's item wrote to the stock ledger")
    assert _item_row(db, "foreign-1") == before_item, (
        f"a {kind} line naming another firm's item changed that firm's stock and cost")


@pytest.mark.parametrize("kind, post", DOCUMENTS, ids=[k for k, _ in DOCUMENTS])
def test_a_line_naming_the_firms_own_item_still_moves_stock(kind, post):
    """The control for the test above: the filter keeps a foreign item out and nothing else."""
    db = _FakeDB()
    _own_item(db)
    before = len(db.store["inventory_stock_ledger"])
    post(db, "own-1")
    assert len(db.store["inventory_stock_ledger"]) == before + 1, kind


# ── the mapping's account name ───────────────────────────────────────────────

class _Q:
    def __init__(self, store, name):
        self.store, self.name, self.f, self.patch, self.rows = store, name, [], None, None

    def select(self, *_a, **_k): return self
    def eq(self, k, v): self.f.append((k, v)); return self
    def order(self, *_a, **_k): return self
    def maybe_single(self): self._single = True; return self
    def insert(self, row): self.rows = row; return self
    def update(self, patch): self.patch = patch; return self

    def execute(self):
        table = self.store.setdefault(self.name, [])
        if self.rows is not None:
            row = dict(self.rows)
            table.append(row)
            return types.SimpleNamespace(data=[row])
        hit = [r for r in table if all(r.get(k) == v for k, v in self.f)]
        if self.patch is not None:
            for r in hit:
                r.update(self.patch)
            return types.SimpleNamespace(data=hit)
        if getattr(self, "_single", False):
            return types.SimpleNamespace(data=hit[0] if hit else None)
        return types.SimpleNamespace(data=hit)


class _DB:
    def __init__(self):
        self.store = {"accounts": [
            {"id": "acct-own", "firm_id": OWN, "account_name": "Our Bank"},
            {"id": "acct-theirs", "firm_id": THEIRS, "account_name": "Their Secret Reserve"},
        ]}

    def table(self, name): return _Q(self.store, name)


def _post_mapping(monkeypatch, account_id):
    import routers.year_end_mappings as ye
    import core.supabase_client as sc
    db = _DB()
    monkeypatch.setattr(ye, "_USE_MOCK", False)
    monkeypatch.setattr(sc, "get_supabase", lambda: db)
    monkeypatch.setattr(ye, "log_event", lambda *a, **k: None)
    out = ye.create_or_update_mapping(
        ye.MappingIn(account_id=account_id, schedule_line="cash_and_bank"),
        current_user={"firm_id": OWN, "auth_user_id": "u", "email": "a@b.c"})
    return db, out


def test_a_mapping_names_only_an_account_of_this_firm(monkeypatch):
    db, out = _post_mapping(monkeypatch, "acct-own")
    assert out["data"]["account_name"] == "Our Bank"


def test_a_mapping_naming_another_firms_account_gets_no_name_from_it(monkeypatch):
    db, out = _post_mapping(monkeypatch, "acct-theirs")
    stored = db.store["account_group_mappings"][0]
    assert stored["account_name"] != "Their Secret Reserve", (
        "another firm's account name was copied into this firm's mapping")
    assert stored["firm_id"] == OWN
    assert out["data"]["account_name"] is None, (
        "an account that is not this firm's reads as no account, as an unknown id does")


# ── the kanban ───────────────────────────────────────────────────────────────

def test_a_kanban_for_one_firm_carries_only_that_firms_tasks(monkeypatch):
    import repositories.task_repository as tr
    from domain.task_service import task_domain_service
    if not tr._USE_MOCK:
        pytest.skip("this checks the mock branch, which the suite runs")

    def task(i, firm, status):
        return {"id": i, "firm_id": firm, "client_id": "c1", "title": i, "status": status,
                "priority": "high", "due_date": None}

    monkeypatch.setattr(tr, "MOCK_TASKS", [task("a1", "firm-A", "todo"),
                                           task("a2", "firm-A", "in_progress"),
                                           task("b1", "firm-B", "todo"),
                                           task("b2", "firm-B", "completed")])
    board = task_domain_service.get_kanban(firm_id="firm-A")
    ids = {t["id"] for column in board.values() for t in column}
    assert ids == {"a1", "a2"}, f"the board for firm-A carried {sorted(ids)}"


def test_a_kanban_without_a_firm_is_refused_not_read_for_every_firm():
    import repositories.task_repository as tr
    with pytest.raises(ValueError):
        tr.task_repo.group_by_status("")
    with pytest.raises(TypeError):
        tr.task_repo.group_by_status()  # type: ignore[call-arg]


# ── an id that does not resolve under the firm says so in the log ───────────

def test_a_line_naming_an_item_that_is_not_this_firms_is_noted_in_the_log(caplog):
    import logging
    db = _FakeDB()
    _foreign_item(db)
    with caplog.at_level(logging.WARNING, logger="caflow.inventory"):
        _sale(db, "foreign-1")
    notes = [r.getMessage() for r in caplog.records if r.name == "caflow.inventory"]
    assert any("sale" in n and "1 line item id" in n for n in notes), notes
    assert not any("foreign-1" in n for n in notes), (
        "the id of an item that is not this firm's must not be written down")


def test_a_line_naming_the_firms_own_item_is_not_noted(caplog):
    import logging
    db = _FakeDB()
    _own_item(db)
    with caplog.at_level(logging.WARNING, logger="caflow.inventory"):
        _sale(db, "own-1")
    assert not [r for r in caplog.records if "did not resolve" in r.getMessage()]


# ── the landed-cost preview does not read another firm's item name ──────────

def test_the_landed_cost_preview_does_not_name_another_firms_item():
    from services import landed_cost_service as lc
    db = _FakeDB()
    _own_item(db)
    _foreign_item(db)
    db.store["purchase_bills"] = [
        {"id": "bill-1", "firm_id": OWN, "client_id": "client-1", "bill_no": "B-1",
         "our_reference": None, "status": "received", "landed_cost_basis": None}]
    db.store["clients"] = [{"id": "client-1", "firm_id": OWN, "landed_cost_basis": None}]
    db.store["purchase_bill_landed_costs"] = []
    db.store["purchase_bill_lines"] = [
        {"id": "p1", "bill_id": "bill-1", "description": "ours", "quantity": "3",
         "taxable_amount_paise": 3_000_00, "service_catalogue_id": "own-1",
         "itc_eligible": True, "cgst_paise": 0, "sgst_paise": 0, "igst_paise": 0, "cess_paise": 0},
        {"id": "p2", "bill_id": "bill-1", "description": "theirs", "quantity": "2",
         "taxable_amount_paise": 2_000_00, "service_catalogue_id": "foreign-1",
         "itc_eligible": True, "cgst_paise": 0, "sgst_paise": 0, "igst_paise": 0, "cess_paise": 0}]

    out = lc.read_for_bill(db, firm_id=OWN, client_id="client-1", bill_id="bill-1")

    assert out["found"] is True
    names = [ln["item_name"] for ln in out["lines"]]
    assert "Our Widget" in names
    assert "Their Widget" not in names and "Their Widget" not in repr(out), (
        "another firm's item name reached the landed-cost preview")
