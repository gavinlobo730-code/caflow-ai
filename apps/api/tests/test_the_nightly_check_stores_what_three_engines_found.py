"""The nightly books check stores what three exception engines found, and the digest reads it (POST-A-050).

THE CLAIMS, AND WHERE EACH IS HELD
    1. Each engine's result is the engine's own: the recurring-journal rule is the one the screen uses (moved, not copied),
       the duplicate pairs are `near_duplicate`'s, and the GSTR-2B row is the §16(4) radar's answer.
    2. A result that could not be computed is stored as `not_computed` with a reason and NEVER as a zero, and one engine
       failing does not lose the others.
    3. The stored rows are the nightly run's: `run_reconciliation` writes them, a second run replaces them, and a failure of
       the new stage cannot fail the books check.
    4. The digest reads them for the caller's own clients, recent rows only, behind the access of the screen each summarises,
       and says which clients have no result.
    5. The vocabulary in the Python module is the one the migration's CHECK allows.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from domain.accounting import recurring_suggestions
from domain.practice import digest as dg
from domain.practice import nightly_results as nr
from domain.reporting.model import JournalEntry, JournalLine
from services import nightly_exception_results_service as svc
import services.reconciliation_service as rs
from tests.e2e_harness import FakeDB

FIRM, CLIENT, OTHER = "FIRM-A", "CLI-A", "CLI-B"
TODAY = date(2026, 11, 16)
MIGRATION = next(Path(__file__).resolve().parents[1].glob("migrations/660_*.sql"))


def _e(id_, d, narration, accounts=("a", "b"), client=CLIENT):
    return JournalEntry(
        id=id_, entry_date=d, client_id=client, firm_id=FIRM, entry_type="Journal",
        lines=(JournalLine(accounts[0], 1000, 0), JournalLine(accounts[1], 0, 1000)),
        narration=narration, source_type="manual")


# ── 1. the recurring-journal rule ────────────────────────────────────────────

def test_a_pattern_in_two_prior_months_and_not_this_one_is_suggested():
    entries = {e.id: e for e in (_e("1", "2026-09-05", "Rent"), _e("2", "2026-10-05", "rent"))}
    r = svc.compute_recurring_journals(entries, CLIENT, TODAY)
    assert (r.status, r.count) == (nr.COMPUTED, 1)
    assert r.details["examples"][0]["occurrences"] == 2


@pytest.mark.parametrize("entries", [
    [_e("1", "2026-10-05", "Rent")],                                        # one prior month
    [_e("1", "2026-09-05", "Rent"), _e("2", "2026-10-05", "Rent"),
     _e("3", "2026-11-03", "Rent")],                                        # already posted this month
    [_e("1", "2026-09-05", "Rent"), _e("2", "2026-10-05", "Rent", accounts=("a", "c"))],  # accounts differ
    [_e("1", "2026-01-05", "Rent"), _e("2", "2026-02-05", "Rent")],         # outside the look-back
])
def test_the_ordinary_ledger_suggests_nothing_and_that_is_a_computed_zero(entries):
    r = svc.compute_recurring_journals({e.id: e for e in entries}, CLIENT, TODAY)
    assert (r.status, r.count) == (nr.COMPUTED, 0)


def test_the_screens_function_and_the_nightly_one_share_one_rule(monkeypatch):
    """`compute_journal_suggestions` calls `recurring_suggestions.suggest`; the nightly count equals the screen's."""
    import services.intelligence_service as intel
    posted = [{"id": "1", "client_id": CLIENT, "narration": "Rent", "entry_date": "2026-09-05",
               "status": "posted", "entry_type": "Journal", "lines": [{"account_id": "a"}, {"account_id": "b"}]},
              {"id": "2", "client_id": CLIENT, "narration": "Rent", "entry_date": "2026-10-05",
               "status": "posted", "entry_type": "Journal", "lines": [{"account_id": "a"}, {"account_id": "b"}]}]
    import domain.accounting_service as acc
    monkeypatch.setattr(acc.accounting_service, "list_journal_entries", lambda **kw: posted)
    monkeypatch.setattr(intel, "ist_today", lambda: TODAY)
    screen = intel.compute_journal_suggestions(FIRM)
    assert screen["month"] == "2026-11" and len(screen["suggestions"]) == 1
    nightly = svc.compute_recurring_journals(
        {"1": _e("1", "2026-09-05", "Rent"), "2": _e("2", "2026-10-05", "Rent")}, CLIENT, TODAY)
    assert nightly.count == len(screen["suggestions"])
    assert recurring_suggestions.MIN_PRIOR_MONTHS == 2


