"""
Service-level tests for the trial-balance import.

The property these exist for, above all others: a trial-balance import and the
master-record opening-balance sync must never see each other's journal entries.
They both post entry_type='Opening', and if they shared a source_type the
opening-balance reconciler would treat an imported trial balance as an unjustified
opening position and back it out on the next customer edit — silently, and only
noticed when a report went wrong weeks later.
"""
import pytest

import services.trial_balance_import_service as tbi
import services.opening_balance_service as obs
from domain.accounting.trial_balance import TrialBalanceRow, TrialBalanceError


def row(name, dr=0, cr=0, typ="Asset", code=None):
    return TrialBalanceRow(account_name=name, account_type=typ,
                           debit_paise=dr, credit_paise=cr, account_code=code)


BALANCED = [row("Cash", dr=500_00), row("Capital", cr=500_00, typ="Equity")]


# ── the separation that matters ─────────────────────────────────────────────

def test_the_two_opening_families_use_different_source_types():
    """If these ever collide, opening_balance_service reverses out every
    imported trial balance. It reconciles the 'Opening' family against master
    records, and an imported trial balance is not justified by any master."""
    assert tbi.TB_SOURCE == "TrialBalance"
    assert obs.OPENING_SOURCE == "Opening"
    assert tbi.TB_SOURCE != obs.OPENING_SOURCE


def test_the_import_queries_only_its_own_family():
    """Pins the filter, not just the constant — a query that forgot to filter by
    source_type would pass the constant check above and still collide."""
    import inspect
    src = inspect.getsource(tbi._current_tb_net)
    assert 'eq("source_type", TB_SOURCE)' in src


def test_the_entry_type_is_one_the_journal_check_constraint_allows():
    """journal_entries_entry_type_check permits exactly these seven."""
    assert tbi.TB_ENTRY_TYPE in {"Sales", "Purchase", "Payment", "Receipt",
                                 "Journal", "Contra", "Opening"}


# ── validation happens before any write ─────────────────────────────────────

def test_an_unbalanced_trial_balance_is_refused_before_the_database_is_touched(monkeypatch):
    """A rejected import must not leave newly created accounts behind."""
    called = []
    monkeypatch.setattr(tbi, "_db", lambda: called.append("db") or None)
    with pytest.raises(TrialBalanceError, match="does not balance"):
        tbi.import_trial_balance("firm-1", "client-1",
                                 [row("Cash", dr=100_00), row("Capital", cr=99_00, typ="Equity")])
    assert called == [], "the database was reached despite an invalid trial balance"


def test_an_empty_import_is_refused_before_the_database_is_touched(monkeypatch):
    called = []
    monkeypatch.setattr(tbi, "_db", lambda: called.append("db") or None)
    with pytest.raises(TrialBalanceError):
        tbi.import_trial_balance("firm-1", "client-1", [])
    assert called == []


def test_mock_mode_reports_that_it_posted_nothing(monkeypatch):
    """Without SUPABASE_URL there is no ledger to post to; it must say so rather
    than claim success."""
    monkeypatch.setattr(tbi, "_USE_MOCK", True)
    result = tbi.import_trial_balance("firm-1", "client-1", BALANCED)
    assert result["posted"] is False
    assert result["mock"] is True


# ── preview ─────────────────────────────────────────────────────────────────

def test_preview_returns_the_totals_without_a_database():
    assert tbi.preview_trial_balance(BALANCED) == {
        "valid": True, "rows": 2,
        "total_debit_paise": 500_00, "total_credit_paise": 500_00,
    }


def test_preview_raises_on_an_unbalanced_trial_balance():
    with pytest.raises(TrialBalanceError, match="does not balance"):
        tbi.preview_trial_balance([row("Cash", dr=1), row("Capital", cr=2, typ="Equity")])


# ── generated account codes ─────────────────────────────────────────────────

