"""
Tax identifiers never leave for an AI provider.

WHAT WAS WRONG (ai-15, security_privacy-12)
    The client-level copilot was withdrawn (410) because it sent a client's GSTIN
    and PAN to Groq, and the firm-level one was reduced to counts for the same
    reason. Two other doors still put them in the prompt:
    `ai_copilot_service._build_context` for `context_type="client"` (CLIENT NAME,
    GSTIN, PAN) and `get_client_intelligence` (name, PAN, GSTIN). Both are
    reachable by API though no screen calls them today — so the promise held only
    as long as nobody did — and the test that enforces it,
    tests/test_copilot_no_client_data.py, covers only the router it was written
    beside.

WHAT THIS IS
    Two layers, and the second is why the first cannot silently regress:

    1. The builders no longer ASK for an identifier (the prompts were edited).
    2. `redact` runs on every outbound message at the one place a chat request is
       built — `domain/ai/groq_text.chat_detailed`, which is now the ONLY module that
       sends text to Groq (the copilot router's and the statement narrator's own
       requests were moved onto it, ai-04) — and replaces anything shaped like a PAN
       or a GSTIN with a placeholder. A prompt builder added next year that forgets
       the rule still cannot send one.

    It is deliberately a SHAPE test and not a lookup of this firm's clients. The
    shape is what a regulator would call an identifier; a known-client list would
    miss the one typed into a question by a CA, and would have to be loaded (and
    kept fresh) on every request. A PAN is AAAAA9999A and a GSTIN is the two-digit
    state code, a PAN, an entity digit, `Z` and a check character — the same
    shapes `core.validators` and `domain/gst/gstin` check elsewhere, written here
    without the check digit: a transposed GSTIN is exactly the one a CA is likely
    to paste, and it is still an identifier.

WHAT IT DOES NOT DO
    * It does not pseudonymise NAMES. A name has no shape; removing names is the
      builders' job, and the firm-level context already does. A reversible
      `Client A` / `Vendor 3` layer that rehydrates the reply is the larger
      design the finding describes and is NOT built here.
    * It is not applied to document extraction (routers/document_intelligence_*),
      where the document being read IS the payload: an invoice carries its
      supplier's GSTIN and the extraction exists to read it. Those callers pass
      `redact=False` to the door, and tests/test_no_model_call_site_sends_an_identifier.py
      lists every module that does, by name, rather than exempting by silence.
"""
from __future__ import annotations

import re
from typing import Any

PAN_PLACEHOLDER = "[PAN]"
GSTIN_PLACEHOLDER = "[GSTIN]"

# GSTIN first: it CONTAINS a PAN, so replacing the PAN first would leave the
# rest of the GSTIN behind as a recognisable fragment.
_GSTIN = re.compile(r"(?<![A-Za-z0-9])\d{2}[A-Z]{5}\d{4}[A-Z][0-9A-Z]Z[0-9A-Z](?![A-Za-z0-9])")
_PAN = re.compile(r"(?<![A-Za-z0-9])[A-Z]{5}\d{4}[A-Z](?![A-Za-z0-9])")


def redact(text: str) -> str:
    """`text` with every GSTIN and PAN replaced by a placeholder. Anything that is
    not a string comes back untouched."""
    if not isinstance(text, str) or not text:
        return text
    return _PAN.sub(PAN_PLACEHOLDER, _GSTIN.sub(GSTIN_PLACEHOLDER, text))


def redact_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A copy of a chat `messages` list with each string `content` redacted. The
    caller's list is not modified, so a stored conversation keeps what the user
    typed and only what is SENT is cleaned."""
    return [
        {**m, "content": redact(m["content"])} if isinstance(m, dict) and isinstance(m.get("content"), str) else m
        for m in messages
    ]


def contains_identifier(text: str) -> bool:
    """Whether `text` holds anything `redact` would replace — for tests and for
    a caller that wants to say so rather than silently clean."""
    return isinstance(text, str) and redact(text) != text
