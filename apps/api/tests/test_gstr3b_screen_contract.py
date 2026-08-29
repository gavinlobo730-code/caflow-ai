"""Every field the GSTR-3B screen reads must be one the endpoint returns.

WHAT WAS WRONG
    apps/web/app/gst/gstr3b/page.tsx rendered `result.working`, typed as
    GSTR3BWorking. That interface described /api/gst/gstr3b/COMPUTE — book vs
    GSTR-2A vs eligible ITC, plus a net_payable block. computeGSTR3B was moved
    to /gstr3b/from-books, whose working block is a different shape entirely,
    and the type did not move with it.

    Nothing caught it. The move happens at `apiPost<FromBooksGSTR3B>(...)`,
    which is a cast: TypeScript checks the annotation against nothing. `pnpm
    build`, `tsc --noEmit` and `pnpm lint` all passed. So did 7,000 backend
    tests, because no backend test reads the screen.

    On the deployed screen, pressing Compute:

      * rendered every ITC figure as "Rs NaN" — w.itc.book_igst_paise and the
        other eight are simply absent, and undefined/100 is NaN; and
      * threw on w.net_payable.igst_paise, because w.net_payable is undefined.
        A TypeError during render takes the whole page, so the CA saw the
        return blank out after asking for it.

    And saveGSTR3BReturn, which runs BEFORE the throw, wrote those same
    undefined values to gstr3b_returns — JSON.stringify drops undefined keys,
    so the stored return silently kept whatever those columns last held.

WHAT THIS TEST DOES
    Reads the screen's own source, extracts every `w.a.b` binding, and walks it
    against a real response built by driving posted documents through the e2e
    harness. A field the screen reads and the endpoint does not return fails
    here, in the backend suite, on the commit that introduces it.

    Comments are stripped before extraction. Twice in this codebase a test that
    scanned raw source has been satisfied by its own explanatory comment, and a
    contract test that passes because it matched a sentence about the contract
    is worse than no test.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from _pytest.monkeypatch import MonkeyPatch

import tests.test_gstr3b_itc_reversal_from_books as E

WEB = Path(__file__).resolve().parents[2] / "web"
SCREEN = WEB / "app" / "gst" / "gstr3b" / "page.tsx"

# Trailing segments that are JavaScript, not response fields.
_JS = {"map", "filter", "reduce", "length", "slice", "some", "every", "forEach",
       "find", "join", "toFixed", "toLocaleString"}

pytestmark = pytest.mark.skipif(not SCREEN.is_file(),
                                reason="needs apps/web/app/gst/gstr3b/page.tsx")


def _code_only(src: str) -> str:
    """Source with // line comments and /* */ blocks removed."""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"^\s*//.*$", "", src, flags=re.M)


def _bindings() -> set[tuple[str, ...]]:
    """Every `w.a.b[.c]` the screen reads, as a tuple path."""
    code = _code_only(SCREEN.read_text(encoding="utf-8"))
    out: set[tuple[str, ...]] = set()
    for m in re.finditer(r"\bw((?:\.[A-Za-z_][A-Za-z_0-9]*)+)", code):
        parts = tuple(m.group(1).lstrip(".").split("."))
        while parts and parts[-1] in _JS:
            parts = parts[:-1]
        if len(parts) >= 2:
            out.add(parts)
    return out


@pytest.fixture()
def working():
    """A real from-books response, with a reversal in it so 4(B) is populated."""
    mp = MonkeyPatch()
    try:
        db = E._setup(mp)
        bill = E._receive_bill(db, "B-1", 5_00000, "2025-06-12")
        E._cancel_on(mp, bill, "2025-07-15")
        E._receive_bill(db, "B-2", 2_00000, "2025-07-04")
        yield E._3b(db, E.JULY)["working"]
    finally:
        mp.undo()


# ── the extraction has to actually find things ───────────────────────────────

def test_the_screen_really_binds_the_fields_that_were_broken():
    """Guard. An empty or near-empty binding set would make the contract test
    below pass against any response at all, which is the state the codebase was
    already in."""
    paths = _bindings()
    assert len(paths) >= 15, f"only found {len(paths)} bindings: {sorted(paths)}"
    assert ("net_payable", "total_paise") in paths, (
        "the screen no longer reads net_payable — if Table 6 was removed this "
        "test should be revisited, but it was the field that threw")
    assert any(p[0] == "itc_reversal" for p in paths), sorted(paths)
    assert any(p[0] == "itc" for p in paths)


