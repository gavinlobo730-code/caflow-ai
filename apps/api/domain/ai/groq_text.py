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

WHAT THE GATEWAY ADDED (ai-04, ai-05)
    This module is the one place a Groq request is built, and it is now the only
    module that talks to Groq at all: the invoice and notice extractors (vendor
    SDK, no timeout, a generic 502), the firm copilot route and the statement
    narrator (their own httpx requests) all call `chat` / `chat_sync`. What sits
    around the request is `domain/ai/gateway` — a bounded retry with backoff on
    429 and 5xx, an ordered fallback list (`GROQ_TEXT_MODEL_FALLBACK`), the
    classified sentence for every failure, and a usage row per attempt.

    The default model is a REASONING model, and reasoning tokens are drawn from
    the same response budget as the answer. Three consequences are handled here
    rather than at each caller:

      * `reasoning_effort` and a `json_schema` response format are sent ONLY to
        model families Groq documents them for (`[S]`-graded: egress is refused
        in this environment, so it rests on a search summary of Groq's docs), and
        if Groq rejects either anyway the call goes again WITHOUT it. They are
        hints. Correctness stays with the caller's own validation, which is why
        a model that ignores them is caught by the same check;
      * an EMPTY reply — or a null `content`, which is what a model that only
        reasoned returns — is a FAILURE (`ProviderFailed`, kind `empty_reply`),
        never a value. Before this an assistant answer could come back as "" with
        success true, and the statement narrator marked an empty string
        `ai_generated`;
      * a reply that ends on the response budget with text in it is returned and
        recorded as `truncated`, so the budget can be tuned from evidence.

    A fallback model changes WHO WROTE an answer, so `answered_by()` says which
    model answered the last call in this context and the places that store a
    model label read it instead of `text_model()`.
"""
from __future__ import annotations

import asyncio
import contextvars
import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from domain.ai import gateway
from domain.ai.gateway import JsonSchema, ProviderFailed  # noqa: F401 — re-exported
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

# The response budgets, named once. They are RAISED from the 1024 / 512 / 300
# the extractors, the notice reader and the narrator carried: on a reasoning
# model the reasoning is drawn from the same allowance as the answer, and an
# invoice with twenty lines is more than a thousand tokens of JSON before any
# reasoning at all. `[S]`: whether Groq counts the requested allowance toward
# its tokens-per-minute estimate could not be read here, so these are generous
# rather than maximal, and the usage record carries `reasoning_tokens` so they
# can be tuned from what the model actually spends.
EXTRACTION_MAX_TOKENS = 4096
NOTICE_MAX_TOKENS = 2048
NARRATION_MAX_TOKENS = 1200
ASSISTANT_MAX_TOKENS = 2048

#: Model families Groq documents `reasoning_effort` for, and the values it takes
#: there (low, medium, high). `[S]`. A model outside this list is sent nothing:
#: a different family reads the same parameter differently or rejects it.
_REASONING_EFFORT_FAMILIES = ("openai/gpt-oss",)
_REASONING_EFFORTS = ("low", "medium", "high")
#: Model families Groq documents `json_schema` structured outputs for. `[S]`.
_JSON_SCHEMA_FAMILIES = ("openai/gpt-oss",)

#: The words in a 400 that mean "it is the OPTIONAL parameter you sent".
_HINT_WORDS = ("response_format", "json_schema", "reasoning_effort", "structured output")

# Which model answered the last call made in this context. A ContextVar and not
# a return value because `chat` already returns the `(text, tokens)` pair six
# callers and their test doubles are written against.
_answered_by: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "groq_answered_by", default=None)


def text_model() -> str:
    """The Groq text model to ask for, read on every call so a changed
    environment is honoured without anybody remembering to re-import."""
    return (os.environ.get("GROQ_TEXT_MODEL") or "").strip() or DEFAULT_TEXT_MODEL


def fallback_models() -> list[str]:
    """The models tried, in order, when `text_model()` fails. Empty unless
    GROQ_TEXT_MODEL_FALLBACK names some — there is no built-in one."""
    return gateway.models_in(os.environ.get("GROQ_TEXT_MODEL_FALLBACK"))


def model_chain() -> list[str]:
    return gateway.model_chain(text_model(), "GROQ_TEXT_MODEL_FALLBACK")


def answered_by() -> str:
    """The model that wrote the last answer in this context, else the one
    configured now. What a stored row's `model_used` label is read from, so a
    reply a fallback wrote is not recorded under the primary's name."""
    return _answered_by.get() or text_model()


def supports_reasoning_effort(model: str) -> bool:
    return any(model.startswith(f) for f in _REASONING_EFFORT_FAMILIES)


def supports_json_schema(model: str) -> bool:
    return any(model.startswith(f) for f in _JSON_SCHEMA_FAMILIES)


def failure_sentence(status: int, body: Any, model: str) -> tuple[str, Optional[str]]:
    """What to tell the person who asked, given Groq's status and body."""
    return gateway.failure_sentence(gateway.GROQ, status, body, model)


@dataclass(frozen=True)
class Reply:
    """A model's answer and who gave it."""
    text: str
    total_tokens: int
    model: str
    finish_reason: Optional[str] = None
    fallback_used: bool = False
    call_id: str = ""


def build_request(
    model: str,
    messages: list[dict],
    *,
    max_tokens: int,
    temperature: Optional[float] = None,
    reasoning_effort: Optional[str] = None,
    response_schema: Optional[JsonSchema] = None,
    hints: bool = True,
) -> tuple[dict, bool]:
    """THE Groq request, built in one place. Returns (payload, hints_were_sent).

    `messages` arrive already redacted (or deliberately not — `chat`'s `redact`
    flag). The two hints go only to a model family Groq documents them for, and
    only while `hints` is True, which is how a call goes again without them."""
    payload: dict[str, Any] = {"model": model, "messages": messages, "max_tokens": max_tokens}
    if temperature is not None:
        payload["temperature"] = temperature
    sent = False
    if hints:
        if reasoning_effort in _REASONING_EFFORTS and supports_reasoning_effort(model):
            payload["reasoning_effort"] = reasoning_effort
            sent = True
        if response_schema is not None and supports_json_schema(model):
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": response_schema.name, "strict": True,
                                "schema": response_schema.schema},
            }
            sent = True
    return payload, sent


