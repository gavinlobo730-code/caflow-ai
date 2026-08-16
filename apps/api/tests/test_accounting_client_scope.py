"""
Client-assignment scope (M2) on accounting.py — Chart of Accounts, Journal
Entries, Ledger, Trial Balance, P&L, Balance Sheet.

chart_of_accounts.client_id is NULLABLE (migration 003: NULL = firm-level
template); journal_entries.client_id is NOT NULL (every journal belongs to
exactly one client). list_journal_entries/create_journal_entry/
post_opening_balances_endpoint/list_journals_queue took client_id from the
query/body and never checked it. update_account and post_journal_entry (the
row-addressed PATCH /journal/{entry_id}/post, backed by the legacy in-memory
engine that is never Supabase-backed regardless of SUPABASE_URL — see the
module note above create_journal_entry) had NO check at all, not even
firm_id; the new resolvers replace the id-embedded NotFoundError text with
ONE fixed message covering missing and hidden alike (year_end.py's
`_assert_engagement_scope` shape). post_draft_journal
(/journals/{journal_id}/post) and reverse_journal_entry
(/journal/{entry_id}/reverse) require `accounting.approve`, Partner-only by
RBAC (the sole firm-wide role) — M2 cannot be bypassed by construction there,
so the new checks close only the firm-BOUNDARY half (the billing.py
record_fee_receipt convention). The seven reporting endpoints now check a
NAMED client_id; client_id=None still aggregates firm-wide (recorded, not
fixed — see get_ledger's docstring).
"""
import pytest
from fastapi import HTTPException

import routers.accounting as acct
import domain.accounting_service as acct_svc
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "firm-1"
MINE, THEIRS = "client-mine", "client-theirs"
EXEC_USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "email": "e@f.test", "role": "Executive"}
MANAGER_USER = {"id": "u2", "firm_id": FIRM, "auth_user_id": "u2", "email": "m@f.test", "role": "Manager"}
PARTNER_USER = {"id": "u3", "firm_id": FIRM, "auth_user_id": "u3", "email": "p@f.test", "role": "Partner"}


@pytest.fixture
def deny(monkeypatch):
    """Refuse THEIRS, allow everything else (including client_id=None) —
    wires all four names the router imports from core.authz so no endpoint
    can pass by using the "wrong" one."""
    seen = []

    def _assert(user, client_id):
        seen.append(client_id)
        if client_id == THEIRS:
            raise HTTPException(status_code=404, detail="Not found")

    def _can(user, client_id):
        seen.append(client_id)
        return client_id != THEIRS

    def _filter(user, rows, key="client_id"):
        return [r for r in rows if not r.get(key) or r.get(key) != THEIRS]

    def _effective(user):
        return None if user is PARTNER_USER else {MINE}

    monkeypatch.setattr(acct, "assert_client_access", _assert)
    monkeypatch.setattr(acct, "can_access_client", _can)
    monkeypatch.setattr(acct, "filter_by_client", _filter)
    monkeypatch.setattr(acct, "effective_client_ids", _effective)
    return seen


@pytest.fixture(autouse=True)
def _clear_mock_stores():
    account_ids_before = {a["id"] for a in acct_svc.MOCK_ACCOUNTS}
    entry_ids_before = {e["id"] for e in acct_svc.MOCK_JOURNAL_ENTRIES}
    yield
    acct_svc.MOCK_ACCOUNTS[:] = [a for a in acct_svc.MOCK_ACCOUNTS if a["id"] in account_ids_before]
    acct_svc.ACCOUNT_INDEX.clear()
    acct_svc.ACCOUNT_INDEX.update({a["id"]: a for a in acct_svc.MOCK_ACCOUNTS})
    acct_svc.MOCK_JOURNAL_ENTRIES[:] = [e for e in acct_svc.MOCK_JOURNAL_ENTRIES if e["id"] in entry_ids_before]
    acct_svc.JOURNAL_INDEX.clear()
    acct_svc.JOURNAL_INDEX.update({e["id"]: e for e in acct_svc.MOCK_JOURNAL_ENTRIES})


