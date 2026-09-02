"""
The firm's own reading of the DTAA rates it withholds under.

WHY THIS IS A TABLE AND NOT A COLUMN

    Migration 309 put treaty_rate_bps on the vendor, which reads naturally and
    is wrong in a way that shows up on the second vendor. A DTAA rate is a fact
    about a COUNTRY and an ARTICLE, not about a supplier: royalty to
    Switzerland is the same rate whichever Swiss company is being paid, and the
    same agreement commonly gives royalty, fees for technical services,
    interest and dividends four different rates.

    A firm with five Swiss vendors was entering one rate five times, could not
    express that royalty and interest differ under the same treaty, and would
    have to find all five rows again when a protocol changed.

WHAT THIS DOES NOT DO

    Hold any rates. dtaa_treaty_rates ships empty and is never seeded. India
    has agreements with over ninety countries; their articles differ, MFN
    clauses need their own s.90(1) notification (AO v. Nestle SA, 2023), and a
    wrong rate too low disallows the WHOLE expenditure under s.40(a)(i) while
    too high takes money off a supplier who can only recover it by filing an
    Indian return. A CA reads the agreement and records what they read.

"NO ARTICLE" IS AN ANSWER

    Several agreements — the UAE and Singapore among them — have no fees for
    technical services article at all. That is not an unknown rate: the income
    is business profits under Article 7 and is not taxable in India without a
    permanent establishment. The row says so, and the caller turns it into the
    nil it means (still on the payee's no-PE declaration, because that is the
    fact it actually turns on).

PRECEDENCE

    A per-vendor treaty_rate_bps still wins where one is set, for the rare
    payee whose position genuinely differs from the firm's country reading —
    an advance ruling, or a failed beneficial-ownership condition the country
    row assumes. Otherwise the country table answers.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

_logger = logging.getLogger("caflow.treaty_rates")


@dataclass(frozen=True)
class TreatyPosition:
    """What the firm has recorded for one (country, nature).

    `found` False means nobody has read this agreement for this nature yet,
    which is different from having read it and found no article — that is
    `found` True with `no_article` True.
    """
    found: bool
    rate_bps: Optional[int] = None
    no_article: bool = False
    article_ref: str = ""
    source: str = ""          # "vendor_override" | "firm_table" | ""


def treaty_position(db, firm_id: str, vendor: dict,
                    nature: Optional[str]) -> TreatyPosition:
    """The treaty position for this vendor's payment, or a not-found.

    Never raises: a treaty lookup that fails must not take a bill with it. A
    failure reports not-found, which makes the engine REFUSE rather than fall
    back to the Act rate — the safe direction, since the Act rate over-deducts
    exactly where a treaty has been established.
    """
    v = vendor or {}

    override = v.get("treaty_rate_bps")
    if override is not None:
        return TreatyPosition(found=True, rate_bps=int(override),
                              source="vendor_override",
                              article_ref="per-vendor override")

    country = (v.get("country_of_residence") or "").strip().upper()
    key = (nature or "").strip().lower()
    if db is None or not country or not key:
        return TreatyPosition(found=False)

    try:
        rows = (db.table("dtaa_treaty_rates")
                .select("rate_bps, no_article, article_ref")
                .eq("firm_id", firm_id)
                .eq("country_code", country)
                .eq("nature", key)
                .limit(1).execute().data) or []
    except Exception as e:                                      # noqa: BLE001
        _logger.warning(
            "treaty_position: could not read dtaa_treaty_rates for firm=%s "
            "country=%s nature=%s: %s — the withholding will be refused rather "
            "than computed at the Act rate", firm_id, country, key, e)
        return TreatyPosition(found=False)

    if not rows:
        return TreatyPosition(found=False)
    row = rows[0]
    return TreatyPosition(
        found=True,
        rate_bps=(None if row.get("no_article") else int(row.get("rate_bps") or 0)),
        no_article=bool(row.get("no_article")),
        article_ref=(row.get("article_ref") or ""),
        source="firm_table",
    )
