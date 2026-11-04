"""The demo practice's own work (tasks, hours, fee invoices, leads) agrees with the books and returns the same seeder records.

WHAT WAS WRONG (found by an independent read of the first version, 4-11-2026)
    The Tasks board said work was open or under way that the GST, payroll and Income Tax screens showed as finished:
    "GSTR-1 for January 2026" in progress over a return filed in February, "Run payroll for January 2026" in progress over a
    run that is paid, "Collect Form 16" to do for an individual whose return is acknowledged and for companies that have no
    Form 16. The same open tasks lowered the clients' seeded health scores (the engine deducts for each task in progress past
    its date). A section 44AD proprietor was told what to deposit for an instalment its own advance-tax schedule does not
    have. The pipeline's values were annual-scale numbers under a per-month label, and 37 hours were stored with no end,
    which is how the product stores a running timer. The tests that were there checked counts and shapes, and six deliberate
    mutations of the fixture and the seeder all passed them.

WHAT IS HELD
    A task's status is DERIVED, here, from the same facts the seeder files: the months a return window covers
    (`scripts.seed_demo_firm._return_windows`, the seeder's own function, not a copy), the status each payroll month is left at,
    and how far each client's income tax return is taken. Nothing below restates a statutory date or a rate.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

import pytest

from domain.demo import fixture

FY = "2025-26"
_MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"], 1)}


@pytest.fixture(scope="module")
def firm():
    return fixture.build(FY)


@pytest.fixture(scope="module")
def seeder():
    import scripts.seed_demo_firm as seeder
    return seeder


def _month_of(text: str) -> str:
    """'February 2026' (the last such phrase in a title) -> '2026-02'."""
    name, year = re.findall(r"(" + "|".join(_MONTHS) + r") (\d{4})", text)[-1]
    return f"{year}-{_MONTHS[name]:02d}"


def _filed_months(seeder, client) -> set[str]:
    """Every month a filed GST return covers, from the seeder's own windows."""
    quarterly = client.gst_filing_frequency == "quarterly"
    windows = seeder._return_windows(FY, quarterly, fixture.draft_month(FY), (client.gstin or "")[:2] or None)
    out: set[str] = set()
    for key, window_end, _g1, _g3b in windows:
        start_m, start_y = int(key[:2]), int(key[2:])
        end_y, end_m = int(window_end[:4]), int(window_end[5:7])
        y, m = start_y, start_m
        while (y, m) <= (end_y, end_m):
            out.add(f"{y:04d}-{m:02d}")
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def test_a_gst_task_is_completed_exactly_when_the_seeder_files_the_return_it_names(firm, seeder):
    seen = 0
    for c in firm.clients:
        if not c.gstin:
            continue
        filed = _filed_months(seeder, c)
        for t in fixture.tasks_for(c, FY):
            if t.title.startswith("GSTR-3B for "):
                seen += 1
                assert t.status == "completed" and _month_of(t.title) in filed, (c.name, t.title, "is not a filed return")
            elif "GSTR-1" in t.title or "GSTR-2B" in t.title or t.title.startswith("Chase the missing purchase bills"):
                seen += 1
                # Work on the return still to come: the month it names is one the seeder has NOT filed.
                assert t.status in ("in_progress", "waiting_client") and _month_of(t.title) not in filed, (
                    c.name, t.title, t.status, "is open work over a return the seeder files")
    assert seen >= 15, "the rule saw almost no GST task, so it held nothing"


def test_a_quarterly_filers_open_quarter_is_the_one_the_seeder_leaves_open(firm, seeder):
    q = next(c for c in firm.clients if c.gst_filing_frequency == "quarterly")
    filed = _filed_months(seeder, q)
    titles = {t.title: t for t in fixture.tasks_for(q, FY)}
    done = next(t for n, t in titles.items() if n.startswith("GSTR-3B for "))
    assert done.status == "completed" and _month_of(done.title) in filed
    reconcile = next(t for n, t in titles.items() if n.startswith("Reconcile "))
    assert reconcile.status == "in_progress" and _month_of(reconcile.title) not in filed
    assert "January to March 2026" in reconcile.title, "the title follows the year, not a literal"


def test_the_quarters_named_follow_the_financial_year(firm):
    q = next(c for c in firm.clients if c.gst_filing_frequency == "quarterly")
    later = " ".join(t.title for t in fixture.tasks_for(q, "2026-27"))
    assert "January to March 2027" in later and "2026" in later and "2025" not in later.replace("2025-26", "")


def test_a_payroll_task_follows_the_status_the_seeder_leaves_each_month_at(firm):
    seen = 0
    for c in firm.clients:
        if not c.employees:
            continue
        left = {p.month: p.leave_at for p in c.payroll}
        for t in fixture.tasks_for(c, FY):
            if t.title.startswith("Run payroll for "):
                seen += 1
                assert left[_month_of(t.title)] == "paid" and t.status == "completed", (c.name, t.title, left[_month_of(t.title)])
            if t.title.startswith("Record the salary payment for "):
                seen += 1
                assert left[_month_of(t.title)] == "finalized" and t.status == "todo", (c.name, t.title, left[_month_of(t.title)])
    assert seen >= 4


