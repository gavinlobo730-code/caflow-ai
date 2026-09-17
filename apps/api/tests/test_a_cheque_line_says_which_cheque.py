"""A cheque has no UTR, so the leaf number is the only thing that names it (BANK-28).

WHAT WAS WRONG

`domain/banking/narration.ParsedNarration` has carried `cheque_no` since the
module was written, `_RE_CHEQUE_AFTER` / `_RE_CHEQUE_BEFORE` populate it, and
`describe()` puts "Cheque 004521" in the one-line summary. None of that reached
a screen:

  * both services built the `parsed` payload as a DICT LITERAL — one in
    `bank_entry_service._annotate`, one in `bank_matching_service` — and both
    omitted the key, so the browser never saw it;
  * `EntryDetailModal` showed a UTR, a reference, a VPA and an IFSC, and a
    cheque line has none of the four, so it printed the bank narration with
    NOTHING beneath it;
  * `match_and_settle_multi` fell back from a caller's reference to
    `bank_transactions.reference_no`, which comes from a COLUMN in the uploaded
    file. Plenty of Indian statements have no such column, only a narration, so
    a cheque settled from the queue carried no reference at all — while the leaf
    number sat parsed out of that very narration.

THE FIX IS ONE BUILDER, NOT TWO KEYS. `narration.parsed_view` is what both
services call now: adding `cheque_no` to two literals would have left a third
place for the next field to be forgotten, which is how this one was.

THE ORDER OF THE SETTLEMENT REFERENCE IS THE RULE. What the CALLER said, then
what the FILE said, then what the BANK PRINTED. A parse is a reading of somebody
else's document and must never displace an answer a person or the statement
gave.
"""
import inspect

import pytest

from domain.banking import parse_narration, parsed_view


def test_the_view_carries_every_field_the_parse_found():
    v = parsed_view(parse_narration("CHQ NO 004521 RAMESH KUMAR"))
    assert v["cheque_no"] == "004521"
    assert "Cheque 004521" in v["summary"]
    # The whole record, so a field added to ParsedNarration is either carried
    # here or deliberately left out — not silently dropped.
    assert set(v) == {"channel", "utr", "vpa", "counterparty", "ifsc",
                      "cheque_no", "summary"}


def test_a_line_with_no_cheque_answers_none_rather_than_omitting_the_key():
    """A screen must be able to tell "no cheque number" from "this build does
    not report one"."""
    v = parsed_view(parse_narration("UPI/412345678901/RAMESH/okhdfc"))
    assert "cheque_no" in v and v["cheque_no"] is None


@pytest.mark.parametrize("module,attr", [
    ("services.bank_entry_service", "BankEntryService"),
    ("services.bank_matching_service", None),
])
def test_neither_service_builds_the_view_itself(module, attr):
    import importlib
    src = inspect.getsource(importlib.import_module(module))
    assert "parsed_view(" in src, f"{module} stopped using the one builder"
    # The literal that was there. Both copies omitted cheque_no; a third copy
    # would omit whatever comes next.
    assert '"counterparty": n.counterparty' not in src, (
        f"{module} is building the parsed payload by hand again — "
        "domain/banking/narration.parsed_view is the one builder.")


# ── the settlement reference ────────────────────────────────────────────────

def _settle_source() -> str:
    import services.bank_posting_service as m
    return inspect.getsource(m.BankPostingService.match_and_settle_multi)


def test_the_settlement_reference_prefers_what_a_person_said():
    src = _settle_source()
    assert "reference_no or txn.get(\"reference_no\")" in src, (
        "the caller's own reference and the statement's own column must come "
        "FIRST — a parse is a reading and never displaces an answer.")
    assert "_n.utr or _n.cheque_no" in src, (
        "a cheque settled from the queue still carries no reference where the "
        "uploaded file had no reference column.")


def test_the_settlement_reference_is_one_value_for_both_documents():
    """A receipt and a payment, or the same statement line settles with a
    reference against a bill and without one against an invoice."""
    assert _settle_source().count('"reference_no": settle_ref') == 2


@pytest.mark.parametrize("screen", [
    "components/banking/EntryDetailModal.tsx",
    "components/banking/EntriesTab.tsx",
])
def test_the_screen_shows_the_cheque_number(screen):
    import pathlib
    web = pathlib.Path(__file__).resolve().parents[2] / "web"
    path = web / screen
    if not path.exists():
        pytest.skip("apps/web not present")
    body = path.read_text()
    assert "cheque_no" in body, (
        f"{screen} renders a bank line's identifiers and not the one a cheque "
        "actually has. Read from the PYTHON side deliberately: a guard in "
        "apps/web asserting the browser against a copy of itself passes "
        "whenever both drift together.")
