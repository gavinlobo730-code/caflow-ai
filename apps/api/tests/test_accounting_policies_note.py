"""
Significant Accounting Policies — Schedule III, Division I, General Instructions.

The notes must disclose the entity's significant accounting policies, and there
was no such note at all: the generated set went straight to Fixed Assets.

Most policies are the CA's JUDGEMENTS and the system has no basis for asserting
them. Two are facts about how these books were kept rather than opinions about
them, and only those are stated:

  * depreciation — read off each row's fixed_assets.depreciation_method
  * inventory — the cost formula (AS-2 paragraph 14) that priced THE YEAR'S stock movements, read from the
    stamp every stock-ledger row carries (migration 394). It was "moving average, by construction" until FIFO
    became a client policy; POST-A-108 is the second half of that change, and the cases at the end of this
    file are its statement.

Everything else is named as outstanding. This follows the pattern task #240
established for gst_tds: an honest placeholder, never a plausible-looking
fabricated number — and a policies note is the worst place to invent text,
because it reads as boilerplate, nobody re-reads it, and it ends up attached to
a filed AOC-4 asserting a policy the client does not follow.
"""
import inspect

import pytest

import routers.year_end_notes as yen
from domain.inventory import costing
from services import inventory_location_service as locsvc
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "firm-1"
CLIENT = "client-1"
USER = {"id": "u1", "firm_id": FIRM, "role": "Partner",
        "email": "p@f.test", "auth_user_id": "auth-1"}


@pytest.fixture
def db(monkeypatch):
    import routers.year_end as year_end_mod
    d = FakeDB()
    wire_e2e(monkeypatch, d, [yen, year_end_mod])
    monkeypatch.setattr(yen, "_USE_MOCK", False)
    # _assert_engagement_scope lives in routers.year_end and is called by name
    # from routers.year_end_notes; its OWN _USE_MOCK governs which branch it
    # takes, independently of this module's, so it has to be flipped here too
    # or the resolver reads the (empty) in-memory mock store instead of FakeDB.
    # Same trap documented in test_r3_8_year_end_review_workflow.
    monkeypatch.setattr(year_end_mod, "_USE_MOCK", False)
    d.seed("clients", {"id": CLIENT, "firm_id": FIRM,
                       "entity_type": "Private Limited"})
    return d


def _policies(db):
    return yen._compute_accounting_policies_data(db, FIRM, CLIENT, "2025-03-31")


# ── What the books actually say ──────────────────────────────────────────────

def test_the_depreciation_method_is_read_off_the_register():
    """Not assumed. The Fixed Assets note used to assert "Written Down Value
    method" as flat text for every client, which is false for any client whose
    assets are on straight line."""
    d = FakeDB()
    d.seed("clients", {"id": CLIENT, "firm_id": FIRM, "entity_type": "Private Limited"})
    for i in range(3):
        d.seed("fixed_assets", {"id": f"a{i}", "firm_id": FIRM, "client_id": CLIENT,
                                "is_disposed": False, "depreciation_method": "SL"})
    data = yen._compute_accounting_policies_data(d, FIRM, CLIENT, "2025-03-31")
    assert data["has_fixed_assets"] is True
    assert data["depreciation_methods"] == ["SL"]
    assert "Straight Line" in yen._accounting_policies_text(data)
    assert "Written Down Value" not in yen._accounting_policies_text(data)


def test_a_register_using_both_methods_says_so_rather_than_picking_one():
    """Mixed methods within one register are legitimate, and a CA should see it
    at a glance rather than have one silently chosen for the disclosure."""
    d = FakeDB()
    d.seed("clients", {"id": CLIENT, "firm_id": FIRM, "entity_type": "Private Limited"})
    d.seed("fixed_assets", {"id": "a1", "firm_id": FIRM, "client_id": CLIENT,
                            "is_disposed": False, "depreciation_method": "SL"})
    d.seed("fixed_assets", {"id": "a2", "firm_id": FIRM, "client_id": CLIENT,
                            "is_disposed": False, "depreciation_method": "WDV"})
    data = yen._compute_accounting_policies_data(d, FIRM, CLIENT, "2025-03-31")
    assert data["depreciation_methods"] == ["SL", "WDV"]
    text = yen._accounting_policies_text(data)
    assert "more than one method" in text
    assert "Straight Line" in text and "Written Down Value" in text


