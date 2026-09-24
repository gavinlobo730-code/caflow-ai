"""The hub is CALLED, not just shaped.

`test_the_hub_asks_the_right_table.py` reads `services/hub_service.py`'s AST
and `..._pg.py` checks every column it filters on exists. Both passed on a
`_sum_paise` that could not run at all: it handed `core.db_paging.fetch_all`
THREE positional arguments where the signature takes two, so every call raised
`TypeError` — and `_safely` is there precisely to swallow a tile's exception,
so the three MONEY tiles (sales, purchases, TDS) came back `signal: None` and
the hub rendered "—" against each of them. Silently, on the three figures a CA
opens the screen for.

A shape test cannot catch that and was never going to: the call site it reads
looks correct in isolation, and the defect is in the CALLEE's signature. So
this module calls `hub()` for real against the shared FakeDB and asserts what
comes back, which is the only check that covers the arity, the argument ORDER,
the projection carrying the keyset cursor, and the arithmetic at once.

THE HEADLINE ASSERTION IS A NEGATIVE ONE — no tile that `answerable` says has
a figure may come back with `signal: None`. That is the exact shape of a
swallowed exception, and stating it as a rule rather than as three named tiles
means a fourth money tile added later is covered on the day it is written.
`test_a_hub_tile_shows_what_is_outstanding.py` already pins that a null signal
on an answerable tile is a LEGITIMATE third state the payload can carry; this
asserts it does not occur when every table is readable, which is a different
claim about the same field.
"""
from __future__ import annotations

import pytest

from tests.e2e_harness import FakeDB

import services.hub_service as hub_service


FIRM = "11111111-1111-4111-8111-111111111111"
CLIENT_A = "22222222-2222-4222-8222-222222222222"
CLIENT_B = "33333333-3333-4333-8333-333333333333"

PARTNER = {"id": "u1", "firm_id": FIRM, "role": "Partner"}


def _seed(db: FakeDB) -> None:
    """A practice with something outstanding in every module that has a tile.

    Each table gets one row that COUNTS and one that does not, so a query that
    forgot its status predicate reads 2 where the tile says 1 — a wrong number
    rather than a wrong shape, which is the failure a count test has to be able
    to see.
    """
    def row(table, client, **kw):
        db.seed(table, {"firm_id": FIRM, "client_id": client, **kw})

    # compliance: "In Progress" is outstanding, "Filed" is not.
    row("compliance_records", CLIENT_A, status="In Progress")
    row("compliance_records", CLIENT_A, status="Filed")
    row("compliance_records", CLIENT_B, status="Overdue")

    # gst: both return tables feed one tile, so the figure is their SUM.
    row("gstr1_returns", CLIENT_A, status="draft")
    row("gstr1_returns", CLIENT_A, status="submitted")
    row("gstr3b_returns", CLIENT_A, status="ca_approved")

    # banking: OPEN_STATES comes from domain/banking/entry.
    from domain.banking import entry as bank_entry
    row("bank_transactions", CLIENT_A, entry_state=sorted(bank_entry.OPEN_STATES)[0])
    row("bank_transactions", CLIENT_A, entry_state="posted")

    row("journal_entries", CLIENT_A, status="draft")
    row("journal_entries", CLIENT_A, status="posted")

    # The three money tiles. `outstanding_paise` is GENERATED on both document
    # tables (migration 278), so the harness computes it from the components
    # rather than letting a test state it directly — which is also what makes
    # the zero-balance row genuinely filtered out by `.gt(column, 0)`.
    row("client_sales_invoices", CLIENT_A, total_paise=118_000_00, paid_paise=0)
    row("client_sales_invoices", CLIENT_A, total_paise=50_000_00, paid_paise=50_000_00)
    row("client_sales_invoices", CLIENT_B, total_paise=2_000_00, paid_paise=0)

    row("purchase_bills", CLIENT_A, net_payable_paise=45_000_00, paid_paise=0)
    row("purchase_bills", CLIENT_A, net_payable_paise=10_000_00, paid_paise=10_000_00)

    # TDS: deposited means a challan number, so the row carrying one is out.
    row("tds_deductions", CLIENT_A, tds_paise=10_000_00, challan_no=None)
    row("tds_deductions", CLIENT_A, tds_paise=7_500_00, challan_no="0001234")

    row("payroll_runs", CLIENT_A, status="review")
    row("payroll_runs", CLIENT_A, status="paid")

    row("itr_filings", CLIENT_A, status="ready_for_filing")
    row("itr_filings", CLIENT_A, status="filed")

    row("fixed_assets", CLIENT_A, depreciation_posted_through=None)
    row("fixed_assets", CLIENT_A, depreciation_posted_through="2026-03-31")

    row("year_end_engagements", CLIENT_A, status="in_review")
    row("year_end_engagements", CLIENT_A, status="locked")

    row("documents", CLIENT_A, review_status="pending_review")
    row("documents", CLIENT_A, review_status="approved")