def _account(client_id, **extra):
    return acct_svc.accounting_service.create_account({
        "account_code": "9999", "account_name": "Test Account",
        "account_type": "Asset", "client_id": client_id, **extra,
    })


def _entry(entry_id, client_id, firm_id=FIRM, status="posted"):
    row = {
        "id": entry_id, "client_id": client_id, "firm_id": firm_id,
        "entry_date": "2025-04-01", "reference_no": None, "narration": "test",
        "entry_type": "Journal", "status": status,
        "created_by": "x", "created_at": "2025-04-01T00:00:00",
        "lines": [
            {"id": f"{entry_id}-l1", "account_id": "acc-001", "account_name": "x",
             "debit_paise": 100, "credit_paise": 0, "narration": ""},
            {"id": f"{entry_id}-l2", "account_id": "acc-002", "account_name": "x",
             "debit_paise": 0, "credit_paise": 100, "narration": ""},
        ],
    }
    acct_svc.MOCK_JOURNAL_ENTRIES.append(row)
    acct_svc.JOURNAL_INDEX[entry_id] = row
    return row


def _journal_in(client_id, **overrides):
    body = {
        "client_id": client_id, "entry_date": "2025-04-01",
        "lines": [
            {"account_id": "acc-001", "debit_paise": 100, "credit_paise": 0},
            {"account_id": "acc-002", "debit_paise": 0, "credit_paise": 100},
        ],
    }
    body.update(overrides)
    return acct.JournalEntryIn(**body)


# ══════════════════════════════════════════════════════════════════════════
# update_account (_assert_account_scope) — row-addressed by account_id
# ══════════════════════════════════════════════════════════════════════════

def test_updating_a_hidden_clients_account_is_refused(deny):
    acc = _account(THEIRS)
    with pytest.raises(HTTPException) as exc:
        acct.update_account(acc["id"], acct.AccountUpdateIn(is_active=False), current_user=EXEC_USER)
    assert exc.value.status_code == 404
    assert acct_svc.ACCOUNT_INDEX[acc["id"]]["is_active"] is True


def test_updating_an_own_clients_account_is_allowed(deny):
    acc = _account(MINE)
    resp = acct.update_account(acc["id"], acct.AccountUpdateIn(is_active=False), current_user=EXEC_USER)
    assert resp["success"] is True
    assert resp["data"]["is_active"] is False


def test_updating_a_firm_level_account_is_allowed(deny):
    """client_id=None (a firm-level template) can_access_client(user, None) is
    always True — never refused."""
    acc = _account(None)
    resp = acct.update_account(acc["id"], acct.AccountUpdateIn(is_active=False), current_user=EXEC_USER)
    assert resp["success"] is True


def test_missing_and_hidden_account_errors_match(deny):
    acc = _account(THEIRS)
    with pytest.raises(HTTPException) as missing:
        acct.update_account("acc-does-not-exist", acct.AccountUpdateIn(is_active=False), current_user=EXEC_USER)
    with pytest.raises(HTTPException) as hidden:
        acct.update_account(acc["id"], acct.AccountUpdateIn(is_active=False), current_user=EXEC_USER)
    assert missing.value.status_code == hidden.value.status_code == 404
    assert missing.value.detail == hidden.value.detail == "Account not found."


# ══════════════════════════════════════════════════════════════════════════
# list_journal_entries — optional client_id query param, else firm-wide
# ══════════════════════════════════════════════════════════════════════════

def test_listing_journal_entries_with_a_hidden_client_id_is_refused(deny):
    with pytest.raises(HTTPException) as exc:
        acct.list_journal_entries(client_id=THEIRS, start_date=None, end_date=None, current_user=EXEC_USER)
    assert exc.value.status_code == 404