# ── 1b. duplicate bills ──────────────────────────────────────────────────────

def _bill(id_, no, d, total, vendor="v1", **kw):
    return {"id": id_, "vendor_id": vendor, "bill_no": no, "bill_date": d, "total_paise": total,
            "status": "received", "deleted_at": None, "is_opening": False, **kw}


def test_two_bills_with_one_amount_a_few_days_apart_are_one_pair_counted_once():
    r = nr.duplicate_bill_pairs([_bill("a", "INV-1", "2026-11-01", 118000_00),
                                 _bill("b", "INV-2", "2026-11-03", 118000_00)])
    assert (r.status, r.count, r.amount_paise) == (nr.COMPUTED, 1, 118000_00)
    assert r.details["examples"][0]["reason"] == "same_amount_near_date"


def test_one_number_written_two_ways_is_a_pair_whatever_the_amounts():
    r = nr.duplicate_bill_pairs([_bill("a", "INV-2025/0043", "2026-10-01", 500_00),
                                 _bill("b", "inv 2025-43", "2026-10-20", 900_00)])
    assert r.count == 1 and r.details["examples"][0]["reason"] == "same_number_different_spelling"


@pytest.mark.parametrize("bills", [
    [_bill("a", "INV-1", "2026-11-01", 100_00), _bill("b", "INV-2", "2026-11-03", 200_00)],            # different money
    [_bill("a", "INV-1", "2026-10-01", 100_00), _bill("b", "INV-2", "2026-11-03", 100_00)],            # a month apart
    [_bill("a", "INV-1", "2026-11-01", 100_00, vendor="v1"),
     _bill("b", "INV-2", "2026-11-02", 100_00, vendor="v2")],                                          # two suppliers
    [_bill("a", "INV-1043", "2026-11-01", 100_00), _bill("b", "INV-1044", "2026-11-20", 300_00)],      # the next invoice
    [_bill("a", "INV-1", "2026-11-01", 0), _bill("b", "INV-2", "2026-11-02", 0)],                      # zero-value bills
    [_bill("a", "INV-1", "2026-11-01", 100_00, vendor=None),
     _bill("b", "INV-2", "2026-11-02", 100_00, vendor=None)],                                          # no supplier named
])
def test_the_ordinary_bills_are_not_a_pair(bills):
    assert nr.duplicate_bill_pairs(bills).count == 0


def test_three_alike_bills_are_three_pairs_and_two_second_bookings():
    r = nr.duplicate_bill_pairs([_bill("a", "A", "2026-11-01", 100_00), _bill("b", "B", "2026-11-02", 100_00),
                                 _bill("c", "C", "2026-11-03", 100_00)])
    assert r.count == 3 and r.details["bills_in_a_pair"] == 2 and r.amount_paise == 200_00


def test_the_service_reads_this_clients_live_recent_bills_and_leaves_opening_ones_out():
    db = FakeDB()
    base = {"firm_id": FIRM, "client_id": CLIENT, "status": "received", "deleted_at": None, "is_opening": False}
    db.seed("purchase_bills", {**base, "id": "a", "vendor_id": "v", "bill_no": "1", "bill_date": "2026-11-01", "total_paise": 5000})
    db.seed("purchase_bills", {**base, "id": "b", "vendor_id": "v", "bill_no": "2", "bill_date": "2026-11-02", "total_paise": 5000})
    db.seed("purchase_bills", {**base, "id": "o", "vendor_id": "v", "bill_no": "3", "bill_date": "2026-11-02", "total_paise": 5000, "is_opening": True})
    db.seed("purchase_bills", {**base, "id": "x", "vendor_id": "v", "bill_no": "4", "bill_date": "2026-11-02", "total_paise": 5000, "status": "cancelled"})
    db.seed("purchase_bills", {**base, "id": "old", "vendor_id": "v", "bill_no": "5", "bill_date": "2025-01-02", "total_paise": 5000})
    db.seed("purchase_bills", {**base, "id": "other", "client_id": OTHER, "vendor_id": "v", "bill_no": "6", "bill_date": "2026-11-02", "total_paise": 5000})
    r = svc.compute_duplicate_bills(db, FIRM, CLIENT, TODAY)
    assert (r.count, r.details["bills_scanned"]) == (1, 2)


