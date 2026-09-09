"""ACC-09 — a ledger can be created, corrected and put in its group.

WHAT WAS WRONG
    chart_of_accounts has carried parent_group and sub_group since migration
    057 and NOTHING wrote them: create_account's payload named neither, and
    update_account accepted only name, code and is_active. The only writer in
    the whole product was the CSV import.

    So apps/web/app/accounting/account-groups/page.tsx, which reads them and
    groups by `acc.parent_group ?? "Ungrouped"`, rendered one "Ungrouped →
    General" block for any normally-seeded firm. The screen was not broken; it
    was being told nothing. Neither was parent_id editable, so a ledger filed
    under the wrong head stayed there.

    An Indian trial balance is READ by group — Current Assets → Sundry Debtors,
    Indirect Expenses → Rates and Taxes. A flat list of 60 accounts is not the
    document a CA is looking at.

Every test here fails against the previous code: the fields did not reach the
write, and the two update fields did not exist on the model.
"""
import pytest
from fastapi import HTTPException

import routers.accounting as ac
from models.accounting import AccountIn, AccountUpdateIn, AccountType

USER = {"id": "u1", "firm_id": "f1", "auth_user_id": "a1", "email": "p@f.in", "role": "Partner"}


class DB:
    def __init__(self, rows=None):
        self.rows = rows if rows is not None else [{"id": "a1", "client_id": None}]
        self.payload = None
        self.filters = {}

    def table(self, _name):
        return self

    def select(self, *_a, **_k):
        return self

    def insert(self, payload):
        self.payload = payload
        return self

    def update(self, payload):
        self.payload = payload
        return self

    def eq(self, col, val):
        self.filters[col] = val
        return self

    def limit(self, _n):
        return self

    def execute(self):
        return type("R", (), {"data": [dict(self.payload or {}, id="a1")] if self.payload
                              else list(self.rows)})()


@pytest.fixture()
def db(monkeypatch):
    d = DB()
    monkeypatch.setattr(ac, "_prod_db", lambda: d)
    monkeypatch.setattr(ac, "assert_client_access", lambda *_a, **_k: None)
    monkeypatch.setattr(ac, "can_access_client", lambda *_a, **_k: True)
    return d


def test_a_new_ledger_carries_the_group_it_was_given(db):
    out = ac.create_account(AccountIn(
        name="Sundry Debtors — Domestic", code="1200",
        account_type=AccountType.ASSET,
        parent_group="Current Assets", sub_group="Sundry Debtors"), None, USER)
    assert out["success"] is True
    assert db.payload["parent_group"] == "Current Assets"
    assert db.payload["sub_group"] == "Sundry Debtors"


def test_a_ledger_with_no_group_stores_null_not_an_empty_string(db):
    """`""` and NULL are different to the screen: it groups on
    `parent_group ?? "Ungrouped"`, and an empty string is not null, so a blank
    would produce a nameless heading rather than falling into Ungrouped."""
    ac.create_account(AccountIn(name="Suspense", code="9999",
                                account_type=AccountType.ASSET,
                                parent_group="  ", sub_group=""), None, USER)
    assert db.payload["parent_group"] is None
    assert db.payload["sub_group"] is None


def test_a_ledger_filed_under_the_wrong_head_can_be_moved(db):
    out = ac.update_account("a1", AccountUpdateIn(
        parent_group="Indirect Expenses", sub_group="Rates and Taxes"), USER)
    assert out["success"] is True
    assert db.payload == {"parent_group": "Indirect Expenses",
                          "sub_group": "Rates and Taxes"}


def test_a_ledger_can_be_re_parented(db):
    ac.update_account("a1", AccountUpdateIn(parent_id="a-parent"), USER)
    assert db.payload == {"parent_id": "a-parent"}


def test_an_account_cannot_be_made_its_own_parent(db):
    with pytest.raises(HTTPException) as exc:
        ac.update_account("a1", AccountUpdateIn(parent_id="a1"), USER)
    assert exc.value.status_code == 422
    assert "own parent" in exc.value.detail


def test_the_type_still_cannot_be_changed(db):
    """It decides which side of the trial balance the account falls on, so
    changing it after a posting silently restates every report. Absent from
    the update model, and the scan in
    test_a_field_you_can_create_is_a_field_you_can_correct.py holds the reason."""
    assert "account_type" not in AccountUpdateIn.model_fields
