import logging
import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from models.common import api_response
from core.permissions import rbac
from domain.ai import groq_text
from middleware.rate_limit import ai_limit
from domain.money_text import whole_rupees

router = APIRouter(prefix="/api/assistant", tags=["assistant"])
logger = logging.getLogger("caflow.assistant")

# Ported from the frontend's dead /app/api/ai-assistant route (removed in #220),
# which carried a far richer domain brief than this endpoint had. Two things had
# to survive the move and are load-bearing:
#
#   1. THE "Source:" TRAILER IS A PARSER CONTRACT, not a stylistic preference.
#      The endpoint below splits the reply on the last "Source:" to populate the
#      `source` field. The frontend prompt never asked for it, so porting it
#      verbatim would have silently blanked that field on every answer. It is
#      stated first and last here for that reason, and pinned by a test.
#
#   2. RATES ARE DATED, DEADLINES ARE NOT. The statutory due dates below are
#      stable and match CLAUDE.md. The slab and surcharge figures came from a
#      specific Finance Act and were labelled with a forward financial year, as
#      if unchanged rates were a fact rather than an assumption. A CA asking
#      "what are the slabs" and receiving confidently wrong numbers is the worst
#      failure this endpoint has available to it, so the rates are attributed to
#      their source Act and the model is told to say when it cannot confirm the
#      year — rather than restating them as settled for a year nobody verified.
def _rupees(paise: int) -> str:
    """Integer paise -> a rupee figure grouped the Indian way (Rs 1,00,000).

    ⚠️ THIS USED TO GROUP THE DIGITS ITSELF, AND IT WAS A THIRD IMPLEMENTATION
    OF A RULE CLAUDE.md SAYS HAS ONE PER LANGUAGE. `domain/money_text` is the
    backend authority; this file carried its own pair-slicing loop, and the two
    disagreed on every NEGATIVE figure:

        paise    old _rupees     whole_rupees
         -150    "Rs -2"         "-1"
      -10,050    "Rs -101"       "-100"

    because `paise // 100` FLOORS and `abs()` was then applied to the
    already-floored value, so a magnitude was rounded AWAY from zero and the
    sign re-attached. That is the `f"{p // 100:,}.{p % 100:02d}"` trap CLAUDE.md
    records, in a different spelling.

    Nothing is visibly wrong today — the only caller feeds it TDS thresholds,
    which are positive — and that is the point: it is latent until the copilot
    is given a client's own figures (Phase 3a-7), which is a change one step
    away and would have shipped a wrong minus sign inside an answer a CA reads
    as the software's own.

    The "Rs " prefix stays rather than becoming ₹, deliberately: this string
    goes into a PROMPT, and the reply is parsed on a `Source:` trailer by code
    that has a test pinning it — changing the currency mark in the brief is a
    change to what the model is shown, which is not this fix.
    """
    return f"Rs {whole_rupees(paise)}"


