"""Godowns, batches and expiry (INV-03a, migration 398).

WHAT WAS MISSING
    `inventory_stock_ledger` records WHAT moved, WHEN and for how much. It never
    recorded WHERE it moved or WHICH LOT it was, so a client with two
    warehouses had one undifferentiated pile of stock and a client whose goods
    expire had no way to say which ones.

THE TWO PROPERTIES THAT MATTER MOST ARE BOTH ABOUT NOT BEING CLEVER
    A batch does NOT change what an issue costs. AS-2 paragraph 14 permits FIFO
    or weighted average and migration 394 made that a client policy; paragraph
    13's specific identification is a THIRD formula, and a batch column is
    exactly the thing that invites it in silently. A test asserts
    `record_stock_out` never mentions a batch.

    A transfer between godowns under DIFFERENT registrations is a supply
    (Schedule I paragraph 2 with s.25(4)) and this software does not raise the
    invoice: Rule 28's valuation option is the client's. The decision is a
    tri-state — True, False, and None where a registration is not recorded —
    because one guess mints a document the Act does not ask for and the other
    omits one it does.
"""
from __future__ import annotations

import inspect
from datetime import date
from decimal import Decimal

import pytest

from domain.inventory import batches as batch_domain
from domain.inventory import location as loc
from domain.reporting import stock_position as sp
from services import inventory_location_service as svc
from tests.e2e_harness import FakeDB

FIRM = "firm-inv03"
CLIENT = "client-inv03"
AS_OF = date(2026, 9, 14)

BHIWANDI = loc.Godown("g1", "Bhiwandi", state_code="27",
                      gstin="27AAACA1234A1Z5", is_default=True)
BHIWANDI_2 = loc.Godown("g2", "Bhiwandi Annexe", state_code="27",
                        gstin="27AAACA1234A1Z5")
HOSUR = loc.Godown("g3", "Hosur", state_code="29", gstin="29AAACA1234A1Z2")
UNRECORDED = loc.Godown("g4", "New shed")


# ── 1. a transfer between registrations is a supply ─────────────────────────

def test_two_godowns_under_DIFFERENT_registrations_is_a_supply():
    """Schedule I paragraph 2 with s.25(4): two registrations of one entity are
    distinct persons, so the movement is a supply even with no consideration."""
    d = loc.transfer_decision(BHIWANDI, HOSUR)
    assert d.is_supply is True
    assert d.same_registration is False
    assert "distinct persons" in d.reason
    assert "tax invoice" in d.reason


def test_two_godowns_under_the_SAME_registration_is_not():
    d = loc.transfer_decision(BHIWANDI, BHIWANDI_2)
    assert d.is_supply is False
    assert d.same_registration is True
    assert "not a supply" in d.reason


def test_the_comparison_is_on_the_REGISTRATION_not_the_state():
    """s.25(2)'s proviso allows a second registration within one state, so two
    godowns in Maharashtra under different GSTINs ARE distinct persons.
    Comparing state codes would call that a non-supply."""
    second = loc.Godown("g5", "Pune", state_code="27", gstin="27AAACA1234A2Z4")
    assert BHIWANDI.state_code == second.state_code
    assert loc.transfer_decision(BHIWANDI, second).is_supply is True


def test_an_unrecorded_registration_is_REFUSED_never_guessed():
    """The tri-state, and both guesses are wrong: one mints a tax invoice the
    Act does not ask for, the other omits one it does."""
    d = loc.transfer_decision(BHIWANDI, UNRECORDED)
    assert d.is_supply is None
    assert d.same_registration is None
    assert d.gaps and "cannot be determined" in d.gaps[0]


