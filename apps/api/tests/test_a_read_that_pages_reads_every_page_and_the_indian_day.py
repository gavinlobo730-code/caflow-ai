"""Overdue tasks and the section 32 asset read are complete, and "overdue" is judged on the Indian day.

POST-A-048  `task_repo.find_overdue` compared `due_date` with `date.today()` (the server's clock, UTC on Render) and read
            with one unpaged `.execute()`. Between 00:00 and 05:30 IST it named yesterday, so everything due yesterday
            was missing from the count the Executive Dashboard and the morning digest share; and past PostgREST's
            row cap (about 1,000) the count was silently short.
POST-A-072  `Section32Service.assemble` read `fixed_assets` unpaged, so a client with more than a thousand assets had its
            block allowance understated with nothing to say so.

Both are driven against `_capped_postgrest.CappedDB`, which has the row cap: an unpaged read against it returns exactly a
thousand rows and raises nothing, which is what production did.
"""
from __future__ import annotations


import pytest

from tests._capped_postgrest import DB_MAX_ROWS, CappedDB

FIRM, CLIENT = "f1", "c1"


# ── find_overdue ─────────────────────────────────────────────────────────────

def _task(i, due="2026-10-01", status="in_progress", firm=FIRM, deleted=None):
    return {"id": f"t{i:06d}", "firm_id": firm, "due_date": due, "status": status, "deleted_at": deleted}


@pytest.fixture()
def repo(monkeypatch):
    import repositories.task_repository as tr
    monkeypatch.setattr(tr, "_USE_MOCK", False)

    def install(rows):
        db = CappedDB({"tasks": rows})
        monkeypatch.setattr(tr, "_get_db", lambda: db)
        return db

    repo = tr.TaskRepository()
    repo.install = install
    return repo


def _freeze_utc(monkeypatch, utc_iso):
    """Freeze `core.ist_clock`'s notion of now to a UTC instant (the same device as tests/test_ist_clock.py), leaving
    `ist_today` itself unpatched so the test goes through the real conversion."""
    import datetime as _dt

    import core.ist_clock as clock

    fixed = _dt.datetime.fromisoformat(utc_iso).replace(tzinfo=_dt.timezone.utc)

    class _Frozen(_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz) if tz is not None else fixed

    monkeypatch.setattr(clock, "datetime", _Frozen)


def test_overdue_is_judged_on_the_indian_day_not_the_servers(repo, monkeypatch):
    """At 01:30 IST on 18 October it is 20:00 on the 17th by the server's UTC clock. A task due on the 17th is overdue
    in India; judged on the server's day it was not, and it was missing from the count until 05:30."""
    _freeze_utc(monkeypatch, "2026-10-17T20:00:00")
    rows = [_task(1, due="2026-10-17"), _task(2, due="2026-10-18"), _task(3, due="2026-10-19")]
    db = repo.install(rows)
    got = repo.find_overdue(firm_id=FIRM)
    assert [t["id"] for t in got] == ["t000001"]
    asked = [op for page in db.requests["tasks"] for op in page]
    assert ("lt", "due_date", "2026-10-18") in asked, asked


def test_2500_overdue_tasks_are_all_counted(repo):
    rows = [_task(i) for i in range(2500)]
    repo.install(rows)
    got = repo.find_overdue(firm_id=FIRM)
    assert len(got) == 2500, f"read {len(got)} of 2500: the count stopped at the row cap"
    assert len({t["id"] for t in got}) == 2500, "a page repeated a row"


def test_the_double_would_have_caught_the_unpaged_read(repo):
    """Guard on the guard: one unpaged request against this double returns exactly the cap."""
    db = CappedDB({"tasks": [_task(i) for i in range(2500)]})
    assert len(db.table("tasks").select("*").lt("due_date", "2026-12-31").execute().data) == DB_MAX_ROWS