def _tds_lines(fy: str | None = None) -> str:
    """The TDS bullet list, generated from the rate registry rather than typed.

    It used to be typed, and it drifted: the prompt still carried the s. 194J
    Rs 30,000 and s. 194A Rs 5,000 thresholds the Finance Act 2025 raised to
    Rs 50,000 and Rs 10,000, the s. 194I Rs 2.4 lakh ANNUAL limit that Act
    replaced with Rs 50,000 a month, and a flat "Section 194Q: 0.1%; threshold
    Rs 50L" that says nothing about s. 194Q(1) charging only the sum EXCEEDING
    Rs 50 lakh. So a CA who asked the copilot got one answer and the bill they
    then entered got another - from the same application, with nothing
    reconciling the two.

    Same failure shape as the two this module's header already records (a wrong
    Q4 deadline, a hardcoded financial year): a fact duplicated into prose,
    drifting from the code that owns it. The cure is the same - derive it.
    tests/test_system_prompts_agree_with_the_code.py holds the two together.
    """
    from domain.tds.section_rates import tds_rates_for
    from core import ist_clock

    # THE YEAR THE CLOCK SAYS IT IS, not `LATEST_VERIFIED_TDS_FY` (ai-19): the
    # block described FY 2025-26's table in FY 2026-27 without saying so. A year
    # the registry does not hold falls back inside `tds_rates_for` and the
    # heading `_tds_heading` says that it did, in `fy_rate_gap`'s own words.
    fy = fy or ist_clock.ist_fy_label()

    # The sections a CA actually asks about, in the order they are usually met,
    # with what the registry's single figure MEANS where that is not obvious.
    # Not every section in the registry - the prompt is a briefing, not a table.
    WANTED = [
        ("194C", "contractors", ""),
        ("194J", "professional or technical fees", ""),
        ("194H", "commission or brokerage", ""),
        ("194A", "interest other than on securities", ""),
        # s. 194I's limit is per month or part of a month (Finance Act 2025
        # replaced the old Rs 2,40,000 annual limit), so it is deliberately NOT
        # an FY aggregate and must not be described as one.
        ("194I", "rent",
         " — this limit is PER MONTH or part of a month, not for the year"),
        ("194Q", "purchase of goods", ""),
    ]

    rules = tds_rates_for(fy).sections
    out = []
    for code, what, note in WANTED:
        r = rules.get(code)
        if r is None:
            continue
        if r.individual_rate_bps == r.company_rate_bps:
            rate = f"{r.individual_rate_bps / 100:g}%"
        else:
            rate = (f"{r.individual_rate_bps / 100:g}% individual/HUF, "
                    f"{r.company_rate_bps / 100:g}% others")
        line = (f"- Section {code} {what}: {rate}; threshold "
                f"{_rupees(r.single_threshold_paise)} single payment")
        if r.aggregate_threshold_paise is not None:
            line += f" or {_rupees(r.aggregate_threshold_paise)} aggregate in the year"
        line += note
        # What the tax is charged ON, once a threshold is crossed. The two are
        # mutually exclusive and stating both would contradict: s. 194Q(1)
        # carves its threshold OUT of the base, every other section here
        # charges the whole aggregate once a limit is passed.
        if r.charge_on_excess_only:
            line += (f". The tax is charged ONLY on the amount by which the year"
                     f" exceeds {_rupees(r.single_threshold_paise)}, never on the"
                     f" whole sum — s. 194Q(1), \"0.1 per cent of such sum"
                     f" exceeding fifty lakh rupees\"")
        elif r.aggregate_threshold_paise is not None:
            line += (". Once either is crossed the tax is due on the WHOLE"
                     " aggregate for the year, not only on the payment that"
                     " crossed it — the earlier payments are not forgiven,"
                     " they simply had not been taxed yet")
        out.append(line)
    return "\n".join(out)


# ── THE PROMPT IS BUILT PER REQUEST, NOT AT IMPORT (ai-19) ───────────────────
#
# `SYSTEM_PROMPT` used to be a module-level string with `_tds_lines()` spliced in
# once, when the module was first imported. On Render the process stays up across
# 1 April, so it kept briefing the model for a financial year that had ended, and
# the slab, rebate, surcharge, e-invoice and registration figures around the
# generated TDS block were typed text for FY 2025-26 — while the Income-tax Act
# 2025 had taken over the TDS vocabulary on 01-04-2026 and the prompt never said so.
#
# Now the statutory blocks come from `domain/ai/statutory_brief`, which reads the
# registries the engines compute with (`statutory_rates`, `domain/tds/vocabulary`,
# `domain/gst/irn_scope`) at call time, names the financial year the clock says it
# is, and says in the registry's own words when that year's figures are carried
# forward or not held. `SYSTEM_PROMPT` survives as a module attribute computed on
# access (PEP 562), so the tests and any reader that imports it get the CURRENT
# prompt rather than the import-time one; the handler calls `build_system_prompt`.
#
# What stays typed is what is statutory and stable across years — the GST due
# dates, the TDS return dates, the advance-tax instalments, the MCA windows — and
# `tests/test_system_prompts_agree_with_the_code.py` checks each against
# `services/compliance_engine`.

_PROMPT_HEAD = """You are an expert AI assistant for Indian Chartered Accountants \
using PracticeSync. You answer on Indian taxation, GST and statutory compliance.

OUTPUT CONTRACT — follow exactly:
Always end your answer with a final line of the form:
Source: [Act name], Section [number]
This line is parsed by the application. Never omit it, never place anything after \
it, and never use the word "Source:" anywhere earlier in the answer.

"""

_PROMPT_GST_DATES = """

GST COMPLIANCE (CGST Act) — statutory due dates:
- GSTR-1: 11th of the following month (Section 37); QRMP filers 13th
- GSTR-3B: 20th of the following month (Section 39); 22nd/24th for small taxpayers
- GSTR-9 annual return: 31st December (Section 44)
- GSTR-2B auto-populated by the 14th of the following month
"""

_PROMPT_TDS_SALARY = """
- Section 192 salary: applicable slab rates
"""

# The two-limb paragraph is GENERATED (`statutory_brief.two_limb_block`) and no
# longer typed. It said "this software does not hold either concessional rate ...
# do NOT quote a figure" after TDS-22 (25-09-2026) put the confirmed 2% for
# 194I(a) and 194J(a) in `section_rates` — a typed statement of what the engine
# does not hold, contradicting the engine, which is the drift this module's
# header records.

