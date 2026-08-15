"""
The schema guard's exclusion list must stay smaller than the thing it excuses.

WHAT THIS EXISTS TO PREVENT
    core/schema_guard.py fails /health when the deployed code expects a column
    the live database does not have. It derives "what the code expects" from
    every `ADD COLUMN IF NOT EXISTS` in the migration history, which is an
    approximation — and for 17 of 477 parsed columns it was wrong, because
    production superseded those migrations instead of applying them.

    The consequence was not a cosmetic warning. /health returned 503 on every
    boot, continuously, which disables the entire mechanism: Render's
    healthCheckPath gates deploy cutover, and a check that is always red can
    never distinguish new drift from the standing 17.

    SUPERSEDED_TABLES / SUPERSEDED_COLUMNS fix that. They are also the obvious
    way to defeat the guard — anyone can silence a genuine unapplied migration
    by appending a line. These tests make that expensive and visible:

      * every entry must name something a migration really declares (no typos,
        no entries that outlive the migration they excuse),
      * every reason must be substantive, not a shrug,
      * no superseded TABLE may be queried by live code — the moment someone
        writes .table("transactions"), this fails and the exclusion is wrong,
      * the lists cannot grow without editing the cap here, deliberately.

    And the guard must still do its job: a genuinely missing column on a live
    table is reported exactly as before.
"""
from __future__ import annotations

import re
from pathlib import Path

from core.schema_guard import (
    SUPERSEDED_COLUMNS,
    SUPERSEDED_TABLES,
    check_schema_drift,
    expected_columns_from_migrations,
)

API_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = API_ROOT.parents[1] / "apps" / "web"

# The exclusion list is a liability, not a feature. This cap is the count that
# was justified one entry at a time against the live catalog on 2026-08-15;
# raising it should require the same evidence, which is why it is a number
# someone has to change on purpose rather than a list that quietly grows.
MAX_EXCLUSIONS = 7


def test_the_lists_cannot_grow_without_a_deliberate_edit():
    total = len(SUPERSEDED_TABLES) + len(SUPERSEDED_COLUMNS)
    assert total <= MAX_EXCLUSIONS, (
        f"{total} exclusions, cap is {MAX_EXCLUSIONS}. Adding one silences the "
        f"drift guard for that column. If the new entry is genuinely superseded, "
        f"verify it against the live catalog, raise MAX_EXCLUSIONS, and say so."
    )


def test_every_superseded_table_is_one_a_migration_actually_declares():
    """A stale entry is a hole: the name can come back into use later and skip
    the drift check entirely, which is the failure this guard exists for."""
    expected = expected_columns_from_migrations()
    stale = sorted(t for t in SUPERSEDED_TABLES if t not in expected)

    assert not stale, (
        f"SUPERSEDED_TABLES names tables no migration adds columns to: {stale}. "
        f"The guard never looks at them, so the exemption is dead weight — remove it."
    )


def test_every_superseded_column_is_one_a_migration_actually_declares():
    expected = expected_columns_from_migrations()
    stale = []
    for entry in SUPERSEDED_COLUMNS:
        table, _, column = entry.partition(".")
        if column not in expected.get(table, set()):
            stale.append(entry)

    assert not sorted(stale), (
        f"SUPERSEDED_COLUMNS names columns no migration adds: {sorted(stale)}. "
        f"Either the name is a typo or the migration changed — check before deleting."
    )


def test_no_entry_is_covered_twice():
    """A column excused by both lists means one of the two reasons is untrue,
    and nobody would find out which."""
    doubled = sorted(e for e in SUPERSEDED_COLUMNS if e.split(".")[0] in SUPERSEDED_TABLES)
    assert not doubled, f"covered by both lists: {doubled}"


def test_every_exclusion_states_its_evidence():
    for name, why in {**SUPERSEDED_TABLES, **SUPERSEDED_COLUMNS}.items():
        assert len(why) > 100, (
            f"{name}: say what production has INSTEAD and how you know — a short "
            f"reason here is how a real unapplied migration gets waved through."
        )


def _source_files():
    for root, patterns in ((API_ROOT, ("*.py",)), (WEB_ROOT, ("*.ts", "*.tsx"))):
        if not root.is_dir():
            continue
        for pattern in patterns:
            for path in root.rglob(pattern):
                parts = set(path.parts)
                if parts & {"node_modules", ".next", "__pycache__", ".venv", "migrations", "tests"}:
                    continue
                yield path


