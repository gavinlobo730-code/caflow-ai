"""
The policy every model call lives under, and the one record of it. (ai-04)

WHAT WAS WRONG
    Eight places called a model and each had its own idea of what a failure is.
    `domain/ai/groq_text.chat` (the assistant, the copilot's domain layer, the
    digest) classified a refusal into a sentence and had a 30-second timeout;
    `routers/ai_copilot.py` and `financial_analysis_service` built their own httpx
    request, the invoice and notice extractors used the vendor SDK with no
    timeout argument at all and answered a generic 502, and both Gemini calls
    had neither a timeout nor a retry. There was one model and no second route,
    so a model Groq retired (it already did, on 29-09-2026) or a Gemini model
    Google withdrew early took a whole feature out with a message that said
    "failed" and nothing tried anything else.

WHAT THIS MODULE IS
    Provider-agnostic policy, and nothing that builds a request. The request is
    built in ONE place per provider (`groq_text.chat`, `gemini_vision.generate`),
    which is where the PAN/GSTIN redaction already lives; this module is what
    both of them ask:

      * `model_chain` — the model that is configured, then the fallbacks that
        are CONFIGURED (`GROQ_TEXT_MODEL_FALLBACK`, `GEMINI_VISION_MODEL_FALLBACK`).
        There is deliberately no built-in fallback name: a default nobody has
        called is the 29-09-2026 mistake again (a model name written from a
        search summary and found dead on the first real request), and an unset
        fallback is a named, visible state rather than a guess.
      * `decide` — after a failed attempt, retry the same model, move to the
        next, or stop. A rate limit and a 5xx are retried with a bounded
        backoff; a retired model, a timeout and an empty reply move to the next
        model; a revoked key or an over-long prompt STOPS, because a second
        model behind the same key or the same prompt would fail the same way.
      * `failure_sentence` — what to tell the person who asked, per provider.
        The wording for Groq is exactly what `groq_text` has always said.
      * `UsageEvent` / `record` — one row per ATTEMPT: firm, feature, model,
        token counts, latency and outcome. NEVER a prompt, a reply, an
        identifier or a client name — the record has no field to hold one.

WHAT IT DOES NOT DO
    There is no per-firm monthly budget and no usage screen; those need this
    table and a screen for a Partner to read it, and are their own piece of work
    (the table is firm-scoped so that work can read it). The rate limiter in
    `middleware/rate_limit` is untouched and still asked first. What it DOES now
    keep, in memory, is the last attempt and the last answer per provider
    (`last_attempt`, `last_success`, `provider_status`), which `/health` and the
    Partner's AI status screen read (ai-06) — see `domain/ai/probe`.
"""
from __future__ import annotations

import contextvars
import functools
import inspect
import logging
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Optional

_logger = logging.getLogger("caflow.ai.gateway")

# ── the budget ───────────────────────────────────────────────────────────────

#: Everything one gateway call may spend — attempts, backoff and fallbacks
#: together. `lib/api` aborts at 45 seconds and never retries, so a call that is
#: still working at 45 is a call whose answer nobody receives.
TOTAL_BUDGET_S = 40.0
#: A model that has not answered with this long to spare is not tried again.
MIN_ATTEMPT_S = 1.0
#: Per model: the first attempt and ONE retry. Two more would turn a rate limit
#: into a wait nobody asked for; a different model is the better second try.
MAX_ATTEMPTS_PER_MODEL = 2
BACKOFF_BASE_S = 0.5
BACKOFF_CAP_S = 4.0
#: A `Retry-After` longer than this is not waited out in a request: the next
#: model is tried instead, and if there is none the person is told to wait.
RETRY_AFTER_CAP_S = 5.0

# ── what one attempt can end as ──────────────────────────────────────────────

OK = "ok"
#: Answered, non-empty, but cut off by the response budget. Returned as an
#: answer (the caller's own validation decides whether a cut-off reading is
#: usable) and recorded so the budget can be tuned from evidence.
TRUNCATED = "truncated"
EMPTY = "empty_reply"
BAD_SHAPE = "unreadable_reply"
TIMEOUT = "timeout"
NETWORK = "network"
RATE_LIMITED = "rate_limited"
SERVER_ERROR = "provider_error"
AUTH = "auth"
MODEL_GONE = "model_gone"
TOO_LONG = "too_long"
REFUSED = "refused"
#: The provider rejected an OPTIONAL request parameter (structured output,
#: reasoning effort). Never the end of a call: the call goes again without it.
PARAM_REJECTED = "param_rejected"

