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
  4. THE CATALOGUE IS CLIENT-OWNED, NOT JUST FIRM-OWNED (POST-A-109; migration 182 makes
     `service_catalogue.client_id` NOT NULL). The firm filter in (1) left a line on one
     client's document naming ANOTHER CLIENT's item of the same firm free to move that
     client's stock and price the cost of goods sold off its average cost. The four posting
     paths, the manual-adjustment and write-down functions and the landed-cost preview now
     ask for the item under the firm AND the client. The two reversal paths read the stock
     ledger by the document's id alone, which is unique only within its own table, so they
     now read it under the firm and the client too: a reversal for one client's invoice can
     no longer find, and reverse, another's movements, and another client's reversal row
     can no longer make this one's look already done. HONESTLY: the reversal filters are defence in depth. Both routes
     resolve the document under the firm before they call them, a document id is a UUID, and every production ledger row
     already matches its source document's firm and client (measured 17-10-2026), so no failing input exists today; the
     four posting lookups and the batch door are the live defects (a line's or a body's item id is not checked at create).
  5. A BATCH NAMES AN ITEM. `POST /inventory/batches` took `service_catalogue_id` from the body and inserted it; foreign
     keys ignore row security, so another firm's or client's item id was accepted. `inventory_location_service.create_batch`
     now reads the item under the firm and the client.
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


# ── the catalogue is the CLIENT's: same firm, different client (POST-A-109) ──

OTHER_CLIENT = "client-2"


def _other_clients_item(db, item_id="sibling-1"):
    """An item of the SAME firm that belongs to a different client, holding ten units at Rs 1,000 each."""
    _seed_catalogue_item(db, item_id=item_id, client_id=OTHER_CLIENT, kind="good", name="Sibling Widget")
    inv.record_stock_in(
        db, firm_id=OWN, client_id=OTHER_CLIENT, service_catalogue_id=item_id,
        movement_date="2026-04-01", quantity=Decimal("10"), total_cost_paise=10_000_00,
        movement_type="opening")


@pytest.mark.parametrize("kind, post", DOCUMENTS, ids=[k for k, _ in DOCUMENTS])
def test_a_line_naming_another_clients_item_of_the_same_firm_moves_none_of_its_stock(kind, post):
    db = _FakeDB()
    _other_clients_item(db)
    before_ledger = [dict(r) for r in db.store["inventory_stock_ledger"]]
    before_item = dict(_item_row(db, "sibling-1"))

    post(db, "sibling-1")

    assert db.store["inventory_stock_ledger"] == before_ledger, (
        f"a {kind} line for one client wrote to another client's stock ledger")
    assert _item_row(db, "sibling-1") == before_item, (
        f"a {kind} line for one client changed another client's stock and cost")


def test_the_adjustment_and_write_down_functions_ask_for_the_item_under_the_client():
    db = _FakeDB()
    _other_clients_item(db)
    before = [dict(r) for r in db.store["inventory_stock_ledger"]]

    adjusted = inv.apply_stock_adjustment(
        db, firm_id=OWN, client_id="client-1", service_catalogue_id="sibling-1",
        movement_date="2026-04-20", quantity=Decimal("2"), direction="decrease")
    written_down = inv.apply_nrv_writedown(
        db, firm_id=OWN, client_id="client-1", service_catalogue_id="sibling-1",
        movement_date="2026-04-20", nrv_per_unit_paise=500_00)

    assert adjusted is None, "an adjustment named another client's item and was posted"
    assert written_down is None, "a write-down named another client's item and was posted"
    assert db.store["inventory_stock_ledger"] == before