def test_no_fixed_assets_means_no_depreciation_policy_is_stated():
    """A service business with no register gets no depreciation policy at all.
    Stating one would disclose a basis for assets that do not exist."""
    d = FakeDB()
    d.seed("clients", {"id": CLIENT, "firm_id": FIRM, "entity_type": "Private Limited"})
    data = yen._compute_accounting_policies_data(d, FIRM, CLIENT, "2025-03-31")
    assert data["has_fixed_assets"] is False
    assert "Depreciation" not in yen._accounting_policies_text(data)


def test_inventory_is_stated_only_for_a_stock_tracked_client():
    """A client that tracks stock is told which cost formula priced its stock (a client with nothing recorded
    is on the moving average, the only formula there was). For one that does not track stock, the policy is
    omitted rather than stated as nil."""
    d = FakeDB()
    d.seed("clients", {"id": CLIENT, "firm_id": FIRM, "entity_type": "Private Limited"})
    assert "Inventories" not in yen._accounting_policies_text(
        yen._compute_accounting_policies_data(d, FIRM, CLIENT, "2025-03-31"))

    d.seed("service_catalogue", {"id": "s1", "firm_id": FIRM, "client_id": CLIENT,
                                 "kind": "good"})
    data = yen._compute_accounting_policies_data(d, FIRM, CLIENT, "2025-03-31")
    assert data["inventory_is_stock_tracked"] is True
    assert data["inventory_valuation_basis"] == "moving average"
    assert "moving average" in yen._accounting_policies_text(data)


def test_a_services_only_catalogue_does_not_make_it_stock_tracked():
    d = FakeDB()
    d.seed("clients", {"id": CLIENT, "firm_id": FIRM, "entity_type": "Private Limited"})
    d.seed("service_catalogue", {"id": "s1", "firm_id": FIRM, "client_id": CLIENT,
                                 "kind": "service"})
    data = yen._compute_accounting_policies_data(d, FIRM, CLIENT, "2025-03-31")
    assert data["inventory_is_stock_tracked"] is False


def test_a_foreign_currency_policy_is_required_only_when_there_are_such_entries():
    """Multi-currency is dormant for most clients (migration 147 defaults
    txn_currency to INR), so this normally stays off the list."""
    # txn_currency lives on journal_LINES, not journal_entries — migration 147
    # puts it on the leg because the rate is frozen per leg. Reading it off the
    # entry returns nothing and reports "no foreign currency" for every client;
    # tests/test_backend_columns_exist_pg caught exactly that.
    d = FakeDB()
    d.seed("clients", {"id": CLIENT, "firm_id": FIRM, "entity_type": "Private Limited"})
    data = yen._compute_accounting_policies_data(d, FIRM, CLIENT, "2025-03-31")
    assert data["has_foreign_currency_transactions"] is False
    assert not any("Foreign currency" in p for p in data["ca_input_required"])


# ── What the system must NOT assert ──────────────────────────────────────────

def test_the_judgement_policies_are_named_as_outstanding_never_filled_in():
    """Revenue recognition, employee benefits, provisions, taxes on income and
    borrowing costs are the CA's assertions about the entity. Pre-filling them
    with boilerplate is the failure mode this note is most exposed to."""
    d = FakeDB()
    d.seed("clients", {"id": CLIENT, "firm_id": FIRM, "entity_type": "Private Limited"})
    data = yen._compute_accounting_policies_data(d, FIRM, CLIENT, "2025-03-31")
    outstanding = data["ca_input_required"]
    for policy in ("Revenue recognition", "Employee benefits",
                   "Taxes on income, including deferred tax", "Borrowing costs"):
        assert policy in outstanding
    text = yen._accounting_policies_text(data)
    assert "require the CA's input" in text
    assert "deliberately left blank rather than pre-filled" in text


def test_the_note_always_requires_ca_review():
    """Even the derived policies are a starting point the CA confirms, not a
    disclosure the software makes on their behalf."""
    d = FakeDB()
    d.seed("clients", {"id": CLIENT, "firm_id": FIRM, "entity_type": "Private Limited"})
    d.seed("fixed_assets", {"id": "a1", "firm_id": FIRM, "client_id": CLIENT,
                            "is_disposed": False, "depreciation_method": "WDV"})
    assert yen._compute_accounting_policies_data(
        d, FIRM, CLIENT, "2025-03-31")["requires_ca_review"] is True