OUTCOMES = frozenset({
    OK, TRUNCATED, EMPTY, BAD_SHAPE, TIMEOUT, NETWORK, RATE_LIMITED, SERVER_ERROR,
    AUTH, MODEL_GONE, TOO_LONG, REFUSED, PARAM_REJECTED,
})

RETRY = "retry"
NEXT_MODEL = "next_model"
STOP = "stop"

#: A second model behind the SAME key or the SAME prompt fails the same way.
_STOPS = frozenset({AUTH, TOO_LONG, REFUSED})
#: Worth the same model once more, after a pause.
_RETRYABLE = frozenset({RATE_LIMITED, SERVER_ERROR, NETWORK})


def decide(outcome: str, attempt: int) -> str:
    """What to do after attempt number `attempt` (1-based, on this model) ended
    as `outcome`."""
    if outcome in _STOPS:
        return STOP
    if outcome in _RETRYABLE:
        return RETRY if attempt < MAX_ATTEMPTS_PER_MODEL else NEXT_MODEL
    # A timeout is not retried against the same model (a second wait of the same
    # length is the budget gone), a retired model and an empty or unreadable
    # reply will not change on a second ask.
    return NEXT_MODEL


def backoff_delay(retry_number: int, retry_after: Optional[float] = None) -> Optional[float]:
    """Seconds to pause before retry number `retry_number` (1-based), or None
    when the provider asked for longer than a request can wait.

    No jitter: this process makes a handful of calls a minute and the limiter in
    front of it is per firm, so there is no herd to spread, and a deterministic
    delay is one a test can assert."""
    delay = min(BACKOFF_CAP_S, BACKOFF_BASE_S * (2 ** max(0, retry_number - 1)))
    if retry_after is None:
        return delay
    if retry_after > RETRY_AFTER_CAP_S:
        return None
    return max(delay, retry_after)


# Indirections so a test can watch the pauses without waiting for them.
def sleep_sync(seconds: float) -> None:
    time.sleep(seconds)


async def sleep_async(seconds: float) -> None:
    import asyncio
    await asyncio.sleep(seconds)


def clock() -> float:
    return time.monotonic()


# ── the providers ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Provider:
    """Names, for the sentence a person reads."""
    name: str
    key_env: str
    model_env: str


GROQ = Provider("Groq", "GROQ_API_KEY", "GROQ_TEXT_MODEL")
GEMINI = Provider("Gemini", "GEMINI_API_KEY", "GEMINI_VISION_MODEL")


def models_in(raw: Optional[str]) -> list[str]:
    """A comma-separated list of model names, blanks dropped, order kept."""
    return [m.strip() for m in (raw or "").split(",") if m.strip()]


def model_chain(primary: str, fallback_env: str) -> list[str]:
    """`primary`, then whatever `fallback_env` names, each model once."""
    out: list[str] = []
    for m in [primary, *models_in(os.environ.get(fallback_env))]:
        if m and m not in out:
            out.append(m)
    return out


# ── the failure, and the sentence ───────────────────────────────────────────

class ProviderFailed(Exception):
    """A provider did not give an answer. `sentence` is written for the person
    who asked; `http_status` is what the API should answer with (502 when the
    provider refused, 504 when it did not answer in time); `kind` is the
    gateway's outcome word for it."""

    def __init__(self, sentence: str, *, http_status: int = 502,
                 provider_status: Optional[int] = None,
                 provider_code: Optional[str] = None,
                 kind: str = REFUSED) -> None:
        super().__init__(sentence)
        self.sentence = sentence
        self.http_status = http_status
        self.provider_status = provider_status
        self.provider_code = provider_code
        self.kind = kind


_MODEL_GONE_CODES = {"model_not_found", "model_decommissioned", "model_deprecated"}
_TOO_LONG_CODES = {"context_length_exceeded", "request_too_large"}


def error_parts(body: Any) -> tuple[Optional[str], str]:
    """(code, message) out of an OpenAI-compatible or Google error body, never
    raising."""
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


def _says_key_is_bad(low: str) -> bool:
    return "api key" in low and any(w in low for w in ("invalid", "not valid", "expired", "revoked"))


