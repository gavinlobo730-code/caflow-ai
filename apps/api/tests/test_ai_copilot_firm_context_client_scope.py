"""
Client-assignment scope on ai_copilot.py — the FIRM-context copilot on
/api/ai-copilot.

NOT the same router as ai_copilot_v2.py, which owns /api/copilot and was
audited earlier in this sweep — that one's tests live in
test_ai_copilot_client_scope.py, hence this file's longer name. Two router
files, two prefixes, one feature name; keeping the test files distinct is
the same discipline the ratchet's two separate AUDITED entries encode.

get_firm_context and copilot_chat have no client_id anywhere, so main.py's
mount-level client guard never fires on them — and both built a NAMED list of
every client in the firm. copilot_chat puts those names verbatim into the Groq
system prompt, so an unassigned Executive could simply ask the copilot to list
them; get_firm_context returns the same leak in structured form.

The task-dashboard and risk tallies expose no per-client scoping parameter and
are deliberately left as firm-wide COUNTS with no client named — the same line
already drawn for /api/copilot/intelligence/*, recorded in the audit doc.
"""
import pytest
from fastapi import HTTPException

import routers.ai_copilot as cp

FIRM = "firm-1"
MINE, THEIRS = "c-mine", "c-theirs"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "role": "Manager"}

CLIENTS = [
    {"id": MINE, "client_name": "My Client Ltd", "status": "active"},
    {"id": THEIRS, "client_name": "Someone Elses Client Ltd", "status": "active"},
]


@pytest.fixture
def scoped(monkeypatch):
    """Narrow to {MINE}. filter_by_client here is keyed on "id", not
    "client_id" — `clients` rows name their own id that way, and getting the
    key wrong would silently return everything."""
    monkeypatch.setattr(cp, "effective_client_ids", lambda user: {MINE})
    monkeypatch.setattr(cp, "filter_by_client",
                        lambda user, rows, key="client_id":
                        [r for r in rows if str(r.get(key)) in {MINE}])

    import repositories.client_repository as client_mod

    class _Repo:
        def find_all(self, firm_id=None):
            return list(CLIENTS)

    monkeypatch.setattr(client_mod, "client_repo", _Repo())


# ══════════════════════════════════════════════════════════════════════════════
# _build_firm_context — the string that becomes the Groq system prompt
# ══════════════════════════════════════════════════════════════════════════════

def test_the_groq_prompt_does_not_name_clients_outside_your_book(scoped):
    ctx = cp._build_firm_context(FIRM, USER)
    assert "My Client Ltd" in ctx
    assert "Someone Elses Client Ltd" not in ctx


def test_the_compliance_summary_is_narrowed_to_your_book(scoped, monkeypatch):
    import domain.compliance_record_service as comp_mod
    seen = {}

    class _Svc:
        def get_firm_summary(self, firm_id=None, allowed_client_ids=None):
            seen["allowed"] = allowed_client_ids
            return {}

    monkeypatch.setattr(comp_mod, "compliance_record_service", _Svc())
    cp._build_firm_context(FIRM, USER)
    assert seen["allowed"] == {MINE}


def test_a_firmwide_caller_still_sees_every_client(monkeypatch):
    """effective_client_ids returns None for a Partner — filter_by_client must
    then be a pass-through, not an empty set."""
    from core.authz import filter_by_client
    monkeypatch.setattr(cp, "effective_client_ids", lambda user: None)
    monkeypatch.setattr(cp, "filter_by_client", filter_by_client)

    import repositories.client_repository as client_mod

    class _Repo:
        def find_all(self, firm_id=None):
            return list(CLIENTS)

    monkeypatch.setattr(client_mod, "client_repo", _Repo())
    ctx = cp._build_firm_context(FIRM, {**USER, "role": "Partner"})
    assert "My Client Ltd" in ctx
    assert "Someone Elses Client Ltd" in ctx


# ══════════════════════════════════════════════════════════════════════════════
# get_firm_context — the same leak, in structured form
# ══════════════════════════════════════════════════════════════════════════════

def test_the_firm_context_panel_omits_clients_outside_your_book(scoped):
    out = cp.get_firm_context(current_user=USER)
    names = [c["name"] for c in out["data"]["clients"]]
    assert names == ["My Client Ltd"]


def test_the_firm_context_panel_narrows_its_compliance_summary(scoped, monkeypatch):
    import domain.compliance_record_service as comp_mod
    seen = {}

    class _Svc:
        def get_firm_summary(self, firm_id=None, allowed_client_ids=None):
            seen["allowed"] = allowed_client_ids
            return {}

    monkeypatch.setattr(comp_mod, "compliance_record_service", _Svc())
    cp.get_firm_context(current_user=USER)
    assert seen["allowed"] == {MINE}


# ══════════════════════════════════════════════════════════════════════════════
# client_copilot_chat — client_id in the path
# ══════════════════════════════════════════════════════════════════════════════

def test_chatting_about_another_clients_book_is_refused(monkeypatch):
    # Driven with asyncio.run rather than pytest.mark.asyncio — this repo has
    # no async pytest plugin installed, and the guard is reached before the
    # first await regardless.
    import asyncio

    def _assert(user, client_id):
        if client_id == THEIRS:
            raise HTTPException(status_code=404, detail="Not found")

    monkeypatch.setattr(cp, "assert_client_access", _assert)
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    built = []
    monkeypatch.setattr(cp, "_build_client_context",
                        lambda firm_id, cid: built.append(cid) or "ctx")

    with pytest.raises(HTTPException) as e:
        asyncio.run(cp.client_copilot_chat(
            THEIRS, cp.CopilotRequest(message="hi"), current_user=USER))
    assert e.value.status_code == 404
    assert not built   # refused before any client context was assembled

    # …and the in-scope case still reaches the context builder.
    asyncio.run(cp.client_copilot_chat(
        MINE, cp.CopilotRequest(message="hi"), current_user=USER))
    assert built == [MINE]
