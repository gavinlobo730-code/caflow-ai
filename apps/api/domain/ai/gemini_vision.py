"""
The one way to ask Gemini to read a picture, under the same policy as Groq. (ai-04)

WHAT WAS WRONG
    Two call sites — the invoice reader in `routers/document_intelligence_v1` and
    the scanned-statement reader in `services/statement_vision` — each built a
    `genai.Client` and called `generate_content` with no timeout argument, no
    retry, no second model and no record of what the call cost. The repo's own
    notes record that Google retired `gemini-2.5-flash` AHEAD of its announced
    shutdown date, so "the next retirement is a config change" was a plan with
    nothing behind it for the vision path: one retired model and every
    photographed bill and every scanned statement stops with a generic 502.

WHAT THIS MODULE IS
    `generate` is the only function in the codebase that imports `google.genai`.
    It asks `domain/ai/gateway` the same questions `groq_text` does — a bounded
    retry on a rate limit or a 5xx, the configured fallback model
    (`GEMINI_VISION_MODEL_FALLBACK`; none is built in, for the reason the gateway
    gives), the classified sentence for each failure, an EMPTY reply treated as a
    failure and a usage row per attempt — so a person is told the same thing in
    the same words whichever provider failed.

    It is SYNCHRONOUS on purpose: both callers are plain `def` code running in a
    threadpool (the statement reader hands it to `vision.read_statement` as a
    `ModelCall`), and an `async` door would need a second copy of the policy.

WHAT IS NOT DONE
    No redaction: what is sent is a PICTURE of a document, and the identifier on
    it is the thing being read — the same reason `document_intelligence_v1` is
    exempt for text, named in `tests/test_no_model_call_site_sends_an_identifier`.
    The structured-output hint (`response_schema`) is a hint, exactly as on Groq:
    if Gemini rejects it the call goes again without it, and the caller validates
    the reply against its own pydantic model either way.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

from domain.ai import gateway

_logger = logging.getLogger("caflow.ai.gemini")

#: gemini-2.5-flash was retired by Google ahead of its announced shutdown date
#: (a live 404 "no longer available to new users" — a known, reported issue, not
#: specific to this account). gemini-3.5-flash is the current free-tier
#: vision-capable model as of that fix. Overridable, because the next retirement
#: is a config change.
DEFAULT_VISION_MODEL = "gemini-3.5-flash"
DEFAULT_TIMEOUT_S = 30.0

_HINT_WORDS = ("response_schema", "response_mime_type", "responseschema", "schema",
               "mime type", "response mime")


def vision_model() -> str:
    return (os.environ.get("GEMINI_VISION_MODEL") or "").strip() or DEFAULT_VISION_MODEL


def fallback_models() -> list[str]:
    return gateway.models_in(os.environ.get("GEMINI_VISION_MODEL_FALLBACK"))


def model_chain() -> list[str]:
    return gateway.model_chain(vision_model(), "GEMINI_VISION_MODEL_FALLBACK")


def available() -> bool:
    """Whether a picture can be read at all on this deployment."""
    return bool(os.environ.get("GEMINI_API_KEY"))


# ── what an SDK exception means ──────────────────────────────────────────────

def _class_names(exc: BaseException) -> str:
    return " ".join(c.__name__.lower() for c in type(exc).__mro__)


def _is_timeout(exc: BaseException) -> bool:
    return isinstance(exc, TimeoutError) or "timeout" in _class_names(exc)


def _is_network(exc: BaseException) -> bool:
    names = _class_names(exc)
    return any(w in names for w in ("connectionerror", "connecterror", "networkerror",
                                    "httperror", "requestexception", "protocolerror"))


def _api_status_and_body(exc: BaseException) -> tuple[Optional[int], Any]:
    """(HTTP status, an OpenAI-shaped error body) for the SDK's own API error."""
    code = getattr(exc, "code", None)
    if not isinstance(code, int) or isinstance(code, bool):
        return None, None
    body = {"error": {"code": code, "message": str(getattr(exc, "message", "") or ""),
                      "status": str(getattr(exc, "status", "") or "")}}
    return code, body


def _hint_rejected(status: int, body: Any) -> bool:
    if status not in (400, 422):
        return False
    code, message = gateway.error_parts(body)
    text = f"{code or ''} {message}".lower()
    return any(w in text for w in _HINT_WORDS)


def _usage_of(response: Any) -> tuple[Optional[int], Optional[int], Optional[int], Optional[int]]:
    u = getattr(response, "usage_metadata", None)
    if u is None:
        return None, None, None, None

    def _n(name: str) -> Optional[int]:
        v = getattr(u, name, None)
        return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None
    return (_n("prompt_token_count"), _n("candidates_token_count"),
            _n("thoughts_token_count"), _n("total_token_count"))


def _text_of(response: Any) -> Optional[str]:
    """The reply's text, or None. `.text` itself can raise when a reply has no
    text part (a safety block), which is an empty reply and not a crash."""
    try:
        text = getattr(response, "text", None)
    except Exception:                                            # noqa: BLE001
        return None
    return text if isinstance(text, str) else None


