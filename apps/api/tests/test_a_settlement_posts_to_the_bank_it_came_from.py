"""The statement line knows which bank it is; the settlement must use it (ACC-03).

WHAT WAS WRONG

`domain/accounting/payment_account.resolve_payment_account` decides the cash
leg's ledger: a stated `bank_account_id` wins, a cash mode goes to Cash in Hand,
and otherwise it falls through to the firm's GENERIC `%Bank%` ledger — a
FALLBACK, flagged as one, which posts and balances fine and can land in the
wrong sub-ledger. That module's own docstring says it exists because "a
statement line and a receipt for the SAME payment into the SAME bank landed in
different ledgers".

Three doors were still sending no account, and the third is the one that had no
excuse:

  * `app/clients/[id]/purchases/page.tsx` — the Purchases payment form;
  * `components/purchases/PurchaseBillViewDrawer.tsx` — Record Payment on a bill;
  * `bank_posting_service.match_and_settle_multi` — the BANK MATCH QUEUE, which
    settles a statement line against documents. That line came off a statement
    that names its `bank_accounts` row, and `_resolve_bank` has walked exactly
    that path since the module was written. The settlement built its
    `create_receipt_core` / `create_payment_core` payload without it, so PASSING
    a line and SETTLING the same line posted the cash leg to two different
    ledgers.

WHAT IS PINNED HERE, AND WHAT IS NOT

The lookup is one method now — `BankPostingService.bank_account_id_for` — so
the posting path and the settlement path cannot disagree about which account a
line came from. `bank_transactions` carries no `bank_account_id` of its own;
the account is one hop away through `statement_id`, which is why this was easy
to leave out.

It returns None rather than raising. A transaction with no statement must still
settle: the resolver then falls back exactly as before AND SAYS it fell back,
which is the property that makes the fallback safe. A test below asserts that.

NOT PINNED, AND OPEN: `PaymentAccount.is_fallback` and `.reason` are computed
and reach no caller. The resolver is called inside eight journal-line builders,
so surfacing them to the API response is a refactor through the posting kernel's
callers rather than a line, and where a CA should be told is an owner decision.
The finding stays `partial` for that half.
"""
import pytest

from services.bank_posting_service import BankPostingService


class _Q:
    """The two-hop read `bank_account_id_for` performs, and nothing else."""

    def __init__(self, store, table):
        self._store, self._table, self._eq = store, table, {}

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self._eq[col] = val
        return self

    def single(self):
        return self

    def execute(self):
        rows = [r for r in self._store.get(self._table, [])
                if all(r.get(k) == v for k, v in self._eq.items())]
        if not rows:
            raise RuntimeError("no rows")          # PostgREST .single() behaviour
        return type("R", (), {"data": rows[0]})()


class _DB:
    def __init__(self, store):
        self._store = store

    def table(self, name):
        return _Q(self._store, name)


FIRM, CLIENT = "F", "C"
TXN = {"id": "T1", "client_id": CLIENT, "statement_id": "S1"}
STORE = {"bank_statements": [
    {"id": "S1", "firm_id": FIRM, "client_id": CLIENT, "bank_account_id": "BA-HDFC"},
]}


def test_the_account_comes_off_the_statement():
    assert BankPostingService().bank_account_id_for(_DB(STORE), FIRM, TXN) == "BA-HDFC"


def test_a_transaction_with_no_statement_answers_none_rather_than_raising():
    """Not every row has one, and a settlement must not start refusing."""
    got = BankPostingService().bank_account_id_for(
        _DB(STORE), FIRM, {"id": "T2", "client_id": CLIENT, "statement_id": None})
    assert got is None


def test_a_statement_belonging_to_another_firm_is_not_read():
    """The scoping is the point: this read decides which sub-ledger real money
    lands in, and an unscoped read-by-id in a money path is task #228's finding."""
    got = BankPostingService().bank_account_id_for(_DB(STORE), "OTHER-FIRM", TXN)
    assert got is None


def test_a_statement_with_no_account_answers_none():
    store = {"bank_statements": [
        {"id": "S1", "firm_id": FIRM, "client_id": CLIENT, "bank_account_id": None}]}
    assert BankPostingService().bank_account_id_for(_DB(store), FIRM, TXN) is None


# ── the rule, read off the source ───────────────────────────────────────────

def _settle_source() -> str:
    import inspect
    import services.bank_posting_service as m
    return inspect.getsource(m.BankPostingService.match_and_settle_multi)


def test_both_settlement_payloads_carry_the_account():
    """A receipt and a payment, because the queue settles both and a fix on one
    branch leaves the other posting to the generic ledger."""
    src = _settle_source()
    assert src.count('"bank_account_id": settled_from') == 2, (
        "match_and_settle_multi builds a receipt payload and a payment payload; "
        "both must carry the statement's own bank account, or the same statement "
        "line posts to a different ledger depending on which document it settles.")


def test_the_settlement_resolves_it_through_the_one_lookup():
    """Not a second walk of statement → bank_accounts. `_resolve_bank` and the
    settlement must agree about which account a line came from."""
    src = _settle_source()
    assert "bank_account_id_for(" in src
    assert "bank_statements" not in src, (
        "the settlement is walking to the statement itself instead of asking "
        "bank_account_id_for — two lookups of one fact is how they drift.")


def test_resolve_bank_uses_the_same_lookup():
    import inspect
    import services.bank_posting_service as m
    src = inspect.getsource(m.BankPostingService._resolve_bank)
    assert "bank_account_id_for(" in src, (
        "the posting path stopped using the shared lookup, so it and the "
        "settlement can now disagree about which account a line came from.")


@pytest.mark.parametrize("screen", [
    "app/clients/[id]/purchases/page.tsx",
    "components/purchases/PurchaseBillViewDrawer.tsx",
    "app/clients/[id]/sales/page.tsx",
])
def test_every_money_door_offers_the_account(screen):
    """The three screens that record money moving. Read from the PYTHON side for
    the Schedule III caption reason: a guard in apps/web asserting the browser
    against a copy of itself passes whenever both drift together."""
    import pathlib
    web = pathlib.Path(__file__).resolve().parents[2] / "web"
    path = web / screen
    if not path.exists():
        pytest.skip("apps/web not present")
    body = path.read_text()
    assert "PaymentAccountPicker" in body, (
        f"{screen} records a payment or receipt and offers no account, so it "
        "posts to the firm's generic Bank ledger whichever of the client's "
        "accounts the money actually moved through.")
    assert "bank_account_id" in body, f"{screen} renders the picker and sends nothing"
