"""
The Tally import must survive a real CA's data, not a demo's.

WHAT WENT WRONG
    The import path had four defects that only appear above ~1000 items, which
    is to say: never in testing, and immediately on first contact with a paying
    customer's books.

      1. execute_import read its work list with an unpaged
         `.select("*").eq("job_id", ...)`. PostgREST caps a response at ~1000
         rows and says nothing, so the importer processed the first 1000 items,
         wrote status='completed', and reported success. Items 1001+ were never
         touched and nothing anywhere recorded that.

      2. rollback_migration read the same way, so the designated remedy for a
         bad import could itself only undo the first 1000 records.

      3. get_migration_preview read the same way, so the CA approved a list
         they had only partly been shown.

      4. The whole thing ran inside the HTTP request under gunicorn's
         `--timeout 120`, at two round trips per item. Past roughly 1,200 items
         the worker was killed mid-write.

    This is audit C6 — the same silent PostgREST truncation that had already
    hit the reporting ledger and the schema guard. Its third and fourth
    appearance, on the path that carries a CA's entire book of accounts.

WHY THESE TESTS USE 2,500 ITEMS
    Any count over the 1000 cap would do, but a number that is not a multiple of
    the page size also catches an off-by-one at the final short page, and 2,500
    spans three pages so the cursor has to advance correctly twice rather than
    once.
"""
from __future__ import annotations

import pytest

import domain.tally.migration_service as svc


FIRM = "firm-1"
JOB = "job-1"


# ── A fake PostgREST that truncates exactly like the real one ────────────────

class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    """Chainable stub honouring eq/gt/order/limit, and — crucially — capping an
    un-limited response at CAP the way PostgREST's db-max-rows does."""

    CAP = 1000

    def __init__(self, rows: list[dict], table: str, store: "_Store"):
        self._rows = rows
        self._table = table
        self._store = store
        self._limit: int | None = None

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self._rows = [r for r in self._rows if r.get(col) == val]
        return self

    def gt(self, col, val):
        self._rows = [r for r in self._rows if str(r.get(col)) > str(val)]
        return self

    def order(self, col, **_k):
        self._rows = sorted(self._rows, key=lambda r: str(r.get(col)))
        return self

    def limit(self, n):
        self._limit = n
        return self

    def execute(self):
        rows = self._rows
        # The whole point: an unbounded read is silently truncated.
        n = self._limit if self._limit is not None else self.CAP
        self._store.reads.append((self._table, len(rows[:n])))
        return _Result([dict(r) for r in rows[:n]])

    # writes. The real client returns a BUILDER from insert/update/delete that
    # the caller then .execute()s — the stub must do the same or it tests a
    # shape the production code never sees.
    def insert(self, rows):
        rows = rows if isinstance(rows, list) else [rows]
        return _InsertQuery(rows, self._table, self._store)

    def update(self, patch):
        self._store.updates.append((self._table, patch))
        return _UpdateQuery(self._rows, patch)

    def delete(self):
        return _DeleteQuery(self._rows, self._table, self._store)


class _InsertQuery:
    def __init__(self, rows, table, store):
        self._rows, self._table, self._store = rows, table, store

    def execute(self):
        self._store.inserts.append((self._table, len(self._rows)))
        bucket = self._store.data.setdefault(self._table, [])
        for r in self._rows:
            bucket.append(dict(r))
        return _Result([{"id": f"new-{len(bucket)}"}])


class _DeleteQuery:
    def __init__(self, rows, table, store):
        self._rows, self._table, self._store = rows, table, store

    def eq(self, col, val):
        self._rows = [r for r in self._rows if r.get(col) == val]
        return self

    def execute(self):
        self._store.deletes.append((self._table, len(self._rows)))
        return _Result(self._rows)


class _UpdateQuery:
    def __init__(self, rows, patch):
        self._rows, self._patch = rows, patch

    def eq(self, col, val):
        self._rows = [r for r in self._rows if r.get(col) == val]
        return self

    def execute(self):
        for r in self._rows:
            r.update(self._patch)
        return _Result(self._rows)


