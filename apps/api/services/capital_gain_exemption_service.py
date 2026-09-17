"""Fetches what `domain/income_tax/reinvestment_exemption.py` decides with
(IT-19).

The split is this file's whole point and it is the one every other statutory
module in this codebase makes: the domain module is pure and takes facts, this
one reads them. So the s.54 family can be unit-tested against a table of
transfers with no database, and the reading — which client, which register
entry, which s.139(1) due date — is exercised separately.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Optional

from domain.income_tax import reinvestment_exemption as rex
from domain.income_tax.capital_gains_engine import fy_for_date, is_long_term
from services import compliance_obligation_service as cos

_logger = logging.getLogger("caflow.capital_gain_exemption")

#: The columns the engine needs off a claim row. Named so a query can be
#: checked against them — a read that silently omits `cgas_deposit_date`
#: reports the deposit as undated and refuses a claim that was in time.
CLAIM_COLUMNS = (
    "id, capital_gain_id, section, new_asset_description, acquisition_kind, "
    "acquisition_date, cost_paise, cgas_deposit_paise, cgas_deposit_date, "
    "other_residential_houses_owned, agricultural_use_two_years, "
    "new_asset_transferred_on, notes, created_at"
)


#: Which `clients.entity_type` values are an INDIVIDUAL OR HUF for s.54,
#: s.54B and s.54F. A proprietorship has no separate legal personality — the
#: assessee is the proprietor — so it belongs with 'Individual'.
#:
#: ⚠️ 'HUF' IS NOT A VALUE THE CLIENT VOCABULARY HAS. Migration 001's CHECK
#: allows Proprietorship, Partnership, LLP, Private Limited, Public Limited,
#: Trust, Society and Individual, so an HUF client is recorded as one of those
#: — in practice 'Individual'. Widening that CHECK is a migration and an owner
#: decision; until then the mapping cannot distinguish them, which does not
#: matter here because the two sit on the same side of every section in this
#: family.
_INDIVIDUAL_OR_HUF_ENTITY_TYPES = frozenset({"Individual", "Proprietorship"})
#: Everything the CHECK allows that is definitely NOT one. Written as its own
#: set rather than as "not in the first" so a value added to migration 001
#: later reads as UNKNOWN and is refused, instead of being silently classified
#: as a company by falling through.
_NOT_INDIVIDUAL_OR_HUF_ENTITY_TYPES = frozenset({
    "Partnership", "LLP", "Private Limited", "Public Limited", "Trust", "Society",
})


def individual_or_huf(entity_type: Optional[str]) -> Optional[bool]:
    """Tri-state, and the third state is the point: an entity type this
    mapping does not know is REFUSED AND NAMED, not read as a company."""
    if not entity_type:
        return None
    value = entity_type.strip()
    if value in _INDIVIDUAL_OR_HUF_ENTITY_TYPES:
        return True
    if value in _NOT_INDIVIDUAL_OR_HUF_ENTITY_TYPES:
        return False
    return None


def _d(value: Any) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def to_reinvestment(row: dict) -> rex.Reinvestment:
    return rex.Reinvestment(
        section=(row.get("section") or "").strip(),
        cost_paise=int(row.get("cost_paise") or 0),
        acquisition_kind=row.get("acquisition_kind") or None,
        acquisition_date=_d(row.get("acquisition_date")),
        cgas_deposit_paise=int(row.get("cgas_deposit_paise") or 0),
        cgas_deposit_date=_d(row.get("cgas_deposit_date")),
        other_residential_houses_owned=(
            None if row.get("other_residential_houses_owned") is None
            else int(row["other_residential_houses_owned"])),
        agricultural_use_two_years=(
            None if row.get("agricultural_use_two_years") is None
            else bool(row["agricultural_use_two_years"])),
        new_asset_transferred_on=_d(row.get("new_asset_transferred_on")),
        description=row.get("new_asset_description") or "",
        id=str(row.get("id") or ""),
    )


def _due_date(client_id: str, firm_id: Optional[str], transfer_date: date) -> tuple[Optional[date], bool]:
    """The s.139(1) due date for the YEAR OF TRANSFER, and whether the statute
    settled it on facts this product holds.

    A Capital Gains Accounts Scheme deposit counts as utilised only if it was
    made before that date, so the question cannot be skipped — and it cannot be
    answered confidently either, because s.44AB turns on a turnover figure no
    client record carries. `itr_due_date_for_client` already refuses in exactly
    that shape and hands back the EARLIER of the two dates with `decided:
    false`. The earlier date is the STRICTER test here: it excludes more
    deposits, which understates the exemption, which cannot understate the tax.
    """
    fy = fy_for_date(transfer_date)
    try:
        entity_type, has_audit = cos.itr_profile_for(client_id, firm_id=firm_id)
        answer = cos.itr_due_date_for_client(fy, entity_type=entity_type,
                                             has_tax_audit_engagement=has_audit)
        return _d(answer.get("due_date")), bool(answer.get("decided"))
    except Exception:  # noqa: BLE001 — an unreadable client must not stop the working
        _logger.warning("capital-gain exemption: could not resolve the s.139(1) "
                        "due date for client %s", client_id)
        return None, False


def exemption_for_entry(entry: dict, claim_rows: list[dict], *,
                        client_id: str, firm_id: Optional[str] = None) -> rex.ExemptionResult:
    """The s.54-family working for one register entry and its recorded claims.

    THE GAIN IS THE REGISTER'S OWN s.48 FIGURE — sale value less cost less
    improvement — and NOT the indexed one. That is deliberate: post
    23-07-2024 s.112 charges without indexation, `indexed_cost_paise` is left
    NULL whenever the index was a fallback (IT-29), and a reader that silently
    picked whichever of the two happened to be present would give two clients
    different exemptions on identical facts.
    """
    sale_value = int(entry.get("sale_value_paise") or 0)
    cost = int(entry.get("purchase_cost_paise") or 0)
    improvement = int(entry.get("improvement_cost_paise") or 0)
    gain = sale_value - cost - improvement

    purchase_date = _d(entry.get("purchase_date"))
    transfer_date = _d(entry.get("sale_date"))
    if transfer_date is None:
        return rex.ExemptionResult(
            gain_paise=gain, total_exemption_paise=0, taxable_gain_paise=max(0, gain),
            gaps=["This register entry has no sale date, so no window under "
                  "s.54, s.54B, s.54EC or s.54F can be measured."])

    long_term = bool(entry.get("gain_type") == "LTCG")
    if entry.get("gain_type") is None and purchase_date is not None:
        # IT-28. The fallback asks the classifier, so it must ask it with the
        # same fact the classifier now takes: a LISTED bond is long-term after
        # twelve months, and reading the row without `is_listed_security`
        # would give this path a different answer from the one stored in
        # `gain_type` on every entry that has one. `None` is the register's
        # own "not recorded" and the classifier reads it as unlisted.
        long_term = is_long_term(entry.get("asset_type") or "other",
                                 purchase_date, transfer_date,
                                 entry.get("is_listed_security"))

    due_date, decided = _due_date(client_id, firm_id, transfer_date)

    # The same read `itr_due_date_for_client` is given, used for a different
    # question — whether s.54, s.54B and s.54F reach this assessee at all.
    entity_type: Optional[str] = None
    try:
        entity_type, _ = cos.itr_profile_for(client_id, firm_id=firm_id)
    except Exception:  # noqa: BLE001 — an unreadable client is a NAMED gap
        _logger.warning("capital-gain exemption: could not read client %s", client_id)

    return rex.compute_exemption(
        gain_paise=gain,
        # The register holds no transfer-expenditure column, so the full value
        # of the consideration stands in for the net. The engine says so on
        # every s.54F answer.
        net_consideration_paise=sale_value,
        transfer_date=transfer_date,
        is_long_term=long_term,
        transferred_asset_nature=entry.get("transferred_asset_nature"),
        assessee_is_individual_or_huf=individual_or_huf(entity_type),
        assessee_description=entity_type or "no entity type",
        reinvestments=tuple(to_reinvestment(r) for r in claim_rows),
        return_due_date=due_date,
        return_due_date_is_decided=decided,
        net_consideration_is_gross=True,
    )