def classify(status: int, body: Any) -> str:
    """The outcome word for a non-200 answer."""
    code, message = error_parts(body)
    low = f"{code or ''} {message}".lower()
    if status == 401 or code == "invalid_api_key" or _says_key_is_bad(low):
        return AUTH
    if code in _MODEL_GONE_CODES or status == 404 or "decommission" in low or "does not exist" in low:
        return MODEL_GONE
    if status == 429 or code == "rate_limit_exceeded":
        return RATE_LIMITED
    if status == 413 or code in _TOO_LONG_CODES:
        return TOO_LONG
    if status >= 500 or status == 498:
        return SERVER_ERROR
    return REFUSED


def failure_sentence(provider: Provider, status: int, body: Any, model: str) -> tuple[str, Optional[str]]:
    """What to tell the person who asked, given the provider's status and body.

    Split by what the reader can DO about it, because "please try again" is
    right for a rate limit and useless for a revoked key — and those two used
    to get the same words."""
    code, message = error_parts(body)
    kind = classify(status, body)
    name = provider.name

    if kind == AUTH:
        # The provider's message is deliberately not echoed: some providers
        # quote part of the key back in it.
        return (f"The AI provider ({name}) rejected this server's API key "
                f"(HTTP {status}). {provider.key_env} on the server is invalid or has "
                "been revoked and must be replaced — retrying will not help."), code
    if kind == MODEL_GONE:
        return (f"The AI provider ({name}) no longer serves the model '{model}' "
                f"({code or f'HTTP {status}'}). Set {provider.model_env} on the server "
                "to a model " + name + " currently offers — retrying will not help."
                + (f" {name} said: {message[:300]}" if message else "")), code
    if kind == RATE_LIMITED:
        return (f"The AI provider ({name}) is rate-limiting this account right now. "
                "Wait a minute and ask again."), code
    if kind == TOO_LONG:
        return ("This question and the conversation before it are too long for "
                "the AI model. Start a new chat and ask again."), code
    if kind == SERVER_ERROR:
        return (f"The AI provider ({name}) is unavailable right now (HTTP {status}). "
                "Try again in a few minutes."), code
    return (f"The AI provider ({name}) refused the request (HTTP {status}"
            + (f", {code}" if code else "") + ")."
            + (f" {name} said: {message[:300]}" if message else "")), code


def timeout_failure(provider: Provider, seconds: float) -> ProviderFailed:
    return ProviderFailed(
        f"The AI provider ({provider.name}) did not answer within {int(seconds)} seconds. "
        "Try again; a shorter question may help.", http_status=504, kind=TIMEOUT)


def network_failure(provider: Provider) -> ProviderFailed:
    return ProviderFailed(
        f"This server could not reach the AI provider ({provider.name}). Try again in a "
        "few minutes.", http_status=502, kind=NETWORK)


def empty_failure(provider: Provider) -> ProviderFailed:
    """A reasoning model can spend its whole response budget thinking and send
    back nothing. That is a failed answer, not an answer that happens to be
    empty — presented as the latter it is a blank summary marked 'AI-written'."""
    return ProviderFailed(
        f"The AI provider ({provider.name}) answered without any text — the model used its "
        "whole response allowance before it wrote an answer. Try again; if it keeps "
        "happening, a shorter document or question helps.", http_status=502, kind=EMPTY)


def unreadable_failure(provider: Provider) -> ProviderFailed:
    return ProviderFailed(
        f"The AI provider ({provider.name}) answered in a shape this server could not "
        "read. Please report it.", http_status=502, kind=BAD_SHAPE)


def failure_from_status(provider: Provider, status: int, body: Any, model: str) -> ProviderFailed:
    sentence, code = failure_sentence(provider, status, body, model)
    return ProviderFailed(sentence, http_status=502, provider_status=status,
                          provider_code=code, kind=classify(status, body))


# ── a structured-output request, described once ──────────────────────────────

@dataclass(frozen=True)
class JsonSchema:
    """The shape a reply must have, for a provider that can be asked for it.

    A HINT, never the guarantee: the reply is validated against a pydantic
    model by whoever asked, because a model the provider does not offer this
    for (or one that ignores it) must be caught by the same check."""
    name: str
    schema: dict


# ── who is asking, for the two seams with a fixed signature ──────────────────

@dataclass(frozen=True)
class Scope:
    firm_id: Optional[str] = None
    user_id: Optional[str] = None
    feature: Optional[str] = None


