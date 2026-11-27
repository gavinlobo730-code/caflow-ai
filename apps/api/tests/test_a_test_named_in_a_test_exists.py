"""A test or test file that a test names exists (POST-A-024).

WHAT WAS WRONG
    A comment, docstring or failure message in the tests that sends the reader to `test_something` is a promise that the
    proof is there. The 15-09-2026 sweep found one such citation pointing at nothing (`test_backend_tables_exist`, since
    written as `test_backend_tables_exist_pg.py`) and declined a guard for a single instance. The class recurred: on
    14-11-2026 seven citations named tests or files that do not exist, among them the never-do list sending the reader
    to `tests/test_one_door_to_every_model.py` for the rule that one module talks to each AI provider, and the RLS
    category test naming `test_rls_actor_by_table_matrix_pg` for the matrix that is `test_rls_role_by_table_matrix_pg`.
    Each was fixed to the test that holds the rule.

THE RULE
    Every `test_...` token in a file under `tests/` resolves to a test file's name or to a name defined somewhere in the
    tests (a function, a class, an assigned name, an argument, an import), read with `ast`. Read on purpose:
      * `test_x.py` must be a test FILE; `test_x.pdf` (or any other extension) is data and is skipped;
      * `test_x*`, `test_x...` and `test_x…` are prefixes, as is a numbered family (`test_262`, `test_549`);
      * `test_x` where `test_x_pg.py` exists is the same file under its Postgres name;
      * a name broken across two comment lines (`test_a_rate_of_zero_is` / `# _honoured`) is read joined, and one that ends
        in an underscore (broken across two string literals or lines some other way) is read as the start of a name;
      * a token cut by a section number or an uppercase letter (`test_a_115BAC...`) is not a name and is skipped.
    What is left is either a defect or on EXEMPT below, with its reason. EXEMPT only shrinks: a line whose token now
    resolves, or no longer appears, fails, so a fixed entry cannot be kept for the next stale citation to hide behind.

WHAT THIS DOES NOT SEE
    A citation outside `tests/` (a router's comment, a design record) and a test named in prose without the `test_`
    prefix. Whether the cited test still proves what the sentence says is a reading, not a scan.
"""
from __future__ import annotations

import ast
import functools
import re
from pathlib import Path

TESTS = Path(__file__).resolve().parent
TOKEN = re.compile(r"\btest_[a-z0-9_]+")
NUMBERED = re.compile(r"test_r?\d+$")
WRAPPED = re.compile(r"\n[ \t]*#[ \t]*(_[a-z0-9_]+)")

#: Tokens that name something that is not a test, or name one that was deleted ON PURPOSE in a sentence that says so.
EXEMPT: dict[str, str] = {
    "test_debt_mf_is_flagged_as_slab_rate_estimate": "historical: the header describes what a deleted test wrongly asserted",
    "test_the_shipped_engagement_default_is_one_the_server_will_accept": "historical: the comment says it 'lived here' and what replaced it",
    "test_health": "historical: a deleted file (tests/test_health.py) the header explains was copying the formula",
    "test_health_engine": "historical: a deleted file (tests/test_health_engine.py), as above",
    "test_event": "data: an event_type value written to a fixture row",
    "test_feature": "data: the feature label a gateway test records usage under",
    "test_reads": "data: a temporary file a CI-guard test writes to tmp_path",
    "test_talks": "data: a temporary file a CI-guard test writes to tmp_path",
    "test_imports_a_reader": "data: a temporary file a CI-guard test writes to tmp_path",
    "test_it": "data: a function inside sample source a premise test writes",
    "test_x": "data: a placeholder name inside sample source two scanners are fed",
    "test_grant": "data: a test-only approval request type registered for the length of a test",
    "test_grant_refused": "data: a test-only approval request type, as above",
    "test_mock_secret": "data: a placeholder secret value",
    "test_a": "data: a synthetic test module name in a directory the docs-lane finder's own tests write to tmp_path",
    "test_b": "data: a synthetic test module name in a directory the docs-lane finder's own tests write to tmp_path",
    "test_c": "data: a synthetic test module name in a directory the docs-lane finder's own tests write to tmp_path",
    "test_broken": "data: a synthetic test module name in a directory the docs-lane finder's own tests write to tmp_path",
    "test_other": "data: a synthetic test module name in a directory the docs-lane finder's own tests write to tmp_path",
    "test_reader": "data: a synthetic test module name in a directory the docs-lane finder's own tests write to tmp_path",
    "test_unrelated": "data: a synthetic test module name in a directory the docs-lane finder's own tests write to tmp_path",
    "test_user": "data: a synthetic test module name in a directory the docs-lane finder's own tests write to tmp_path",
}