def test_listing_journal_entries_with_an_own_client_id_is_allowed(deny):
    _entry("JE-MINE", MINE)
    resp = acct.list_journal_entries(client_id=MINE, start_date=None, end_date=None, current_user=EXEC_USER)
    assert [e["id"] for e in resp["data"]] == ["JE-MINE"]


def test_listing_journal_entries_without_a_client_id_narrows_to_assigned_clients(deny):
    _entry("JE-MINE", MINE)
    _entry("JE-THEIRS", THEIRS)
    resp = acct.list_journal_entries(client_id=None, start_date=None, end_date=None, current_user=EXEC_USER)
    ids = {e["id"] for e in resp["data"]}
    assert ids == {"JE-MINE"}


# ══════════════════════════════════════════════════════════════════════════
# create_journal_entry — client_id is on the body
# ══════════════════════════════════════════════════════════════════════════

def test_creating_a_journal_entry_for_a_hidden_client_is_refused(deny):
    with pytest.raises(HTTPException) as exc:
        acct.create_journal_entry(_journal_in(THEIRS), current_user=EXEC_USER)
    assert exc.value.status_code == 404
    assert THEIRS in deny


def test_creating_a_journal_entry_for_an_own_client_is_allowed(deny):
    resp = acct.create_journal_entry(_journal_in(MINE), current_user=EXEC_USER)
    assert resp["success"] is True
    assert resp["data"]["client_id"] == MINE


# ══════════════════════════════════════════════════════════════════════════
# post_opening_balances_endpoint — client_id is on the body
# ══════════════════════════════════════════════════════════════════════════

def test_posting_opening_balances_for_a_hidden_client_is_refused(deny):
    with pytest.raises(HTTPException) as exc:
        acct.post_opening_balances_endpoint(
            acct.OpeningBalancePostIn(client_id=THEIRS), current_user=MANAGER_USER)
    assert exc.value.status_code == 404


def test_posting_opening_balances_for_an_own_client_is_allowed(deny):
    resp = acct.post_opening_balances_endpoint(
        acct.OpeningBalancePostIn(client_id=MINE), current_user=MANAGER_USER)
    assert resp["success"] is True


# ══════════════════════════════════════════════════════════════════════════
# post_journal_entry (_assert_journal_scope) — PATCH /journal/{entry_id}/post,
# the legacy in-memory engine
# ══════════════════════════════════════════════════════════════════════════

def test_posting_a_hidden_clients_journal_entry_is_refused(deny):
    _entry("JE1", THEIRS, status="draft")
    with pytest.raises(HTTPException) as exc:
        acct.post_journal_entry("JE1", current_user=PARTNER_USER)
    assert exc.value.status_code == 404
    assert acct_svc.JOURNAL_INDEX["JE1"]["status"] == "draft"


def test_posting_an_own_clients_journal_entry_is_allowed(deny):
    _entry("JE1", MINE, status="draft")
    resp = acct.post_journal_entry("JE1", current_user=PARTNER_USER)
    assert resp["success"] is True
    assert acct_svc.JOURNAL_INDEX["JE1"]["status"] == "posted"


def test_missing_and_hidden_journal_entry_errors_match(deny):
    _entry("JE1", THEIRS, status="draft")
    with pytest.raises(HTTPException) as missing:
        acct.post_journal_entry("JE-does-not-exist", current_user=PARTNER_USER)
    with pytest.raises(HTTPException) as hidden:
        acct.post_journal_entry("JE1", current_user=PARTNER_USER)
    assert missing.value.status_code == hidden.value.status_code == 404
    assert missing.value.detail == hidden.value.detail == "Journal entry not found."


# ══════════════════════════════════════════════════════════════════════════
# The seven reporting endpoints — client_id is checked when named
# ══════════════════════════════════════════════════════════════════════════

