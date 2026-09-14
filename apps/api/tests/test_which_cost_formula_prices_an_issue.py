"""INV-02 — AS-2 paragraph 14's two cost formulas, and what changing one means.

The moving average was the only formula the product had, so a client whose
books are kept on FIFO had a closing stock figure — and therefore a profit —
that its own accounting policy note did not describe.

What these tests hold, in the order the module reasons:

    1. The formula is a POLICY (AS-2 par. 16), carried with the client it
       belongs to, and a movement refuses a policy that is not its own.
    2. A RECEIPT costs the same under both, which is why the fork is in one
       function and `stock_position` needs no change.
    3. An ISSUE is where they differ, and the shape of the answer does not.
    4. Every invariant the moving-average path guards — force-close at zero,
       the deltas summing to the running value, an oversell at zero cost —
       holds identically under FIFO.
    5. A change is PROSPECTIVE (AS-5 par. 29/32) and nothing is re-costed.
    6. Standard cost is refused and NAMED (AS-2 par. 17).
"""
import uuid
from decimal import Decimal

import pytest

import domain.inventory_service as inventory_service
from domain.inventory import costing
from domain.inventory_service import (
    _compute_stock_out,
    _compute_stock_out_fifo,
    _open_layers,
    _policy,
    record_stock_in,
    record_stock_out,
    record_stock_out_at_value,
    record_nrv_writedown,
    resolve_costing_policy,
    seed_opening_balance,
)
from services import inventory_costing_policy_service as svc


FIRM = "firm-1"
CLIENT = "client-1"
ITEM = "item-1"


# ── the fake, deliberately the one the inventory suite already uses ─────────

class _Res:
    def __init__(self, data):
        self.data = data


class _Q:
    def __init__(self, store, table):
        self.store, self.t = store, table
        self.f = []
        self._order = []
        self._limit = None
        self._insert = None
        self._update = None

    def select(self, *a, **k):
        return self

    def eq(self, k, v):
        self.f.append(("eq", k, v))
        return self

    def gte(self, k, v):
        self.f.append(("gte", k, v))
        return self

    def lte(self, k, v):
        self.f.append(("lte", k, v))
        return self

    def in_(self, k, vals):
        self.f.append(("in", k, set(vals)))
        return self

    def is_(self, k, v):
        self.f.append(("is", k, v))
        return self

    def order(self, key, desc=False):
        self._order.append((key, desc))
        return self

    def limit(self, n):
        self._limit = n
        return self

    def range(self, lo, hi):
        self._range = (lo, hi)
        return self

    def insert(self, rows):
        self._insert = rows if isinstance(rows, list) else [rows]
        return self

    def update(self, patch):
        self._update = patch
        return self

    def _match(self, r):
        for op, k, v in self.f:
            if op == "eq" and r.get(k) != v:
                return False
            if op == "gte" and str(r.get(k)) < str(v):
                return False
            if op == "lte":
                # NUMERIC in production; the double compares as a number where
                # it can, so a running quantity of "10" is not "less than" "0"
                # by string order on some other column's values.
                try:
                    if Decimal(str(r.get(k))) > Decimal(str(v)):
                        return False
                except Exception:
                    if str(r.get(k)) > str(v):
                        return False
            if op == "in" and r.get(k) not in v:
                return False
            if op == "is":
                is_null = v in (None, "null")
                if is_null and r.get(k) is not None:
                    return False
        return True

    def execute(self):
        rows_table = self.store.setdefault(self.t, [])
        if self._insert is not None:
            out = []
            for r in self._insert:
                row = {"id": str(uuid.uuid4()), **r}
                rows_table.append(row)
                out.append(row)
            return _Res(out)
        if self._update is not None:
            updated = []
            for r in rows_table:
                if self._match(r):
                    r.update(self._update)
                    updated.append(r)
            return _Res(updated)
        # Copies, matching PostgREST: a caller must not be able to mutate the
        # store by holding on to a returned row.
        rows = [dict(r) for r in rows_table if self._match(r)]
        for key, desc in reversed(self._order):
            rows.sort(key=lambda r: str(r.get(key)), reverse=desc)
        if self._limit is not None:
            rows = rows[: self._limit]
        return _Res(rows)


