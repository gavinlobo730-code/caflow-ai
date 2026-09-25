"""The copilot's client context is scoped, and the brief carries no document.

⚠️ THE CONDITION FOR THIS FEATURE WAS WRITTEN DOWN BEFORE THE FEATURE EXISTED.
`AssistantRequest` used to carry a `client_id` that nothing read, and it was
DELETED with the reason recorded in its place: "this router carries NO
mount-level client guard (main.py includes it with no dependencies), so a dead
client_id is a trap: the moment someone wires it up to real client context,
there is nothing enforcing assignment scope. If the assistant ever becomes
client-aware, add `_CLIENT_GUARD` to its `include_router` FIRST."

Phase 3a-7 made it client-aware. This asserts the FIRST actually happened, and
keeps it happening — a mount guard is one line in another file and a refactor
that never opens `routers/assistant.py` can drop it.

TWO INDEPENDENT CHECKS ARE ASSERTED, and that is deliberate rather than
duplication: the mount guard (`require_client_access`, which inspects a JSON
POST body as well as the path and query) and the handler's own
`assert_client_access`. This is the one endpoint in the product that forwards a
client's figures to a third party, so one of the two failing silently is not an
acceptable state.

AND THE BRIEF'S CONTENTS ARE ASSERTED ON BEHAVIOUR, not on the source. What
must not reach Groq is third-party personal data — a bank statement's
counterparty is a stranger to the engagement, an employee's salary is §17(1)
data about somebody who is not the client — and no source scan can prove a
composed string does not contain it. So the brief is BUILT and read.
"""
import ast
import pathlib

import pytest
from fastapi import HTTPException

import routers.assistant as asst
from domain.ai.client_brief import build_client_brief

API = pathlib.Path(__file__).resolve().parent.parent

FIRM = "firm-1"
MINE, THEIRS = "client-mine", "client-theirs"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "role": "Executive"}


# ══════════════════════════════════════════════════════════════════════════
# The guard that had to come first
# ══════════════════════════════════════════════════════════════════════════

def test_the_assistant_router_is_mounted_with_the_client_guard():
    """Read off `main.py`'s AST rather than matched as text, so a reformat
    cannot make it pass and a rename cannot make it vacuous."""
    tree = ast.parse((API / "main.py").read_text())
    mounts = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "include_router"
        and node.args
        and isinstance(node.args[0], ast.Attribute)
        and isinstance(node.args[0].value, ast.Name)
        and node.args[0].value.id == "assistant"
    ]
    assert len(mounts) == 1, "expected exactly one assistant mount"
    deps = [k for k in mounts[0].keywords if k.arg == "dependencies"]
    assert deps, (
        "app.include_router(assistant.router) carries no `dependencies`. The "
        "assistant takes a client_id and forwards that client's figures to "
        "Groq; `_CLIENT_GUARD` is what enforces assignment scope on it, and "
        "the field's own docstring says this mount must come FIRST."
    )
    assert isinstance(deps[0].value, ast.Name) and deps[0].value.id == "_CLIENT_GUARD", (
        "the assistant's mount dependencies are not `_CLIENT_GUARD`"
    )


def test_the_handler_refuses_a_client_you_are_not_assigned_to(monkeypatch):
    """The SECOND check, exercised. The mount guard lives in another file;
    this one lives beside the code that builds the prompt."""
    import core.authz as authz

    def only_mine(user, cid):
        if cid != MINE:
            raise HTTPException(status_code=404, detail="Client not found")

    monkeypatch.setattr(authz, "assert_client_access", only_mine)
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr(
        asst, "_client_brief",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("the brief was built for an unassigned client")),
    )

    # ⚠️ `asyncio.run`, NOT `get_event_loop().run_until_complete`. The first
    # draft used the latter, passed on its own, and failed inside the full
    # suite — the loop is process-wide and another module had already closed
    # it. A test that only passes when run alone is not a test of anything.
    import asyncio
    req = asst.AssistantRequest(question="what is due?", client_id=THEIRS)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(asst.assistant(req, USER))
    assert exc.value.status_code == 404


# ══════════════════════════════════════════════════════════════════════════
# What the brief may contain
# ══════════════════════════════════════════════════════════════════════════

def _hub(**signals):
    return {"tiles": [
        {"id": k, "label": k.title(), "question": f"{k} question",
         "unit": "count", "answerable": True, "signal": v}
        for k, v in signals.items()
    ]}


def test_a_nil_an_unreadable_and_a_destination_read_differently():
    """The hub's own three states, carried into words. Flattening the second
    to "0" would have the model tell a CA there is nothing outstanding in a
    module nobody could read."""
    brief = build_client_brief("Acme", "Private Limited", {"tiles": [
        {"id": "gst", "label": "GST", "question": "q", "unit": "count",
         "answerable": True, "signal": 0},
        {"id": "bank", "label": "Banking", "question": "q", "unit": "count",
         "answerable": True, "signal": None},
        {"id": "insights", "label": "Insights", "question": "q", "unit": "count",
         "answerable": False, "no_signal_because": "a destination, not a queue"},
    ]})
    assert "GST (q): 0" in brief
    assert "could not be read just now" in brief and "do not treat this as nil" in brief
    assert "a destination, not a queue" in brief


def test_money_is_grouped_by_the_one_authority():
    from domain.money_text import whole_rupees
    brief = build_client_brief("Acme", None, {"tiles": [
        {"id": "p", "label": "Purchases", "question": "owed", "unit": "paise",
         "answerable": True, "signal": 12_34_567_00},
    ]})
    assert f"Rs {whole_rupees(12_34_567_00)}" in brief
    assert "12,34,567" in brief, "Western grouping reached the prompt"


def test_nothing_to_say_answers_none_rather_than_an_empty_heading():
    """A heading with no figures under it invites the model to fill the
    silence, which is the one thing it must not do."""
    assert build_client_brief("Acme", None, None) is None
    assert build_client_brief("Acme", None, {}) is None
    assert build_client_brief("Acme", None, {"tiles": []}) is None


def test_the_brief_tells_the_model_it_may_not_compute():
    """Phase 3's rule travels WITH the figures rather than only in the system
    prompt, so a later prompt edit cannot separate them."""
    brief = build_client_brief("Acme", None, _hub(gst=3))
    assert "Do NOT" in brief and "ratio" in brief
    assert "computed by the application" in brief


def test_the_brief_says_what_it_is_not():
    brief = build_client_brief("Acme", None, _hub(gst=3))
    for owed in ("not the books", "no document", "no employee record",
                 "no tax identifier"):
        assert owed in brief, owed


def test_no_identifier_and_no_third_party_name_can_reach_the_prompt():
    """BEHAVIOURAL. The builder takes three arguments — a name, an entity type
    and a hub payload — so there is no parameter through which a GSTIN, a PAN,
    a bank counterparty or an employee could arrive. Asserted on the SIGNATURE
    so a fourth argument fails here rather than becoming a way in."""
    import inspect
    params = list(inspect.signature(build_client_brief).parameters)
    assert params == ["client_name", "entity_type", "hub_payload"], params