_scope: contextvars.ContextVar[Scope] = contextvars.ContextVar("ai_usage_scope", default=Scope())


def current_scope() -> Scope:
    return _scope.get()


@contextmanager
def usage_scope(*, firm_id: Optional[str], user_id: Optional[str] = None,
                feature: Optional[str] = None) -> Iterator[Scope]:
    """Say who a block of model calls is for.

    Only for the two places whose signature is fixed by a seam — the copilot
    service's `_call_groq` (six callers and test doubles) and the statement
    reader's `ModelCall` — where threading `firm_id` through every layer would
    change a protocol. Everywhere else the caller passes `firm_id` and `feature`
    to the door itself, and a guard (`tests/test_every_model_call_is_attributed`)
    fails a call that does not."""
    token = _scope.set(Scope(firm_id=firm_id, user_id=user_id, feature=feature))
    try:
        yield _scope.get()
    finally:
        _scope.reset(token)


def attributed(feature: str) -> Callable:
    """Decorator for an `async def` method taking `firm_id` (and optionally
    `user_id`): the model calls beneath it are attributed to that firm."""
    def deco(fn: Callable) -> Callable:
        sig = inspect.signature(fn)

        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any):
            bound = sig.bind_partial(*args, **kwargs)
            with usage_scope(firm_id=bound.arguments.get("firm_id"),
                             user_id=bound.arguments.get("user_id"), feature=feature):
                return await fn(*args, **kwargs)
        return wrapper
    return deco


# ── the usage record ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class UsageEvent:
    """One attempt. Counts, a model name, a latency and an outcome — and
    deliberately nothing else. There is no text field, no client field and no
    identifier field, so a caller cannot put a prompt, a reply, a GSTIN or a
    client's name here by accident; `tests/test_a_usage_row_holds_no_text`
    holds that to the dataclass."""
    firm_id: Optional[str]
    user_id: Optional[str]
    feature: str
    provider: str
    model: str
    call_id: str
    attempt: int
    outcome: str
    latency_ms: int
    fallback_used: bool = False
    http_status: Optional[int] = None
    provider_code: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    reasoning_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    #: Images or pages sent, for the vision path — the unit that costs there.
    input_units: Optional[int] = None


def new_call_id() -> str:
    return uuid.uuid4().hex


_sink: Optional[Callable[[UsageEvent], None]] = None
_writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ai-usage")
_pending = 0
_pending_lock = threading.Lock()
#: A database that has stopped answering must not grow an unbounded queue of
#: rows nobody will read; past this the row is logged and dropped.
_MAX_PENDING = 500


def set_sink(fn: Optional[Callable[[UsageEvent], None]]) -> None:
    """Replace where usage goes (tests); None restores the default."""
    global _sink
    _sink = fn


def _as_uuid(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError):
        return None


def _write_row(ev: UsageEvent) -> None:
    """The one INSERT. The payload is written out as a literal so
    `tests/_backend_query_parser` can read its keys against the real schema; a
    payload held in a name would make this write invisible to it (its unreadable
    budget is exact)."""
    global _pending
    try:
        from core.supabase_client import get_service_supabase
        get_service_supabase().table("ai_usage_events").insert({
            "firm_id": ev.firm_id,
            "user_id": _as_uuid(ev.user_id),
            "feature": ev.feature,
            "provider": ev.provider,
            "model": ev.model,
            "call_id": ev.call_id,
            "attempt": ev.attempt,
            "outcome": ev.outcome,
            "fallback_used": ev.fallback_used,
            "http_status": ev.http_status,
            "provider_code": ev.provider_code,
            "latency_ms": ev.latency_ms,
            "prompt_tokens": ev.prompt_tokens,
            "completion_tokens": ev.completion_tokens,
            "reasoning_tokens": ev.reasoning_tokens,
            "total_tokens": ev.total_tokens,
            "input_units": ev.input_units,
        }).execute()
    except Exception:                                            # noqa: BLE001
        # A usage row that was not kept must never cost anybody an answer, and
        # the failure is logged WITHOUT the row.
        _logger.warning("ai_usage: could not keep a usage row for feature=%s", ev.feature,
                        exc_info=True)
    finally:
        with _pending_lock:
            _pending -= 1


