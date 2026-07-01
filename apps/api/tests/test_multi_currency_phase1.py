"""
Multi-Currency — Phase 1 (Foundation) tests.

Covers the additive infrastructure ONLY: the L1 feature flag, the three-level
resolve_currency_policy() decision point (fail-safe to INR), the immutable
RateQuote, the RateProvider abstraction (Manual / RBI / ECB), the
ExchangeRateService, and the currency-master reader. No posting/journal/kernel
code is exercised — those are unchanged in this phase.

The overarching backward-compat guarantee ("feature OFF ⇒ behaviour identical")
is asserted here at the policy layer and, separately, by the full existing suite
continuing to pass unchanged.
"""
from dataclasses import FrozenInstanceError
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from core.feature_flags import multi_currency_platform_enabled
from domain.currency import (
    CurrencyPolicy,
    ExchangeRateService,
    ManualRateProvider,
    RateNotFound,
    RateProvider,
    RateQuote,
    RBIRateProvider,
    ECBRateProvider,
    is_valid_rate_type,
    resolve_currency_policy,
)
from domain.currency import currency_service


ENV = "MULTI_CURRENCY_ENABLED"


# ── L1 platform feature flag ──────────────────────────────────────────────────
def test_platform_flag_defaults_off(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)
    assert multi_currency_platform_enabled() is False


@pytest.mark.parametrize("val,expected", [
    ("true", True), ("1", True), ("yes", True), ("on", True), ("TRUE", True),
    ("false", False), ("0", False), ("", False), ("nope", False),
])
def test_platform_flag_parses_env(monkeypatch, val, expected):
    monkeypatch.setenv(ENV, val)
    assert multi_currency_platform_enabled() is expected


# ── L1∧L2∧L3 resolve_currency_policy (single decision point, fail-safe INR) ────
def _firm(entitled): return {"multi_currency_entitled": entitled}
def _client(enabled, functional="INR"):
    return {"multi_currency_enabled": enabled, "functional_currency": functional}


def test_policy_all_off_is_inert(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)
    pol = resolve_currency_policy(None, None)
    assert pol == CurrencyPolicy(active=False, functional_currency="INR")


def test_policy_kill_switch_env_off_overrides_firm_and_client(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)  # L1 off
    pol = resolve_currency_policy(_firm(True), _client(True, "INR"))
    assert pol.active is False and pol.functional_currency == "INR"


def test_policy_firm_gate(monkeypatch):
    monkeypatch.setenv(ENV, "true")
    pol = resolve_currency_policy(_firm(False), _client(True, "INR"))
    assert pol.active is False


def test_policy_client_gate(monkeypatch):
    monkeypatch.setenv(ENV, "true")
    pol = resolve_currency_policy(_firm(True), _client(False, "INR"))
    assert pol.active is False


def test_policy_all_on_inr_is_active(monkeypatch):
    monkeypatch.setenv(ENV, "true")
    pol = resolve_currency_policy(_firm(True), _client(True, "INR"))
    assert pol.active is True and pol.functional_currency == "INR"


def test_policy_non_inr_functional_fails_safe_capability_b(monkeypatch):
    # A non-INR functional currency is Capability B (not implemented) → never active,
    # and it fails safe to INR so no caller can act on an unsupported currency.
    monkeypatch.setenv(ENV, "true")
    pol = resolve_currency_policy(_firm(True), _client(True, "USD"))
    assert pol.active is False and pol.functional_currency == "INR"


def test_policy_functional_case_normalised(monkeypatch):
    monkeypatch.setenv(ENV, "true")
    pol = resolve_currency_policy(_firm(True), _client(True, "inr"))
    assert pol.active is True and pol.functional_currency == "INR"


def test_policy_missing_firm_or_client_fails_safe(monkeypatch):
    monkeypatch.setenv(ENV, "true")
    assert resolve_currency_policy(None, _client(True, "INR")).active is False
    assert resolve_currency_policy(_firm(True), None).active is False


def test_policy_never_raises_on_garbage(monkeypatch):
    monkeypatch.setenv(ENV, "true")
    pol = resolve_currency_policy({}, {"functional_currency": None})
    assert pol == CurrencyPolicy(active=False, functional_currency="INR")


# ── RateQuote immutability + exactness (G3/G4) ────────────────────────────────
def _quote():
    return RateQuote(base="USD", quote="INR", rate=Decimal("83.25"),
                     rate_date=date(2026, 7, 1), rate_type="booking", source="manual")


def test_rate_quote_is_frozen():
    q = _quote()
    with pytest.raises(FrozenInstanceError):
        q.rate = Decimal("99")  # type: ignore[misc]


def test_rate_quote_rejects_float_rate():
    with pytest.raises(TypeError):
        RateQuote(base="USD", quote="INR", rate=83.25,  # type: ignore[arg-type]
                  rate_date=date(2026, 7, 1), rate_type="booking", source="manual")


def test_rate_quote_rejects_non_positive():
    with pytest.raises(ValueError):
        RateQuote(base="USD", quote="INR", rate=Decimal("0"),
                  rate_date=date(2026, 7, 1), rate_type="booking", source="manual")