@pytest.fixture()
def db(monkeypatch):
    d = FakeDB()
    _seed(d)
    # hub_service imports both names at module level, so the module's own
    # attribute is what has to move — patching core.supabase_client would
    # leave the already-bound reference pointing at the real client.
    monkeypatch.setattr(hub_service, "get_service_supabase", lambda: d)
    return d


def _by_id(payload) -> dict:
    return {t["id"]: t for t in payload["tiles"]}


# ── The headline: an answerable tile comes back with a number ────────────────

def test_no_answerable_tile_comes_back_with_a_null_signal_at_firm_scope(db):
    tiles = _by_id(hub_service.hub(PARTNER))
    silent = sorted(k for k, t in tiles.items()
                    if t["answerable"] and t["signal"] is None)
    assert silent == [], (
        f"tiles answerable but with no figure: {silent}. `_safely` swallows a "
        "tile's exception by design, so this is what a broken query looks like "
        "from the outside."
    )


def test_no_answerable_tile_comes_back_with_a_null_signal_at_client_scope(db):
    tiles = _by_id(hub_service.hub(PARTNER, client_id=CLIENT_A))
    silent = sorted(k for k, t in tiles.items()
                    if t["answerable"] and t["signal"] is None)
    assert silent == []


# ── The money tiles specifically, because they are the ones that were dead ──

@pytest.mark.parametrize("tile_id,expected", [
    # 1,18,000 open; the fully-paid invoice is filtered out, and CLIENT_B's
    # 2,000 is in scope at firm level.
    ("sales", 118_000_00 + 2_000_00),
    ("purchases", 45_000_00),
    ("tds", 10_000_00),
])
def test_a_money_tile_sums_what_is_open(db, tile_id, expected):
    assert _by_id(hub_service.hub(PARTNER))[tile_id]["signal"] == expected


def test_a_money_tile_is_in_paise_not_rupees(db):
    """The unit the browser formats with. A tile that answered in rupees would
    still be a number and would still be non-null — it would just be 100x
    wrong on screen, which no shape test can see."""
    sales = _by_id(hub_service.hub(PARTNER))["sales"]
    assert sales["unit"] == "paise"
    assert sales["signal"] == 120_000_00


# ── The counts, one per remaining tile that has one ─────────────────────────

@pytest.mark.parametrize("tile_id,expected", [
    ("compliance", 2),       # In Progress + Overdue; Filed is done
    ("gst", 2),              # one gstr1 draft + one gstr3b ca_approved
    ("banking", 1),
    ("accounting", 1),
    ("payroll", 1),
    ("income_tax", 1),
    ("fixed_assets", 1),
    ("year_end", 1),
    ("documents", 1),
])
def test_a_count_tile_counts_only_what_is_outstanding(db, tile_id, expected):
    assert _by_id(hub_service.hub(PARTNER))[tile_id]["signal"] == expected


# ── Scope ───────────────────────────────────────────────────────────────────

def test_a_client_hub_asks_the_same_questions_of_one_client(db):
    firm = _by_id(hub_service.hub(PARTNER))
    client_a = _by_id(hub_service.hub(PARTNER, client_id=CLIENT_A))

    # CLIENT_B's 2,000 invoice and its Overdue obligation are the difference.
    assert firm["sales"]["signal"] == 120_000_00
    assert client_a["sales"]["signal"] == 118_000_00
    assert firm["compliance"]["signal"] == 2
    assert client_a["compliance"]["signal"] == 1


def test_an_assignment_scoped_user_sees_only_their_own_clients(db, monkeypatch):
    """`effective_client_ids` answering a SET is the non-Partner path, and an
    EMPTY set means nothing — never "no filter". Both are asserted, because
    collapsing the second is how a scoping bug becomes a cross-client read."""
    monkeypatch.setattr(hub_service, "effective_client_ids", lambda u: {CLIENT_B})
    assert _by_id(hub_service.hub(PARTNER))["sales"]["signal"] == 2_000_00

    monkeypatch.setattr(hub_service, "effective_client_ids", lambda u: set())
    assert _by_id(hub_service.hub(PARTNER))["sales"]["signal"] == 0


def test_a_caller_with_no_firm_is_refused(db):
    with pytest.raises(ValueError):
        hub_service.hub({"id": "u1", "role": "Partner"})