def test_unavailable_books_do_not_invent_policies():
    data = yen._compute_accounting_policies_data(None, FIRM, CLIENT, "2025-03-31")
    assert data["depreciation_methods"] == []
    assert data["requires_ca_review"] is True
    assert "requires the CA's input" in data["review_note"]


# ── Position and numbering ───────────────────────────────────────────────────

def test_policies_is_the_first_note(db):
    db.seed("year_end_engagements", {"id": "E1", "firm_id": FIRM, "client_id": CLIENT,
                                     "financial_year": "2024-25", "status": "draft",
                                     "fy_start": "2024-04-01", "fy_end": "2025-03-31"})
    notes = yen.generate_notes("E1", current_user=USER)["data"]
    assert notes[0]["note_type"] == "accounting_policies"
    assert notes[0]["sequence_no"] == 1
    assert notes[0]["title"].startswith("Note 1 — Significant Accounting Policies")


def test_every_note_is_numbered_by_its_position(db):
    """Each title used to hardcode its own number, so inserting a note ahead of
    them left "Note 1 — Fixed Assets" sitting at sequence 2 — and the note
    references on the face of the statements pointing at the wrong note."""
    db.seed("year_end_engagements", {"id": "E2", "firm_id": FIRM, "client_id": CLIENT,
                                     "financial_year": "2024-25", "status": "draft",
                                     "fy_start": "2024-04-01", "fy_end": "2025-03-31"})
    notes = yen.generate_notes("E2", current_user=USER)["data"]
    for note in notes:
        assert note["title"].startswith(f"Note {note['sequence_no']} — "), note["title"]
    assert [n["sequence_no"] for n in notes] == list(range(1, len(notes) + 1))


def test_the_fixed_assets_note_no_longer_asserts_a_depreciation_method(db):
    """It said "Depreciation is provided on Written Down Value method" for
    every client. The basis belongs to the policies note, derived from the
    register — and stating it in two places is how the two come to disagree."""
    db.seed("year_end_engagements", {"id": "E3", "firm_id": FIRM, "client_id": CLIENT,
                                     "financial_year": "2024-25", "status": "draft",
                                     "fy_start": "2024-04-01", "fy_end": "2025-03-31"})
    notes = yen.generate_notes("E3", current_user=USER)["data"]
    fa = next(n for n in notes if n["note_type"] == "fixed_assets")
    assert "Written Down Value" not in fa["content"]
    assert "Significant Accounting Policies note" in fa["content"]


# ═════════════════════════════════════════════════════════════════════════════
# INVENTORY — which cost formula priced THIS YEAR's movements (POST-A-108)
#
# The note said "valued on the moving average cost basis" for every client with a
# goods item, and its docstring said that was "by construction and not as a
# configurable option". Both stopped being true with migration 394 (INV-02): FIFO
# is a client policy, every stock-ledger row is stamped with the formula that
# priced it, and a note describing a FIFO client's closing stock as moving
# average puts a false accounting policy on a signed balance sheet.
# ═════════════════════════════════════════════════════════════════════════════

FY_START, FY_END = "2025-04-01", "2026-03-31"
MOVING_AVERAGE_SENTENCE = ("Inventories — valued on the moving average cost basis, which is how "
                           "stock movements are costed in these books.")
CHANGE_INPUT = "Effect of the change in the inventory cost formula (AS-5 paragraph 32)"
FORMULA_INPUT = "Inventory cost formula (AS-2 paragraph 14)"


class SpyDB(FakeDB):
    """Remembers every query made on the stock ledger, so a test can say how many and how wide."""

    def __init__(self):
        super().__init__()
        self.ledger_queries = []

    def table(self, name):
        q = super().table(name)
        if name == "inventory_stock_ledger":
            self.ledger_queries.append(q)
        return q


