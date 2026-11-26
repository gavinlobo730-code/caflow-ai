"""An AI provider account whose prepaid balance has run out is told to the person in words (POST-A-564).

Google's billing page says (read on 25-11-2026 only as a search summary) that when a prepaid balance reaches zero every
key on the account stops and requests are refused with HTTP 402 until credit is added. The gateway had no outcome for
it, so the person was told the provider "refused the request (HTTP 402)" and nothing about what to do. Now: its own
outcome, its own sentence (whoever pays for the account adds credit; trying again will not help), no retry and no
second model, and Google's older 429 that points at the plan and billing is told apart from an ordinary rate limit.
"""
import asyncio

import httpx
import pytest

from domain.ai import gateway, groq_text

OK_BODY = {"choices": [{"message": {"content": "fine"}, "finish_reason": "stop"}],
           "usage": {"prompt_tokens": 1, "completion_tokens": 1}}


def _err(status, code=None, message="x"):
    return status, {"error": {"code": code, "message": message}}


@pytest.mark.parametrize("status,code,message", [
    (402, None, "Payment required"),
    (402, "PAYMENT_REQUIRED", "Your prepaid credit balance is depleted."),
    (429, "RESOURCE_EXHAUSTED", "You exceeded your current quota, please check your plan and billing details."),
    (400, "insufficient_quota", "You exceeded your current quota."),
    (403, "billing_hard_limit_reached", "Billing hard limit has been reached."),
])
def test_a_spent_account_is_its_own_outcome(status, code, message):
    assert gateway.classify(status, _err(status, code, message)[1]) == gateway.CREDIT


@pytest.mark.parametrize("status,code,message,expected", [
    (429, "rate_limit_exceeded", "Rate limit reached for requests per minute. Please try again in 2s.", gateway.RATE_LIMITED),
    (429, "RESOURCE_EXHAUSTED", "Resource has been exhausted (e.g. check quota).", gateway.RATE_LIMITED),
    (401, "invalid_api_key", "Invalid API Key", gateway.AUTH),
    (400, "bad_request", "something else", gateway.REFUSED),
])
def test_an_ordinary_rate_limit_or_bad_key_is_not_mistaken_for_it(status, code, message, expected):
    assert gateway.classify(status, _err(status, code, message)[1]) == expected


def test_the_sentence_says_who_acts_and_that_waiting_will_not_help():
    sentence, _code = gateway.failure_sentence(gateway.GEMINI, 402, _err(402)[1], "m")
    assert "no credit left" in sentence and "add credit" in sentence and "will not help" in sentence
    assert "Gemini" in sentence and "HTTP 402" in sentence


def test_it_stops_at_once_whatever_the_attempt():
    assert gateway.decide(gateway.CREDIT, 1) == gateway.STOP
    assert gateway.CREDIT in gateway.OUTCOMES


def test_a_spent_account_is_not_retried_or_sent_to_a_second_model(monkeypatch):
    monkeypatch.setenv("GROQ_TEXT_MODEL", "primary-model")
    monkeypatch.setenv("GROQ_TEXT_MODEL_FALLBACK", "backup-model")
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(402, json=_err(402, None, "Payment required")[1])
        return httpx.Response(200, json=OK_BODY)

    with pytest.raises(groq_text.ProviderFailed) as e:
        asyncio.run(groq_text.chat([{"role": "user", "content": "q"}], api_key="k", max_tokens=100,
                                   transport=httpx.MockTransport(handler), feature="test_feature", firm_id="firm-c"))
    assert len(calls) == 1
    assert e.value.kind == gateway.CREDIT and "add credit" in e.value.sentence