def test_rate_types_vocabulary():
    for t in ("booking", "gst_notified", "customs", "closing"):
        assert is_valid_rate_type(t)
    assert not is_valid_rate_type("spot")


# ── ExchangeRateService (G5) ──────────────────────────────────────────────────
class _FakeProvider(RateProvider):
    source = "fake"

    def __init__(self, quote=None):
        self._quote = quote

    def get_rate(self, base, quote, rate_date, rate_type):
        return self._quote


def test_service_identity_needs_no_provider():
    svc = ExchangeRateService()  # no providers at all
    q = svc.get_quote("INR", "INR", date(2026, 7, 1))
    assert q.rate == Decimal(1) and q.source == "identity" and q.base == "INR"


def test_service_identity_any_currency():
    svc = ExchangeRateService()
    assert svc.get_quote("usd", "USD", date(2026, 7, 1)).rate == Decimal(1)


def test_service_invalid_rate_type_raises():
    svc = ExchangeRateService()
    with pytest.raises(ValueError):
        svc.get_quote("INR", "INR", date(2026, 7, 1), rate_type="spot")


def test_service_delegates_to_provider():
    q = RateQuote(base="USD", quote="INR", rate=Decimal("83.5"),
                  rate_date=date(2026, 7, 1), rate_type="booking", source="fake")
    svc = ExchangeRateService([_FakeProvider(q)])
    got = svc.get_quote("USD", "INR", date(2026, 7, 1))
    assert got is q  # immutable quote passed straight through


def test_service_missing_rate_raises_ratenotfound():
    svc = ExchangeRateService([_FakeProvider(None)])
    with pytest.raises(RateNotFound):
        svc.get_quote("USD", "INR", date(2026, 7, 1))


def test_service_unknown_source_raises_ratenotfound():
    svc = ExchangeRateService([_FakeProvider(None)])
    with pytest.raises(RateNotFound):
        svc.get_quote("USD", "INR", date(2026, 7, 1), source="rbi")


# ── Provider adapters ─────────────────────────────────────────────────────────
class _FakeQuery:
    """Minimal PostgREST-shaped fake that honours .eq() filtering and .limit()."""
    def __init__(self, rows):
        self._rows = list(rows)
        self._filters = []
        self._limit = None

    def select(self, *a, **k): return self
    def eq(self, col, val): self._filters.append((col, val)); return self
    def lte(self, *a, **k): return self
    def order(self, *a, **k): return self
    def limit(self, n): self._limit = n; return self

    def execute(self):
        rows = [r for r in self._rows if all(r.get(c) == v for c, v in self._filters)]
        if self._limit is not None:
            rows = rows[: self._limit]
        return SimpleNamespace(data=rows)


class _FakeDB:
    def __init__(self, tables): self._tables = tables
    def table(self, name): return _FakeQuery(self._tables.get(name, []))


def test_manual_provider_reads_stored_rate():
    db = _FakeDB({"fx_rates": [{
        "base": "USD", "quote": "INR", "rate_date": "2026-06-30",
        "rate_type": "booking", "rate": "83.25000000", "source": "manual",
    }]})
    q = ManualRateProvider(db).get_rate("USD", "INR", date(2026, 7, 1), "booking")
    assert q is not None
    assert q.rate == Decimal("83.25") and isinstance(q.rate, Decimal)
    assert q.source == "manual" and q.rate_date == date(2026, 6, 30)


def test_manual_provider_none_when_absent():
    assert ManualRateProvider(_FakeDB({"fx_rates": []})).get_rate(
        "USD", "INR", date(2026, 7, 1), "booking") is None


def test_rbi_ecb_are_abstraction_only():
    for prov, src in ((RBIRateProvider(), "rbi"), (ECBRateProvider(), "ecb")):
        assert isinstance(prov, RateProvider)
        assert prov.source == src
        with pytest.raises(NotImplementedError):
            prov.get_rate("USD", "INR", date(2026, 7, 1), "booking")


# ── Currency master reader (G1 — no hardcoded lists) ──────────────────────────
def _master_db():
    return _FakeDB({"currencies": [
        {"code": "INR", "symbol": "₹", "display_name": "Indian Rupee", "minor_unit": 2, "is_active": True},
        {"code": "JPY", "symbol": "¥", "display_name": "Japanese Yen", "minor_unit": 0, "is_active": True},
    ]})


def test_currency_master_list_and_get():
    db = _master_db()
    rows = currency_service.list_currencies(db)
    assert {r["code"] for r in rows} == {"INR", "JPY"}
    assert currency_service.get_currency(db, "jpy")["display_name"] == "Japanese Yen"


def test_currency_master_minor_unit_from_master():
    db = _master_db()
    # JPY = 0 decimals (never "paise"), INR = 2 — read from the master, not hardcoded.
    assert currency_service.minor_unit(db, "JPY") == 0
    assert currency_service.minor_unit(db, "INR") == 2


def test_currency_master_minor_unit_fallback_when_absent():
    assert currency_service.minor_unit(_FakeDB({"currencies": []}), "ZZZ", default=2) == 2