def _goods_client(recorded=None, db=None, with_client_row=True):
    d = db or SpyDB()
    if with_client_row:
        d.seed("clients", {"id": CLIENT, "firm_id": FIRM, "entity_type": "Private Limited",
                           "inventory_costing_method": recorded})
    d.seed("service_catalogue", {"id": "s1", "firm_id": FIRM, "client_id": CLIENT, "kind": "good"})
    return d


def _moved(d, method, date, client=CLIENT, firm=FIRM):
    d.seed("inventory_stock_ledger", {"firm_id": firm, "client_id": client, "costing_method": method,
                                      "movement_date": date})


def _year(d, fy_start=FY_START):
    data = yen._compute_accounting_policies_data(d, FIRM, CLIENT, FY_END, fy_start=fy_start)
    return data, yen._accounting_policies_text(data)


def test_fy_start_is_keyword_only_so_every_existing_four_argument_caller_still_works():
    param = inspect.signature(yen._compute_accounting_policies_data).parameters["fy_start"]
    assert param.kind is inspect.Parameter.KEYWORD_ONLY and param.default is None


def test_the_functions_docstring_no_longer_claims_the_formula_is_not_configurable():
    assert "not as a configurable option" not in yen._compute_accounting_policies_data.__doc__


def test_the_two_wordings_cover_every_formula_AS_2_permits_and_nothing_else():
    """A formula added to costing.METHODS must arrive here with its words, or this fails; a missing entry
    would otherwise be a note that quietly describes the weighted average."""
    assert set(yen._INVENTORY_SENTENCE) == set(costing.METHODS)
    assert set(yen._INVENTORY_BASIS_NAME) == set(costing.METHODS)
    assert len(set(yen._INVENTORY_SENTENCE.values())) == len(costing.METHODS)


@pytest.mark.parametrize("recorded", [None, "moving_average"])
def test_the_moving_average_sentence_is_unchanged_for_a_client_on_it(recorded):
    """Regression pin of the exact text, with and without the ledger to confirm it, and with nothing recorded."""
    for seed_ledger, fy_start in ((False, FY_START), (True, FY_START), (False, None)):
        d = _goods_client(recorded)
        if seed_ledger:
            _moved(d, costing.MOVING_AVERAGE, "2025-06-10")
        data, text = _year(d, fy_start)
        assert MOVING_AVERAGE_SENTENCE in text, (recorded, seed_ledger, fy_start)
        assert data["inventory_valuation_basis"] == "moving average"
        assert data["inventory_cost_formula"] == costing.MOVING_AVERAGE
        assert FORMULA_INPUT not in data["ca_input_required"]
    # With nothing recorded at all it is a fact about the books and carries no caveat (costing.UNRECORDED_MEANS).
    if recorded is None:
        assert "currently recorded" not in _year(_goods_client(None))[1]


def test_a_fifo_client_whose_year_was_costed_on_fifo_is_told_so_and_not_called_moving_average():
    d = _goods_client("fifo")
    _moved(d, costing.FIFO, "2025-05-02")
    _moved(d, costing.FIFO, "2026-01-20")
    data, text = _year(d)
    assert data["inventory_valuation_basis"] == "first-in, first-out"
    assert data["inventory_cost_formula"] == costing.FIFO and data["inventory_cost_formula_source"] == "ledger"
    assert "first-in, first-out (FIFO)" in text and "AS-2 paragraph 14" in text
    assert "moving average" not in text
    assert "currently recorded" not in text           # the ledger confirms it, so there is nothing to caveat
    assert data["inventory_cost_formula_change"] is None
    assert FORMULA_INPUT not in data["ca_input_required"] and CHANGE_INPUT not in data["ca_input_required"]


@pytest.mark.parametrize("method", costing.METHODS)
def test_the_note_names_the_formula_the_ledger_says_for_every_formula_there_is(method):
    """The rule, over the whole vocabulary: whichever formula the year's rows carry is the one stated, and no
    other formula's wording appears."""
    d = _goods_client(method)
    _moved(d, method, "2025-07-01")
    data, text = _year(d)
    assert data["inventory_cost_formula"] == method
    assert yen._INVENTORY_SENTENCE[method] in text
    for other in set(costing.METHODS) - {method}:
        assert yen._INVENTORY_BASIS_NAME[other] not in text
        assert yen._INVENTORY_SENTENCE[other] not in text