def test_the_software_does_not_raise_the_invoice_and_says_why():
    """Rule 28's valuation option — open market value, like goods, or 90% of the
    onward price, at the supplier's election — is not recorded anywhere here."""
    assert "Rule 28" in loc.INTERSTATE_TRANSFER_IS_A_SUPPLY
    assert "does not raise it" in loc.INTERSTATE_TRANSFER_IS_A_SUPPLY
    # And the same-registration answer names the document that IS needed.
    assert "Rule 55" in loc.SAME_REGISTRATION_IS_NOT_A_SUPPLY


# ── 2. the default godown ───────────────────────────────────────────────────

def test_the_default_is_the_MARKED_one():
    assert loc.default_godown([HOSUR, BHIWANDI]).godown_id == "g1"


def test_one_active_godown_needs_no_marking():
    assert loc.default_godown([HOSUR]).godown_id == "g3"


def test_several_with_none_marked_is_None_never_the_first():
    """A movement landing in whichever godown happened to sort first is a
    position nobody can explain later."""
    assert loc.default_godown([HOSUR, BHIWANDI_2]) is None


def test_a_closed_godown_is_not_the_default_and_cannot_take_stock():
    closed = loc.Godown("g6", "Old shed", is_active=False, is_default=True)
    assert loc.default_godown([closed]) is None
    assert "closed" in loc.refusal_for([closed], "g6")


def test_a_client_with_no_godowns_is_not_refused():
    """The columns are nullable and every movement before migration 398 has
    none, so requiring one would break the ordinary path for every client who
    keeps stock in one place."""
    assert loc.refusal_for([], None) is None


def test_a_godown_from_another_client_is_refused():
    assert loc.refusal_for([BHIWANDI], "somebody-elses") is not None


# ── 3. expiry ───────────────────────────────────────────────────────────────

def _pos(expiry, qty="10", value=1000, batch="L-1"):
    return batch_domain.BatchPosition(
        batch_id=f"b-{batch}", batch_no=batch, service_catalogue_id="i1",
        item_name="Syrup", quantity=Decimal(qty), value_paise=value,
        expiry_date=expiry)


@pytest.mark.parametrize("expiry,expected", [
    (date(2026, 9, 13), batch_domain.EXPIRED),
    (date(2026, 9, 14), batch_domain.WITHIN_30),      # today: still good
    (date(2026, 10, 14), batch_domain.WITHIN_30),     # exactly 30 days
    (date(2026, 10, 15), batch_domain.WITHIN_90),
    (date(2026, 12, 13), batch_domain.WITHIN_90),     # exactly 90 days
    (date(2026, 12, 14), batch_domain.LATER),
    (None, batch_domain.NO_EXPIRY_RECORDED),
])
def test_the_bucket_boundaries(expiry, expected):
    assert batch_domain.bucket_for(expiry, AS_OF) == expected


def test_stock_is_good_ON_its_expiry_date():
    """A shelf life runs to the end of the stated day. Reading it the other way
    writes off a day of sound stock and reverses §17(5)(h) credit that is not
    yet due to be reversed."""
    assert batch_domain.bucket_for(AS_OF, AS_OF) != batch_domain.EXPIRED


def test_no_expiry_recorded_is_its_own_answer_and_not_LATER():
    """Stock that does not expire and stock whose date nobody wrote down are
    opposite situations. "Later" would tell a CA the stock is sound."""
    report = batch_domain.expiry_report([_pos(None)], as_of=AS_OF)
    assert report.buckets[batch_domain.NO_EXPIRY_RECORDED]["batches"] == 1
    assert report.buckets[batch_domain.LATER]["batches"] == 0
    assert any("not the same as" in n for n in report.notes)


def test_a_batch_with_nothing_left_is_not_reported():
    """A lot fully issued has nothing to expire, and listing it puts a CA on
    the phone about goods that left months ago."""
    report = batch_domain.expiry_report([_pos(date(2026, 1, 1), qty="0")],
                                        as_of=AS_OF)
    assert report.rows == []


def test_a_NEGATIVE_position_is_kept_because_it_is_a_defect_not_an_absence():
    report = batch_domain.expiry_report([_pos(date(2027, 1, 1), qty="-5")],
                                        as_of=AS_OF)
    assert len(report.rows) == 1


