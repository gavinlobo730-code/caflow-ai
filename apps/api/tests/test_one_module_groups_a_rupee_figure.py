"""Indian digit grouping has ONE implementation in `apps/api`, and it is
`domain/money_text`.

CLAUDE.md states the rule — "A RUPEE FIGURE WRITTEN FOR A PERSON IS GROUPED THE
INDIAN WAY, AND THE GROUPING HAS ONE IMPLEMENTATION PER LANGUAGE" — and
`shared/money-grouping-vectors.json` pins the Python side against the browser's.
Neither of those stops a THIRD copy appearing inside `apps/api`, and one had:
`routers/assistant._rupees` sliced the digits into pairs itself.

It was not merely duplicated, it was WRONG, on every negative figure:

    paise      assistant._rupees     money_text.whole_rupees
     -150      "Rs -2"               "-1"
  -10,050      "Rs -101"             "-100"

`paise // 100` floors, and `abs()` was applied to the already-floored value, so
a magnitude was rounded AWAY from zero and the sign re-attached. The one caller
feeds it positive TDS thresholds, so nothing was visibly wrong — which is what
makes it worth a guard rather than a fix: it is latent until somebody gives
that prompt a client's real figures.

⚠️ WHAT THIS GUARD MATCHES IS A MECHANISM, NOT A NAME, and that distinction is
this file's own most-repeated lesson. Grouping Indian digits means walking the
string in TWO-character steps, so the tell is a `[-2:]` slice inside a loop.
A guard keyed on a FUNCTION NAME would pass the moment somebody called theirs
`_fmt`; a guard keyed on `//100` would fire on every honest paise-to-rupee
conversion in the tree.

It states one spelling of the mechanism and says so. The vacuity control below
is what keeps that honest: the scan must FIND the authority's own loop, so a
regex that stops matching fails rather than reporting a clean tree.
"""
import ast
import pathlib
import re

API = pathlib.Path(__file__).resolve().parent.parent
AUTHORITY = API / "domain" / "money_text.py"

#: A two-character step through a digit string — `rest[-2:]`, `head[-2:]`,
#: `s[-2:]` — which is what pair-grouping is and what nothing else needs.
PAIR_STEP = re.compile(r"\[-2:\]")


def _python_files():
    for f in API.rglob("*.py"):
        parts = set(f.parts)
        if parts & {"tests", "__pycache__", "migrations", ".venv", "venv"}:
            continue
        yield f


def _loops_with_a_pair_step(path: pathlib.Path) -> list[int]:
    """Line numbers of `while`/`for` bodies containing a `[-2:]` slice."""
    src = path.read_text(encoding="utf-8", errors="replace")
    if "[-2:]" not in src:
        return []
    try:
        tree = ast.parse(src)
    except SyntaxError:                                          # pragma: no cover
        return []
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.While, ast.For)):
            continue
        body = ast.get_source_segment(src, node) or ""
        if PAIR_STEP.search(body):
            hits.append(node.lineno)
    return hits


def test_the_scan_finds_the_authoritys_own_loop():
    """THE VACUITY CONTROL. `group_indian` walks the string in pairs, so if
    this finds nothing the matcher has stopped working and every assertion
    below is empty."""
    assert _loops_with_a_pair_step(AUTHORITY), (
        "the pair-step scan no longer matches domain/money_text.group_indian — "
        "fix the matcher rather than trusting the clean result below"
    )


def test_nothing_else_groups_digits_in_pairs():
    offenders = {
        str(f.relative_to(API)): lines
        for f in _python_files()
        if f != AUTHORITY and (lines := _loops_with_a_pair_step(f))
    }
    assert not offenders, (
        "these walk a digit string in two-character steps, which is Indian "
        "grouping, and `domain/money_text` is the one place allowed to: "
        f"{offenders}. Import `group_indian` / `rupees_paise` / `whole_rupees` "
        "instead. If a loop here is genuinely not grouping digits, say so in "
        "the commit and widen this guard deliberately."
    )


def test_the_assistant_delegates_rather_than_reimplementing():
    """The specific site this guard was written for, asserted on BEHAVIOUR
    rather than on the source — a scan cannot tell a delegating wrapper from a
    re-implementation that happens to avoid the matched spelling."""
    from domain.money_text import whole_rupees
    from routers.assistant import _rupees

    for paise in (0, 99, 150, 5_000_000, 10_000_000, -150, -10_050, -1):
        assert _rupees(paise) == f"Rs {whole_rupees(paise)}", paise