def test_a_change_during_the_year_is_stated_with_its_dates_and_the_effect_is_left_to_the_ca():
    """AS-5 paragraphs 29 and 32: a change of accounting policy is disclosed, with its effect. The effect is a
    figure no ledger holds, so it is named and not computed."""
    d = _goods_client("fifo")
    for date in ("2025-04-10", "2025-08-14", "2025-09-20"):
        _moved(d, costing.MOVING_AVERAGE, date)
    for date in ("2025-10-01", "2026-01-05", "2026-03-15"):
        _moved(d, costing.FIFO, date)
    data, text = _year(d)
    change = data["inventory_cost_formula_change"]
    assert change == {"formulas": [costing.MOVING_AVERAGE, costing.FIFO],
                      "last_movement_on_earlier_formula": "2025-09-20",
                      "first_movement_on_later_formula": "2025-10-01", "interleaved": False}
    assert data["inventory_valuation_basis"] == "moving average, then first-in, first-out"
    assert "changed during the year" in text and "AS-5 paragraphs 29 and 32" in text
    assert "20-09-2025" in text and "01-10-2025" in text
    assert "no earlier period has been re-costed" in text and "requires the CA's input" in text
    assert CHANGE_INPUT in data["ca_input_required"]
    assert "Rs" not in text, "the effect of the change is not a number this module may invent"


def test_documents_dated_either_side_of_the_change_are_flagged_and_no_date_is_claimed():
    d = _goods_client("fifo")
    for date in ("2025-04-10", "2025-11-20"):          # a back-dated document costed before the switch
        _moved(d, costing.MOVING_AVERAGE, date)
    for date in ("2025-10-01", "2025-12-05"):
        _moved(d, costing.FIFO, date)
    data, text = _year(d)
    assert data["inventory_cost_formula_change"]["interleaved"] is True
    assert "overlap" in text and "cannot be read from the ledger" in text
    assert "dated up to" not in text, "a change date was claimed over a ledger that does not give one"
    assert CHANGE_INPUT in data["ca_input_required"]


def test_a_formula_switched_after_the_year_end_describes_the_year_by_its_own_formula():
    """The client row is TODAY's policy. The ledger says what priced the year, and where they differ the note
    says so instead of stating either silently."""
    d = _goods_client("fifo")                                    # switched on 01-04-2026 ...
    _moved(d, costing.MOVING_AVERAGE, "2025-12-01")              # ... so the year was costed on the weighted average
    data, text = _year(d)
    assert data["inventory_cost_formula"] == costing.MOVING_AVERAGE
    assert MOVING_AVERAGE_SENTENCE in text
    assert "now recorded for this client is first-in, first-out" in text
    assert "confirm the date from which it applies" in text


def test_a_fifo_client_with_no_movement_in_the_year_is_stated_as_recorded_and_says_that_is_all_it_is():
    d = _goods_client("fifo")
    data, text = _year(d)
    assert data["inventory_cost_formula"] == costing.FIFO and data["inventory_cost_formula_source"] == "recorded"
    assert yen._INVENTORY_SENTENCE[costing.FIFO] in text
    assert "currently recorded for the client" in text and "not been confirmed against a stock movement" in text


def test_a_year_that_is_not_known_states_the_recorded_formula_with_the_same_caveat():
    d = _goods_client("fifo")
    _moved(d, costing.FIFO, "2025-06-01")
    data, text = _year(d, fy_start=None)
    assert data["inventory_cost_formula"] == costing.FIFO and data["inventory_cost_formula_source"] == "recorded"
    assert "currently recorded for the client" in text
    assert d.ledger_queries == [], "no year, no ledger read"


def test_movements_outside_the_year_are_not_the_years_formula():
    d = _goods_client(None)
    _moved(d, costing.MOVING_AVERAGE, "2025-09-01")
    _moved(d, costing.FIFO, "2025-03-31")                    # the day before the year
    _moved(d, costing.FIFO, "2026-04-01")                    # the day after it
    data, text = _year(d)
    assert data["inventory_cost_formula"] == costing.MOVING_AVERAGE and data["inventory_cost_formula_change"] is None
    assert "first-in, first-out" not in text


