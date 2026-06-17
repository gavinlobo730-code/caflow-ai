"""
Account classification for report projection.

Identifies the control accounts (A/R, A/P, Bank/Cash, advances) needed to
transform the accrual ledger into a cash-basis view. Prefers the stable
`system_account_key` (migration: chart_of_accounts.system_account_key) and
falls back to name matching that mirrors phase2_journal_service._find_account,
so it works on charts seeded before the key existed.
"""
from __future__ import annotations

from .model import Account


# Substring patterns mirror phase2_journal_service._find_account (case-insensitive).
_NAME_PATTERNS = {
    "ar": ("trade receivable", "accounts receivable", "sundry debtor"),
    "ap": ("trade payable", "accounts payable", "sundry creditor"),
    "advance_customer": ("advance from customer", "customer advance", "advance received"),
    "advance_vendor": ("advance to vendor", "vendor advance", "advance paid"),
}
_BANK_NAME = ("bank", "cash")


class AccountResolver:
    """Resolves control-account id sets for a single firm's chart of accounts."""

    def __init__(self, accounts: dict[str, Account]):
        self._accounts = accounts
        self.ar_ids: frozenset[str] = self._by_key_or_name("ar")
        self.ap_ids: frozenset[str] = self._by_key_or_name("ap")
        self.bank_ids: frozenset[str] = self._resolve_bank()
        self.advance_customer_id = self._first("advance_customer", key="advance_customer")
        self.advance_vendor_id = self._first("advance_vendor", key="advance_vendor")

    def _by_key_or_name(self, kind: str) -> frozenset[str]:
        ids = {a.id for a in self._accounts.values() if a.system_key == kind}
        if ids:
            return frozenset(ids)
        pats = _NAME_PATTERNS[kind]
        return frozenset(
            a.id for a in self._accounts.values()
            if any(p in (a.name or "").lower() for p in pats)
        )

    def _resolve_bank(self) -> frozenset[str]:
        ids = {a.id for a in self._accounts.values() if a.system_key == "bank"}
        if ids:
            return frozenset(ids)
        out = set()
        for a in self._accounts.values():
            if a.type != "Asset":
                continue
            hay = f"{a.name or ''} {a.subtype or ''}".lower()
            if any(p in hay for p in _BANK_NAME):
                out.add(a.id)
        return frozenset(out)

    def _first(self, kind: str, key: str) -> str | None:
        ids = self._by_key_or_name(kind)
        # Deterministic pick: lowest account code, else lowest id.
        candidates = [self._accounts[i] for i in ids if i in self._accounts]
        if not candidates:
            return None
        candidates.sort(key=lambda a: (a.code or "", a.id))
        return candidates[0].id

    def is_ar(self, account_id: str) -> bool:
        return account_id in self.ar_ids

    def is_ap(self, account_id: str) -> bool:
        return account_id in self.ap_ids