class _Store:
    def __init__(self, items: list[dict], job: dict):
        self.data = {"tally_migration_items": items, "tally_migration_jobs": [job]}
        self.reads: list[tuple[str, int]] = []
        self.inserts: list[tuple[str, int]] = []
        self.updates: list[tuple[str, dict]] = []
        self.deletes: list[tuple[str, int]] = []

    def table(self, name):
        return _Query(self.data.setdefault(name, []), name, self)


def _items(n: int, status: str = "pending") -> list[dict]:
    # Zero-padded so lexicographic ordering on the uuid-ish id is stable, which
    # is what keyset paging relies on.
    return [{"id": f"i{i:05d}", "job_id": JOB, "firm_id": FIRM, "status": status,
             "item_type": "customer", "tally_data": {"name": f"C{i}"}}
            for i in range(n)]


@pytest.fixture
def store(monkeypatch):
    st = _Store(_items(2500), {"id": JOB, "firm_id": FIRM, "client_id": "cl-1"})
    monkeypatch.setattr(svc, "_USE_MOCK", False)
    monkeypatch.setattr(svc, "_supabase", lambda: st)
    return st


# ── The truncation ───────────────────────────────────────────────────────────

def test_the_stub_truncates_like_postgrest_does():
    """Vacuity guard. If the fake did not cap, every test below would pass
    against the unpaged code too and prove nothing."""
    st = _Store(_items(2500), {"id": JOB, "firm_id": FIRM})
    got = st.table("tally_migration_items").select("*").eq("job_id", JOB).execute()

    assert len(got.data) == 1000, "the fake must cap like db-max-rows, or it tests nothing"


def test_every_item_is_read_not_just_the_first_page(store):
    got = svc._all_items(store, JOB, FIRM)

    assert len(got) == 2500, f"paged read returned {len(got)} of 2500"
    assert len({r["id"] for r in got}) == 2500, "duplicate rows across pages"


def test_paging_walks_forward_and_terminates(store):
    """A cursor that fails to advance loops forever on page 1; one that advances
    wrongly skips rows. Three pages for 2,500 at 1,000/page (1000+1000+500)."""
    svc._all_items(store, JOB, FIRM)
    item_reads = [n for (t, n) in store.reads if t == "tally_migration_items"]

    assert item_reads == [1000, 1000, 500], f"expected 3 pages, got {item_reads}"


def test_a_short_final_page_ends_the_walk_without_an_extra_round_trip(monkeypatch):
    """Exactly one full page then nothing. End-of-data is the short page, so an
    exact multiple must not cost a wasted empty read... and must not stop early
    either."""
    st = _Store(_items(1000), {"id": JOB, "firm_id": FIRM})
    monkeypatch.setattr(svc, "_USE_MOCK", False)
    got = svc._all_items(st, JOB, FIRM)

    assert len(got) == 1000
    assert [n for (t, n) in st.reads if t == "tally_migration_items"] == [1000, 0]


# ── The import ───────────────────────────────────────────────────────────────

def test_the_import_processes_every_item_past_the_cap(store, monkeypatch):
    monkeypatch.setattr(svc, "_import_single_item",
                        lambda *a, **k: ("rec-1", "customers"))
    report = svc.execute_import(FIRM, JOB, "actor-1", is_dry_run=False)

    assert report["imported"] == 2500, (
        f"imported {report['imported']} of 2500 — the unpaged read stopped at 1000")
    assert report["total"] == 2500