def test_ledger_with_a_hidden_client_id_is_refused(deny):
    with pytest.raises(HTTPException) as exc:
        acct.get_ledger(account_id="acc-001", client_id=THEIRS, start_date=None,
                        end_date=None, current_user=EXEC_USER)
    assert exc.value.status_code == 404


def test_ledger_with_an_own_client_id_is_allowed(deny):
    resp = acct.get_ledger(account_id="acc-001", client_id=MINE, start_date=None,
                           end_date=None, current_user=EXEC_USER)
    assert resp["success"] is True


def test_trial_balance_with_a_hidden_client_id_is_refused(deny):
    with pytest.raises(HTTPException) as exc:
        acct.get_trial_balance(as_of_date=None, client_id=THEIRS, current_user=EXEC_USER)
    assert exc.value.status_code == 404


def test_profit_loss_with_a_hidden_client_id_is_refused(deny):
    with pytest.raises(HTTPException) as exc:
        acct.get_profit_loss(start_date=None, end_date=None, client_id=THEIRS, current_user=EXEC_USER)
    assert exc.value.status_code == 404


def test_balance_sheet_with_a_hidden_client_id_is_refused(deny):
    with pytest.raises(HTTPException) as exc:
        acct.get_balance_sheet(as_of_date=None, client_id=THEIRS, current_user=EXEC_USER)
    assert exc.value.status_code == 404


def test_schedule_iii_with_a_hidden_client_id_is_refused(deny):
    with pytest.raises(HTTPException) as exc:
        acct.get_schedule_iii(fy_start=None, fy_end=None, client_id=THEIRS, current_user=EXEC_USER)
    assert exc.value.status_code == 404


def test_cash_flow_with_a_hidden_client_id_is_refused(deny):
    with pytest.raises(HTTPException) as exc:
        acct.get_cash_flow(start_date=None, end_date=None, client_id=THEIRS, current_user=EXEC_USER)
    assert exc.value.status_code == 404


def test_statement_analysis_with_a_hidden_client_id_is_refused(deny):
    import asyncio
    with pytest.raises(HTTPException) as exc:
        asyncio.run(acct.get_statement_analysis(
            financial_year="2025-26", client_id=THEIRS, current_user=EXEC_USER))
    assert exc.value.status_code == 404


# ══════════════════════════════════════════════════════════════════════════
# Live mode (e2e FakeDB) — post_draft_journal / reverse_journal_entry /
# list_journals_queue query journal_entries directly and short-circuit
# BEFORE the guard in mock mode (db is None), so the tests above never
# exercise these branches.
# ══════════════════════════════════════════════════════════════════════════

def _e2e_setup(monkeypatch):
    db = FakeDB()
    monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.test")
    wire_e2e(monkeypatch, db, [acct])
    return db


def test_live_posting_a_draft_journal_for_a_hidden_client_is_refused(deny, monkeypatch):
    db = _e2e_setup(monkeypatch)
    db.seed("journal_entries", {"id": "J1", "firm_id": FIRM, "client_id": THEIRS,
                                "is_posted": False, "entry_date": "2025-04-01"})
    with pytest.raises(HTTPException) as exc:
        acct.post_draft_journal("J1", current_user=PARTNER_USER)
    assert exc.value.status_code == 404
    assert db.rows("journal_entries")[0]["is_posted"] is False


def test_live_posting_a_draft_journal_for_an_own_client_is_allowed(deny, monkeypatch):
    db = _e2e_setup(monkeypatch)
    # FakeDB does not resolve PostgREST embeds (journal_lines(...)) — seed the
    # embedded key directly on the row, matching what a real embedded select
    # returns.
    db.seed("journal_entries", {
        "id": "J1", "firm_id": FIRM, "client_id": MINE,
        "is_posted": False, "entry_date": "2025-04-01",
        "journal_lines": [
            {"account_id": "a1", "debit_paise": 100, "credit_paise": 0},
            {"account_id": "a2", "debit_paise": 0, "credit_paise": 100},
        ],
    })
    resp = acct.post_draft_journal("J1", current_user=PARTNER_USER)
    assert resp["success"] is True


