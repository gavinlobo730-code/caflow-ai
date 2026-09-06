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
"""
from __future__ import annotations

import os

#: Same two variables the invoice path uses. Adding a third name for one key
#: would mean two places to rotate it.
_GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
_GEMINI_VISION_MODEL = os.environ.get("GEMINI_VISION_MODEL", "gemini-3.5-flash")


def available() -> bool:
    """Whether a scan can be read at all. Checked BEFORE a file is rasterised,
    so a deployment with no key refuses in one sentence instead of doing the
    expensive half of the work and then failing."""
    return bool(_GEMINI_KEY)


def call(*, image: bytes, mime: str, prompt: str) -> str:
    """One page to the vision model; its raw text back. Matches vision.ModelCall."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=_GEMINI_KEY)
    response = client.models.generate_content(
        model=_GEMINI_VISION_MODEL,
        contents=[types.Part.from_bytes(data=image, mime_type=mime), prompt],
    )
    return response.text or ""
