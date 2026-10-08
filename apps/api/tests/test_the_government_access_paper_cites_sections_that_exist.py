"""The government-access paper cites only sections, rows and emails that exist.

WHY THIS EXISTS

    `docs/compliance/08-government-api-access-the-verified-position.md` is
    circulated outside engineering, and it cross-referenced a list that was not
    in it: eight references to "§6.4.4" and "§6.4.1" (six and two) against a
    section 6.4 that is a six-row priority table with no numbered items.
    Appendix C opened "§6.4.4 lists nine open questions", every email heading
    said which "question" it closed, and the tracking table carried the same
    numbers - all pointing at a list that had been condensed away. The callout
    over the table said "Four enquiries are already drafted" above six emails.
    Nothing could catch it: no test reads the paper.

    The rule is about the DOCUMENT, not those eight lines: every section
    reference resolves to a heading that exists, every row it names in the 6.4
    table is a row that exists, every email it names is one of the emails, and
    the count of emails agrees in the three places that state it. It cannot catch
    a reference that RESOLVES but means the wrong thing (a pointer to a real
    heading about something else), so a person still reads the replacements.

    What counts as a reference is deliberately narrow so that a statutory
    section is never mistaken for one of ours: a `§` followed by a SINGLE digit
    (`§16(2)(aa)`, `§43B(h)`, `§194C` and `§206AB` are not references to this
    paper's section 1, 4 or 2), `Appendix A.2`-style pointers and `section 6.4`.
"""
from __future__ import annotations

import re
from pathlib import Path

DOC = (Path(__file__).resolve().parents[3] / "docs" / "compliance"
       / "08-government-api-access-the-verified-position.md")

FENCE = re.compile(r"^```.*?^```", re.DOTALL | re.MULTILINE)
# A top-level number carries its full stop ("# 1. Summary"), a dotted one does not need it, and a
# bare number is NOT a heading id: "### 11 September 2026" is a date, not a section 11.
HEADING = re.compile(
    r"^#{1,4}\s+(?:Appendix\s+(?P<app>[A-D])\b"
    r"|(?P<num>[A-D]\.\d+(?:\.\d+)*|\d+(?:\.\d+)+)\s"
    r"|(?P<top>\d+)\.\s)",
    re.MULTILINE,
)
NOT_MORE = r"(?![\d(A-Za-z])"
REF_PARAGRAPH = re.compile(r"§(?P<id>\d(?:\.\d+)*)" + NOT_MORE)
REF_SECTION = re.compile(r"\bsection\s+(?P<id>\d(?:\.\d+)*)" + NOT_MORE)
REF_APPENDIX = re.compile(r"\bAppendix\s+(?P<id>[A-D](?:\.\d+(?:\.\d+)*)?)")
EMAIL_HEADING = re.compile(r"^###\s+Email\s+(\d+)\s+of\s+(\d+)\b(?P<rest>.*)$", re.MULTILINE)
EMAIL_REF = re.compile(r"\bEmail\s+(\d+)\b(?!\s+of\s+\d)")
ROWS = re.compile(r"§6\.4\s+rows?\s+(?P<rows>\d+(?:(?:,\s*|\s+and\s+)\d+)*)")
WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
         "eight": 8, "nine": 9, "ten": 10}


def prose(text: str) -> str:
    """The text with fenced code blanked line for line, so a line number still points at the file."""
    return FENCE.sub(lambda m: "\n" * m.group(0).count("\n"), text)


def heading_ids(text: str) -> set[str]:
    return {m.group("app") or m.group("num") or m.group("top")
            for m in HEADING.finditer(prose(text))}


def references(text: str) -> list[tuple[int, str]]:
    """(line number, id) for every section-style reference, fenced code excluded."""
    body = prose(text)
    found: list[tuple[int, str]] = []
    for rx in (REF_PARAGRAPH, REF_SECTION, REF_APPENDIX):
        for m in rx.finditer(body):
            found.append((body.count("\n", 0, m.start()) + 1, m.group("id")))
    return found


def dangling(text: str) -> list[str]:
    ids = heading_ids(text)
    return [f"line {ln}: reference to {i!r}, which no heading numbers"
            for ln, i in references(text) if i not in ids]


def section_64_rows(text: str) -> dict[int, str]:
    """Row number -> its 'What it settles' cell, for the table under '### 6.4'."""
    body = prose(text)
    start = re.search(r"^###\s+6\.4\b.*$", body, re.MULTILINE)
    if not start:
        return {}
    end = re.search(r"^#{1,3}\s", body[start.end():], re.MULTILINE)
    block = body[start.end(): start.end() + end.start()] if end else body[start.end():]
    rows: dict[int, str] = {}
    for line in block.splitlines():
        m = re.match(r"^\|\s*\*\*(\d+)\*\*\s*\|(.*)\|\s*$", line)
        if m:
            rows[int(m.group(1))] = m.group(2)
    return rows


def numbers(s: str) -> list[int]:
    return [int(n) for n in re.findall(r"\d+", s)]


def unknown_rows(text: str) -> list[str]:
    rows = section_64_rows(text)
    problems = []
    for m in ROWS.finditer(prose(text)):
        for n in numbers(m.group("rows")):
            if n not in rows:
                problems.append(f"'§6.4 row {n}' - the table has rows {sorted(rows)}")
    return problems


def emails(text: str) -> list[tuple[int, int, str]]:
    return [(int(m.group(1)), int(m.group(2)), m.group("rest"))
            for m in EMAIL_HEADING.finditer(prose(text))]


def tracking_rows(text: str) -> int:
    body = prose(text)
    start = re.search(r"^###\s+Tracking the replies\s*$", body, re.MULTILINE)
    if not start:
        return 0
    rest = body[start.end():]
    end = re.search(r"^#{1,3}\s", rest, re.MULTILINE)
    block = rest[: end.start()] if end else rest
    return sum(1 for ln in block.splitlines() if re.match(r"^\|\s*\d+\s*\|", ln))


