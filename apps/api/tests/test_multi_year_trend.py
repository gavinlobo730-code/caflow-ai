"""
The multi-year trend statement.

TWO THINGS THIS HAS TO GET RIGHT, AND THEY PULL IN OPPOSITE DIRECTIONS

    It must read ONE set of numbers with the statements — a trend whose Revenue
    from Operations differs from the statement's invites a CA to explain a
    movement that is really a difference in method.

    And it must not COST what five statements cost. On the passbook path every
    report begins by fetching the client's whole bucket set, and schedule_iii
    now computes its preceding year too — so five years the obvious way is
    twenty reads of one table. A financial year is month-aligned, so the whole
    window projects from a single fetch.

    The first is proved by comparing against build_schedule_iii; the second by
    counting the fetches.
"""
import pytest

from domain.reporting import (
    Account, JournalEntry, JournalLine, InMemoryLedgerSource, ReportingService,
)
from domain.reporting.sources import SupabaseLedgerSource
from domain.reporting import balance_cache, trend
from domain.reporting.schedule_iii import build_schedule_iii

FIRM, CLIENT = "firm-trend", "client-trend"
L = 1_00_000_00

ACCOUNTS = [
    Account("bank", "1000", "Bank",              "Asset",     "Bank", system_key="bank"),
    Account("ar",   "1100", "Trade Receivables", "Asset",     "Receivable", system_key="ar"),
    Account("inv",  "1200", "Inventory",         "Asset",     "Inventory"),
    Account("fa",   "1500", "Plant & Machinery", "Asset",     "Fixed Asset"),
    Account("ap",   "2150", "Trade Payables",    "Liability", "Payable", system_key="ap"),
    Account("ltl",  "2500", "Term Loan",         "Liability", "Long Term Loan"),
    Account("cap",  "3000", "Share Capital",     "Equity",    "Share Capital"),
    Account("rev",  "4000", "Sales",             "Revenue",   "Sales"),
    Account("cogs", "5000", "Cost of Materials", "Expense",   "Raw Material"),
    Account("sal",  "5100", "Salaries",          "Expense",   "Employee Benefit"),
    Account("int",  "5200", "Interest",          "Expense",   "Finance Cost"),
]


def je(jid, lines, when):
    return JournalEntry(id=jid, entry_date=when, client_id=CLIENT, firm_id=FIRM,
                        entry_type="x", lines=tuple(JournalLine(*l) for l in lines))


# Three trading years, growing. Nothing at all in 2023-24, which is the year the
# document must DROP rather than show as zeros.
ENTRIES = [
    je("open", [("bank", 10 * L, 0), ("fa", 20 * L, 0), ("cap", 0, 20 * L),
                ("ltl", 0, 10 * L)], "2024-04-01"),
    # FY 2024-25
    je("s1", [("ar", 40 * L, 0), ("rev", 0, 40 * L)], "2024-09-30"),
    je("c1", [("cogs", 24 * L, 0), ("ap", 0, 24 * L)], "2024-09-30"),
    je("w1", [("sal", 8 * L, 0), ("bank", 0, 8 * L)], "2025-01-31"),
    je("i1", [("int", 1 * L, 0), ("bank", 0, 1 * L)], "2025-03-31"),
    # FY 2025-26
    je("s2", [("ar", 60 * L, 0), ("rev", 0, 60 * L)], "2025-09-30"),
    je("c2", [("cogs", 35 * L, 0), ("ap", 0, 35 * L)], "2025-09-30"),
    je("w2", [("sal", 10 * L, 0), ("bank", 0, 10 * L)], "2026-01-31"),
    je("i2", [("int", 1 * L, 0), ("bank", 0, 1 * L)], "2026-03-31"),
    # FY 2026-27
    je("s3", [("ar", 75 * L, 0), ("rev", 0, 75 * L)], "2026-09-30"),
    je("c3", [("cogs", 44 * L, 0), ("ap", 0, 44 * L)], "2026-09-30"),
    je("w3", [("sal", 12 * L, 0), ("bank", 0, 12 * L)], "2027-01-31"),
    je("i3", [("int", 1 * L, 0), ("bank", 0, 1 * L)], "2027-03-31"),
]

FYS = ["2023-24", "2024-25", "2025-26", "2026-27"]


@pytest.fixture()
def svc():
    return ReportingService(InMemoryLedgerSource(accounts=ACCOUNTS, entries=list(ENTRIES)))


def _line(doc, section, label):
    return next(l for l in doc[section] if l["label"] == label)


# ── One set of numbers with the statements ───────────────────────────────────