def test_expired_stock_names_the_write_off_and_s_17_5_h():
    report = batch_domain.expiry_report([_pos(date(2026, 1, 1))], as_of=AS_OF)
    note = " ".join(report.notes)
    assert "17(5)(h)" in note
    assert "written off" in note


def test_the_rows_are_soonest_first_with_no_date_last():
    report = batch_domain.expiry_report(
        [_pos(None, batch="C"), _pos(date(2027, 1, 1), batch="B"),
         _pos(date(2026, 1, 1), batch="A")], as_of=AS_OF)
    assert [r["batch_no"] for r in report.rows] == ["A", "B", "C"]


def test_first_expiry_first_out_is_a_PICKING_order_and_says_so():
    """Suggested, never applied: what an issue costs is the client's own AS-2
    paragraph 14 policy, and forcing an order would change their closing
    stock."""
    order = batch_domain.first_expiry_first_out(
        [_pos(None, batch="C"), _pos(date(2027, 1, 1), batch="B"),
         _pos(date(2026, 1, 1), batch="A")])
    assert [p.batch_no for p in order] == ["A", "B", "C"]
    assert "picking order" in batch_domain.first_expiry_first_out.__doc__


# ── 4. A BATCH IS NOT A COST FORMULA ────────────────────────────────────────

def test_the_issue_path_never_mentions_a_batch():
    """THE LINE THIS WHOLE FEATURE HAS TO NOT CROSS.

    AS-2 paragraph 13's specific identification — costing an issue at its own
    batch's cost — is a third formula beside the two migration 394 made a
    client policy. Applying it silently would give a client a closing stock
    figure, and therefore a profit, that their own accounting policy note does
    not describe. Asserted on the SOURCE of the function that prices an issue,
    because a test on one scenario would pass while a branch existed.
    """
    from domain import inventory_service
    src = inspect.getsource(inventory_service.record_stock_out)
    assert "batch" not in src.lower(), (
        "record_stock_out has learned about batches — that is AS-2 paragraph "
        "13 specific identification, a third cost formula, arriving by the "
        "back door")


def test_the_module_says_a_batch_is_not_a_cost_formula():
    assert "paragraph 13" in batch_domain.SPECIFIC_IDENTIFICATION_NOT_A_COST_FORMULA
    report = batch_domain.expiry_report([_pos(date(2027, 1, 1))], as_of=AS_OF)
    assert any("does not change what the movement cost" in n for n in report.notes)


# ── 5. the detail position is the same total, one grain finer ───────────────

def _mv(item, qty, value, *, on="2026-01-01", godown=None, batch=None):
    return {"id": f"m{item}{qty}{value}{godown}{batch}",
            "service_catalogue_id": item, "movement_date": on,
            "quantity_delta": str(qty), "value_delta_paise": value,
            "godown_id": godown, "batch_id": batch}


def test_the_detail_total_is_the_item_total():
    """Two aggregates over one table that can disagree is how a register stops
    tying to its own ledger."""
    movements = [
        _mv("i1", 10, 1000, godown="g1", batch="b1"),
        _mv("i1", 5, 600, godown="g2"),
        _mv("i1", 3, 300),                       # before godowns existed
        _mv("i2", 7, 700, godown="g1"),
    ]
    coarse = sp.position(movements, "2026-12-31")
    fine = sp.position_detail(movements, "2026-12-31")
    assert coarse["total_value_paise"] == fine["total_value_paise"] == 2600
    assert len(fine["rows"]) == 4


def test_a_movement_with_no_godown_is_a_ROW_not_a_dropped_one():
    """Every movement before migration 398 has none, nothing is back-filled,
    and dropping them would make the detail sum to less than the total with
    nothing saying why."""
    fine = sp.position_detail([_mv("i1", 3, 300)], "2026-12-31")
    assert len(fine["rows"]) == 1
    assert fine["rows"][0]["godown_id"] is None
    assert fine["total_value_paise"] == 300


