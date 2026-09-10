"""
One question, two kinds of closed, asked where it belongs (ACC-12, ACC-27).

WHAT WAS WRONG
    "Is this period closed" had three answers and they were enforced in three
    different places, so no path asked all three:

      * the FIRM's locked financial year — period_validation_service, called
        from 67 router call sites;
      * a filed RETURN covering the date — period_lock_service.assert_open,
        called from exactly two files, sales_invoices.py and purchase_bills.py;
      * this CLIENT's finalised year-end — the posting kernel, and nowhere else.

    The asymmetry the finding leads with: GSTR-3B for June is filed on 20 July.
    On 25 July the CA tries to EDIT a June journal and is refused with a clear
    sentence. On the same day they post a NEW June journal and it goes through
    silently.

    Migration 361 puts all three behind one definition and splits them by KIND
    rather than by caller:

      * `period_closure_reason` — the two DELIBERATE closures. The posting
        KERNEL asks this, so nothing reaches the ledger without it, and it is
        the same single round trip the kernel already made.
      * `period_lock_reason` — those two, then a filed return. Asked where a
        document that FEEDS a return is written, and by the manual journal,
        which can move any account including the tax ledgers.

THE SPLIT IS THE DESIGN, AND THE CALENDAR IS WHY
    The finding's suggested fix says "move the filed-return check into
    _create_journal" and then, in the same sentence, "make it a
    warning-with-override for postings ... but keep it a hard refusal for
    edits". Taking the first half without the second freezes the practice:
    GSTR-1 for June is filed on 11 July and GSTR-3B on the 20th, while June's
    bank reconciliation happens after both, every month, for every client. A
    hard refusal on every posting dated in June would stop June receipts, June
    payments, June bank entries, June depreciation and June payroll accruals
    from 11 July onwards — and would overturn from underneath the argued
    decision in receipt_service.py that a receipt is deliberately NOT locked by
    a filed return.

    A filed return freezes what it REPORTED. A closure freezes the books.

AND THE DATE THAT BOUGHT ITS WAY PAST IT (ACC-27)
    The kernel parsed `entry_date` with `date.fromisoformat` and, on failure,
    set the date to None and SKIPPED the lock. Two layers parse this string
    differently — period_validation_service uses `strptime("%Y-%m-%d")`, which
    accepts "2025-4-1" — so a single-digit month passed the firm check, failed
    the kernel's parse, and was posted into a client year that year-end
    finalisation had closed. Postgres then stored it happily: it is a perfectly
    valid DATE.

    A value the control cannot read must never be the value that gets past it.
"""
from __future__ import annotations

import pytest

from tests.e2e_harness import FakeDB

FIRM = "F1"
CLIENT = "C1"
OTHER_CLIENT = "C2"

_MJ_LINES = [{"account_id": "a1", "debit_paise": 100, "credit_paise": 0},
             {"account_id": "a2", "debit_paise": 0, "credit_paise": 100}]


def _lines():
    return [
        {"account_id": "a1", "debit_paise": 10_000_00, "credit_paise": 0},
        {"account_id": "a2", "debit_paise": 0, "credit_paise": 10_000_00},
    ]


def _post(db, client_id: str, entry_date: str, ref: str) -> str:
    from services.phase2_journal_service import Phase2JournalService
    return Phase2JournalService()._create_journal(
        db, FIRM, client_id, entry_date, ref, "n", "Journal", _lines(),
    )


def _manual(db, entry_date: str, status: str = "posted", client_id: str = CLIENT):
    from services.manual_journal_service import ManualJournalService
    return ManualJournalService().create(db, FIRM, {
        "client_id": client_id, "entry_date": entry_date, "status": status,
        "lines": list(_MJ_LINES),
    })


def _filed(db, client_id=CLIENT, ftype="GSTR-1", start="2026-06-01",
           end="2026-06-30", filed="2026-07-11", deleted=None):
    db.seed("filings", {
        "id": f"FIL-{ftype}-{start}-{client_id}", "client_id": client_id,
        "filing_type": ftype, "period_start": start, "period_end": end,
        "filed_date": filed, "deleted_at": deleted,
    })


@pytest.fixture()
def db():
    return FakeDB()


# ── A filed return does NOT stop the kernel, and that is the decision ────────

def test_a_filed_return_does_not_stop_an_ordinary_posting(db):
    """The June receipt entered on 15 July, after GSTR-1 for June went on the
    11th. This is the single most common thing an Indian practice does in the
    second week of a month, and a hard kernel refusal would forbid it."""
    _filed(db)
    assert _post(db, CLIENT, "2026-06-15", "REF-1")