class _DB:
    def __init__(self, method=None):
        self.store = {
            "clients": [{"id": CLIENT, "firm_id": FIRM, "name": "Acme",
                         "inventory_costing_method": method}],
            "service_catalogue": [{"id": ITEM, "firm_id": FIRM, "client_id": CLIENT,
                                   "name": "Widget", "kind": "good",
                                   "stock_qty_units": "0", "avg_cost_paise": 0}],
        }

    def table(self, name):
        return _Q(self.store, name)


def _in(db, qty, total_paise, date="2026-04-01"):
    return record_stock_in(
        db, firm_id=FIRM, client_id=CLIENT, service_catalogue_id=ITEM,
        movement_date=date, quantity=Decimal(str(qty)),
        total_cost_paise=total_paise, movement_type="purchase")


def _out(db, qty, date="2026-04-10"):
    return record_stock_out(
        db, firm_id=FIRM, client_id=CLIENT, service_catalogue_id=ITEM,
        movement_date=date, quantity=Decimal(str(qty)), movement_type="sale")


# ── 1. the formula is a policy ──────────────────────────────────────────────

def test_a_client_with_nothing_recorded_is_on_the_weighted_average():
    assert costing.method_for(None) == costing.MOVING_AVERAGE
    assert costing.method_for("") == costing.MOVING_AVERAGE
    assert costing.method_for("  FIFO ") == costing.FIFO


def test_the_unrecorded_answer_says_it_is_a_fact_and_not_a_guess():
    # The whole reason there is no DEFAULT on the column: every book in this
    # product was kept on the weighted average because it was the only
    # formula there was.
    assert "only formula" in costing.UNRECORDED_MEANS
    assert "guess" in costing.UNRECORDED_MEANS


def test_a_policy_cannot_be_built_on_a_formula_AS_2_does_not_permit():
    with pytest.raises(ValueError) as e:
        costing.CostingPolicy(client_id=CLIENT, method="standard_cost")
    assert "paragraph 17" in str(e.value)


def test_a_movement_REFUSES_another_clients_policy():
    db = _DB()
    other = costing.CostingPolicy(client_id="client-2", method=costing.FIFO)
    with pytest.raises(ValueError) as e:
        _policy(db, CLIENT, other)
    assert "belongs to a client" in str(e.value)


def test_a_movement_with_no_policy_reads_the_clients_own():
    db = _DB(method="fifo")
    assert _policy(db, CLIENT, None).method == costing.FIFO


def test_an_unreadable_client_row_never_blocks_the_document():
    class _Broken(_DB):
        def table(self, name):
            if name == "clients":
                raise RuntimeError("network")
            return super().table(name)

    # The formula every book in this product has always been kept on.
    assert resolve_costing_policy(_Broken(), CLIENT).method == costing.MOVING_AVERAGE


# ── 2. a receipt costs the same either way ──────────────────────────────────

@pytest.mark.parametrize("method", [None, "moving_average", "fifo"])
def test_a_receipt_adds_its_own_cost_whatever_the_formula(method):
    db = _DB(method=method)
    row = _in(db, 10, 10_000_00)
    assert row["running_qty_units"] == "10"
    assert row["running_value_paise"] == 10_000_00
    assert row["value_delta_paise"] == 10_000_00


def test_the_ledger_row_is_stamped_with_the_formula_in_force():
    db = _DB(method="fifo")
    _in(db, 10, 10_000_00)
    assert db.store["inventory_stock_ledger"][0]["costing_method"] == "fifo"


def test_an_unrecorded_client_stamps_the_formula_its_books_were_kept_on():
    db = _DB(method=None)
    _in(db, 10, 10_000_00)
    assert db.store["inventory_stock_ledger"][0]["costing_method"] == "moving_average"


# ── 3. an issue is where they differ ────────────────────────────────────────

def test_FIFO_prices_the_issue_off_the_OLDEST_layer_and_the_average_does_not():
    # 10 @ Rs 100, then 10 @ Rs 120. Sell 15.
    #   FIFO:            10 x 100 + 5 x 120 = Rs 1,600
    #   weighted average: 15 x 110          = Rs 1,650
    fifo_db, avg_db = _DB(method="fifo"), _DB(method="moving_average")
    for db in (fifo_db, avg_db):
        _in(db, 10, 1_000_00)
        _in(db, 10, 1_200_00, date="2026-04-05")
    fifo, avg = _out(fifo_db, 15), _out(avg_db, 15)
    assert fifo["value_delta_paise"] == -1_600_00
    assert avg["value_delta_paise"] == -1_650_00
    # And what is LEFT differs by exactly the same amount.
    assert fifo["running_value_paise"] == 600_00
    assert avg["running_value_paise"] == 550_00
    assert fifo["running_qty_units"] == avg["running_qty_units"] == "5"


