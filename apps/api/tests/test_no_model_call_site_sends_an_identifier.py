"""
No client PAN or GSTIN reaches an AI provider — at any door, not just the router
the original test was written beside (ai-15, security_privacy-12).

WHAT WAS WRONG
    The client-level copilot was withdrawn (410) and the firm-level one reduced to
    counts precisely so a client's identifiers never go to a third party. Two other
    doors still sent them: `_build_context` for `context_type="client"` (CLIENT
    NAME, GSTIN, PAN) and `get_client_intelligence` (name, PAN, GSTIN) — reachable
    by API though no screen calls them, so the promise held only while nobody did.
    `tests/test_copilot_no_client_data.py` covers only `routers/ai_copilot.py`.

WHAT THIS ASSERTS
    Two independent layers, each with its own tests, because the second exists so
    the first cannot silently regress:
      1. the BUILDERS no longer ask for an identifier;
      2. `domain/ai/redaction` cleans every outbound chat payload at the place it
         is built, so a builder that forgets still cannot send one.
    plus a guard over EVERY place in the codebase that sends text to Groq.
"""
from __future__ import annotations

import asyncio
import pathlib
import re

import pytest

from domain.ai import groq_text
from domain.ai.redaction import (
    GSTIN_PLACEHOLDER, PAN_PLACEHOLDER, contains_identifier, redact, redact_messages,
)

# Well-formed, and deliberately not any real party's.
GSTIN = "27AAAAA0000A1Z5"
PAN = "AAAAA0000A"
NAME = "ZZTOPSECRETCLIENTALPHA"


# ── the redactor ─────────────────────────────────────────────────────────────

def test_a_gstin_and_a_pan_are_replaced():
    out = redact(f"Client {NAME} has GSTIN {GSTIN} and PAN {PAN}.")
    assert GSTIN not in out and PAN not in out
    assert GSTIN_PLACEHOLDER in out and PAN_PLACEHOLDER in out


def test_a_gstin_leaves_no_fragment_of_its_pan_behind():
    """A GSTIN CONTAINS a PAN. Replacing the PAN first would leave the state
    code, the entity digit and the Z as a recognisable tail."""
    out = redact(f"GSTIN: {GSTIN}")
    assert out == f"GSTIN: {GSTIN_PLACEHOLDER}"


def test_a_gstin_with_a_wrong_check_digit_is_still_an_identifier():
    """The redactor tests SHAPE, not the checksum: the GSTIN a CA pastes is the one
    with a transposition in it, and it still names a registration."""
    assert contains_identifier("27AAAAA0000A1ZX")
    assert contains_identifier("27AAAAA0000A1Z0")


@pytest.mark.parametrize("text", [
    "Section 194J applies to fees for professional services.",
    "GSTR-3B is due on the 20th; GSTR-1 on the 11th (CGST Act, Section 39).",
    "TDS 26Q for Q1 FY 2026-27 is due 31 July. Form 140 from 01-04-2026.",
    "Interest at 18% under Section 50(1) on Rs. 12,34,567.89.",
    "Invoice INV/2026-27/0042 dated 01-06-2026, HSN 998313.",
    "",
])
def test_ordinary_statutory_text_is_left_alone(text):
    """The redactor must not eat the thing the assistant exists to answer."""
    assert redact(text) == text
    assert not contains_identifier(text)


def test_an_identifier_inside_a_longer_token_is_not_split_out():
    assert redact("XAAAAA0000AX") == "XAAAAA0000AX"
    assert redact("AAAAA0000A1") == "AAAAA0000A1"


def test_anything_that_is_not_a_string_comes_back_untouched():
    assert redact(None) is None
    assert redact(12) == 12


def test_redact_messages_copies_and_does_not_touch_the_callers_list():
    original = [{"role": "user", "content": f"check {GSTIN}"}]
    out = redact_messages(original)
    assert original[0]["content"] == f"check {GSTIN}", "a stored conversation keeps what was typed"
    assert out[0]["content"] == f"check {GSTIN_PLACEHOLDER}"
    assert out[0]["role"] == "user"


# ── layer 2: the wire ────────────────────────────────────────────────────────

class _Resp:
    status_code = 200
    text = ""

    def json(self):
        return {"choices": [{"message": {"content": "ok"}}], "usage": {"total_tokens": 5}}


class _FakeAsyncClient:
    """Captures the JSON of every POST instead of sending it."""
    sent: list[dict] = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None, **k):
        type(self).sent.append(json)
        return _Resp()


