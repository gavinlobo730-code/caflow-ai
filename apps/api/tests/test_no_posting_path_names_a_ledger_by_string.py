"""Phase 1a: the money goes to the account it actually moved through.

THE RULE THIS GUARDS

    No posting path may decide the CASH ledger by naming it.

`_find_account(db, firm_id, client_id, "%Bank%", system_key="bank")` reads like
a lookup and is really a guess: it returns ONE firm-wide ledger, with no client
filter, and consults neither the bank account the CA chose nor whether the
payment was cash at all. Six call sites did it, and three of them were not named
by any finding — ACC-02/ACC-03/SALES-08 between them listed the two rupee paths
and receipt_service, and a grep for the pattern found the two foreign-currency
payment paths and the foreign-currency receipt as well.

WHY A STRUCTURAL GUARD AND NOT SIX TESTS

Six behavioural tests would pass again the moment somebody adds a seventh call
site, which is exactly how this defect spread from one path to six. The lesson
is the money parser's: a guard that names instances is a guard that expires.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

API = pathlib.Path(__file__).resolve().parent.parent

#: The one module allowed to name the generic ledger — it IS the resolver, and
#: its fallback is the old behaviour kept deliberately.
RESOLVER = "domain/accounting/payment_account.py"

#: Sites that still name it, each with the finding that owns them and the phase
#: that closes them. An entry here is a DEBT, not an exemption: the list may
#: only shrink. Adding to it needs the same argument as adding to the money
#: parser's allowlist, and for the same reason.
STILL_NAMING_IT: dict[str, str] = {
    "services/phase2_journal_service.py": (
        "journal_for_asset_acquisition and journal_for_asset_disposal (FA-07). "
        "An asset bought on credit needs a vendor, a bill link and an ITC split "
        "before the credit leg means anything — Phase 1b, not a rename."
    ),
    "services/opening_balance_service.py": (
        "Deliberate and correct. The lines above it already route each bank's "
        "opening balance to that bank's own coa_account_id; this names the "
        "generic ledger only for the RESIDUAL of banks that have no linked "
        "ledger at all, which is what the generic ledger is for."
    ),
}


def _names_the_generic_bank(path: pathlib.Path) -> list[int]:
    """Lines whose CODE (not comments, not docstrings) names the generic ledger.

    AST rather than grep: three modules explain the defect in prose, and a
    grep-based first version of this guard would have failed on the very
    comments that document the fix — the mistake the ₹-glyph guard made in
    Phase 0 and the money parser made twice before that.
    """
    tree = ast.parse(path.read_text())
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) and \
               isinstance(body[0].value, ast.Constant) and \
               isinstance(body[0].value.value, str):
                docstrings.add(id(body[0].value))
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
           and id(node) not in docstrings and node.value == "%Bank%":
            hits.append(node.lineno)
    return sorted(hits)


def _posting_modules() -> list[pathlib.Path]:
    out = []
    for sub in ("services", "routers", "domain"):
        out.extend(sorted((API / sub).rglob("*.py")))
    return [p for p in out if "__pycache__" not in p.parts]


def test_no_posting_path_names_the_generic_bank_ledger():
    offenders = {}
    for path in _posting_modules():
        rel = path.relative_to(API).as_posix()
        if rel == RESOLVER:
            continue
        lines = _names_the_generic_bank(path)
        if lines and rel not in STILL_NAMING_IT:
            offenders[rel] = lines
    assert not offenders, (
        "these decide the cash ledger by naming it instead of asking "
        "domain/accounting/payment_account.resolve_payment_account: "
        f"{offenders}"
    )


def test_the_debt_list_only_shrinks():
    """An entry that no longer names it must be DELETED, not left reassuring."""
    dead = []
    for rel, why in STILL_NAMING_IT.items():
        if not _names_the_generic_bank(API / rel):
            dead.append(rel)
        assert len(why) > 60, f"{rel}: say which finding owns it and why"
    assert not dead, f"no longer name the generic ledger — delete their entries: {dead}"


def test_the_resolver_is_the_only_module_that_may_name_it():
    assert _names_the_generic_bank(API / RESOLVER), (
        "the resolver's own fallback IS the generic ledger; if it stops naming "
        "it, this guard is pointing at the wrong module")


# ── the behaviour, not just the shape ───────────────────────────────────────

class _Q:
    def __init__(self, store, table): self.store, self.table, self.f = store, table, {}
    def select(self, *a, **k): return self
    def eq(self, k, v): self.f[k] = v; return self
    def limit(self, n): return self
    def execute(self):
        rows = [r for r in self.store.get(self.table, [])
                if all(r.get(k) == v for k, v in self.f.items())]
        return type("R", (), {"data": rows})()


class _DB:
    def __init__(self, store): self.store = store
    def table(self, name): return _Q(self.store, name)


def _find_account(db, firm_id, client_id, pattern, system_key=None):
    return {"%Bank%": "generic-bank", "%Cash in Hand%": "cash-in-hand"}[pattern]


def _resolve(**kw):
    from domain.accounting.payment_account import resolve_payment_account
    store = {"bank_accounts": [
        {"id": "ba-1", "firm_id": "f", "coa_account_id": "hdfc-ledger",
         "bank_name": "HDFC", "account_type": "Current"},
        {"id": "ba-unlinked", "firm_id": "f", "coa_account_id": None,
         "bank_name": "Cosmos", "account_type": "Current"},
    ]}
    return resolve_payment_account(_DB(store), firm_id="f", client_id="c",
                                   find_account=_find_account, **kw)


def test_a_named_bank_account_wins():
    r = _resolve(bank_account_id="ba-1", payment_mode="neft")
    assert r.account_id == "hdfc-ledger" and r.source == "bank_account"
    assert r.is_fallback is False and "HDFC" in r.reason


def test_a_cash_receipt_goes_to_cash_in_hand():
    """ACC-02: payment_mode was captured, stored, and never once consulted."""
    r = _resolve(payment_mode="cash")
    assert r.account_id == "cash-in-hand" and r.source == "cash"
    assert r.is_fallback is False


@pytest.mark.parametrize("mode", ["bank", "cheque", "upi", "neft", "rtgs", "online"])
def test_every_other_mode_is_a_bank_mode(mode):
    """A cheque and a UPI transfer move money through an ACCOUNT. Treating them
    as cash would be the same defect with the sign flipped."""
    assert _resolve(payment_mode=mode).source == "generic_bank"


def test_a_named_account_beats_a_cash_mode():
    """A stated fact outranks a derived one — and this ordering is load-bearing:
    a CA who picks an account and leaves payment_mode at its 'cash' default must
    get the account they picked."""
    assert _resolve(bank_account_id="ba-1", payment_mode="cash").account_id == "hdfc-ledger"


def test_an_unlinked_bank_account_falls_back_and_says_so():
    """_ensure_bank_ledger returns None rather than refusing a save when ledger
    creation fails, so an unlinked bank account is a state the product allows."""
    r = _resolve(bank_account_id="ba-unlinked")
    assert r.account_id == "generic-bank" and r.is_fallback is True


def test_nothing_recorded_is_a_FALLBACK_not_a_decision():
    """The whole defect in one assertion. The old code returned this same ledger
    and nothing distinguished it from a resolved one."""
    r = _resolve()
    assert r.account_id == "generic-bank"
    assert r.is_fallback is True
    assert "no bank account was recorded" in r.reason.lower()


def test_the_resolver_never_guesses_a_bank_from_the_clients_list():
    """A client with two current accounts banks at both. Picking one would move
    this very defect a level down, where it is harder to see."""
    import inspect
    from domain.accounting import payment_account
    src = inspect.getsource(payment_account.resolve_payment_account)
    assert ".eq(\"client_id\"" not in src, (
        "the resolver must look a bank account up BY ID, never list a client's "
        "accounts and choose")


# ── BANK-02 ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bank_type,caption", [
    ("Current",     "Cash & Cash Equivalents"),
    ("Savings",     "Cash & Cash Equivalents"),
    ("Cash Credit", "Short Term Borrowings"),
    ("Overdraft",   "Short Term Borrowings"),
])
def test_an_overdraft_ledger_lands_under_short_term_borrowings(bank_type, caption):
    """BANK-02. The subtype was CHECKED against bs_bucket rather than chosen:
    'Bank OD' and 'Cash Credit' both fall to Other Current Liabilities, because
    the branch matches the literal 'overdraft'. Schedule III Division I puts
    'loans repayable on demand from banks' under Short-term borrowings, and a
    drawn overdraft shown as a negative asset both understates borrowings and
    misstates liquidity."""
    from routers.banking import ledger_shape_for_bank
    from domain.reporting.schedule_iii import bs_bucket
    typ, sub = ledger_shape_for_bank(bank_type)
    assert bs_bucket(typ, sub) == caption


def test_the_overdraft_subtype_is_pinned_to_the_bucketing():
    """If either the subtype or bs_bucket's keyword moves, this fails rather
    than silently re-bucketing every overdraft in the firm."""
    from routers.banking import ledger_shape_for_bank
    assert "overdraft" in ledger_shape_for_bank("Overdraft")[1].lower()
