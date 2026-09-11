"""No PDF this product produces contains U+20B9, because it cannot render it.

WHAT GOES WRONG

ReportLab's core fonts — Helvetica and its siblings — use WinAnsiEncoding, which
has no glyph for the Indian Rupee sign. A ₹ passed into a PDF does not fall back
to "Rs."; it renders as a black box:

    'PAYSLIP  Net Pay: ■1,234.56'
    'STATEMENT Invoiced: ■1,000.00'

WHY THIS IS A TEST AND NOT A COMMENT

**It shipped twice.** The fee invoice and the customer statement were found on
8 September; the audit the next day found the same defect still live in
`payslip_pdf_service` (₹×5), `statement_pdf_service` (₹×3) and
`year_end_pdf_service` (₹×7) — and recorded that the tranche in between had
EDITED one of the affected files without noticing. Two services had already
solved it and their comments said why; nothing carried the rule across.

The documents are the ones that leave the firm. A payslip is handed to an
EMPLOYEE, a statement to the client's CUSTOMER, and the year-end schedules go
into a signed set.

THE RULE, AND THE ONE PLACE ₹ IS ALLOWED

No string a PDF service can put on a page may contain U+20B9. The sign may
appear only as the SUBJECT OF ITS OWN REMOVAL — `.replace("₹", "Rs. ")`, which
is `engagement_pdf_service`'s fix for HTML that legitimately carries it (email
renders ₹ correctly; only the PDF cannot).

Comments and docstrings are stripped before the scan. They are where the reason
is written down — this file's own header quotes the very character it bans —
and prose cannot reach a page.
"""
from __future__ import annotations

import pathlib
import re

SERVICES = pathlib.Path(__file__).resolve().parents[1] / "services"
RUPEE = "\u20b9"

#: The only legal form: a replacement that REMOVES the sign. Matched on the
#: operation rather than on a file name, so a second service that needs to strip
#: ₹ out of user-supplied HTML does not have to be added to an exemption list.
_STRIPS_IT = re.compile(
    r"""\.replace\(\s*(['"])""" + RUPEE + r"""\1\s*,\s*(['"])(?!.*""" + RUPEE + r""").*?\2\s*\)""")


def _pdf_services() -> list[pathlib.Path]:
    return sorted(SERVICES.glob("*pdf*.py"))


def _code(path: pathlib.Path) -> str:
    """Source with docstrings and comments removed — prose cannot reach a page."""
    src = path.read_text()
    src = re.sub(r'"""[\s\S]*?"""', "", src)
    src = re.sub(r"'''[\s\S]*?'''", "", src)
    return re.sub(r"^\s*#.*$", "", src, flags=re.M)


def test_the_scan_still_finds_the_pdf_services():
    """A glob that quietly matched nothing would pass every test below."""
    found = _pdf_services()
    assert len(found) >= 5, f"expected the PDF services, found {[p.name for p in found]}"
    names = {p.name for p in found}
    for expected in ("payslip_pdf_service.py", "statement_pdf_service.py",
                     "year_end_pdf_service.py", "invoice_pdf_service.py"):
        assert expected in names, f"{expected} is one of the four this rule was written for"


def test_no_pdf_service_puts_the_rupee_sign_on_a_page():
    offenders = []
    for path in _pdf_services():
        code = _STRIPS_IT.sub("", _code(path))
        if RUPEE in code:
            lines = [ln.strip()[:90] for ln in code.split("\n") if RUPEE in ln]
            offenders.append(f"{path.name}: {lines}")

    assert not offenders, (
        "ReportLab's core fonts are WinAnsiEncoding and have no glyph for the "
        "Indian Rupee sign — these render as a black box on a document that "
        "leaves the firm:\n  " + "\n  ".join(offenders)
        + "\n\nWrite 'Rs.' instead, or strip it with .replace(\"\\u20b9\", \"Rs. \") "
          "as engagement_pdf_service does for HTML it did not author.")


def test_the_one_legal_form_is_still_recognised():
    """The exemption is an OPERATION, not a file name.

    If this stopped matching, engagement_pdf_service's fix would read as a
    violation and the next person would 'fix' it by deleting the replacement —
    putting the black box back on the page.
    """
    assert _STRIPS_IT.search('return (html or "").replace("\u20b9", "Rs. ")'), (
        "engagement_pdf_service's actual line must be recognised as the fix")
    assert _STRIPS_IT.search("x.replace('\u20b9', 'Rs.')"), "single quotes too"
    # And a replacement that keeps the sign is NOT the fix.
    assert not _STRIPS_IT.search('x.replace("\u20b9", "\u20b9 ")'), (
        "replacing the sign with itself is not a removal")


def test_rs_is_what_the_services_actually_write():
    """Not just an absence — the positive form has to be there, or a service
    that had simply stopped printing any currency marker would pass."""
    for name in ("payslip_pdf_service.py", "statement_pdf_service.py"):
        code = _code(SERVICES / name)
        assert "Rs." in code, f"{name} should spell the currency as Rs."


def test_html_this_product_did_not_author_still_has_the_sign_stripped():
    """A POSITIVE requirement, because its absence is invisible to the scan above.

    engagement_pdf_service renders an engagement letter's stored HTML, and that
    HTML is not ours — a CA writing "fees of ₹25,000" into a template is doing
    the right thing, and the same body goes out by email, where ₹ renders
    correctly. Only the PDF cannot.

    Deleting `.replace("\u20b9", "Rs. ")` therefore puts a black box back on a
    signed engagement letter, and leaves NO ₹ in the module's code for the scan
    above to find — it passes clean. This mutation was run and did exactly that,
    which is why this test exists.
    """
    code = _code(SERVICES / "engagement_pdf_service.py")
    assert _STRIPS_IT.search(code), (
        "engagement_pdf_service renders HTML this product did not author, so it "
        "must strip \u20b9 before ReportLab sees it. Without the replacement a "
        "CA who types the rupee sign into a template gets a black box on the "
        "signed letter, and no test above can see it, because the sign never "
        "appears in our own source.")
