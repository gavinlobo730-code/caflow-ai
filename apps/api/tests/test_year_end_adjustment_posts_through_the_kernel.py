"""
Posting a year-end adjustment writes its journal through the ONE posting
kernel, and could not write one at all before that.

WHAT WAS WRONG
    routers/year_end_adjustments.post_adjustment built a journal_entries dict
    by hand, inserted it, then inserted the two journal_lines in a second
    statement. Both halves were broken.

    (a) The COLUMNS were not the live ones. It sent `source` and
        `source_ref_id`; journal_entries carries `source_type` and `source_id`
        (migration 104). It omitted `client_id` and `entry_type`, both NOT
        NULL with no default (migration 003). Against the real database that
        insert fails, so every approved adjustment 500'd at the last step: the
        CA worked the whole approval trail, clicked Post, and nothing reached
        the ledger — which means the Balance Sheet and P&L they went on to
        sign were the UNADJUSTED ones. Mock mode never noticed because mock
        mode never posts a journal, and the FakeDB accepts any dict.

    (b) It was a SECOND WRITE PATH into the general ledger, which CLAUDE.md
        forbids outright: "Every accounting event that touches the GL is
        written by services/phase2_journal_service._create_journal ... Do not
        add a second write path." The kernel asserts double-entry balance,
        refuses a zero-value entry, checks the client's own year lock
        (migration 289), dedupes on (firm, client, reference_no, entry_date)
        and writes the header with all its lines in ONE transaction
        (post_journal_atomic, migration 152). None of that ran here.

    (a) is the visible bug and (b) is the reason it existed: the kernel is the
    thing that knows what the columns are called, so the fix for both is to
    stop hand-rolling the write.

WHY THE ASSERTIONS ARE SHAPED LIKE THIS
    Asserting only "a journal row exists" would have passed against the old
    code under the FakeDB, which is exactly how this survived. So the column
    names are asserted positively AND the dead ones negatively, and the call
    into the kernel is asserted directly — a future hand-rolled insert that
    happens to name the columns correctly would still be a second write path.
"""
import pytest
from fastapi import HTTPException

from tests.e2e_harness import FakeDB, wire_e2e

PARTNER_F1 = {"firm_id": "F1", "role": "Partner", "auth_user_id": "auth-p1",
              "id": "user-p1", "email": "p1@f1.test"}


def _seed(db, *, status="approved", amount_paise=250_000, date="2025-07-15"):
    eng = db.seed("year_end_engagements",
                  {"firm_id": "F1", "client_id": "C1", "status": "draft"})
    adj = db.seed("year_end_adjustments", {
        "engagement_id": eng["id"], "firm_id": "F1", "client_id": "C1",
        "status": status, "adjustment_date": date,
        "amount_paise": amount_paise,
        "debit_account_id": "ACC-EXPENSE", "credit_account_id": "ACC-ACCRUAL",
        "description": "Accrued audit fee", "adjustment_type": "accrual",
    })
    return eng, adj


# ── (a) the row that reaches journal_entries ─────────────────────────────────

def test_posted_journal_names_the_columns_the_table_actually_has(monkeypatch):
    import routers.year_end_adjustments as m

    db = FakeDB()
    wire_e2e(monkeypatch, db, [m])
    eng, adj = _seed(db)

    m.post_adjustment(eng["id"], adj["id"], PARTNER_F1)

    entries = db.rows("journal_entries")
    assert len(entries) == 1
    e = entries[0]
    # NOT NULL with no default — omitting either is the production 500.
    assert e["client_id"] == "C1"
    assert e["entry_type"] == "Journal"
    assert e["firm_id"] == "F1"
    assert e["entry_date"] == "2025-07-15"
    # migration 104's names, not the invented ones.
    assert e["source_type"] == "year_end_adjustment"
    assert e["source_id"] == adj["id"]
    assert "source" not in e, "`source` is not a column on journal_entries"
    assert "source_ref_id" not in e, "`source_ref_id` is not a column on journal_entries"