def test_the_income_tax_task_follows_how_far_the_seeder_takes_the_return(firm):
    seen = 0
    for c in firm.clients:
        it = c.income_tax
        task = next(t for t in fixture.tasks_for(c, FY) if "income tax return" in t.title.lower())
        seen += 1
        if it is not None and it.itr_form and it.take_it_to == "filed":
            assert task.status == "completed", (c.name, task.title)
        elif it is not None and it.itr_form:
            assert task.status == "review_required", (c.name, task.title)
        else:
            assert task.status == "todo", (c.name, task.title, "no return is prepared, so the documents are still to collect")
    assert seen == len(firm.clients)


def test_form_16_is_asked_only_of_a_client_with_salary(firm):
    asked = {c.name for c in firm.clients for t in fixture.tasks_for(c, FY) if "Form 16" in t.description or "Form 16" in t.title}
    for c in firm.clients:
        has_salary = bool(c.income_tax and c.income_tax.salary_paise > 0)
        assert (c.name in asked) == has_salary, (c.name, "Form 16 is the salary certificate an employee receives")


def test_no_task_names_an_advance_tax_instalment_for_a_presumptive_client(firm):
    presumptive = [c for c in firm.clients if c.income_tax and c.income_tax.presumptive_44ad]
    assert presumptive, "the fixture has no presumptive client, so this held nothing"
    for c in presumptive:
        for t in fixture.tasks_for(c, FY):
            assert "advance tax" not in t.title.lower() and "instalment" not in (t.title + t.description).lower(), (c.name, t.title)


def test_a_client_has_at_most_one_task_in_progress_because_each_one_past_its_date_costs_the_clients_health_score(firm):
    for c in firm.clients:
        assert sum(1 for t in fixture.tasks_for(c, FY) if t.status == "in_progress") <= 1, c.name


def test_a_task_due_date_is_a_working_date_inside_the_year_and_never_a_statutory_one_restated(firm):
    for c in firm.clients:
        for t in fixture.tasks_for(c, FY):
            assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", t.due_date)
            if t.title.startswith(("GSTR-3B for", "Enter the", "Reconcile", "Chase")):
                assert int(t.due_date[8:]) <= 8, (c.name, t.title, t.due_date, "earlier than the 11th and the 20th it prepares for")


def test_every_time_entry_is_on_an_engagement_the_client_holds_ends_after_it_starts_and_bills_nothing(firm):
    seen = 0
    for c in firm.clients:
        held = {e.service_type for e in c.engagements}
        for e in fixture.time_entries_for(c, FY):
            seen += 1
            assert e.service_type in held
            assert e.is_billable is False
            started, ended = datetime.fromisoformat(e.started_at), datetime.fromisoformat(e.ended_at)
            assert ended - started == timedelta(minutes=e.duration_minutes) and e.duration_minutes > 0
            assert started.utcoffset() == timedelta(hours=5, minutes=30), "a wall-clock time in India"
    assert seen == fixture.summary(firm)["time_entries"] > 20


def test_a_fee_receipt_is_a_part_of_its_invoice_and_comes_after_it(firm):
    seen = 0
    for c in firm.clients:
        for f in fixture.fee_invoices_for(c, FY):
            if f.receipt_after_days is None:
                continue
            seen += 1
            assert f.receipt_after_days >= 0 and 0 < f.receipt_fraction_bps <= 10_000, (c.name, f)
    assert seen == fixture.summary(firm)["fee_receipts"] > 10


def test_the_pipeline_is_of_the_order_of_the_practice_it_would_join(firm):
    """A lead's value is a MONTHLY fee. Annual-scale numbers (Rs 1.8 lakh to Rs 3.6 lakh under a per-month label) added up to
    Rs 9.48 lakh a month of 'Est. MRR if all convert', about sixteen times the whole seeded practice. The check is on scale, not on
    a figure: no lead is dearer than the dearest engagement a seeded client is billed monthly, and the pipeline is less than the
    practice's own monthly fees."""
    monthly = 0.0
    dearest = 0
    for c in firm.clients:
        for e in c.engagements:
            per_month = e.monthly_fee_paise if hasattr(e, "monthly_fee_paise") else e.fee_paise / {"Monthly": 1, "Quarterly": 3, "Annually": 12}[e.billing_cycle]
            monthly += per_month
            dearest = max(dearest, per_month)
    leads = fixture.leads_for()
    assert len(leads) == 5
    assert max(l.estimated_monthly_fee_paise for l in leads) <= 3 * dearest
    assert sum(l.estimated_monthly_fee_paise for l in leads) < monthly
    for l in leads:
        assert l.email.endswith(".example.invalid")
        assert 0 <= l.last_contact_days_ago < l.expected_close_in_days and 0 < l.follow_up_in_days <= l.expected_close_in_days