def test_the_detail_respects_the_as_at_date():
    movements = [_mv("i1", 10, 1000, on="2026-01-01", godown="g1"),
                 _mv("i1", 5, 500, on="2026-06-01", godown="g1")]
    assert sp.position_detail(movements, "2026-03-31")["total_value_paise"] == 1000


def test_the_same_item_in_two_godowns_is_two_rows():
    fine = sp.position_detail(
        [_mv("i1", 10, 1000, godown="g1"), _mv("i1", 4, 400, godown="g2")],
        "2026-12-31",
        godowns={"g1": {"name": "Bhiwandi"}, "g2": {"name": "Hosur"}})
    assert {r["godown_name"] for r in fine["rows"]} == {"Bhiwandi", "Hosur"}


def test_the_unallocated_sentence_says_nothing_was_backfilled():
    assert "back-filled" in loc.UNALLOCATED_MEANS
    assert "would assert they all happened there" in loc.UNALLOCATED_MEANS


# ── 6. the transfer itself ──────────────────────────────────────────────────

def _seed(db, *, gstins=("27AAACA1234A1Z5", "29AAACA1234A1Z2")):
    db.seed("godowns", {"id": "g1", "firm_id": FIRM, "client_id": CLIENT,
                        "name": "Bhiwandi", "state_code": "27",
                        "gstin": gstins[0], "is_default": True, "is_active": True})
    db.seed("godowns", {"id": "g2", "firm_id": FIRM, "client_id": CLIENT,
                        "name": "Hosur", "state_code": "29",
                        "gstin": gstins[1], "is_default": False, "is_active": True})
    db.seed("service_catalogue", {"id": "i1", "firm_id": FIRM, "client_id": CLIENT,
                                  "name": "Widget", "kind": "good", "unit": "NOS"})
    db.seed("inventory_stock_ledger", {
        "firm_id": FIRM, "client_id": CLIENT, "service_catalogue_id": "i1",
        "movement_date": "2026-01-01", "movement_type": "purchase",
        "quantity_delta": "100", "value_delta_paise": 10_000_00,
        "godown_id": "g1", "batch_id": None})


def test_a_transfer_writes_two_rows_that_net_to_nothing():
    """Within one entity the stock is worth what it was worth before it was
    carried across the yard, so every total that already ties still ties."""
    db = FakeDB()
    _seed(db)
    out = svc.transfer(db, firm_id=FIRM, client_id=CLIENT,
                       service_catalogue_id="i1", from_godown_id="g1",
                       to_godown_id="g2", quantity="40",
                       movement_date="2026-02-01")
    assert out["ok"] is True
    rows = db.rows("inventory_stock_ledger")
    assert len(rows) == 3
    assert sum(int(r["value_delta_paise"]) for r in rows) == 10_000_00
    moved = [r for r in rows if r.get("movement_type") == "transfer"]
    assert sum(int(r["value_delta_paise"]) for r in moved) == 0
    assert sum(Decimal(str(r["quantity_delta"])) for r in moved) == 0