def test_created_by_is_the_internal_user_id_not_the_auth_id(monkeypatch):
    """journal_entries.created_by FKs public.users.id (CLAUDE.md). The
    adjustment's own posted_by has no FK and keeps carrying the auth id, so
    the two columns must not be filled from the same value."""
    import routers.year_end_adjustments as m

    db = FakeDB()
    wire_e2e(monkeypatch, db, [m])
    eng, adj = _seed(db)

    m.post_adjustment(eng["id"], adj["id"], PARTNER_F1)

    assert db.rows("journal_entries")[0]["created_by"] == "user-p1"
    assert db.rows("year_end_adjustments")[0]["posted_by"] == "auth-p1"


def test_the_two_lines_balance_in_integer_paise(monkeypatch):
    import routers.year_end_adjustments as m

    db = FakeDB()
    wire_e2e(monkeypatch, db, [m])
    eng, adj = _seed(db, amount_paise=250_000)

    m.post_adjustment(eng["id"], adj["id"], PARTNER_F1)

    entry_id = db.rows("journal_entries")[0]["id"]
    lines = db.rows("journal_lines")
    assert len(lines) == 2
    assert all(l["journal_entry_id"] == entry_id for l in lines)
    assert sum(l["debit_paise"] for l in lines) == 250_000
    assert sum(l["credit_paise"] for l in lines) == 250_000
    dr = next(l for l in lines if l["debit_paise"])
    cr = next(l for l in lines if l["credit_paise"])
    assert dr["account_id"] == "ACC-EXPENSE"
    assert cr["account_id"] == "ACC-ACCRUAL"


def test_the_adjustment_links_the_journal_that_was_actually_written(monkeypatch):
    import routers.year_end_adjustments as m

    db = FakeDB()
    wire_e2e(monkeypatch, db, [m])
    eng, adj = _seed(db)

    resp = m.post_adjustment(eng["id"], adj["id"], PARTNER_F1)

    entry_id = db.rows("journal_entries")[0]["id"]
    row = db.rows("year_end_adjustments")[0]
    assert row["status"] == "posted"
    assert row["journal_entry_id"] == entry_id
    assert resp["data"]["journal_entry_id"] == entry_id


# ── (b) it goes through the kernel, not past it ──────────────────────────────

def test_the_journal_is_written_by_the_posting_kernel(monkeypatch):
    import routers.year_end_adjustments as m
    from services.phase2_journal_service import phase2_journal_service

    db = FakeDB()
    wire_e2e(monkeypatch, db, [m])
    eng, adj = _seed(db)

    calls = []
    real = phase2_journal_service._create_journal

    def _spy(*a, **kw):
        calls.append(kw)
        return real(*a, **kw)

    monkeypatch.setattr(phase2_journal_service, "_create_journal", _spy)

    m.post_adjustment(eng["id"], adj["id"], PARTNER_F1)

    assert len(calls) == 1, "the GL write must go through _create_journal"
    kw = calls[0]
    assert kw["firm_id"] == "F1"
    assert kw["client_id"] == "C1"
    assert kw["entry_type"] == "Journal"
    assert kw["source_type"] == "year_end_adjustment"
    assert kw["source_id"] == adj["id"]
    assert kw["is_posted"] is True
    assert kw["reference_no"] == f"YEA-{adj['id'][:8].upper()}"
    assert [(l["debit_paise"], l["credit_paise"]) for l in kw["lines"]] == [
        (250_000, 0), (0, 250_000)]


def test_nothing_inserts_journal_entries_or_lines_directly(monkeypatch):
    """The kernel reaches Postgres through post_journal_atomic (migration
    152), so a direct .insert() on either table is by definition a second
    write path — including one that names every column correctly."""
    import routers.year_end_adjustments as m

    db = FakeDB()
    wire_e2e(monkeypatch, db, [m])
    eng, adj = _seed(db)

    direct = []
    original_table = db.table

    def _watch(name):
        q = original_table(name)
        if name in ("journal_entries", "journal_lines"):
            real_insert = q.insert

            def _insert(payload, **kw):
                direct.append(name)
                return real_insert(payload, **kw)
            q.insert = _insert
        return q

    monkeypatch.setattr(db, "table", _watch)

    m.post_adjustment(eng["id"], adj["id"], PARTNER_F1)

    assert direct == [], f"direct insert into {set(direct)} — use the kernel"
    assert len(db.rows("journal_entries")) == 1


