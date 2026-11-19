"""The P&L Statement nets the four CGST section 34 notes, signed as the ledger posts them (POST-A-502, migration 766).

WHAT WAS WRONG. The Reports page's P&L Statement added the taxable value of issued sales invoices and received purchase
bills and nothing else. The browser's own arithmetic had always done the same, so migration 745 moved it faithfully and
the review of that batch found that a month with a sales credit note showed more revenue than the books hold (and a
month with a purchase return more expense): the notes that change a supply's value were in the answer nowhere. A wrong
figure on a screen is the failure that matters most.

THE RULE, asserted three ways here and in the real-Postgres parity test:
  1. the sign of each note kind is read OFF THE LEDGER'S OWN POSTING FUNCTIONS, not off a list in this file: the leg
     that moves the revenue or expense account is found in the source of each journal function and its side decides;
  2. the service's Python path reads each note table by its own date, issued (or applied) and not deleted, for the
     clients asked for, and joins a note to the line of the party it names;
  3. an answer from before migration 766 (no note keys) is passed through untouched, so a screen can tell "not read" from nil.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from domain.reporting import party_totals as rule
from services import report_transactions_service as svc
from tests.test_report_transactions_service import FIRM, FakeDB, _bill, _sale

API_ROOT = Path(__file__).resolve().parents[1]

#: Which journal function posts which kind of note, and which account family its taxable leg moves.
POSTING = {
    "sales_credit_notes": ("journal_for_credit_note", "sales_id"),
    "sales_debit_notes": ("journal_for_sales_debit_note", "sales_id"),
    "purchase_debit_notes": ("journal_for_debit_note", "purchases_id"),
    "purchase_credit_notes": ("journal_for_purchase_credit_note", "purchases_id"),
}


def _taxable_leg_side(function_name: str, account_var: str) -> str:
    """'debit' or 'credit': the side the journal function puts on the revenue or expense account's line."""
    tree = ast.parse((API_ROOT / "services" / "phase2_journal_service.py").read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == function_name)
    sides: set[str] = set()
    for node in ast.walk(fn):
        if not isinstance(node, ast.Dict):
            continue
        d = {k.value: v for k, v in zip(node.keys, node.values, strict=True) if isinstance(k, ast.Constant)}
        acct = d.get("account_id")
        if not (isinstance(acct, ast.Name) and acct.id == account_var):
            continue
        for side in ("debit_paise", "credit_paise"):
            v = d.get(side)
            if v is not None and not (isinstance(v, ast.Constant) and v.value == 0):
                sides.add(side.split("_")[0])
    assert len(sides) == 1, f"{function_name} puts {account_var} on {sides or 'no side'}: the rule below cannot read it"
    return sides.pop()


@pytest.mark.parametrize("kind", sorted(POSTING))
def test_the_sign_of_each_note_is_the_side_the_ledger_posts_it_on(kind):
    function_name, account_var = POSTING[kind]
    side = _taxable_leg_side(function_name, account_var)
    # Revenue is a credit account (a credit adds to it, a debit takes from it); an expense is a debit account.
    revenue = account_var == "sales_id"
    adds = (side == "credit") if revenue else (side == "debit")
    assert rule.NOTE_SIGNS[kind] == (1 if adds else -1), (
        f"{function_name} posts the taxable value as a {side} on the {'revenue' if revenue else 'expense'} account, which "
        f"{'adds to' if adds else 'takes from'} it; the P&L Statement signs {kind} {rule.NOTE_SIGNS[kind]:+d}")


def test_every_kind_of_note_is_signed_and_nothing_else_is():
    assert set(rule.NOTE_SIGNS) == set(POSTING) and all(v in (1, -1) for v in rule.NOTE_SIGNS.values())


# ── the rule ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def _n(party_key, party, paise):
    return {party_key: party, "taxable_amount_paise": paise}