def generate(
    *,
    api_key: str,
    images: list[bytes],
    mime: str,
    prompt: str,
    system_instruction: Optional[str] = None,
    response_schema: Any = None,
    feature: str,
    firm_id: Optional[str] = None,
    user_id: Optional[str] = None,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> str:
    """One or more page images of ONE document, and the instruction, to Gemini;
    its text back. Raises `gateway.ProviderFailed` — never returns nothing.

    `response_schema` is the OpenAPI-subset dict Gemini documents for structured
    output; see the module note on why it is only a hint.
    """
    from google import genai
    from google.genai import types

    # The firm's monthly allowance, asked BEFORE anything is sent: a document that would
    # take the firm past its page allowance is refused whole, never read in part (ai-17).
    gateway.enforce_budget(provider="gemini", model=vision_model(), firm_id=firm_id,
                           user_id=user_id, feature=feature, pages_wanted=len(images))

    chain = model_chain()
    call_id = gateway.new_call_id()
    deadline = gateway.clock() + gateway.TOTAL_BUDGET_S
    hints = True
    attempt_no = 0
    primary_failure: Optional[gateway.ProviderFailed] = None
    failure: Optional[gateway.ProviderFailed] = None
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
            attempt_timeout = min(timeout, remaining)
            hints_sent = bool(hints and (response_schema is not None))
            started = gateway.clock()
            status: Optional[int] = None
            retry_after: Optional[float] = None
            response: Any = None
            failure = None

            try:
                config_kwargs: dict[str, Any] = {}
                if system_instruction:
                    config_kwargs["system_instruction"] = system_instruction
                if hints_sent:
                    config_kwargs["response_mime_type"] = "application/json"
                    config_kwargs["response_schema"] = response_schema
                client = genai.Client(
                    api_key=api_key,
                    http_options=types.HttpOptions(timeout=int(attempt_timeout * 1000)))
                kwargs: dict[str, Any] = {
                    "model": model,
                    "contents": [
                        *[types.Part.from_bytes(data=img, mime_type=mime) for img in images],
                        prompt,
                    ],
                }
                if config_kwargs:
                    kwargs["config"] = types.GenerateContentConfig(**config_kwargs)
                response = client.models.generate_content(**kwargs)
            except Exception as exc:                             # noqa: BLE001 — SDK errors
                api_status, body = _api_status_and_body(exc)
                if api_status is not None:
                    status = api_status
                    _logger.error("Gemini refused: HTTP %s model=%s body=%.800s",
                                  api_status, model, body)
                    if hints_sent and _hint_rejected(api_status, body):
                        failure = gateway.ProviderFailed(
                            "an optional request parameter was rejected",
                            kind=gateway.PARAM_REJECTED, provider_status=api_status)
                    else:
                        failure = gateway.failure_from_status(
                            gateway.GEMINI, api_status, body, model)
                elif _is_timeout(exc):
                    _logger.error("Gemini did not answer within %ss (model=%s): %r",
                                  attempt_timeout, model, exc)
                    failure = gateway.timeout_failure(gateway.GEMINI, attempt_timeout)
                elif _is_network(exc):
                    _logger.error("Could not reach Gemini (model=%s): %r", model, exc)
                    failure = gateway.network_failure(gateway.GEMINI)
                elif hints_sent:
                    # The SDK refused to BUILD the request around the schema.
                    _logger.warning("Gemini request could not be built with a response "
                                    "schema (%s) — asking again without it", type(exc).__name__)
                    failure = gateway.ProviderFailed(
                        "an optional request parameter was rejected",
                        kind=gateway.PARAM_REJECTED)
                else:
                    _logger.error("Gemini call failed (model=%s): %s: %s",
                                  model, type(exc).__name__, exc)
                    failure = gateway.ProviderFailed(
                        "The AI provider (Gemini) could not complete the request. "
                        "Please report it.", http_status=502, kind=gateway.REFUSED)
            latency_ms = int((gateway.clock() - started) * 1000)
            tokens = _usage_of(response) if response is not None else (None, None, None, None)

            if failure is None:
                text = _text_of(response)
                if not text or not text.strip():
                    _logger.error("Gemini answered with no text (model=%s)", model)
                    failure = gateway.empty_failure(gateway.GEMINI)
                else:
                    gateway.record(gateway.UsageEvent(
                        firm_id=firm_id, user_id=user_id, feature=feature, provider="gemini",
                        model=model, call_id=call_id, attempt=attempt_no, outcome=gateway.OK,
                        latency_ms=latency_ms, fallback_used=index > 0, http_status=200,
                        prompt_tokens=tokens[0], completion_tokens=tokens[1],
                        reasoning_tokens=tokens[2], total_tokens=tokens[3],
                        input_units=len(images)))
                    return text

            gateway.record(gateway.UsageEvent(
                firm_id=firm_id, user_id=user_id, feature=feature, provider="gemini",
                model=model, call_id=call_id, attempt=attempt_no, outcome=failure.kind,
                latency_ms=latency_ms, fallback_used=index > 0, http_status=status,
                provider_code=failure.provider_code, prompt_tokens=tokens[0],
                completion_tokens=tokens[1], reasoning_tokens=tokens[2],
                total_tokens=tokens[3], input_units=len(images)))

            if failure.kind == gateway.PARAM_REJECTED:
                hints = False
                tries -= 1
                continue

            step = gateway.decide(failure.kind, tries)
            if step == gateway.STOP:
                raise failure
            if step == gateway.RETRY:
                delay = gateway.backoff_delay(tries, retry_after)
                if delay is not None and deadline - gateway.clock() > delay + gateway.MIN_ATTEMPT_S:
                    gateway.sleep_sync(delay)
                    continue
            break  # the next model

        if index == 0:
            primary_failure = failure
        if out_of_time:
            break

    final = primary_failure or failure
    if final is None:
        final = gateway.timeout_failure(gateway.GEMINI, gateway.TOTAL_BUDGET_S)
    raise final