def test_a_transfer_carries_the_ITEM_s_running_totals_forward_unchanged():
    """Two things at once, and the first was a real defect.

    `inventory_stock_ledger`'s three running columns are NOT NULL with no
    default, so omitting them is a write PostgREST rejects outright — which a
    `**spread` payload hid until the insert guard could read the columns.

    And unchanged is the RIGHT value rather than merely a value that satisfies
    the constraint: those columns are the ITEM's position chained in insertion
    order, and a transfer moves stock between two of the client's own shelves.
    The item's quantity, value and average cost are exactly what they were, so
    recomputing them would make the chain disagree with itself across a pair
    that nets to zero.
    """
    db = FakeDB()
    _seed(db)
    opening = db.rows("inventory_stock_ledger")[0]
    opening["running_qty_units"] = "100"
    opening["running_value_paise"] = 10_000_00
    opening["running_avg_cost_paise"] = 10_00

    svc.transfer(db, firm_id=FIRM, client_id=CLIENT, service_catalogue_id="i1",
                 from_godown_id="g1", to_godown_id="g2", quantity="40",
                 movement_date="2026-02-01")

    moved = [r for r in db.rows("inventory_stock_ledger")
             if r.get("movement_type") == "transfer"]
    assert len(moved) == 2
    for row in moved:
        for column in ("running_qty_units", "running_value_paise",
                       "running_avg_cost_paise"):
            assert row.get(column) is not None, (
                f"{column} is NOT NULL with no default — PostgREST rejects the "
                f"whole insert without it")
        assert str(row["running_qty_units"]) == "100"
        assert int(row["running_value_paise"]) == 10_000_00
        assert int(row["running_avg_cost_paise"]) == 10_00

    # And the movement's OWN rate on each row, not the item's blended average:
    # the transfer carries the source godown's cost, and two figures on one row
    # that do not multiply out is how a stock ledger stops being readable.
    for row in moved:
        rate = int(row["unit_cost_paise"])
        assert rate * abs(Decimal(str(row["quantity_delta"]))) == \
            abs(int(row["value_delta_paise"]))


def test_the_transfer_carries_the_SOURCE_godown_s_own_value():
    """Not the item's average across every location: taking the average would
    move a different number out than in where two godowns hold stock at
    different costs, and the per-godown position would drift from the total."""
    db = FakeDB()
    _seed(db)
    db.seed("inventory_stock_ledger", {
        "firm_id": FIRM, "client_id": CLIENT, "service_catalogue_id": "i1",
        "movement_date": "2026-01-01", "movement_type": "purchase",
        "quantity_delta": "100", "value_delta_paise": 50_000_00,
        "godown_id": "g2", "batch_id": None})
    out = svc.transfer(db, firm_id=FIRM, client_id=CLIENT,
                       service_catalogue_id="i1", from_godown_id="g1",
                       to_godown_id="g2", quantity="50",
                       movement_date="2026-02-01")
    # g1 holds 100 at ₹10,000, so half of it is ₹5,000 — NOT half of the
    # blended ₹30,000 average across both godowns.
    assert out["value_paise"] == 5_000_00


def test_a_transfer_out_of_a_godown_that_does_not_have_it_is_refused():
    db = FakeDB()
    _seed(db)
    out = svc.transfer(db, firm_id=FIRM, client_id=CLIENT,
                       service_catalogue_id="i1", from_godown_id="g2",
                       to_godown_id="g1", quantity="10",
                       movement_date="2026-02-01")
    assert out["ok"] is False and "does not have it" in out["refusal"]


def test_a_transfer_to_the_same_godown_is_refused():
    db = FakeDB()
    _seed(db)
    out = svc.transfer(db, firm_id=FIRM, client_id=CLIENT,
                       service_catalogue_id="i1", from_godown_id="g1",
                       to_godown_id="g1", quantity="10",
                       movement_date="2026-02-01")
    assert out["ok"] is False


def test_a_transfer_posts_no_journal():
    db = FakeDB()
    _seed(db)
    svc.transfer(db, firm_id=FIRM, client_id=CLIENT, service_catalogue_id="i1",
                 from_godown_id="g1", to_godown_id="g2", quantity="10",
                 movement_date="2026-02-01")
    assert db.rows("journal_entries") == []


def test_the_transfer_answer_carries_the_supply_decision():
    db = FakeDB()
    _seed(db)
    out = svc.transfer(db, firm_id=FIRM, client_id=CLIENT,
                       service_catalogue_id="i1", from_godown_id="g1",
                       to_godown_id="g2", quantity="10",
                       movement_date="2026-02-01")
    assert out["decision"]["is_supply"] is True


