"""
The cash-flow timing line must be accurate, or it will produce a fourth wrong model.

WHY THIS EXISTS
    "Cash flow takes 14 seconds" is not a diagnosis, and three attempts to guess
    which part owned those seconds were all wrong:

      1. three unbounded snapshot fetches — wrong, _base_cache dedupes them
      2. _base() is the cost — wrong, Trial Balance pays it too and took 2s
      3. the full-history replay is the cost — this one shipped, and bought
         about one second, because the PERIOD entries fetch (which the statement
         genuinely cannot avoid) was the cost all along

    Each model was plausible from reading the code and false against the system.
    The instrumentation is the correction: it reports where the time went instead
    of leaving it to inference. That only helps if the numbers are right, so the
    counts are asserted against fixtures whose true values are known here.

WHAT IS PINNED
    * the log fires, once, at INFO, on the fast path
    * entry / line / page counts match the fixture exactly
    * paging is counted per page, not per call — the page COUNT is the number
      that matters, since _fetch_all pages sequentially and wall-clock is
      roughly pages x round-trip
    * the date bounds are respected, so the counts describe the WINDOW and not
      the whole ledger — a count that silently covered all history would make
      the slow phase look inevitable
    * measuring does not change the measured value
"""
from __future__ import annotations

import logging
import re

import pytest

from domain.reporting.service import ReportingService
from domain.reporting.sources import SupabaseLedgerSource
from tests.test_passbook_read_path import CLIENT, FIRM, _DB, _entry
from tests.test_cash_flow_passbook_equivalence import _seed_store, _svc

FY = ("2026-04-01", "2027-03-31")


def _log_line(caplog) -> str:
    lines = [r.getMessage() for r in caplog.records
             if r.getMessage().startswith("reporting.cash_flow ")]
    assert len(lines) == 1, f"expected exactly one timing line, got {len(lines)}: {lines}"
    return lines[0]


@pytest.fixture
def cash_flow_log(monkeypatch, caplog):
    monkeypatch.setenv("REPORTING_PASSBOOK_MODE", "on")
    caplog.set_level(logging.INFO, logger="caflow.reporting.service")
    return caplog


def test_the_fast_path_logs_one_timing_line(cash_flow_log):
    _svc().cash_flow_statement(FIRM, CLIENT, *FY)
    line = _log_line(cash_flow_log)

    for phase in ("accounts=", "buckets=", "entries=", "opening=", "closing=", "build="):
        assert phase in line, f"{phase} missing from: {line}"
    assert "took=" in line
    assert f"window={FY[0]}..{FY[1]}" in line


def test_the_entry_and_line_counts_are_the_real_ones(cash_flow_log):
    """Counts are asserted against the fixture, not against themselves. Of the
    ten fixture entries, e1 (2025-05-10) and e2 (2025-06-15) fall in the prior
    year; the remaining eight — e3 on the FY start through e10 on the FY end —
    are in window, at two lines each."""
    _svc().cash_flow_statement(FIRM, CLIENT, *FY)
    line = _log_line(cash_flow_log)

    m = re.search(r"entries=[\d.]+s\((\d+) entries/(\d+) lines/(\d+) pages\)", line)
    assert m, f"entry stats not parseable from: {line}"
    entries, lines, pages = (int(g) for g in m.groups())

    assert entries == 8, f"expected the 8 in-window entries, logged {entries}"
    assert lines == 16, f"8 entries x 2 lines, logged {lines}"
    assert pages == 1, "an 8-entry fetch is one page"


def test_the_counts_describe_the_window_not_the_whole_ledger(cash_flow_log):
    """The point of the bounded fetch. A narrow window must log fewer entries
    than a wide one — if it logged the same, the date bounds are not reaching
    the query and the 'slow phase' would look unavoidable when it is not."""
    _svc().cash_flow_statement(FIRM, CLIENT, "2026-07-05", "2026-07-20")
    narrow = _log_line(cash_flow_log)
    narrow_n = int(re.search(r"entries=[\d.]+s\((\d+) entries", narrow).group(1))

    assert narrow_n == 3, f"2026-07-05..20 holds e6, e7, e8; logged {narrow_n}"
    assert narrow_n < 8, "the narrow window must read fewer entries than the full FY"


