"""A supplier or customer you probably already have.

WHAT THE EXISTING GUARD DOES, AND WHERE IT STOPS

`routers/vendors._match_existing_vendor` and `routers/customers._match_existing`
refuse a second ACTIVE party matching an existing one by GSTIN (CGST §25 — a
registration number identifies one registration) or, failing that, by PAN
(IT Act §139A). That is right and stays: those two identifiers are the entity,
so a match on either is not a resemblance, it is the same person, and returning
the existing row rather than inserting a second is the correct answer.

It reaches only a party that HAS one. An unregistered supplier below the §22
threshold — the local printer, the courier, the tea vendor, the landlord
letting a room — has no GSTIN, and a practice does not hold the PAN of every
one of them. For those, the product had nothing at all: `Sharma Traders` typed
in March and `SHARMA TRADERS` typed in June are two rows, and after that one
supplier's ledger is two ledgers.

WHAT THAT COSTS, AND WHY THE SUPPLIER SIDE IS WORSE

Both sides split an ageing schedule and a statement in half, which is a
presentation error somebody notices. The supplier side also moves statutory
figures, silently:

  * **§43B(h)**, from the Finance Act 2023. A sum payable to a micro or small
    enterprise beyond the MSMED §15 limit is disallowed unless actually paid,
    and `vendors.msme_status` is recorded per vendor — so one copy classified
    and the other not gives an add-back computed over half the balance.

  * **The §194 FY AGGREGATE.** §194C(5) and the "aggregate of the sums" limb in
    §§194A/194D/194G/194H/194J charge on the YEAR'S total credited to one
    payee. `resolve_tds` is given `fy_prior_taxable_paise` for that payee, and
    a payee split across two vendor rows has each half measured against the
    whole threshold — so a supplier who crossed ₹1,00,000 may cross it in
    neither copy and nothing is withheld at all. §40(a)(ia) then disallows the
    WHOLE expenditure, with §201(1) putting the tax on the deductor.

  * **`vendors.tds_section`** is per vendor, so one copy can carry §194J and
    the other nothing — which is PUR-06 = TDS-13's failure reached by a
    different road.

None of that is visible. Two ledgers that each look right is exactly the shape
of defect this codebase keeps finding.

IT REPORTS. IT NEVER MERGES, AND IT NEVER REFUSES.

Two genuine suppliers share a name — `Sharma Traders` in Pune and
`Sharma Traders` in Nashik are two businesses, two proprietors, two PANs — and
a name is not an identifier of anything. Merging them on a name would be
invisible and would move money: their ledgers, their ageing, their §43B(h)
position and their §194 aggregate all silently become one, and there is no
undo. Refusing is no better: it stops a CA recording a supplier that genuinely
exists, and a guard that refuses real work is a guard people route around.

So the party is CREATED exactly as asked and the resemblance travels back
beside it, for the screen to say "you already have a Sharma Traders". Report,
never block, is the shape `domain/purchases/three_way_match` and
`domain/purchases/near_duplicate` already take, for the same reason.

WHAT COUNTS AS THE SAME NAME

Exact equality of a NORMALISED name, and nothing looser. Deliberately NOT an
edit distance and NOT a substring: `Sharma Traders` and `Sharma Trading Co`
are one edit apart in words and are plausibly two businesses, `Sharma` is a
substring of `Sharma Electronics`, and a warning that fires on most rows is a
warning a CA stops reading — `near_duplicate` records the same conclusion
after its first draft used an edit distance.

Normalisation folds only what carries no identity:

  * case, and runs of whitespace;
  * the `M/s` honorific, which prefixes a large share of Indian supplier names
    and says nothing about which supplier;
  * punctuation — `Sharma Traders.`, `Sharma-Traders`, `Sharma Traders,`;
  * `&` as the word `and`.

THE ENTITY FORM IS CANONICALISED, NEVER REMOVED, and that distinction is the
one to keep. `Pvt Ltd`, `Pvt. Ltd.`, `Private Limited` and `P Ltd` are four
spellings of one thing and fold together. An **LLP does not fold into them**:
the LLP Act 2008 makes it a different legal person from a company of the same
name, with its own PAN and its own return, and the two commonly coexist in one
promoter group. Dropping the form altogether — the obvious simplification —
would report `Sharma Traders LLP` and `Sharma Traders Pvt Ltd` as the same
party, which is a resemblance that is not one.

`Limited` and `Private Limited` DO fold together, and that is a judgement
rather than a derivation: they are different classes under the Companies Act
2013, but in Indian practice `Pvt` is dropped constantly when a private
company's name is typed, and two DIFFERENT companies sharing a base name where
one is public and the other private is vanishingly rare. This only warns, so
the cheap error is the one that costs a glance.

Two limbs, reported separately because they mean different things:

  * `same_name` — the normalised names are equal. Almost always one party
    entered twice.
  * `same_name_different_form` — the base names are equal and the entity forms
    differ (`Sharma Traders` against `Sharma Traders Pvt Ltd`). This is the
    commonest real duplicate AND a real pattern in its own right: a
    proprietorship and the company that succeeded it are two parties, often
    both live, often related. Naming the difference lets the CA tell which.

Only ACTIVE parties are reported. A deactivated namesake is one somebody has
already dealt with, and naming it would make re-creating a party the CA
retired look like a mistake.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

# The honorific, at the START only. "M/s" inside a name is not an honorific.
_HONORIFIC = re.compile(r"^(m\s*/\s*s|messrs)\b[.\s]*", re.IGNORECASE)

# Spellings of one entity form -> the canonical token. Ordered longest-first
# where one is a prefix of another, because the scan takes the first match.
_COMPANY_FORMS = (
    "private limited", "private ltd", "pvt limited", "pvt ltd", "p ltd",
    "limited", "ltd",
)
_COMPANY_TOKEN = "ltd"

# Forms that are their OWN legal person and never fold into a company.
_DISTINCT_FORMS = {
    "llp": "llp",
    "limited liability partnership": "llp",
}

SAME_NAME = "same_name"
SAME_NAME_DIFFERENT_FORM = "same_name_different_form"


@dataclass(frozen=True)
class NameParts:
    """A party name split into what identifies it and what form it takes."""
    normalised: str            # base + form, the thing `same_name` compares
    base: str                  # the name with the entity form taken off
    form: str                  # "", "ltd" or "llp"


@dataclass(frozen=True)
class PossibleDuplicate:
    id: str
    name: str
    reason: str
    gstin: Optional[str] = None
    pan: Optional[str] = None

    def as_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "reason": self.reason,
                "gstin": self.gstin, "pan": self.pan,
                "explanation": EXPLANATIONS[self.reason]}


EXPLANATIONS = {
    SAME_NAME:
        "A party with this name already exists for this client. It was not "
        "merged and nothing was refused — two businesses can share a name. "
        "Check whether this is the same supplier before booking against it: "
        "a party split in two splits its ageing, its MSMED classification for "
        "s.43B(h) and its s.194 financial-year aggregate.",
    SAME_NAME_DIFFERENT_FORM:
        "A party with the same name and a different entity form already "
        "exists (for example a proprietorship and the company that succeeded "
        "it). These may genuinely be two parties. Nothing was merged.",
}


@dataclass
class DuplicateReport:
    """What the create path hands back beside the row it created."""
    checked: bool
    possible_duplicates: list[PossibleDuplicate] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"checked": self.checked,
                "possible_duplicates": [d.as_dict() for d in self.possible_duplicates]}


def normalise_party_name(name: Optional[str]) -> NameParts:
    """Fold away everything that does not identify the party.

    Returns the three pieces rather than one string, because the two limbs ask
    different questions of the same name and re-deriving the base from the
    normalised form at each call site is how they would come to disagree.
    """
    text = (name or "").strip()
    if not text:
        return NameParts("", "", "")
    text = _HONORIFIC.sub("", text)
    text = text.replace("&", " and ")
    text = re.sub(r"[^0-9a-zA-Z]+", " ", text).strip().lower()
    text = re.sub(r"\s+", " ", text)
    if not text:
        return NameParts("", "", "")

    form = ""
    for spelling, token in _DISTINCT_FORMS.items():
        if text == spelling or text.endswith(" " + spelling):
            form = token
            text = text[: -len(spelling)].strip()
            break
    else:
        for spelling in _COMPANY_FORMS:
            if text == spelling or text.endswith(" " + spelling):
                form = _COMPANY_TOKEN
                text = text[: -len(spelling)].strip()
                break

    base = re.sub(r"\s+", " ", text).strip()
    normalised = f"{base} {form}".strip() if form else base
    return NameParts(normalised, base, form)


def possible_duplicates(
    name: Optional[str],
    candidates: Iterable[dict],
    *,
    name_key: str = "name",
    exclude_id: Optional[str] = None,
) -> list[PossibleDuplicate]:
    """Active candidates whose name resembles `name`.

    `candidates` must already be scoped to the firm and client — the caller
    holds the tenancy filter, as every read in this codebase does, and a
    domain module that took a firm_id would be inviting one to be passed
    rather than applied.

    `exclude_id` keeps a row from reporting itself, which matters the moment
    this is asked on an EDIT rather than a create.
    """
    wanted = normalise_party_name(name)
    if not wanted.base:
        # Nothing to compare. An unnamed party is a different problem and the
        # required-field check is where it belongs.
        return []

    out: list[PossibleDuplicate] = []
    for row in candidates or []:
        if not row.get("is_active", True):
            continue
        rid = str(row.get("id") or "")
        if not rid or (exclude_id and rid == exclude_id):
            continue
        other = normalise_party_name(row.get(name_key))
        if not other.base:
            continue
        if other.normalised == wanted.normalised:
            reason = SAME_NAME
        elif other.base == wanted.base:
            reason = SAME_NAME_DIFFERENT_FORM
        else:
            continue
        out.append(PossibleDuplicate(
            id=rid,
            name=str(row.get(name_key) or ""),
            reason=reason,
            gstin=(row.get("gstin") or None),
            pan=(row.get("pan") or None),
        ))
    # Exact matches first: the stronger signal is the one to read.
    out.sort(key=lambda d: (d.reason != SAME_NAME, d.name.lower()))
    return out