def test_the_two_formulas_agree_when_every_layer_cost_the_same():
    fifo_db, avg_db = _DB(method="fifo"), _DB(method="moving_average")
    for db in (fifo_db, avg_db):
        _in(db, 10, 1_000_00)
        _in(db, 10, 1_000_00, date="2026-04-05")
    assert _out(fifo_db, 15)["value_delta_paise"] == _out(avg_db, 15)["value_delta_paise"]


def test_the_shape_of_a_FIFO_issue_is_the_moving_averages():
    layers = (costing.Layer(Decimal("10"), 100_00),)
    fifo = _compute_stock_out_fifo(Decimal("10"), 1_000_00, Decimal("4"), layers)
    avg = _compute_stock_out(Decimal("10"), 1_000_00, 100_00, Decimal("4"))
    assert set(fifo) == set(avg) , (
        "one posting path, one ledger and one closing-stock function serve "
        "both formulas — a key on one and not the other breaks that")


def test_the_issues_own_unit_cost_is_recorded_not_the_running_average():
    db = _DB(method="fifo")
    _in(db, 10, 1_000_00)
    _in(db, 10, 1_200_00, date="2026-04-05")
    row = _out(db, 15)
    # Rs 1,600 over 15 units, not the Rs 110 average.
    assert row["unit_cost_paise"] == 106_67
    assert row["running_avg_cost_paise"] == 120_00


# ── 4. every invariant the moving average guards holds under FIFO ───────────

def test_FIFO_force_closes_the_value_to_zero_when_the_quantity_is_exhausted():
    db = _DB(method="fifo")
    _in(db, 3, 1_000_01)          # a cost that does not divide by three
    row = _out(db, 3)
    assert row["running_qty_units"] == "0"
    assert row["running_value_paise"] == 0
    assert row["value_delta_paise"] == -1_000_01, (
        "the movement relieves EXACTLY what was on the books, so the deltas "
        "always sum to the running value")


def test_the_force_close_relieves_the_BOOKS_not_what_the_layers_add_up_to():
    # The layers and the ledger agree receipt by receipt, so the ordinary
    # case cannot tell the force-close from the clamp. This one can: the
    # layers here are short of the books by a paise, which is what a
    # re-basing division leaves, and only the force-close relieves the books.
    layers = (costing.Layer(Decimal("3"), 9_999),)
    calc = _compute_stock_out_fifo(Decimal("3"), 10_000, Decimal("3"), layers)
    assert calc["value_delta_paise"] == -10_000, (
        "without the force-close the Inventory control account keeps a paise "
        "for ever against a quantity of nil — the exact drift the "
        "moving-average path's own force-close exists to stop")
    assert calc["running_value_paise"] == 0


def test_an_oversell_under_FIFO_relieves_everything_the_books_held():
    layers = (costing.Layer(Decimal("2"), 5_000),)
    calc = _compute_stock_out_fifo(Decimal("2"), 5_000, Decimal("5"), layers)
    assert calc["running_qty_units"] == Decimal("-3")
    assert calc["value_delta_paise"] == -5_000
    assert calc["running_value_paise"] == 0


def test_FIFO_deltas_sum_to_the_running_value_across_many_small_issues():
    db = _DB(method="fifo")
    _in(db, 7, 1_000_00)
    for _ in range(6):
        _out(db, 1)
    rows = db.store["inventory_stock_ledger"]
    assert sum(int(r["value_delta_paise"]) for r in rows) == int(rows[-1]["running_value_paise"])


def test_an_oversell_is_recorded_at_zero_under_FIFO_exactly_as_under_the_average():
    fifo, avg = _DB(method="fifo"), _DB(method="moving_average")
    assert _out(fifo, 5)["running_value_paise"] == _out(avg, 5)["running_value_paise"] == 0
    assert _out(fifo, 1)["running_qty_units"] == "-6"


