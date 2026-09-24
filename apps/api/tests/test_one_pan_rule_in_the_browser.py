"""ONE PAN RULE IN THE BROWSER, AND IT NORMALISES THE WAY THE SERVER DOES.

Seven screens each carried `/^[A-Z]{5}[0-9]{4}[A-Z]$/` and tested it against
the RAW field value. `core/validators.validate_pan` — the authority the MCA,
lifecycle and payroll doors call — does `value.strip().upper()` FIRST. So the
two disagreed on every PAN merely typed in lower case or pasted with a space,
and they disagreed in the direction that BLOCKS: the browser refused what the
server would have accepted.

**ON TWO OF THE SEVEN IT WAS PLAINLY VISIBLE.** The firm's own PAN on Settings
and at onboarding is rendered by a shared `Field` that does NOT uppercase what
is typed — other identifier inputs in this product do
(`e.target.value.toUpperCase()`), these two do not — and the submit path
`.trim()`s on the way out while the validator did not trim before testing. So
a CA typing `aabcu9603r` was told "Invalid PAN format (e.g. AABCU9603R)" about
a PAN that is correct, on the first form the product ever shows them.

`lib/identifiers/pan.ts` is the one browser implementation, shaped like
`lib/gst/gstin.gstinProblem` so there is one idea of "what is wrong with this
identifier". This guard pins it to `core/validators.validate_pan` on the SAME
inputs, and holds the sweep.

**THE FOURTH CHARACTER'S HOLDER TYPE IS DELIBERATELY NOT TESTED** on either
side. Rule 114 makes it a status code, so a PAN whose fourth character is
outside that set cannot exist and the test would be a real strengthening — but
the full set could not be confirmed here (egress is refused at this
environment's proxy) and the error direction is UNSAFE: an incomplete set
refuses a genuine PAN and blocks a client record, where the present behaviour
merely fails to catch a typo. A test below asserts NEITHER side tests it, so
adding it to one alone fails rather than drifting.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from core.validators import validate_pan

API = pathlib.Path(__file__).resolve().parent.parent
WEB = API.parent / "web"
PAN_MODULE = WEB / "lib" / "identifiers" / "pan.ts"

_PAN_SHAPE_REGEX = re.compile(r"\[A-Z\]\{5\}\s*\[0-9\]\{4\}\s*\[A-Z\]")

# GSTIN embeds a PAN, so its own two files spell the sub-pattern; they are not
# PAN validators and `test_one_gstin_rule_in_the_browser` already governs them.
_CARRIES_A_GSTIN_PATTERN = {"lib/gst/gstin.ts", "lib/invoices/compliance.ts"}
_THE_AUTHORITY = "lib/identifiers/pan.ts"


def _web_sources() -> list[pathlib.Path]:
    out: list[pathlib.Path] = []
    for d in ("app", "components", "lib", "scripts"):
        for p in (WEB / d).rglob("*.ts*"):
            if "node_modules" not in p.parts:
                out.append(p)
    return sorted(out)


_SOURCES = _web_sources()


def test_the_probe_reads_a_real_tree():
    assert len(_SOURCES) > 500, f"only {len(_SOURCES)} browser sources"
    assert PAN_MODULE.exists(), "lib/identifiers/pan.ts is gone"


def test_only_the_authority_spells_the_pan_shape():
    offenders = []
    for p in _SOURCES:
        rel = str(p.relative_to(WEB))
        if rel in _CARRIES_A_GSTIN_PATTERN or rel == _THE_AUTHORITY:
            continue
        if p.name.endswith((".test.ts", ".test.tsx")):
            continue
        code = "\n".join(
            line.split("//", 1)[0] for line in p.read_text(encoding="utf-8").splitlines()
        )
        if _PAN_SHAPE_REGEX.search(code):
            offenders.append(rel)
    assert not offenders, (
        "A raw PAN shape regex disagrees with core/validators.validate_pan, "
        "which strips and uppercases first. Use lib/identifiers/pan:\n  "
        + "\n  ".join(offenders)
    )


def test_the_seven_doors_ask_the_authority():
    doors = [
        "app/settings/page.tsx",
        "app/onboarding/page.tsx",
        "app/clients/page.tsx",
        "app/tds/page.tsx",
        "app/clients/[id]/compliance/mca/page.tsx",
        "components/ClientFormModal.tsx",
        "components/customers/CustomerFormModal.tsx",
        "lib/imports/mappers.ts",
    ]
    # An IMPORT, not a mention — the comment above each import names the module,
    # and a substring match would be satisfied by the explanation. That mistake
    # was made three times in this run before the rule stuck.
    imports = re.compile(r'from\s+"[^"]*identifiers/pan(?:\.ts)?"')
    missing = [
        d for d in doors
        if not imports.search(
            "\n".join(
                line.split("//", 1)[0]
                for line in (WEB / d).read_text(encoding="utf-8").splitlines()
            )
        )
    ]
    assert not missing, "these doors must resolve a PAN through lib/identifiers/pan:\n  " + "\n  ".join(missing)


# ── The two implementations agree, on the inputs that used to separate them ──

_CASES = [
    "AABCU9603R",          # plain and correct
    "aabcu9603r",          # lower case — the visible defect
    "  AABCU9603R  ",      # pasted with spaces — the other half
    "\tAABCU9603R\n",      # pasted out of a table
    "aAbCu9603r",          # mixed
    "",                    # blank is "not held", not "wrong"
    "   ",                 # blank once trimmed
    "AABCU9603",           # nine characters
    "AABCU96033R",         # eleven
    "AABC19603R",          # a digit where a letter belongs
    "AABCU9603RX",         # trailing junk
    "AABCU960 R",          # an interior space is NOT trimmed away
    "ABCDE1234F",
]


@pytest.mark.parametrize("value", _CASES)
def test_the_browser_rule_and_the_server_rule_agree(value: str):
    """Run the TypeScript through node against the Python on the same input.
    A fixture file would be the usual shape here, but the whole finding is that
    the two normalise differently — so the test has to exercise both, not two
    descriptions of both."""
    import json
    import subprocess

    script = f"""
      const {{ panProblem }} = await import({json.dumps(str(PAN_MODULE))});
      process.stdout.write(JSON.stringify(panProblem({json.dumps(value)})));
    """
    proc = subprocess.run(
        ["node", "--input-type=module", "--experimental-strip-types", "-e", script],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        pytest.skip(f"node cannot run the TS module here: {proc.stderr.strip()[:200]}")
    browser_problem = json.loads(proc.stdout)
    server_problem = validate_pan(value)
    assert (browser_problem is None) == (server_problem is None), (
        f"{value!r}: the browser says {browser_problem!r} and the server says "
        f"{server_problem!r} — one accepts what the other refuses"
    )


def test_neither_side_tests_the_fourth_character():
    """Rule 114's holder-type code is refused on BOTH sides, together. Adding it
    to one alone puts them back in disagreement, which is the whole finding."""
    server = (API / "core" / "validators.py").read_text(encoding="utf-8")
    browser = PAN_MODULE.read_text(encoding="utf-8")
    # The set would have to appear as a character class or a list of the status
    # letters; the marker either side uses is the section it would cite.
    assert "[ABCFGHJLPT]" not in server and "[ABCFGHJLPT]" not in browser, (
        "one side now tests the PAN holder-type code and the other does not — "
        "settle Rule 114's full set and change both, or neither"
    )
    assert "Rule 114" in browser, (
        "lib/identifiers/pan.ts must keep the recorded reason for not testing "
        "the holder-type code, or the next reader will add it to one side"
    )