_PROMPT_TDS_AFTER = """
- 24Q/26Q returns: 31 July (Q1), 31 October (Q2), 31 January (Q3), 31 May (Q4). \
Q4 is 31 May, NOT 30 April — it is the one quarter that does not follow the \
"end of the month after quarter end" pattern.

ADVANCE TAX (IT Act Sections 208 and 211), cumulative:
- 15 June 15%, 15 September 45%, 15 December 75%, 15 March 100%

MCA / COMPANIES ACT 2013:
- AOC-4 financial statements: within 30 days of the AGM
- MGT-7 / 7A annual return: within 60 days of the AGM
- DIR-3 KYC: 30 September annually
- ADT-1 auditor appointment: within 15 days of the AGM

RULES:
- Cite the specific provision, e.g. "Section 44 of the CGST Act", "Section 139 of \
the IT Act". A general answer with no section is not useful to a CA.
- The Indian financial year runs 1 April to 31 March.
- For anything to be filed or submitted, add: "Please have your CA review before filing."
- Never advise on tax evasion or aggressive avoidance.
- If you are unsure, say so. Never guess on a tax matter — a wrong figure stated \
confidently is worse than no answer.
- End with the Source: line described in the output contract above."""


def _tds_heading(fy: str) -> str:
    """The TDS block's title: the year it is for, and what the registry says about it.

    Named because the same table can be one year's verified figures or another's
    carry-forward, and the model has to be able to tell a CA which. The sentence
    is `section_rates.fy_rate_gap`'s own, so the prompt and the engine's refusal
    to call an unverified year verified can never disagree.
    """
    from domain.tds import section_rates

    head = (f"TDS, FY {fy} (rates and thresholds below are generated from the engine "
            f"that computes them — domain/tds/section_rates.py — so they cannot drift "
            f"from what the app does):")
    gap = section_rates.fy_rate_gap(fy)
    return head + (f"\n{gap}" if gap else "")


def build_system_prompt(today=None) -> str:
    """The assistant's brief for TODAY — see the block comment above.

    `today` is injectable so a test can move the clock without patching the module
    that reads it. Everything generated reads a registry; everything typed is a
    statutory date that does not move with the year.
    """
    from core import ist_clock
    from domain.ai import statutory_brief as brief

    today = today or ist_clock.ist_today()
    fy = ist_clock.ist_fy_label(today)
    return (
        _PROMPT_HEAD
        + brief.income_tax_block(today)
        + "\n\n"
        + brief.act_transition_block(today)
        + _PROMPT_GST_DATES
        + "- " + brief.einvoice_block().replace("\n", "\n  ") + "\n"
        + brief.registration_threshold_block()
        + "\n\n"
        + _tds_heading(fy) + "\n"
        + _tds_lines(fy)
        + _PROMPT_TDS_SALARY
        + "- " + brief.two_limb_block(fy) + "\n"
        + _PROMPT_TDS_AFTER
    )


def __getattr__(name: str):
    """`SYSTEM_PROMPT` as a computed attribute (PEP 562): importing the name
    returns the prompt for the clock's CURRENT year, never the import-time one."""
    if name == "SYSTEM_PROMPT":
        return build_system_prompt()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

# No URL and no model name here any more. Both lived here as literals — the
# model hardcoded while GROQ_TEXT_MODEL existed for exactly this — and the
# copilot carried its own copy of each. domain/ai/groq_text is the one call.


def split_source(full_answer: str) -> tuple[str, str]:
    """Split a reply into (answer, citation) on the trailing "Source:" marker.

    Module-level and public so the tests exercise THIS code rather than a copy
    of it. The first version of the test reimplemented the split inline, and the
    copy immediately drifted from the original — which is the same class of
    mistake as the prompt and the parser disagreeing, only in the test.

    rsplit, not split: the marker is defined as the LAST thing in the reply, so
    a stray earlier mention must not carve the answer in half. Returns an empty
    citation when the model omitted the marker — a degraded answer, not an
    error, which is exactly why the prompt's demand for it is asserted in tests.
    """
    if "Source:" not in full_answer:
        return full_answer, ""
    body, citation = full_answer.rsplit("Source:", 1)
    # A marker with NOTHING after it is a malformed citation, and it must read as
    # an absent one: rebuilt below it would be the truthy string "Source: ", and
    # the page would show an empty citation as though a section had been named
    # (ai-18). The reply keeps its text; the dangling marker is what is dropped.
    if not citation.strip():
        return body.strip(), ""
    # Rebuilt with the space: .strip() removes the one the model wrote after the
    # colon, and rebuilding without it rendered every citation as
    # "Source:CGST Act, Section 37".
    return body.strip(), "Source: " + citation.strip()


class Message(BaseModel):
    role: str
    content: str


