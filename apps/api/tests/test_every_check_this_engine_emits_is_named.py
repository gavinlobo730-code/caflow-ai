"""
Every check name "Verify Books" can produce has a human label, and no spare.

WHY THIS EXISTS. `CHECK_LABEL` lived in `apps/web/app/clients/[id]/accounting/
page.tsx` and held SIX entries against the sixteen names the engine emits, so
a CA reading a genuine finding on a bank reconciliation, an orphan money
journal or the fixed-asset register got the raw snake_case identifier —
`fixed_asset_register.wdv_asset_has_no_stopping_point` — as its own chip. The
tab's blurb was a second copy of the same vocabulary and named five of nine
checks. Both drifted silently because nothing could tell they had.

THE RULE, NOT A SPELLING OF IT. A guard listing the sixteen names would be a
third copy and would drift the same way. This one DERIVES the emitted set:

  * the literal first argument of every `_finding(...)` call in the service,
    read from the AST;
  * an f-string first argument is followed to the vocabulary it interpolates —
    `fixed_asset_register.{kind}` to `domain/fixed_assets/integrity`'s own
    kinds, and `{a.kind}` to `ledger_anomalies.ALL_KINDS` — because those are
    the two places a name can be added without touching this service at all,
    which is exactly how a new kind would slip through.

So adding a finding kind anywhere fails here until it is named, and deleting
one fails until its entry goes. Asserted as an EQUALITY rather than a subset,
the `UNREACHED_COMPUTED_ANSWERS` discipline: a catalogue entry left behind by
a deleted check is a label for something that can never appear.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from domain.accounting import ledger_anomalies
from domain.fixed_assets import integrity as fa_integrity
from services import reconciliation_service as rs

_SERVICE = pathlib.Path(rs.__file__)

#: The one name that is NOT in the catalogue and must not be: the runner wraps
#: a check that itself raised as `<function>.execution_error`, and the browser
#: already renders that shape by rule ("Check failed to run (…)") rather than
#: by lookup. Naming sixteen of those would be a second entry per check saying
#: the same thing.
EXECUTION_ERROR_SUFFIX = ".execution_error"


def _finding_first_args() -> list[ast.expr]:
    tree = ast.parse(_SERVICE.read_text())
    out: list[ast.expr] = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "_finding"
                and node.args):
            out.append(node.args[0])
    return out


def emitted_check_names() -> set[str]:
    """Every `check_name` the engine can write to `reconciliation_findings`."""
    names: set[str] = set()
    for arg in _finding_first_args():
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            names.add(arg.value)
            continue
        if not isinstance(arg, ast.JoinedStr):
            raise AssertionError(
                f"_finding()'s first argument is a {type(arg).__name__}, which this "
                "guard cannot follow to the names it can produce. Either make it a "
                "literal or teach this function the new vocabulary — do not relax it."
            )
        src = ast.unparse(arg)
        if "execution_error" in src:
            continue
        if "fixed_asset_register" in src:
            names |= {f"fixed_asset_register.{k}" for k in fa_integrity.ALL_KINDS}
            continue
        if src in ('f"{a.kind}"', "f'{a.kind}'"):
            names |= set(ledger_anomalies.ALL_KINDS)
            continue
        raise AssertionError(
            f"_finding() builds a check name from {src!r} and this guard does not "
            "know which vocabulary that draws on. Add the case."
        )
    return names


def test_the_walk_finds_the_finding_calls_at_all():
    """Vacuity control. If `_finding` is renamed or the AST shape changes, every
    assertion below passes over an empty set and says nothing."""
    args = _finding_first_args()
    assert len(args) >= 8, f"only {len(args)} _finding() calls found — the walk is blind"
    assert any(isinstance(a, ast.JoinedStr) for a in args), (
        "no f-string first argument found, so the vocabulary-following branches "
        "above are never exercised and a new kind would slip through"
    )


def test_every_emitted_check_name_is_in_the_catalogue():
    missing = sorted(emitted_check_names() - set(rs.CHECK_CATALOGUE))
    assert not missing, (
        "These checks can produce a finding the screen has no words for, so a CA "
        f"sees the raw identifier: {missing}. Add an entry to CHECK_CATALOGUE."
    )


def test_the_catalogue_has_no_entry_for_a_check_that_cannot_fire():
    spare = sorted(set(rs.CHECK_CATALOGUE) - emitted_check_names())
    assert not spare, (
        f"CHECK_CATALOGUE names checks this engine can no longer emit: {spare}. "
        "A label for something that can never appear is how the browser's own "
        "copy came to be trusted while it was wrong."
    )


def test_the_execution_error_name_is_deliberately_absent():
    for name in rs.CHECK_CATALOGUE:
        assert not name.endswith(EXECUTION_ERROR_SUFFIX), (
            f"{name} is the runner's wrapper for a check that itself raised. The "
            "browser renders that shape by rule, not by lookup."
        )


@pytest.mark.parametrize("name,body", sorted(rs.CHECK_CATALOGUE.items()))
def test_each_entry_says_what_it_looks_for(name, body):
    assert body["label"] and not body["label"].islower(), (
        f"{name}'s label reads like an identifier rather than a heading")
    assert len(body["looks_for"]) >= 40 and body["looks_for"].endswith("."), (
        f"{name}'s `looks_for` is what the tab lists so a CA knows what the "
        "button covers; it has to be a sentence")


def test_the_three_judgement_calls_are_marked_as_such():
    """A heuristic filed beside eight invariants, with nothing saying which is
    which, is how a CA learns to discount the invariants too."""
    served = {c["check_name"]: c for c in rs.check_catalogue()["checks"]}
    for kind in ledger_anomalies.ALL_KINDS:
        assert served[kind]["is_heuristic"] is True, f"{kind} is a judgement call"
    assert served["trial_balance"]["is_heuristic"] is False, (
        "debits equalling credits is an invariant, not an opinion")


def test_the_catalogue_carries_what_the_engine_cannot_see():
    """A clean result must not read as a clean set of books."""
    not_checked = rs.check_catalogue()["not_checked"]
    assert len(not_checked) >= 3
    assert all(len(s) >= 40 for s in not_checked)


def test_the_fixed_asset_vocabulary_matches_its_own_source():
    """`integrity.ALL_KINDS` is a DECLARATION and could drift from the module it
    declares. The kinds are read back out of that module's AST — every string
    literal under a `"kind"` key — so adding a finding there and forgetting the
    tuple fails here rather than reaching a CA as a raw identifier."""
    tree = ast.parse(pathlib.Path(fa_integrity.__file__).read_text())
    in_source: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if (isinstance(key, ast.Constant) and key.value == "kind"
                    and isinstance(value, ast.Constant)
                    and isinstance(value.value, str)):
                in_source.add(value.value)

    assert in_source, "the AST walk found no kind literals — it has gone blind"
    assert in_source == set(fa_integrity.ALL_KINDS), (
        "integrity.ALL_KINDS disagrees with the kinds the module actually "
        f"builds. Only in the source: {sorted(in_source - set(fa_integrity.ALL_KINDS))}; "
        f"only declared: {sorted(set(fa_integrity.ALL_KINDS) - in_source)}"
    )