def test_a_zero_value_adjustment_is_refused_rather_than_posted(monkeypatch):
    """The kernel refuses a balanced-but-zero journal (M8). The hand-rolled
    path posted one, because nothing checked."""
    import routers.year_end_adjustments as m

    db = FakeDB()
    wire_e2e(monkeypatch, db, [m])
    eng, adj = _seed(db, amount_paise=0)

    with pytest.raises(HTTPException) as ei:
        m.post_adjustment(eng["id"], adj["id"], PARTNER_F1)

    assert ei.value.status_code == 422
    assert db.rows("journal_entries") == []
    assert db.rows("year_end_adjustments")[0]["status"] == "approved"


# ── rollback discipline ──────────────────────────────────────────────────────

def test_a_failed_journal_leaves_the_adjustment_re_postable(monkeypatch):
    """Same discipline as purchase_bills.receive_purchase_bill and
    fixed_assets.dispose_asset: the row is claimed first, and a journal that
    does not post puts the claim back. A stuck 'posted' with no journal
    behind it is unrecoverable through the UI — the status guard refuses to
    post it again."""
    import routers.year_end_adjustments as m
    from services.phase2_journal_service import phase2_journal_service

    db = FakeDB()
    wire_e2e(monkeypatch, db, [m])
    eng, adj = _seed(db)

    def _boom(*a, **kw):
        raise RuntimeError("postgrest is down")
    monkeypatch.setattr(phase2_journal_service, "_create_journal", _boom)

    with pytest.raises(HTTPException) as ei:
        m.post_adjustment(eng["id"], adj["id"], PARTNER_F1)

    assert ei.value.status_code == 500
    row = db.rows("year_end_adjustments")[0]
    assert row["status"] == "approved"
    assert row["posted_at"] is None
    assert row.get("journal_entry_id") is None
    assert db.rows("journal_entries") == []


def test_a_refusal_from_the_kernel_keeps_its_own_message(monkeypatch):
    """A closed client year is something the CA can act on. Collapsing it into
    "please try again" tells them to retry what can never succeed."""
    import routers.year_end_adjustments as m
    from services.phase2_journal_service import phase2_journal_service

    db = FakeDB()
    wire_e2e(monkeypatch, db, [m])
    eng, adj = _seed(db)

    def _closed(*a, **kw):
        raise ValueError("FY 2025-26 is closed for this client")
    monkeypatch.setattr(phase2_journal_service, "_create_journal", _closed)

    with pytest.raises(HTTPException) as ei:
        m.post_adjustment(eng["id"], adj["id"], PARTNER_F1)

    assert ei.value.status_code == 422
    assert "closed for this client" in ei.value.detail
    assert db.rows("year_end_adjustments")[0]["status"] == "approved"


def test_posting_the_same_adjustment_twice_writes_one_journal(monkeypatch):
    import routers.year_end_adjustments as m

    db = FakeDB()
    wire_e2e(monkeypatch, db, [m])
    eng, adj = _seed(db)

    m.post_adjustment(eng["id"], adj["id"], PARTNER_F1)
    with pytest.raises(HTTPException) as ei:
        m.post_adjustment(eng["id"], adj["id"], PARTNER_F1)

    assert ei.value.status_code == 422
    assert len(db.rows("journal_entries")) == 1
    assert len(db.rows("journal_lines")) == 2


def test_a_concurrent_winner_takes_the_posting_and_the_loser_never_posts(monkeypatch):
    """The status check above reads, then the claim writes. A request that
    loses that gap must not post a second journal — the conditional claim
    (WHERE status = 'approved') is what makes it 409 instead."""
    import routers.year_end_adjustments as m

    db = FakeDB()
    wire_e2e(monkeypatch, db, [m])
    eng, adj = _seed(db)

    def _someone_else_posts_it_first(firm_id, date_str):
        db.table("year_end_adjustments").update(
            {"status": "posted"}).eq("id", adj["id"]).execute()
    monkeypatch.setattr(m.period_validation_service, "validate_posting_date",
                        _someone_else_posts_it_first)

    with pytest.raises(HTTPException) as ei:
        m.post_adjustment(eng["id"], adj["id"], PARTNER_F1)

    assert ei.value.status_code == 409
    assert db.rows("journal_entries") == []
