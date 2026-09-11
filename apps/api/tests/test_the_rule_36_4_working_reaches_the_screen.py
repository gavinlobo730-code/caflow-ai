"""The Rule 36(4) working was computed, returned, and rendered by nothing.

CGST Rule 36(4) caps a client's input tax credit at what their suppliers have
actually filed, and s.16(2)(aa) makes that decisive rather than advisory: credit
is available only where "the details of the invoice ... has been furnished by
the supplier ... and such details have been communicated to the recipient".

`domain/gst/gstr3b_computer` has applied the cap since it was written.
`services/gst_return_service.gstr3b_from_books` returns the whole working —
the book figure, the 2A figure, whether the cap fired, whether anything was
compared at all, and the self-assessed reverse-charge tax that sits outside the
cap. Ten fields.

THE BROWSER READ NONE OF THEM. `GSTR3BWorking` in apps/web/lib/data/gst.ts did
not even declare a `rule_36_4` block, so a CA whose claim had been trimmed saw
the trimmed figure and no statement that anything had been withheld, by how
much, or why. On the credit side of a return that is the difference between a
claim that survives an ASMT-10 and one that does not.

THE GUARD IS WRITTEN FROM THE BACKEND SIDE deliberately. apps/api owns this
vocabulary; a test in apps/web would assert the screen against a copy of
itself and pass whenever both drifted together — which is precisely what the
Schedule III caption list did for months.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = API_ROOT.parents[1] / "apps" / "web"
TYPES = WEB_ROOT / "lib" / "data" / "gst.ts"
PAGE = WEB_ROOT / "app" / "gst" / "gstr3b" / "page.tsx"


def _served_keys() -> list[str]:
    """The keys the service actually puts in the `rule_36_4` block.

    Read from the SOURCE with `ast` rather than from a literal list here — a
    list here would be a third copy of the vocabulary, free to drift from both
    the service and the screen, which is the defect this guards."""
    tree = ast.parse((API_ROOT / "services" / "gst_return_service.py").read_text())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if (isinstance(key, ast.Constant) and key.value == "rule_36_4"
                    and isinstance(value, ast.Dict)):
                return [k.value for k in value.keys
                        if isinstance(k, ast.Constant) and isinstance(k.value, str)]
    raise AssertionError(
        "no `rule_36_4` dict literal in services/gst_return_service.py — the "
        "working the screen renders is no longer served under that name")


def test_the_service_still_serves_the_whole_working():
    """Named individually, because each answers a question the others cannot.
    `cap_applied` says the cap bit; `compared` says whether there was anything
    to compare it against — and a book figure equal to the 2A and a book figure
    with no 2A on file both show 'no cap applied' while meaning opposite
    things."""
    keys = set(_served_keys())
    assert {"cap_applied", "compared", "gstr2a_record_count"} <= keys, sorted(keys)
    assert {"gstr2a_igst_paise", "gstr2a_cgst_paise", "gstr2a_sgst_paise"} <= keys
    assert {"self_assessed_igst_paise", "self_assessed_cgst_paise",
            "self_assessed_sgst_paise"} <= keys


def test_every_served_field_is_declared_in_the_browser_type():
    """The rule, not a spelling of it: whatever the service sends under
    `rule_36_4`, the browser's own type has to declare — otherwise a field can
    be added in apps/api and be invisible in the product with nothing failing."""
    src = TYPES.read_text()
    assert "rule_36_4" in src, (
        "apps/web/lib/data/gst.ts declares no `rule_36_4` block, so the whole "
        "Rule 36(4) working is computed and thrown away at the wire")
    missing = [k for k in _served_keys() if k not in src]
    assert not missing, (
        f"served by gst_return_service and not declared in the browser type: "
        f"{missing}. A CA cannot see a figure the type does not carry.")


def test_the_screen_renders_the_cap_and_says_which_kind_of_uncapped():
    """Three states, and the third is the one that is easy to omit. Capped;
    compared and clean; and NOT COMPARED — no GSTR-2B on file — which looks
    identical to 'clean' in every figure and means something else entirely.

    ASSERTED ON THE FIELD ACCESS, not on the word. A bare `"compared" in src`
    passes on the sentence "nothing was compared" in the panel's own prose —
    which it did, on this test's first negative control: stubbing the branch
    out left the guard green. A guard whose subject is code has to be given
    code, and `w.rule_36_4.compared` is an expression no comment contains."""
    src = PAGE.read_text()
    # JSX comments stripped anyway, so a `{/* … */}` block cannot satisfy
    # anything below either.
    code = re.sub(r"\{/\*[\s\S]*?\*/\}", "", src)

    assert "w.rule_36_4" in code, (
        "the GSTR-3B screen renders no Rule 36(4) working at all — a trimmed "
        "claim is shown trimmed, with no statement that it was trimmed")
    assert "w.rule_36_4.cap_applied" in code, (
        "the screen never reads whether the cap fired")
    assert "w.rule_36_4.compared" in code, (
        "the screen reads `cap_applied` but not `compared`, so a period with "
        "no GSTR-2B uploaded is presented exactly like one where the books and "
        "the portal agree — the figures are identical and the meanings are "
        "opposite")
    for head in ("igst", "cgst", "sgst"):
        assert f"w.rule_36_4.self_assessed_{head}_paise" in code, (
            f"the self-assessed {head.upper()} is not rendered. Reverse-charge "
            f"tax is outside the Rule 36(4) cap — it is self-assessed on the "
            f"recipient's own s.31(3)(f) invoice, so no supplier furnishes it "
            f"and GSTR-2B cannot carry it. Without that row the screen shows a "
            f"book total above the 2A with no cap applied and no explanation")
        assert f"w.rule_36_4.gstr2a_{head}_paise" in code, (
            f"the GSTR-2B {head.upper()} figure is not shown, so the CA is "
            f"told the claim was trimmed without being told to what")
