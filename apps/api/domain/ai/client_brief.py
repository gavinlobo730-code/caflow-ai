"""What the copilot is told about the client it is answering for — Phase 3a-7.

`routers/assistant` was a pure Groq passthrough over a static SYSTEM_PROMPT
that loaded no client data at all, so a CA asking "what does Acme still owe
this month" got a generic tax chatbot wearing the product's name. This module
turns the figures the product ALREADY COMPUTED into the block of text the model
is given beside the question.

── THE RULE THIS EXISTS UNDER ───────────────────────────────────────────────

    The LLM narrates figures the product computed. It never computes them.

So the brief carries FIGURES AND NOTHING ELSE — no ratios it worked out, no
totals it summed across tiles, no sentence about what a number means. Every
line is one tile's own label, its own question and its own signal, taken
verbatim from `domain/hub/tiles.describe`. The model may read them out and
reason about what to DO; it is told, in the block itself, that it may not
compute a new figure from them, because a CA who catches the AI inventing a
number stops trusting the software entirely and there is no way to audit the
number afterwards.

── IT IS BUILT FROM THE HUB PAYLOAD, WHICH IS WHY IT CANNOT GO STALE ────────

`services/hub_service.hub(current_user, client_id)` already answers every
tile's figure for one client in one request, scoped, with its own three-state
discipline. Building the brief from that payload rather than from a second
list of things-to-fetch means a tile added next year appears here the day it
is added, and a tile whose meaning changes changes here too. A private list
would be the `capital_wip` shape: two authorities, one of them quietly wrong.

── A NIL AND AN UNREADABLE ARE DIFFERENT AND THE MODEL IS TOLD WHICH ────────

`describe` sets `answerable: false` with a REASON where a tile is a
destination rather than a queue, and `signal: None` with `answerable: true`
where the fetch failed. Flattening either to "0" would have the model tell a
CA there is nothing outstanding in a module nobody could read. The three
states are carried through in words.

── WHAT IS DELIBERATELY NOT IN THE BRIEF ────────────────────────────────────

Named, so the next reader does not add them by accident:

  · **No document text.** Not an invoice narration, not a bank statement's
    counterparty, not a document the client uploaded. A statement line names a
    counterparty who is a stranger to the engagement (`docs/compliance/06`),
    and sending one to Groq is an egress of third-party personal data that
    nothing here has a lawful basis for.
  · **No employee record.** Salary is §17(1) data about a person who is not
    the CA's client.
  · **No identifier beyond the client's own name and entity type** — no GSTIN,
    no PAN, no TAN. The model needs to know WHO it is answering about, not
    enough to impersonate them, and a PAN in a prompt is a PAN in somebody's
    logs.
  · **No figure from another client**, which is structural rather than
    checked: `build_client_brief` takes ONE hub payload, and that payload is
    produced for one validated client id.
"""
from __future__ import annotations

from typing import Optional

from domain.money_text import whole_rupees

#: What the model is told about its own licence, in the block itself rather
#: than only in the system prompt — the figures and the rule about them travel
#: together, so a future prompt edit cannot separate them.
NARRATE_ONLY = (
    "These figures were computed by the application from this client's own "
    "records. Read them out, and reason about what the CA should DO. Do NOT "
    "add them up, work out a ratio, project a trend or produce any figure that "
    "is not written above — if the answer needs a number that is not here, say "
    "which one is missing and where in the application it lives."
)

#: Said once at the top, so an answer cannot imply the model saw the ledger.
WHAT_THIS_IS = (
    "The CA is asking about one client. What follows is every question the "
    "application's hub asks of that client, with the answer it computed. It is "
    "a summary of OUTSTANDING WORK, not the books: no document, no ledger "
    "line, no employee record and no tax identifier is included."
)


def _figure(unit: str, signal: int) -> str:
    """A tile's signal in the unit the tile itself declares.

    `whole_rupees` rather than a second grouping — `domain/money_text` is the
    one backend authority and this module is not going to become a fourth
    implementation of it.
    """
    return f"Rs {whole_rupees(signal)}" if unit == "paise" else str(signal)


def build_client_brief(client_name: Optional[str],
                       entity_type: Optional[str],
                       hub_payload: Optional[dict]) -> Optional[str]:
    """The prompt block, or None where there is nothing worth sending.

    None rather than an empty block: a heading with no figures under it invites
    the model to fill the silence, which is the one thing it must not do.
    """
    if not isinstance(hub_payload, dict):
        return None
    tiles = hub_payload.get("tiles")
    if not isinstance(tiles, list) or not tiles:
        return None

    who = client_name or "this client"
    if entity_type:
        who = f"{who} ({entity_type})"

    lines: list[str] = []
    for t in tiles:
        if not isinstance(t, dict):
            continue
        label = t.get("label") or t.get("id") or "?"
        question = t.get("question") or ""
        if not t.get("answerable"):
            why = t.get("no_signal_because") or "no figure is kept for this"
            lines.append(f"- {label}: no figure — {why}")
            continue
        signal = t.get("signal")
        if signal is None:
            # `answerable` and yet no signal: the fetch failed. Saying "0" here
            # would have the model report a clean module nobody could read.
            lines.append(
                f"- {label} ({question}): could not be read just now — do not "
                f"treat this as nil.")
            continue
        lines.append(
            f"- {label} ({question}): {_figure(str(t.get('unit') or ''), int(signal))}")

    if not lines:
        return None

    return (
        f"CLIENT CONTEXT — {who}\n"
        f"{WHAT_THIS_IS}\n\n"
        + "\n".join(lines)
        + f"\n\n{NARRATE_ONLY}"
    )


__all__ = ["build_client_brief", "NARRATE_ONLY", "WHAT_THIS_IS"]