def test_every_trend_figure_equals_the_statement_for_that_year(svc):
    """The property the whole design rests on. If these differ, a CA reading the
    trend and a CA reading the statement are looking at two businesses."""
    doc = svc.multi_year_trend(FIRM, CLIENT, FYS)
    for i, fy in enumerate(doc["fys"]):
        start, end = f"{fy[:4]}-04-01", f"{int(fy[:4]) + 1}-03-31"
        pl = svc.profit_loss(FIRM, CLIENT, start, end, basis="accrual")
        bs = svc.balance_sheet(FIRM, CLIENT, end, basis="accrual")
        stmt = build_schedule_iii(pl, bs, start, end)

        assert _line(doc, "profit_and_loss", "Revenue from Operations")["values_paise"][i] == \
            next(l["paise"] for s in stmt["profit_and_loss"]["revenue"]
                 for l in s["lines"] if l["label"] == "Revenue from Operations")
        assert _line(doc, "profit_and_loss", "Profit After Tax")["values_paise"][i] == \
            stmt["profit_and_loss"]["profit_after_tax_paise"]
        assert _line(doc, "balance_sheet", "Trade Receivables")["values_paise"][i] == \
            next(l["paise"] for s in stmt["balance_sheet"]["assets"]
                 for l in s["lines"] if l["label"] == "Trade Receivables")


def test_the_ratios_are_the_clause_q_ratios(svc):
    """Not a second set of definitions. A current ratio that means something
    different here from the note is worse than not showing one."""
    from domain.reporting import ratios as R
    doc = svc.multi_year_trend(FIRM, CLIENT, FYS)
    keys = [r["key"] for r in doc["ratios"]]
    reference = [r["key"] for r in R.build(R.Components())["ratios"]]
    assert keys == reference

    last = doc["fys"][-1]
    start, end = f"{last[:4]}-04-01", f"{int(last[:4]) + 1}-03-31"
    note = R.build(R.components_from(
        svc.profit_loss(FIRM, CLIENT, start, end, basis="accrual"),
        svc.balance_sheet(FIRM, CLIENT, end, basis="accrual")))
    for series, spec in zip(doc["ratios"], note["ratios"]):
        assert series["values_bps"][-1] == spec["value_bps"], series["key"]


# ── The window ───────────────────────────────────────────────────────────────

def test_a_year_with_nothing_recorded_is_dropped_not_zeroed(svc):
    """A column of zeros asserts the business had nil revenue and nil assets
    that year. That is a claim about the business, not about the records."""
    doc = svc.multi_year_trend(FIRM, CLIENT, FYS)
    assert doc["fys"] == ["2024-25", "2025-26", "2026-27"]
    assert doc["dropped_fys"] == ["2023-24"]
    assert doc["requested_fys"] == FYS
    assert "years_without_records_dropped" in [g["code"] for g in doc["gaps"]]


def test_the_years_are_in_chronological_order(svc):
    doc = svc.multi_year_trend(FIRM, CLIENT, FYS)
    assert doc["fys"] == sorted(doc["fys"])


def test_it_says_it_is_not_a_statutory_statement(svc):
    """Schedule III para 5 wants ONE comparative. Five years is a management
    view, and presenting it as the statements would be the mistake."""
    doc = svc.multi_year_trend(FIRM, CLIENT, FYS)
    assert "not a statutory statement" in doc["basis"].lower()
    assert "para 5" in doc["basis"]


# ── Movement ─────────────────────────────────────────────────────────────────

def test_movement_is_one_shorter_than_the_values(svc):
    """The first year has nothing to move from. A leading 0 or null in the same
    array is how an off-by-one becomes a reported movement."""
    doc = svc.multi_year_trend(FIRM, CLIENT, FYS)
    for section in ("profit_and_loss", "balance_sheet"):
        for series in doc[section]:
            assert len(series["movement_paise"]) == len(series["values_paise"]) - 1
            assert len(series["movement_bps"]) == len(series["values_paise"]) - 1


def test_movement_is_both_the_amount_and_the_percentage(svc):
    """Neither alone is readable: ₹20 lakh means nothing without the base, and
    +50% means nothing without the amount."""
    doc = svc.multi_year_trend(FIRM, CLIENT, FYS)
    rev = _line(doc, "profit_and_loss", "Revenue from Operations")
    assert rev["values_paise"] == [40 * L, 60 * L, 75 * L]
    assert rev["movement_paise"] == [20 * L, 15 * L]
    assert rev["movement_bps"] == [50 * 100, 25 * 100]


