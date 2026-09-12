"""The five figures read off an invoice have to agree with each other.

WHAT WAS WRONG (PUR-21)
    `routers/document_intelligence_v1._parse_extraction_json` coerced
    `taxable_amount_paise`, `cgst_paise`, `sgst_paise`, `igst_paise` and
    `total_paise` to integers and returned them. NOTHING CHECKED THAT THEY SUM,
    and `_estimate_confidence` scored the extraction on FIELD PRESENCE alone —
    so a model that misread one digit produced five plausible numbers, scored
    "high", and pre-filled a draft bill with them.

    The screen made it worse by saying nothing: `PurchaseBillEditor` held the
    whole extraction in `aiExtracted` and rendered one sentence from it ("AI
    extracted data pre-filled below"). The header figures — the only ones a CA
    could have checked against the paper in front of them — were never shown.

WHY IT WARNS AND NEVER REFUSES
    Two legitimate reasons for a small difference: the invoice's own ROUND OFF
    line (CGST Act §170 rounds tax to the nearest rupee, so up to 50 paise
    before anybody misreads anything), and per-line paise on a multi-line bill.
    The tolerance is one rupee — above both, far below the ten a transposed
    digit costs. "Block the save when they differ", which the finding proposed,
    would stop a CA saving a correct bill.

WHERE THE RULE LIVES
    `domain/extraction_totals.py`, not the router and not the browser: the
    tolerance is a statement about §170, and CLAUDE.md keeps statutory rules in
    apps/api. The screen renders the verdict.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from domain.extraction_totals import TOLERANCE_PAISE, check_totals

_WEB = Path(__file__).resolve().parents[2] / "web"
_EDITOR = _WEB / "components" / "purchases" / "PurchaseBillEditor.tsx"


def _ex(taxable=1_00_000, cgst=9_000, sgst=9_000, igst=0, total=1_18_000):
    return {"taxable_amount_paise": taxable, "cgst_paise": cgst,
            "sgst_paise": sgst, "igst_paise": igst, "total_paise": total}


# ── the arithmetic ───────────────────────────────────────────────────────────

def test_a_bill_that_adds_up_agrees():
    out = check_totals(_ex())
    assert out["checked"] is True and out["agrees"] is True
    assert out["difference_paise"] == 0
    assert out["note"] is None


def test_an_inter_state_bill_adds_up_the_same_way():
    assert check_totals(_ex(cgst=0, sgst=0, igst=18_000))["agrees"] is True


def test_a_misread_digit_is_reported_with_the_amount():
    """1,00,000 read as 10,000 — the shape of the error this exists to catch."""
    out = check_totals(_ex(taxable=10_000))
    assert out["agrees"] is False
    assert out["difference_paise"] == -90_000
    assert "misread" in (out["note"] or "")


def test_the_invoices_own_round_off_is_within_tolerance():
    """CGST §170 rounds tax to the nearest rupee, so a printed total can be up
    to 50 paise from the sum of its parts with nothing wrong at all."""
    for off in (-50, -1, 0, 1, 50):
        assert check_totals(_ex(total=1_18_000 + off))["agrees"] is True, off


def test_the_tolerance_is_one_rupee_and_stops_there():
    assert TOLERANCE_PAISE == 100
    assert check_totals(_ex(total=1_18_000 + 100))["agrees"] is True
    assert check_totals(_ex(total=1_18_000 + 101))["agrees"] is False


def test_an_unread_total_is_not_a_disagreement():
    """A scan the model could not finish must not put a red warning on every
    field it did read."""
    out = check_totals(_ex(total=0))
    assert out["checked"] is False and out["agrees"] is True
    assert "could not be read" in (out["note"] or "")


def test_an_empty_extraction_does_not_raise():
    assert check_totals({})["checked"] is False


def test_a_string_amount_does_not_raise():
    """The coercion upstream is `int(x or 0)` inside a try — this must survive
    whatever reaches it, because it runs on a model's output."""
    out = check_totals({"taxable_amount_paise": "not a number",
                        "total_paise": 1_18_000})
    assert out["checked"] is False


# ── it reaches the response, and the confidence ──────────────────────────────

def test_confidence_is_capped_at_low_when_the_figures_disagree():
    """Field presence is not evidence of a correct reading, and it was the only
    input: five fields populated scored "high" whether or not they added up."""
    from routers.document_intelligence_v1 import _estimate_confidence
    full = {"vendor_name": "Acme", "vendor_gstin": "27CCCCC2222C1Z8",
            "invoice_no": "INV-1", "invoice_date": "2026-06-01",
            **_ex()}
    assert _estimate_confidence(full, check_totals(full)) == "high"
    bad = {**full, **_ex(taxable=10_000)}
    assert _estimate_confidence(bad, None) == "high"          # the old answer
    assert _estimate_confidence(bad, check_totals(bad)) == "low"


def test_the_endpoint_returns_the_check():
    import inspect
    from routers import document_intelligence_v1 as m
    src = inspect.getsource(m.extract_invoice)
    assert '"totals_check": totals' in src
    assert "_estimate_confidence(extracted, totals)" in src


# ── and the CA is shown the figures ─────────────────────────────────────────

@pytest.mark.skipif(not _EDITOR.is_file(), reason="needs apps/web")
def test_the_editor_shows_what_was_read_off_the_document():
    """`aiExtracted` held all five and the screen rendered one sentence from
    it. A figure the server got right and no screen shows is not a fixed bug."""
    src = _EDITOR.read_text()
    code = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    code = re.sub(r"^\s*//.*$", "", code, flags=re.M)
    for key in ("taxable_amount_paise", "cgst_paise", "sgst_paise",
                "igst_paise", "total_paise"):
        assert f'"{key}"' in code, f"the editor never renders {key}"
    assert "aiTotals" in code, "the server's verdict is not read"
    assert "totals_check" in code, "the response field is not read"


@pytest.mark.skipif(not _EDITOR.is_file(), reason="needs apps/web")
def test_the_editor_does_not_decide_the_tolerance_for_the_header_check():
    """The §170 tolerance is the server's. The screen may compare its own
    computed line total against the extracted one — that is a different
    comparison and its own threshold is fine — but it must not re-derive the
    verdict on the five header figures."""
    src = _EDITOR.read_text()
    code = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    code = re.sub(r"^\s*//.*$", "", code, flags=re.M)
    assert "aiTotals.agrees" in code, (
        "the screen decides for itself whether the header adds up instead of "
        "rendering the server's answer")
    assert "sum_of_parts_paise" not in code or "aiTotals" in code


@pytest.mark.skipif(not _EDITOR.is_file(), reason="needs apps/web")
def test_nothing_blocks_the_save_on_a_totals_disagreement():
    """A one- or two-paise difference is the CORRECT behaviour and a refusal
    would stop a CA saving a right bill. The validator must not learn about
    this."""
    from pathlib import Path as _P
    rules = (_P(__file__).resolve().parents[2] / "web" / "lib" / "purchases"
             / "billEditor.ts").read_text()
    for token in ("aiTotals", "totals_check", "extraction"):
        assert token not in rules, (
            f"billEditor.ts validation mentions {token} — the totals check "
            "warns, it never refuses")