def test_a_customers_line_is_invoices_less_credit_notes_plus_debit_notes():
    out = rule.party_totals(
        [_n("customer_id", "c1", 100_000)], [],
        customer_names={"c1": "Acme"}, vendor_names={},
        sales_credit_notes=[_n("customer_id", "c1", 30_000)], sales_debit_notes=[_n("customer_id", "c1", 5_000)])
    assert out["revenue"] == [{"party_id": "c1", "party_name": "Acme", "total_paise": 75_000, "documents": 3}]
    assert out["revenue_total_paise"] == 75_000 and out["revenue_notes_paise"] == -25_000
    assert out["sales_documents"] == 1 and out["note_documents"] == 2


def test_a_suppliers_line_is_bills_less_debit_notes_plus_credit_notes():
    out = rule.party_totals(
        [], [_n("vendor_id", "v1", 50_000)],
        customer_names={}, vendor_names={"v1": "Bolt"},
        purchase_debit_notes=[_n("vendor_id", "v1", 8_000)], purchase_credit_notes=[_n("vendor_id", "v1", 1_000)])
    assert out["expenses"][0]["total_paise"] == 43_000
    assert out["expense_total_paise"] == 43_000 and out["expense_notes_paise"] == -7_000
    assert out["purchase_documents"] == 1 and out["note_documents"] == 2


def test_a_credit_note_in_a_window_its_invoice_is_not_in_is_a_negative_line_and_the_total_follows():
    out = rule.party_totals([], [], customer_names={"c1": "Acme"}, vendor_names={},
                            sales_credit_notes=[_n("customer_id", "c1", 12_000)])
    assert out["revenue"][0]["total_paise"] == -12_000
    assert out["revenue_total_paise"] == -12_000 and out["net_paise"] == -12_000


def test_net_profit_moves_by_the_notes_on_both_sides():
    """A sales credit note lowers profit; a purchase debit note (a return) raises it; the other two do the opposite."""
    base = rule.party_totals([_n("customer_id", "c", 1_000_000)], [_n("vendor_id", "v", 400_000)],
                             customer_names={}, vendor_names={})
    with_notes = rule.party_totals(
        [_n("customer_id", "c", 1_000_000)], [_n("vendor_id", "v", 400_000)], customer_names={}, vendor_names={},
        sales_credit_notes=[_n("customer_id", "c", 100_000)], sales_debit_notes=[_n("customer_id", "c", 20_000)],
        purchase_debit_notes=[_n("vendor_id", "v", 50_000)], purchase_credit_notes=[_n("vendor_id", "v", 10_000)])
    assert base["net_paise"] == 600_000
    assert with_notes["net_paise"] == 600_000 - 100_000 + 20_000 + 50_000 - 10_000


def test_a_caller_that_knows_no_notes_gets_the_answer_it_always_got_and_nil_for_them():
    out = rule.party_totals([_n("customer_id", "c", 7)], [], customer_names={}, vendor_names={})
    assert out["revenue_total_paise"] == 7
    assert (out["revenue_notes_paise"], out["expense_notes_paise"], out["note_documents"]) == (0, 0, 0)


# ── the service's Python path ─────────────────────────────────────────────────────────────────────────────────────────

def _cn(**over):
    row = {"id": "cn1", "firm_id": FIRM, "client_id": "c1", "customer_id": "cus1", "credit_note_date": "2026-04-15",
           "taxable_amount_paise": 30_000, "status": "issued", "deleted_at": None}
    row.update(over)
    return row


def _sdn(**over):
    row = {"id": "sdn1", "firm_id": FIRM, "client_id": "c1", "customer_id": "cus1", "debit_note_date": "2026-04-16",
           "taxable_amount_paise": 5_000, "status": "issued", "deleted_at": None}
    row.update(over)
    return row


def _dn(**over):
    row = {"id": "dn1", "firm_id": FIRM, "client_id": "c1", "vendor_id": "ven1", "debit_note_date": "2026-04-17",
           "taxable_amount_paise": 8_000, "status": "issued", "deleted_at": None}
    row.update(over)
    return row


