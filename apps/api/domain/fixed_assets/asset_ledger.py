"""Which ledger a fixed asset of a given category is booked to - one table.

WHAT THIS REPLACED

    `phase2_journal_service` carried the same nine-line dict three times: in the
    acquisition journal, in the CWIP capitalisation journal and in the disposal
    journal. Three copies of a lookup are three places a category can be added
    to and forgotten in, which is what task #232 found once already ("adding a
    key to the category taxonomy without adding it to the map silently books the
    asset to Plant & Machinery") and what happened again here in the other
    direction: `Office Equipment` was in all three maps and in NO chart. The map
    asked for `%Office Equipment%`, `services/coa_seed_service.STANDARD_COA` had
    no such ledger, and `_find_account` raised "Required account not found" -
    which `POST /api/fixed-assets` does not convert, so a firm onboarded through
    the product got a 500 on the commonest office purchase there is (and the
    asset row had already been written, with no journal behind it).

THE RULE THAT WOULD HAVE CAUGHT BOTH

    Every category in `schedule_ii.PART_C` is an EXPLICIT key here, and the
    pattern it names matches exactly one ledger on the standard chart.
    `tests/test_every_asset_category_has_a_ledger_on_the_standard_chart.py` holds
    both, and holds that no module but this one carries a category-to-ledger
    dict again.

    "Other" is a key on purpose. It has always fallen through to the Plant &
    Machinery default (Schedule II prescribes no class for it, so the CA picks
    the rate and the cost sits with the general plant ledger); listing it makes
    that a statement in the table and not an accident of `dict.get`.

THE PATTERNS ARE THE ENGINE'S ILIKE PATTERNS

    They are handed to `phase2_journal_service._find_account`, which matches
    `chart_of_accounts.account_name` case-insensitively and takes the first
    ACTIVE row of the firm that is firm-level or the client's own. A pattern that
    matched two ledgers would resolve to whichever Postgres returned first, so
    the guard asks for exactly one.
"""
from __future__ import annotations

from typing import Optional

#: category (the platform-wide asset_category taxonomy, `schedule_ii.PART_C`'s
#: keys) -> the ILIKE pattern of the ledger its cost is debited to.
LEDGER_PATTERN_BY_CATEGORY: dict[str, str] = {
    "Plant & Machinery":        "%Plant & Machinery%",
    "Furniture & Fixtures":     "%Furniture & Fixtures%",
    "Computer & IT Equipment":  "%Computers & Software%",
    "Office Equipment":         "%Office Equipment%",
    "Vehicles":                 "%Vehicles%",
    "Building":                 "%Land & Building%",
    "Land":                     "%Land & Building%",
    "Intangibles":              "%Intangible Assets%",
    # No Schedule II class: the CA determines the life or rate, and the cost
    # sits with the general plant ledger as it always has.
    "Other":                    "%Plant & Machinery%",
}

#: THE LEDGER AN ASSET'S ACCUMULATED DEPRECIATION IS CREDITED TO, AND ITS DISPOSAL DEBITS (POST-A-345). Until migration 553 this was one
#: fixed pattern for every category, found by name: the firm's Accumulated Depreciation, which Schedule III places on the TANGIBLE line,
#: so an amortised intangible asset's amortisation reduced the wrong line. An asset may now NAME its ledger
#: (`fixed_assets.accumulated_account_id`); NULL, which is every asset before the change and every asset nobody has reclassified,
#: means the shared ledger below. `services.phase2_journal_service._accumulated_account_id` is the one function that applies this, and
#: both journals call it: a pattern named here and written out in a journal is how an asset ends up half in each ledger.
SHARED_ACCUMULATED_PATTERN = "%Accumulated Depreciation%"


class AccumulatedLedgerUnavailable(ValueError):
    """The ledger an asset names for its accumulated depreciation cannot be used. A ValueError so that the journals' own
    "re-raise account problems" branch lets it through, and a type of its own so a route can answer 422 in the sentence it carries."""


def accumulated_account_pointer(asset: dict) -> Optional[str]:
    """The id of the ledger this asset's accumulated depreciation is kept in, or None for the shared ledger.

    An ABSENT key reads as None, deliberately: the row comes from `select("*")` and the column arrived with migration 553, so a row
    read before it, a hand-built dict in a test and an asset nobody has pointed anywhere all mean the same thing, which is what
    every asset meant before the change. (The other direction is the dangerous one, and it is guarded where the pointer is WRITTEN:
    an asset is never pointed at a ledger without the entry that moved its history.)
    """
    pointer = asset.get("accumulated_account_id") if isinstance(asset, dict) else None
    return str(pointer) if pointer else None


#: What an asset whose category is absent, empty or outside the taxonomy (a row
#: written before the taxonomy was fixed) is booked to. Named so the fall-through
#: is a decision in the table's own module rather than a default argument.
DEFAULT_LEDGER_PATTERN = LEDGER_PATTERN_BY_CATEGORY["Plant & Machinery"]


def ledger_pattern(category: Optional[str]) -> str:
    """The ILIKE pattern of the ledger an asset of `category` is booked to."""
    if not isinstance(category, str):
        return DEFAULT_LEDGER_PATTERN
    return LEDGER_PATTERN_BY_CATEGORY.get(category, DEFAULT_LEDGER_PATTERN)
