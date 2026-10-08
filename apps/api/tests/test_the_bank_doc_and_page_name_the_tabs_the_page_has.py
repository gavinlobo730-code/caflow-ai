"""The Bank screen's tabs are the same four in the page, its header comment and its design record.

WHY THIS EXISTS

    `apps/web/app/clients/[id]/bank/page.tsx` declares four tabs (Entries, Reconcile,
    Worth a Look, Rules). Its header comment opened "Bank - three tabs" and listed
    the fourth by a truncated name ("Worth a..."), and `docs/architecture/09-bank-
    entries.md` said "Three tabs: **Entries · Reconcile · Rules**" and that the web
    guard "holds the three-tab shape". Worth a Look joined on 17-09-2026 on the
    owner's decision; the guard in apps/web was updated at once (it asserts the real
    four) and the two places a human reads about the screen were not.

    The guard is on the Python side deliberately: a test written in apps/web would
    assert the page against a copy of itself, and it already does. This one reads
    the page's own `TABS` and holds the comment above it and the design record to
    that, so the count and the labels cannot be restated by hand in either.

    It checks the tab LIST and COUNT, not the description of each tab.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PAGE = REPO / "apps" / "web" / "app" / "clients" / "[id]" / "bank" / "page.tsx"
DOC = REPO / "docs" / "architecture" / "09-bank-entries.md"

WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8}
TAB = re.compile(r"\{\s*id:\s*\"([^\"]+)\"\s*,\s*label:\s*\"([^\"]+)\"")


def tabs(page: str) -> list[tuple[str, str]]:
    m = re.search(r"const TABS\b[^=]*=\s*\[(.*?)\n\];", page, re.DOTALL)
    return TAB.findall(m.group(1)) if m else []


def header_claim(page: str) -> tuple[int | None, str]:
    """(the number the header comment states, the comment itself)."""
    m = re.search(r"/\*\*(.*?)\*/", page, re.DOTALL)
    comment = m.group(1) if m else ""
    n = re.search(r"\bBank\s+\W+\s*(\w+)\s+tabs\b", comment)
    return (WORDS.get(n.group(1).lower()) if n else None), comment


def doc_claim(doc: str) -> tuple[int | None, list[str]]:
    """(the number the screens section states, the labels it lists), from 'N tabs: **A · B · C**'."""
    m = re.search(r"^(\w+)\s+tabs:\s+\*\*([^*]+)\*\*", doc, re.MULTILINE)
    if not m:
        return None, []
    return WORDS.get(m.group(1).lower()), [s.strip() for s in m.group(2).split("·")]


def problems(page: str, doc: str) -> list[str]:
    declared = tabs(page)
    labels = [label for _id, label in declared]
    out: list[str] = []
    if not declared:
        return ["the page's TABS were not found"]
    n_comment, comment = header_claim(page)
    if n_comment != len(declared):
        out.append(f"the page header says {n_comment} tabs and TABS declares {len(declared)}")
    for label in labels:
        if label not in comment:
            out.append(f"the page header does not name the tab {label!r} in full")
    n_doc, doc_labels = doc_claim(doc)
    if n_doc != len(declared):
        out.append(f"09-bank-entries.md says {n_doc} tabs and TABS declares {len(declared)}")
    if doc_labels != labels:
        out.append(f"09-bank-entries.md lists the tabs {doc_labels} and TABS declares {labels}")
    return out


def _page() -> str:
    return PAGE.read_text(encoding="utf-8")


def _doc() -> str:
    return DOC.read_text(encoding="utf-8")


def test_the_page_header_and_the_design_record_state_the_tabs_the_page_declares():
    found = problems(_page(), _doc())
    assert not found, "\n".join(found)


def test_the_collector_is_not_vacuous():
    declared = tabs(_page())
    assert len(declared) >= 3, declared
    assert ("entries", "Entries") in declared
    assert header_claim(_page())[0] is not None, "the page header's count was not found"
    assert doc_claim(_doc())[1], "the design record's tab line was not found"


def test_the_rule_fires_on_each_way_the_count_goes_stale():
    page = ('/**\n * Bank — four tabs, one working screen.\n *   Entries  x\n *   Worth a Look  y\n */\n'
            'const TABS: { id: T; label: string }[] = [\n'
            '  { id: "entries", label: "Entries", title: "t" },\n'
            '  { id: "worth", label: "Worth a Look", title: "t" },\n];\n')
    # two declared, header says four: stale
    assert any("header says 4" in p for p in problems(page, "Two tabs: **Entries · Worth a Look**"))
    ok = page.replace("four tabs", "two tabs")
    assert problems(ok, "Two tabs: **Entries · Worth a Look**") == []
    # the doc's count, its labels and their order are each held
    assert problems(ok, "Three tabs: **Entries · Worth a Look**")
    assert problems(ok, "Two tabs: **Worth a Look · Entries**")
    assert problems(ok, "Two tabs: **Entries · Reconcile**")
    # a header that abbreviates a label is not naming it
    assert problems(ok.replace("Worth a Look  y", "Worth a…  y"), "Two tabs: **Entries · Worth a Look**")
