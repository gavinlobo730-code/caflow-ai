"""
Government-notice extraction asks Groq for the model GROQ_TEXT_MODEL names.

WHAT WAS WRONG
    routers/document_intelligence_v2._extract_with_groq hardcoded
    model="llama-3.3-70b-versatile" while v1 reads GROQ_TEXT_MODEL. CLAUDE.md
    makes the env var the whole plan for a retired model ("the next
    retirement is a config change"), so setting it would have moved invoice
    extraction and left notice extraction asking for the old name — which the
    endpoint can only report as its generic 502.

WHAT IS ASSERTED — by calling the code with a stand-in Groq client
    * the model sent is the one the environment names;
    * with nothing set, it is v1's default, so the two paths cannot disagree.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

_MODULE = Path(__file__).resolve().parents[1] / "routers" / "document_intelligence_v2.py"


def _fresh_copy(monkeypatch, env_value):
    """A private copy of the router module, imported under the given
    environment. A copy rather than importlib.reload, so the router object the
    app already mounted is left alone for every other test."""
    if env_value is None:
        monkeypatch.delenv("GROQ_TEXT_MODEL", raising=False)
    else:
        monkeypatch.setenv("GROQ_TEXT_MODEL", env_value)
    spec = importlib.util.spec_from_file_location("_dv2_copy_for_model_test", _MODULE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def groq_calls(monkeypatch):
    """Stand in for the `groq` package and record every completion request."""
    calls: list[dict] = []

    class _Completions:
        def create(self, **kwargs):
            calls.append(kwargs)
            msg = types.SimpleNamespace(content='{"authority": "GSTN"}')
            return types.SimpleNamespace(
                choices=[types.SimpleNamespace(message=msg)])

    class _Groq:
        def __init__(self, api_key=None):
            self.chat = types.SimpleNamespace(completions=_Completions())

    monkeypatch.setitem(sys.modules, "groq", types.SimpleNamespace(Groq=_Groq))
    return calls


def test_the_model_sent_is_the_one_the_environment_names(monkeypatch, groq_calls):
    mod = _fresh_copy(monkeypatch, "llama-4-something-newer")
    assert mod._extract_with_groq("DRC-01 notice text") == {"authority": "GSTN"}
    assert groq_calls[-1]["model"] == "llama-4-something-newer"


def test_with_nothing_set_it_is_the_same_default_invoice_extraction_uses(
        monkeypatch, groq_calls):
    from domain.ai.groq_text import DEFAULT_TEXT_MODEL

    mod = _fresh_copy(monkeypatch, None)
    mod._extract_with_groq("DRC-01 notice text")

    v1_spec = importlib.util.spec_from_file_location(
        "_dv1_copy_for_model_test", _MODULE.with_name("document_intelligence_v1.py"))
    v1 = importlib.util.module_from_spec(v1_spec)
    v1_spec.loader.exec_module(v1)
    assert groq_calls[-1]["model"] == v1._GROQ_TEXT_MODEL == DEFAULT_TEXT_MODEL