class AssistantRequest(BaseModel):
    question: str
    conversation_history: Optional[List[Message]] = []
    #: The client the question is about, or None for a general one.
    #:
    #: ⚠️ THIS FIELD WAS DELETED ONCE AND THE CONDITION FOR BRINGING IT BACK
    #: WAS WRITTEN DOWN. It used to sit here read by nothing, and was removed
    #: because "this router carries NO mount-level client guard ... so a dead
    #: client_id is a trap: the moment someone wires it up to real client
    #: context, there is nothing enforcing assignment scope. If the assistant
    #: ever becomes client-aware, add _CLIENT_GUARD to its include_router
    #: FIRST." That was done first (main.py), and `require_client_access`
    #: inspects a JSON POST body as well as the path and query, so this field
    #: is covered by it — the internal-practice-client check AND
    #: `assert_client_access`.
    #:
    #: The handler asks `assert_client_access` AGAIN anyway. That is not
    #: belt-and-braces for its own sake: the mount guard lives in a
    #: `dependencies=[...]` list in another file, which a refactor can drop
    #: without touching anything in here, and this is the one endpoint in the
    #: product that forwards a client's figures to a third party.
    client_id: Optional[str] = None


def _client_brief(client_id: str, current_user: dict) -> Optional[str]:
    """What this client's own figures say, as a block for the prompt.

    Built from `services/hub_service.hub`, which already answers every tile's
    question for one client in one scoped request — so a tile added later
    reaches the copilot the day it is added, and there is no second list of
    things-to-fetch to drift. `domain/ai/client_brief` is the rule for what
    goes in and, more importantly, what does not.

    ⚠️ A FAILURE HERE ANSWERS None RATHER THAN RAISING. The copilot still works
    without context, and refusing to answer a general tax question because one
    count could not be read would be the worse outcome. What it must never do
    is answer as though it HAD the figures, which is why the brief says in its
    own words that it is a summary of outstanding work and nothing else.
    """
    from domain.ai.client_brief import build_client_brief
    from repositories.client_repository import client_repo
    from services.hub_service import hub

    firm_id = current_user.get("firm_id")
    try:
        client = client_repo.find_by_id(client_id, firm_id=firm_id) or {}
        payload = hub(current_user, client_id=client_id)
    except Exception:                                            # noqa: BLE001
        logger.exception("assistant: the client brief could not be built")
        return None
    return build_client_brief(
        client.get("legal_name") or client.get("client_name"),
        client.get("entity_type"),
        payload,
    )


@router.post("")
async def assistant(request: AssistantRequest, current_user: dict = Depends(rbac("ai", "read")),
                    _limit: None = Depends(ai_limit("chat"))):
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        # 503 and the variable's name: a missing key is a deployment setting,
        # not an internal fault, and saying which setting is the whole remedy.
        raise HTTPException(status_code=503, detail=(
            "The AI assistant is not configured on this server: GROQ_API_KEY is "
            "not set."))

    messages = [{"role": "system", "content": build_system_prompt()}]

    # When the question NAMES a date, pin the Act-transition rule to it so the
    # answer carries both numberings for an event on or after 01-04-2026. A
    # separate system message, like the client brief below: the standing brief is
    # about the law and the same for everyone, this is about one question.
    from domain.ai import statutory_brief
    dated = statutory_brief.event_brief(request.question)
    if dated:
        messages.append({"role": "system", "content": dated})

    if request.client_id:
        # The SECOND check. See the field's own note: the first is the mount
        # guard in main.py, which lives in another file and can be dropped by a
        # refactor that never opens this one.
        from core.authz import assert_client_access
        assert_client_access(current_user, request.client_id)
        brief = _client_brief(request.client_id, current_user)
        if brief:
            # A SEPARATE system message rather than appended to SYSTEM_PROMPT:
            # the standing brief is about the LAW and does not change, this is
            # about one client and changes every request, and concatenating
            # them would make the statutory prompt look per-request to the next
            # reader — and to any cache keyed on it.
            messages.append({"role": "system", "content": brief})

    messages += [{"role": m.role, "content": m.content} for m in (request.conversation_history or [])]
    messages.append({"role": "user", "content": request.question})

    # ⚠️ THIS USED TO ANSWER EVERY FAILURE WITH "AI service error. Please try
    # again." and discard Groq's status and body — so a revoked key or a
    # retired model, the two failures that make EVERY attempt fail, were
    # reported as something a retry might fix, and nobody could tell which it
    # was (sweep-misc-tools-02: 4 of 4 attempts). A timeout was worse: it was
    # not caught at all and came back as a bare 500. groq_text logs what Groq
    # said and hands back a sentence saying what is wrong and whether retrying
    # can help; /ai-assistant renders the `detail` as given.
    try:
        full_answer, _tokens = await groq_text.chat(messages, api_key=api_key, max_tokens=1024)
    except groq_text.ProviderFailed as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.sentence) from exc

    answer, source = split_source(full_answer)

    return api_response(True, {"answer": answer, "source": source})