def test_the_first_and_last_day_of_the_year_are_inside_it():
    d = _goods_client("fifo")
    _moved(d, costing.MOVING_AVERAGE, FY_START)
    _moved(d, costing.FIFO, FY_END)
    data, _ = _year(d)
    assert data["inventory_cost_formula_change"]["formulas"] == [costing.MOVING_AVERAGE, costing.FIFO]


def test_another_clients_or_another_firms_movements_are_not_this_clients_formula():
    d = _goods_client(None)
    _moved(d, costing.MOVING_AVERAGE, "2025-09-01")
    _moved(d, costing.FIFO, "2025-09-02", client="client-2")
    _moved(d, costing.FIFO, "2025-09-03", firm="firm-2")
    data, _ = _year(d)
    assert data["inventory_cost_formula"] == costing.MOVING_AVERAGE and data["inventory_cost_formula_change"] is None


class _Down(SpyDB):
    """A database where the named table cannot be read."""

    def __init__(self, broken):
        super().__init__()
        self._broken = broken

    def table(self, name):
        if name == self._broken:
            raise RuntimeError(f"{name} is unreachable")
        return super().table(name)


def test_a_stock_ledger_that_cannot_be_read_asserts_no_formula_and_puts_it_on_the_cas_list(monkeypatch):
    soft = []
    monkeypatch.setattr(yen, "capture_soft_failure", lambda exc, *, operation, **ctx: soft.append(operation))
    d = _goods_client("fifo", db=_Down("inventory_stock_ledger"))
    data, text = _year(d)
    assert data["inventory_cost_formula"] is None and data["inventory_valuation_basis"] is None
    assert data["inventory_cost_formula_unreadable"] is True
    assert "moving average" not in text and "first-in, first-out" not in text
    assert "requires the CA's input" in text
    assert FORMULA_INPUT in data["ca_input_required"]
    assert "accounting_policies.inventory_formula" in soft


def test_a_client_row_that_cannot_be_read_does_not_get_a_formula_guessed_for_it(monkeypatch):
    monkeypatch.setattr(yen, "capture_soft_failure", lambda *a, **k: None)
    d = _goods_client("fifo", db=_Down("clients"), with_client_row=False)
    data, text = _year(d)
    assert data["inventory_cost_formula"] is None
    assert FORMULA_INPUT in data["ca_input_required"]
    assert "moving average" not in text


def test_a_client_row_that_cannot_be_read_still_gets_the_years_formula_from_the_ledger(monkeypatch):
    monkeypatch.setattr(yen, "capture_soft_failure", lambda *a, **k: None)
    d = _goods_client(None, db=_Down("clients"), with_client_row=False)
    _moved(d, costing.FIFO, "2025-06-01")
    data, _ = _year(d)
    assert data["inventory_cost_formula"] == costing.FIFO and data["inventory_recorded_cost_formula"] is None


def test_the_ledger_is_read_in_single_rows_and_never_in_volume():
    """What crosses the wire is proportional to the answer: one row per formula for its first date, and one more
    each for the last date only when two formulas appear."""
    one = _goods_client(None)
    for i in range(50):
        _moved(one, costing.MOVING_AVERAGE, f"2025-06-{(i % 28) + 1:02d}")
    _year(one)
    assert len(one.ledger_queries) == len(costing.METHODS)

    two = _goods_client("fifo")
    for i in range(20):
        _moved(two, costing.MOVING_AVERAGE, f"2025-06-{(i % 28) + 1:02d}")
        _moved(two, costing.FIFO, f"2025-12-{(i % 28) + 1:02d}")
    _year(two)
    assert len(two.ledger_queries) == 2 * len(costing.METHODS)
    for q in one.ledger_queries + two.ledger_queries:
        assert q._limit == 1


def test_a_client_that_tracks_no_stock_never_touches_the_ledger():
    d = SpyDB()
    d.seed("clients", {"id": CLIENT, "firm_id": FIRM, "entity_type": "Private Limited",
                       "inventory_costing_method": "fifo"})
    data, text = _year(d)
    assert d.ledger_queries == [] and "Inventories" not in text
    assert data["inventory_cost_formula"] is None


