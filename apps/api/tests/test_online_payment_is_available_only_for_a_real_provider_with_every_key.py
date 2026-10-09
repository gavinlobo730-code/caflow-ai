"""Online payment is AVAILABLE only when a real gateway is chosen and every setting it cannot work without is set (PRE-B-002 part 2).

WHY THIS EXISTS

    Pay Now, the staff Payment Link modal and the emailed Pay Now button were shown with no check of the
    configured provider. With `PAYMENT_PROVIDER` blank or `mock` (production on 9 October 2026: a blank reads as
    the mock since 8 October) the link was `https://mock-pay.local/pay/<id>`, which does not resolve. The rule that
    answers "may a link be made?" is `domain/payments/availability.py` (pure) and its one reader of the environment
    is `services/payments/availability.py`. This file holds both to the four states they define:

      live              razorpay chosen and RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET and RAZORPAY_WEBHOOK_SECRET all set
      setup_incomplete  razorpay chosen and one of those three blank or missing
      not_switched_on   blank, spaces or `mock`
      unrecognised      anything else (what `factory.get_provider` refuses)

    and to two rules about the WORDS: what a client is told names no setting, no gateway and no test double, and
    what the practice is told names the settings to check and never a value.

NOT HERE: the routes that refuse (test_a_payment_link_is_never_made_or_sent_while_online_payment_is_off.py) and
the AST rule that every route asks (test_every_route_that_makes_or_sends_a_payment_link_asks_whether_online_
payment_is_on.py).
"""
from __future__ import annotations

import itertools
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from domain.filing_posture import FORBIDDEN_REGISTRATION_CLAIMS
from domain.payments import availability as rule
from services.payments import availability as service
from services.payments import factory

KEYS = rule.GATEWAY_SETTINGS["razorpay"]
ALL_KEY_NAMES = {k for names in rule.GATEWAY_SETTINGS.values() for k in names}


def _env(monkeypatch, provider, set_keys=(), blank_keys=()):
    """Set PAYMENT_PROVIDER (None = delete it) and the named keys: `set_keys` to a value, `blank_keys` to ''/spaces."""
    if provider is None:
        monkeypatch.delenv("PAYMENT_PROVIDER", raising=False)
    else:
        monkeypatch.setenv("PAYMENT_PROVIDER", provider)
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)
    for k in set_keys:
        monkeypatch.setenv(k, "x")
    for i, k in enumerate(blank_keys):
        monkeypatch.setenv(k, "" if i % 2 == 0 else "   ")


# ── the four states, from the environment a deployment really presents ───────────────────────────────────────

@pytest.mark.parametrize("provider", [None, "", "   ", "mock", " MOCK ", "Mock"])
@pytest.mark.parametrize("keys", [(), KEYS])
def test_a_blank_unset_or_mock_provider_is_not_switched_on_whatever_keys_are_set(monkeypatch, provider, keys):
    """The production state, and the case that must never read as live: even with every key present."""
    _env(monkeypatch, provider, set_keys=keys)
    a = service.current()
    assert a.state == rule.NOT_SWITCHED_ON and a.available is False
    assert a.settings_to_check == (rule.PROVIDER_SETTING,)


@pytest.mark.parametrize("provider", ["razorpay", " RazorPay "])
def test_a_real_provider_is_live_only_with_every_setting(monkeypatch, provider):
    for n in range(len(KEYS) + 1):
        for present in itertools.combinations(KEYS, n):
            _env(monkeypatch, provider, set_keys=present)
            a = service.current()
            if n == len(KEYS):
                assert a.state == rule.LIVE and a.available is True and a.settings_to_check == ()
            else:
                assert a.state == rule.SETUP_INCOMPLETE and a.available is False
                assert set(a.settings_to_check) == set(KEYS) - set(present), "names exactly what is missing"


def test_a_missing_webhook_secret_alone_is_not_live(monkeypatch):
    """Without it every delivery is unverified and refused: money could be captured and no receipt ever posted."""
    _env(monkeypatch, "razorpay", set_keys=("RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET"))
    a = service.current()
    assert a.state == rule.SETUP_INCOMPLETE and a.settings_to_check == ("RAZORPAY_WEBHOOK_SECRET",)


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_dashboard_value_is_a_missing_key(monkeypatch, blank):
    """Render lists every sync:false key and an untouched one reaches the process as '' (core/env.py)."""
    _env(monkeypatch, "razorpay", set_keys=KEYS[:2])
    monkeypatch.setenv(KEYS[2], blank)
    assert service.current().state == rule.SETUP_INCOMPLETE


@pytest.mark.parametrize("provider", ["stripe", "cashfree", "razorpay2", "none"])
def test_a_provider_the_factory_would_refuse_is_unrecognised(monkeypatch, provider):
    _env(monkeypatch, provider, set_keys=KEYS)
    a = service.current()
    assert a.state == rule.UNRECOGNISED and a.available is False


