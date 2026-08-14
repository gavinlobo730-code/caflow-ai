"""
The AI Copilot must not send client-identifying data to a third-party model.

Groq is an external processor. An Indian CA practice cannot hand it a client
list, and certainly not a GSTIN or PAN — those are the identifiers the whole
confidentiality obligation is about. The product decision taken here was to keep
the copilot open to every role and remove the data instead: if the prompt
carries nothing client-identifying, it stops mattering who is allowed to type
into it. That is a stronger guarantee than a permission check, because it holds
even for a Partner.

Two halves, treated differently on purpose:

  * FIRM-level copilot — reduced. Counts stay ("7 clients, 3 overdue"), names go.
    Still answers "what is my workload?" while identifying nobody.
  * CLIENT-level copilot — withdrawn (410). There was no reduced version worth
    keeping: the endpoint existed solely to feed one client's name, entity type,
    GSTIN, PAN, task titles and compliance records to the model.
"""
import pytest

import routers.ai_copilot as cp


FIRM = "firm-1"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "role": "Partner"}


@pytest.fixture
def clients_with_obvious_names(monkeypatch):
    """Client names chosen to be unmistakable if they leak into the prompt."""
    rows = [
        {"id": "c1", "client_name": "ZZTOPSECRETCLIENTALPHA", "firm_id": FIRM,
         "gstin": "27AAAAA0000A1Z5", "pan": "AAAAA0000A"},
        {"id": "c2", "client_name": "ZZTOPSECRETCLIENTBETA", "firm_id": FIRM,
         "gstin": "29BBBBB1111B1Z5", "pan": "BBBBB1111B"},
    ]
    from repositories.client_repository import client_repo
    monkeypatch.setattr(client_repo, "find_all", lambda **kw: rows)
    return rows


def test_firm_context_contains_no_client_names(clients_with_obvious_names):
    context = cp._build_firm_context(FIRM, USER)

    assert "ZZTOPSECRETCLIENTALPHA" not in context
    assert "ZZTOPSECRETCLIENTBETA" not in context


def test_firm_context_contains_no_gstin_or_pan(clients_with_obvious_names):
    """The identifiers that matter most. Checked separately from names so a
    failure says which kind of leak reappeared."""
    context = cp._build_firm_context(FIRM, USER)

    for forbidden in ("27AAAAA0000A1Z5", "29BBBBB1111B1Z5", "AAAAA0000A", "BBBBB1111B"):
        assert forbidden not in context, f"{forbidden} reached the model prompt"


def test_firm_context_still_reports_the_client_count(clients_with_obvious_names):
    """Reduced, not gutted — the copilot has to stay useful or it will simply be
    reverted by whoever needs it."""
    context = cp._build_firm_context(FIRM, USER)

    # Exact line, not a substring: "Clients: 2" also matches "Clients: 2 names",
    # so a loose assertion would let the names creep back on the same line.
    assert "Clients: 2" in [ln.strip() for ln in context.splitlines()]


def test_system_prompt_does_not_ask_the_model_to_name_clients():
    """The prompt used to instruct: 'Reference actual client names and data from
    the context when relevant.' With names removed that instruction would push
    the model to invent them."""
    prompt = cp.COPILOT_SYSTEM_PROMPT

    assert "actual client names" not in prompt
    assert "NO" in prompt and "client names" in prompt  # states the absence


def test_client_level_copilot_context_builder_returns_nothing():
    """The builder is a stub. If someone restores a body that serialises a PAN,
    this fails before the endpoint is ever re-enabled."""
    assert cp._build_client_context(FIRM, "c1") == ""


def test_client_level_copilot_is_withdrawn():
    """Driven with asyncio.run rather than pytest.mark.asyncio — this repo has
    no pytest-asyncio plugin, and the marker silently no-ops without it."""
    import asyncio
    from fastapi import HTTPException

    class Body:
        message = "what is this client's PAN?"
        conversation_history = []

    with pytest.raises(HTTPException) as exc:
        asyncio.run(cp.client_copilot_chat(Body(), current_user=USER))

    assert exc.value.status_code == 410
    assert "GSTIN" in exc.value.detail or "identifier" in exc.value.detail.lower()