def test_the_receipt_decision_is_not_overturned_from_underneath(db):
    """services/receipt_service.py argues, and
    test_documents_locked_by_filed_return.py pins, that a receipt is
    deliberately NOT locked by a filed return: `public.filings` records only
    GSTR-1 and GSTR-3B, returns of SUPPLIES, and a receipt moves Bank and
    Debtors. Putting the filed-return branch in the KERNEL would have reversed
    that decision silently — the source-inspection test that pins it would still
    have passed, because receipt_service's own source would not have changed."""
    _filed(db, ftype="GSTR-3B", filed="2026-07-20")
    assert _post(db, CLIENT, "2026-06-20", "REF-2")


# ── ...but it stops the free-form posting, which is the finding's own case ───

def test_a_manual_journal_created_into_a_filed_period_is_refused(db):
    """A manual journal can credit GST Output Payable or debit an ITC ledger
    directly, so it is exactly what a filed return has to stop. Editing one was
    already refused (migration 266); creating one was not."""
    from fastapi import HTTPException
    _filed(db)
    with pytest.raises(HTTPException) as e:
        _manual(db, "2026-06-15")
    assert e.value.status_code == 422
    assert "GSTR-1 covering this date was filed on 11 Jul 2026" in str(e.value.detail)
    assert "reversal and an amendment in the next return" in str(e.value.detail)


def test_the_first_and_last_day_of_the_filed_period_are_closed_to_it(db):
    from fastapi import HTTPException
    _filed(db)
    for day in ("2026-06-01", "2026-06-30"):
        with pytest.raises(HTTPException, match="was filed"):
            _manual(db, day)


def test_a_date_outside_the_filed_period_is_open(db):
    _filed(db)
    assert _manual(db, "2026-07-01")


def test_a_manual_DRAFT_into_a_filed_period_is_allowed_and_checked_at_posting(db):
    """A draft is off the books. It is checked when it reaches them —
    journal_posting_service.post_draft already asks the whole rule, because a
    draft raised in June and approved in September posts with its JUNE date."""
    import inspect
    from services import journal_posting_service as jps
    _filed(db)
    assert _manual(db, "2026-06-15", status="draft")
    assert "period_lock_service.assert_open" in inspect.getsource(jps), (
        "post_draft must ask the whole rule — a draft created before a return "
        "was filed can be posted after it")


def test_a_prepared_but_unfiled_return_locks_nothing(db):
    _filed(db, filed=None)
    assert _manual(db, "2026-06-15")


def test_a_deleted_filing_locks_nothing(db):
    """A return recorded by mistake and removed must reopen the period — the
    path test_unfiled_returns_can_be_deleted_and_rechecked.py exists for."""
    _filed(db, deleted="2026-08-01T00:00:00Z")
    assert _manual(db, "2026-06-15")


def test_another_clients_filed_return_locks_nothing(db):
    """`filings` has no firm_id — it is scoped by client — so a scope error here
    would stop one client's books because another client filed."""
    _filed(db, client_id=OTHER_CLIENT)
    assert _manual(db, "2026-06-15")


# ── The firm's own lock now reaches the kernel too ───────────────────────────

def test_the_firms_locked_year_is_refused_by_the_kernel(db):
    """It was enforced only at the routers, so a path that never went through
    one — a scheduled accrual, a service-layer posting, a job — did not see
    it."""
    db.seed("firms", {"id": FIRM, "locked_financial_years": ["2026-27"]})
    with pytest.raises(ValueError, match="Financial year 2026-27 is locked"):
        _post(db, CLIENT, "2026-06-15", "REF-3")


def test_the_clients_finalised_year_is_still_refused_by_the_kernel(db):
    """The branch the kernel already had, moved into the shared definition
    rather than lost — test_client_year_lock_enforced.py holds the rest."""
    db.seed("client_year_locks", {"id": "L1", "firm_id": FIRM, "client_id": CLIENT,
                                  "financial_year": "2026-27"})
    with pytest.raises(ValueError, match="closed for this client"):
        _post(db, CLIENT, "2026-06-15", "REF-4")


def test_the_firms_lock_outranks_the_clients_year_end(db):
    """Both at once names the FIRM's lock, because unlocking the year is what
    the CA has to do first and is the one they already know they did."""
    db.seed("firms", {"id": FIRM, "locked_financial_years": ["2026-27"]})
    db.seed("client_year_locks", {"id": "L1", "firm_id": FIRM, "client_id": CLIENT,
                                  "financial_year": "2026-27"})
    with pytest.raises(ValueError, match="Financial year 2026-27 is locked"):
        _post(db, CLIENT, "2026-06-15", "REF-5")