def test_the_rule_and_the_factory_agree_about_which_providers_exist(monkeypatch):
    """`unrecognised` is exactly what `get_provider` raises on, and no recognised provider raises."""
    for provider in [None, "", "mock", "razorpay", "stripe", "typo"]:
        _env(monkeypatch, provider, set_keys=KEYS)
        state = service.current().state
        if state == rule.UNRECOGNISED:
            with pytest.raises(ValueError):
                factory.get_provider()
        else:
            assert factory.get_provider() is not None


def test_available_is_true_in_exactly_one_state():
    assert [s for s in rule.STATES if rule.Availability(s).available] == [rule.LIVE]
    assert set(rule.STATES) == {rule.LIVE, rule.SETUP_INCOMPLETE, rule.NOT_SWITCHED_ON, rule.UNRECOGNISED}


def test_the_pure_rule_takes_what_it_is_given_and_reads_nothing(monkeypatch):
    """No environment read inside the rule: a hostile environment changes nothing it returns."""
    monkeypatch.setenv("PAYMENT_PROVIDER", "razorpay")
    for k in KEYS:
        monkeypatch.setenv(k, "x")
    assert rule.assess("mock", {k: True for k in KEYS}).state == rule.NOT_SWITCHED_ON
    assert rule.assess("razorpay", {}).state == rule.SETUP_INCOMPLETE
    assert rule.assess(None, {}).state == rule.NOT_SWITCHED_ON


# ── the words ────────────────────────────────────────────────────────────────────────────────────────────

_ENV_SHAPED = re.compile(r"\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b")


def _states_and_blocks():
    for state, missing in [
        (rule.NOT_SWITCHED_ON, (rule.PROVIDER_SETTING,)), (rule.UNRECOGNISED, (rule.PROVIDER_SETTING,)),
        (rule.SETUP_INCOMPLETE, KEYS), (rule.LIVE, ()),
    ]:
        a = rule.Availability(state, tuple(missing))
        yield a, rule.portal_block(a), rule.staff_block(a)


def test_what_a_client_is_told_names_no_setting_no_gateway_and_no_test_double():
    for a, portal, _ in _states_and_blocks():
        text = " ".join(str(v) for v in portal.values() if v)
        assert not _ENV_SHAPED.search(text), f"{a.state}: a setting name in what a client reads: {text!r}"
        low = text.lower()
        for word in ("mock", "razorpay", "gateway", "provider", "webhook", "key"):
            assert word not in low, f"{a.state}: {word!r} in what a client reads: {text!r}"
        assert set(portal) == {"available", "label", "headline", "reason"}, "no state, no setting list for a client"


def test_what_a_client_is_told_when_not_available_is_coming_soon_with_one_reason():
    a = rule.Availability(rule.NOT_SWITCHED_ON, (rule.PROVIDER_SETTING,))
    block = rule.portal_block(a)
    assert block["available"] is False
    assert block["headline"] == "Online payment is coming soon."
    assert block["label"] == "Pay Now · coming soon"
    assert "payment details on your invoice" in block["reason"], "tells the client what to do meanwhile"
    # The same words for every state that is not live: a client cannot act on the difference.
    for state in (rule.SETUP_INCOMPLETE, rule.UNRECOGNISED):
        assert rule.portal_block(rule.Availability(state, ("X",))) == block
    live = rule.portal_block(rule.Availability(rule.LIVE))
    assert live == {"available": True, "label": "Pay Now", "headline": None, "reason": None}


def test_what_the_practice_is_told_names_the_settings_to_check_and_never_a_value():
    for a, _, staff in _states_and_blocks():
        assert staff["state"] == a.state
        assert staff["settings_to_check"] == list(a.settings_to_check)
        assert staff["available"] is a.available
        for v in staff["settings_to_check"]:
            assert _ENV_SHAPED.fullmatch(v), "names only"
    # setup_incomplete says which keys are missing; not_switched_on says which switch to look at.
    names = rule.staff_block(rule.Availability(rule.SETUP_INCOMPLETE, ("RAZORPAY_WEBHOOK_SECRET",)))
    assert names["settings_to_check"] == ["RAZORPAY_WEBHOOK_SECRET"]
    assert names["headline"] == "Online payment is coming soon."
    # Each state has its own reason for the practice: they send a person to different places.
    reasons = {rule.staff_block(rule.Availability(s, ("X",)))["reason"]
               for s in (rule.NOT_SWITCHED_ON, rule.SETUP_INCOMPLETE, rule.UNRECOGNISED)}
    assert len(reasons) == 3