def test_paging_keeps_the_firm_the_deleted_and_the_completed_filters(repo):
    rows = ([_task(i) for i in range(1200)]
            + [_task(2000 + i, firm="other") for i in range(50)]
            + [_task(3000 + i, status="completed") for i in range(50)]
            + [_task(4000 + i, deleted="2026-10-02T00:00:00+00:00") for i in range(50)])
    repo.install(rows)
    got = repo.find_overdue(firm_id=FIRM)
    assert len(got) == 1200 and all(t["firm_id"] == FIRM and t["status"] != "completed" and not t["deleted_at"]
                                    for t in got)


# ── section 32 ───────────────────────────────────────────────────────────────

def _asset(i):
    return {"id": f"a{i:06d}", "firm_id": FIRM, "client_id": CLIENT, "deleted_at": None, "is_disposed": False,
            "purchase_date": "2025-06-01", "it_block_key": None, "purchase_cost_paise": 100_00, "asset_name": f"A{i}"}


def test_section_32_reads_every_asset_of_a_large_register():
    from services.section_32_service import Section32Service
    db = CappedDB({"fixed_assets": [_asset(i) for i in range(2500)],
                   "income_tax_asset_blocks": [],
                   "clients": [{"id": CLIENT, "firm_id": FIRM, "section_32_1_iia_business": None}]})
    out = Section32Service().assemble(db, FIRM, CLIENT, "2025-26")
    unplaced = out["unclassified_assets"]
    assert len(unplaced) == 2500, f"{len(unplaced)} of 2500 assets were considered: the read stopped at the row cap"


# ── find_open: the dashboard's open-task counts read every page too ──────────────────────────────────────────────

def test_open_tasks_are_read_on_every_page_so_the_two_counts_on_one_payload_agree(repo):
    """1,500 open tasks, all overdue: `find_overdue` said 1,500 and the open count (through the unpaged `find_all`)
    said 1,000, on one dashboard payload."""
    repo.install([_task(i) for i in range(1500)])
    overdue = repo.find_overdue(firm_id=FIRM)
    open_ = repo.find_open(firm_id=FIRM)
    assert len(overdue) == 1500 and len(open_) == 1500


def test_open_tasks_leave_out_the_completed_the_deleted_and_the_other_firms(repo):
    rows = ([_task(i) for i in range(1100)]
            + [_task(2000 + i, status="completed") for i in range(40)]
            + [_task(3000 + i, deleted="2026-10-02T00:00:00+00:00") for i in range(40)]
            + [_task(4000 + i, firm="other") for i in range(40)])
    repo.install(rows)
    assert len(repo.find_open(firm_id=FIRM)) == 1100


def test_the_overdue_read_asks_for_the_columns_its_readers_use_and_not_every_column(repo):
    db = repo.install([_task(1)])
    repo.find_overdue(firm_id=FIRM)
    columns = {c.strip() for c in db.selects["tasks"][0].split(",")}
    assert columns == {"id", "firm_id", "client_id", "assignee_id", "assigned_to", "due_date", "status"}, columns


def test_the_dashboard_summary_counts_open_tasks_through_the_paged_read(monkeypatch):
    import domain.compliance_record_service as crs
    import domain.task_service as ts

    open_rows = [{"id": f"t{i}", "status": "in_progress", "due_date": "2026-10-01"} for i in range(1500)]
    monkeypatch.setattr(ts.task_repo, "find_open", lambda firm_id=None: open_rows)
    monkeypatch.setattr(ts.task_repo, "find_overdue", lambda firm_id=None: open_rows)

    def unpaged(*a, **k):
        raise AssertionError("the unpaged read must not feed the dashboard's counts")

    monkeypatch.setattr(ts.task_repo, "find_all", unpaged)
    monkeypatch.setattr(ts.client_repo, "find_all", lambda firm_id=None: [])
    monkeypatch.setattr(crs.compliance_record_service, "list_records", lambda firm_id=None, **k: [])
    out = ts.TaskDomainService().get_dashboard_summary(firm_id=FIRM)
    assert out["total_open_tasks"] == 1500 and out["overdue_tasks"] == 1500
