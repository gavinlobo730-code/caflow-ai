"""
The payroll accrual belongs to the payroll MONTH, not to the button press.

WHAT WAS WRONG
    journal_for_payroll posted with

        entry_date=str(datetime.now(timezone.utc).date())

    when the run already carried its period in `run["month"]`. Two consequences,
    both in books this firm produces for a client:

      * Finalising August's payroll on 3 September dated the accrual
        3 September. August's profit and loss carried no salary cost at all and
        September carried two months of it.
      * The date came off a UTC clock. The container is python:3.11-slim with no
        timezone pinned, so between 00:00 and 05:30 IST the UTC date is the day
        before — and a March run finalised in that window on 1 April crosses a
        FINANCIAL YEAR boundary, which is the one date error the year-end close
        cannot absorb.

    It also broke the idempotency the same method relies on: _create_journal
    dedupes on (client, reference_no, entry_date), and with `today` in the key a
    re-finalisation on a later calendar day produced a SECOND accrual for the
    same month. routers/payroll.py's own comment says so.

NEGATIVE CONTROL
    Restore `entry_date=str(datetime.now(timezone.utc).date())` and
    test_accrual_is_dated_to_the_payroll_month_end fails, because the recorded
    date is today rather than the month end.
"""
from __future__ import annotations

import pytest

from core.ist_clock import month_end_date
from services.phase2_journal_service import Phase2JournalService


# ── the shared helper ────────────────────────────────────────────────────────

@pytest.mark.parametrize("period, expected", [
    ("2026-08", "2026-08-31"),
    ("2026-04", "2026-04-30"),
    ("2026-02", "2026-02-28"),
    ("2024-02", "2024-02-29"),   # a leap February, which a hardcoded 28 gets wrong
    ("2026-12", "2026-12-31"),
    ("2026-01", "2026-01-31"),
])
def test_month_end_date(period, expected):
    assert month_end_date(period) == expected


@pytest.mark.parametrize("bad", ["", None, "2026", "2026-13", "2026-00", "August 2026", "2026-8"])
def test_month_end_date_refuses_anything_that_is_not_a_period(bad):
    """A caller that cannot name its period has no business choosing an
    accounting date for it. Falling back to today is the bug this replaces."""
    with pytest.raises(ValueError):
        month_end_date(bad)


# ── the accrual ──────────────────────────────────────────────────────────────

class _Recorder:
    """Captures what journal_for_payroll would post, without a database."""
    def __init__(self):
        self.calls = []

    def __call__(self, **kw):
        self.calls.append(kw)
        return "je-1"


def _run(month="2026-08"):
    return {
        "id": "run-1", "month": month,
        "total_gross_paise": 100000, "total_net_paise": 67250,
        "total_pf_paise": 24000, "total_esi_paise": 4000,
        "total_pt_paise": 20000, "total_tds_paise": 0,
    }


@pytest.fixture
def posted(monkeypatch):
    """journal_for_payroll returns early under _USE_MOCK (no SUPABASE_URL), so
    the real branch is reached by turning that off and standing in for the two
    things it needs: the client and the account lookups."""
    import services.phase2_journal_service as mod
    monkeypatch.setattr(mod, "_USE_MOCK", False)
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: object(), raising=False)
    svc = Phase2JournalService()
    rec = _Recorder()
    monkeypatch.setattr(svc, "_create_journal", rec)
    monkeypatch.setattr(svc, "_find_account", lambda *a, **k: "acc-x")
    return svc, rec


def test_accrual_is_dated_to_the_payroll_month_end(posted):
    svc, rec = posted
    svc.journal_for_payroll(_run("2026-08"), "firm-1", "client-1")
    assert rec.calls, "the accrual must be posted"
    assert rec.calls[0]["entry_date"] == "2026-08-31", (
        "August's salary cost belongs in August, whenever the CA pressed Finalize")


def test_a_march_run_stays_in_its_financial_year(posted):
    """The case the UTC clock got wrong: FY 2025-26 ends 31 March 2026, and a
    run finalised just after midnight IST on 1 April was dated into FY 2026-27."""
    svc, rec = posted
    svc.journal_for_payroll(_run("2026-03"), "firm-1", "client-1")
    assert rec.calls[0]["entry_date"] == "2026-03-31"


def test_the_date_does_not_depend_on_when_it_is_run(posted):
    """Two finalisations of the same month produce the same accounting date —
    which is also what makes _create_journal's (client, reference_no,
    entry_date) dedup catch a re-finalisation on a later day."""
    svc, rec = posted
    svc.journal_for_payroll(_run("2026-08"), "firm-1", "client-1")
    svc.journal_for_payroll(_run("2026-08"), "firm-1", "client-1")
    assert rec.calls[0]["entry_date"] == rec.calls[1]["entry_date"]
    assert rec.calls[0]["reference_no"] == rec.calls[1]["reference_no"] == "PAY-2026-08"