def test_a_movement_off_zero_has_no_percentage(svc):
    """Undefined, not infinite and not 100%."""
    from domain.reporting.ratios import pct_change_bps
    assert pct_change_bps(500, 0) is None
    assert pct_change_bps(0, 0) is None


def test_a_falling_line_reports_a_negative_movement():
    from domain.reporting.ratios import pct_change_bps
    assert pct_change_bps(75, 100) == -25 * 100
    # …and the sign survives a negative base, so a widening loss reads as a fall.
    assert pct_change_bps(-30, -20) == -50 * 100


# ── The read shape, which is the design ──────────────────────────────────────

class _CountingSource(InMemoryLedgerSource):
    """Counts what the trend actually asks the database for."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.bucket_fetches = 0
        self.snapshots = 0

    def fetch_buckets(self, firm_id, client_id):          # pragma: no cover - shape only
        self.bucket_fetches += 1
        return super().fetch_buckets(firm_id, client_id)

    def snapshot(self, firm_id, client_id, start, end):
        self.snapshots += 1
        return super().snapshot(firm_id, client_id, start, end)


DECADE = [f"{y}-{str(y + 1)[2:]}" for y in range(2017, 2027)]


def test_a_ten_year_trend_costs_what_a_one_year_trend_costs():
    """CLAUDE.md's reporting rule, in the dimension that applies here: the cost
    must not scale with the number of YEARS either. Ten years is the same read
    as two — what changes is the arithmetic done on it, in memory.

    This is the LEGACY path (mock mode, local dev, passbook off), which is what
    an in-memory source takes. The passbook path — what production runs — is
    counted by its own test below."""
    src = _CountingSource(accounts=ACCOUNTS, entries=list(ENTRIES))
    service = ReportingService(src)

    service.multi_year_trend(FIRM, CLIENT, ["2025-26", "2026-27"])
    two = src.snapshots
    src.snapshots = 0
    service.multi_year_trend(FIRM, CLIENT, DECADE)
    ten = src.snapshots

    assert two == 1, f"two years already cost {two} snapshots"
    assert ten == two, (
        f"ten years cost {ten} source reads against {two} for two — the window is "
        "being re-fetched per year")


class _PassbookProbe:
    """The passbook read surface, counted.

    _passbook_applicable gates on isinstance(source, SupabaseLedgerSource), so
    an in-memory source can never reach the fast branch on its own — and that
    gate is about where the buckets live, not about the read shape this test is
    pinning. So the gate is opened explicitly and the three calls the branch
    makes are served from the same fixtures the legacy path replays, which is
    also what makes the parity assertion below meaningful."""

    def __init__(self, accounts, entries):
        self.accounts = {a.id: a for a in accounts}
        self.entries = list(entries)
        # The real SupabaseLedgerSource serves BOTH paths — the passbook and the
        # replay the passbook falls back to — so the probe has to as well, or
        # the fallback has nothing to fall back to.
        self.replay = InMemoryLedgerSource(accounts=accounts, entries=list(entries))
        self.account_reads = 0
        self.bucket_fetches = 0
        self.edge_fetches = 0
        self.snapshots = 0

    def snapshot(self, firm_id, client_id, start, end):
        self.snapshots += 1
        return self.replay.snapshot(firm_id, client_id, start, end)

    def _accounts(self, firm_id, client_id):
        self.account_reads += 1
        return dict(self.accounts)

    def fetch_buckets(self, firm_id, client_id):
        self.bucket_fetches += 1
        return balance_cache.build_buckets(self.entries)

    # The real edge-month method, bound to this probe. It is not restated here
    # on purpose: the claim under test is that PRODUCTION'S range arithmetic
    # asks for nothing on a month-aligned window, and a paraphrase of it would
    # prove only that the paraphrase is right.
    fetch_edge_month_entries = SupabaseLedgerSource.fetch_edge_month_entries

    def _entries(self, firm_id, client_id, date_from=None, date_to=None, **kw):
        self.edge_fetches += 1
        return {e.id: e for e in self.entries
                if (date_from is None or e.entry_date >= date_from)
                and (date_to is None or e.entry_date <= date_to)}

    def reset(self):
        self.account_reads = self.bucket_fetches = self.edge_fetches = 0
        self.snapshots = 0


@pytest.fixture()
def passbook(monkeypatch):
    probe = _PassbookProbe(ACCOUNTS, ENTRIES)
    service = ReportingService(probe)
    monkeypatch.setattr(service, "_passbook_applicable", lambda *a, **k: True)
    return probe, service


def test_the_passbook_path_reads_the_buckets_once_for_the_whole_trend(passbook):
    """The branch production actually runs. One accounts read and one bucket
    fetch, whether the CA asked for two years or ten — every year after that is
    arithmetic on rows already in memory."""
    probe, service = passbook

    service.multi_year_trend(FIRM, CLIENT, ["2025-26", "2026-27"])
    assert (probe.account_reads, probe.bucket_fetches) == (1, 1)

    probe.reset()
    service.multi_year_trend(FIRM, CLIENT, DECADE)
    assert (probe.account_reads, probe.bucket_fetches) == (1, 1), (
        f"ten years cost {probe.account_reads} account reads and "
        f"{probe.bucket_fetches} bucket fetches")


def test_a_financial_year_needs_no_edge_month_fetch(passbook):
    """1 April to 31 March is month-aligned at both ends, so the partial-month
    replay has nothing to replay — fetch_edge_month_entries computes an empty
    range list and issues no query at all. If this ever fires, the trend has
    started paying a per-year query it was designed not to."""
    probe, service = passbook
    service.multi_year_trend(FIRM, CLIENT, DECADE)
    assert probe.edge_fetches == 0


def test_the_passbook_trend_is_the_same_document_as_the_replay(svc, passbook):
    """Two ways of arriving at one set of numbers. A CA on a passbook-enabled
    deployment and a CA on a local one must be reading the same trend."""
    probe, service = passbook
    assert service.multi_year_trend(FIRM, CLIENT, FYS) == \
        svc.multi_year_trend(FIRM, CLIENT, FYS)


def test_one_unreadable_year_does_not_lose_the_others(svc, monkeypatch):
    """A trend is the one report where a single bad year must not take the
    document with it — the other four are what the CA came for.

    Patched at the BUILDER, which both the passbook and the legacy branch call,
    so this pins the behaviour on whichever path is running rather than on the
    fallback only."""
    from domain.reporting import builders as B
    real = B.profit_loss

    def flaky(lines, accounts, start, end, basis):
        if start.startswith("2025"):
            raise RuntimeError("bucket cache corrupt for this window")
        return real(lines, accounts, start, end, basis)

    monkeypatch.setattr(B, "profit_loss", flaky)
    doc = svc.multi_year_trend(FIRM, CLIENT, FYS)
    assert "2025-26" not in doc["fys"]
    assert "2024-25" in doc["fys"] and "2026-27" in doc["fys"]


def test_a_year_that_failed_is_not_reported_as_a_year_with_nothing_in_it(svc, monkeypatch):
    """The two are indistinguishable in the document and mean opposite things.
    "2025-26 has nothing recorded against it" is a finding about the client's
    books; "2025-26 could not be read" is a finding about this request. A CA
    repeats the first one to the client."""
    from domain.reporting import builders as B
    real = B.profit_loss

    def flaky(lines, accounts, start, end, basis):
        if start.startswith("2025"):
            raise RuntimeError("bucket cache corrupt for this window")
        return real(lines, accounts, start, end, basis)

    monkeypatch.setattr(B, "profit_loss", flaky)
    doc = svc.multi_year_trend(FIRM, CLIENT, FYS)

    assert doc["unreadable_fys"] == ["2025-26"]
    # 2023-24 really is empty; 2025-26 is not, and must not be lumped in with it.
    assert doc["dropped_fys"] == ["2023-24"]
    codes = [g["code"] for g in doc["gaps"]]
    assert "years_unreadable" in codes and "years_without_records_dropped" in codes


def test_a_clean_run_reports_no_unreadable_years(svc):
    doc = svc.multi_year_trend(FIRM, CLIENT, FYS)
    assert doc["unreadable_fys"] == []
    assert "years_unreadable" not in [g["code"] for g in doc["gaps"]]


def test_a_failed_bucket_read_falls_back_to_the_replay(passbook, svc, monkeypatch):
    """_serve's contract, which this method has to keep on its own because it
    does not go through _serve: a missing or stale passbook degrades to the slow
    path. Returning a short document instead would report years as unreadable
    that the replay can read perfectly well."""
    probe, service = passbook

    def broken(*a, **k):
        raise RuntimeError("account_period_balances unavailable")

    monkeypatch.setattr(probe, "fetch_buckets", broken)
    doc = service.multi_year_trend(FIRM, CLIENT, FYS)

    assert probe.snapshots == 1, "the fallback should replay the window once, not per year"
    assert doc["unreadable_fys"] == []
    assert doc == svc.multi_year_trend(FIRM, CLIENT, FYS)
