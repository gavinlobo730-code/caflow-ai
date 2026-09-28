"""sweep-reports-documents-05 (Phase 5) — compliance_records_repository.find_all
read every matching row through one unpaged `.execute()`, capped by PostgREST's
db-max-rows (~1000) with no signal that it happened. A firm-wide read (the /gst
tracker, the risk register's own consumers, the AI copilot) would silently work
from a truncated set once a practice's compliance_records history passed that
line.

`find_all` now goes through core.db_paging.fetch_all, the shared helper this
codebase already uses everywhere else a query can return more than a page (see
CLAUDE.md's "Reporting performance" section). fetch_all pages by cursor on
`id` and orders the combined result by `id`, so `find_all`'s own `due_date`
ordering has to be restored afterwards over the whole set rather than inside
the paged query — this pins that restoration too, since a silent reversion to
unordered output would look like "it still works" on every small fixture.
"""
from __future__ import annotations

import pytest

import core.db_paging as db_paging
import core.supabase_client as sc
import repositories.compliance_records_repository as repo_mod
from repositories.compliance_records_repository import compliance_records_repo
from tests.e2e_harness import FakeDB

FIRM = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
CLIENT = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


@pytest.fixture()
def db(monkeypatch):
    d = FakeDB()
    monkeypatch.setattr(sc, "get_supabase", lambda: d)
    monkeypatch.setattr(repo_mod, "_USE_MOCK", False)
    return d


def _seed(db, n: int, *, firm_id=FIRM):
    for i in range(n):
        db.seed("compliance_records", {
            "firm_id": firm_id, "client_id": CLIENT, "compliance_type": "GST",
            "obligation_type": "GSTR1", "status": "Not Started",
            "period_label": f"Month {i}",
            "due_date": f"2026-{(i % 12) + 1:02d}-01",
        })


def test_find_all_reads_past_a_single_page(db, monkeypatch):
    """A single unpaged `.execute()` looks identical to a paged read once the
    dataset is smaller than one page, so the page size is shrunk here to force
    a real multi-page walk without seeding a thousand rows."""
    monkeypatch.setattr(db_paging, "PAGE", 3)
    _seed(db, 10)
    rows = compliance_records_repo.find_all(firm_id=FIRM)
    assert len(rows) == 10


def test_another_firms_records_are_not_read(db, monkeypatch):
    monkeypatch.setattr(db_paging, "PAGE", 3)
    _seed(db, 4, firm_id=FIRM)
    _seed(db, 4, firm_id="cccccccc-cccc-4ccc-8ccc-cccccccccccc")
    rows = compliance_records_repo.find_all(firm_id=FIRM)
    assert len(rows) == 4


def test_find_all_is_still_ordered_by_due_date(db):
    """fetch_all orders the paged read by `id`; find_all's own contract is
    `due_date` order, so it must be re-applied over the complete result."""
    for due in ("2026-05-01", "2026-01-01", "2026-03-01"):
        db.seed("compliance_records", {
            "firm_id": FIRM, "client_id": CLIENT, "compliance_type": "GST",
            "obligation_type": "GSTR1", "status": "Not Started", "due_date": due,
        })
    rows = compliance_records_repo.find_all(firm_id=FIRM)
    assert [r["due_date"] for r in rows] == ["2026-01-01", "2026-03-01", "2026-05-01"]


def test_exclude_statuses_still_filters_across_pages(db, monkeypatch):
    monkeypatch.setattr(db_paging, "PAGE", 3)
    for i in range(6):
        db.seed("compliance_records", {
            "firm_id": FIRM, "client_id": CLIENT, "compliance_type": "GST",
            "obligation_type": "GSTR1",
            "status": "Filed" if i % 2 == 0 else "Not Started",
            "due_date": f"2026-{(i % 12) + 1:02d}-01",
        })
    open_only = compliance_records_repo.find_all(firm_id=FIRM, exclude_statuses=("Filed",))
    assert len(open_only) == 3
    assert all(r["status"] != "Filed" for r in open_only)
