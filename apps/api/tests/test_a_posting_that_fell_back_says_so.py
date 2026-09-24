"""A payment that could not be attributed to a bank account says so.

THE DEFECT

    `domain/accounting/payment_account.resolve_payment_account` has decided the
    cash leg's ledger since ACC-03, in three steps: a stated `bank_account_id`
    wins, a cash `payment_mode` goes to Cash in Hand, and otherwise it falls
    through to the firm's GENERIC `%Bank%` ledger. The result has carried
    `is_fallback` and a `reason` written for a CA since the day it was built,
    and CLAUDE.md records the rest: "`is_fallback` and `reason` still reach no
    caller."

    So a payment that landed in the firm's general Bank ledger rather than the
    client's own account looked, on every screen and in every response, exactly
    like one that had not. The posting is balanced and the double entry is
    right; it is simply not attributable, and nothing said which.

    Two of the three fallbacks were worse than unreported. A recorded bank
    account with no ledger of its own FELL THROUGH to branch 3 and came back
    saying *"No bank account was recorded on this document"* — false, and it
    sends the CA to set a field that is already set. Found on 24-09-2026 while
    surfacing these sentences; it was invisible for as long as nothing
    rendered them.

THE RULE (D14, 24-09-2026)

    The CA is told on the ENTRY ROW — visible while scanning the ledger — and
    in the POSTING CONFIRMATION, where it is caught at the moment it happens
    and the account is one field away.

    `row_notice` is the row half and is the SAME rule the resolver's branch 3
    tests, not a second reading of the same columns. `apps/web/lib/accounting/
    postingAccountNotice.ts` mirrors it for the client Sales tab, which reads
    `receipts` straight over PostgREST and never sees a stamped response;
    `tests/fixtures/posting_account_notice.json` is the vector table both read,
    and it is asserted here rather than in `apps/web` so the guard cannot
    compare the browser against a copy of itself.
"""
from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path

import pytest

from domain.accounting import payment_account as PA

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
WEB = REPO / "apps" / "web"
MIRROR = WEB / "lib" / "accounting" / "postingAccountNotice.ts"
VECTORS = json.loads((HERE / "fixtures" / "posting_account_notice.json").read_text())


# ── 1. the rule ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("case", VECTORS["cases"], ids=lambda c: c["why"][:48])
def test_the_python_authority_answers_each_vector(case):
    got = PA.row_notice(case["bank_account_id"], case["payment_mode"])
    if case["notice"]:
        assert got == VECTORS["notice"], case["why"]
    else:
        assert got is None, case["why"]


def test_the_fixture_is_not_all_one_answer():
    """A vector table that only ever expects one answer passes against a
    function that returns a constant."""
    answers = {c["notice"] for c in VECTORS["cases"]}
    assert answers == {True, False}, "the fixture must exercise both answers"
    assert sum(1 for c in VECTORS["cases"] if not c["notice"]) >= 5