def test_a_receipt_covering_an_oversell_becomes_a_layer_of_only_the_excess():
    # Sold 5 with nothing on hand, then bought 8 @ Rs 100. Three units are on
    # hand; the other five are the true-up for units already gone.
    db = _DB(method="fifo")
    _out(db, 5, date="2026-04-02")
    row = _in(db, 8, 800_00, date="2026-04-03")
    assert row["running_qty_units"] == "3"
    assert row["running_value_paise"] == 300_00
    assert row["trueup_paise"] == 500_00
    layers = _open_layers(db, ITEM, {"running_value_paise": 300_00})
    assert costing.value_of(layers) == 300_00
    assert costing.quantity_of(layers) == Decimal("3")


def test_a_write_down_to_NRV_re_costs_every_remaining_layer(caplog):
    # AS-2 par. 5: carried at the lower of cost and net realisable value, and
    # the written-down amount is what the next issue costs.
    db = _DB(method="fifo")
    _in(db, 10, 1_000_00)
    record_nrv_writedown(
        db, firm_id=FIRM, client_id=CLIENT, service_catalogue_id=ITEM,
        movement_date="2026-04-05", nrv_per_unit_paise=60_00)
    with caplog.at_level("WARNING", logger="caflow.inventory"):
        row = _out(db, 4, date="2026-04-06")
    assert row["value_delta_paise"] == -240_00, (
        "priced at the written-down figure, not at what the goods cost")
    # AND SILENTLY. The outer re-base would reach the same figure, which is
    # why the replay handling a write-down looks redundant — the difference
    # is that this is the ordinary course and not a disagreement, and a
    # warning on an ordinary event is how people learn to ignore warnings.
    assert not [r for r in caplog.records if "re-basing" in r.getMessage()], (
        "a write-down is expected, not a discrepancy")


def test_a_cancellation_reversal_still_removes_the_ORIGINAL_value_under_FIFO():
    db = _DB(method="fifo")
    _in(db, 10, 1_000_00)
    _in(db, 10, 1_200_00, date="2026-04-05")
    row = record_stock_out_at_value(
        db, firm_id=FIRM, client_id=CLIENT, service_catalogue_id=ITEM,
        movement_date="2026-04-06", quantity=Decimal("10"),
        value_paise=1_200_00, movement_type="purchase_reversal")
    # The reversal mirrors the journal, which reversed the second receipt at
    # its own value — not the oldest layer's.
    assert row["value_delta_paise"] == -1_200_00
    assert row["running_value_paise"] == 1_000_00


def test_the_layers_are_re_based_on_the_books_after_such_a_reversal():
    db = _DB(method="fifo")
    _in(db, 10, 1_000_00)
    _in(db, 10, 1_200_00, date="2026-04-05")
    record_stock_out_at_value(
        db, firm_id=FIRM, client_id=CLIENT, service_catalogue_id=ITEM,
        movement_date="2026-04-06", quantity=Decimal("10"),
        value_paise=1_200_00, movement_type="purchase_reversal")
    # Ten units left and Rs 1,000 on the books. A replay would consume the
    # OLDEST ten and leave the Rs 1,200 layer, which the ledger contradicts.
    layers = _open_layers(db, ITEM, {"running_value_paise": 1_000_00})
    assert costing.value_of(layers) == 1_000_00, (
        "the ledger is the authority on the VALUE on hand — the stock ledger "
        "and the Inventory control account must never disagree")
    assert _out(db, 10, date="2026-04-07")["running_value_paise"] == 0


def test_the_replay_starts_at_the_last_time_stock_ran_out():
    db = _DB(method="fifo")
    _in(db, 5, 500_00)
    _out(db, 5, date="2026-04-02")          # force-close: every layer consumed
    _in(db, 4, 800_00, date="2026-04-03")   # Rs 200 a unit
    row = _out(db, 2, date="2026-04-04")
    assert row["value_delta_paise"] == -400_00, (
        "priced off the Rs 200 layer — nothing before the force-close can "
        "matter, because the running value there is exactly zero")


# ── 5. a change of formula is prospective ──────────────────────────────────

def test_a_change_with_no_date_is_refused_and_names_AS_5():
    r = costing.switch_refusal(current=None, wanted="fifo", effective_from=None)
    assert "AS-5 paragraph 29" in r and "not retrospective" in r