# ── The three states, from the outside ──────────────────────────────────────

def test_a_tile_that_is_not_answerable_carries_its_reason_and_no_figure(db):
    firm = _by_id(hub_service.hub(PARTNER))
    # Insights and Reports are destinations at BOTH scopes; inventory has no
    # firm-wide figure because on-hand stock is one client's own ledger.
    for tile_id in ("insights", "reports", "inventory"):
        t = firm[tile_id]
        assert t["answerable"] is False, tile_id
        assert t["signal"] is None, tile_id
        assert t["no_signal_because"], tile_id


def test_one_unreadable_table_costs_that_tile_and_nothing_else(db, monkeypatch):
    """`_safely`'s whole purpose, asserted from the outside: fourteen figures
    must survive the fifteenth failing."""
    real = hub_service._count

    def boom(table, *a, **kw):
        if table == "journal_entries":
            raise RuntimeError("PGRST000")
        return real(table, *a, **kw)

    monkeypatch.setattr(hub_service, "_count", boom)
    tiles = _by_id(hub_service.hub(PARTNER))

    assert tiles["accounting"]["answerable"] is True
    assert tiles["accounting"]["signal"] is None       # the third state
    assert tiles["sales"]["signal"] == 120_000_00      # unaffected
    assert tiles["compliance"]["signal"] == 2


def test_a_firm_scoping_failure_is_loud_rather_than_an_empty_hub(db, monkeypatch):
    """The exception `_safely` deliberately does NOT cover. `effective_client_ids`
    returning the wrong set is the failure that must not be swallowed into a
    hub of dashes."""
    def boom(_user):
        raise RuntimeError("authz is down")

    monkeypatch.setattr(hub_service, "effective_client_ids", boom)
    with pytest.raises(RuntimeError):
        hub_service.hub(PARTNER)


# ── The read stays proportional to the answer ───────────────────────────────

def test_the_hub_reads_no_rows_it_does_not_need(db, monkeypatch):
    """CLAUDE.md's reporting rule, measured rather than asserted about the
    source: a COUNT tile must not pull the rows it is counting, and a money
    tile must pull only the columns it adds up."""
    seen: list[tuple[str, str]] = []
    real_table = db.table

    def spy(name):
        q = real_table(name)
        real_select = q.select

        def select(cols="*", count=None, **kw):
            seen.append((name, cols if count is None else f"{cols}#count"))
            return real_select(cols, count=count, **kw)

        q.select = select
        return q

    monkeypatch.setattr(db, "table", spy)
    hub_service.hub(PARTNER)

    for table, cols in seen:
        assert cols in ("id#count", "id,outstanding_paise", "id,tds_paise"), (
            f"{table} was read as {cols!r} — a hub tile reads a count or the "
            "one column it sums, never a row set."
        )


def test_the_client_hub_delegates_exactly_one_read_and_it_is_named(db, monkeypatch):
    """The inventory tile is the one that does not issue its own query, and
    that exception is asserted rather than left implicit.

    It reads the CATALOGUE — one row per good — because on-hand stock against a
    per-item level cannot be counted in SQL from anything authoritative
    (`service_catalogue.stock_qty_units` is a cache, migration 188). That is
    proportional to the item master and not to the ledger, which is what the
    reporting rule actually forbids; it is still the heaviest thing on the
    screen, and this test is where a SECOND such delegation would show up.
    """
    seen: list[tuple[str, str]] = []
    real_table = db.table

    def spy(name):
        q = real_table(name)
        real_select = q.select

        def select(cols="*", count=None, **kw):
            seen.append((name, cols if count is None else f"{cols}#count"))
            return real_select(cols, count=count, **kw)

        q.select = select
        return q

    monkeypatch.setattr(db, "table", spy)
    hub_service.hub(PARTNER, client_id=CLIENT_A)

    # The RULE, not the projection's current spelling: how MANY reads are
    # neither a count nor a summed column, and which TABLE they are against.
    # Asserting the column list would fail the day somebody adds a column to
    # the reorder report for reasons that have nothing to do with the hub —
    # a guard that names a spelling, which is this repo's most-repeated
    # lesson.
    wide = [(t, c) for t, c in seen
            if c not in ("id#count", "id,outstanding_paise", "id,tds_paise")]
    assert [t for t, _ in wide] == ["service_catalogue"], (
        f"the client hub made {len(wide)} read(s) that are neither a count nor "
        f"a summed column: {wide}. Exactly one is expected — the reorder "
        "catalogue, whose cost is argued in `_signals`. A second one needs the "
        "same argument written down."
    )
