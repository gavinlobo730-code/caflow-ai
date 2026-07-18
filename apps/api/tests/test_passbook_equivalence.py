"""
Passbook (monthly balance cache) — Phase 1 correctness.

The entire safety argument for the passbook is this: a report computed from the
monthly buckets must equal the SAME report computed the old way (replaying every
raw posted line), to the paise. These tests lock that invariant for Trial
Balance, P&L and Balance Sheet across month-aligned windows, arbitrary mid-month
dates (which exercise partial-edge-month replay), reversals (net-zero pairs), and
cumulative as-of-date views.

Pure — no database. If any of these ever fail, the passbook must NOT feed a live
report.
"""
from __future__ import annotations

from domain.reporting import builders
from domain.reporting.balance_cache import build_buckets, month_of, project_lines
from domain.reporting.model import Account, JournalEntry, JournalLine, ProjectedLine

ACCOUNTS = {
    "bank": Account("bank", "1000", "Bank", "Asset", "Bank", "bank"),
    "ar":   Account("ar", "1100", "Trade Receivables", "Asset", "Receivable", "ar"),
    "rev":  Account("rev", "4000", "Sales", "Revenue", None, None),
    "gst":  Account("gst", "2100", "GST Output", "Liability", None, "gst_output"),
    "exp":  Account("exp", "5000", "Rent", "Expense", None, None),
    "cap":  Account("cap", "3000", "Capital", "Equity", None, None),
}


def _je(eid, date, lines):
    return JournalEntry(id=eid, entry_date=date, client_id="C", firm_id="F",
                        entry_type="X", lines=tuple(JournalLine(*l) for l in lines))


# A small but representative history spanning two financial years, including a
# same-month reversal and two same-month entries either side of a mid-month cut.
ENTRIES = [
    _je("e1", "2025-05-10", [("bank", 100000, 0), ("cap", 0, 100000)]),          # capital intro
    _je("e2", "2025-06-15", [("ar", 11800, 0), ("rev", 0, 10000), ("gst", 0, 1800)]),  # credit sale
    _je("e3", "2025-06-20", [("bank", 11800, 0), ("ar", 0, 11800)]),             # receipt
    _je("e4", "2026-04-05", [("exp", 5000, 0), ("bank", 0, 5000)]),              # rent (next FY)
    _je("e5", "2026-04-18", [("ar", 5900, 0), ("rev", 0, 5000), ("gst", 0, 900)]),   # sale…
    _je("e5r", "2026-04-25", [("ar", 0, 5900), ("rev", 5000, 0), ("gst", 900, 0)]),  # …reversed
    _je("e6", "2026-07-10", [("exp", 2000, 0), ("bank", 0, 2000)]),              # before the 18th
    _je("e7", "2026-07-25", [("exp", 3000, 0), ("bank", 0, 3000)]),              # after the 18th
]


def _raw_lines(start, end):
    """The old path: every raw posted line whose entry_date is in [start, end]."""
    out = []
    for e in ENTRIES:
        if start and e.entry_date < start:
            continue
        if end and e.entry_date > end:
            continue
        for ln in e.lines:
            out.append(ProjectedLine(ln.account_id, ln.debit_paise, ln.credit_paise))
    return out


def _bucket_lines(start, end):
    """The new path: reconstruct the stream from monthly buckets (+ edge replay)."""
    return project_lines(build_buckets(ENTRIES), start, end, edge_entries=ENTRIES)


# Windows the reports actually request, plus adversarial mid-month cuts.
WINDOWS = [
    ("FY 2025-26", "2025-04-01", "2026-03-31"),      # month-aligned full year
    ("FY 2026-27", "2026-04-01", "2027-03-31"),      # includes the reversal (nets to 0)
    ("Q1 2025-26", "2025-04-01", "2025-06-30"),      # month-aligned quarter
    ("single month 2026-04", "2026-04-01", "2026-04-30"),  # reversal month, nets to 0
    ("mid-month cut", "2026-07-05", "2026-07-20"),   # BOTH edges partial -> full replay of July
    ("as-of month-end", None, "2026-03-31"),         # cumulative, aligned end
    ("as-of mid-month", None, "2026-07-18"),         # cumulative, partial end -> edge replay
]


def test_trial_balance_matches_raw_across_windows():
    for label, start, end in WINDOWS:
        raw = builders.trial_balance(_raw_lines(start, end), ACCOUNTS, end, "accrual")
        buck = builders.trial_balance(_bucket_lines(start, end), ACCOUNTS, end, "accrual")
        assert buck == raw, f"trial balance differs for window: {label}"


def test_profit_loss_matches_raw_across_windows():
    for label, start, end in WINDOWS:
        s = start or "2000-01-01"
        raw = builders.profit_loss(_raw_lines(start, end), ACCOUNTS, s, end or "2100-01-01", "accrual")
        buck = builders.profit_loss(_bucket_lines(start, end), ACCOUNTS, s, end or "2100-01-01", "accrual")
        assert buck == raw, f"P&L differs for window: {label}"


def test_balance_sheet_matches_raw_across_windows():
    for label, start, end in WINDOWS:
        raw = builders.balance_sheet(_raw_lines(start, end), ACCOUNTS, end, "accrual")
        buck = builders.balance_sheet(_bucket_lines(start, end), ACCOUNTS, end, "accrual")
        assert buck == raw, f"balance sheet differs for window: {label}"


def test_month_aligned_windows_need_no_edge_replay():
    # For a window whose edges are month boundaries, the buckets alone must be
    # exact — passing NO edge entries must give the same result as passing them.
    for label, start, end in WINDOWS:
        aligned = (start is None or start.endswith("-01")) and _is_aligned_end(end)
        if not aligned:
            continue
        b = build_buckets(ENTRIES)
        with_edges = project_lines(b, start, end, edge_entries=ENTRIES)
        no_edges = project_lines(b, start, end, edge_entries=())
        assert _norm(with_edges) == _norm(no_edges), f"aligned window needed replay: {label}"


def test_mid_month_cut_excludes_later_same_month_entry():
    # As-of the 18th: the 10th's expense is in, the 25th's is out. This is the
    # exact partial-month case buckets alone would get wrong without edge replay.
    lines = _bucket_lines(None, "2026-07-18")
    by_acct = {l.account_id: l for l in lines}
    # Bank: 100000 in − 5000 (Apr rent) − 2000 (Jul 10) = 93000 debit; the Jul 25
    # −3000 must NOT be included. (June sale/receipt/reversal net to their values.)
    # Assert the July 25 entry is excluded by checking expense total = 5000 + 2000.
    assert by_acct["exp"].debit_paise == 7000, "the 25th's expense leaked past the as-of date"


def test_build_buckets_definition():
    b = build_buckets(ENTRIES)
    # June 2025 has the credit sale: AR debit 11800 in 2025-06, plus the receipt's
    # AR credit 11800 in the same month -> AR June bucket = (11800, 11800).
    assert b[("ar", "2025-06-01")] == (11800, 11800)
    # April 2026 rev: sale credit 5000 and reversal debit 5000 -> (5000, 5000).
    assert b[("rev", "2026-04-01")] == (5000, 5000)
    assert month_of("2026-07-25") == "2026-07-01"


# ── helpers ───────────────────────────────────────────────────────────────────

def _is_aligned_end(end):
    if end is None:
        return True
    import calendar
    y, m, d = int(end[:4]), int(end[5:7]), int(end[8:10])
    return d == calendar.monthrange(y, m)[1]


def _norm(lines):
    return sorted((l.account_id, l.debit_paise, l.credit_paise) for l in lines)