def test_the_landed_cost_preview_does_not_name_another_clients_item():
    from services import landed_cost_service as lc
    db = _FakeDB()
    _own_item(db)
    _other_clients_item(db)
    db.store["purchase_bills"] = [
        {"id": "bill-1", "firm_id": OWN, "client_id": "client-1", "bill_no": "B-1",
         "our_reference": None, "status": "received", "landed_cost_basis": None}]
    db.store["clients"] = [{"id": "client-1", "firm_id": OWN, "landed_cost_basis": None}]
    db.store["purchase_bill_landed_costs"] = []
    db.store["purchase_bill_lines"] = [
        {"id": "p1", "bill_id": "bill-1", "description": "ours", "quantity": "3",
         "taxable_amount_paise": 3_000_00, "service_catalogue_id": "own-1",
         "itc_eligible": True, "cgst_paise": 0, "sgst_paise": 0, "igst_paise": 0, "cess_paise": 0},
        {"id": "p2", "bill_id": "bill-1", "description": "sibling", "quantity": "2",
         "taxable_amount_paise": 2_000_00, "service_catalogue_id": "sibling-1",
         "itc_eligible": True, "cgst_paise": 0, "sgst_paise": 0, "igst_paise": 0, "cess_paise": 0}]

    out = lc.read_for_bill(db, firm_id=OWN, client_id="client-1", bill_id="bill-1")

    assert "Our Widget" in [ln["item_name"] for ln in out["lines"]]
    assert "Sibling Widget" not in repr(out), "another client's item name reached the landed-cost preview"


# ── a reversal reads the ledger under the firm AND the client ────────────────

def _someone_elses_sale(db, *, firm, client, item_id):
    """A sale of 3 units booked against the id `inv-1` — the same id the reversal below is asked about."""
    inv.record_stock_out(
        db, firm_id=firm, client_id=client, service_catalogue_id=item_id,
        movement_date="2026-04-10", quantity=Decimal("3"), movement_type="sale",
        source_type="sales_invoice", source_id="inv-1", reference_no="INV-1")


def _someone_elses_purchase(db, *, firm, client, item_id):
    inv.record_stock_in(
        db, firm_id=firm, client_id=client, service_catalogue_id=item_id,
        movement_date="2026-04-05", quantity=Decimal("3"), total_cost_paise=3_000_00,
        movement_type="purchase", source_type="purchase_bill", source_id="bill-1", reference_no="BILL-1")


def _reverse_sale(db):
    inv.reverse_sale_stock(db, firm_id=OWN, client_id="client-1", invoice_id="inv-1", invoice_no="INV-1")


def _reverse_purchase(db):
    inv.reverse_purchase_stock(db, firm_id=OWN, client_id="client-1", bill_id="bill-1", bill_reference="BILL-1")


REVERSALS = [
    ("sale", _someone_elses_sale, _reverse_sale),
    ("purchase", _someone_elses_purchase, _reverse_purchase),
]


@pytest.mark.parametrize("whose", ["another firm's", "another client's"])
@pytest.mark.parametrize("kind, book, reverse", REVERSALS, ids=[k for k, _, _ in REVERSALS])
def test_a_reversal_does_not_find_and_reverse_somebody_elses_movements(kind, book, reverse, whose):
    db = _FakeDB()
    if whose == "another firm's":
        _foreign_item(db)
        book(db, firm=THEIRS, client="client-9", item_id="foreign-1")
        item = "foreign-1"
    else:
        _other_clients_item(db)
        book(db, firm=OWN, client=OTHER_CLIENT, item_id="sibling-1")
        item = "sibling-1"
    before_ledger = [dict(r) for r in db.store["inventory_stock_ledger"]]
    before_item = dict(_item_row(db, item))

    reverse(db)

    assert db.store["inventory_stock_ledger"] == before_ledger, (
        f"cancelling a {kind} document reversed {whose} stock movement that shares its id")
    assert _item_row(db, item) == before_item