def test_generate_notes_hands_the_engagements_own_year_to_the_policies_note(db):
    """The wiring: the engagement's fy_start and fy_end are the window, so a FIFO client's generated note says
    FIFO and a movement outside that engagement's year does not change it."""
    db.seed("clients", {"id": "client-fifo", "firm_id": FIRM, "entity_type": "Private Limited",
                        "inventory_costing_method": "fifo"})
    db.seed("service_catalogue", {"id": "g1", "firm_id": FIRM, "client_id": "client-fifo", "kind": "good"})
    _moved(db, costing.FIFO, "2025-09-01", client="client-fifo")
    _moved(db, costing.MOVING_AVERAGE, "2024-09-01", client="client-fifo")      # the PREVIOUS year
    db.seed("year_end_engagements", {"id": "E9", "firm_id": FIRM, "client_id": "client-fifo",
                                     "financial_year": "2025-26", "status": "draft",
                                     "fy_start": FY_START, "fy_end": FY_END})
    notes = yen.generate_notes("E9", current_user=USER)["data"]
    policies = next(n for n in notes if n["note_type"] == "accounting_policies")
    assert "first-in, first-out (FIFO)" in policies["content"]
    assert "changed during the year" not in policies["content"]
    assert policies["note_data"]["inventory_cost_formula"] == costing.FIFO


# ═════════════════════════════════════════════════════════════════════════════
# A GODOWN TRANSFER PRICES NOTHING, AND A FIFO CLIENT WITH ONE HAS NOT CHANGED ITS FORMULA
#
# `inventory_stock_ledger.costing_method` is NOT NULL DEFAULT 'moving_average' (migration 394) and the transfer
# writer did not stamp it, so a FIFO client's transfer row read as a movement priced on the weighted average.
# The note counted every row, and a signed Significant Accounting Policies note announced a change of accounting
# policy (AS-5 paragraphs 29 and 32) that never happened. The fixtures above stamp every row by hand through
# `_moved`, which is why none of them could see it: these drive the REAL writer, on a double that supplies the
# column default the way Postgres does (tests/e2e_harness `_DEFAULTS`).
# ═════════════════════════════════════════════════════════════════════════════

def _seed_two_godowns_under_one_registration(d):
    for gid, name, default in (("g1", "Bhiwandi", True), ("g2", "Pune", False)):
        d.seed("godowns", {"id": gid, "firm_id": FIRM, "client_id": CLIENT, "name": name, "state_code": "27",
                           "gstin": "27AAACA1234A1Z5", "is_default": default, "is_active": True})


def _fifo_stock_in_godown(d, on, method=costing.FIFO):
    """A stamped purchase and a stamped sale: what `domain/inventory_service` writes, which does stamp."""
    d.seed("inventory_stock_ledger", {
        "firm_id": FIRM, "client_id": CLIENT, "service_catalogue_id": "s1", "movement_type": "purchase",
        "movement_date": on, "quantity_delta": "100", "value_delta_paise": 10_000_00, "godown_id": "g1",
        "batch_id": None, "costing_method": method,
        "running_qty_units": "100", "running_value_paise": 10_000_00, "running_avg_cost_paise": 100_00})
    d.seed("inventory_stock_ledger", {
        "firm_id": FIRM, "client_id": CLIENT, "service_catalogue_id": "s1", "movement_type": "sale",
        "movement_date": "2026-03-20", "quantity_delta": "-5", "value_delta_paise": -500_00, "godown_id": "g1",
        "batch_id": None, "costing_method": method,
        "running_qty_units": "95", "running_value_paise": 9_500_00, "running_avg_cost_paise": 100_00})


def _transfer(d, on):
    out = locsvc.transfer(d, firm_id=FIRM, client_id=CLIENT, service_catalogue_id="s1", from_godown_id="g1",
                          to_godown_id="g2", quantity="10", movement_date=on)
    assert out["ok"] is True, out
    return out