@pytest.fixture
def wire(monkeypatch):
    _FakeAsyncClient.sent = []
    monkeypatch.setattr("httpx.AsyncClient", _FakeAsyncClient)
    return _FakeAsyncClient.sent


def _payload_text(payload: dict) -> str:
    return " ".join(m["content"] for m in payload["messages"])


def test_groq_text_chat_redacts_what_it_sends(wire):
    asyncio.run(groq_text.chat(
        [{"role": "system", "content": f"GSTIN: {GSTIN}"},
         {"role": "user", "content": f"Is {PAN} a valid PAN?"}],
        api_key="k", max_tokens=10))
    text = _payload_text(wire[0])
    assert GSTIN not in text and PAN not in text


def test_the_firm_copilot_route_redacts_what_it_sends(wire, monkeypatch):
    """routers/ai_copilot builds its OWN request rather than calling groq_text.chat,
    so it is asked for by name."""
    import routers.ai_copilot as cp
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setattr(cp, "check_rate_limit", lambda *a, **k: None)
    monkeypatch.setattr(cp, "_build_firm_context", lambda *a, **k: "Clients: 2")
    user = {"id": "u1", "firm_id": "f1", "auth_user_id": "u1", "role": "Partner"}
    body = cp.CopilotRequest(message=f"What is due for {GSTIN} ({PAN})?", conversation_history=[])
    asyncio.run(cp.copilot_chat(request=None, body=body, current_user=user))
    text = _payload_text(wire[0])
    assert GSTIN not in text and PAN not in text


# ── layer 1: the builders ────────────────────────────────────────────────────

CLIENT_ROW = {"id": "c1", "client_name": NAME, "firm_id": "f1", "gstin": GSTIN, "pan": PAN,
              "status": "active", "health_score": 71, "lifecycle_stage": "retained",
              "email": "owner@example.test"}


@pytest.fixture
def one_client(monkeypatch):
    import domain.ai_copilot_service as mod

    class _Clients:
        def find_all(self, **kw):
            return [CLIENT_ROW]

        def find_by_id(self, cid, **kw):
            return CLIENT_ROW if cid == "c1" else None

    class _Compliance:
        def find_all(self, **kw):
            return []

    monkeypatch.setattr(mod, "_get_client_repo", lambda: _Clients())
    monkeypatch.setattr(mod, "_get_compliance_records_repo", lambda: _Compliance())
    return mod


def test_the_client_context_builder_carries_no_name_gstin_or_pan(one_client):
    context = one_client.ai_copilot_service._build_context("f1", "client", "c1", None)
    for forbidden in (NAME, GSTIN, PAN):
        assert forbidden not in context, f"{forbidden} reached the prompt"
    # Reduced, not gutted: the figures that make the answer useful stay.
    assert "CLIENT STATUS: active" in context
    assert "HEALTH SCORE: 71" in context


def test_the_client_intelligence_prompt_carries_no_name_gstin_or_pan(one_client, monkeypatch):
    svc = one_client.ai_copilot_service
    seen: list[list[dict]] = []

    async def capture(messages):
        seen.append(messages)
        return "report", 7

    class _Repo:
        def get_summary(self, *a, **k):
            return None

        def upsert_summary(self, firm_id, kind, entity, row):
            return row

    monkeypatch.setattr(svc, "_call_groq", capture)
    monkeypatch.setattr(svc, "_repo", _Repo())
    asyncio.run(svc.get_client_intelligence("f1", "c1"))
    sent = " ".join(m["content"] for m in seen[0])
    for forbidden in (NAME, GSTIN, PAN):
        assert forbidden not in sent, f"{forbidden} reached the prompt"
    assert "Status: active" in sent


def test_the_stored_summary_still_knows_which_client_it_is_about(one_client, monkeypatch):
    """The name is withheld from the PROVIDER, not from our own record."""
    svc = one_client.ai_copilot_service
    stored: list[dict] = []

    async def capture(messages):
        return "report", 7

    class _Repo:
        def get_summary(self, *a, **k):
            return None

        def upsert_summary(self, firm_id, kind, entity, row):
            stored.append(row)
            return row

    monkeypatch.setattr(svc, "_call_groq", capture)
    monkeypatch.setattr(svc, "_repo", _Repo())
    asyncio.run(svc.get_client_intelligence("f1", "c1"))
    assert stored[0]["metadata"]["client_name"] == NAME