def test_a_change_behind_a_recorded_movement_is_refused_and_names_the_date():
    r = costing.switch_refusal(current=None, wanted="fifo",
                               effective_from="2026-04-01",
                               movement_on_or_after="2026-04-10")
    assert "2026-04-10" in r and "nothing is re-costed" in r


def test_recording_the_weighted_average_where_nothing_was_recorded_is_allowed():
    # Confirming in writing what the books have always been kept on.
    assert costing.switch_refusal(current=None, wanted="moving_average",
                                  effective_from="2026-04-01") is None


def test_recording_the_formula_already_in_force_says_there_is_nothing_to_do():
    r = costing.switch_refusal(current="fifo", wanted="fifo",
                               effective_from="2026-04-01")
    assert "already on" in r


def test_standard_cost_is_refused_and_names_the_paragraph():
    r = costing.switch_refusal(current=None, wanted="standard_cost",
                               effective_from="2026-04-01")
    assert "AS-2 paragraph 17" in r and "variance account" in r


def test_the_service_refuses_a_date_stock_has_already_moved_on():
    db = _DB()
    _in(db, 5, 500_00, date="2026-04-10")
    out = svc.set_policy(db, firm_id=FIRM, client_id=CLIENT,
                         method="fifo", effective_from="2026-04-01")
    assert out["ok"] is False and "2026-04-10" in out["refusal"]
    assert db.store["clients"][0]["inventory_costing_method"] is None, (
        "a refused change writes nothing")


def test_the_service_records_a_change_from_a_date_after_the_last_movement():
    db = _DB()
    _in(db, 5, 500_00, date="2026-04-10")
    out = svc.set_policy(db, firm_id=FIRM, client_id=CLIENT,
                         method="fifo", effective_from="2026-04-11")
    assert out["ok"] is True
    assert db.store["clients"][0]["inventory_costing_method"] == "fifo"


def test_a_client_in_another_firm_is_refused():
    db = _DB()
    out = svc.set_policy(db, firm_id="firm-2", client_id=CLIENT,
                         method="fifo", effective_from="2026-04-11")
    assert out["ok"] is False and "not in this firm" in out["refusal"]


def test_the_read_says_whether_anybody_has_CHOSEN_as_well_as_which_formula():
    db = _DB()
    read = svc.read_policy(db, firm_id=FIRM, client_id=CLIENT)
    assert read["method"] == "moving_average"
    assert read["is_recorded"] is False
    assert read["unrecorded_means"]
    db.store["clients"][0]["inventory_costing_method"] = "moving_average"
    read = svc.read_policy(db, firm_id=FIRM, client_id=CLIENT)
    assert read["method"] == "moving_average"
    assert read["is_recorded"] is True
    assert read["unrecorded_means"] is None


def test_the_read_suggests_the_day_after_the_last_movement():
    db = _DB()
    _in(db, 5, 500_00, date="2026-04-30")
    read = svc.read_policy(db, firm_id=FIRM, client_id=CLIENT)
    assert read["earliest_date_a_change_can_take_effect"] == "2026-05-01"


def test_a_client_with_no_movements_has_no_suggested_date():
    read = svc.read_policy(_DB(), firm_id=FIRM, client_id=CLIENT)
    assert read["earliest_date_a_change_can_take_effect"] is None


def test_which_formulas_priced_the_ledger_is_DERIVED_not_remembered():
    db = _DB()
    _in(db, 5, 500_00, date="2026-04-10")
    db.store["clients"][0]["inventory_costing_method"] = "fifo"
    _in(db, 5, 700_00, date="2026-05-10")
    spans = svc.ledger_methods_used(db, firm_id=FIRM, client_id=CLIENT)
    assert [s["method"] for s in spans] == ["moving_average", "fifo"]
    assert spans[0]["last_movement"] == "2026-04-10"
    assert spans[1]["first_movement"] == "2026-05-10"


def test_an_opening_balance_is_stamped_too_so_the_span_starts_where_it_should():
    db = _DB(method="fifo")
    seed_opening_balance(
        db, firm_id=FIRM, client_id=CLIENT, service_catalogue_id=ITEM,
        movement_date="2026-04-01", opening_qty=Decimal("5"),
        opening_cost_paise=500_00)
    assert db.store["inventory_stock_ledger"][0]["costing_method"] == "fifo"


# ── 6. what the fork does NOT touch ────────────────────────────────────────