def test_the_comment_stripper_works():
    """The failure mode this file is guarding against in itself."""
    got = _code_only("const a = w.real.field;\n// see w.fake.field\n/* w.other.f */")
    assert "w.real.field" in got
    assert "fake" not in got and "other" not in got


# ── the contract ─────────────────────────────────────────────────────────────

def test_every_field_the_screen_reads_is_returned_by_the_endpoint(working):
    missing = []
    for path in sorted(_bindings()):
        node = working
        for i, key in enumerate(path):
            if not isinstance(node, dict) or key not in node:
                missing.append(".".join(("working",) + path[:i + 1]))
                break
            node = node[key]
    assert not missing, (
        "the GSTR-3B screen reads fields the from-books endpoint does not "
        f"return: {missing}. On the deployed screen these render as 'Rs NaN', "
        "or throw and blank the page if the missing level is the object.")


def test_the_values_are_numbers_the_screen_can_format(working):
    """`r(paise)` divides by 100. A string or a null formats as NaN just as
    surely as a missing key does."""
    bad = []
    for path in sorted(_bindings()):
        node = working
        for key in path:
            node = node[key] if isinstance(node, dict) and key in node else None
            if node is None:
                break
        if path[-1].endswith("_paise") and not isinstance(node, int):
            bad.append((".".join(path), type(node).__name__))
    assert not bad, f"non-integer paise fields: {bad}"


def test_each_reversal_reason_carries_what_the_list_prints(working):
    """The 4(B) breakdown is rendered from itc_reversal.reasons, whose element
    fields are bound to the map variable and so escape the scan above."""
    reasons = working["itc_reversal"]["reasons"]
    assert reasons, "the fixture produced no reversal — the assertion below would be vacuous"
    for row in reasons:
        for key in ("reason", "reclaimable", "igst_paise", "cgst_paise",
                    "sgst_paise", "cess_paise"):
            assert key in row, f"reason row is missing {key}: {row}"
        assert isinstance(row["reason"], str) and row["reason"]
        assert isinstance(row["reclaimable"], bool)


# ── The right panel, not just the right fields ──────────────────────────────

def test_the_gstr3b_breakdown_lives_in_the_gstr3b_tab():
    """It shipped inside GSTR1Tab, and nothing noticed.

    The client workspace has two compute panels — GSTR-1 and GSTR-3B — and both
    end with the same "Save as Draft" button. A text anchor on that button put
    the Table 3.1/4/6 breakdown into the GSTR-1 panel, where `working` is a
    different shape entirely: every figure would have rendered as zero, under
    headings naming Table 4(A) and Table 6, on a screen a CA reviews before
    filing. Type-checking cannot see it (both are Record<string, unknown>),
    every backend test passed, and the build was clean.

    So the placement is asserted, not just the field names.
    """
    from pathlib import Path

    src = (Path(__file__).resolve().parents[2] / "web" / "app" / "clients" / "[id]"
           / "compliance" / "gst" / "page.tsx").read_text()

    def body_of(name: str) -> str:
        start = src.index(f"function {name}(")
        after = src[start + 10:]
        nxt = after.find("\nfunction ")
        return after if nxt == -1 else after[:nxt]

    gstr3b = body_of("GSTR3BTab")
    gstr1 = body_of("GSTR1Tab")

    assert "Table-by-table breakdown" in gstr3b, (
        "the GSTR-3B breakdown is not in GSTR3BTab"
    )
    assert "Table-by-table breakdown" not in gstr1, (
        "the GSTR-3B breakdown is in the GSTR-1 panel, where working.outward and "
        "working.itc do not exist — every figure would render as zero"
    )
    # Same for the carry-forward, which belongs to the 3B return only.
    assert "itc_carried_forward_paise" in gstr3b
    assert "itc_carried_forward_paise" not in gstr1


def test_that_placement_detector_can_tell_the_panels_apart():
    """A guard on absence passes when it cannot find either function."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[2] / "web" / "app" / "clients" / "[id]"
           / "compliance" / "gst" / "page.tsx").read_text()
    assert "function GSTR1Tab(" in src
    assert "function GSTR3BTab(" in src
    assert src.index("function GSTR1Tab(") < src.index("function GSTR3BTab("), (
        "the detector assumes GSTR1Tab is declared first; if that changed, "
        "body_of would slice the wrong region"
    )