def test_live_posting_a_missing_draft_journal_500s_on_a_pre_existing_single_bug(deny, monkeypatch):
    """Not the fix under test: journal_posting_service.post_draft's own
    lookup uses .single(), which raises on zero rows instead of resolving to
    a clean 404 — the same pre-existing shape already found (and left
    unfixed, out of proportion to a client-scope pass) in health.py,
    relationships.py, lifecycle.py, engagement_letters.py, fixed_assets.py
    and form_26as.py. _assert_draft_scope itself does not raise here (the
    row genuinely does not exist, so there is nothing to hide) — the crash
    happens one line further in, in code this phase did not touch."""
    _e2e_setup(monkeypatch)
    with pytest.raises(Exception, match="PGRST116"):
        acct.post_draft_journal("J-does-not-exist", current_user=PARTNER_USER)


def test_live_reversing_a_hidden_clients_journal_is_refused(deny, monkeypatch):
    db = _e2e_setup(monkeypatch)
    db.seed("journal_entries", {"id": "J1", "firm_id": FIRM, "client_id": THEIRS,
                                "is_posted": True, "entry_type": "Journal",
                                "reference_no": "REF-1"})
    with pytest.raises(HTTPException) as exc:
        acct.reverse_journal_entry("J1", acct.JournalReversalIn(reversal_date="2025-04-02"),
                                   current_user=PARTNER_USER)
    assert exc.value.status_code == 404
    assert exc.value.detail == "Journal entry not found"


def test_live_reversing_a_missing_journal_uses_the_same_message_as_hidden(deny, monkeypatch):
    db = _e2e_setup(monkeypatch)
    db.seed("journal_entries", {"id": "J1", "firm_id": FIRM, "client_id": THEIRS,
                                "is_posted": True, "entry_type": "Journal",
                                "reference_no": "REF-1"})
    with pytest.raises(HTTPException) as missing:
        acct.reverse_journal_entry("J-does-not-exist", acct.JournalReversalIn(reversal_date="2025-04-02"),
                                   current_user=PARTNER_USER)
    with pytest.raises(HTTPException) as hidden:
        acct.reverse_journal_entry("J1", acct.JournalReversalIn(reversal_date="2025-04-02"),
                                   current_user=PARTNER_USER)
    assert missing.value.status_code == hidden.value.status_code == 404
    assert missing.value.detail == hidden.value.detail == "Journal entry not found"


def test_live_listing_journals_without_a_client_id_narrows_to_assigned_clients(deny, monkeypatch):
    db = _e2e_setup(monkeypatch)
    db.seed("journal_entries", {"id": "J-MINE", "firm_id": FIRM, "client_id": MINE,
                                "is_posted": False, "entry_date": "2025-04-01"})
    db.seed("journal_entries", {"id": "J-THEIRS", "firm_id": FIRM, "client_id": THEIRS,
                                "is_posted": False, "entry_date": "2025-04-01"})
    resp = acct.list_journals_queue(client_id=None, status="draft", current_user=EXEC_USER)
    ids = {j["id"] for j in resp["data"]}
    assert ids == {"J-MINE"}


