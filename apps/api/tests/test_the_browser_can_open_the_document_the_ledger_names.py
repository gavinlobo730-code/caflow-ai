"""
ACC-22 — every source the ledger can name has an ANSWER in the browser.

WHY THIS GUARD LIVES HERE AND NOT IN apps/web
    `apps/api/domain/accounting/journal_source.py` owns the vocabulary:
    ALL_SOURCES, and ENTRY_IS_THE_RECORD within it. Where each one OPENS is a
    fact about Next.js routes, so the map is
    `apps/web/lib/accounting/sourceDocument.ts`. That makes two files that have
    to agree, and a guard written in `apps/web` would read the browser's list
    and assert it against the browser's list — passing whenever both drifted
    together, which is exactly what the Schedule III caption list did for
    months.

    So this asserts from the side that owns the vocabulary: every value the
    backend can stamp is either routed, or the entry itself, or REFUSED WITH A
    REASON. A twenty-fourth source added to journal_source.py fails here until
    somebody says where it goes.

WHAT A REFUSAL HAS TO BE
    A sentence about THAT source, not a shared paragraph: two sources are refused for different reasons and a CA acts on each
    differently. The map is EMPTY since POST-A-096, when the last two (a settlement, whose screen was keyed on the employee, and a
    year-end adjustment, whose screen lives under its engagement) got a way in. The rule stays for the next source that has nowhere
    to go, and a test below holds those two routed so neither slips back onto the map unseen.
"""
from __future__ import annotations

import pathlib
import re
import sys

from domain.accounting import journal_source as JS

WEB = pathlib.Path(__file__).resolve().parents[3] / "apps" / "web"
MODULE = WEB / "lib" / "accounting" / "sourceDocument.ts"


def _source() -> str:
    assert MODULE.exists(), f"the browser's route map is gone: {MODULE}"
    return MODULE.read_text(encoding="utf-8")


def _routed() -> set[str]:
    """The keys of the ROUTES object literal.

    Read from the literal rather than by running the module: this repository
    has no TypeScript runtime in the Python suite, and the keys are what the
    guard is about. A vacuity floor below stops a regex that stops matching
    from reading as "everything is routed".
    """
    src = _source()
    body = src[src.index("const ROUTES:"):]
    body = body[: body.index("\n};")]
    return set(re.findall(r"^\s{2}([A-Za-z_][A-Za-z0-9_]*):\s*\{", body, re.M))


def _refused() -> dict[str, str]:
    src = _source()
    body = src[src.index("export const NO_ROUTE_REASON"):]
    body = body[: body.index("\n};")]
    return {m.group(1): m.group(2) for m in
            re.finditer(r"^\s{2}([A-Za-z_][A-Za-z0-9_]*):\s*\n?\s*\"(.*?)\"",
                        body, re.M | re.S)}


def _entry_is_the_record() -> set[str]:
    src = _source()
    line = re.search(r"export const ENTRY_IS_THE_RECORD[^=]*=\s*\[(.*?)\]", src, re.S)
    assert line, "the browser no longer declares ENTRY_IS_THE_RECORD"
    return set(re.findall(r'"([^"]+)"', line.group(1)))


def test_the_guard_is_reading_something():
    """A regex that stops matching must fail, not quietly approve everything."""
    assert len(_routed()) >= 21, f"only {len(_routed())} routes parsed — the regex has drifted"
    # The refusal map is empty, so a regex that stopped matching would read the same as an empty map: the parse is asked of a
    # sample that has one entry, through the same function.
    assert "export const NO_ROUTE_REASON" in _source(), "the refusal map is gone"
    assert len(_entry_is_the_record()) == 3, "ENTRY_IS_THE_RECORD is three values"


def test_every_source_the_backend_stamps_has_an_answer():
    answered = _routed() | set(_refused()) | _entry_is_the_record()
    missing = sorted(JS.ALL_SOURCES - answered)
    assert missing == [], (
        "a ledger row can carry these and the browser does not know where they "
        "go — route them in apps/web/lib/accounting/sourceDocument.ts, or add a "
        "sentence to NO_ROUTE_REASON saying why there is nowhere: "
        + ", ".join(missing))


def test_the_browser_routes_nothing_the_backend_never_stamps():
    stray = sorted((_routed() | set(_refused())) - set(JS.ALL_SOURCES))
    assert stray == [], (
        "these are routed or refused in the browser and are not in "
        "journal_source.ALL_SOURCES, so no entry can ever carry them: "
        + ", ".join(stray))


def test_the_three_that_are_their_own_record_match_the_python_set():
    # The browser sends these to the JOURNAL ENTRY rather than to a document,
    # and it must send exactly the three that carry no source_id — one more
    # would hide a real document, one fewer would build a link to nothing.
    assert _entry_is_the_record() == set(JS.ENTRY_IS_THE_RECORD)


def test_nothing_is_both_routed_and_refused():
    both = sorted(_routed() & set(_refused()))
    assert both == [], f"routed AND refused: {both}"


def test_a_refusal_is_about_its_own_source():
    reasons = _refused()
    assert len(set(reasons.values())) == len(reasons), (
        "two sources share one refusal sentence — they are refused for "
        "different reasons and a CA acts on each differently")
    for source, reason in reasons.items():
        assert len(reason) > 40, f"{source}'s refusal says nothing: {reason!r}"


def test_a_routed_source_is_not_one_whose_entry_is_the_record():
    # Routing one of the three would send the CA to a list keyed on a
    # source_id that is, by construction, null.
    overlap = sorted(_routed() & set(JS.ENTRY_IS_THE_RECORD))
    assert overlap == [], f"these have no document row to open: {overlap}"


def test_a_settlement_and_a_year_end_adjustment_are_routed_and_not_refused():
    """POST-A-096: both have a screen that opens them by the id the row carries (the payroll Inputs tab shows the recorded settlement,
    and the year-end list finds an adjustment's engagement). Neither goes back on the refusal map without this failing."""
    assert {"settlement", "year_end_adjustment"} <= _routed()
    assert not ({"settlement", "year_end_adjustment"} & set(_refused()))


def test_the_refusal_parse_reads_an_entry_when_there_is_one(monkeypatch):
    """The negative control for the empty map: one refusal written in the file's own shape is read back."""
    sample = ('export const NO_ROUTE_REASON: Record<string, string> = {\n'
              '  some_source:\n    "A sentence about some source that says why there is nowhere to send the CA.",\n'
              '};\n')
    monkeypatch.setattr(sys.modules[__name__], "_source", lambda: sample)
    assert _refused() == {"some_source": "A sentence about some source that says why there is nowhere to send the CA."}
