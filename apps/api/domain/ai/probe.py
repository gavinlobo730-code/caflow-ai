"""
One tiny real call per provider, and what it says about whether the AI works. (ai-06)

WHAT WAS WRONG
    The Groq default was changed on 29-09-2026 after a live `model_not_found` 404
    on the old one, to a name taken from a search summary and graded `[S]` in the
    code, and **no successful live call was ever recorded anywhere**. Production
    on 01-10-2026 held no `ai_usage_events` row at all and two stored assistant
    replies, both from 27-09-2026, both `tokens_used = 0` — the canned mock text
    under the retired model's name. Nothing in the product could say whether the
    assistant, the invoice reader or the copilot answers at all, and the first
    person to find out would have been a CA in front of a client.

WHAT THIS IS
    A probe a Partner can press. It makes ONE small real call to a provider
    through the same door every feature uses (`groq_text.chat_sync`,
    `gemini_vision.generate`), so it exercises the real key, the real model name,
    the real retry and fallback policy and writes the real usage row — which is
    where "last success" is kept. It builds no request of its own and imports no
    SDK (`tests/test_the_ai_gateway_retries_falls_back_and_says_why.py` fails a
    ninth call site).

    * A FAILURE IS A RESULT, NOT AN ERROR. A person pressing "check" wants to be
      told which of a retired model, a revoked key, a timeout or an empty reply it
      was, in the gateway's own sentence — not a 502.
    * AN ABSENT KEY IS NOT A FAILURE. It is `skipped`, with the setting named,
      because nobody called anything.
    * IT SENDS NOTHING ABOUT ANY CLIENT. The prompt is a fixed sentence and the
      picture is a plain white square, so what leaves for the provider is the same
      on every firm and carries no identifier and no document.

WHAT IT DOES NOT PROVE
    That the structured-output and reasoning hints a document reader sends are
    accepted (the probe sends no schema — those are asked once per feature and the
    gateway already retries without them), and that a LONG document fits the
    response budget. It proves the key works and the configured model answers.
"""
from __future__ import annotations

import os
import struct
import zlib
from dataclasses import dataclass
from typing import Callable, Optional

from domain.ai import gateway, gemini_vision, groq_text

#: What the usage row's `feature` says, so a probe is never counted as a
#: customer's own use.
FEATURE = "probe"

PROMPT = "Reply with the single word OK."
#: Reasoning is drawn from the same allowance as the answer on the default model,
#: so a few tokens would come back EMPTY and the probe would report a healthy
#: provider as broken. 512 is generous for one word, and `reasoning_effort: low`
#: is a hint the door sends only to a family Groq documents it for.
GROQ_MAX_TOKENS = 512

PROVIDERS = ("groq", "gemini")