def test_live_listing_journals_with_a_hidden_client_id_is_refused(deny, monkeypatch):
    db = _e2e_setup(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        acct.list_journals_queue(client_id=THEIRS, status="draft", current_user=EXEC_USER)
    assert exc.value.status_code == 404


# ══════════════════════════════════════════════════════════════════════════
# GET / PATCH /journal/{entry_id} — the editable-until-locked routes
# (migration 266). These call the router FUNCTIONS, which is the whole point:
# both endpoints shipped calling a scope helper that had been shadowed by a
# same-named function defined later in the module, so every request raised
# TypeError. 6982 tests passed anyway, because the suite exercised the
# SERVICE and nothing walked these two routes.
# ══════════════════════════════════════════════════════════════════════════

def _seed_editable_entry(db, client_id=MINE):
    """A posted entry with its lines. FakeDB does not resolve PostgREST
    embeds, so the aliased `lines:journal_lines(...)` select is seeded as the
    alias key directly, matching what the real embed returns."""
    db.seed("journal_entries", {
        "id": "J1", "firm_id": FIRM, "client_id": client_id,
        "entry_date": "2025-06-15", "reference_no": "MJ-1", "narration": "Rent",
        "entry_type": "Journal", "is_posted": True, "is_reversed": False,
        "source_type": "manual", "deleted_at": None,
        "lines": [
            {"id": "L1", "account_id": "a1", "debit_paise": 500000, "credit_paise": 0, "narration": ""},
            {"id": "L2", "account_id": "a2", "debit_paise": 0, "credit_paise": 500000, "narration": ""},
        ],
    })


def test_live_reading_an_own_clients_journal_entry_is_allowed(deny, monkeypatch):
    db = _e2e_setup(monkeypatch)
    _seed_editable_entry(db)

    resp = acct.get_journal_entry("J1", current_user=EXEC_USER)

    assert resp["success"] is True
    assert resp["data"]["id"] == "J1"
    # Both halves of the editor's contract are present, not just the row.
    assert "editable" in resp["data"] and "lock_reason" in resp["data"]
    assert resp["data"]["total_debit_paise"] == 500000


def test_live_reading_a_hidden_clients_journal_entry_is_refused(deny, monkeypatch):
    db = _e2e_setup(monkeypatch)
    _seed_editable_entry(db, client_id=THEIRS)

    with pytest.raises(HTTPException) as exc:
        acct.get_journal_entry("J1", current_user=EXEC_USER)
    assert exc.value.status_code == 404


def test_live_reading_a_missing_journal_entry_matches_the_hidden_message(deny, monkeypatch):
    db = _e2e_setup(monkeypatch)
    _seed_editable_entry(db, client_id=THEIRS)

    with pytest.raises(HTTPException) as missing:
        acct.get_journal_entry("J-does-not-exist", current_user=EXEC_USER)
    with pytest.raises(HTTPException) as hidden:
        acct.get_journal_entry("J1", current_user=EXEC_USER)
    assert missing.value.status_code == hidden.value.status_code == 404
    assert missing.value.detail == hidden.value.detail


def test_live_editing_a_hidden_clients_journal_entry_is_refused(deny, monkeypatch):
    db = _e2e_setup(monkeypatch)
    _seed_editable_entry(db, client_id=THEIRS)

    with pytest.raises(HTTPException) as exc:
        acct.update_journal_entry(
            "J1", acct.JournalEntryUpdateIn(narration="edited"), current_user=MANAGER_USER)
    assert exc.value.status_code == 404
    assert db.rows("journal_entries")[0]["narration"] == "Rent", "a refused edit still wrote"


def test_live_editing_a_missing_journal_entry_is_refused(deny, monkeypatch):
    _e2e_setup(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        acct.update_journal_entry(
            "J-does-not-exist", acct.JournalEntryUpdateIn(narration="edited"),
            current_user=MANAGER_USER)
    assert exc.value.status_code == 404


def test_both_journal_scope_helpers_survive_side_by_side():
    """The two guards in this module read different engines and take different
    arguments — the Supabase-backed one used by GET/PATCH /journal/{id}, and
    the legacy in-memory one used by PATCH /journal/{id}/post. Naming them the
    same silently bound BOTH call sites to whichever came last in the file.
    """
    import inspect
    assert list(inspect.signature(acct._assert_journal_scope_db).parameters) == \
        ["db", "current_user", "entry_id"]
    assert list(inspect.signature(acct._assert_journal_scope).parameters) == \
        ["current_user", "entry_id"]
