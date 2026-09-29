"""Neither ratios.py nor its trend builder knew the current FY was still
open, so a part-year `current` was compared against a full prior year with
nothing saying the two periods are different lengths — an ordinary seasonal
or not-yet-finished line reads as a misleading >25% move needing an
explanation nobody can write (apex-accounting-reports-20).

This is a small, surgical addition: both `ratios.build()` and `trend.build()`
now accept (and echo) a period label the CALLER supplies, since neither
domain module holds a calendar of its own. The callers —
services/ratio_analysis_service.ratio_note and
ReportingService.multi_year_trend — set it to "year to date to <last posted
date>" exactly when the FY in question is today's FY, using
services/ledger_span_service.ledger_span for the date. A CLOSED year (any FY
other than the current one) gets no label, because comparing two full years
is the comparison clause (Q) already asks for.

Also: `moved_count` (ratios that moved by more than 25%, whether or not
explained) is now served alongside `needs_explanation_count` (moved AND
unexplained) — the banner needs both to say "N of M ratios ... still need an
explanation" rather than wording the unexplained count as if it were the
total.
"""
from __future__ import annotations

from domain.reporting import ratios as R
from domain.reporting import trend as T


# ── domain/reporting/ratios.py: the label is carried, not derived ───────────

def test_build_echoes_the_current_period_label_it_is_given():
    out = R.build(R.Components(revenue_from_operations=100),
                  current_period_label="year to date to 15 Sep 2026")
    assert out["current_period_label"] == "year to date to 15 Sep 2026"


def test_build_defaults_the_label_to_none_for_a_closed_year():
    out = R.build(R.Components(revenue_from_operations=100))
    assert out["current_period_label"] is None


def test_moved_count_is_the_total_and_needs_explanation_count_is_the_unexplained_subset():
    # Two independent ratios, both moving well past the 25% threshold:
    # current_ratio triples (cash up, payables flat) and debt_equity triples
    # (borrowings up, share capital flat).
    prior = R.Components(cash=100_00, trade_payables=100_00,
                         long_term_borrowings=50_00, share_capital=100_00)
    current = R.Components(cash=300_00, trade_payables=100_00,
                           long_term_borrowings=150_00, share_capital=100_00)
    moved_first = R.build(current, prior)
    a_moved_key = next(r["key"] for r in moved_first["ratios"] if r["needs_explanation"])
    out = R.build(current, prior, explanations={a_moved_key: "Because of a one-off contract."})
    assert out["moved_count"] >= 2, "current_ratio and debt_equity both cross the 25% threshold here"
    assert out["needs_explanation_count"] == out["moved_count"] - 1
    assert out["needs_explanation_count"] < out["moved_count"], (
        "the banner must be able to say N of M — collapsing the two into one "
        "count is exactly the defect this guards against")


# ── domain/reporting/trend.py: the same shape, for the rightmost column ─────

def test_trend_build_echoes_the_latest_period_label_it_is_given():
    out = T.build([], [], latest_period_label="year to date to 15 Sep 2026")
    assert out["latest_period_label"] == "year to date to 15 Sep 2026"


def test_trend_build_defaults_the_label_to_none():
    out = T.build([], [])
    assert out["latest_period_label"] is None


# ── services/ratio_analysis_service.py: WHEN the label is set ────────────────

class _Query:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def is_(self, *a, **k): return self
    def in_(self, *a, **k): return self
    def limit(self, *a, **k): return self

    def order(self, col, desc=False):
        rows = sorted(self._rows, key=lambda r: r.get(col) or "", reverse=desc)
        return _Query(rows)

    def execute(self):
        return type("R", (), {"data": self._rows})()


class _DB:
    """Answers journal_entries (for ledger_span) with a fixed last posted
    date, and everything else (the ratio explanations/inputs tables) with no
    rows — which _explanations/_principal_repaid already read as "nothing
    recorded"."""

    def __init__(self, last_entry_date):
        self._last = last_entry_date

    def table(self, name):
        if name == "journal_entries":
            return _Query([{"entry_date": self._last}])
        return _Query([])


