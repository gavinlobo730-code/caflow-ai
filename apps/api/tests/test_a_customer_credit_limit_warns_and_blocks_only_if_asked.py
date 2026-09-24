"""
A customer's credit limit — SALES-25 (b), migration 414.

WHAT IS ASSERTED
    1. `None` IS NOT ZERO. An unrecorded limit offers no opinion and blocks
       nothing; a recorded ZERO is a real limit meaning cash only. Reading the
       first as the second would put every customer in the database on the
       strictest possible terms the day this landed.
    2. It WARNS by default and BLOCKS only where the firm asked. A block stops
       a CA recording a supply that has already happened.
    3. An OPENING document is never blocked, whatever the switch says, and the
       answer SAYS it was not — ACC-14's reasoning, on the very documents that
       push a customer past a limit somebody has just typed in.
    4. NOTHING HERE IS STATUTORY, asserted on the module: it sits in
       `domain/sales/` beside `line_tax` and `order_cycle`, which are, and a
       later reader will go looking for the section.
    5. The exposure is the GENERATED `outstanding_paise` column and is never
       re-derived from `total - paid`, which omits the CGST s.34 note terms.
"""
from __future__ import annotations

import pathlib
import re

import pytest
from pydantic import ValidationError

from domain.sales import credit_limit as cl
from models.parties import CustomerIn, CustomerUpdateIn

LAKH = 1_00_000_00   # Rs 1,00,000 in paise


# ── 1. three states, and None is not zero ───────────────────────────────────

def test_an_unrecorded_limit_offers_no_opinion():
    a = cl.assess(limit_paise=None, outstanding_paise=50 * LAKH,
                  invoice_paise=50 * LAKH, firm_blocks=True)
    assert a.state == cl.NOT_SET
    assert a.blocks is False and a.message is None
    # The figures are still reported: a screen showing "nothing recorded" beside
    # what the customer owes is more useful than one showing neither.
    assert a.exposure_paise == 100 * LAKH


def test_zero_is_a_real_limit_and_means_cash_only():
    a = cl.assess(limit_paise=0, outstanding_paise=0, invoice_paise=1,
                  firm_blocks=True)
    assert a.state == cl.WOULD_EXCEED and a.blocks is True
    assert a.excess_paise == 1


def test_within_the_limit_says_nothing():
    a = cl.assess(limit_paise=LAKH, outstanding_paise=60_000_00,
                  invoice_paise=40_000_00, firm_blocks=True)
    assert a.state == cl.WITHIN and a.blocks is False and a.message is None
    assert a.excess_paise == 0


def test_exactly_at_the_limit_is_within_it():
    """`<=`, not `<`. A limit of a lakh permits a lakh — the other reading
    refuses the very invoice the CA set the limit to allow."""
    a = cl.assess(limit_paise=LAKH, outstanding_paise=0, invoice_paise=LAKH)
    assert a.state == cl.WITHIN


# ── 2. warn by default, block only if asked ─────────────────────────────────

def test_it_warns_by_default_and_does_not_block():
    a = cl.assess(limit_paise=LAKH, outstanding_paise=80_000_00,
                  invoice_paise=50_000_00)
    assert a.state == cl.WOULD_EXCEED
    assert a.blocks is False, (
        "blocking is the firm's opt-in. A block stops a CA recording a supply "
        "that has already happened, and a supply that cannot be recorded here "
        "gets recorded somewhere this product cannot see")
    assert a.message


def test_the_firm_can_ask_for_a_refusal():
    a = cl.assess(limit_paise=LAKH, outstanding_paise=80_000_00,
                  invoice_paise=50_000_00, firm_blocks=True)
    assert a.blocks is True


def test_the_message_names_every_figure_the_ca_needs():
    """"Over the credit limit" alone sends the CA to look four numbers up, and
    the one they most need — what is ALREADY open — is on no screen here."""
    a = cl.assess(limit_paise=LAKH, outstanding_paise=80_000_00,
                  invoice_paise=50_000_00)
    for figure in ("1,30,000", "1,00,000", "30,000", "80,000"):
        assert figure in a.message, f"{figure} missing from {a.message!r}"


# ── 3. an opening document is never blocked ─────────────────────────────────

def test_an_opening_document_is_never_blocked():
    a = cl.assess(limit_paise=LAKH, outstanding_paise=80_000_00,
                  invoice_paise=50_000_00, firm_blocks=True, is_opening=True)
    assert a.state == cl.WOULD_EXCEED
    assert a.blocks is False, (
        "an opening document records a balance the client arrived with; "
        "refusing one would make a migration impossible for the clients who "
        "most need one (ACC-14)")
    assert "opening document" in a.message, (
        "a warning that does not say it was NOT blocked reads to a firm that "
        "switched blocking on as though the switch had failed")


# ── 4. nothing here is statutory, and the module says so ────────────────────

def _module_source() -> str:
    return (pathlib.Path(__file__).resolve().parents[1]
            / "domain/sales/credit_limit.py").read_text()


def test_the_module_says_it_is_not_a_statutory_rule():
    assert "commercial term" in cl.NOT_A_STATUTORY_RULE
    # Carried on every answer that has one, so the sentence reaches the CA and
    # not only the next programmer.
    a = cl.assess(limit_paise=0, outstanding_paise=0, invoice_paise=1)
    assert cl.NOT_A_STATUTORY_RULE in a.message


def test_no_act_or_rule_is_cited_as_the_source_of_the_limit():
    """It sits beside `line_tax` and `order_cycle`, which ARE statutory, so a
    reader will look for the section. There is not one, and inventing a
    citation is how a commercial term comes to look like a legal requirement."""
    src = _module_source()
    # ACC-14 and CGST s.31 are referenced in prose as REASONS for the opening
    # carve-out; what must not appear is a section presented as the source of
    # the limit itself.
    for claim in (r"under\s+s\.?\s*\d+", r"prescribed by", r"the Act requires"):
        assert not re.search(claim, src, re.I), claim


# ── 5. the exposure is the generated column ─────────────────────────────────

def test_the_service_reads_outstanding_and_never_re_derives_it():
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "services/customer_credit_service.py").read_text()
    body = re.sub(r'"""[\s\S]*?"""', "", src)
    assert '"outstanding_paise"' in body
    for column in ("total_paise", "paid_paise", "credited_paise",
                   "debit_note_paise"):
        assert column not in body, (
            f"{column} is re-subtracted here. Migration 278 made "
            "outstanding_paise GENERATED so the formula lives once, in the "
            "schema — it carries the CGST s.34 note terms that total - paid "
            "omits")


# ── 6. both doors refuse a negative ─────────────────────────────────────────

@pytest.mark.parametrize("model,kwargs", [
    (CustomerIn, {"client_id": "c", "name": "n"}),
    (CustomerUpdateIn, {}),
])
def test_a_negative_limit_is_refused_at_both_doors(model, kwargs):
    """The DB CHECK refuses it; mock mode has no CHECK, so without this the two
    disagree and a test written in mock mode passes against a request
    production rejects. BOTH doors, because a validator on the create door
    alone is one PATCH from being none."""
    assert model(**kwargs, credit_limit_paise=0).credit_limit_paise == 0
    with pytest.raises(ValidationError):
        model(**kwargs, credit_limit_paise=-1)
