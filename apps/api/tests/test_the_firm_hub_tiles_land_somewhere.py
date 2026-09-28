"""A hub tile with a figure has somewhere to go, and the queue behind it agrees
with the number on it (D22, question G3).

THREE PLACES COMPUTE "WHAT IS OUTSTANDING ON THIS TILE" and they must say the
same thing, or a CA clicks 7 and counts 5:

  * `services/hub_service._signals`  — the FIGURE on the tile
  * `services/hub_worklist_service._POPULATION` — the mock-mode twin of the queue
  * the LAST migration defining `hub_client_worklist` — what production runs
    for the queue (416, then 432)

Two of the three are Python and can be compared directly. The third is SQL, so
this reads the migration's own text and asserts each predicate is transcribed
into it. That is a weaker check than an execution, which is what
`test_hub_client_worklist_parity_pg.py` adds against a real Postgres — but it
runs in the mock suite, which is where a drift is cheapest to catch.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from domain.banking import entry as bank_entry
from domain.hub import worklist
from domain.hub.tiles import BY_ID, MODULES_WITH_NO_FIRM_SCREEN, TILES
from services import hub_service, hub_worklist_service

API = Path(__file__).resolve().parents[1]
WEB_APP = API.parent / "web" / "app"


def _last_definer() -> Path:
    """The migration that LAST defined the function, found by scanning — the
    CLAUDE.md rule for `CREATE OR REPLACE`: a guard pinned to 416 would keep
    reading a body production no longer runs the day a later migration
    replaces it, and pass. Rollbacks are not definers."""
    hits = sorted(
        p for p in API.joinpath("migrations").glob("[0-9]*.sql")
        if not p.name.endswith("_rollback.sql")
        and re.search(r"FUNCTION\s+public\.hub_client_worklist\s*\(",
                      p.read_text(encoding="utf-8"))
    )
    assert hits, "no migration defines public.hub_client_worklist"
    return hits[-1]


MIGRATION = _last_definer()
SQL = MIGRATION.read_text(encoding="utf-8")
# The SQL below the header prose. The header NAMES every predicate in a table,
# so a search over the whole file would be satisfied by the documentation of
# the rule rather than by the rule — the comment-as-deed hazard this codebase
# has now hit four times in one day.
#
# Split at the STATEMENT — anchored to a line start and naming the function —
# rather than at the first occurrence of the phrase: a header explaining why
# `CREATE OR REPLACE FUNCTION` replaces a whole body would otherwise move the
# split point up into the prose and hand every assertion below the
# documentation instead of the code.
_STATEMENT = re.search(r"(?m)^CREATE OR REPLACE FUNCTION public\.hub_client_worklist\(", SQL)
assert _STATEMENT, f"{MIGRATION.name} does not define public.hub_client_worklist"
SQL_BODY = SQL[_STATEMENT.end():]


# ── The vocabulary ──────────────────────────────────────────────────────────

def test_every_worklist_names_a_real_tile_that_is_client_scoped():
    for w in worklist.WORKLISTS:
        assert w.tile_id in BY_ID, f"{w.tile_id} is not a tile"
        assert BY_ID[w.tile_id].client_scoped, (
            f"{w.tile_id} is a FIRM-level question, so 'which clients' is not "
            f"a question about it")


def test_a_worklist_opens_the_tiles_own_client_section():
    """Restated in `worklist.py` only so that module reads on its own. If the
    two disagree, a row opens a section that is not the one the tile counts."""
    for w in worklist.WORKLISTS:
        assert w.opens_section == BY_ID[w.tile_id].client_section, (
            f"{w.tile_id}: the worklist opens {w.opens_section!r} and the tile "
            f"counts {BY_ID[w.tile_id].client_section!r}")


def test_every_worklist_href_is_the_tiles_own_firm_href():
    """One source for where a tile goes. `Tile.firm_href` is what the hub
    serves, so a worklist route the tile does not carry is a screen nothing
    links to."""
    for w in worklist.WORKLISTS:
        assert BY_ID[w.tile_id].firm_href == w.href, (
            f"{w.tile_id}: the hub sends a CA to {BY_ID[w.tile_id].firm_href!r} "
            f"and the worklist lives at {w.href!r}")


def test_a_worklist_route_is_a_real_page_and_not_a_tombstone():
    if not WEB_APP.exists():
        pytest.skip("apps/web is not present in this checkout")
    for w in worklist.WORKLISTS:
        page = WEB_APP.joinpath(*[s for s in w.href.split("/") if s]) / "page.tsx"
        assert page.exists(), f"{w.tile_id} links to {w.href}, which has no page.tsx"
        body = re.sub(r"/\*.*?\*/", "", page.read_text(encoding="utf-8"), flags=re.S)
        assert "MovedToClientWorkspace" not in body, (
            f"{w.tile_id} links to {w.href}, which still renders the tombstone")
        assert f'tile="{w.tile_id}"' in body, (
            f"{w.href} does not render the {w.tile_id} worklist — a page that "
            f"renders a DIFFERENT tile shows one module's queue under "
            f"another's heading")
        # The H1 is the PAGE's, because it has to be right before the fetch
        # lands — a screen titled "Worklist" until the server answers reads as
        # broken. Pinned to the tile's own label so the two cannot drift.
        assert f'heading="{BY_ID[w.tile_id].label}"' in body, (
            f"{w.href} does not head itself {BY_ID[w.tile_id].label!r}, which "
            f"is what the hub tile that sends a CA there is called")


def test_a_tile_with_no_firm_screen_carries_a_reason():
    """The rule, not a count. See
    `test_a_hub_tile_shows_what_is_outstanding.test_the_firm_level_gap_is_
    recorded_and_honest`, which holds the same identity from the other side."""
    absent = {t.id for t in TILES if t.firm_href is None and t.client_scoped}
    assert absent == set(worklist.NO_WORKLIST_BECAUSE), (
        f"tiles with no firm screen {sorted(absent)} against tiles with a "
        f"recorded reason {sorted(worklist.NO_WORKLIST_BECAUSE)}")
    assert absent == set(MODULES_WITH_NO_FIRM_SCREEN)
    for tile_id, why in worklist.NO_WORKLIST_BECAUSE.items():
        assert len(why) > 40, f"{tile_id}'s reason is too short to be one"


def test_no_tile_both_has_a_worklist_and_a_reason_for_having_none():
    overlap = set(worklist.BY_TILE) & set(worklist.NO_WORKLIST_BECAUSE)
    assert overlap == set(), f"{sorted(overlap)} both has a worklist and does not"


# ── The three vocabularies ──────────────────────────────────────────────────

def test_the_python_twin_covers_exactly_the_tiles_with_a_worklist():
    assert set(hub_worklist_service._POPULATION) == set(worklist.BY_TILE)


def test_the_guard_reads_the_body_production_runs():
    """Not vacuous about WHICH file: 432 replaced 416's body, and reading 416
    would pass every assertion below against a function that no longer
    exists."""
    assert int(MIGRATION.name.split("_", 1)[0]) >= 432, MIGRATION.name


@pytest.mark.parametrize("tile_id,table", [
    ("banking", "bank_transactions"),
    ("sales", "client_sales_invoices"),
    ("purchases", "purchase_bills"),
    ("fixed_assets", "fixed_assets"),
    ("year_end", "year_end_engagements"),
])
def test_all_three_read_the_same_table(tile_id: str, table: str):
    assert hub_worklist_service._POPULATION[tile_id]["table"] == table
    assert f"public.{table}" in SQL_BODY, (
        f"{MIGRATION.name} does not read public.{table} for {tile_id}")


def test_the_banking_predicate_is_the_banking_modules_own_vocabulary():
    """`domain/banking/entry.OPEN_STATES` is the definition of a line still
    needing a person, and BOTH the tile and the queue must take it from there —
    a hand-written list in either is a second definition that drifts the day a
    state is added."""
    assert (list(hub_worklist_service._POPULATION["banking"]["in_"][1])
            == list(bank_entry.OPEN_STATES))
    for state in bank_entry.OPEN_STATES:
        assert f"'{state}'" in SQL_BODY, (
            f"migration 416 does not carry the {state!r} entry state")
    # And nothing beyond them: a fourth quoted state in that IN list would mean
    # the SQL counts a line the tile does not.
    in_list = re.search(r"entry_state IN \(([^)]*)\)", SQL_BODY)
    assert in_list, "migration 416 no longer filters bank_transactions on entry_state"
    assert ({s.strip().strip("'") for s in in_list.group(1).split(",")}
            == set(bank_entry.OPEN_STATES))


def test_the_year_end_predicate_is_the_complement_of_the_finished_states():
    """⚠️ THE SQL WRITES `status <> 'locked'`, WHICH IS ONLY THE COMPLEMENT
    WHILE `locked` IS THE ONLY FINISHED STATE. A second finished state added to
    `_YEAR_END_DONE` would leave the SQL counting engagements the tile does
    not, so this asserts the premise rather than the spelling."""
    assert hub_service._YEAR_END_DONE == ("locked",), (
        "the year-end finished states moved — migration 416's `status <> "
        "'locked'` is no longer the complement and must be rewritten")
    assert (hub_worklist_service._POPULATION["year_end"]["in_"][1]
            == hub_service._outstanding("year_end_engagements", hub_service._YEAR_END_DONE))
    assert "status <> 'locked'" in SQL_BODY


def test_the_two_column_predicates_are_transcribed():
    assert hub_worklist_service._POPULATION["fixed_assets"]["is_null"] == \
        "depreciation_posted_through"
    assert "depreciation_posted_through IS NULL" in SQL_BODY


def _branch(tile_id: str) -> str:
    """One tile's branch of the SQL, so a predicate transcribed into the WRONG
    branch — the purchases filter written under sales — is not satisfied by
    its presence somewhere in the file."""
    m = re.search(rf"p_tile = '{tile_id}' THEN(.*?)(?:ELSIF|ELSE\b)", SQL_BODY, flags=re.S)
    assert m, f"{MIGRATION.name} has no {tile_id!r} branch"
    return m.group(1)


@pytest.mark.parametrize("tile_id,alias", [("sales", "s"), ("purchases", "b")])
def test_a_money_worklist_counts_a_live_document_only(tile_id: str, alias: str):
    """accounting-hub-1-02. `outstanding_paise` is GENERATED from the money
    columns and knows nothing about `status` or `deleted_at`, so a cancelled
    bill kept its whole face value as owed. The tile, the twin and the SQL
    must all exclude the SAME dead states — the ones AP/AR ageing exclude —
    or the queue and the number on the tile disagree about what exists."""
    spec = hub_worklist_service._POPULATION[tile_id]
    assert spec["column"] == "outstanding_paise"
    assert spec["gt"] == ("outstanding_paise", 0)
    assert spec["not_in"] == ("status", list(hub_service._DEAD_DOCUMENT))
    assert spec["is_null"] == "deleted_at"

    body = _branch(tile_id)
    assert f"SUM({alias}.outstanding_paise)" in body
    assert f"{alias}.outstanding_paise > 0" in body
    assert f"{alias}.deleted_at IS NULL" in body
    in_list = re.search(rf"{alias}\.status NOT IN \(([^)]*)\)", body)
    assert in_list, f"the {tile_id} branch does not exclude dead statuses"
    assert ({v.strip().strip("'") for v in in_list.group(1).split(",")}
            == set(hub_service._DEAD_DOCUMENT))


def test_the_dead_states_are_the_ageing_screens_own():
    """The tile is checked against AP/AR ageing by anybody who doubts it, so
    they must agree about which documents exist. Both statement services name
    their dead states privately; this holds the hub to them rather than to a
    third spelling."""
    from services import customer_statement_service, vendor_statement_service

    assert set(hub_service._DEAD_DOCUMENT) == set(vendor_statement_service._DEAD_BILL)
    assert set(hub_service._DEAD_DOCUMENT) == set(customer_statement_service._DEAD_INVOICE)
    for key in ("client_sales_invoices", "purchase_bills"):
        assert set(hub_service._DEAD_DOCUMENT) <= set(hub_service._ALL[key]), key


def test_the_hub_tile_asks_the_same_live_document_rule():
    """The FIGURE on the tile is the third place — `_signals` passes
    `live_documents_only=True` for both money tiles, and `_sum_paise` applies
    exactly `_DEAD_DOCUMENT` and `deleted_at`."""
    import inspect

    src = inspect.getsource(hub_service._signals)
    for table in ("client_sales_invoices", "purchase_bills"):
        call = re.search(rf'"{table}", "outstanding_paise"[^)]*\)', src, flags=re.S)
        assert call and "live_documents_only=True" in call.group(0), table
    body = inspect.getsource(hub_service._sum_paise)
    assert 'is_("deleted_at", "null")' in body
    assert 'not_.in_("status", list(_DEAD_DOCUMENT))' in body


# ── The refusals ────────────────────────────────────────────────────────────

def test_the_sql_refuses_an_unknown_tile_rather_than_answering_empty():
    """A nil meaning *no client needs work* and a nil meaning *this tile has no
    worklist* are different facts — `domain/gst/gstr3b_computer`'s rule applied
    to a queue."""
    assert "has no firm-level worklist" in SQL_BODY
    assert "RAISE EXCEPTION" in SQL_BODY


def test_the_sql_scopes_by_firm_and_treats_an_empty_list_as_nothing():
    """`p_client_ids` NULL means no restriction and an EMPTY array means
    nothing. The SQL expresses that as `IS NULL OR = ANY(...)`, which gives an
    empty array no rows — the distinction that turns a scoping bug into a
    cross-client read if it is collapsed."""
    branches = len(worklist.WORKLISTS)
    assert branches == 5
    assert SQL_BODY.count("firm_id = p_firm") == branches, (
        f"every branch of {MIGRATION.name} must filter on the firm")
    assert SQL_BODY.count("p_client_ids IS NULL OR") == branches


def test_the_service_refuses_a_tile_with_no_worklist_with_its_own_reason():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as e:
        hub_worklist_service.worklist({"firm_id": "f1"}, "inventory")
    assert e.value.status_code == 422
    assert "reorder" in str(e.value.detail).lower()

    with pytest.raises(HTTPException) as e:
        hub_worklist_service.worklist({"firm_id": "f1"}, "not_a_tile")
    assert e.value.status_code == 422


def test_a_caller_with_no_firm_is_refused():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as e:
        hub_worklist_service.worklist({}, "banking")
    assert e.value.status_code == 400


# ── The Python twin actually runs ───────────────────────────────────────────
#
# A service whose job is to FETCH needs a test that fetches — CLAUDE.md's own
# lesson from `fetch_all` being handed something it cannot call at two sites,
# both invisible to a source scan. `_hub_worklist_double` is the narrowest
# PostgREST stand-in that runs `_python_twin` end to end, and the `_pg` parity
# file feeds the same double from the same rows as Postgres.

FIRM = "f4160000-0000-0000-0000-000000000001"
A = "c4160000-0000-0000-0000-00000000000a"
B = "c4160000-0000-0000-0000-00000000000b"
OTHER = "f4160000-0000-0000-0000-0000000000ff"


def _double():
    from tests._hub_worklist_double import Double

    return Double({
        "bank_transactions": [
            {"id": "1", "firm_id": FIRM, "client_id": A, "entry_state": "needs_you"},
            {"id": "2", "firm_id": FIRM, "client_id": A, "entry_state": "ready"},
            {"id": "3", "firm_id": FIRM, "client_id": B, "entry_state": "proposed"},
            # Passed — done, so not in the queue.
            {"id": "4", "firm_id": FIRM, "client_id": B, "entry_state": "passed"},
            # Another firm's line. The tenancy filter is the primary isolation
            # control here (the service key bypasses RLS), so it is exercised.
            {"id": "5", "firm_id": OTHER, "client_id": A, "entry_state": "ready"},
        ],
        # `status` is NOT NULL on both document tables, so every row carries
        # one — a row without it would be dropped by `not.in` as a NULL is.
        "purchase_bills": [
            {"id": "1", "firm_id": FIRM, "client_id": A, "outstanding_paise": 118000,
             "status": "received", "deleted_at": None},
            {"id": "2", "firm_id": FIRM, "client_id": A, "outstanding_paise": 59000,
             "status": "partially_paid", "deleted_at": None},
            {"id": "3", "firm_id": FIRM, "client_id": B, "outstanding_paise": 0,
             "status": "paid", "deleted_at": None},
            # Three documents nobody owes, each carrying a balance the generated
            # column still computes. Client B would appear on their strength
            # alone, which is what accounting-hub-1-02 was.
            {"id": "4", "firm_id": FIRM, "client_id": B, "outstanding_paise": 720000,
             "status": "cancelled", "deleted_at": None},
            {"id": "5", "firm_id": FIRM, "client_id": B, "outstanding_paise": 71000,
             "status": "draft", "deleted_at": None},
            {"id": "6", "firm_id": FIRM, "client_id": B, "outstanding_paise": 9000,
             "status": "received", "deleted_at": "2026-09-01T00:00:00+00:00"},
        ],
        "client_sales_invoices": [
            {"id": "1", "firm_id": FIRM, "client_id": B, "outstanding_paise": 250000,
             "status": "issued", "deleted_at": None},
            {"id": "2", "firm_id": FIRM, "client_id": B, "outstanding_paise": 50000,
             "status": "partially_paid", "deleted_at": None},
            {"id": "3", "firm_id": FIRM, "client_id": A, "outstanding_paise": 11800,
             "status": "cancelled", "deleted_at": None},
            {"id": "4", "firm_id": FIRM, "client_id": A, "outstanding_paise": 78000,
             "status": "draft", "deleted_at": "2026-09-01T00:00:00+00:00"},
        ],
        "fixed_assets": [
            {"id": "1", "firm_id": FIRM, "client_id": B, "depreciation_posted_through": None},
            {"id": "2", "firm_id": FIRM, "client_id": B, "depreciation_posted_through": "2026-03-31"},
        ],
        "year_end_engagements": [
            {"id": "1", "firm_id": FIRM, "client_id": A, "status": "draft"},
            {"id": "2", "firm_id": FIRM, "client_id": A, "status": "locked"},
        ],
        "clients": [
            {"id": A, "firm_id": FIRM, "client_name": "Acme", "legal_name": "Acme Traders LLP",
             "entity_type": "LLP"},
            {"id": B, "firm_id": FIRM, "client_name": "Bharat", "legal_name": None,
             "entity_type": "Private Limited"},
        ],
    })


@pytest.fixture()
def twin(monkeypatch):
    d = _double()
    monkeypatch.setattr(hub_worklist_service, "_db", lambda: d)
    return d


def test_the_twin_counts_open_bank_lines_per_client(twin):
    out = hub_worklist_service.worklist({"firm_id": FIRM}, "banking")
    assert [(r["client_id"], r["signal"]) for r in out["rows"]] == [(A, 2), (B, 1)]
    assert out["unit"] == "count"
    assert out["clients_examined"] == 2


def test_the_twin_sums_what_is_still_open_and_drops_a_settled_client(twin):
    """A client with nothing outstanding is NOT a zero row — a queue is work,
    not a position. `outstanding_paise` is migration 278's generated column,
    so a fully-settled bill is excluded by the predicate rather than netted."""
    out = hub_worklist_service.worklist({"firm_id": FIRM}, "purchases")
    assert [(r["client_id"], r["signal"]) for r in out["rows"]] == [(A, 177000)]
    assert out["unit"] == "paise"


def test_a_cancelled_draft_or_deleted_bill_is_owed_by_nobody(twin):
    """accounting-hub-1-02, from the outside. Client B's only balances are a
    cancelled bill, a draft and a soft-deleted one — 8,00,000 paise the
    generated column still reports — so B has no row at all."""
    rows = hub_worklist_service.worklist({"firm_id": FIRM}, "purchases")["rows"]
    assert B not in {r["client_id"] for r in rows}


def test_the_sales_worklist_sums_what_customers_owe_and_skips_dead_invoices(twin):
    """accounting-hub-2-05. The Sales tile's queue is the clients' OWN
    customer receivables — `client_sales_invoices` — and a cancelled or
    soft-deleted draft invoice is owed by nobody, so client A (whose only
    invoices are those two) has no row."""
    out = hub_worklist_service.worklist({"firm_id": FIRM}, "sales")
    assert [(r["client_id"], r["signal"]) for r in out["rows"]] == [(B, 300000)]
    assert out["unit"] == "paise"
    assert out["opens_section"] == "sales"
    assert out["label"] == "Sales"
    assert out["column"] == "Outstanding"


def test_the_twin_honours_the_finished_states(twin):
    assert [(r["client_id"], r["signal"])
            for r in hub_worklist_service.worklist({"firm_id": FIRM}, "fixed_assets")["rows"]] \
        == [(B, 1)]
    assert [(r["client_id"], r["signal"])
            for r in hub_worklist_service.worklist({"firm_id": FIRM}, "year_end")["rows"]] \
        == [(A, 1)]


def test_a_row_carries_the_clients_name_legal_first(twin):
    rows = hub_worklist_service.worklist({"firm_id": FIRM}, "banking")["rows"]
    by_id = {r["client_id"]: r for r in rows}
    assert by_id[A]["client_name"] == "Acme Traders LLP"
    # No legal name recorded — falls back rather than blanking the row.
    assert by_id[B]["client_name"] == "Bharat"


def test_another_firms_rows_are_never_counted(twin):
    """The app-layer `.eq("firm_id", …)` is the primary isolation control —
    the service key bypasses RLS — so a missing filter here is a cross-tenant
    read rather than an error."""
    out = hub_worklist_service.worklist({"firm_id": OTHER}, "banking")
    assert [(r["client_id"], r["signal"]) for r in out["rows"]] == [(A, 1)]


def test_a_caller_assigned_to_nothing_gets_nothing_not_everything(twin, monkeypatch):
    """An EMPTY scope means NOTHING, never 'no filter' — the distinction that
    turns a scoping bug into a cross-client read if it is collapsed."""
    monkeypatch.setattr(hub_worklist_service, "effective_client_ids", lambda u: set())
    out = hub_worklist_service.worklist({"firm_id": FIRM}, "banking")
    assert out["rows"] == []
    assert out["clients_examined"] == 0


def test_an_assigned_caller_sees_only_their_own_book(twin, monkeypatch):
    monkeypatch.setattr(hub_worklist_service, "effective_client_ids", lambda u: {B})
    out = hub_worklist_service.worklist({"firm_id": FIRM}, "banking")
    assert [(r["client_id"], r["signal"]) for r in out["rows"]] == [(B, 1)]
    assert out["clients_examined"] == 1


def test_the_rows_are_worst_first(twin):
    rows = hub_worklist_service.worklist({"firm_id": FIRM}, "banking")["rows"]
    assert [r["signal"] for r in rows] == sorted((r["signal"] for r in rows), reverse=True)