def _pcn(**over):
    row = {"id": "pcn1", "firm_id": FIRM, "client_id": "c1", "vendor_id": "ven1", "credit_note_date": "2026-04-18",
           "taxable_amount_paise": 1_000, "status": "issued", "deleted_at": None}
    row.update(over)
    return row


def _db(**tables):
    return FakeDB(
        client_sales_invoices=tables.pop("sales", [_sale()]), purchase_bills=tables.pop("bills", [_bill()]),
        customers=[{"id": "cus1", "firm_id": FIRM, "name": "Acme Traders"},
                   {"id": "cus-only-note", "firm_id": FIRM, "name": "Note Only Ltd"}],
        vendors=[{"id": "ven1", "firm_id": FIRM, "name": "Bolt Supplies"}], **tables)


def test_the_service_nets_all_four_notes_from_their_own_tables():
    db = _db(credit_notes=[_cn()], sales_debit_notes=[_sdn()], debit_notes=[_dn()], purchase_credit_notes=[_pcn()])
    out = svc.party_totals(db, FIRM)
    assert out["revenue_total_paise"] == 100_000 - 30_000 + 5_000
    assert out["expense_total_paise"] == 50_000 - 8_000 + 1_000
    assert out["net_paise"] == (100_000 - 30_000 + 5_000) - (50_000 - 8_000 + 1_000)
    assert (out["revenue_notes_paise"], out["expense_notes_paise"], out["note_documents"]) == (-25_000, -7_000, 4)
    assert out["revenue"] == [{"party_id": "cus1", "party_name": "Acme Traders", "total_paise": 75_000, "documents": 3}]


def test_a_draft_a_deleted_and_another_firms_note_are_not_counted_and_an_applied_one_is():
    db = _db(credit_notes=[
        _cn(id="a", status="draft", taxable_amount_paise=9_999_999),
        _cn(id="b", deleted_at="2026-05-01T00:00:00Z", taxable_amount_paise=8_888_888),
        _cn(id="c", firm_id="firm-other", taxable_amount_paise=7_777_777),
        _cn(id="d", status="applied", taxable_amount_paise=2_000),
    ])
    out = svc.party_totals(db, FIRM)
    assert out["revenue_notes_paise"] == -2_000 and out["note_documents"] == 1


def test_a_note_is_dated_by_its_own_date_and_scoped_by_its_own_client():
    db = _db(credit_notes=[_cn(id="in-window", credit_note_date="2026-04-30", taxable_amount_paise=1_000),
                           _cn(id="before", credit_note_date="2026-03-31", taxable_amount_paise=2_000),
                           _cn(id="after", credit_note_date="2026-05-01", taxable_amount_paise=4_000),
                           _cn(id="other-client", client_id="c2", credit_note_date="2026-04-10", taxable_amount_paise=8_000)])
    out = svc.party_totals(db, FIRM, client_ids=["c1"], date_from="2026-04-01", date_to="2026-04-30")
    assert out["revenue_notes_paise"] == -1_000 and out["note_documents"] == 1


def test_a_party_with_only_a_note_still_has_its_name():
    db = _db(sales=[], bills=[], credit_notes=[_cn(customer_id="cus-only-note", taxable_amount_paise=3_000)])
    out = svc.party_totals(db, FIRM)
    assert out["revenue"] == [{"party_id": "cus-only-note", "party_name": "Note Only Ltd", "total_paise": -3_000,
                               "documents": 1}]


def test_an_answer_from_before_migration_766_is_passed_through_with_no_note_keys_invented():
    class OldFunction(FakeDB):
        def rpc(self, name, params):
            class _R:
                def execute(self_inner):
                    class _D:
                        data = {"revenue": [], "expenses": [], "revenue_total_paise": 1, "expense_total_paise": 0,
                                "net_paise": 1, "sales_documents": 0, "purchase_documents": 0}
                    return _D()
            return _R()

    out = svc.party_totals(OldFunction(), FIRM)
    assert "revenue_notes_paise" not in out and "note_documents" not in out