# ── the guard: every door that sends text to Groq ────────────────────────────
#
# THE GUARD WAS RESTATED WHEN THE GATEWAY LANDED (ai-04). It listed the files that
# SENT to Groq — three redacting senders and two document readers — and failed a
# file that appeared or vanished from the list. That was a guard on a spelling of
# the rule: five modules each built a request, so five had to be named. The rule
# is that a request is built in ONE place that redacts, and that the only callers
# who may switch the redaction off are the ones for whom the DOCUMENT is the
# payload. So the guard is now stated on those two facts:
#
#   1. one module sends text to Groq at all;
#   2. `redact=False` appears at exactly the document readers, by name.

import ast

API = pathlib.Path(__file__).resolve().parents[1]

#: The ONE module that sends text to Groq, and why that is acceptable.
REDACTING_SENDERS = {
    "domain/ai/groq_text.py": "the one chat client; it redacts in chat_detailed() by default",
}
#: The modules that may call the door with `redact=False`. A new reader has to be
#: added here with its reason, rather than appearing quietly.
DOCUMENT_IS_THE_PAYLOAD = {
    "routers/document_intelligence_v1.py":
        "invoice extraction: the supplier's GSTIN is printed on the document being read",
    "routers/document_intelligence_v2.py":
        "notice extraction: the notice text is the document being read",
}


def _production_files():
    for path in API.rglob("*.py"):
        rel = path.relative_to(API).as_posix()
        if rel.startswith(("tests/", "migrations/", "scripts/")):
            continue
        yield rel, path.read_text()


def _senders() -> set[str]:
    found = set()
    for rel, src in _production_files():
        if ("api.groq.com" in src or "from groq import Groq" in src):
            found.add(rel)
    return found


def test_one_module_sends_text_to_groq_and_it_redacts():
    senders = _senders()
    assert senders, "the scan found nothing — it would pass vacuously"
    assert senders == set(REDACTING_SENDERS), (
        f"{sorted(senders ^ set(REDACTING_SENDERS))} send text to Groq (or stopped). Route "
        "the request through domain/ai/groq_text.chat — the one place a Groq request is "
        "built, and the one place it is redacted.")


@pytest.mark.parametrize("rel", sorted(REDACTING_SENDERS))
def test_a_redacting_sender_really_calls_the_redactor(rel):
    src = (API / rel).read_text()
    code = re.sub(r'""".*?"""', "", src, flags=re.S)
    assert re.search(r"\bredact_messages\(", code), f"{rel} is listed as redacting and does not"


def test_the_door_redacts_unless_it_is_told_not_to():
    import inspect
    sig = inspect.signature(groq_text.chat_detailed)
    assert sig.parameters["redact"].default is True, (
        "the door must redact by DEFAULT: a caller that says nothing sends no identifier")


def _calls_that_switch_redaction_off() -> set[str]:
    """Every production file with a call carrying `redact=<anything but True>`."""
    off = set()
    for rel, src in _production_files():
        if "redact" not in src:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if kw.arg == "redact" and not (
                        isinstance(kw.value, ast.Constant) and kw.value.value is True):
                    off.add(rel)
    return off


def test_redaction_is_switched_off_only_where_the_document_is_the_payload():
    off = _calls_that_switch_redaction_off()
    assert off, "the scan found no document reader — it would pass vacuously"
    unknown = off - set(DOCUMENT_IS_THE_PAYLOAD)
    assert not unknown, (
        f"{sorted(unknown)} call the AI door with redaction off. Redaction is off only "
        f"where the DOCUMENT is the payload (an invoice or a notice being read); name the "
        f"module in DOCUMENT_IS_THE_PAYLOAD with the reason, or redact.")
    stale = set(DOCUMENT_IS_THE_PAYLOAD) - off
    assert not stale, f"{sorted(stale)} no longer switch redaction off — remove the entry"


def test_the_statement_analysis_is_redacted_on_the_wire(wire, monkeypatch):
    """financial_analysis_service used to build its own request and redact it by
    name; it goes through the door now, so the door's redaction is what is
    asserted — on the wire, not in a copy."""
    import domain.financial_analysis_service as fa
    monkeypatch.setattr(fa, "_GROQ_API_KEY", "k")
    asyncio.run(fa._call_groq([
        {"role": "system", "content": "analyse"},
        {"role": "user", "content": f"Client {GSTIN} / {PAN}: revenue Rs 1,00,000"}]))
    text = _payload_text(wire[0])
    assert GSTIN not in text and PAN not in text