def test_ratio_note_labels_the_current_fy_as_year_to_date(monkeypatch):
    import services.ratio_analysis_service as svc_mod

    monkeypatch.setattr(svc_mod, "ist_fy_label", lambda: "2026-27")

    class _StubReporting:
        def profit_loss(self, *a, **k): return {"revenue": {"lines": []}}
        def balance_sheet(self, *a, **k): return {}

    db = _DB("2026-09-15")
    out = svc_mod.ratio_note(_StubReporting(), db, "firm-1", "client-1", "2026-27")
    assert out["current_period_label"] == "year to date to 15 Sep 2026"


def test_ratio_note_does_not_label_a_closed_year(monkeypatch):
    import services.ratio_analysis_service as svc_mod

    # Today is FY 2026-27; the note asked for is the CLOSED preceding one.
    monkeypatch.setattr(svc_mod, "ist_fy_label", lambda: "2026-27")

    class _StubReporting:
        def profit_loss(self, *a, **k): return {"revenue": {"lines": []}}
        def balance_sheet(self, *a, **k): return {}

    db = _DB("2026-09-15")
    out = svc_mod.ratio_note(_StubReporting(), db, "firm-1", "client-1", "2025-26")
    assert out["current_period_label"] is None


def test_ratio_note_does_not_label_the_current_fy_with_no_activity_yet(monkeypatch):
    """The last posted date belongs to an EARLIER year (nothing posted yet
    this FY) — labelling it "year to date to <last year's date>" would read
    as though the current year had already ended before it began."""
    import services.ratio_analysis_service as svc_mod

    monkeypatch.setattr(svc_mod, "ist_fy_label", lambda: "2026-27")

    class _StubReporting:
        def profit_loss(self, *a, **k): return {"revenue": {"lines": []}}
        def balance_sheet(self, *a, **k): return {}

    db = _DB("2026-01-15")   # inside FY 2025-26, before 2026-27 started
    out = svc_mod.ratio_note(_StubReporting(), db, "firm-1", "client-1", "2026-27")
    assert out["current_period_label"] is None


# ── domain/reporting/service.py: the trend's own rightmost-column label ─────

def test_multi_year_trend_labels_the_latest_column_when_it_is_the_current_fy(monkeypatch):
    from domain.reporting.service import ReportingService

    monkeypatch.setattr("domain.reporting.service.ist_fy_label", lambda: "2026-27")

    class _Source:
        db = _DB("2026-09-15")

    svc = ReportingService(_Source())
    label = svc._latest_period_label(
        "firm-1", "client-1",
        years=[("2025-26", {}, {}), ("2026-27", {}, {})])
    assert label == "year to date to 15 Sep 2026"


def test_multi_year_trend_does_not_label_a_window_ending_in_a_closed_year(monkeypatch):
    from domain.reporting.service import ReportingService

    monkeypatch.setattr("domain.reporting.service.ist_fy_label", lambda: "2026-27")

    class _Source:
        db = _DB("2026-09-15")

    svc = ReportingService(_Source())
    # The rightmost column is 2025-26, a CLOSED year — today being in
    # 2026-27 does not matter here.
    label = svc._latest_period_label(
        "firm-1", "client-1",
        years=[("2024-25", {}, {}), ("2025-26", {}, {})])
    assert label is None


def test_multi_year_trend_has_no_label_with_no_database():
    """InMemoryLedgerSource (mock mode, local dev) has no `.db` — the same
    "no ledger to span" case useLedgerSpan.ts's own docstring names."""
    from domain.reporting.service import ReportingService

    class _Source:
        pass   # no .db attribute at all

    svc = ReportingService(_Source())
    label = svc._latest_period_label("firm-1", "client-1", years=[("2026-27", {}, {})])
    assert label is None
