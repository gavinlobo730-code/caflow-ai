"""A design document may not describe a provider factory as ignoring its argument when it refuses it.

WHY THIS EXISTS

    `domain/gst/portal_service.get_provider` once took a `provider_name` and returned
    the manual provider whatever it was asked for. That was a real sharp edge, it was
    written up in four compliance documents (01, 02, 07 and 08), and it was fixed: the
    factory now raises `ValueError` for any name but `manual`, pinned by
    `test_provider_factories_refuse_a_name_they_lack.py`. The documents went on saying
    "takes a name and ignores it" and "fix before a real provider exists" for as long
    as nobody re-read them, and a reader preparing the first real provider was told to
    fix something already fixed.

    The rule is about the DOCUMENTS' claim and the code's behaviour together:

      * the premise the documents now rest on is true (the factory refuses a name it
        does not have), so this test fails the day somebody reverts the code and the
        documents become wrong again; and
      * no paragraph under docs/compliance or docs/architecture that names
        `get_provider`, or immediately follows one that does, still says in the
        present tense that it ignores its name, takes a name and does nothing with
        it, or needs to be made to honour its argument.

    The window of one paragraph is deliberate: a code block naming the function is
    followed, as a separate paragraph, by the sentence about what it does, and a scan
    of the naming paragraph alone read the first and never the second. Past tense is
    fine and wanted ("once took a name and ignored it"): the history is the useful
    part and the patterns below are the present-tense forms only.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
DOC_DIRS = (REPO / "docs" / "compliance", REPO / "docs" / "architecture")

STALE = re.compile(
    r"\btakes a name\b"
    r"|\bignores (?:it|its|the (?:name|argument|provider name))\b"
    r"|\bhonou?r its argument\b",
    re.IGNORECASE,
)


def paragraphs(text: str) -> list[str]:
    return re.split(r"\n\s*\n", text)


def stale_claims(text: str) -> list[str]:
    """The paragraphs that name `get_provider` (or follow one that does) and still claim it
    ignores its name."""
    paras = paragraphs(text)
    found = []
    for i, para in enumerate(paras):
        near = "get_provider" in para or (i > 0 and "get_provider" in paras[i - 1])
        if near and STALE.search(para):
            found.append(" ".join(para.split())[:160])
    return found


def _docs() -> list[Path]:
    return sorted(p for d in DOC_DIRS if d.is_dir() for p in d.glob("*.md"))


def test_the_factory_refuses_a_name_it_does_not_have():
    """The premise: if this fails the documents are wrong again, not merely this test."""
    from domain.gst.portal_service import ManualGSTProvider, get_provider

    assert isinstance(get_provider("manual"), ManualGSTProvider)
    with pytest.raises(ValueError):
        get_provider("a-provider-that-does-not-exist")


def test_no_compliance_or_architecture_doc_says_the_factory_ignores_its_name():
    problems = []
    for path in _docs():
        for claim in stale_claims(path.read_text(encoding="utf-8")):
            problems.append(f"{path.relative_to(REPO)}: {claim!r}")
    assert not problems, (
        "get_provider refuses a name it does not have (ValueError); these paragraphs "
        "still say otherwise:\n" + "\n".join(problems))


def test_the_collector_is_not_vacuous():
    docs = _docs()
    assert len(docs) >= 10, "the docs were not found"
    naming = [p for p in docs if "get_provider" in p.read_text(encoding="utf-8")]
    assert len(naming) >= 4, f"only {len(naming)} documents name get_provider: collector broken?"


def test_the_rule_fires_on_the_original_wording_and_not_on_the_history():
    # the four ways the documents said it
    assert stale_claims("`get_provider()` currently takes a name and **ignores it**; fix it.")
    assert stale_claims("Its `get_provider(provider_name)`\ntakes a name and ignores it.")
    assert stale_claims("| 5 | Fix `get_provider()` to honour its argument | Nothing today |")
    # the sentence about the code arrives in the paragraph AFTER the one naming it
    assert stale_claims("```python\ndef get_provider(n):\n    return M()\n```\n\n"
                        "It takes a name and ignores it. Today harmless.")
    # but not two paragraphs later
    assert not stale_claims("`get_provider` is the seam.\n\nSomething else.\n\n"
                            "A different function takes a name and ignores it.")
    # the corrected wording and the history are fine
    assert not stale_claims("`get_provider()` refuses any name but `manual` with a `ValueError`.")
    assert not stale_claims("`get_provider` once took a name and ignored it, so it was fixed.")
    assert not stale_claims("An unrelated paragraph where a parser ignores it entirely.")
