"""
One way to ask Groq's text model, and one sentence for when it refuses.

WHAT WAS WRONG (sweep-misc-tools-02)
    POST /api/assistant answered 502 "AI service error. Please try again." on
    every attempt, and the copilot was reported as working. It was not. The
    copilot's own `_call_groq` caught EVERY Groq failure and returned a canned
    `_mock_response` — so each copilot reply stored in production on
    27-09-2026 carries `tokens_used = 0` and is that mock's GST paragraph word
    for word, including for "Which workflows have failed recently?". Both
    routes sent the same key to the same URL for the same hardcoded model, and
    both were failing; one said so and one pretended not to.

    And neither could say WHY. The assistant dropped Groq's status and body on
    the floor and told the CA to try again — advice that cannot work against
    an invalid key or a retired model, which are the two failures that make
    every attempt fail. The copilot logged one line and answered anyway.

WHAT THIS MODULE IS
    The call both routes now make, so they cannot drift again:

    * the MODEL is `GROQ_TEXT_MODEL`, read at call time, defaulting to the
      name routers/document_intelligence_v1 and _v2 default to. CLAUDE.md's
      whole plan for a retired model is "the next retirement is a config
      change", and a hardcoded name at a call site is the one place that plan
      cannot reach — both chat routes had one.
    * a refusal becomes `ProviderFailed`, carrying a SENTENCE saying what is
      wrong and whether retrying can help, and the provider's own status, code
      and body are LOGGED first — the thing somebody with Render's logs needs
      and the thing the old 502 threw away.

    ⚠️ At the time this module was written it did NOT change the default
    model, because whether Groq still served `llama-3.3-70b-versatile` to
    this account could not be checked from here (egress refused) — the plan
    was: the next failure names the cause, and if it is a retirement the
    remedy is setting GROQ_TEXT_MODEL, which needs no deploy.

WHAT HAPPENED NEXT (29-09-2026)
    That retirement arrived. A real call against this account now returns a
    live `model_not_found` 404 for `llama-3.3-70b-versatile`, confirming the
    exact failure this module was built to name — and a web search found
    Groq's own announcement of the deprecation, for free/developer accounts
    from 17-06-2026, naming `openai/gpt-oss-120b` as the replacement.
    `DEFAULT_TEXT_MODEL` is updated to it directly, rather than leaving every
    deployment to discover the 404 and set `GROQ_TEXT_MODEL` by hand — the
    env var still exists for whatever Groq retires next, but there is no
    reason to ship a default known to be dead. ⚠️ The replacement name is
    `[S]`-graded: this environment's egress proxy still refuses a direct
    fetch of Groq's own docs page, so it rests on a search engine's summary
    of Groq's announcement, not a firsthand read of the primary source.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

import httpx

from domain.ai.redaction import redact_messages

_logger = logging.getLogger("caflow.ai.groq")

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
#: The same default the document-extraction routers use, so all Groq text
#: callers agree when nothing is configured.
#:
#: `llama-3.3-70b-versatile` (the default until 29-09-2026) is retired: a real
#: call against this account now returns a live `model_not_found` 404, and a
#: web search found Groq announcing the deprecation of
#: `llama-3.3-70b-versatile` (and `llama-3.1-8b-instant`) for free/developer
#: accounts from 17-06-2026, naming `openai/gpt-oss-120b` as the stated
#: replacement (`qwen/qwen3.6-27b` mentioned as an alternative). `[S]`-graded:
#: this environment's egress proxy refuses a direct fetch of Groq's own docs
#: page, so that announcement is read from a search engine's summary, not the
#: primary source — the same discipline `domain/gst/late_filing.py` and
#: others in this codebase mark with `[S]` for exactly this reason. If Groq
#: has since moved again, the remedy is still what this module's own history
#: already says: set GROQ_TEXT_MODEL, which needs no deploy.
DEFAULT_TEXT_MODEL = "openai/gpt-oss-120b"
DEFAULT_TIMEOUT_S = 30.0

_MODEL_GONE = {"model_not_found", "model_decommissioned", "model_deprecated"}
_TOO_LONG = {"context_length_exceeded", "request_too_large"}


def text_model() -> str:
    """The Groq text model to ask for, read on every call so a changed
    environment is honoured without anybody remembering to re-import."""
    return (os.environ.get("GROQ_TEXT_MODEL") or "").strip() or DEFAULT_TEXT_MODEL


class ProviderFailed(Exception):
    """Groq did not give an answer. `sentence` is written for the person who
    asked; `http_status` is what the API should answer with (502 when the
    provider refused, 504 when it did not answer in time)."""

    def __init__(self, sentence: str, *, http_status: int = 502,
                 provider_status: Optional[int] = None,
                 provider_code: Optional[str] = None) -> None:
        super().__init__(sentence)
        self.sentence = sentence
        self.http_status = http_status
        self.provider_status = provider_status
        self.provider_code = provider_code


def _error_parts(body: Any) -> tuple[Optional[str], str]:
    """(code, message) out of an OpenAI-compatible error body, never raising."""
    try:
        err = body.get("error") if isinstance(body, dict) else None
        if isinstance(err, dict):
            code = err.get("code") or err.get("type")
            return (str(code) if code else None), str(err.get("message") or "").strip()
        if isinstance(err, str):
            return None, err.strip()
    except Exception:                                            # noqa: BLE001
        pass
    return None, ""


def failure_sentence(status: int, body: Any, model: str) -> tuple[str, Optional[str]]:
    """What to tell the person who asked, given Groq's status and body.

    Split by what the reader can DO about it, because "please try again" is
    right for a rate limit and useless for a revoked key — and those two used
    to get the same words."""
    code, message = _error_parts(body)
    low = f"{code or ''} {message}".lower()

    if status == 401 or code == "invalid_api_key":
        # The provider's message is deliberately not echoed: some providers
        # quote part of the key back in it.
        return ("The AI provider (Groq) rejected this server's API key "
                f"(HTTP {status}). GROQ_API_KEY on the server is invalid or has "
                "been revoked and must be replaced — retrying will not help."), code
    if code in _MODEL_GONE or status == 404 or "decommission" in low or "does not exist" in low:
        return (f"The AI provider (Groq) no longer serves the model '{model}' "
                f"({code or f'HTTP {status}'}). Set GROQ_TEXT_MODEL on the server "
                "to a model Groq currently offers — retrying will not help."
                + (f" Groq said: {message[:300]}" if message else "")), code
    if status == 429 or code == "rate_limit_exceeded":
        return ("The AI provider (Groq) is rate-limiting this account right now. "
                "Wait a minute and ask again."), code
    if status == 413 or code in _TOO_LONG:
        return ("This question and the conversation before it are too long for "
                "the AI model. Start a new chat and ask again."), code
    if status >= 500 or status == 498:
        return (f"The AI provider (Groq) is unavailable right now (HTTP {status}). "
                "Try again in a few minutes."), code
    return (f"The AI provider (Groq) refused the request (HTTP {status}"
            + (f", {code}" if code else "") + ")."
            + (f" Groq said: {message[:300]}" if message else "")), code


async def chat(
    messages: list[dict],
    *,
    api_key: str,
    max_tokens: int,
    temperature: Optional[float] = None,
    timeout: float = DEFAULT_TIMEOUT_S,
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> tuple[str, int]:
    """Ask Groq's text model. Returns (reply, total_tokens).

    Raises ProviderFailed — never returns a stand-in answer. A route that has
    no answer must say so; presenting canned text as the model's reply is what
    hid this failure on the copilot.

    `transport` exists for tests, which exercise THIS code against a stand-in
    Groq rather than a copy of it.
    """
    model = text_model()
    # Redacted HERE, at the one place a chat request is built, so a prompt
    # builder that forgets the rule still cannot send a PAN or a GSTIN
    # (domain/ai/redaction). The caller's own list is untouched.
    payload: dict[str, Any] = {"model": model, "messages": redact_messages(messages),
                               "max_tokens": max_tokens}
    if temperature is not None:
        payload["temperature"] = temperature

    try:
        async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
            response = await client.post(
                GROQ_CHAT_URL,
                headers={"Authorization": f"Bearer {api_key}",
                         "Content-Type": "application/json"},
                json=payload,
            )
    except httpx.TimeoutException as exc:
        _logger.error("Groq did not answer within %ss (model=%s): %r", timeout, model, exc)
        raise ProviderFailed(
            f"The AI provider (Groq) did not answer within {int(timeout)} seconds. "
            "Try again; a shorter question may help.", http_status=504) from exc
    except httpx.HTTPError as exc:
        _logger.error("Could not reach Groq (model=%s): %r", model, exc)
        raise ProviderFailed(
            "This server could not reach the AI provider (Groq). Try again in a "
            "few minutes.", http_status=502) from exc

    if response.status_code != 200:
        try:
            body: Any = response.json()
        except ValueError:
            body = response.text
        # LOGGED before anything else: this is the evidence the old 502 threw
        # away. Groq's error body carries a code and a message, not the key.
        _logger.error("Groq refused: HTTP %s model=%s body=%.800s",
                      response.status_code, model, body)
        sentence, code = failure_sentence(response.status_code, body, model)
        raise ProviderFailed(sentence, http_status=502,
                             provider_status=response.status_code, provider_code=code)

    try:
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise TypeError(type(content).__name__)
    except Exception as exc:                                     # noqa: BLE001
        _logger.error("Groq answered 200 in an unreadable shape (model=%s): %.800s",
                      model, response.text)
        raise ProviderFailed(
            "The AI provider (Groq) answered in a shape this server could not "
            "read. Please report it.", http_status=502) from exc

    tokens = (data.get("usage") or {}).get("total_tokens", 0) or 0
    return content, int(tokens)