# ── 1c. GSTR-2B / ITC ────────────────────────────────────────────────────────

def _radar(items, unreconciled):
    return {"items": items, "periods_not_reconciled": ["p"] * unreconciled,
            "blocked_by_2b_count": 1, "not_assessed_count": 2}


def _item(kind, status, paise, label="B1"):
    return {"kind": kind, "status": status, "credit_at_risk_paise": paise, "label": label,
            "supplier": "S", "closes_on": "2026-11-30"}


def test_a_client_with_no_reconciled_month_is_not_computed_and_never_a_zero():
    r = nr.from_itc_radar(_radar([], unreconciled=19), window_months=19)
    assert r.status == nr.NOT_COMPUTED and r.count is None and r.reason


def test_credit_still_claimable_is_counted_and_credit_already_lapsed_is_kept_apart():
    r = nr.from_itc_radar(_radar([_item("withheld_bill", "open", 1000), _item("not_booked", "closing_soon", 500),
                                  _item("withheld_bill", "closed", 9000)], unreconciled=10), window_months=19)
    assert (r.status, r.count, r.amount_paise) == (nr.COMPUTED, 2, 1500)
    assert r.details["lapsed_count"] == 1 and r.details["lapsed_paise"] == 9000
    assert r.details["bills_not_in_2b"] == 1 and r.details["documents_not_booked"] == 1
    assert r.details["months_not_reconciled"] == 10


def test_a_reconciled_month_with_nothing_missing_is_a_computed_zero():
    r = nr.from_itc_radar(_radar([], unreconciled=18), window_months=19)
    assert (r.status, r.count) == (nr.COMPUTED, 0)


def test_a_result_cannot_be_built_that_reads_as_zero_while_not_computed():
    with pytest.raises(AssertionError):
        nr.Result(nr.GSTR_2B, nr.NOT_COMPUTED, count=0, reason="x")
    with pytest.raises(AssertionError):
        nr.Result(nr.GSTR_2B, nr.NOT_COMPUTED)


# ── 2/3. storing, replacing and isolating ────────────────────────────────────

def test_all_three_rows_are_stored_for_the_client_and_a_second_night_replaces_them():
    db = FakeDB()
    assert svc.refresh_client(db, FIRM, CLIENT, {}, TODAY) == 3
    assert svc.refresh_client(db, FIRM, CLIENT, {}, TODAY) == 3
    rows = db.rows("nightly_exception_results")
    assert sorted(r["engine"] for r in rows) == sorted(nr.ENGINES)
    assert all(r["firm_id"] == FIRM and r["client_id"] == CLIENT for r in rows)
    gstr = next(r for r in rows if r["engine"] == "gstr_2b")
    assert gstr["status"] == "not_computed" and gstr["count"] is None and gstr["reason"]


def test_another_clients_rows_are_not_touched():
    db = FakeDB()
    svc.refresh_client(db, FIRM, OTHER, {}, TODAY)
    svc.refresh_client(db, FIRM, CLIENT, {}, TODAY)
    svc.refresh_client(db, FIRM, CLIENT, {}, TODAY)
    assert sum(1 for r in db.rows("nightly_exception_results") if r["client_id"] == OTHER) == 3


