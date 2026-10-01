"""Who each relief reaches — the table the tax engine asks (TDS-INCOME-TAX-16).

WHAT WAS WRONG
    A HUF, an AOP and a BOI could not be recorded as clients, so each was
    recorded as an "Individual" and given an individual's reliefs whole: the
    §87A rebate, the §16(ia) standard deduction, the senior-citizen slab, the
    §80CCD and §80E/§80EE/§80GG/§80U deductions. Each of those names the
    assessee it reaches in its own opening words, and none of the three is that
    assessee for most of them.

    Migration 453 lets the three be recorded. This module is where the engine
    finds out what each one may and may not claim, so that it asks a TABLE and
    never tests a kind by name — the way `presumptive.ELIGIBLE_PRESUMPTIVE_
    ASSESSEES` answers §44AD and unlike the scatter of `assessee_kind ==
    "individual"` tests it replaces. A kind absent from a row's tuple is
    REFUSED the relief, so an assessee added later gets nothing until somebody
    has read the section.

It is deliberately a leaf: no service import, so the engine can use it without
pulling the compliance calendar in behind it.

Nothing here is money.
"""
from __future__ import annotations

from typing import Optional


#: WHO EACH RELIEF REACHES, by the section's own words — the table the engine
#: asks instead of testing a kind by name, and the reason a HUF is no longer
#: handed an individual's relief just because it takes an individual's slabs.
#:
#: key -> (what the relief is, the kinds it reaches, the words that say so).
#: The kinds are this module's, and a kind absent from the tuple is refused the
#: relief rather than granted it, so a kind added later gets nothing until
#: somebody decides it.
#:
#: ⚠️ `[S]`-GRADED. Every section's wording is written from knowledge — egress
#: is refused here, incometax.gov.in included — so `REACH_VERIFIED` is False and
#: `tests/test_a_huf_aop_and_boi_have_their_own_tax_basis.py` pins each row
#: exactly. The rows are deliberately limited to reliefs whose own opening words
#: name the assessee; one whose reach turns on a fact about the CLAIM rather
#: than the assessee (§80G, which is "any assessee"; §24(b), which sits inside a
#: head every assessee can have) is not in the table because it has no reach to
#: test.
REACH_VERIFIED = False

_IND = ("individual",)
_IND_HUF = ("individual", "huf")

RELIEF_REACH: dict[str, tuple[str, tuple[str, ...], str]] = {
    "rebate_87a": ("the §87A rebate", _IND,
                   "§87A: \"an assessee, being an individual resident in India\""),
    "standard_deduction_16ia": ("the §16(ia) standard deduction", _IND,
                                "§16(ia) is a deduction from income chargeable "
                                "under the head Salaries, and only an employee "
                                "has one"),
    "senior_citizen_slab": ("the senior and very senior citizen slab benefit", _IND,
                            "the Finance Act's higher exemption limits are for "
                            "\"every individual\" aged sixty or more"),
    "salary_head": ("the head Salaries", _IND,
                    "a salary is paid by an employer to an employee, which a "
                    "family or an association cannot be"),
    "hra_10_13a": ("the §10(13A) house rent allowance exemption", _IND,
                   "it exempts an allowance received as part of a salary"),
    "s80c": ("§80C", _IND_HUF,
             "§80C(1): \"an assessee, being an individual or a Hindu undivided "
             "family\""),
    "s80ccd_1b": ("§80CCD(1B)", _IND,
                  "§80CCD(1): \"an assessee, being an individual employed by "
                  "the Central Government ... or any other employer\""),
    "s80ccd_2": ("§80CCD(2)", _IND,
                 "it is the employer's contribution to an EMPLOYEE's account"),
    "s80d": ("§80D", _IND_HUF,
             "§80D(1): \"an assessee, being an individual or a Hindu undivided "
             "family\""),
    "s80tta": ("§80TTA", _IND_HUF,
               "§80TTA(1): \"an assessee, being an individual or a Hindu "
               "undivided family\""),
    "s80e": ("§80E", _IND,
             "§80E: \"an assessee, being an individual\""),
    "s80ee": ("§80EE and §80EEA", _IND,
              "§80EE and §80EEA: \"an assessee, being an individual\""),
    "s80dd": ("§80DD", _IND_HUF,
              "§80DD(1): \"an assessee, being an individual or a Hindu "
              "undivided family, who is resident in India\""),
    "s80ddb": ("§80DDB", _IND_HUF,
               "§80DDB(1): \"an assessee, being an individual or a Hindu "
               "undivided family, resident in India\""),
    "s80u": ("§80U", _IND,
             "§80U(1): \"an individual, who is resident in India\""),
    "s80gg": ("§80GG", _IND,
              "§80GG: \"any individual\" who receives no house rent allowance"),
    # The three provisos to §111A(1), §112(1)(a)(ii) and §112A(2): the unused
    # basic exemption absorbs into the special-rate gains for "an individual or
    # a Hindu undivided family, being a resident" and for nobody else.
    "basic_exemption_absorption": ("the unused basic exemption set against "
                                   "special-rate capital gains", _IND_HUF,
                                   "the provisos to §111A(1), §112(1)(a)(ii) "
                                   "and §112A(2): \"in the case of an individual "
                                   "or a Hindu undivided family, being a "
                                   "resident\""),
}


def reaches(relief: str, kind: Optional[str]) -> bool:
    """Whether this relief is available to this assessee.

    An unknown relief or an unknown kind answers False: a relief nobody
    recorded the reach of is not granted by default, and the KeyError a typo
    would otherwise raise is the same refusal with worse manners."""
    entry = RELIEF_REACH.get(relief)
    return bool(entry) and kind in entry[1]


def unavailable_for(kind: Optional[str]) -> list[str]:
    """The relief keys this assessee does NOT get, in the table's own order.

    SERVED to the computation screen (`GET /api/income-tax/assessee-kind`) so it
    hides the boxes the server would refuse instead of offering them and
    answering with an error after the CA has typed — a screen must never invite
    a CA to enter something the server will refuse. The screen holds no list and
    no section: it asks whether a key is in this one."""
    return [key for key in RELIEF_REACH if not reaches(key, kind)]


def why_not(relief: str, kind: str, word: Optional[str] = None) -> str:
    """The sentence for a relief this assessee does not get, naming the words
    of the section so a CA can check them rather than take ours."""
    label, _, words = RELIEF_REACH[relief]
    who = word or {"huf": "a Hindu undivided family",
                   "aop": "an association of persons",
                   "boi": "a body of individuals"}.get(kind, f"a {kind}")
    sentence = f"{label} is not available to {who} — {words}."
    return sentence[0].upper() + sentence[1:]