def _default_sink(ev: UsageEvent) -> None:
    global _pending
    _logger.info(
        "ai_usage firm=%s feature=%s provider=%s model=%s attempt=%d outcome=%s "
        "status=%s tokens=%s latency_ms=%d fallback=%s",
        ev.firm_id, ev.feature, ev.provider, ev.model, ev.attempt, ev.outcome,
        ev.http_status, ev.total_tokens, ev.latency_ms, ev.fallback_used)
    # A row needs a firm to belong to, and a database to go to.
    if not ev.firm_id or not os.environ.get("SUPABASE_URL"):
        return
    with _pending_lock:
        if _pending >= _MAX_PENDING:
            _logger.warning("ai_usage: write queue full — row for feature=%s dropped", ev.feature)
            return
        _pending += 1
    try:
        _writer.submit(_write_row, ev)
    except Exception:                                            # noqa: BLE001
        with _pending_lock:
            _pending -= 1
        _logger.warning("ai_usage: could not queue a usage row", exc_info=True)


# ── what this process has SEEN a provider do ────────────────────────────────
#
# THE QUESTION (ai-06): "does the AI answer at all, live?" Nothing could say. The
# usage table says it per firm and only once somebody has made a call, so the
# gateway also keeps, IN THIS PROCESS, the last attempt and the last success per
# provider. It is read by `/health` (one word per provider, no database call, so
# the route stays what Render's health check needs it to be) and by the Partner's
# AI status screen. It is memory, so a restart forgets it and the honest answer
# after a restart is `unverified`, never `ok`.

#: Outcomes that mean the provider ANSWERED. A reply cut off by the response
#: budget is still an answer; every other outcome is a failure of the attempt.
ANSWERED = frozenset({OK, TRUNCATED})

STATUS_OK = "ok"
STATUS_FAILING = "failing"
STATUS_UNVERIFIED = "unverified"
STATUS_NOT_CONFIGURED = "not_configured"


@dataclass(frozen=True)
class Seen:
    """One attempt, reduced to what a status screen needs. No text, no firm."""
    provider: str
    model: str
    outcome: str
    at: float            # epoch seconds, UTC
    latency_ms: int
    total_tokens: Optional[int] = None
    http_status: Optional[int] = None


_seen_lock = threading.Lock()
_last_attempt: dict[str, Seen] = {}
_last_success: dict[str, Seen] = {}


def reset_health() -> None:
    """Forget what this process has seen. For tests, and for nothing else: the
    honest state after a restart is the empty one."""
    with _seen_lock:
        _last_attempt.clear()
        _last_success.clear()


def _note(ev: UsageEvent) -> None:
    # A PARAM_REJECTED attempt is the gateway's own housekeeping (the call goes
    # again without the hint) and says nothing about whether the provider works.
    if ev.outcome == PARAM_REJECTED:
        return
    seen = Seen(provider=ev.provider, model=ev.model, outcome=ev.outcome,
                at=time.time(), latency_ms=ev.latency_ms,
                total_tokens=ev.total_tokens, http_status=ev.http_status)
    with _seen_lock:
        _last_attempt[ev.provider] = seen
        if ev.outcome in ANSWERED:
            _last_success[ev.provider] = seen


def last_attempt(provider: str) -> Optional[Seen]:
    with _seen_lock:
        return _last_attempt.get(provider)


def last_success(provider: str) -> Optional[Seen]:
    with _seen_lock:
        return _last_success.get(provider)


def provider_status(provider: str, configured: bool) -> str:
    """One word. `not_configured` is its own state because a missing key and a
    provider nobody has called yet send a person to different places; `failing`
    is the LAST attempt failing (an earlier success does not hide it);
    `unverified` is the honest answer to "has it ever worked, since this process
    started" when nothing has been asked of it."""
    if not configured:
        return STATUS_NOT_CONFIGURED
    attempt = last_attempt(provider)
    if attempt is None:
        return STATUS_UNVERIFIED
    return STATUS_OK if attempt.outcome in ANSWERED else STATUS_FAILING


def record(ev: UsageEvent) -> None:
    """Hand one attempt to the sink. Never raises."""
    try:
        _note(ev)
    except Exception:                                            # noqa: BLE001
        _logger.warning("ai_health: could not note an attempt", exc_info=True)
    try:
        (_sink or _default_sink)(ev)
    except Exception:                                            # noqa: BLE001
        _logger.warning("ai_usage: the usage sink failed", exc_info=True)
