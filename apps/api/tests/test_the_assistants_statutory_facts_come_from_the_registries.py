"""The assistant's statutory facts are generated from the registries, for the
year it is NOW, and name both Acts (ai-19).

WHAT WAS WRONG
    Only the TDS block of the prompt was generated. The slabs, the §87A rebate,
    the surcharge ladder, the e-invoice threshold and the GST registration
    thresholds were typed text for FY 2025-26; the prompt was a module-level
    string built ONCE at import, so a process that stayed up across 1 April kept
    briefing the model for a year that had ended; and neither the assistant nor
    the copilot prompt knew that the Income-tax Act 2025 took over the TDS
    vocabulary on 01-04-2026. For a payment on 15 May 2026 the chat cited the
    1961 section, which that Act's successor does not contain, while
    `domain/tds/vocabulary` held the whole mapping and the product's own 26Q
    already used it.

WHAT THESE ASSERT
    A change to a registry changes the prompt with NO other edit — each block is
    tested by moving its registry and reading the prompt, which is the only way to
    show a block is derived rather than retyped. The clock is moved the same way.
    `tests/test_system_prompts_agree_with_the_code.py` carries the older checks
    (the Q4 date, the TDS thresholds); this file carries the new ones.
"""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import date

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import core.ist_clock as clock
from core.auth import get_current_user
from domain.ai import groq_text, statutory_brief as sb
from domain.gst import irn_scope
from domain.income_tax import statutory_rates as sr
from domain.tds import section_rates
from domain.tds import vocabulary as vocab
from routers import assistant

TODAY = date(2026, 10, 1)          # FY 2026-27, a 2025-Act period


def _prompt(today: date = TODAY) -> str:
    return assistant.build_system_prompt(today)


# ── the income-tax block is the registry ─────────────────────────────────────

def test_the_slab_block_reads_exactly_as_the_registry_says():
    p = _prompt()
    assert ("- New Tax Regime (default): 0-4L Nil, 4L-8L 5%, 8L-12L 10%, 12L-16L 15%, "
            "16L-20L 20%, 20L-24L 25%, above 24L 30%") in p
    assert "- Old Tax Regime slabs (below 60): 0-2.5L Nil, 2.5L-5L 5%, 5L-10L 20%, above 10L 30%" in p
    assert "- Old Tax Regime slabs (60 to 79): 0-3L Nil, 3L-5L 5%, 5L-10L 20%, above 10L 30%" in p
    assert "- Old Tax Regime slabs (80 and above): 0-5L Nil, 5L-10L 20%, above 10L 30%" in p
    assert "- Surcharge: 10% (50L-1Cr), 15% (1Cr-2Cr), 25% (2Cr-5Cr), 37% (above 5Cr)" in p
    assert "capped at 25% under the new regime" in p
    assert "- Health & Education Cess: 4% on tax plus surcharge" in p
    assert "no tax payable if total income <= Rs 12,00,000, capped at Rs 60,000" in p
    assert "Standard deduction for salaried: Rs 75,000 under the new regime, Rs 50,000 under the old" in p
    assert "no marginal relief" in p, "the old regime's rebate is a hard cliff and must say so"


def test_moving_the_registry_moves_the_prompt_with_no_other_edit(monkeypatch):
    """The regression that matters: a figure typed into the prose passes on the day
    it is written and drifts the first time the Finance Act moves it."""
    real = sr.RATES_BY_FY[sr.LATEST_VERIFIED_FY]
    moved = replace(
        real,
        new_regime_rebate=replace(real.new_regime_rebate, threshold_paise=15_00_000_00),
        new_regime_slabs=(sr.SlabBracket(5_00_000_00, 0), sr.SlabBracket(None, 35)),
        cess_percent=5,
    )
    monkeypatch.setitem(sr.RATES_BY_FY, sr.LATEST_VERIFIED_FY, moved)
    p = _prompt()
    assert "no tax payable if total income <= Rs 15,00,000" in p
    assert "New Tax Regime (default): 0-5L Nil, above 5L 35%" in p
    assert "Cess: 5% on tax plus surcharge" in p
    assert "Rs 12,00,000" not in p, "the old figure survived somewhere in the prose"