def test_closing_stock_as_at_a_date_needs_no_knowledge_of_the_formula():
    # `domain/reporting/stock_position` sums value_delta_paise, and FIFO
    # produces that figure the same way the moving average does. A mention of
    # the formula there would be a second place the rule lives.
    import inspect
    from domain.reporting import stock_position
    src = inspect.getsource(stock_position)
    assert "fifo" not in src.lower()
    assert "costing_method" not in src


def test_the_batch_opening_seed_reads_the_client_ONCE_per_client():
    reads = {"n": 0}

    class _Counting(_DB):
        def table(self, name):
            if name == "clients":
                reads["n"] += 1
            return super().table(name)

    db = _Counting(method="fifo")
    rows = []
    for i in range(5):
        iid = f"item-{i}"
        db.store["service_catalogue"].append(
            {"id": iid, "firm_id": FIRM, "client_id": CLIENT, "kind": "good",
             "stock_qty_units": "0", "avg_cost_paise": 0})
        rows.append({"id": iid, "client_id": CLIENT, "kind": "good",
                     "opening_qty_units": "2", "opening_cost_paise": 200_00,
                     "created_at": "2026-04-01T00:00:00Z"})
    inventory_service.seed_opening_balances_batch(
        db, firm_id=FIRM, created_by=None, rows=rows)
    assert reads["n"] == 1, (
        "a bulk import is exactly the shape that made the old per-row loop "
        "hang — a fresh round trip per product puts it straight back")
    assert all(r["costing_method"] == "fifo"
               for r in db.store["inventory_stock_ledger"])


# ── the invariant that caught the watermark bug ────────────────────────────
# The first version of `_open_layers` dropped the watermark row's own oversold
# deficit, so a receipt clearing an oversell became a layer of its WHOLE
# quantity. The value check below it re-based and hid that; only the QUANTITY
# says so. This walks a sequence with every movement shape in it and asserts
# the layers describe the ledger on both.

_SEQUENCE = [
    ("in", 10, 1_000_00),
    ("out", 4, None),
    ("in", 6, 900_00),
    ("out", 12, None),      # exhausts and oversells -> force-close below zero
    ("in", 9, 1_800_00),    # clears the deficit, three units genuinely on hand
    ("out", 2, None),
    ("in", 5, 600_00),
    ("out", 5, None),
]


def test_the_layers_describe_the_ledger_on_quantity_AND_value_at_every_step():
    db = _DB(method="fifo")
    day = 0
    for kind, qty, cost in _SEQUENCE:
        day += 1
        date = f"2026-04-{day:02d}"
        if kind == "in":
            _in(db, qty, cost, date=date)
        else:
            _out(db, qty, date=date)
        last = db.store["inventory_stock_ledger"][-1]
        layers = _open_layers(db, ITEM, last)
        running_qty = Decimal(str(last["running_qty_units"]))
        assert costing.value_of(layers) == int(last["running_value_paise"]), (
            f"after {kind} {qty} on {date}: the layers must be worth what the "
            f"ledger holds")
        assert costing.quantity_of(layers) == max(Decimal(0), running_qty), (
            f"after {kind} {qty} on {date}: the layers must hold the units the "
            f"ledger holds — a value that ties over the wrong quantity prices "
            f"the next issue wrongly")


def test_a_quantity_disagreement_is_logged_rather_than_absorbed(caplog):
    db = _DB(method="fifo")
    _in(db, 10, 1_000_00)
    with caplog.at_level("WARNING", logger="caflow.inventory"):
        _open_layers(db, ITEM, {"running_qty_units": "4",
                                "running_value_paise": 1_000_00})
    assert any("do not describe this item's position" in r.getMessage()
               for r in caplog.records)


# ── 7. exactness: the layers tie to the books to the paise ─────────────────
# The layer model carries a VALUE and not a unit cost for one reason: three
# units costing Rs 100 have a unit cost of 3,333 paise and a value of 10,000,
# and 3 x 3,333 is 9,999. Every test below is that one paise, in the place it
# would otherwise appear.

def test_a_layer_is_worth_the_value_the_LEDGER_added_not_quantity_times_a_rate():
    pos = costing.layers_from_movements(
        [{"quantity_delta": 3, "value_delta_paise": 10_000,
          "unit_cost_paise": 3_333}])
    assert costing.value_of(pos.layers) == 10_000, (
        "a layer built from a rounded unit cost is a paise short of the "
        "running value on every receipt whose cost does not divide by its "
        "quantity — and that residue is indistinguishable from the real "
        "difference a cancellation reversal leaves")


