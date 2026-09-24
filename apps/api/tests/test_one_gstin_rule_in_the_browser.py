"""ONE GSTIN RULE IN THE BROWSER, AND THE ONE DELIBERATE EXCEPTION SAYS SO.

GST-29 closed the check digit at every door in `apps/api`. Nobody swept
`apps/web`, and the sweep that found this counted **eight** independent copies
of the GSTIN shape regex there against **one** caller of the browser's own
authority — `lib/gst/gstin.gstinProblem`, which has tested the check digit
since it was written and is pinned to `domain/gst/gstin.py` by
`tests/fixtures/gstin.json`.

**THE SHAPE CANNOT SEE THE COMMONEST WRONG GSTIN.** `27AAPFU0939F1ZV` and
`27AAPFU0399F1ZV` are both well-formed; only the check digit tells them apart,
and a transposition inside the PAN is exactly what a person typing fifteen
characters produces. The shape also accepts a state code that does not exist.

**THE WORST OF THE EIGHT WAS `app/risks/page.tsx`** — the screen whose GSTIN
Mismatch section exists for no other purpose — so the one page a CA opens to be
told their client's GSTIN is wrong reported clean on every transposition. The
others were: the CLIENT form and the client bulk import (a client's own GSTIN
is the registration every one of that client's returns is filed under, and
`models.client.validate_gstin` on the server is deliberately shape-only too,
because 512 invented fixture GSTINs across 95 files flow through that Pydantic
field — so the browser was the ONLY place the check digit could be asked); the
firm's own GSTIN on Settings and at onboarding, which `domain/firm/identity`
puts on every fee invoice the practice raises; a VENDOR's GSTIN, which is half
the key `domain/gst/itc_matching` reconciles a GSTR-2B on; and the CSV import
mapper.

**THE EXCEPTION IS `lib/invoices/compliance.ts` AND IT IS NOT AN OVERSIGHT.**
Its `GSTIN_RE` answers Rule 48(4)'s supply limb and Rule 138's — *is the
recipient a registered person at all* — and `domain/gst/irn_scope.py` answers
that on the SHAPE for a recorded reason: a checksum would put the two
implementations in disagreement on a transposition, which says nothing about
who the customer is, and `shared/irn-parity-vectors.json` pins that agreement.
Tightening it would break the parity fixture. The exemption is named here with
that reason and the file must still carry it, so deleting the regex without
deleting the exemption fails.

**AND A PLACEHOLDER IS A GSTIN THE SCREEN TEACHES.** Four example GSTINs a CA
reads — two `placeholder=` attributes on the relationships and pipeline
screens, the invoice-terms example, a supplier placeholder — and the client
form's own error message had check digits that this product's own validator
rejects. That is the third time this repository has found a specimen
identifier its own rule refuses; it is checked here rather than left to be
found a fourth time.

**THE GUARD IS ON THE PYTHON SIDE** — the Schedule III caption lesson. One
written in `apps/web` would assert the browser against a copy of itself and
pass whenever the browser drifted as a whole.
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

from domain.gst.gstin import checksum_char, problem_with

API = pathlib.Path(__file__).resolve().parent.parent
WEB = API.parent / "web"

# Any regex that spells the GSTIN shape, however the repetition counts are
# written: `[A-Z]{1}` and `[A-Z]` are the same rule with different spellings,
# and both appeared among the eight.
_GSTIN_SHAPE_REGEX = re.compile(r"\[0-9\]\{2\}\s*\[A-Z\]\{5\}")

# The one file allowed to carry it, with the reason. See the docstring.
_SHAPE_ONLY_BY_DESIGN = {
    "lib/gst/gstin.ts": "the authority itself — it tests the check digit after the shape",
    "lib/invoices/compliance.ts": (
        "Rule 48(4)'s supply limb asks whether the recipient is registered at all, "
        "and irn_scope.py answers it on the shape; shared/irn-parity-vectors.json "
        "pins the two, so a checksum here breaks the fixture"
    ),
}


def _web_sources() -> list[pathlib.Path]:
    out: list[pathlib.Path] = []
    for d in ("app", "components", "lib", "scripts"):
        for p in (WEB / d).rglob("*.ts*"):
            if "node_modules" in p.parts:
                continue
            out.append(p)
    return sorted(out)


_SOURCES = _web_sources()


def test_the_probe_reads_a_real_tree():
    """Vacuity floor: two of the three assertions below are 'nothing found'."""
    assert len(_SOURCES) > 500, f"only {len(_SOURCES)} browser sources — the walk is broken"
    assert (WEB / "lib" / "gst" / "gstin.ts").exists(), "the browser authority is gone"


def test_only_the_named_files_spell_the_gstin_shape():
    offenders = []
    for p in _SOURCES:
        rel = str(p.relative_to(WEB))
        if rel in _SHAPE_ONLY_BY_DESIGN or p.name.endswith((".test.ts", ".test.tsx")):
            continue
        src = p.read_text(encoding="utf-8")
        code = "\n".join(line.split("//", 1)[0] for line in src.splitlines())
        if _GSTIN_SHAPE_REGEX.search(code):
            offenders.append(rel)
    assert not offenders, (
        "A GSTIN shape regex accepts every transposition inside the PAN. "
        "`lib/gst/gstin.gstinProblem` is the one browser implementation and it "
        "tests the check digit:\n  " + "\n  ".join(offenders)
    )


@pytest.mark.parametrize("rel", sorted(_SHAPE_ONLY_BY_DESIGN))
def test_each_exemption_still_describes_a_real_file(rel: str):
    """An exemption for a file that no longer carries the pattern is an
    exemption that will quietly cover the next one added to it."""
    p = WEB / rel
    assert p.exists(), f"{rel} is exempt and does not exist — drop the exemption"
    assert _GSTIN_SHAPE_REGEX.search(p.read_text(encoding="utf-8")), (
        f"{rel} is exempt from the shape-regex rule and no longer carries one — "
        "drop the exemption rather than leaving it to cover a future copy"
    )


def test_the_seven_doors_ask_the_authority():
    """Behaviour, not a count: every place a human types or an importer reads a
    GSTIN must import the authority by name."""
    doors = [
        "app/risks/page.tsx",
        "app/settings/page.tsx",
        "app/onboarding/page.tsx",
        "app/clients/page.tsx",
        "app/clients/[id]/purchases/page.tsx",
        "components/ClientFormModal.tsx",
        "lib/imports/mappers.ts",
    ]
    # AN IMPORT STATEMENT, NOT A MENTION. The first spelling of this looked for
    # the substring "gst/gstin" anywhere in the file, and its negative control
    # — deleting the import from `lib/imports/mappers.ts` — PASSED, because the
    # comment written above that import to explain the fix names the module.
    # A guard that is satisfied by its own explanation is no guard; this is the
    # third time in this run and the rule is in CLAUDE.md. `from "…"` reaches
    # both spellings in the tree: "@/lib/gst/gstin" and the relative
    # "../gst/gstin.ts".
    imports_authority = re.compile(r'from\s+"[^"]*gst/gstin(?:\.ts)?"')
    missing = []
    for d in doors:
        src = (WEB / d).read_text(encoding="utf-8")
        code = "\n".join(line.split("//", 1)[0] for line in src.splitlines())
        if not imports_authority.search(code):
            missing.append(d)
    assert not missing, (
        "these doors take a typed or imported GSTIN and must resolve it through "
        "lib/gst/gstin:\n  " + "\n  ".join(missing)
    )


# ── A specimen GSTIN is a GSTIN the screen teaches ─────────────────────────

_GSTIN_LITERAL = re.compile(r"\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]\b")


def _specimen_sites() -> list[tuple[str, str]]:
    """GSTIN literals a CA actually READS: a placeholder, an example in prose,
    an error message. Test files are excluded — several of their literals are
    deliberately wrong, which is the point of them."""
    out = []
    for p in _SOURCES:
        rel = str(p.relative_to(WEB))
        if p.name.endswith((".test.ts", ".test.tsx")) or rel.startswith("scripts/"):
            continue
        if rel == "lib/gst/gstin.ts":
            continue  # its docstring names a transposition on purpose
        for line in p.read_text(encoding="utf-8").splitlines():
            if not any(k in line for k in ("placeholder", "Expected:", "e.g.", "GSTIN ")):
                continue
            for m in _GSTIN_LITERAL.finditer(line):
                out.append((rel, m.group(0)))
    return sorted(set(out))


_SPECIMENS = _specimen_sites()


def test_there_are_specimens_to_check():
    assert _SPECIMENS, "found no specimen GSTIN at all — the literal probe is broken"


@pytest.mark.parametrize("rel,gstin", _SPECIMENS)
def test_a_specimen_gstin_passes_this_products_own_validator(rel: str, gstin: str):
    problem = problem_with(gstin)
    assert problem is None, (
        f"{rel} shows a CA the example GSTIN {gstin}, which this product's own "
        f"validator refuses: {problem} (it should end {checksum_char(gstin[:14])})"
    )


def test_the_browser_authority_and_this_one_agree_on_the_fixture():
    """The fixture that already pins the two implementations still exists and
    still covers a check-digit failure — without that case the pinning is
    about the shape alone and this whole sweep could be undone silently."""
    fixture = json.loads((API / "tests" / "fixtures" / "gstin.json").read_text())
    assert fixture.get("valid"), "tests/fixtures/gstin.json holds no valid cases"
    invalid = fixture.get("invalid") or []
    assert invalid, "tests/fixtures/gstin.json holds no invalid cases"

    # A check-digit case specifically. Without one the fixture pins the two
    # implementations on the SHAPE alone, and this whole sweep — seven doors
    # moved off a shape regex precisely because the shape cannot see a
    # transposition — could be undone with the fixture still green.
    check_digit_cases = [
        c for c in invalid if "check digit" in str(c.get("fragment", "")).lower()
    ]
    assert check_digit_cases, (
        "the shared GSTIN fixture no longer exercises a check-digit failure"
    )
    for case in check_digit_cases:
        problem = problem_with(case["gstin"])
        assert problem is not None and case["fragment"] in problem, (
            f"{case['gstin']}: the authority no longer reports "
            f"{case['fragment']!r} — it said {problem!r}"
        )