def test_the_table_is_headed_with_the_verified_year_and_the_current_one_is_named_with_its_gap():
    p = _prompt()
    heading = next(ln for ln in p.splitlines() if ln.startswith("INCOME TAX RATES"))
    assert f"verified for FY {sr.LATEST_VERIFIED_FY} / AY 2026-27" in heading
    assert "Finance Act 2025" in heading
    status = next(ln for ln in p.splitlines() if ln.startswith("STATUS OF THE CURRENT YEAR"))
    assert "FY 2026-27" in status and sr.fy_rate_gap("2026-27") in status


def test_a_year_the_registry_does_not_hold_says_so_in_the_registrys_words():
    p = _prompt(date(2031, 6, 1))
    assert "STATUS OF THE CURRENT YEAR (FY 2031-32)" in p
    assert sr.fy_rate_gap("2031-32") in p, "the substitution sentence is not in the prompt"
    assert section_rates.fy_rate_gap("2031-32") in p
    assert "TDS, FY 2031-32" in p


def test_a_verified_year_carries_no_gap_sentence(monkeypatch):
    verified = replace(sr.RATES_BY_FY["2026-27"], verified=True)
    monkeypatch.setitem(sr.RATES_BY_FY, "2026-27", verified)
    monkeypatch.setattr(sr, "LATEST_VERIFIED_FY", "2026-27")
    p = _prompt()
    assert "verified for FY 2026-27 / AY 2027-28" in p
    assert "Finance Act 2026" in p
    assert "carried forward" not in p.split("INCOME TAX RATES")[1].split("INCOME-TAX ACT 1961")[0]
    assert "has verified them against its Finance Act" in p


# ── the clock, not a constant ────────────────────────────────────────────────

def test_the_prompt_is_built_per_request_and_not_at_import(monkeypatch):
    """`SYSTEM_PROMPT` is a computed attribute: reading it twice across a financial
    year boundary gives two different prompts, which a string built at import
    cannot."""
    monkeypatch.setattr(clock, "ist_today", lambda: date(2027, 3, 31))
    before = assistant.SYSTEM_PROMPT
    monkeypatch.setattr(clock, "ist_today", lambda: date(2027, 4, 1))
    after = assistant.SYSTEM_PROMPT
    assert "TDS, FY 2026-27" in before and "TDS, FY 2027-28" in after
    assert before != after