def test_paging_is_counted_per_page(monkeypatch, caplog):
    """The number that matters when a report is slow. _fetch_all pages
    sequentially, so wall-clock is roughly pages x round-trip; a stat that
    counted calls instead of pages would report 1 for a 13-round-trip fetch and
    hide the whole problem."""
    monkeypatch.setenv("REPORTING_PASSBOOK_MODE", "on")
    caplog.set_level(logging.INFO, logger="caflow.reporting.service")

    store = _seed_store()
    # 2 full pages + a short one, with _PAGE forced small so the fixture stays
    # readable. All inside the FY window.
    store["journal_entries"] = [
        _entry(f"p{i:04d}", "2026-06-15", [("bank", 100, 0), ("rev", 0, 100)])
        for i in range(5)
    ]
    monkeypatch.setattr(SupabaseLedgerSource, "_PAGE", 2)
    ReportingService(SupabaseLedgerSource(_DB(store))).cash_flow_statement(FIRM, CLIENT, *FY)

    m = re.search(r"entries=[\d.]+s\((\d+) entries/(\d+) lines/(\d+) pages\)", _log_line(caplog))
    assert (int(m.group(1)), int(m.group(3))) == (5, 3), (
        f"5 rows at 2/page is 3 pages (2+2+1); logged {m.group(1)} rows / {m.group(3)} pages")


def test_the_bucket_read_is_reported_too(cash_flow_log):
    """The other fetch on this path. Without it, a slow buckets read would be
    invisible and the entries phase would take the blame."""
    _svc().cash_flow_statement(FIRM, CLIENT, *FY)

    assert re.search(r"buckets=[\d.]+s\(\d+ rows/\d+ pages\)", _log_line(cash_flow_log))


def test_the_phases_account_for_the_total(cash_flow_log):
    """A breakdown that does not add up is worse than none — it sends the next
    person after a phantom. Allows a small margin for the untimed glue between
    phases (building bank_ids, the sort key)."""
    _svc().cash_flow_statement(FIRM, CLIENT, *FY)
    line = _log_line(cash_flow_log)

    total = float(re.search(r"took=([\d.]+)s", line).group(1))
    phases = sum(float(v) for v in re.findall(r"(?:accounts|buckets|entries|opening|closing|build)="
                                              r"([\d.]+)s", line))
    assert phases <= total + 0.01, f"phases {phases:.4f}s exceed total {total:.4f}s"
    assert total - phases < 0.5, f"{total - phases:.4f}s unaccounted for outside the phases"


def test_measuring_does_not_change_the_measurement(monkeypatch):
    """The statement must be identical with instrumentation to what the legacy
    replay produces — the equivalence suite proves that generally, this pins it
    against the specific code path the timing calls wrap."""
    monkeypatch.setenv("REPORTING_PASSBOOK_MODE", "off")
    legacy = _svc().cash_flow_statement(FIRM, CLIENT, *FY)
    monkeypatch.setenv("REPORTING_PASSBOOK_MODE", "on")

    assert _svc().cash_flow_statement(FIRM, CLIENT, *FY) == legacy


def test_the_legacy_path_logs_nothing_new(monkeypatch, caplog):
    """The fallback already logs through reporting._base. A second line from
    there would double-count and confuse the two paths."""
    monkeypatch.setenv("REPORTING_PASSBOOK_MODE", "off")
    caplog.set_level(logging.INFO, logger="caflow.reporting.service")
    _svc().cash_flow_statement(FIRM, CLIENT, *FY)

    assert not [r for r in caplog.records if "reporting.cash_flow " in r.getMessage()]


def test_stats_are_optional_everywhere_they_are_offered():
    """Every other caller passes no stats. If the parameter were required, or
    filled a shared dict, this would fail — instrumentation must not become a
    correctness dependency."""
    src = SupabaseLedgerSource(_DB(_seed_store()))

    assert src.fetch_buckets(FIRM, CLIENT)
    assert src._entries(FIRM, CLIENT)
