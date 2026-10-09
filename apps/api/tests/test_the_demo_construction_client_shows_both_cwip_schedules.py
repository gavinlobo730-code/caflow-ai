"""The demo's projects under construction are a coherent set of books, and between them show everything Schedule III's
two capital work-in-progress schedules can say (PRE-A-004).

THE CLIENT FOR CONSTRUCTION SAID IT "DEMONSTRATES capital work in progress, its Schedule III line and its ageing
schedule, which nothing else here produces" -- and the seeder wrote no project, so the line, both schedules and the
register were empty on the one client built to fill them. These are the properties of the fixture that make what the
seeder then writes worth reading; the seeder's own bodies are held in
`test_every_body_the_seeder_sends_is_one_its_door_accepts.py` and the books they produce were driven over a real
database (tranches Rs 1,54,348 in all: Purchases down by exactly that, Capital Work-in-Progress up by it, the
Schedule III balance sheet balanced, Verify Books clean of critical findings).

It reads only the fixture, so it states the RULES and not the positions of today's bills:
  - a project is built out of bills the client RECEIVED, each by one project and none a reverse-charge bill or one
    left in the draft month (nothing posted, so nothing to reclassify);
  - its dates are in the order a project's life runs (started, then its first cost, then any suspension, then the
    approved and expected completion), so no tranche precedes the project it belongs to;
  - at the year end the set shows a project past its approved completion date, a project over its approved cost, one
    inside it, a suspended one and one still in progress -- the completion schedule's two reasons and the ageing
    schedule's two rows -- with a margin wide enough that a paisa of difference between the fixture's estimate of a
    bill and the engine's own figure cannot flip a verdict;
  - it is plant, not a building: CGST s.17(5)(c) and (d) block the credit on construction of an immovable property
    other than plant or machinery, and the bills these tranches come from have already claimed theirs.
"""
from __future__ import annotations

from datetime import date

import pytest

from domain.demo import fixture
from domain.fixed_assets import schedule_ii

FIRM = fixture.build()
WITH_PROJECTS = [c for c in FIRM.clients if c.cwip_projects]
#: The Schedule II Part C classes that are immovable property. Anchored to the table below (a class renamed there
#: fails `test_the_immovable_classes_are_ones_part_c_holds`, rather than leaving this set naming nothing).
IMMOVABLE = {"Building", "Land"}


def _bill(client, n):
    return client.purchases[n - 1]


def _cost(client, project) -> int:
    return sum(fixture.document_taxable_paise(_bill(client, n)) for n in project.bills)


def test_some_client_has_a_project_to_show():
    assert WITH_PROJECTS, "no client has a project under construction: the CWIP line and both schedules are empty"
    assert sum(len(c.cwip_projects) for c in FIRM.clients) == fixture.summary(FIRM)["cwip_projects"]


@pytest.mark.parametrize("client", WITH_PROJECTS, ids=lambda c: c.name)
def test_a_project_is_built_out_of_received_bills_each_used_once(client):
    draft = fixture.draft_month(FIRM.financial_year)
    seen: set[int] = set()
    for p in client.cwip_projects:
        assert p.bills, f"{p.name} has no cost in it"
        for n in p.bills:
            assert 1 <= n <= len(client.purchases), f"{p.name} names purchase {n}, which does not exist"
            assert n not in seen, f"purchase {n} is the cost of two projects"
            seen.add(n)
            bill = _bill(client, n)
            assert bill.doc_date[:7] != draft, f"purchase {n} is left as a draft: it posted nothing to reclassify"
            assert not bill.is_reverse_charge, f"purchase {n} is reverse charge"
            assert fixture.document_taxable_paise(bill) > 0


@pytest.mark.parametrize("client", WITH_PROJECTS, ids=lambda c: c.name)
def test_a_projects_dates_run_in_the_order_a_projects_life_does(client):
    for p in client.cwip_projects:
        started = date.fromisoformat(p.started_on)
        dates = sorted(date.fromisoformat(_bill(client, n).doc_date) for n in p.bills)
        assert started <= dates[0], f"{p.name}: a tranche precedes the project's start"
        assert date.fromisoformat(p.approved_completion_date) > started
        assert date.fromisoformat(p.expected_completion_date) > started
        if p.suspended_on:
            assert date.fromisoformat(p.suspended_on) >= dates[-1], f"{p.name}: suspended before its last tranche"
        assert all(d.isoformat() >= FIRM.financial_year[:4] + "-04-01" for d in dates)


@pytest.mark.parametrize("client", WITH_PROJECTS, ids=lambda c: c.name)
def test_the_set_shows_both_completion_reasons_and_both_ageing_rows_at_the_year_end(client):
    year_end = date(int(FIRM.financial_year[:4]) + 1, 3, 31)
    overdue, over_budget, within_budget, suspended, running = [], [], [], [], []
    for p in client.cwip_projects:
        cost = _cost(client, p)
        approved = p.approved_cost_paise(cost)
        # A margin of at least a tenth either side of the budget: the fixture's estimate of a bill and the
        # engine's own figure can differ by a paisa and that must not flip which side of the budget a project is on.
        assert abs(cost - approved) >= cost // 10, f"{p.name}: cost {cost} too close to its approved {approved}"
        (over_budget if cost > approved else within_budget).append(p)
        if date.fromisoformat(p.approved_completion_date) < year_end:
            overdue.append(p)
        (suspended if p.suspended_on else running).append(p)
    assert overdue, "no project is past its approved completion date at the year end"
    assert over_budget, "no project has spent more than it was approved to"
    assert within_budget, "no project is inside its budget, so the schedule shows only failures"
    assert suspended and running, "the ageing schedule's two rows are not both shown"


@pytest.mark.parametrize("client", WITH_PROJECTS, ids=lambda c: c.name)
def test_a_project_is_plant_and_not_a_building(client):
    for p in client.cwip_projects:
        assert p.asset_category in schedule_ii.PART_C, f"{p.asset_category!r} has no Schedule II Part C class"
        assert p.asset_category not in IMMOVABLE, (
            "CGST s.17(5)(c)/(d) blocks the credit on construction of an immovable property other than plant or "
            "machinery, and the bills a tranche comes from have already claimed it")


def test_the_immovable_classes_are_ones_part_c_holds():
    assert IMMOVABLE <= set(schedule_ii.PART_C)


def test_the_budget_is_a_whole_number_of_thousands_of_rupees():
    thousand = 1_000_00
    for client in WITH_PROJECTS:
        for p in client.cwip_projects:
            approved = p.approved_cost_paise(_cost(client, p))
            assert approved > 0 and approved % thousand == 0


def test_a_client_without_projects_asks_for_none():
    """Construction is one client's story; nobody else is given a project."""
    assert len(WITH_PROJECTS) < len(FIRM.clients)
    assert all(not c.cwip_projects for c in FIRM.clients if c not in WITH_PROJECTS)