def test_the_handler_builds_the_prompt_at_request_time_and_does_not_read_a_frozen_one():
    """Asked of the CODE, not its text: the handler's own comments name the old
    constant (they explain why it is not used), and a substring test would fail
    on the explanation."""
    import ast
    import inspect
    import textwrap
    tree = ast.parse(textwrap.dedent(inspect.getsource(assistant.assistant)))
    called = {n.func.id for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    read = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | \
           {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "build_system_prompt" in called
    assert "SYSTEM_PROMPT" not in read


# ── both Acts ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind", vocab.STATEMENT_KINDS)
def test_every_statement_form_is_given_under_both_acts(kind):
    old = vocab.statement_form(kind, fy_label="2025-26")
    new = vocab.statement_form(kind, fy_label="2026-27")
    assert f"Form {old} -> Form {new}" in _prompt()


@pytest.mark.parametrize("kind", vocab.CERTIFICATE_KINDS)
def test_every_certificate_form_is_given_under_both_acts(kind):
    old = vocab.certificate_form(kind, fy_label="2025-26")
    new = vocab.certificate_form(kind, fy_label="2026-27")
    assert f"Form {old} -> Form {new}" in _prompt()


@pytest.mark.parametrize("section", ["192", "194C", "194J", "195", "206C"])
def test_a_section_is_given_under_both_numberings(section):
    new = vocab.section_code(section, fy_label="2026-27")
    assert f"s.{section} -> s.{new}" in _prompt()


def test_the_event_rule_and_the_refusals_are_stated():
    p = _prompt()
    assert "01-04-2026" in p
    assert "whichever is EARLIER" in p and "never by the date of filing" in p
    assert "s.393(1) has NO single 1961 equivalent" in p
    assert vocab.payment_code_gap().note in p, "the payment-code position is the vocabulary's own"
    assert "ITR-1 to ITR-7 were not renumbered" in p
    assert "does not hold how" in p, "non-TDS 2025-Act sections must be refused, not guessed"
    assert "falls under the Income-tax Act, 2025" in p


def test_the_copilot_prompts_name_both_acts_too():
    from domain.ai_copilot_service import _system_prompt
    p = _system_prompt()
    assert "Income-tax Act 2025" in p and "Income-tax Act 1961" in p
    assert f"Form {vocab.statement_form('resident_non_salary', fy_label='2025-26')} -> Form " \
           f"{vocab.statement_form('resident_non_salary', fy_label='2026-27')}" in p
    assert sr.fy_rate_gap(clock.ist_fy_label()) in p, "the copilot carries no rate table and must not imply one"
    # The Q4 pin of the older test still holds with the new text appended.
    assert "31 MAY" in p and "30 April" in p


def test_the_firm_copilot_route_appends_the_same_brief():
    import inspect
    from routers import ai_copilot
    src = inspect.getsource(ai_copilot.copilot_chat)
    assert "act_transition_block()" in src and "rates_status_line()" in src


# ── a question that names a date ─────────────────────────────────────────────

def test_a_payment_dated_15_may_2026_gets_both_numberings():
    brief = sb.event_brief("What TDS applies to a contractor payment dated 15 May 2026?")
    assert brief
    assert "Income-tax Act 2025 governs" in brief
    assert "s.393(1) (1961: s.194C, s.194J, s.194H)" in brief
    assert "s.392 (1961: s.192)" in brief
    assert "s.393(2) (1961: s.195)" in brief
    assert "Form 140 (1961: 26Q)" in brief
    assert "credited or paid (whichever is earlier)" in brief, "a date in a question is not always the event"


def test_a_payment_before_commencement_keeps_the_1961_labels():
    brief = sb.event_brief("TDS on rent paid on 15/01/2026")
    assert "BEFORE 01-04-2026" in brief and "do not substitute the 2025-Act numbering" in brief
    assert "393" not in brief


def test_the_earlier_of_two_dates_decides():
    """Credit and payment: whichever is earlier is the event."""
    brief = sb.event_brief("credited on 25 March 2026 and paid on 10 April 2026")
    assert "BEFORE 01-04-2026" in brief and "25 March 2026" in brief


@pytest.mark.parametrize("text,expected", [
    ("paid on 15 May 2026", date(2026, 5, 15)),
    ("paid on 15th May, 2026", date(2026, 5, 15)),
    ("paid on 3 Sept 2026", date(2026, 9, 3)),
    ("paid on 15-05-2026", date(2026, 5, 15)),
    ("paid on 15/05/2026", date(2026, 5, 15)),
    ("paid on 2026-05-15", date(2026, 5, 15)),
])
def test_the_date_forms_a_ca_types(text, expected):
    assert sb._dates_in(text) == [expected]


def test_a_question_with_no_date_or_an_impossible_one_adds_nothing():
    assert sb.event_brief("When is GSTR-1 due?") is None
    assert sb.event_brief("") is None
    assert sb.event_brief("on 31 February 2026") is None
    assert sb.event_brief("FY 2026-27 and AY 2027-28") is None, "a year label is not a date"


# ── the handler end to end ───────────────────────────────────────────────────

_real_chat = groq_text.chat
PARTNER = {"id": "u-1", "auth_user_id": "a-1", "firm_id": "firm-1",
           "email": "p@f.test", "role": "Partner"}


@pytest.fixture
def ask(monkeypatch):
    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "Answer.\nSource: Income-tax Act, Section 393"}}],
            "usage": {"total_tokens": 5}})

    transport = httpx.MockTransport(handler)

    # The REAL `groq_text.chat` runs (so redaction and the payload are the production
    # ones) against a stand-in Groq: `chat` takes the transport for exactly this.
    async def chat_against_the_stand_in(messages, **kw):
        return await _real_chat(messages, transport=transport, **kw)

    monkeypatch.setattr(groq_text, "chat", chat_against_the_stand_in)
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    app = FastAPI()
    app.include_router(assistant.router)
    app.dependency_overrides[get_current_user] = lambda: PARTNER
    client = TestClient(app, raise_server_exceptions=False)

    def _ask(question: str) -> list[dict]:
        r = client.post("/api/assistant", json={"question": question})
        assert r.status_code == 200, r.text
        return sent[-1]["messages"]
    return _ask