def callout_count(text: str) -> int | None:
    m = re.search(r"^:::note\s+(\w+)\s+enquiries\s+are\s+already\s+drafted", prose(text),
                  re.MULTILINE | re.IGNORECASE)
    return WORDS.get(m.group(1).lower()) if m else None


def email_problems(text: str) -> list[str]:
    heads = emails(text)
    problems = []
    if not heads:
        return ["no 'Email k of N' headings found"]
    totals = {n for _, n, _ in heads}
    if len(totals) != 1:
        problems.append(f"the email headings disagree on N: {sorted(totals)}")
    n = max(totals)
    if sorted(k for k, _, _ in heads) != list(range(1, n + 1)):
        problems.append(f"the email headings are numbered {[k for k, _, _ in heads]}, "
                        f"not 1..{n}")
    if tracking_rows(text) != n:
        problems.append(f"the tracking table has {tracking_rows(text)} rows for {n} emails")
    if callout_count(text) != n:
        problems.append(f"the callout over section 6.4 counts {callout_count(text)} enquiries "
                        f"for {n} emails")
    for m in EMAIL_REF.finditer(prose(text)):
        if not 1 <= int(m.group(1)) <= n:
            problems.append(f"'Email {m.group(1)}' - there are emails 1..{n}")
    return problems


def agreement_problems(text: str) -> list[str]:
    """Each 6.4 row says which email asks it, and that email's heading says it closes the row."""
    rows = section_64_rows(text)
    problems = []
    asked: dict[int, set[int]] = {}
    for r, cell in rows.items():
        m = re.search(r"\*Asked in Email (\d+)\.?\*", cell)
        if m:
            asked.setdefault(int(m.group(1)), set()).add(r)
        elif "*Not asked by email" not in cell:
            problems.append(f"row {r} says neither which email asks it nor that none does")
    for k, _, rest in emails(text):
        m = ROWS.search(rest)
        closes = set(numbers(m.group("rows"))) if m else set()
        if closes != asked.get(k, set()):
            problems.append(f"Email {k} closes rows {sorted(closes)} by its heading but the "
                            f"table says it asks rows {sorted(asked.get(k, set()))}")
    return problems


def _read() -> str:
    return DOC.read_text(encoding="utf-8")


def test_every_section_reference_resolves_to_a_heading():
    found = dangling(_read())
    assert not found, "\n".join(found)


def test_every_row_named_in_section_6_4_is_a_row_of_that_table():
    assert not unknown_rows(_read()), "\n".join(unknown_rows(_read()))


def test_the_emails_are_counted_the_same_everywhere_they_are_counted():
    found = email_problems(_read())
    assert not found, "\n".join(found)


def test_the_priority_table_and_the_email_headings_agree_about_who_asks_what():
    found = agreement_problems(_read())
    assert not found, "\n".join(found)


def test_the_collector_is_not_vacuous():
    text = _read()
    assert len(heading_ids(text)) >= 40, "the headings were not parsed"
    assert len(references(text)) >= 15, "the references were not found"
    assert len(section_64_rows(text)) == 6, "the 6.4 table was not parsed"
    assert len(emails(text)) >= 5 and tracking_rows(text) >= 5
    # the ids a reader is most likely to be sent to exist
    assert {"6.4", "6.1", "3.4", "D.3", "A.2", "B.1", "B.2", "C"} <= heading_ids(text)
    assert "11" not in heading_ids(text), "a date heading was read as section 11"


def test_a_statutory_section_is_never_mistaken_for_one_of_ours():
    sample = "ITC under §16(2)(aa), §43B(h), §194C, §206AB and §139 are statute; §4.3 is ours."
    assert [i for _, i in references(sample)] == ["4.3"]


def test_the_rules_fire_on_the_original_defects():
    doc = (
        "## Contents\n\n# 1. Summary\n\n# 6. Confidence\n\n### 6.1 Why\n\n### 6.4 Open\n\n"
        "| Priority | Page | Settles |\n|---|---|---|\n"
        "| **1** | A | x. *Asked in Email 1.* |\n| **2** | B | y. *Not asked by email.* |\n\n"
        ":::note Four enquiries are already drafted\nbody\n:::\n\n"
        "# Appendix C - The enquiries\n\n### Email 1 of 2 - A · closes §6.4 row 1\n\n"
        "### Email 2 of 2 - B\n\n### Tracking the replies\n\n| # | To |\n|---|---|\n| 1 | a |\n| 2 | b |\n"
    )
    assert dangling(doc) == []
    # the original: a reference to a numbered item list under 6.4 that was never there
    assert len(dangling(doc + "\nSee §6.4.4 and §6.4.1.\n")) == 2
    # a row the table does not have
    assert len(unknown_rows(doc + "\ncloses §6.4 rows 1 and 7\n")) == 1
    # "Four enquiries" over two emails
    assert any("callout" in p for p in email_problems(doc))
    assert not email_problems(doc.replace("Four", "Two"))
    # an email numbered out of sequence, a table row short, an email that is not there
    assert email_problems(doc.replace("Email 2 of 2", "Email 3 of 2"))
    assert email_problems(doc.replace("| 2 | b |\n", ""))
    assert email_problems(doc.replace("Four", "Two") + "\nsend Email 5\n")
    # a heading and the table disagreeing about who asks a row
    assert agreement_problems(doc) == []
    assert agreement_problems(doc.replace("closes §6.4 row 1", "closes §6.4 row 2"))
    # a row that says nothing about email at all
    assert agreement_problems(doc.replace("*Not asked by email.*", ""))
