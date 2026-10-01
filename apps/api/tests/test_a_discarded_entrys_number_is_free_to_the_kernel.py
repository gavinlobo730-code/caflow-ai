"""
accounting-17 (second look) — a voucher whose number and date a DISCARDED entry
held is posted, not "created" by being handed the dead entry's id.

WHAT WAS WRONG
    `voucher_import.plan` reads LIVE entries only (`deleted_at IS NULL`) and says
    "the CA discarded it and its number is free". The database agrees: the unique
    index behind the posting kernel's dedupe is partial, `WHERE deleted_at IS NULL
    AND reference_no IS NOT NULL AND is_reversed = false` (migrations 143 / 213),
    and `post_journal_atomic` filters `deleted_at IS NULL` when it resolves a
    unique violation to the winner (migration 418). The kernel's own Python
    idempotency fast path, `_create_journal._find_existing`, filtered firm, client,
    reference_no, entry_date and `is_reversed = false` and NOT `deleted_at` — so it
    found the discarded entry, logged "Duplicate journal detected ... skipping" and
    RETURNED ITS ID. The import counted that as `created`, the CA was told "N
    vouchers saved", and nothing had been written: import as drafts, discard some,
    fix the sheet, upload again — the second summary was a lie.

    It was the kernel that was out of step with its own index, so it is the kernel
    that is fixed, and the single-journal editor (`manual_journal_service.create`)
    had the same quirk and is fixed by the same line.

WHY THE EXISTING TESTS COULD NOT SEE IT
    `test_voucher_import.py` stubs `_create_journal` with a recording kernel that
    has no idempotency pre-check at all. These drive the REAL kernel over the e2e
    FakeDB, whose `post_journal_atomic` already ignores a discarded row exactly as
    the SQL does — so the only thing that can answer wrongly here is the Python
    pre-check, which is the thing under test.
"""
from __future__ import annotations

import pytest

import services.manual_journal_service as mjs
import services.phase2_journal_service as pjs
import services.voucher_import_service as svc
from domain.accounting import voucher_import as vi
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "FIRM-A"
CLIENT = "CLI"
DISCARDED_AT = "2026-05-01T09:00:00+00:00"


def _setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [svc, mjs])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("clients", {"id": CLIENT, "firm_id": FIRM, "financial_year_start": "2026-04-01"})
    rent = db.seed("chart_of_accounts", {
        "firm_id": FIRM, "client_id": CLIENT, "account_code": "5100",
        "account_name": "Rent Expense", "account_type": "Expense", "is_active": True})
    bank = db.seed("chart_of_accounts", {
        "firm_id": FIRM, "client_id": CLIENT, "account_code": "1001",
        "account_name": "HDFC Bank", "account_type": "Asset", "is_active": True})
    return db, rent["id"], bank["id"]


def _lines(rent, bank, amount=500_000):
    return [{"account_id": rent, "debit_paise": amount, "credit_paise": 0},
            {"account_id": bank, "debit_paise": 0, "credit_paise": amount}]


def _post(db, rent, bank, *, ref="JV-1", date="2026-04-05", is_posted=True):
    return pjs.phase2_journal_service._create_journal(
        db, firm_id=FIRM, client_id=CLIENT, entry_date=date, reference_no=ref,
        narration="x", entry_type="Journal", lines=_lines(rent, bank),
        is_posted=is_posted)


def _discard(db, entry_id):
    """What a discard leaves behind: the row stays, stamped `deleted_at`."""
    [row] = [e for e in db.rows("journal_entries") if e["id"] == entry_id]
    row["deleted_at"] = DISCARDED_AT


def _live(db, ref):
    return [e for e in db.rows("journal_entries")
            if e.get("reference_no") == ref and not e.get("deleted_at")]


def _lines_of(db, entry_id):
    return [l for l in db.rows("journal_lines") if l.get("journal_entry_id") == entry_id]


# ── the kernel's fast path agrees with its own unique index ──────────────────

def test_a_discarded_entry_does_not_answer_for_its_number(monkeypatch):
    db, rent, bank = _setup(monkeypatch)
    dead = _post(db, rent, bank, is_posted=False)
    _discard(db, dead)

    fresh = _post(db, rent, bank, is_posted=False)

    assert fresh != dead, "the kernel handed back the discarded entry's id and wrote nothing"
    assert [e["id"] for e in _live(db, "JV-1")] == [fresh]
    assert len(_lines_of(db, fresh)) == 2
    # The discarded entry is left exactly as it was: not revived, not edited.
    [dead_row] = [e for e in db.rows("journal_entries") if e["id"] == dead]
    assert dead_row["deleted_at"] == DISCARDED_AT
    assert len(_lines_of(db, dead)) == 2