def test_taking_a_WHOLE_layer_takes_its_whole_value():
    issue = costing.consume((costing.Layer(Decimal("3"), 10_000),), Decimal("3"))
    assert issue.value_paise == 10_000
    assert issue.remaining == ()


def test_a_part_issue_and_what_is_left_add_back_to_what_was_there():
    layers = (costing.Layer(Decimal("3"), 10_000),)
    for take in ("1", "2", "0.5", "2.5"):
        issue = costing.consume(layers, Decimal(take))
        assert issue.value_paise + costing.value_of(issue.remaining) == 10_000, (
            f"taking {take} of three units left a residue")


def test_repeated_part_issues_never_accumulate_a_residue():
    layers = (costing.Layer(Decimal("7"), 10_000),)
    spent = 0
    for _ in range(7):
        issue = costing.consume(layers, Decimal("1"))
        spent += issue.value_paise
        layers = issue.remaining
    assert spent == 10_000
    assert costing.value_of(layers) == 0


def test_a_rebase_sums_to_the_target_EXACTLY():
    # Largest remainder, the same discipline domain/gst/discount.py uses for a
    # document-level discount: the parts sum to the whole or the layers stop
    # describing the books.
    for target in (10_000, 10_001, 9_999, 1, 0):
        for n in (3, 7, 11):
            layers = tuple(costing.Layer(Decimal("1"), 0) for _ in range(n))
            out = costing.rebase(layers, target)
            assert costing.value_of(out) == target, (target, n)


def test_a_rebase_over_unequal_quantities_is_proportional_and_exact():
    layers = (costing.Layer(Decimal("1"), 0), costing.Layer(Decimal("2"), 0))
    out = costing.rebase(layers, 10_000)
    assert [l.value_paise for l in out] == [3_333, 6_667]
    assert costing.value_of(out) == 10_000


def test_the_issue_is_CLAMPED_to_what_the_books_hold():
    # Non-terminal: five units on hand, the books hold less than the layers
    # say. Without the clamp the running value goes NEGATIVE and the Inventory
    # control account follows it.
    layers = (costing.Layer(Decimal("5"), 1_000),)
    calc = _compute_stock_out_fifo(Decimal("5"), 300, Decimal("2"), layers)
    assert calc["value_delta_paise"] == -300
    assert calc["running_value_paise"] == 0
    assert calc["running_qty_units"] == Decimal("3")


def test_two_movements_at_the_same_instant_both_survive_the_watermark():
    # The watermark row is dropped by ID and not by timestamp. Dropping by
    # timestamp would take a real movement with it whenever two rows share a
    # `created_at`, and the replay would then be short a layer.
    db = _DB(method="fifo")
    _in(db, 5, 500_00)
    _out(db, 5, date="2026-04-02")          # force-close
    _in(db, 4, 800_00, date="2026-04-03")
    ledger = db.store["inventory_stock_ledger"]
    ledger[2]["created_at"] = ledger[1]["created_at"]   # same instant
    layers = _open_layers(db, ITEM, ledger[-1])
    assert costing.quantity_of(layers) == Decimal("4")
    assert costing.value_of(layers) == 800_00


def test_the_watermark_can_only_narrow_the_read_never_change_the_answer():
    # A watermark query that answers nothing at all (an unsupported filter, a
    # driver that raises) must give the same layers as one that answers.
    class _NoWatermark(_DB):
        def table(self, name):
            q = super().table(name)
            if name == "inventory_stock_ledger":
                original = q.lte

                def _lte(k, v):
                    if k == "running_qty_units":
                        raise RuntimeError("this driver has no numeric lte")
                    return original(k, v)
                q.lte = _lte
            return q

    for db in (_DB(method="fifo"), _NoWatermark(method="fifo")):
        _in(db, 5, 500_00)
        _out(db, 5, date="2026-04-02")
        _in(db, 4, 800_00, date="2026-04-03")
        _out(db, 1, date="2026-04-04")
        last = db.store["inventory_stock_ledger"][-1]
        layers = _open_layers(db, ITEM, last)
        assert costing.value_of(layers) == 600_00
        assert costing.quantity_of(layers) == Decimal("3")