@pytest.mark.parametrize("whose", ["another firm's", "another client's"])
@pytest.mark.parametrize("kind, book, reverse", REVERSALS, ids=[k for k, _, _ in REVERSALS])
def test_somebody_elses_reversal_row_does_not_make_this_reversal_look_done(kind, book, reverse, whose):
    """The idempotency probe is scoped too: a reversal row of another firm or client with the same source id must not
    make this client's reversal return early and leave its own stock outstanding."""
    db = _FakeDB()
    _own_item(db)
    if kind == "sale":
        _someone_elses_sale(db, firm=OWN, client="client-1", item_id="own-1")
        reversal_type, source_type = "sale_reversal", "sales_invoice"
        source_id = "inv-1"
    else:
        _someone_elses_purchase(db, firm=OWN, client="client-1", item_id="own-1")
        reversal_type, source_type = "purchase_reversal", "purchase_bill"
        source_id = "bill-1"
    firm, client = (THEIRS, "client-9") if whose == "another firm's" else (OWN, OTHER_CLIENT)
    db.store["inventory_stock_ledger"].append({
        "id": "stray-reversal", "firm_id": firm, "client_id": client, "service_catalogue_id": "elsewhere-1",
        "movement_type": reversal_type, "source_type": source_type, "source_id": source_id,
        "quantity_delta": "1", "value_delta_paise": 1})
    own_before = [r for r in db.store["inventory_stock_ledger"] if r.get("service_catalogue_id") == "own-1"]

    reverse(db)

    own_after = [r for r in db.store["inventory_stock_ledger"] if r.get("service_catalogue_id") == "own-1"]
    assert len(own_after) == len(own_before) + 1, (
        f"{whose} reversal row made this client's {kind} cancellation skip its own reversal")
    assert own_after[-1]["movement_type"] == reversal_type


@pytest.mark.parametrize("kind, book, reverse", REVERSALS, ids=[k for k, _, _ in REVERSALS])
def test_a_reversal_still_reverses_the_clients_own_movements(kind, book, reverse):
    """The control for the three tests above: the extra filters keep strangers out and nothing else."""
    db = _FakeDB()
    _own_item(db)
    book(db, firm=OWN, client="client-1", item_id="own-1")
    before = len(db.store["inventory_stock_ledger"])

    reverse(db)

    assert len(db.store["inventory_stock_ledger"]) == before + 1
    assert db.store["inventory_stock_ledger"][-1]["movement_type"].endswith("_reversal")


# ── the FIRM half of each filter, isolated ────────────────────────────────────
# `_foreign_item` belongs to another firm AND another client, so on its own it cannot tell the firm filter from the
# client filter: removing either leaves its test green. These rows share the client's id and differ only in the firm,
# which production cannot hold (a client belongs to one firm) and which is exactly what isolates the firm predicate.

def _same_client_other_firm_item(db, item_id="shadow-1"):
    _seed_catalogue_item(db, item_id=item_id, firm_id=THEIRS, client_id="client-1", kind="good", name="Shadow Widget")
    inv.record_stock_in(
        db, firm_id=THEIRS, client_id="client-1", service_catalogue_id=item_id,
        movement_date="2026-04-01", quantity=Decimal("10"), total_cost_paise=10_000_00, movement_type="opening")


@pytest.mark.parametrize("kind, post", DOCUMENTS, ids=[k for k, _ in DOCUMENTS])
def test_the_firm_filter_alone_keeps_a_posting_off_another_firms_item(kind, post):
    db = _FakeDB()
    _same_client_other_firm_item(db)
    before = ([dict(r) for r in db.store["inventory_stock_ledger"]], dict(_item_row(db, "shadow-1")))

    post(db, "shadow-1")

    assert ([dict(r) for r in db.store["inventory_stock_ledger"]], dict(_item_row(db, "shadow-1"))) == before, kind


def test_the_firm_filter_alone_keeps_the_adjustment_and_the_write_down_off_another_firms_item():
    db = _FakeDB()
    _same_client_other_firm_item(db)
    before = [dict(r) for r in db.store["inventory_stock_ledger"]]
    assert inv.apply_stock_adjustment(
        db, firm_id=OWN, client_id="client-1", service_catalogue_id="shadow-1",
        movement_date="2026-04-20", quantity=Decimal("2"), direction="decrease") is None
    assert inv.apply_nrv_writedown(
        db, firm_id=OWN, client_id="client-1", service_catalogue_id="shadow-1",
        movement_date="2026-04-20", nrv_per_unit_paise=500_00) is None
    assert db.store["inventory_stock_ledger"] == before