def test_a_resumed_import_skips_what_already_landed(monkeypatch):
    """The resumability contract. Half the job is already imported — from a run
    killed by a deploy, an OOM or a free-tier spin-down. Re-running must finish
    the rest and NOT create a second record for the finished half."""
    items = _items(2500)
    for r in items[:1200]:
        r["status"] = "imported"
    st = _Store(items, {"id": JOB, "firm_id": FIRM, "client_id": "cl-1"})
    monkeypatch.setattr(svc, "_USE_MOCK", False)
    monkeypatch.setattr(svc, "_supabase", lambda: st)

    created = []
    monkeypatch.setattr(svc, "_import_single_item",
                        lambda f, c, item, sb: (created.append(item["id"]) or
                                                ("rec", "customers")))
    report = svc.execute_import(FIRM, JOB, "actor-1", is_dry_run=False)

    assert len(created) == 1300, f"re-imported {len(created)}, expected only the 1300 unfinished"
    assert report["imported"] == 2500, "the finished 1200 must still count as imported"
    assert not any(i in created for i in [r["id"] for r in items[:1200]]), \
        "an already-imported item was imported a second time — duplicate records"


def test_progress_is_written_while_the_import_runs(store, monkeypatch):
    """Without a heartbeat, a long import and a hung one look identical — to the
    CA watching, and to whoever debugs it."""
    monkeypatch.setattr(svc, "_import_single_item",
                        lambda *a, **k: ("rec-1", "customers"))
    svc.execute_import(FIRM, JOB, "actor-1", is_dry_run=False)

    job_updates = [p for (t, p) in store.updates if t == "tally_migration_jobs"]
    progress = [p for p in job_updates if "imported_items" in p and "status" not in p]

    assert len(progress) >= 10, f"only {len(progress)} progress writes across 2500 items"
    counts = [p["imported_items"] for p in progress]
    assert counts == sorted(counts), "progress went backwards"
    assert any(p.get("status") == "importing" for p in job_updates), \
        "job never marked running — a caller cannot tell started from never-started"


def test_a_dry_run_writes_nothing(store, monkeypatch):
    monkeypatch.setattr(svc, "_import_single_item",
                        lambda *a, **k: pytest.fail("dry run must not import"))
    report = svc.execute_import(FIRM, JOB, "actor-1", is_dry_run=True)

    assert report["imported"] == 0
    assert report["skipped"] == 2500
    assert not [t for (t, _) in store.inserts], "a dry run inserted rows"


# ── Rollback ─────────────────────────────────────────────────────────────────

def test_rollback_reaches_every_created_record(monkeypatch):
    """The remedy has to cover the whole of what it is undoing. Capped at 1000,
    a rollback left the rest of a bad import in the client's books for good."""
    items = _items(2500, status="imported")
    for r in items:
        r["created_record_id"] = f"rec-{r['id']}"
        r["created_record_type"] = "customers"
    st = _Store(items, {"id": JOB, "firm_id": FIRM})
    # The importer created these in `customers`; rollback deletes from there.
    st.data["customers"] = [{"id": r["created_record_id"], "firm_id": FIRM}
                            for r in items]
    monkeypatch.setattr(svc, "_USE_MOCK", False)
    monkeypatch.setattr(svc, "_supabase", lambda: st)

    report = svc.rollback_migration(FIRM, JOB, "actor-1")

    assert report["records_deleted"] == 2500, (
        f"deleted {report['records_deleted']} of 2500 — the unpaged read capped it")
    assert report["rolled_back"] is True
    assert len([t for (t, _n) in st.deletes if t == "customers"]) == 2500


# ── The write side ───────────────────────────────────────────────────────────

def test_saving_items_is_chunked_not_one_giant_insert(monkeypatch):
    """One insert carrying a whole Tally export is a single enormous request
    body, and a failure anywhere in it loses everything parsed so far."""
    st = _Store([], {"id": JOB, "firm_id": FIRM})
    monkeypatch.setattr(svc, "_USE_MOCK", False)
    monkeypatch.setattr(svc, "_supabase", lambda: st)

    svc.save_migration_items(FIRM, JOB, [{"item_type": "customer"} for _ in range(2500)])
    sizes = [n for (t, n) in st.inserts if t == "tally_migration_items"]

    assert sum(sizes) == 2500, "not every row was written"
    assert max(sizes) <= svc._INSERT_CHUNK, f"a chunk of {max(sizes)} exceeds the limit"
    assert len(sizes) == 5, f"2500 at {svc._INSERT_CHUNK}/chunk is 5 inserts, got {len(sizes)}"
