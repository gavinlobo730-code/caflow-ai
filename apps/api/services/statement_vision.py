"""
The one network call behind domain/banking/vision.py.

Kept to almost nothing on purpose. Everything worth testing — the prompt, the
parsing, the refusals, the arithmetic that gates the import — lives in the
domain module and is exercised with an injected fake. What is here is the part
that cannot be tested without a key, so it is the part with no decisions in it.

Gemini rather than Groq for the same reason routers/document_intelligence_v1.py
gives: Groq's vision offering returned a live 404 model_not_found on this
account, and Gemini's free tier is multimodal-native and already provisioned.
The model name is read from the environment because Google has retired a model
ahead of its announced shutdown before.

And it no longer imports the vendor SDK (ai-04): the call goes through
`domain/ai/gemini_vision.generate`, the one door, which gives it a timeout, a
bounded retry, the configured fallback model (GEMINI_VISION_MODEL_FALLBACK), a
classified failure and a usage row. The page being read is DATA, not an
instruction, and the system instruction says so (domain/ai/untrusted).

WHO IS ASKING comes from `gateway.current_scope()`, not from an argument: this
function is handed to `vision.read_statement` as a `ModelCall` — `(image, mime,
prompt) -> text` — and widening that protocol for the usage record would change
every fake in the statement tests. The router that owns the request sets the
scope around the calls.
"""
from __future__ import annotations

import os

from domain.ai import gateway, gemini_vision, untrusted


def available() -> bool:
    """Whether a scan can be read at all. Checked BEFORE a file is rasterised,
    so a deployment with no key refuses in one sentence instead of doing the
    expensive half of the work and then failing."""
    return gemini_vision.available()


def call(*, image: bytes, mime: str, prompt: str) -> str:
    """One page to the vision model; its raw text back. Matches vision.ModelCall.

    Raises `gateway.ProviderFailed` — never returns nothing: an empty reply is a
    failure here, as everywhere (the old `response.text or ""` turned one into an
    empty page that the statement reader then reported as "no transactions")."""
    scope = gateway.current_scope()
    return gemini_vision.generate(
        api_key=os.environ.get("GEMINI_API_KEY", ""),
        images=[image],
        mime=mime,
        prompt=prompt,
        system_instruction=untrusted.image_system_instruction(),
        feature=scope.feature or "statement_scan",
        firm_id=scope.firm_id,
        user_id=scope.user_id,
    )
