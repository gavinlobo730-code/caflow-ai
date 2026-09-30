"""
A stored copilot reply records the model that actually answered (ai-06, part of it).

`add_message` defaulted `model_used` to "llama-3.3-70b-versatile" — the model Groq
retired on this account — and the column's own default is the same string, so every
stored reply and recommendation named a model that was never asked. Nothing computes
from the label, which is why it sat there; it is the record a CA would read to learn
what answered, and it was wrong.
"""
from domain.ai import groq_text
from repositories.ai_copilot_repository import AICopilotRepository


def _repo():
    return AICopilotRepository()


def test_an_assistant_reply_records_the_configured_model(monkeypatch):
    monkeypatch.setenv("GROQ_TEXT_MODEL", "some/configured-model")
    msg = _repo().add_message("f1", "conv-x", "assistant", "an answer", tokens_used=12)
    assert msg["model_used"] == "some/configured-model"


def test_it_follows_the_default_when_nothing_is_configured(monkeypatch):
    monkeypatch.delenv("GROQ_TEXT_MODEL", raising=False)
    msg = _repo().add_message("f1", "conv-x", "assistant", "an answer")
    assert msg["model_used"] == groq_text.DEFAULT_TEXT_MODEL
    assert "llama-3.3-70b-versatile" not in str(msg["model_used"])


def test_a_user_message_names_no_model():
    assert _repo().add_message("f1", "conv-x", "user", "a question")["model_used"] is None


def test_an_explicit_model_is_respected():
    msg = _repo().add_message("f1", "conv-x", "assistant", "a", model_used="explicit/model")
    assert msg["model_used"] == "explicit/model"


def test_a_new_recommendation_records_the_configured_model(monkeypatch):
    monkeypatch.setenv("GROQ_TEXT_MODEL", "some/configured-model")
    rec = _repo().create_recommendation("f1", {"title": "t", "priority": "high"})
    assert rec["model_used"] == "some/configured-model"