@pytest.mark.parametrize("transfer_on", [
    "2025-04-01",     # the day of the first FIFO movement
    "2025-09-15",     # inside the FIFO span: used to read as documents dated either side of a change
    "2026-03-31",     # after the last FIFO movement: used to read as a clean change, with both dates
])
def test_a_fifo_client_with_a_godown_transfer_in_the_year_has_not_changed_its_cost_formula(transfer_on):
    d = _goods_client("fifo")
    _seed_two_godowns_under_one_registration(d)
    _fifo_stock_in_godown(d, FY_START)
    _transfer(d, transfer_on)

    moved = [r for r in d.rows("inventory_stock_ledger") if r.get("movement_type") == "transfer"]
    assert len(moved) == 2, "the writer under test must really have written the transfer"
    data, text = _year(d)
    assert data["inventory_cost_formula"] == costing.FIFO and data["inventory_cost_formula_source"] == "ledger"
    assert data["inventory_cost_formula_change"] is None
    assert data["inventory_valuation_basis"] == "first-in, first-out"
    assert yen._INVENTORY_SENTENCE[costing.FIFO] in text
    for claimed in ("changed during the year", "overlap", "moving average", "AS-5"):
        assert claimed not in text, claimed
    assert CHANGE_INPUT not in data["ca_input_required"] and FORMULA_INPUT not in data["ca_input_required"]


@pytest.mark.parametrize("recorded, expected", [
    (None, costing.MOVING_AVERAGE), ("moving_average", costing.MOVING_AVERAGE), ("fifo", costing.FIFO)])
def test_the_transfer_writer_stamps_both_rows_with_the_formula_in_force(recorded, expected):
    d = _goods_client(recorded)
    _seed_two_godowns_under_one_registration(d)
    _fifo_stock_in_godown(d, FY_START, method=expected)
    _transfer(d, "2025-09-15")
    moved = [r for r in d.rows("inventory_stock_ledger") if r.get("movement_type") == "transfer"]
    assert [r["costing_method"] for r in moved] == [expected, expected]


def test_a_transfer_already_on_file_carrying_the_column_default_is_not_counted_either():
    """Nothing back-fills the transfers written before the writer stamped. They sit in a FIFO client's ledger
    as 'moving_average', and the note reads by movement type, so history is protected as well as new rows."""
    d = _goods_client("fifo")
    _moved(d, costing.FIFO, "2025-05-02")
    _moved(d, costing.FIFO, "2026-01-20")
    for date in ("2025-09-15", "2026-03-31"):
        d.seed("inventory_stock_ledger", {"firm_id": FIRM, "client_id": CLIENT, "movement_type": "transfer",
                                          "costing_method": costing.MOVING_AVERAGE, "movement_date": date})
    data, text = _year(d)
    assert data["inventory_cost_formula"] == costing.FIFO and data["inventory_cost_formula_change"] is None
    assert "changed during the year" not in text and "moving average" not in text


def test_a_legacy_transfer_does_not_move_the_dates_of_a_change_that_really_happened():
    """The last-date read is filtered too: a transfer entered after a genuine switch, still carrying the old
    formula's default, used to push 'the last movement on the earlier formula' past the switch and turn a clean
    change into an overlapping one."""
    d = _goods_client("fifo")
    for date in ("2025-04-10", "2025-09-20"):
        _moved(d, costing.MOVING_AVERAGE, date)
    for date in ("2025-10-01", "2026-03-15"):
        _moved(d, costing.FIFO, date)
    d.seed("inventory_stock_ledger", {"firm_id": FIRM, "client_id": CLIENT, "movement_type": "transfer",
                                      "costing_method": costing.MOVING_AVERAGE, "movement_date": "2026-01-15"})
    change = _year(d)[0]["inventory_cost_formula_change"]
    assert change == {"formulas": [costing.MOVING_AVERAGE, costing.FIFO],
                      "last_movement_on_earlier_formula": "2025-09-20",
                      "first_movement_on_later_formula": "2025-10-01", "interleaved": False}


def test_only_movements_no_formula_priced_are_left_out_and_a_row_without_a_type_still_counts():
    """The skip is by movement type and not by anything looser: a row that lacks the key (every `_moved`
    fixture, and any legacy shape) is read as priced, the direction that cannot hide a real change."""
    assert costing.MOVEMENT_TYPES_THAT_PRICE_NOTHING == ("transfer",)
    d = _goods_client(None)
    _moved(d, costing.MOVING_AVERAGE, "2025-09-01")
    d.seed("inventory_stock_ledger", {"firm_id": FIRM, "client_id": CLIENT, "movement_type": "sale",
                                      "costing_method": costing.FIFO, "movement_date": "2025-12-01"})
    assert _year(d)[0]["inventory_cost_formula_change"] is not None