def test_a_finalised_client_year_outranks_a_filed_return(db):
    """On the path that asks both. Reopening a year is undoable; amending a
    filed return is not, so telling the CA to amend when all they need to do is
    reopen sends them to the portal for nothing."""
    from fastapi import HTTPException
    db.seed("client_year_locks", {"id": "L1", "firm_id": FIRM, "client_id": CLIENT,
                                  "financial_year": "2026-27"})
    _filed(db)
    with pytest.raises(HTTPException) as e:
        _manual(db, "2026-06-15")
    assert "closed for this client" in str(e.value.detail)


# ── ACC-27: the date that used to buy its way past the lock ──────────────────

def test_a_single_digit_month_is_refused_rather_than_skipping_the_lock(db):
    """The exact value. `strptime("%Y-%m-%d")` accepts "2025-4-1" and
    `date.fromisoformat` does not, so this passed the firm-level check, failed
    the kernel's parse, and — before this change — was posted into a client
    year that had been closed."""
    db.seed("client_year_locks", {"id": "L1", "firm_id": FIRM, "client_id": CLIENT,
                                  "financial_year": "2025-26"})
    with pytest.raises(ValueError, match="is not a posting date"):
        _post(db, CLIENT, "2025-4-1", "REF-6")


@pytest.mark.parametrize("bad", ["2025-4-1", "01-04-2025", "", "today", "2025-13-01"])
def test_nothing_that_is_not_an_iso_date_reaches_the_ledger(db, bad):
    with pytest.raises(ValueError):
        _post(db, CLIENT, bad, f"REF-BAD-{bad}")


def test_the_pydantic_boundary_refuses_it_first(db):
    """Two checks for one rule, deliberately: the kernel is reached by paths
    that never construct a model, and a request that does construct one should
    be told at the field rather than at the ledger."""
    from pydantic import ValidationError
    from models.accounting import JournalEntryIn, JournalEntryUpdateIn, JournalLineIn

    line = JournalLineIn(account_id="a1", debit_paise=100, credit_paise=0)
    line2 = JournalLineIn(account_id="a2", debit_paise=0, credit_paise=100)
    with pytest.raises(ValidationError, match="ISO date"):
        JournalEntryIn(client_id=CLIENT, entry_date="2025-4-1", lines=[line, line2])
    with pytest.raises(ValidationError, match="ISO date"):
        JournalEntryUpdateIn(entry_date="2025-4-1")

    # ...and a real one still passes, both ways round.
    assert JournalEntryIn(client_id=CLIENT, entry_date="2025-04-01",
                          lines=[line, line2]).entry_date == "2025-04-01"
    assert JournalEntryUpdateIn(entry_date=None).entry_date is None


# ── Fail closed ──────────────────────────────────────────────────────────────

def test_a_source_that_cannot_answer_refuses_the_posting(db):
    """A check that could not be completed is not a period that is open. A
    posting wrongly allowed into a closed year is not recoverable from the UI."""
    class _Boom:
        def execute(self):
            raise RuntimeError("connection reset")

    real = db.rpc

    def _rpc(name, params=None):
        if name in ("period_closure_reason", "period_lock_reason",
                    "journal_period_lock_reason"):
            return _Boom()
        return real(name, params)

    db.rpc = _rpc
    with pytest.raises(ValueError, match="Could not confirm this period is open"):
        _post(db, CLIENT, "2026-06-15", "REF-7")


def test_the_two_questions_can_share_one_cache(db):
    """The same (firm, client, date) is OPEN to a closure and CLOSED to a filed
    return, so the memo key carries WHICH question was asked.

    Made structural rather than documented: a caller who passes one dict to both
    would otherwise get whichever was asked first, silently, and only once a
    return had been filed — the hardest kind of bug to find."""
    from services import period_lock_service as pls
    _filed(db)

    shared: dict = {}
    assert pls.closure_reason(db, FIRM, CLIENT, "2026-06-15", shared) is None
    assert shared, "the open closure answer should be remembered"
    assert "was filed" in (pls.lock_reason(db, FIRM, CLIENT, "2026-06-15", shared) or ""), (
        "the closure's OPEN answer hid the filed return — the memo key must "
        "name the question"
    )
    assert len(shared) == 1, "a closed period must never be remembered"


def test_the_cache_never_remembers_a_closed_period(db):
    """The bulk-import memo caches the OPEN answer only, so a refusal is never
    cheaper to forget."""
    from services import period_lock_service as pls
    db.seed("firms", {"id": FIRM, "locked_financial_years": ["2026-27"]})
    cache: dict = {}
    assert pls.closure_reason(db, FIRM, CLIENT, "2026-06-15", cache)
    assert cache == {}, "a closed period must never be remembered"