def test_a_code_is_generated_because_account_code_is_not_null():
    """chart_of_accounts.account_code is NOT NULL. The old wizard passed
    `account_code || null` straight into its upsert, which would have failed the
    moment the feature was switched on."""
    assert tbi._slug_code("Cash in Hand") == "TB-CASH-IN-HAND"


def test_generated_codes_strip_punctuation_and_bound_their_length():
    # Truncated at 24 chars of slug, so the trailing "3" of "123" is cut.
    assert tbi._slug_code("Bank — HDFC (Current) A/c #123") == "TB-BANK-HDFC-CURRENT-A-C-12"
    assert len(tbi._slug_code("x" * 200)) <= 27


def test_truncation_never_leaves_a_trailing_separator():
    """Cutting at 24 can land on a hyphen; "TB-SOMETHING-" is an ugly code and
    two names differing only past the cut would both produce it."""
    code = tbi._slug_code("Reserves and Surplus " + "General Reserve")
    assert not code.endswith("-")
    assert tbi._slug_code("abcdefghijklmnopqrstuvw xyz") == "TB-ABCDEFGHIJKLMNOPQRSTUVW"


def test_a_nameless_account_still_yields_a_usable_code():
    assert tbi._slug_code("!!!") == "TB-ACCOUNT"


# ── account resolution against a fake db ────────────────────────────────────

class _Resp:
    def __init__(self, data): self.data = data


class _Table:
    def __init__(self, parent, name):
        self.parent, self.name = parent, name
        self._inserted = None

    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def or_(self, *a, **k): return self
    def is_(self, *a, **k): return self
    def in_(self, *a, **k): return self
    def limit(self, *a, **k): return self

    def insert(self, payload):
        self._inserted = payload
        self.parent.inserts.append((self.name, payload))
        return self

    def execute(self):
        if self._inserted is not None:
            return _Resp([{"id": f"new-{len(self.parent.inserts)}"}])
        return _Resp(self.parent.rows.get(self.name, []))


class _FakeDB:
    def __init__(self, rows): self.rows, self.inserts = rows, []
    def table(self, name): return _Table(self, name)


def test_an_existing_account_is_reused_case_insensitively():
    """Without a case-insensitive match, importing "CASH" would try to create a
    second account and hit UNIQUE (firm_id, account_name) at the insert."""
    db = _FakeDB({"chart_of_accounts": [
        {"id": "acc-cash", "account_name": "Cash", "account_code": "1001", "client_id": None},
    ]})
    resolved = tbi._resolve_or_create_accounts(db, "firm-1", "client-1", [row("CASH", dr=1)])
    assert resolved == {"CASH": "acc-cash"}
    assert db.inserts == [], "reused account should not have been re-created"


def test_a_missing_account_is_created_firm_level():
    """client_id NULL matches all 129 production accounts and the firm-level
    UNIQUE (firm_id, account_name); _find_account resolves 'client OR NULL'."""
    db = _FakeDB({"chart_of_accounts": []})
    tbi._resolve_or_create_accounts(db, "firm-1", "client-1",
                                    [row("New Account", dr=1, typ="Expense")])
    assert len(db.inserts) == 1
    _, payload = db.inserts[0]
    assert payload["client_id"] is None
    assert payload["firm_id"] == "firm-1"
    assert payload["account_type"] == "Expense"
    assert payload["account_code"] == "TB-NEW-ACCOUNT"


def test_a_generated_code_that_collides_is_disambiguated_not_failed():
    """Two different names can slug to the same code; one import must not abort
    the other on UNIQUE (firm_id, account_code)."""
    db = _FakeDB({"chart_of_accounts": [
        {"id": "a", "account_name": "Other", "account_code": "TB-CASH", "client_id": None},
    ]})
    tbi._resolve_or_create_accounts(db, "firm-1", "client-1", [row("Cash", dr=1)])
    _, payload = db.inserts[0]
    assert payload["account_code"] == "TB-CASH-2"
