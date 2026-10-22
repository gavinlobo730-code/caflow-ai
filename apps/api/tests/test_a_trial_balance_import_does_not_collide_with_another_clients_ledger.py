"""A trial-balance import never collides with a ledger another client of the firm owns (ledger POST-A-313).

THE DEFECT
    `_resolve_or_create_accounts` read `chart_of_accounts` for "this client OR firm-level" and built both its name map and its set
    of used codes from that. But the table is unique on (firm_id, account_code) and on (firm_id, account_name), whichever client an
    account belongs to, and a client can own a ledger (the per-bank ledgers `routers/banking._ensure_bank_ledger` creates carry the
    client's id, codes from 1101 up, names such as "HDFC Bank - 7890"). Another client's ledger was invisible to the import, so a
    trial-balance row that slugged or was numbered to the same code, or was named the same, answered 23505 at the insert and the
    endpoint (which turns only `TrialBalanceError` and `ValueError` into a 422) answered a generic 500. The filter was the
    import's own and not row security, so a Partner was hit too.

WHAT IS HELD (no database; a double that refuses a duplicate the way the two unique keys do and answers at most a page)
    * a code another client's ledger holds is never chosen: the import numbers past it, in any page of the firm's chart;
    * a name another client's ledger holds is not matched as this client's account and cannot be created again: the import is
      refused in words BEFORE it creates anything, naming the row;
    * a name this client's own ledger holds, or a firm-level account holds, still matches (case-insensitively), as before;
    * the chart is read with the privileged client where there is one, whatever the caller was handed, and in keyset pages.
"""
from __future__ import annotations

import pytest

import core.db_provider
import services.trial_balance_import_service as tbi
from domain.accounting.trial_balance import TrialBalanceError, TrialBalanceRow
from tests._capped_postgrest import CappedQuery, DB_MAX_ROWS

FIRM, ME, OTHER = "firm-313", "client-me", "client-other"


class _Duplicate(Exception):
    code = "23505"


class _UniqueQuery(CappedQuery):
    def __init__(self, db):
        super().__init__(db.rows, db.log)
        self._db, self._insert = db, None

    def insert(self, row):
        self._insert = row
        return self

    def execute(self):
        if self._insert is None:
            return super().execute()
        row = dict(self._insert)
        for existing in self._db.rows:
            if existing["firm_id"] == row["firm_id"] and (existing["account_code"] == row["account_code"]
                                                           or existing["account_name"] == row["account_name"]):
                raise _Duplicate("duplicate key value violates unique constraint (firm_id, account_code / account_name)")
        row["id"] = f"new-{len(self._db.rows)}"
        self._db.rows.append(row)

        class R:
            data = [row]
        return R()


class _Db:
    """chart_of_accounts only: rows are dicts with firm_id, id, account_name, account_code, client_id."""

    def __init__(self, rows):
        self.rows, self.log, self.reads = list(rows), [], 0

    def table(self, name):
        assert name == "chart_of_accounts", name
        self.reads += 1
        return _UniqueQuery(self)


def acct(i, name, code, client=None):
    return {"id": f"a{i:05d}", "firm_id": FIRM, "account_name": name, "account_code": code, "client_id": client}


def tb(name, code=None, typ="Asset"):
    return TrialBalanceRow(account_name=name, account_type=typ, debit_paise=100, credit_paise=0, account_code=code)


@pytest.fixture(autouse=True)
def no_privileged_client(monkeypatch):
    monkeypatch.setattr(core.db_provider, "service_db_or_none", lambda: None)


def test_a_code_another_clients_ledger_holds_is_numbered_past(monkeypatch):
    db = _Db([acct(1, "HDFC Bank - 7890", "1101", client=OTHER)])
    resolved = tbi._resolve_or_create_accounts(db, FIRM, ME, [tb("Savings account", code="1101")])
    created = next(r for r in db.rows if r["id"] == resolved["Savings account"])
    assert created["account_code"] == "1101-2" and created["client_id"] is None


def test_a_slugged_code_another_clients_ledger_holds_is_numbered_past():
    db = _Db([acct(1, "Some bank ledger", "TB-CASH", client=OTHER)])
    resolved = tbi._resolve_or_create_accounts(db, FIRM, ME, [tb("Cash")])
    created = next(r for r in db.rows if r["id"] == resolved["Cash"])
    assert created["account_code"] == "TB-CASH-2"


def test_a_name_another_clients_ledger_holds_refuses_the_import_in_words_before_anything_is_created():
    db = _Db([acct(1, "HDFC Bank - 7890", "1101", client=OTHER)])
    with pytest.raises(TrialBalanceError) as refused:
        tbi._resolve_or_create_accounts(db, FIRM, ME, [tb("Cash"), tb("hdfc bank - 7890")])
    assert "hdfc bank - 7890" in str(refused.value) and "another client" in str(refused.value)
    assert [r["id"] for r in db.rows] == ["a00001"], "an account was created before the refusal"


def test_this_clients_own_ledger_and_a_firm_level_account_still_match_by_name_without_regard_to_case():
    db = _Db([acct(1, "Cash", "TB-CASH"), acct(2, "My bank", "1102", client=ME), acct(3, "Theirs", "1103", client=OTHER)])
    resolved = tbi._resolve_or_create_accounts(db, FIRM, ME, [tb("CASH"), tb("my BANK")])
    assert resolved == {"CASH": "a00001", "my BANK": "a00002"}
    assert len(db.rows) == 3                                           # nothing was created


def test_a_client_id_written_in_capitals_is_still_this_clients_own():
    """A uuid compares as the lower-case text the database returns, so an id typed in capitals does not turn this client's own
    ledger into another client's (which would refuse an import that names it)."""
    db = _Db([acct(1, "My bank", "1102", client="3f2c9a10-0000-4000-8000-00000000000a")])
    resolved = tbi._resolve_or_create_accounts(db, FIRM, "3F2C9A10-0000-4000-8000-00000000000A", [tb("my BANK")])
    assert resolved == {"my BANK": "a00001"}
    assert len(db.rows) == 1                                           # nothing was created and nothing was refused


def test_the_chart_is_read_in_pages_and_a_code_held_past_the_first_page_is_not_chosen():
    rows = [acct(i, f"Ledger {i}", f"L{i}") for i in range(1, DB_MAX_ROWS + 5)]
    rows.append(acct(DB_MAX_ROWS + 5, "A bank ledger", "TB-CASH", client=OTHER))      # past the first page
    db = _Db(rows)
    resolved = tbi._resolve_or_create_accounts(db, FIRM, ME, [tb("Cash")])
    created = next(r for r in db.rows if r["id"] == resolved["Cash"])
    assert created["account_code"] == "TB-CASH-2"
    assert len(db.log) >= 2, "the chart was read in a single request"


def test_the_chart_is_read_with_the_privileged_client_where_there_is_one(monkeypatch):
    request = _Db([acct(1, "Visible to the caller", "TB-CASH")])
    privileged = _Db([acct(1, "Visible to the caller", "TB-CASH"), acct(2, "Hidden from a scoped caller", "TB-BANK", client=OTHER)])
    monkeypatch.setattr(core.db_provider, "service_db_or_none", lambda: privileged)
    tbi._resolve_or_create_accounts(request, FIRM, ME, [tb("Bank", code="TB-BANK")])
    assert privileged.reads >= 1
    created = [r for r in request.rows if r["id"].startswith("new-")]
    assert len(created) == 1 and created[0]["account_code"] == "TB-BANK-2", created        # the insert is the caller's own
