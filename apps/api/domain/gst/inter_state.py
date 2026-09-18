"""Whether a supply is INTER-STATE, which is not only a question about states.

SALES-33. `routers/sales_invoices.py` derived it as `client_state_code !=
place_of_supply`, which is CGST §8(1) and is right for an ordinary domestic
supply and wrong for the two classes IGST §7(5) makes inter-State by statute
whatever the geography:

  * **§7(5)(a)** — supplier in India, place of supply OUTSIDE India. An export.
  * **§7(5)(b)** — a supply **to or by** a Special Economic Zone developer or
    unit. Location is irrelevant; the SEZ is deemed to be outside the customs
    frontier for this purpose.

And §8(1)'s own definition of an intra-State supply carries a proviso excluding
"supplies made to or by a Special Economic Zone developer or a Special Economic
Zone unit" — so the two sections agree and neither leaves room for a state
comparison to decide it.

WHAT THAT COST, MEASURED. A supply to an SEZ unit inside the supplier's own
state resolved `place_of_supply` to that same state, compared equal, and booked
**CGST + SGST**. On ₹1,00,000 at 18% that is ₹9,000 + ₹9,000 where IGST §16(1)(b)
and §7(5)(b) give ₹18,000 of IGST or, under an LUT, nothing at all. Three things
are then wrong at once: the customer is charged the wrong heads, the SEZ unit
cannot claim what they were charged, and GSTR-1 files a `SEWP`/`SEWOP` row
carrying `camt` and `samt`, which the portal's own validation 32 rejects.

The EXPORT case reaches the same place by a different road. A foreign buyer has
no GSTIN and no state, so `recipient_place_of_supply` falls through its chain to
the SUPPLIER's own state — which is correct and deliberate for IGST
§12(2)(b)(ii)'s unregistered walk-in, and is exactly wrong here. The comparison
then finds the two equal and charges CGST + SGST on an export.

THE TREATMENT DECIDES, AND IT IS ASKED FIRST. `domain/gst/treatment` already
derives what kind of supply a document is from `supply_type` and `invoice_type`
— the pair GSTR-1 is built from — so this module asks it rather than re-deriving
anything, and a state comparison is reached only where the treatment does not
settle it. Writing it the other way round (compare states, then override) is the
same bug with more steps: the override is what somebody forgets.

A DEEMED EXPORT IS NOT HERE AND THAT IS THE ONE TO GET RIGHT. §147 deems certain
supplies of GOODS to be exports, but the goods do not leave India and §7(5) does
not name it — so a deemed export is an ORDINARY domestic supply for this
purpose, inter-State or intra-State by where the parties are, and it commonly
carries CGST + SGST. Folding it in with the other two because the word "export"
appears in its name would charge IGST on a domestic supply.

`is_inter_state` ON THE REQUEST STILL WINS WHERE IT IS TRUE, unchanged: a
caller who states it is asserting a fact about a supply this module cannot see,
and the mock branch has always honoured it. What it may not do any more is make
an export or an SEZ supply intra-State by staying silent.
"""
from __future__ import annotations

from typing import Optional

from domain.gst import treatment as _treatment

#: IGST §7(5)(a). The place of supply is outside India, so no state comparison
#: can apply — there is no second state to compare with.
_EXPORTS = frozenset({
    _treatment.EXPORT_WITH_PAYMENT,
    _treatment.EXPORT_WITHOUT_PAYMENT,
})

#: IGST §7(5)(b) with the proviso to §8(1). A supply to or by an SEZ developer
#: or unit, wherever both parties sit.
_SEZ = frozenset({
    _treatment.SEZ_WITH_PAYMENT,
    _treatment.SEZ_WITHOUT_PAYMENT,
})

#: The treatments §7(5) makes inter-State whatever the states say.
ALWAYS_INTER_STATE = _EXPORTS | _SEZ

#: Why, per treatment — carried onto the answer so a screen can say it rather
#: than presenting IGST on a same-state invoice as an unexplained result.
#:
#: NEITHER SENTENCE MENTIONS §16(3), and that is deliberate. Whether the supply
#: is made under a letter of undertaking or on payment of integrated tax is a
#: different question with a different answer — it decides what tax is CHARGED,
#: not which heads it falls under — and this module would have to guess it at
#: create time, before any tax has been computed. One module, one rule.
_EXPORT_REASON = (
    "IGST §7(5)(a): the place of supply is outside India, so this is an "
    "inter-State supply however the supplier's own state compares."
)
_SEZ_REASON = (
    "IGST §7(5)(b) with the proviso to §8(1): a supply to a Special Economic "
    "Zone developer or unit is inter-State wherever both parties are."
)
_REASON = {
    _treatment.EXPORT_WITH_PAYMENT: _EXPORT_REASON,
    _treatment.EXPORT_WITHOUT_PAYMENT: _EXPORT_REASON,
    _treatment.SEZ_WITH_PAYMENT: _SEZ_REASON,
    _treatment.SEZ_WITHOUT_PAYMENT: _SEZ_REASON,
}

#: Named on a deemed export so the absence is visible as a decision. §147 deems
#: the supply an export; the goods do not leave India and §7(5) does not reach
#: it, so it is placed by geography like any other domestic supply.
DEEMED_EXPORT_IS_DOMESTIC = (
    "A deemed export under §147 is NOT inter-State by statute: the goods do not "
    "leave India and IGST §7(5) does not name it. It is placed by the supplier's "
    "state and the place of supply, like any other domestic supply, and commonly "
    "carries central and State tax."
)


def is_inter_state(
    *,
    gst_treatment: Optional[str],
    supplier_state_code: Optional[str],
    place_of_supply: Optional[str],
    stated: Optional[bool] = None,
) -> tuple[bool, str]:
    """Inter-State or not, and the sentence saying which rule decided it.

    The order is the whole rule:

      1. the STATUTE — §7(5) reaches exports and SEZ supplies whatever the
         states are, so it is asked before anything can compare them;
      2. what the CALLER stated, where they stated True. A caller asserting it
         knows something this module cannot see; a caller staying SILENT is not
         asserting the supply is intra-State, which is why `False` and `None`
         are the same thing here and why the statute is asked first;
      3. §8(1) — the ordinary comparison.

    An unknown state on either side falls to False, which is unchanged
    behaviour and is the direction that cannot invent an inter-State supply out
    of missing data: CGST + SGST on a supply that turns out inter-State is a
    correctable mis-declaration on one return, while IGST charged because a
    column was empty is money collected under the wrong head from a customer
    who then cannot claim it.
    """
    kind = (gst_treatment or "").strip().lower()
    if kind in ALWAYS_INTER_STATE:
        return True, _REASON[kind]

    if stated:
        return True, (
            "Stated on the request. CGST §8(1) is not asked where the caller "
            "has asserted the supply is inter-State."
        )

    if supplier_state_code and place_of_supply:
        if supplier_state_code != place_of_supply:
            return True, (
                f"CGST §8(1): the supplier is in state {supplier_state_code} "
                f"and the place of supply is {place_of_supply}, so this is an "
                f"inter-State supply."
            )
        return False, (
            f"CGST §8(1): the supplier and the place of supply are both in "
            f"state {supplier_state_code}, so this is an intra-State supply."
        )

    return False, (
        "Neither the supplier's state nor the place of supply is recorded, so "
        "CGST §8(1) cannot be applied and the supply is treated as intra-State. "
        "Record both to settle it."
    )