def _retry_after(response: httpx.Response) -> Optional[float]:
    try:
        raw = response.headers.get("retry-after")
        return float(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _body_of(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text


def _hint_rejected(status: int, body: Any) -> bool:
    if status not in (400, 422):
        return False
    code, message = gateway.error_parts(body)
    param = ""
    try:
        err = body.get("error") if isinstance(body, dict) else None
        param = str(err.get("param") or "") if isinstance(err, dict) else ""
    except Exception:                                            # noqa: BLE001
        pass
    text = f"{code or ''} {message} {param}".lower()
    return any(w in text for w in _HINT_WORDS)


def _usage_of(data: Any) -> tuple[Optional[int], Optional[int], Optional[int], int]:
    """(prompt, completion, reasoning, total) tokens, each None where absent."""
    u = data.get("usage") if isinstance(data, dict) else None
    u = u if isinstance(u, dict) else {}
    details = u.get("completion_tokens_details")
    reasoning = details.get("reasoning_tokens") if isinstance(details, dict) else None
    return (u.get("prompt_tokens"), u.get("completion_tokens"), reasoning,
            int(u.get("total_tokens", 0) or 0))


def _read_reply(response: httpx.Response, model: str, call_id: str,
                fallback_used: bool) -> tuple[Optional[Reply], Optional[ProviderFailed], tuple]:
    """A 200 answer as a Reply, or the failure it is."""
    try:
        data = response.json()
        choice = data["choices"][0]
        content = choice["message"]["content"]
    except Exception:                                            # noqa: BLE001
        _logger.error("Groq answered 200 in an unreadable shape (model=%s): %.800s",
                      model, response.text)
        return None, gateway.unreadable_failure(gateway.GROQ), (None, None, None, 0)
    tokens = _usage_of(data)
    if content is None or (isinstance(content, str) and not content.strip()):
        # A reasoning model that spent its allowance thinking sends nothing (or
        # null) as the content. That is a failed answer, not an empty one.
        _logger.error("Groq answered with no text (model=%s, finish_reason=%s, "
                      "reasoning_tokens=%s)", model, choice.get("finish_reason"), tokens[2])
        return None, gateway.empty_failure(gateway.GROQ), tokens
    if not isinstance(content, str):
        _logger.error("Groq answered 200 with non-text content (model=%s): %.800s",
                      model, response.text)
        return None, gateway.unreadable_failure(gateway.GROQ), tokens
    return Reply(text=content, total_tokens=tokens[3], model=model,
                 finish_reason=choice.get("finish_reason"), fallback_used=fallback_used,
                 call_id=call_id), None, tokens


async def _one_attempt(
    model: str, payload: dict, hints_sent: bool, *, api_key: str, timeout: float,
    transport: Optional[httpx.AsyncBaseTransport], call_id: str, fallback_used: bool,
) -> tuple[Optional[Reply], Optional[ProviderFailed], tuple, Optional[int], Optional[float]]:
    """One request to one model: (reply, failure, tokens, http_status, retry_after).
    Exactly one of reply and failure is set."""
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
        return None, gateway.timeout_failure(gateway.GROQ, timeout), (None, None, None, 0), None, None
    except httpx.HTTPError as exc:
        _logger.error("Could not reach Groq (model=%s): %r", model, exc)
        return None, gateway.network_failure(gateway.GROQ), (None, None, None, 0), None, None

    if response.status_code != 200:
        body = _body_of(response)
        # LOGGED before anything else: this is the evidence the old 502 threw
        # away. Groq's error body carries a code and a message, not the key.
        _logger.error("Groq refused: HTTP %s model=%s body=%.800s",
                      response.status_code, model, body)
        if hints_sent and _hint_rejected(response.status_code, body):
            rejected = ProviderFailed("an optional request parameter was rejected",
                                      kind=gateway.PARAM_REJECTED,
                                      provider_status=response.status_code)
            return None, rejected, (None, None, None, 0), response.status_code, None
        failure = gateway.failure_from_status(gateway.GROQ, response.status_code, body, model)
        return (None, failure, (None, None, None, 0), response.status_code,
                _retry_after(response))

    reply, failure, tokens = _read_reply(response, model, call_id, fallback_used)
    return reply, failure, tokens, response.status_code, None


async def chat_detailed(
    messages: list[dict],
    *,
    api_key: str,
    max_tokens: int,
    temperature: Optional[float] = None,
    timeout: float = DEFAULT_TIMEOUT_S,
    transport: Optional[httpx.AsyncBaseTransport] = None,
    feature: str = "unspecified",
    firm_id: Optional[str] = None,
    user_id: Optional[str] = None,
    redact: bool = True,
    reasoning_effort: Optional[str] = None,
    response_schema: Optional[JsonSchema] = None,
) -> Reply:
    """Ask Groq's text model, under the gateway's policy. Raises ProviderFailed —
    never returns a stand-in answer, and never an EMPTY one.

    `redact=False` is for document extraction ONLY, where the supplier's GSTIN is
    printed on the invoice being read. It is spelled at the call site so that a
    guard (tests/test_no_model_call_site_sends_an_identifier) can list every
    module that does it, by name, with the reason.
    """
    # Redacted HERE, once, at the one place a chat request is built, so a prompt
    # builder that forgets the rule still cannot send a PAN or a GSTIN
    # (domain/ai/redaction). The caller's own list is untouched.
    sendable = redact_messages(messages) if redact else [dict(m) for m in messages]
    chain = model_chain()
    call_id = gateway.new_call_id()
    deadline = gateway.clock() + gateway.TOTAL_BUDGET_S
    hints = True
    attempt_no = 0
    primary_failure: Optional[ProviderFailed] = None
    failure: Optional[ProviderFailed] = None
    out_of_time = False

    for index, model in enumerate(chain):
        tries = 0
        while True:
            remaining = deadline - gateway.clock()
            if remaining < gateway.MIN_ATTEMPT_S:
                out_of_time = True
                break
            tries += 1
            attempt_no += 1
            payload, hints_sent = build_request(
                model, sendable, max_tokens=max_tokens, temperature=temperature,
                reasoning_effort=reasoning_effort, response_schema=response_schema,
                hints=hints)
            started = gateway.clock()
            reply, failure, tokens, http_status, retry_after = await _one_attempt(
                model, payload, hints_sent, api_key=api_key,
                timeout=min(timeout, remaining), transport=transport,
                call_id=call_id, fallback_used=index > 0)
            latency_ms = int((gateway.clock() - started) * 1000)

            if reply is not None:
                outcome = gateway.TRUNCATED if reply.finish_reason == "length" else gateway.OK
                gateway.record(gateway.UsageEvent(
                    firm_id=firm_id, user_id=user_id, feature=feature, provider="groq",
                    model=model, call_id=call_id, attempt=attempt_no, outcome=outcome,
                    latency_ms=latency_ms, fallback_used=index > 0, http_status=http_status,
                    prompt_tokens=tokens[0], completion_tokens=tokens[1],
                    reasoning_tokens=tokens[2], total_tokens=tokens[3] or None))
                if outcome == gateway.TRUNCATED:
                    _logger.warning("Groq reply ended on the response budget (model=%s, "
                                    "max_tokens=%s, feature=%s)", model, max_tokens, feature)
                _answered_by.set(model)
                return reply

            assert failure is not None
            gateway.record(gateway.UsageEvent(
                firm_id=firm_id, user_id=user_id, feature=feature, provider="groq",
                model=model, call_id=call_id, attempt=attempt_no, outcome=failure.kind,
                latency_ms=latency_ms, fallback_used=index > 0, http_status=http_status,
                provider_code=failure.provider_code,
                prompt_tokens=tokens[0], completion_tokens=tokens[1],
                reasoning_tokens=tokens[2], total_tokens=tokens[3] or None))

            if failure.kind == gateway.PARAM_REJECTED:
                # The optional parameter is what Groq objected to. Go again on the
                # same model without it; this is not a failed try of the model.
                _logger.warning("Groq rejected an optional parameter (model=%s) — asking "
                                "again without reasoning_effort / response_format", model)
                hints = False
                tries -= 1
                continue

            step = gateway.decide(failure.kind, tries)
            if step == gateway.STOP:
                raise failure
            if step == gateway.RETRY:
                delay = gateway.backoff_delay(tries, retry_after)
                if delay is not None and deadline - gateway.clock() > delay + gateway.MIN_ATTEMPT_S:
                    await gateway.sleep_async(delay)
                    continue
            break  # the next model

        if index == 0:
            primary_failure = failure
        if out_of_time:
            break

    # Every model failed. The sentence is the PRIMARY model's: that is the one the
    # operator configured, and a retired primary is a standing fault whose remedy
    # (set GROQ_TEXT_MODEL) matters more than a fallback's transient one.
    final = primary_failure or failure
    if final is None:
        # The budget was gone before a single attempt could be made.
        final = gateway.timeout_failure(gateway.GROQ, gateway.TOTAL_BUDGET_S)
    raise final


async def chat(messages: list[dict], **kwargs: Any) -> tuple[str, int]:
    """Ask Groq's text model. Returns (reply, total_tokens). See `chat_detailed`
    for the arguments; this is the shape the assistant, the copilot and the
    digest were written against.

    `transport` exists for tests, which exercise THIS code against a stand-in
    Groq rather than a copy of it.
    """
    reply = await chat_detailed(messages, **kwargs)
    return reply.text, reply.total_tokens


def chat_sync(messages: list[dict], **kwargs: Any) -> Reply:
    """The same door for code that is already synchronous.

    The invoice and notice extractors are plain `def` routes (Starlette runs them
    in a threadpool, which is right: they read an upload, ask storage and parse a
    PDF), so they cannot `await`. This runs the ONE implementation on a private
    event loop rather than keeping a second synchronous copy of the retry policy
    — two copies are two policies that agree until one is changed.

    Must not be called from a thread that already has a running event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(chat_detailed(messages, **kwargs))
    raise RuntimeError("groq_text.chat_sync was called from inside a running event "
                       "loop; await groq_text.chat instead")