def test_the_resolver_and_the_row_agree_on_what_a_fallback_is():
    """One rule, two callers. `resolve_payment_account`'s branch 3 and
    `row_notice` must not be two readings of the same two columns — that is
    how a disclosure comes to disagree with the posting it describes."""
    src = ast.unparse(ast.parse(Path(PA.__file__).read_text()))
    assert "document_names_no_account" in src
    # row_notice must DELEGATE rather than restate the predicate.
    fn = next(n for n in ast.parse(Path(PA.__file__).read_text()).body
              if isinstance(n, ast.FunctionDef) and n.name == "row_notice")
    calls = {n.func.id for n in ast.walk(fn)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "document_names_no_account" in calls, (
        "row_notice restates branch 3's predicate instead of asking it"
    )


# ── 2. the sentences are named, and the unlinked case has its own ───────────


def test_a_recorded_but_unlinked_account_is_not_reported_as_unrecorded():
    """The lie this pass found. Three distinct sentences, and a test on the
    ANSWERS rather than on the data, so collapsing two cannot make it vacuous.
    """
    three = {PA.NOTICE_NO_ACCOUNT_RECORDED,
             PA.NOTICE_ACCOUNT_NOT_LINKED,
             PA.NOTICE_NO_CASH_LEDGER}
    assert len(three) == 3, "two fallback sentences have become the same words"
    assert "no ledger of its own" in PA.NOTICE_ACCOUNT_NOT_LINKED
    assert "No bank account was recorded" not in PA.NOTICE_ACCOUNT_NOT_LINKED, (
        "an account IS recorded in this branch; saying otherwise sends the CA "
        "to set a field that is already set"
    )


def test_the_resolver_returns_the_unlinked_sentence_rather_than_falling_through():
    """A bank account row that exists with `coa_account_id` NULL. The product
    deliberately allows that state — `_ensure_bank_ledger` returns None rather
    than refusing a save — so it is reachable."""
    class _DB:
        def table(self, _):
            return self
        def select(self, *a, **k):
            return self
        def eq(self, *a, **k):
            return self
        def limit(self, *a, **k):
            return self
        def execute(self):
            class R:
                data = [{"id": "b1", "coa_account_id": None, "bank_name": "HDFC"}]
            return R()

    got = PA.resolve_payment_account(
        _DB(), firm_id="f", client_id="c", bank_account_id="b1",
        payment_mode="neft", find_account=lambda *a, **k: "generic-bank")
    assert got.is_fallback is True
    assert got.reason == PA.NOTICE_ACCOUNT_NOT_LINKED
    assert got.account_id == "generic-bank"


# ── 3. the stamp, and its always-present key ────────────────────────────────


def test_the_key_is_always_present_and_null_when_attributable():
    """`journal_source`'s discipline. An absent key and a null key read the
    same to a screen and are different bugs: null is "this posting named its
    account", absent is "this build did not look"."""
    attributable = PA.stamp({"bank_account_id": "b1", "payment_mode": "neft"})
    assert PA.NOTICE_KEY in attributable
    assert attributable[PA.NOTICE_KEY] is None

    fell_back = PA.stamp({"bank_account_id": None, "payment_mode": "neft"})
    assert fell_back[PA.NOTICE_KEY] == VECTORS["notice"]


def test_stamp_all_survives_a_row_that_is_not_a_dict():
    out = PA.stamp_all([{"payment_mode": "neft"}, "junk", None])
    assert out[0][PA.NOTICE_KEY] == VECTORS["notice"]
    assert out[1] == "junk" and out[2] is None


# ── 4. both doors serve it ──────────────────────────────────────────────────


@pytest.mark.parametrize("router", ["receipts", "purchase_payments"])
def test_the_router_stamps_every_document_it_serves(router):
    """Counted rather than matched: a response added later without the stamp
    raises the api_response count without raising the stamp count."""
    src = (REPO / "apps" / "api" / "routers" / f"{router}.py").read_text()
    tree = ast.parse(src)
    stamps = sum(1 for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                 and n.func.id in ("_stamp_posting_account", "_stamp_posting_accounts"))
    assert stamps >= 4, (
        f"routers/{router}.py stamps only {stamps} responses — a document "
        "response that does not carry `posting_account_notice` is a screen "
        "that cannot render the disclosure"
    )


# ── 5. the browser mirror ───────────────────────────────────────────────────


def _mirror_answers(cases: list) -> list:
    payload = json.dumps([[c["bank_account_id"], c["payment_mode"]] for c in cases])
    script = (
        f'import {{ postingAccountNotice }} from "{MIRROR}";\n'
        f"const cases = {payload};\n"
        "process.stdout.write(JSON.stringify("
        "cases.map(([a, m]) => postingAccountNotice(a, m))));\n"
    )
    out = subprocess.run(
        ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
        capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        pytest.skip(f"node could not read the mirror: {out.stderr[-400:]}")
    return json.loads(out.stdout)


def test_the_browser_mirror_answers_every_vector_the_same_way():
    cases = VECTORS["cases"]
    theirs = _mirror_answers(cases)
    assert len(theirs) == len(cases)
    for case, got in zip(cases, theirs):
        mine = PA.row_notice(case["bank_account_id"], case["payment_mode"])
        assert got == mine, (
            f"apps/web/lib/accounting/postingAccountNotice.ts disagrees with "
            f"domain/accounting/payment_account.row_notice on "
            f"{case['bank_account_id']!r}/{case['payment_mode']!r} "
            f"({case['why']}): browser {got!r}, authority {mine!r}"
        )


def test_the_mirror_holds_the_same_cash_modes():
    """The list, not just the sentence. A mode added on one side only would
    make a cash payment report itself as an unattributed bank posting."""
    src = MIRROR.read_text()
    for mode in PA.CASH_PAYMENT_MODES:
        normalised = "_".join(mode.strip().lower().split()).replace("-", "_")
        assert f'"{normalised}"' in src, (
            f"the browser mirror does not know the cash mode {normalised!r}"
        )
