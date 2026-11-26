"""No screen string and no statutory comment cites a paragraph of a provident fund, pension or insurance scheme that was replaced (POST-A-525).

WHAT WAS WRONG
    The Employees' Provident Funds Scheme, the Employees' Pension Scheme and the Employees' Deposit-Linked Insurance Scheme were
    each replaced on 29-06-2026 (G.S.R. 525(E), 527(E) and 526(E): the 2026 Schemes). The product still cited the 1952, 1995 and
    1976 paragraphs as the authority, in screens a CA reads and in the comments of the statutory modules: para 38(1) for the monthly
    deposit, para 26(6) for contributing above the ceiling, EPS 1995 para 3 and para 6, EDLI 1976. A CA who opens the Scheme to
    check a screen finds a paragraph that no longer says what the screen says, which is the first thing that costs a screen its
    credibility. Some of those sentences were also contradicted by the new text (a contribution "capped at Rs 15,000", an officer's
    allowance for the joint option).

THE RULE (written as the rule, not as a spelling of the sentences found)
    A paragraph citation is the word para / paragraph / paragraphs (or the pilcrow) followed by a number. If the sentence it stands in
    names one of the replaced schemes, or an Act or Scheme by its old year (1952, 1995, 1976), within a short distance of it, it
    must either carry "2026" (the new Scheme) or say in the same sentence that the old one was replaced, repealed, superseded or is
    being spoken of in the past ("until", "before", "formerly", "used to"). A paragraph of a replaced scheme cited as if it still
    governed fails.

    It reads every string, comment and docstring under apps/api (not its tests, migrations or scripts) and under apps/web's app,
    components and lib, so a new screen string or statutory comment is caught wherever it is written.

THE SECOND RULE, FOR THE SCREENS ONLY
    A web string a person reads does not name the EPF Act, the EPF & MP Act or the ESI Act as the current authority: the Code on
    Social Security, 2020 repealed them from 21-11-2025 (section 164(1)). The same succession exception applies. The Payment of
    Gratuity Act is added to this list with the gratuity labels (POST-A-526). What it does NOT reach: the sentences
    domain/payroll/one_time_earnings.py serves, which still cite EPF Act s.2(b) and ESI Act s.2(22) for which earnings count as
    wages; the Code's own text (s.2(88)) is a legal reading that waits on a person (POST-A-524), so nothing is re-pointed by
    guess.

NEGATIVE CONTROL
    The detector is run on sentences that must fail and sentences that must pass, below, so a rule that stops seeing anything is
    caught here and not by silence. Run over the tree as it stood on main on 19-11-2026, before this change, it found 29 passages
    citing a paragraph of a replaced scheme as current, in 13 files, and 9 web passages naming a repealed Act, in 4 files.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

API = Path(__file__).resolve().parents[1]
WEB = API.parent / "web"

# ── the paragraph citation, and what makes it a citation of a replaced scheme ───────────────────────────────────────────────────

_PARA = re.compile(r"(?:\bparas?\b\.?|\bparagraphs?\b|¶)\s*\d+(?:\([0-9a-z]+\))*", re.I)

#: A scheme or Act named by its old identity: the short names the old schemes were cited by, the replaced schemes' own names, or any
#: scheme with one of the three old years. The 2026 Schemes are named in full with "2026", which is what clears a sentence.
_REPLACED = re.compile(
    r"""(?ix)
      \bEPF\s+(?:&\s+MP\s+)?Scheme\b
    | \bEPS\b
    | \bEDLI\b
    | Employees['’]?\s+Pension\s+Scheme
    | Employees['’]?\s+Provident\s+Funds?\s+Scheme
    | Employees['’]?\s+Deposit[- ]Linked\s+Insurance\s+Scheme
    | \b(?:Pension|Insurance)\s+Scheme\b
    | \b(?:1952|1995|1976)\s+Scheme\b
    | \bScheme,?\s+(?:1952|1995|1976)\b
    | \bEPS\s*(?:1995|95)\b
    """)

#: Said in the same sentence, the old scheme is being spoken of as the past it is.
_SUCCESSION = re.compile(
    r"(?i)\b(?:replac\w+|repeal\w+|supersed\w+|supersession|formerly|used to|until|before|old scheme|earlier scheme|no longer|"
    r"counterpart|successor|history|historic\w*)\b")

_WINDOW_BEFORE = 100
_WINDOW_AFTER = 70


def _sentences(text: str):
    """The prose of a source file as sentences: comment markers and quote marks dropped, lines joined."""
    text = re.sub(r"(?m)^[ \t]*(?:#:?|//+|\*+/?|/\*+)[ \t]?", " ", text)
    text = text.replace('"""', " ").replace("'''", " ")
    text = re.sub(r"[\"'`]\s*\+\s*\n\s*[\"'`]", " ", text)
    text = re.sub(r"\s+", " ", text)
    # a sentence ends at a full stop or a semicolon followed by a space and a capital; a date, a section number, "G.S.R. 525(E)"
    # and "s.2(b)" never do
    return re.split(r"(?<!Misc\.)(?<=[.;])\s+(?=[A-Z(])", text)


def violations_in(text: str) -> list[str]:
    out = []
    for sentence in _sentences(text):
        if _SUCCESSION.search(sentence):
            continue
        for m in _PARA.finditer(sentence):
            before = sentence[max(0, m.start() - _WINDOW_BEFORE):m.start()]
            after = sentence[m.end():m.end() + _WINDOW_AFTER]
            near = before + " " + m.group(0) + " " + after
            if _REPLACED.search(near) and "2026" not in near:
                out.append(sentence.strip()[:200])
                break
    return out


# ── the detector is held to sentences that must fail and sentences that must pass ──────────────────────────────────────────────

MUST_FAIL = [
    "EPF Scheme 1952, para 38(1): the employer deposits contributions within fifteen days.",
    "The deposit is due under para 38(1) of the EPF Scheme 1952.",
    "EPS 1995 para 3 — 8.33% of the wage, capped at Rs 1,250.",
    "# EPS 1995 para 6, as amended by GSR 609(E): someone who joined EPF after that date is not a member.",
    "the employer must hold the joint request (EPF Scheme para 26(6), unverified reading).",
    "EDLI Scheme 1976 para 7 sets the ceiling.",
    "Employees' Pension Scheme 1995 (para 11(3), as the Supreme Court read it in 2022) is a different option.",
    "Excluded from EPS under paragraph 6 of the Pension Scheme.",
]

MUST_PASS = [
    "Employees' Provident Funds Scheme, 2026, paras 24(2)(ix) and 28(3).",
    "paragraph 9(4) of the Employees' Provident Funds Scheme, 2026 lets an employee and the employer jointly opt in writing.",
    "Employees' Pension Scheme, 2026 para 4(1) — 8.33% of the wage up to the notified wage ceiling.",
    "Which replaced para 38(1) of the 1952 Scheme on 29-06-2026.",
    "Until 29-06-2026 each of the three schemes stated Rs 15,000 (EPF Scheme 1952 para 26, Pension Scheme 1995 para 3).",
    "The 1952 Scheme's paragraph 26(6) was replaced by paragraph 9(4).",
    "Rule 30(2) of the Income-tax Rules sets the seventh of the month.",
    "GST return, para 3 of the circular, lists the tables.",
]


@pytest.mark.parametrize("sentence", MUST_FAIL)
def test_the_detector_flags_a_paragraph_of_a_replaced_scheme_cited_as_current(sentence):
    assert violations_in(sentence), sentence


@pytest.mark.parametrize("sentence", MUST_PASS)
def test_the_detector_passes_the_new_scheme_history_and_unrelated_paragraphs(sentence):
    assert violations_in(sentence) == [], sentence


# ── the tree ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────

_SKIP_API_DIRS = {"tests", "migrations", "scripts", "__pycache__", "node_modules", ".venv", "venv", "docs"}


def _api_files():
    for path in API.rglob("*.py"):
        if _SKIP_API_DIRS & set(path.relative_to(API).parts):
            continue
        yield path


def _web_files():
    for sub in ("app", "components", "lib"):
        for path in (WEB / sub).rglob("*"):
            if path.suffix not in (".ts", ".tsx") or ".test." in path.name:
                continue
            if "node_modules" in path.parts or ".next" in path.parts:
                continue
            yield path


def _all_violations():
    found = []
    for path in list(_api_files()) + list(_web_files()):
        root = API if API in path.parents else WEB
        for sentence in violations_in(path.read_text(encoding="utf-8", errors="ignore")):
            found.append(f"{path.relative_to(root.parent).as_posix()}: {sentence}")
    return found


def test_the_tree_has_something_for_the_rule_to_read():
    assert len(list(_api_files())) > 300 and len(list(_web_files())) > 300


def test_no_screen_string_or_statutory_comment_cites_a_paragraph_of_a_replaced_scheme():
    found = _all_violations()
    assert not found, (
        "A paragraph of a replaced scheme is cited as if it still governed. Cite the 2026 Scheme's paragraph (G.S.R. 525(E), 527(E), "
        "526(E) of 29-06-2026) or say in the sentence that the old one was replaced:\n  " + "\n  ".join(found))


# ── the second rule: a screen does not name a repealed Act as the current authority ────────────────────────────────────────────────

_ACT = re.compile(
    r"(?i)\bEPF\s+Act\b|\bEPF\s+&\s+MP\s+Act\b|Provident\s+Funds?\s+(?:and|&)\s+Misc(?:ellaneous|\.)?\s+Provisions\s+Act|"
    r"\bESI\s+Act\b|Employees['’]?\s+State\s+Insurance\s+Act")


def _code_text(src: str) -> str:
    """A TypeScript source with its comments taken out, so what is left is strings and JSX text."""
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    src = re.sub(r"(?<![:\\])//[^\n]*", " ", src)
    return src


def _web_act_violations(src: str) -> list[str]:
    out = []
    for sentence in _sentences(_code_text(src)):
        if _SUCCESSION.search(sentence):
            continue
        if _ACT.search(sentence):
            out.append(sentence.strip()[:200])
    return out


@pytest.mark.parametrize("sentence", [
    'subtitle="IT Act Section 192 &middot; EPF Act &middot; ESI Act"',
    "PF Challan (EPF Act 1952)",
    "# PF: Employees' Provident Funds and Misc. Provisions Act 1952",
    "ESIC (Employees' State Insurance Act 1948)",
])
def test_the_act_detector_flags_a_repealed_act_named_on_a_screen(sentence):
    assert _web_act_violations(sentence), sentence


def test_the_act_detector_passes_the_code_and_a_stated_succession():
    assert _web_act_violations('subtitle="IT Act Section 192 &middot; Code on Social Security, 2020"') == []
    assert _web_act_violations("The EPF Act was repealed from 21-11-2025 by the Code on Social Security, 2020.") == []
    assert _web_act_violations("// EPF Act s.6 said basic wages plus dearness allowance") == []


def test_no_web_screen_names_a_repealed_act_as_the_current_authority():
    found = []
    for path in _web_files():
        for sentence in _web_act_violations(path.read_text(encoding="utf-8", errors="ignore")):
            found.append(f"{path.relative_to(WEB.parent).as_posix()}: {sentence}")
    assert not found, (
        "A screen names an Act the Code on Social Security, 2020 repealed from 21-11-2025 (section 164(1)). Name the Code, or say in "
        "the sentence that the Act was repealed:\n  " + "\n  ".join(found))
