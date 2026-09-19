"""A document that leaves the building groups the Indian way and is dated in IST.

── TWO DEFECTS, FOUND TOGETHER BECAUSE THEY ARE THE SAME SHAPE ──────────────
Both were a general rule with an authority already written, and callers that
did the thing by hand instead.

**THE GROUPING.** `invoice_pdf_service` and `payslip_pdf_service` each carried

    rupees = paise // 100
    fraction = paise % 100
    return f"{rupees:,}.{fraction:02d}"

`f"{1234567:,}"` is `1,234,567`. Decision D6 is Indian grouping everywhere —
`12,34,567` — and these are the two documents that leave the building most: a
tax invoice goes to the client's own customer, a payslip to an employee.

**AND THE SAME TWO LINES INVERT A NEGATIVE.** Python's `//` floors and `%`
follows it, so `-1` paise rendered as `-1.99` and `-150` as `-2.50`. Every
negative that is not an exact rupee was wrong by one rupee minus its fraction.

**THE DATE.** `core/ist_clock` exists and its own docstring says why: the
container is `python:3.11-slim` with no TZ pinning, so it runs UTC, and for the
5½ hours from 00:00 to 05:30 IST a bare `date.today()` is still on YESTERDAY.
79 sites read the naive clock anyway. On the year-end pack that is the cover of
a set a CA signs — a pack built at 01:00 IST on 1 April was dated 31 March, the
previous day and, on that one night of the year, the previous FINANCIAL YEAR.

── WHY THE RATCHET IS NOT NIL ───────────────────────────────────────────────
A log timestamp may legitimately be UTC, and telling the two apart is a read of
each site rather than a sweep. What is asserted is the population, exactly, so
a new one fails; the sites moved so far are the ones whose answer IS a CA's
today — the due-date countdown, the dates generated documents take, the windows
statements cover.
"""
from __future__ import annotations

import ast
import pathlib
import re

API = pathlib.Path(__file__).resolve().parents[1]
ROOTS = ("services", "routers", "domain", "jobs", "core")


def _code(p: pathlib.Path) -> str:
    """Source with docstrings and comments out — prose says WHY and cannot run."""
    s = p.read_text(errors="ignore")
    s = re.sub(r'"""[\s\S]*?"""', "", s)
    s = re.sub(r"'''[\s\S]*?'''", "", s)
    return re.sub(r"^\s*#.*$", "", s, flags=re.M)


def _files() -> list[pathlib.Path]:
    return [p for r in ROOTS for p in sorted((API / r).rglob("*.py"))]


# ── the grouping ────────────────────────────────────────────────────────────

def test_no_pdf_service_groups_money_in_threes():
    """`f"{n:,}"` is Western. THE RULE, not a spelling: any format spec with a
    comma applied to a name that says rupees or paise."""
    WESTERN = re.compile(r"\{[^{}]*\b(?:rupees?|paise|amount|total)\w*[^{}]*:,[^{}]*\}", re.I)
    offenders = []
    for p in sorted((API / "services").glob("*pdf*.py")):
        for m in WESTERN.finditer(_code(p)):
            offenders.append(f"{p.name}: {m.group(0)}")
    assert not offenders, (
        "a PDF groups money in threes — D6 is Indian grouping everywhere. Use "
        "domain/reporting/pdf_money.rupees_paise:\n  " + "\n  ".join(offenders))


def test_the_three_services_ask_the_one_formatter():
    """MENTIONED IS NOT USED — asserted on the import, which is what a caller
    that reimplements the rule would not have."""
    for name in ("invoice_pdf_service.py", "payslip_pdf_service.py",
                 "year_end_pdf_service.py"):
        src = _code(API / "services" / name)
        assert "domain.reporting.pdf_money" in src, f"{name} does not ask the formatter"


def test_the_formatter_is_right_about_a_negative():
    """The case the two services got wrong, pinned at the boundary. `-1` paise
    is one paisa owed, not one rupee and ninety-nine."""
    import sys
    sys.path.insert(0, str(API))
    from domain.reporting.pdf_money import rupees_paise, whole_rupees

    assert rupees_paise(-1) == "-0.01"
    assert rupees_paise(-99) == "-0.99"
    assert rupees_paise(-150) == "-1.50"
    assert rupees_paise(-100) == "-1.00"
    assert rupees_paise(0) == "0.00"
    # The grouping itself, at the two places the Indian system differs.
    assert rupees_paise(1_00_000_00) == "1,00,000.00"
    assert rupees_paise(12_34_567_89) == "12,34,567.89"
    # `None` is nil rather than a crash: a PDF is built from rows a query
    # returned and one NULL column must not fail the whole document.
    assert rupees_paise(None) == "0.00"
    # Whole rupees truncate TOWARD ZERO, and a magnitude under a rupee carries
    # no sign — "-0" is not a figure.
    assert whole_rupees(-150) == "-1"
    assert whole_rupees(-99) == "0"


# ── the clock ───────────────────────────────────────────────────────────────

_NAIVE = re.compile(r"\b(?:datetime\.now\(\)|date\.today\(\))")

#: EXACT. Lower it as sites are read and moved; never raise it.
NAIVE_CLOCK_READS = 58


def _naive_sites() -> list[str]:
    out = []
    for p in _files():
        src = _code(p)
        for m in _NAIVE.finditer(src):
            out.append(f"{p.relative_to(API)}:{src[:m.start()].count(chr(10)) + 1}")
    return out


def test_no_new_naive_clock_read():
    found = _naive_sites()
    assert len(found) <= NAIVE_CLOCK_READS, (
        f"{len(found)} naive clock reads, budget {NAIVE_CLOCK_READS}. The "
        "container is UTC (no TZ pinning — see core/ist_clock's own header), so "
        "between 00:00 and 05:30 IST a bare date.today() is YESTERDAY. Use "
        "core.ist_clock.ist_today / ist_now wherever the answer is a CA's "
        f"today.\n  " + "\n  ".join(found[:12]))
    assert len(found) == NAIVE_CLOCK_READS, (
        f"{len(found)} left against a budget of {NAIVE_CLOCK_READS} — lower the "
        "budget to what you achieved, so the next regression fails here.")


def test_the_probe_still_sees_naive_reads():
    """A regex that matched nothing would pass the ratchet for ever."""
    assert len(_naive_sites()) >= 10, "the naive-clock probe has stopped working"


def test_the_year_end_pack_is_dated_in_ist():
    """The one document in this repertoire that a CA SIGNS. Asserted on the
    outcome — no naive read anywhere in the module, and the IST clock asked."""
    src = _code(API / "services" / "year_end_pdf_service.py")
    assert not _NAIVE.search(src), "the year-end pack is back on the server's clock"
    assert "ist_now()" in src, "and it must ask core.ist_clock"


def test_the_business_date_services_ask_the_ist_clock():
    """The sites moved on 19 Sep 2026, stated as the property rather than as a
    count, so a file that reverts one fails by name."""
    for name in ("compliance_engine.py", "collections_service.py",
                 "invoice_lifecycle_service.py", "task_service.py",
                 "billing_service.py", "escalation_service.py",
                 "timeline_service.py", "bank_exception_service.py",
                 "portal_data_service.py", "recurring_task_service.py",
                 "recurring_invoice_service.py", "recurring_purchase_bill_service.py",
                 "tds_register_service.py", "inventory_location_service.py",
                 "bank_candidate_search_service.py"):
        src = _code(API / "services" / name)
        assert not _NAIVE.search(src), (
            f"{name} reads the server's clock again — its 'today' is a CA's")
        assert "ist_today" in src, f"{name} no longer asks core.ist_clock"