def test_no_superseded_table_is_queried_by_live_code():
    """The sharp one. Each SUPERSEDED_TABLES reason claims the table is queried
    by nothing — if that stops being true, the exclusion is hiding a real
    dependency on a table this database does not have, and the endpoint is
    failing in production while CI stays green. That is precisely the incident
    the guard was written for."""
    patterns = {
        name: re.compile(r"""(?:\.table\(|\.from\()\s*["']%s["']""" % re.escape(name))
        for name in SUPERSEDED_TABLES
    }
    hits: dict[str, list[str]] = {}
    scanned = 0
    for path in _source_files():
        try:
            src = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        scanned += 1
        for name, pattern in patterns.items():
            if pattern.search(src):
                hits.setdefault(name, []).append(str(path.relative_to(API_ROOT.parents[1])))

    # Vacuity guard: a scan that walked nothing would pass this test forever.
    assert scanned > 200, f"only scanned {scanned} source files — the walk is broken"
    assert not hits, (
        "these tables are excluded from the drift guard as 'queried by nothing', "
        f"but code queries them: {hits}. Either point that code at the table "
        "production actually has, or the exclusion must go and the table must be created."
    )


# ── the guard still guards ────────────────────────────────────────────────────

class _Rpc:
    def __init__(self, payload): self._payload = payload
    def execute(self): return type("R", (), {"data": self._payload})()


class _Db:
    """get_public_schema_columns() (migration 265): one row, carrying the map and
    an independently-computed total so the caller can prove it got everything."""

    def __init__(self, tables: dict[str, list[str]]):
        self._payload = {
            "total_columns": sum(len(c) for c in tables.values()),
            "tables": tables,
        }

    def rpc(self, name, params):
        assert name == "get_public_schema_columns", f"unexpected RPC {name}"
        return _Rpc(self._payload)


def test_a_genuinely_missing_column_is_still_reported(monkeypatch):
    """The exclusion must be surgical. A missing column on a live table that is
    NOT excused still fails /health."""
    monkeypatch.setattr(
        "core.schema_guard.expected_columns_from_migrations",
        lambda *a, **k: {"filings": {"firm_id", "acknowledgement_number"}},
    )
    db = _Db({"filings": ["id"]})
    result = check_schema_drift(db)

    assert result["missing"] == ["filings.acknowledgement_number"], result
    assert "filings.firm_id" not in result["missing"]


def test_a_superseded_table_absent_entirely_does_not_fail_health(monkeypatch):
    monkeypatch.setattr(
        "core.schema_guard.expected_columns_from_migrations",
        lambda *a, **k: {"transactions": {"supply_type", "cess_paise"}},
    )
    db = _Db({"journal_entries": ["id"]})
    assert check_schema_drift(db) == {"checked": True, "missing": []}


def test_the_real_migration_history_against_the_real_production_shape(monkeypatch):
    """End-to-end over the actual migrations/ directory, against the column set
    production was observed to have on 2026-08-15 (17 expectations unmet, all of
    them excused). Pins the claim that /health goes green — if a future migration
    adds a column, this fails until that migration is applied, which is the
    guard working."""
    expected = expected_columns_from_migrations()
    observed_missing = {
        ("notes_to_accounts", c) for c in ("content", "locked_at", "locked_by",
                                           "note_data", "sequence_no")
    } | {
        ("transactions", c) for c in ("cess_paise", "gst_invoice_category", "invoice_type",
                                      "is_reverse_charge", "original_invoice_id", "supply_type")
    } | {
        ("transaction_lines", "cess_paise"),
        ("year_end_reviews", "actor_id"), ("year_end_reviews", "event_type"),
        ("filings", "firm_id"), ("automation_executions", "firm_id"),
        ("permission_grants", "firm_id"),
    }
    assert len(observed_missing) == 17

    present: dict[str, list[str]] = {}
    for t, cols in expected.items():
        kept = [c for c in cols if (t, c) not in observed_missing]
        if kept:
            present[t] = kept
    result = check_schema_drift(_Db(present))

    assert result == {"checked": True, "missing": []}, (
        "against production's observed schema the guard still reports drift: "
        f"{result['missing']}"
    )