@pytest.mark.parametrize("kind, book, reverse", REVERSALS, ids=[k for k, _, _ in REVERSALS])
def test_the_firm_filter_alone_keeps_a_reversal_off_another_firms_movements(kind, book, reverse):
    db = _FakeDB()
    _same_client_other_firm_item(db)
    book(db, firm=THEIRS, client="client-1", item_id="shadow-1")
    before = [dict(r) for r in db.store["inventory_stock_ledger"]]

    reverse(db)

    assert db.store["inventory_stock_ledger"] == before, kind


def test_the_firm_filter_alone_keeps_the_landed_cost_preview_off_another_firms_item_name():
    from services import landed_cost_service as lc
    db = _FakeDB()
    _own_item(db)
    _same_client_other_firm_item(db)
    db.store["purchase_bills"] = [
        {"id": "bill-1", "firm_id": OWN, "client_id": "client-1", "bill_no": "B-1",
         "our_reference": None, "status": "received", "landed_cost_basis": None}]
    db.store["clients"] = [{"id": "client-1", "firm_id": OWN, "landed_cost_basis": None}]
    db.store["purchase_bill_landed_costs"] = []
    db.store["purchase_bill_lines"] = [
        {"id": "p2", "bill_id": "bill-1", "description": "shadow", "quantity": "2",
         "taxable_amount_paise": 2_000_00, "service_catalogue_id": "shadow-1",
         "itc_eligible": True, "cgst_paise": 0, "sgst_paise": 0, "igst_paise": 0, "cess_paise": 0}]
    out = lc.read_for_bill(db, firm_id=OWN, client_id="client-1", bill_id="bill-1")
    assert "Shadow Widget" not in repr(out)


# ── a batch names an item, and the item must be this client's ────────────────

def _batch(db, item_id, client="client-1"):
    from services import inventory_location_service as loc_svc
    return loc_svc.create_batch(
        db, firm_id=OWN, client_id=client, service_catalogue_id=item_id, batch_no="B-1",
        manufactured_on=None, expiry_date=None, notes=None, actor_id=None)


def test_a_batch_for_the_clients_own_item_is_created():
    db = _FakeDB()
    _own_item(db)
    assert _batch(db, "own-1")["service_catalogue_id"] == "own-1"


@pytest.mark.parametrize("shape", ["other firm", "other client of this firm", "same client, other firm", "no such item"])
def test_a_batch_naming_an_item_that_is_not_this_clients_is_refused_and_writes_nothing(shape):
    from fastapi import HTTPException
    db = _FakeDB()
    _own_item(db)
    _foreign_item(db)
    _other_clients_item(db)
    _same_client_other_firm_item(db)
    item = {"other firm": "foreign-1", "other client of this firm": "sibling-1",
            "same client, other firm": "shadow-1", "no such item": "nope"}[shape]

    with pytest.raises(HTTPException) as refused:
        _batch(db, item)

    assert refused.value.status_code == 404
    assert db.store.get("inventory_batches", []) == [], "a refused batch must write nothing"


def test_a_batch_for_a_service_is_refused():
    from fastapi import HTTPException
    db = _FakeDB()
    _seed_catalogue_item(db, item_id="svc-1", kind="service", name="Consulting")
    with pytest.raises(HTTPException) as refused:
        _batch(db, "svc-1")
    assert refused.value.status_code == 422


def test_a_sibling_clients_item_on_a_line_is_noted_in_the_log(caplog):
    import logging
    db = _FakeDB()
    _other_clients_item(db)
    with caplog.at_level(logging.WARNING, logger="caflow.inventory"):
        _sale(db, "sibling-1")
    notes = [r.getMessage() for r in caplog.records if r.name == "caflow.inventory"]
    assert any("sale" in n and "1 line item id" in n and "firm and client" in n for n in notes), notes
    assert not any("sibling-1" in n for n in notes), "the id of an item that is not the client's must not be logged"
