"""A filing walk-through does not state WHO MUST SIGN HOW as an unqualified rule.

WHY THIS EXISTS
    Every flow in `services/filing_demo/` ends in a signature stage whose
    methods carry a one-line note, and several of those notes stated a
    requirement as fact: "Class 3 digital signature via emSigner; mandatory
    for companies and LLPs" (GSTR-1, GSTR-3B, GSTR-9) and "Digital signature
    via emBridge; mandatory for companies and audit cases (Rule 12, IT Rules
    1962)" (ITR). docs/compliance/02-gst.md §3 calls CGST Rule 26 (whether the
    COVID EVC provisos of 27-04-2021 to 31-10-2021 ever became permanent) the
    single highest-priority verification in the GST file, and the Rule 12
    citation on the ITR note belongs to a different provision (the ERI
    scheme) than the one the sentence is about. These walk-throughs are shown
    to practising CAs, so a requirement is either read from a primary source
    or said "generally" with a pointer to the portal.

THE RULE, NOT A LIST OF TODAY'S FLOWS
    Every signature-method note in the package is found by walking the source
    of every module in `services/filing_demo/` (a dict literal with an `otp`
    key, and the argument of `_dsc_only(...)`), so a flow added next year is
    covered the day it is written. A note that states a requirement ("must",
    "mandatory", "required", "compulsory") has to carry a hedge ("generally",
    "usually", "typically" or "confirm"), and no note cites a rule number,
    because the number is the part nobody has read.

    The MCA "who certifies" claims are held in test_filing_demo_mca.py, where
    the flow is built.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent / "services" / "filing_demo"

REQUIREMENT = re.compile(
    r"\b(mandatory|compulsory|required|must|obligatory)\b", re.IGNORECASE)
HEDGE = re.compile(r"\b(generally|usually|typically|confirm)\b", re.IGNORECASE)
RULE_CITATION = re.compile(r"\bRule\s+\d", re.IGNORECASE)


def _constant_string(node: ast.AST):
    return node.value if (isinstance(node, ast.Constant)
                          and isinstance(node.value, str)) else None


def signature_notes() -> list[tuple[str, int, str]]:
    """(module, line, note) for every literal signature-method note."""
    found: list[tuple[str, int, str]] = []
    for path in sorted(PACKAGE.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                keys = {_constant_string(k): v
                        for k, v in zip(node.keys, node.values, strict=True)
                        if _constant_string(k) is not None}
                if "otp" in keys and "note" in keys:
                    note = _constant_string(keys["note"])
                    if note is not None:
                        found.append((path.name, node.lineno, note))
            elif (isinstance(node, ast.Call)
                  and getattr(node.func, "id", None) == "_dsc_only"
                  and node.args):
                note = _constant_string(node.args[0])
                if note is not None:
                    found.append((path.name, node.lineno, note))
    return found


def unqualified_requirements(notes) -> list[str]:
    return [f"{m}:{line}: {note!r}" for m, line, note in notes
            if REQUIREMENT.search(note) and not HEDGE.search(note)]


def rule_citations(notes) -> list[str]:
    return [f"{m}:{line}: {note!r}" for m, line, note in notes
            if RULE_CITATION.search(note)]


def test_the_scan_finds_the_signature_notes_it_is_meant_to_judge():
    """Vacuity floor: the GST returns, the ITR, the TDS statement and MCA each
    carry at least two methods, so a refactor that hides the notes from the
    walk (a builder function, a variable) fails here instead of passing the
    rule below over nothing."""
    notes = signature_notes()
    modules = {m for m, _, _ in notes}
    assert {"gstr1.py", "gstr3b.py", "gstr9.py", "itr.py", "tds_return.py",
            "mca.py"} <= modules, modules
    assert len(notes) >= 12, len(notes)


def test_no_signature_note_states_a_requirement_without_a_hedge():
    """"Mandatory for companies and LLPs" is a reading of CGST Rule 26 that
    the compliance file records as unsettled; a note may say what is
    generally expected and send the reader to the portal, and may not
    legislate."""
    assert unqualified_requirements(signature_notes()) == []


def test_no_signature_note_cites_a_rule_number():
    assert rule_citations(signature_notes()) == []


def test_the_dsc_notes_still_say_what_the_method_is():
    """Hedging is not deleting: the practical content (the token and the
    signer software) is what a CA comes to the walk-through for."""
    by_module: dict[str, list[str]] = {}
    for m, _, note in signature_notes():
        by_module.setdefault(m, []).append(note)
    for gst in ("gstr1.py", "gstr3b.py", "gstr9.py"):
        assert any("emSigner" in n and "Class 3" in n
                   for n in by_module[gst]), gst
    assert any("emBridge" in n for n in by_module["itr.py"])


def test_the_detectors_catch_the_notes_that_were_removed():
    """The negative control, kept: the two detectors must flag the sentences
    these flows used to carry."""
    removed = [
        ("gstr3b.py", 1, "Class 3 digital signature via emSigner; mandatory "
                         "for companies and LLPs"),
        ("itr.py", 2, "Digital signature via emBridge; mandatory for "
                      "companies and audit cases (Rule 12, IT Rules 1962)"),
    ]
    assert len(unqualified_requirements(removed)) == 2
    assert len(rule_citations(removed)) == 1
    hedged = [("gstr3b.py", 3, "Companies and LLPs are generally expected to "
                               "use DSC; confirm on the GST portal")]
    assert unqualified_requirements(hedged) == []