def test_the_model_is_sent_both_labels_for_a_payment_dated_15_may_2026(ask):
    messages = ask("TDS on a payment to a contractor dated 15 May 2026")
    system = "\n".join(m["content"] for m in messages if m["role"] == "system")
    assert "s.393(1)" in system and "s.194C" in system
    assert "Form 140" in system and "26Q" in system
    assert "Income-tax Act 2025 governs" in system
    # The standing brief is first and unchanged in role; the per-question note is its own message.
    assert messages[0]["role"] == "system" and "INCOME-TAX ACT 1961 AND INCOME-TAX ACT 2025" in messages[0]["content"]
    assert messages[-1] == {"role": "user", "content": "TDS on a payment to a contractor dated 15 May 2026"}


def test_a_question_with_no_date_gets_the_standing_brief_only(ask):
    messages = ask("When is GSTR-1 due?")
    assert [m["role"] for m in messages] == ["system", "user"]


# ── the e-invoice threshold ──────────────────────────────────────────────────

def test_the_einvoice_line_is_the_ladder_the_gst_engine_holds():
    p = _prompt()
    latest_from, latest_paise, cite = irn_scope.THRESHOLDS[-1]
    assert f"Rs {latest_paise // 10_000_000_00} crore today ({cite}, from 01-08-2023)" in p
    for frm, paise, _ in irn_scope.THRESHOLDS:
        dmy = date.fromisoformat(frm).strftime("%d-%m-%Y")
        assert f"from {dmy}: Rs {paise // 10_000_000_00} crore" in p
    assert "E-invoicing (CGST Rule 48(4))" in p
    assert "NOT been read against the notifications" in p, "irn_scope.VERIFIED is False and the prompt says so"


def test_a_new_einvoice_threshold_reaches_the_prompt_with_no_other_edit(monkeypatch):
    monkeypatch.setattr(irn_scope, "THRESHOLDS",
                        irn_scope.THRESHOLDS + (("2027-04-01", 3_00_00_000_00, "Notification 99/2027-Central Tax"),))
    p = _prompt()
    assert "Rs 3 crore today (Notification 99/2027-Central Tax, from 01-04-2027)" in p


def test_the_old_typed_einvoice_sentence_is_gone():
    assert "E-invoicing mandatory above Rs 5 crore turnover" not in _prompt()


# ── GST registration thresholds: refused, not typed ──────────────────────────

def test_no_registration_threshold_figure_is_stated_as_fact():
    """No registry holds them, and the typed line was imprecise ("Rs 10L special
    category states" is not one figure). The prompt now says none is held."""
    p = _prompt()
    assert "Rs 40L" not in p and "Rs 20L" not in p and "Rs 10L" not in p
    line = next(ln for ln in p.splitlines() if ln.startswith("- GST registration"))
    assert "holds no register" in line and "do NOT state a figure" in line


# ── the pieces ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("paise,label", [
    (0, "0L"), (4_00_000_00, "4L"), (2_50_000_00, "2.5L"), (3_00_000_00, "3L"),
    (50_00_000_00, "50L"), (1_00_00_000_00, "1Cr"), (5_00_00_000_00, "5Cr"),
    (2_37_500_00, "Rs 2,37,500"),
])
def test_lakh_label(paise, label):
    assert sb.lakh_label(paise) == label