def test_one_engine_failing_is_stored_as_not_computed_and_the_others_survive(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("read failed")
    monkeypatch.setattr(svc, "compute_duplicate_bills", boom)
    db = FakeDB()
    svc.refresh_client(db, FIRM, CLIENT, {}, TODAY)
    by = {r["engine"]: r for r in db.rows("nightly_exception_results")}
    assert by["duplicate_bills"]["status"] == "not_computed" and by["duplicate_bills"]["count"] is None
    assert by["duplicate_bills"]["reason"] == svc.COULD_NOT_READ
    assert by["recurring_journals"]["status"] == "computed"


def test_a_failed_write_does_not_raise_into_the_books_check(monkeypatch):
    monkeypatch.setattr(svc, "store", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("table missing")))
    assert svc.refresh_client(FakeDB(), FIRM, CLIENT, {}, TODAY) == 0


def test_the_nightly_run_stores_the_results_after_it_completes(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr("domain.reporting.sources.SupabaseLedgerSource._entries",
                        lambda self, firm_id, client_id: {})
    result = rs.run_reconciliation(db, FIRM, CLIENT, trigger="scheduled")
    assert result["status"] == "completed"
    assert {r["engine"] for r in db.rows("nightly_exception_results")} == set(nr.ENGINES)


def test_a_check_that_cannot_run_the_new_stage_leaves_the_run_completed(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr("domain.reporting.sources.SupabaseLedgerSource._entries",
                        lambda self, firm_id, client_id: {})
    monkeypatch.setattr(svc, "compute_all", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    assert rs.run_reconciliation(db, FIRM, CLIENT, trigger="scheduled")["status"] == "completed"
    assert db.rows("reconciliation_runs")[0]["status"] == "completed"


# ── 4. the digest ────────────────────────────────────────────────────────────

NAMES = {"c1": "Alpha", "c2": "Bravo", "c3": "Charlie"}


def _row(client, engine, count, status="computed", paise=None):
    return {"client_id": client, "engine": engine, "status": status, "count": count, "amount_paise": paise}


def test_no_computed_row_is_unknown_never_clear():
    item = dg.stored_item("gstr_2b", [_row("c1", "gstr_2b", None, status="not_computed")], NAMES)
    assert item["status"] == dg.UNKNOWN and item["count"] is None


def test_a_computed_zero_is_clear_and_counts_only_the_clients_checked():
    item = dg.stored_item("duplicate_bills", [_row("c1", "duplicate_bills", 0), _row("c2", "duplicate_bills", 0)], NAMES)
    assert item["status"] == dg.CLEAR and item["count"] == 0 and item["facts"]["clients_checked"] == 2


def test_findings_are_summed_and_the_clients_named_biggest_first():
    rows = [_row("c1", "recurring_journals", 1), _row("c2", "recurring_journals", 4),
            _row("c3", "recurring_journals", 0), _row("c3", "recurring_journals", None, status="not_computed")]
    item = dg.stored_item("recurring_journals", rows, NAMES)
    assert item["status"] == dg.ATTENTION and item["count"] == 5 and item["clients_total"] == 2
    assert [c["client_name"] for c in item["clients"]] == ["Bravo", "Alpha"]


def test_a_not_computed_row_is_not_counted_among_the_clients_checked():
    item = dg.stored_item("gstr_2b", [_row("c1", "gstr_2b", 0), _row("c2", "gstr_2b", None, status="not_computed")], NAMES)
    assert item["facts"]["clients_checked"] == 1


@pytest.fixture()
def world(monkeypatch):
    import core.supabase_client as sc
    state = {"db": FakeDB()}
    monkeypatch.setattr(sc, "get_service_supabase", lambda: state["db"])
    return state


def _seed(db, client, engine, count, *, hours_ago=2, status="computed", firm=FIRM):
    db.seed("nightly_exception_results", {
        "firm_id": firm, "client_id": client, "engine": engine, "status": status, "count": count,
        "amount_paise": None, "computed_at": (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()})


def _stored(allowed, engines=("gstr_2b", "duplicate_bills", "recurring_journals")):
    return svc_digest._stored_results(FIRM, allowed, NAMES, datetime.now(timezone.utc), list(engines))


from services import digest_service as svc_digest  # noqa: E402


def test_the_digest_reads_only_the_callers_clients(world):
    _seed(world["db"], "c1", "duplicate_bills", 2)
    _seed(world["db"], "c3", "duplicate_bills", 9)
    items, _ = _stored({"c1", "c2"}, ["duplicate_bills"])
    assert items[0]["count"] == 2 and [c["client_name"] for c in items[0]["clients"]] == ["Alpha"]
    assert "Charlie" not in str(items)


def test_another_firms_rows_and_stale_rows_are_ignored(world):
    _seed(world["db"], "c1", "duplicate_bills", 7, firm="OTHER-FIRM")
    _seed(world["db"], "c2", "duplicate_bills", 8, hours_ago=24 * 10)
    items, _ = _stored(None, ["duplicate_bills"])
    assert items[0]["status"] == dg.UNKNOWN


def test_a_client_with_no_result_is_named_beside_the_section(world):
    _seed(world["db"], "c1", "recurring_journals", 1)
    _, notes = _stored(None, ["recurring_journals"])
    assert any("2 clients had no computed nightly result for recurring journals missing this month" in n for n in notes)


def test_gather_withholds_a_section_the_role_may_not_open_and_says_so(world, monkeypatch):
    import core.permissions  # noqa: F401
    monkeypatch.setattr(svc_digest, "can_user", lambda user, res, act: res != "gst")
    import services.intelligence_service as intel
    monkeypatch.setattr(intel, "compute_compliance_risk", lambda f, a: {"clients": []})
    import repositories.task_repository as tr
    monkeypatch.setattr(tr.task_repo, "find_overdue", lambda **kw: [])
    out = svc_digest.gather({"firm_id": FIRM, "id": "u", "role": "Manager"}, None, TODAY)
    keys = {i["key"] for i in out["items"]}
    assert dg.KEY_ITC_NOT_FURNISHED not in keys and dg.KEY_DUPLICATE_BILLS in keys
    assert any("Credit suppliers have not furnished is not shown to you" in g for g in out["gaps"])


def test_a_failed_read_of_the_stored_rows_is_a_gap_and_not_an_empty_section(world, monkeypatch):
    monkeypatch.setattr(svc_digest, "fetch_all", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no table")))
    monkeypatch.setattr(svc_digest, "can_user", lambda *a: True)
    import services.intelligence_service as intel
    monkeypatch.setattr(intel, "compute_compliance_risk", lambda f, a: {"clients": []})
    import repositories.task_repository as tr
    monkeypatch.setattr(tr.task_repo, "find_overdue", lambda **kw: [])
    out = svc_digest.gather({"firm_id": FIRM, "id": "u", "role": "Partner"}, None, TODAY)
    assert not {dg.KEY_ITC_NOT_FURNISHED, dg.KEY_DUPLICATE_BILLS, dg.KEY_RECURRING_JOURNALS} & {i["key"] for i in out["items"]}
    assert any("could not be read just now" in g and "Possible duplicate bills" in g for g in out["gaps"])


def test_only_rule_37a_is_still_named_as_not_covered():
    assert [k for k, _ in dg.NOT_INCLUDED] == ["rule_37a"]
    assert nr.ENGINES == tuple(dg.STORED_SECTIONS)


# ── 5. the vocabulary is the migration's ─────────────────────────────────────

def test_the_migrations_check_allows_exactly_the_engines_the_module_names():
    sql = MIGRATION.read_text()
    listed = re.search(r"engine IN \(([^)]*)\)", sql).group(1)
    assert tuple(re.findall(r"'([a-z_0-9]+)'", listed)) == nr.ENGINES
    states = re.search(r"status IN \(([^)]*)\)", sql).group(1)
    assert tuple(re.findall(r"'([a-z_]+)'", states)) == nr.STATUSES


def test_the_migration_grants_a_signed_in_session_no_write_and_the_api_the_table():
    sql = MIGRATION.read_text()
    assert "REVOKE ALL ON public.nightly_exception_results FROM PUBLIC, anon, authenticated" in sql
    assert "GRANT SELECT ON public.nightly_exception_results TO authenticated" in sql
    assert re.search(r"GRANT (INSERT|UPDATE|DELETE)[^;]*TO authenticated", sql) is None
    assert "RESTRICTIVE" in sql and "ENABLE ROW LEVEL SECURITY" in sql