def test_a_live_entry_still_answers_for_its_number(monkeypatch):
    """The control: the fix narrows the fast path to LIVE entries and does not
    remove it, so a genuine duplicate is still not written twice."""
    db, rent, bank = _setup(monkeypatch)
    first = _post(db, rent, bank)
    again = _post(db, rent, bank)
    assert again == first
    assert len(_live(db, "JV-1")) == 1
    assert len(_lines_of(db, first)) == 2


def test_a_live_entry_beside_a_discarded_one_is_the_one_that_answers(monkeypatch):
    db, rent, bank = _setup(monkeypatch)
    dead = _post(db, rent, bank, is_posted=False)
    _discard(db, dead)
    live = _post(db, rent, bank, is_posted=False)
    assert _post(db, rent, bank, is_posted=False) == live != dead


def test_the_single_journal_door_posts_over_a_discarded_number_too(monkeypatch):
    """`manual_journal_service.create` is the journal editor's door and had the
    same quirk: a draft discarded, the same number typed again, a success response
    carrying the dead entry's id."""
    db, rent, bank = _setup(monkeypatch)
    dead = _post(db, rent, bank, is_posted=False)
    _discard(db, dead)

    made = mjs.manual_journal_service.create(db, FIRM, {
        "client_id": CLIENT, "entry_date": "2026-04-05", "reference_no": "JV-1",
        "status": "draft", "lines": _lines(rent, bank)})

    assert made["id"] != dead
    assert [e["id"] for e in _live(db, "JV-1")] == [made["id"]]


# ── the import tells the truth about what it did ─────────────────────────────

def _legs(*numbers, amount=500_000):
    legs, row = [], 0
    for vno in numbers:
        row += 1
        legs.append(vi.Leg(row=row, voucher_no=vno, date="05-04-2026", voucher_type="Payment",
                           account="Rent Expense", debit_paise=amount, credit_paise=0,
                           narration=None, line_narration=None))
        row += 1
        legs.append(vi.Leg(row=row, voucher_no=vno, date="05-04-2026", voucher_type="Payment",
                           account="HDFC Bank", debit_paise=0, credit_paise=amount,
                           narration=None, line_narration=None))
    return legs


def _import(db, *numbers, status="draft"):
    return svc.import_vouchers(db, FIRM, CLIENT, legs=_legs(*numbers), status=status)


@pytest.mark.parametrize("status", ["draft", "posted"])
def test_a_re_upload_after_discarding_vouchers_posts_them_again(monkeypatch, status):
    """The scenario of the finding, end to end through the real kernel: import,
    discard two, upload the same sheet again. Every voucher the summary says it
    created is a LIVE entry carrying its lines."""
    db, *_ = _setup(monkeypatch)
    first = _import(db, "PV-1", "PV-2", "PV-3", status=status)
    assert (first["created"], first["rejected"]) == (3, 0)
    ids = {r["voucher_no"]: r["id"] for r in first["results"]}
    _discard(db, ids["PV-1"])
    _discard(db, ids["PV-3"])

    second = _import(db, "PV-1", "PV-2", "PV-3", status=status)

    assert second["created"] == 2 and second["already_recorded"] == 1
    assert second["created_paise"] == 2 * 500_000
    by_no = {r["voucher_no"]: r for r in second["results"]}
    assert by_no["PV-2"]["status"] == vi.ALREADY_RECORDED and by_no["PV-2"]["id"] == ids["PV-2"]
    for vno in ("PV-1", "PV-3"):
        made = by_no[vno]
        assert made["status"] == vi.NEW
        assert made["id"] not in ids.values(), f"{vno}: the id of an entry that was discarded"
        assert [e["id"] for e in _live(db, vno)] == [made["id"]]
        assert len(_lines_of(db, made["id"])) == 2


def test_every_id_the_import_reports_is_a_live_entry(monkeypatch):
    """The invariant behind the count: whatever a summary calls created or already
    recorded must be findable among the client's live entries. Stated over a mixed
    file (one live, one discarded, one never imported) so a count that is right by
    coincidence for one shape cannot pass."""
    db, *_ = _setup(monkeypatch)
    first = _import(db, "PV-1", "PV-2")
    _discard(db, {r["voucher_no"]: r["id"] for r in first["results"]}["PV-1"])

    out = _import(db, "PV-1", "PV-2", "PV-3")

    live_ids = {e["id"] for e in db.rows("journal_entries") if not e.get("deleted_at")}
    assert out["created"] == 2 and out["already_recorded"] == 1
    for r in out["results"]:
        assert r["id"] in live_ids, f"{r['voucher_no']} reported as {r['status']} with no live entry"
    assert len(live_ids) == 3
