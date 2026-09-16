"""Every identifier the demo firm is seeded with is one the product accepts.

WHAT WAS WRONG

`docs/plan/THE-PLAN.md` described `seed/seed_data.py` as "twenty named clients
with valid PANs and GSTINs". Checked against `domain/gst/gstin.checksum_char`
on 16-09-2026, **17 of the 20 client GSTINs carried the wrong check digit, and
so did the firm's own** — 18 in all. The first fourteen characters were well
formed every time; only the last was invented.

That is not cosmetic, and it is not a fixture's private business either. This
data exists to BECOME a real firm:

  * `POST /api/onboarding/firm` refuses a firm GSTIN that fails the check
    (GST-29 put `problem_with` on every door a human types one), so the demo
    firm could not have been created through the product's own path;
  * `GET`/`POST` on the GSTR-1 build refuses the CLIENT's own GSTIN for the
    same reason, so a seeded client could not have filed;
  * and a counterparty GSTIN that is valid-shaped but wrong sends a
    customer's input tax credit to a stranger — which is why the check exists
    rather than the shape regex that used to be there.

THE RULE, WHICH IS THE DURABLE HALF

    A GSTIN in this repository is COMPUTED, never typed.

`checksum_char` is the authority and it is cheap; there is no reason for a
fifteenth character to be a guess. This file holds the line for the seed data
specifically, because that is the set about to be written into a database and
shown to a CA.

CLAUDE.md records the same lesson from the other direction: three fixture
GSTINs used across 77 files were CORRECTED rather than the guard relaxed, two
of them frontend placeholders that taught a CA an example their own keystroke
validator rejected.
"""
from __future__ import annotations

import re

import pytest

from domain.gst.gstin import checksum_char, problem_with
from seed.seed_data import DEMO_FIRM, SEED_CLIENTS

#: IT Act's own PAN shape. Deliberately a shape check and nothing more — a PAN
#: carries no check digit this product can verify, which is exactly why
#: `models/client.py` stops there too.
_PAN = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")


def _seeded_gstins() -> list[tuple[str, str]]:
    out = [("the firm itself", DEMO_FIRM["gst_number"])]
    out += [(c["client_name"], c["gstin"]) for c in SEED_CLIENTS]
    return out


def test_the_seed_carries_gstins_at_all():
    """A rename that emptied this list would make every test below vacuous."""
    assert len(_seeded_gstins()) >= 21, (
        "the seed should carry the firm's GSTIN and one per client — it now "
        "carries fewer, so the checks below are testing almost nothing")


@pytest.mark.parametrize("who,gstin", _seeded_gstins(), ids=lambda v: str(v)[:24])
def test_every_seeded_gstin_would_be_accepted(who, gstin):
    problem = problem_with(gstin)
    assert problem is None, (
        f"{who} is seeded with {gstin}, which the product refuses: {problem}\n"
        f"The first fourteen characters are the fact; the fifteenth is "
        f"arithmetic. Use domain.gst.gstin.checksum_char(gstin[:14]) — here "
        f"that gives {checksum_char(gstin[:14])}.")


@pytest.mark.parametrize("who,gstin", _seeded_gstins(), ids=lambda v: str(v)[:24])
def test_a_seeded_gstin_is_a_maharashtra_registration(who, gstin):
    """Every seeded client is in Maharashtra and the state code says so.

    Not decoration: `place_of_supply` takes the GSTIN's first two characters
    (CGST §25), so a prefix that disagreed with `clients.state` would turn an
    intra-state supply inter-state on the demo's own invoices.
    """
    assert gstin[:2] == "27", (
        f"{who} carries state code {gstin[:2]} while the seed says Maharashtra")


@pytest.mark.parametrize(
    "who,pan",
    [("the firm itself", DEMO_FIRM.get("pan"))] +
    [(c["client_name"], c["pan"]) for c in SEED_CLIENTS],
    ids=lambda v: str(v)[:24],
)
def test_every_seeded_pan_is_well_formed(who, pan):
    if pan is None:
        pytest.skip("the demo firm has no PAN of its own in the seed data")
    assert _PAN.match(pan), f"{who} is seeded with PAN {pan!r}"


def test_the_gstin_carries_the_clients_own_pan():
    """CGST §25: a GSTIN is the state code, then the PAN, then the rest.

    A seeded client whose GSTIN quotes somebody else's PAN is the shape of
    mistake that survives every format check and fails at the portal.
    """
    wrong = [
        (c["client_name"], c["pan"], c["gstin"])
        for c in SEED_CLIENTS
        if c["gstin"][2:12] != c["pan"]
    ]
    assert not wrong, "\n".join(
        f"{name}: PAN {pan} but GSTIN {gstin} quotes {gstin[2:12]}"
        for name, pan, gstin in wrong)
