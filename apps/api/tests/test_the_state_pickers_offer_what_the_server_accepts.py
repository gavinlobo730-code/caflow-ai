"""The state pickers offer the codes the server accepts, no more and no fewer (POST-A-103).

`apps/web/lib/constants/indianStates.ts` is the browser's one state list. The server holds three, for three different
questions (`core.validators` names them): a GSTIN's first two characters, a PLACE OF SUPPLY, and a registration's state.
The picker for a document's place of supply (and an export customer's state) was missing 96, the place of supply GSTN
requires on an export, so a CA could not key it although the API accepted it. This holds the browser's two lists to the
server's, from the side that owns the vocabulary (a guard written in `apps/web` would assert the browser against a copy of
itself).

    INDIAN_STATES           == the GSTIN list's states            (01 to 38)  less the dead codes 25 and 28
    PLACE_OF_SUPPLY_STATES  == the place-of-supply list           (01 to 38, 96, 97)  less the dead codes 25 and 28
"""
from __future__ import annotations

import re
from pathlib import Path

from domain.gst import gstin
from domain.gst.validator import VALID_STATE_CODES as PLACE_OF_SUPPLY_CODES

SRC = Path(__file__).resolve().parents[3] / "apps" / "web" / "lib" / "constants" / "indianStates.ts"
#: Dead codes, kept out of any picker for a NEW document while the server still parses a historical one:
#: 25 merged into 26 on 26-01-2020 and 28 was replaced by 37.
DEAD = {"25", "28"}


def _codes(block: str) -> set[str]:
    return set(re.findall(r'code:\s*"(\d{2})"', block))


def _lists() -> tuple[set[str], set[str]]:
    text = SRC.read_text(encoding="utf-8")
    states = text.split("export const INDIAN_STATES", 1)[1].split("export const PLACE_OF_SUPPLY_STATES", 1)
    assert len(states) == 2, "PLACE_OF_SUPPLY_STATES not found in indianStates.ts — the picker lists moved and this guard is blind"
    base = _codes(states[0])
    extra = _codes(states[1])
    return base, base | extra


def test_the_state_picker_is_the_states_the_gstin_list_holds_less_the_dead_codes():
    base, _ = _lists()
    gstin_states = {c for c in gstin.VALID_STATE_CODES if "01" <= c <= "38"}
    assert base == gstin_states - DEAD, (sorted(base ^ (gstin_states - DEAD)))


def test_the_place_of_supply_picker_is_the_servers_place_of_supply_list_less_the_dead_codes():
    _, place = _lists()
    assert place == PLACE_OF_SUPPLY_CODES - DEAD, sorted(place ^ (PLACE_OF_SUPPLY_CODES - DEAD))


def test_96_is_offered_where_a_place_of_supply_is_chosen_and_never_in_the_plain_state_list():
    base, place = _lists()
    assert "96" in place and "97" in place
    assert "96" not in base and "97" not in base, "a GSTIN-shaped state list must not offer codes a GSTIN cannot begin with"


def test_the_lists_would_catch_a_missing_96():
    # negative control: the comparison fails when the browser's list lacks what the server accepts
    _, place = _lists()
    assert place - {"96"} != PLACE_OF_SUPPLY_CODES - DEAD