def test_the_words_claim_no_registration_is_in_motion():
    """The house rule (docs/open-items/coming-soon.md): "coming soon" is for an ordinary feature, online payment
    included, and the list of words a REGISTRATION sentence may not use does not reach it: that list is about
    filing, so "coming soon" is the one phrase it holds that this text is allowed. But the merchant account is the
    owner's and has not been opened, so nothing here may say one is in motion either."""
    texts = [rule.HEADLINE, rule.CLIENT_REASON, rule.LABEL_COMING_SOON, *rule.STAFF_REASONS.values(), rule.MASKED_LINK_NOTE]
    low = " ".join(texts).lower()
    assert "coming soon" in low, "online payment is an ordinary feature: this is the words the owner chose"
    for phrase in (p for p in FORBIDDEN_REGISTRATION_CLAIMS if p != "coming soon"):
        assert phrase not in low


def test_the_refusal_sentence_is_the_headline_and_the_reason_for_that_audience():
    a = rule.Availability(rule.NOT_SWITCHED_ON, (rule.PROVIDER_SETTING,))
    assert rule.refusal_sentence(a, "portal") == "Online payment is coming soon. " + rule.CLIENT_REASON
    assert rule.refusal_sentence(a, "staff") == "Online payment is coming soon. " + rule.STAFF_REASONS[rule.NOT_SWITCHED_ON]


# ── which invoices, which links ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("status,outstanding,expected", [
    ("issued", 100, True), ("partially_paid", 1, True), ("ISSUED", 100, True),
    ("draft", 100, False), ("cancelled", 100, False), ("paid", 100, False), ("void", 100, False),
    ("issued", 0, False), ("issued", -5, False), ("issued", None, False), ("issued", "abc", False),
    (None, 100, False), ("", 100, False),
])
def test_only_an_issued_or_part_paid_invoice_with_a_balance_is_payable(status, outstanding, expected):
    assert rule.invoice_is_payable(status, outstanding) is expected


def test_payable_statuses_are_the_two_the_portal_and_the_invoice_hub_already_call_open():
    from services import portal_data_service
    assert set(rule.PAYABLE_STATUSES) == set(portal_data_service._OPEN)
    hub_ts = (Path(__file__).resolve().parents[3] / "apps" / "web" / "lib" / "invoices" / "hub.ts").read_text(encoding="utf-8")
    hub = (re.search(r"collectible = ([^;]+);", hub_ts) or [None, ""])[1]
    assert set(re.findall(r'"(\w+)"', hub)) == set(rule.PAYABLE_STATUSES), "lib/invoices/hub.ts collectible"


def test_a_link_the_test_double_made_is_masked_and_a_real_one_is_not():
    mock = {"id": "L1", "provider": "mock", "short_url": "https://mock-pay.local/pay/L1", "status": "active"}
    masked = rule.mask_link(mock)
    assert masked["short_url"] is None and masked["note"] == rule.MASKED_LINK_NOTE
    assert masked["id"] == "L1" and masked["status"] == "active", "listed: the history is true"
    assert mock["short_url"], "the stored row is not changed"
    real = {"id": "L2", "provider": "razorpay", "short_url": "https://pay.example/L2", "status": "active"}
    assert rule.mask_link(real) is real
    assert rule.mask_link({"id": "L3", "provider": " MOCK ", "short_url": "x"})["short_url"] is None


NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
FUTURE = (NOW + timedelta(days=3)).isoformat()
PAST = (NOW - timedelta(days=1)).isoformat()


def _link(**over):
    return {"provider": "razorpay", "status": "active", "short_url": "https://pay.example/x", "expires_at": FUTURE, **over}


def test_a_link_is_emailable_only_when_the_configured_gateway_made_it_and_it_can_still_be_paid():
    assert rule.link_problem(_link(), "razorpay", NOW) is None
    # made by the test double, or by another gateway than the one configured now
    assert rule.link_problem(_link(provider="mock"), "razorpay", NOW)
    assert rule.link_problem(_link(provider="mock"), "mock", NOW), "the double's own links are never emailed either"
    assert rule.link_problem(_link(provider="razorpay"), "mock", NOW)
    assert rule.link_problem(_link(provider=None), "razorpay", NOW)
    # half-made, paid, expired by status, cancelled
    for status in ("created", "paid", "expired", "cancelled", None):
        assert rule.link_problem(_link(status=status), "razorpay", NOW), status
    # no address, a blank address
    assert rule.link_problem(_link(short_url=None), "razorpay", NOW)
    assert rule.link_problem(_link(short_url="  "), "razorpay", NOW)
    # past its own expiry (nothing sets `expired`, so the date is what says so); an unreadable date is not a refusal
    assert "expired" in rule.link_problem(_link(expires_at=PAST), "razorpay", NOW)
    assert rule.link_problem(_link(expires_at="not a date"), "razorpay", NOW) is None
    assert rule.link_problem(_link(expires_at=None), "razorpay", NOW) is None
    assert rule.link_problem(_link(expires_at=FUTURE.replace("+00:00", "Z")), "razorpay", NOW) is None