def _files() -> list[Path]:
    return sorted(p for p in TESTS.rglob("*.py") if "__pycache__" not in p.parts)


def _scanned() -> list[Path]:
    """Every test file but this one, whose negative control names tests that do not exist on purpose."""
    return [p for p in _files() if p.name != Path(__file__).name]


@functools.lru_cache(maxsize=1)
def known_names() -> tuple[frozenset[str], frozenset[str]]:
    """(test file stems, every name defined in the tests)."""
    stems = {p.stem for p in _files()}
    defined: set[str] = set()
    for path in _files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                defined.add(node.name)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                defined.add(node.id)
            elif isinstance(node, ast.arg):
                defined.add(node.arg)
            elif isinstance(node, ast.alias):
                defined.add(node.asname or node.name.split(".")[-1])
    return frozenset(stems), frozenset(defined)


def unresolved_in(text: str, stems: frozenset[str], defined: frozenset[str]) -> list[str]:
    """The `test_...` tokens in `text` that name nothing, by the rule in the header."""
    known = stems | defined
    out: list[str] = []
    for m in TOKEN.finditer(text):
        token, after = m.group(0), text[m.end():m.end() + 4]
        if after[:1].isupper() or after[:1].isdigit():
            continue                                                    # cut by a section number or a capital: not a name
        wrapped = WRAPPED.match(text, m.end())
        if wrapped:
            token += wrapped.group(1)
        if after.startswith(".py"):
            if token not in stems:
                out.append(token)
            continue
        if after[:1] == "." and after[1:2].isalpha():
            continue                                                    # a data file's name (test_deleted.pdf)
        if after.startswith(("*", "...", "…")) or NUMBERED.match(token) or token.endswith("_"):
            if not any(k.startswith(token) for k in known):
                out.append(token)
            continue
        if token in known or f"{token}_pg" in stems:
            continue
        out.append(token)
    return out


@functools.lru_cache(maxsize=1)
def scan() -> dict[str, list[str]]:
    stems, defined = known_names()
    found: dict[str, list[str]] = {}
    for path in _scanned():
        for token in unresolved_in(path.read_text(encoding="utf-8"), stems, defined):
            found.setdefault(token, []).append(path.name)
    return found


def test_every_test_a_test_names_exists():
    stale = {t: files for t, files in scan().items() if t not in EXEMPT}
    assert not stale, ("These tests name a test or a test file that does not exist. Point each at the test that holds the rule "
                       "(or, for a name that is data or a deleted test the sentence says is deleted, add it to EXEMPT with the reason):\n  "
                       + "\n  ".join(f"{t}  in {sorted(set(f))}" for t, f in sorted(stale.items())))


def test_the_exemptions_are_still_needed():
    found = scan()
    unused = sorted(t for t in EXEMPT if t not in found)
    assert not unused, f"These EXEMPT entries no longer name an unresolved token: delete them: {unused}"


def test_the_scan_reads_what_it_says_it_reads():
    """The negative control: a fabricated citation is caught, and each rule in the header lets its own case through."""
    stems = frozenset({"test_alpha", "test_beta_pg", "test_262_portal"})
    defined = frozenset({"test_gamma_is_held", "test_alpha"})
    assert unresolved_in("see test_does_not_exist for the proof", stems, defined) == ["test_does_not_exist"]
    assert unresolved_in("tests/test_missing.py holds it", stems, defined) == ["test_missing"]
    assert unresolved_in("tests/test_gamma_is_held.py", stems, defined) == ["test_gamma_is_held"], "a test's NAME is not a FILE"
    assert unresolved_in("test_alpha.py and test_gamma_is_held", stems, defined) == []
    assert unresolved_in("the test_beta file", stems, defined) == [], "a file under its _pg name"
    assert unresolved_in("test_262's guard and test_gamma*", stems, defined) == []
    assert unresolved_in("test_999's guard", stems, defined) == ["test_999"], "a numbered family that does not exist"
    assert unresolved_in("# test_gamma_is\n# _held asserts it", stems, defined) == [], "a name wrapped across comment lines"
    assert unresolved_in("test_deleted.pdf and test_a_115BAC", stems, defined) == []
    assert unresolved_in('"test_gamma_" "is_held"', stems, defined) == [], "a name broken across two string literals"
    assert unresolved_in('"test_zeta_" "is_held"', stems, defined) == ["test_zeta_"], "a broken name that starts nothing"


def test_the_scan_sees_the_tests():
    stems, defined = known_names()
    assert len(stems) > 1000 and len(defined) > 10000, "the scan has stopped reading the tests it reads"
    assert "test_a_test_named_in_a_test_exists" in stems