def test_a_godown_from_another_firm_is_not_reachable():
    db = FakeDB()
    _seed(db)
    for row in db.rows("godowns"):
        row["firm_id"] = "other-firm"
    out = svc.transfer(db, firm_id=FIRM, client_id=CLIENT,
                       service_catalogue_id="i1", from_godown_id="g1",
                       to_godown_id="g2", quantity="10",
                       movement_date="2026-02-01")
    assert out["ok"] is False


def test_closing_a_godown_that_still_holds_stock_is_refused():
    """Moving it automatically would invent a transfer nobody made — and
    between two registrations that transfer is a supply."""
    db = FakeDB()
    _seed(db)
    out = svc.close_godown(db, firm_id=FIRM, client_id=CLIENT, godown_id="g1")
    assert out["ok"] is False and "still holds stock" in out["refusal"]


def test_an_empty_godown_closes():
    db = FakeDB()
    _seed(db)
    out = svc.close_godown(db, firm_id=FIRM, client_id=CLIENT, godown_id="g2")
    assert out["ok"] is True
    assert db.rows("godowns")[1]["is_active"] is False


def test_marking_a_new_default_clears_the_old_one():
    """Migration 398's partial unique index enforces one; clearing it here
    means a CA marking a new warehouse gets that one rather than a constraint
    violation."""
    db = FakeDB()
    _seed(db)
    svc.create_godown(db, firm_id=FIRM, client_id=CLIENT, name="Nagpur",
                      code=None, address=None, state_code="27", gstin=None,
                      is_default=True, notes=None, actor_id=None)
    defaults = [g for g in db.rows("godowns") if g.get("is_default")]
    assert [g["name"] for g in defaults] == ["Nagpur"]


def test_the_movement_type_a_transfer_writes_is_ADMITTED_by_the_column():
    """A THREE-SECOND TRIPWIRE FOR A THIRTY-SIX-MINUTE FAILURE.

    `inventory_stock_ledger.movement_type` carries a CHECK, and the first
    version of the transfer wrote 'transfer' into a constraint that did not
    admit it — so Postgres rejected both rows outright. Mock mode enforces no
    CHECK, so every test in this module passed and the whole feature was
    broken in production.

    `tests/test_status_vocabularies_pg.py` is the AUTHORITY and caught it, by
    reading the live constraint. It needs a real database and the full
    real-Postgres suite takes about half an hour. This reads the migrations
    instead — the same question, asked where the answer is cheap. It is a
    tripwire and not a second authority: if the two ever disagree, the one
    talking to Postgres is right.
    """
    import re
    from pathlib import Path

    API = Path(__file__).resolve().parents[1]
    # ROLLBACKS EXCLUDED: 398's rollback correctly narrows the list back
    # to 191's, and reading it as the definition in force inverts the
    # answer — which is exactly what the first draft of this test did.
    migrations = sorted(x for x in (API / "migrations").glob("[0-9][0-9][0-9]_*.sql")
                        if not x.name.endswith("_rollback.sql"))
    last = None
    for path in migrations:
        text = path.read_text()
        if "inventory_stock_ledger_movement_type_check" in text and "ADD CONSTRAINT" in text:
            last = (path, text)
    assert last, "no migration defines the movement_type CHECK"
    path, text = last
    # The final ADD CONSTRAINT in that file is the definition in force.
    block = text[text.rindex("inventory_stock_ledger_movement_type_check"):]
    admitted = set(re.findall(r"'([a-z_]+)'", block))
    assert "transfer" in admitted, (
        f"{path.name} is the last migration to define "
        f"inventory_stock_ledger_movement_type_check and its list does not "
        f"admit 'transfer' — Postgres will reject every godown transfer. "
        f"Admitted: {sorted(admitted)}")
    # And the service must still be writing that value, not a renamed one.
    service = (API / "services" / "inventory_location_service.py").read_text()
    assert '"movement_type": "transfer"' in service
