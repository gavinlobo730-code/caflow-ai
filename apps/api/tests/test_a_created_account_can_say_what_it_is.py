"""An account created in the app could not say what kind of account it is.

ACC-11. `create_account` wrote `account_type`, `parent_group` and `sub_group`,
and `AccountUpdateIn` could correct `schedule_iii_mapping` — but NOTHING could
set `account_subtype`, on either path. Only the CSV importer ever had.

THAT WAS COSMETIC ONCE AND IS NOT ANY MORE, which is why this is worth a guard
rather than a field. `domain/reporting/schedule_iii.classify` decides where an
account presents by reading three things — the type, the SUBTYPE, and the CA's
own `schedule_iii_mapping` — and since the year-end statements began deriving
their Schedule III line from the account rather than from a cache
(`domain/reporting/year_end_lines`), an account with no subtype falls to
`DEFAULT_ACCOUNT_TYPE_MAP`: every Asset presents as Other Current Assets, every
Liability as Other Current Liabilities.

So a CA creating "HDFC Current Account" through the product got a bank account
presented as Other Current Assets — on the client Balance Sheet, in the
year-end statements, and in every year-end schedule — and the only way to fix
it was to re-import the whole chart of accounts from a CSV.

THE RULE THIS GUARDS: whatever the classifier READS, the create and update
paths must be able to WRITE. Asserted that way rather than by naming today's
three columns, because a fourth input to `classify` would otherwise be
invisible here.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from models.accounting import AccountIn, AccountType, AccountUpdateIn

API_ROOT = Path(__file__).resolve().parents[1]


def _code(path: Path) -> str:
    src = path.read_text()
    src = re.sub(r"#[^\n]*", "", src)
    return re.sub(r'("""|\'\'\')[\s\S]*?\1', "", src)


# ── what the classifier reads ───────────────────────────────────────────────

def test_what_classify_reads_is_what_the_models_can_set():
    """THE RULE. `classify(account_type, account_subtype, schedule_iii_mapping)`
    is the signature; every one of its inputs must be settable at creation, or
    an account is born unable to say where it belongs."""
    from domain.reporting.schedule_iii import classify

    reads = set(inspect.signature(classify).parameters) - {"self"}
    settable = set(AccountIn.model_fields)
    # `account_type` is spelled the same; the other two are the columns.
    missing = [p for p in reads if p not in settable]
    assert not missing, (
        f"classify() reads {missing}, which AccountIn cannot set — an account "
        f"created through the product cannot say where it belongs, and falls "
        f"to the coarse per-type fallback on every statutory statement")


def test_the_subtype_is_settable_and_correctable():
    """Both paths. Correctable matters as much as settable: every account
    created before this existed carries no subtype."""
    assert "account_subtype" in AccountIn.model_fields
    assert "account_subtype" in AccountUpdateIn.model_fields
    assert AccountIn(name="HDFC Current", code="1100",
                     account_type=AccountType.ASSET,
                     account_subtype="Bank Account").account_subtype == "Bank Account"
    assert AccountUpdateIn(account_subtype="Bank Account").account_subtype == "Bank Account"


def test_the_schedule_iii_caption_is_settable_at_creation_too():
    """ACC-10 made it correctable. Leaving it off the create path meant a CA who
    knew where an account belonged had to save it wrong and then edit it."""
    assert "schedule_iii_mapping" in AccountIn.model_fields
    acc = AccountIn(name="Fixed Deposit", code="1210",
                    account_type=AccountType.ASSET,
                    schedule_iii_mapping="Long-term Investments")
    assert acc.schedule_iii_mapping == "Long-term Investments"


def test_a_caption_the_classifier_does_not_know_is_refused_on_create():
    """The same rule the update path has. An unrecognised caption is IGNORED by
    the classifier, so accepting one would be a screen that says "saved" and
    changes nothing — the exact complaint ACC-10 was."""
    with pytest.raises(Exception) as e:
        AccountIn(name="x", code="1", account_type=AccountType.ASSET,
                  schedule_iii_mapping="Cash And Bank Balances")
    assert "Schedule III caption" in str(e.value)


def test_the_subtype_is_free_text_and_that_is_deliberate():
    """It is the Indian chart's own vocabulary, worded differently by every
    practice and brought in verbatim by the Tally import, and the classifier
    KEYWORD-SCANS it rather than matching a list. Validating it against a
    closed set would refuse the words a real chart uses. The unambiguous
    override is `schedule_iii_mapping`, which IS validated."""
    for text in ("Bank Account", "Sundry Debtors", "Plant & Machinery",
                 "Cash-in-Hand", "something nobody anticipated"):
        assert AccountIn(name="x", code="1", account_type=AccountType.ASSET,
                         account_subtype=text).account_subtype == text


# ── and the endpoints write them ────────────────────────────────────────────

def test_create_writes_both_columns():
    """A model field the handler drops is the same lie as no field at all."""
    code = _code(API_ROOT / "routers" / "accounting.py")
    body = code[code.index("def create_account"):]
    body = body[:body.index("\ndef ", 1)]
    assert '"account_subtype"' in body, (
        "create_account no longer writes account_subtype, so a ledger created "
        "in the app is back to classifying by its type alone")
    assert '"schedule_iii_mapping"' in body


def test_update_writes_the_subtype():
    code = _code(API_ROOT / "routers" / "accounting.py")
    body = code[code.index("def update_account"):]
    body = body[:body.index("\ndef ", 1)]
    assert 'update["account_subtype"]' in body


def test_the_refusal_names_every_changeable_field_and_is_not_a_literal():
    """It WAS a hand-written sentence, and it went stale the first time a field
    was added after the test that checks it — which is the drift that test's own
    comment predicted. Derived from the model, it cannot."""
    code = _code(API_ROOT / "routers" / "accounting.py")
    assert "AccountUpdateIn.model_fields" in code, (
        "the 'only these can be changed' message is a literal list again; it "
        "goes stale the next time a field is added and nothing catches it "
        "until a test that asserts the property fails")


# ── the consequence, end to end ─────────────────────────────────────────────

@pytest.mark.parametrize("subtype,caption", [
    ("Bank Account",       "Cash & Cash Equivalents"),
    ("Trade Receivables",  "Trade Receivables"),
    ("Plant & Machinery",  "Tangible Fixed Assets"),
])
def test_a_subtype_actually_moves_the_account(subtype, caption):
    """The point of the field, not merely that it is stored: with it the
    account lands on its real caption, without it on the generic one."""
    from domain.reporting.schedule_iii import classify

    with_subtype, _ = classify("Asset", subtype, None)
    without, _ = classify("Asset", None, None)
    assert with_subtype == caption, with_subtype
    assert without != caption, (
        "a bare Asset already classifies to this caption, so this case proves "
        "nothing about the subtype")