def _white_png(size: int = 64) -> bytes:
    """A plain white square, built here so no binary file is committed and no
    imaging library is needed. Deterministic, and valid by construction (each
    chunk's CRC is computed over its own type and data)."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", size, size, 8, 0, 0, 0, 0)       # 8-bit greyscale
    rows = b"".join(b"\x00" + b"\xff" * size for _ in range(size))    # filter 0, white
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


@dataclass(frozen=True)
class ProbeResult:
    provider: str
    #: "ok" — it answered; "failed" — it did not; "skipped" — nothing was asked.
    state: str
    #: The model that was ASKED FOR (the configured one), and the one that
    #: ANSWERED, which differs only when a configured fallback took over.
    model: str
    answered_by: Optional[str] = None
    latency_ms: Optional[int] = None
    total_tokens: Optional[int] = None
    #: The sentence a person reads: why it failed, or why it was not asked.
    sentence: Optional[str] = None
    #: The gateway's outcome word for a failure (`model_gone`, `auth`, …).
    kind: Optional[str] = None
    http_status: Optional[int] = None

    @property
    def ok(self) -> bool:
        return self.state == "ok"

    @property
    def tone(self) -> str:
        """The Callout tone the screen draws this in, chosen HERE so the browser
        keeps no vocabulary of its own: an answer is a settled `note`, a failure is
        a `problem`, and a probe that asked nothing needs a person to set a key."""
        return {"ok": "note", "failed": "problem"}.get(self.state, "attention")

    def as_dict(self) -> dict:
        return {
            "provider": self.provider, "state": self.state, "model": self.model,
            "answered_by": self.answered_by, "latency_ms": self.latency_ms,
            "total_tokens": self.total_tokens, "sentence": self.sentence,
            "kind": self.kind, "http_status": self.http_status, "tone": self.tone,
        }


def configured(provider: str) -> bool:
    if provider == "groq":
        return bool(os.environ.get(gateway.GROQ.key_env))
    if provider == "gemini":
        return gemini_vision.available()
    raise KeyError(f"unknown provider {provider!r}")


def configured_model(provider: str) -> str:
    if provider == "groq":
        return groq_text.text_model()
    if provider == "gemini":
        return gemini_vision.vision_model()
    raise KeyError(f"unknown provider {provider!r}")


def _skipped(provider: str, env_name: str, what: str) -> ProbeResult:
    return ProbeResult(
        provider=provider, state="skipped", model=configured_model(provider),
        sentence=f"{env_name} is not set on this server, so nothing was asked. {what}")


def _failed(provider: str, exc: gateway.ProviderFailed, latency_ms: int) -> ProbeResult:
    return ProbeResult(
        provider=provider, state="failed", model=configured_model(provider),
        latency_ms=latency_ms, sentence=exc.sentence, kind=exc.kind,
        http_status=exc.http_status)


def probe_groq(*, firm_id: Optional[str], user_id: Optional[str] = None,
               transport=None) -> ProbeResult:
    """One small text request to the configured Groq model."""
    key = os.environ.get(gateway.GROQ.key_env)
    if not key:
        return _skipped("groq", gateway.GROQ.key_env,
                        "The assistant, the copilot and PDF invoice reading all need it.")
    started = gateway.clock()
    kwargs = {"transport": transport} if transport is not None else {}
    try:
        reply = groq_text.chat_sync(
            [{"role": "user", "content": PROMPT}],
            api_key=key, max_tokens=GROQ_MAX_TOKENS, temperature=0,
            reasoning_effort="low", feature=FEATURE, firm_id=firm_id, user_id=user_id,
            **kwargs)
    except gateway.ProviderFailed as exc:
        return _failed("groq", exc, int((gateway.clock() - started) * 1000))
    return ProbeResult(
        provider="groq", state="ok", model=configured_model("groq"),
        answered_by=reply.model, latency_ms=int((gateway.clock() - started) * 1000),
        total_tokens=reply.total_tokens)


def probe_gemini(*, firm_id: Optional[str], user_id: Optional[str] = None,
                 generate: Optional[Callable[..., str]] = None) -> ProbeResult:
    """One small picture request to the configured Gemini model."""
    key = os.environ.get(gateway.GEMINI.key_env)
    if not key:
        return _skipped("gemini", gateway.GEMINI.key_env,
                        "Reading a photographed bill or a scanned PDF needs it; "
                        "typed PDFs and everything else do not.")
    started = gateway.clock()
    ask = generate or gemini_vision.generate
    try:
        ask(api_key=key, images=[_white_png()], mime="image/png", prompt=PROMPT,
            feature=FEATURE, firm_id=firm_id, user_id=user_id)
    except gateway.ProviderFailed as exc:
        return _failed("gemini", exc, int((gateway.clock() - started) * 1000))
    seen = gateway.last_success("gemini")
    return ProbeResult(
        provider="gemini", state="ok", model=configured_model("gemini"),
        answered_by=seen.model if seen else None,
        latency_ms=int((gateway.clock() - started) * 1000),
        total_tokens=seen.total_tokens if seen else None)


def probe(provider: str, *, firm_id: Optional[str], user_id: Optional[str] = None) -> ProbeResult:
    if provider == "groq":
        return probe_groq(firm_id=firm_id, user_id=user_id)
    if provider == "gemini":
        return probe_gemini(firm_id=firm_id, user_id=user_id)
    raise KeyError(f"unknown provider {provider!r}")
