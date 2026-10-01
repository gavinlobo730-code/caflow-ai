"""What a chat request may carry from the browser. (ai-16.)

WHAT WAS WRONG
    `POST /api/assistant` declared `Message.role: str` and passed
    `conversation_history` to the model verbatim, with no limit on how many
    messages, how long each was, or how long the question was. A request body
    saying `{"role": "system", "content": "..."}` therefore reached the model as
    a SYSTEM message — the one slot the product's own statutory brief occupies —
    and a history of ten thousand messages was a prompt of ten thousand messages,
    on the firm's quota, up to the provider's own refusal.
    `domain/ai_copilot_service._build_messages` already whitelisted `user` and
    `assistant` and kept the last eight, so the two chat doors disagreed about
    what a client may say; `/api/ai-copilot/chat` had the same open `role: str`.

THE RULE
    A browser may send turns the USER or the ASSISTANT said and nothing else; the
    system's words are the server's. A bad role is a 422 (it is never a thing a
    well-behaved client sends). A message or question longer than the cap is a
    422 too. A history longer than `MAX_HISTORY_MESSAGES` is TRIMMED to the most
    recent turns rather than refused: a long conversation is ordinary, the screen
    keeps the whole of it in the browser for a day, and refusing it would break a
    chat the user has done nothing wrong in — while the older turns are exactly
    the ones a model gets least from.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ChatRole = Literal["user", "assistant"]

#: One message, in characters. An assistant answer is capped at about 2,048
#: tokens (`groq_text.ASSISTANT_MAX_TOKENS`), so this is several times the
#: longest reply the product itself produces and well above any question a CA
#: types or pastes.
MAX_MESSAGE_CHARS = 12_000
#: The question being asked now.
MAX_QUESTION_CHARS = 8_000
#: Turns of history sent on. Matches the order of magnitude the copilot's own
#: service keeps (`history[-8:]` there, over stored messages).
MAX_HISTORY_MESSAGES = 30


class ChatTurn(BaseModel):
    """One earlier turn, as the browser sends it back."""
    role: ChatRole
    content: str = Field(max_length=MAX_MESSAGE_CHARS)


def most_recent(history: list) -> list:
    """The last `MAX_HISTORY_MESSAGES` turns, oldest first."""
    return list(history or [])[-MAX_HISTORY_MESSAGES:]
