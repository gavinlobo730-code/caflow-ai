"""Is the SUPPLIER an extracted invoice names a supplier that could exist, and is
the tax charged the kind its place would give? (ai-02.)

WHAT WAS MISSING
    A model reading a photographed invoice is, for the GSTIN, TYPING fifteen
    characters it has looked at. This repository's own rule is that every GSTIN
    a human types is tested against its CHECK DIGIT (`domain/gst/gstin`), because
    the shape regex accepts every transposition inside the PAN, and the GSTIN is
    what routes the supplier's tax to the right registration. The extraction
    path was the one door that did not ask: `document_intelligence_v1` imported
    nothing from `domain/gst/gstin`, so a misread digit arrived looking exactly
    like a read one, and `PurchaseBillEditor` and `routers/purchase_bills`'
    `_match_extracted_vendor` then matched a vendor on a GSTIN nobody had
    verified.

    The second thing the document states twice and nothing compared: whether the
    supply is inter-State. The GSTIN's first two characters are the supplier's
    State (CGST §25), the client's own registration carries its State, and IGST
    Act §§7-8 make a same-State supply intra-State (CGST + SGST) and any other
    inter-State (IGST). A bill charging IGST between two Maharashtra
    registrations is usually a misread head — or a place of supply that is
    somewhere else, which only the CA can tell from the paper.

WHAT THIS IS
    Two checks, both calling the rule rather than restating it:
    `gstin.problem_with` for the check digit and
    `place_of_supply.supplier_state_code` for the client's State (the same chain
    `routers/purchase_bills` resolves it through, GSTIN first and the recorded
    column second). Both REPORT and neither refuses, rewrites or blocks: a CA
    holds the paper. Both name what they could not do — an unregistered supplier
    has no GSTIN to test, and a client with no State recorded has nothing to
    compare against — rather than passing in silence.

WHAT IT DOES NOT DO
    It does not decide the place of supply. Goods delivered to another State,
    services performed elsewhere, an SEZ, an import and a bill under reverse
    charge all legitimately break the same-State rule, and the sentence says so.
"""
from __future__ import annotations

from typing import Optional

from domain.gst import gstin as gstin_rule
from domain.gst.place_of_supply import supplier_state_code
from domain.money_text import rupees_paise

GSTIN = "gstin"
PLACE_OF_SUPPLY = "place_of_supply"

# The same one rupee `extraction_totals` allows for round-off: a head below it is
# nil for this purpose, so a stray paisa of CGST on an inter-State bill is not a
# finding.
_NIL_PAISE = 100


def _rs(paise: int) -> str:
    return f"₹{rupees_paise(paise)}"


def _p(extracted: dict, key: str) -> int:
    try:
        return int(extracted.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def check_gstin(extracted: dict) -> dict:
    """The supplier GSTIN against its own check digit.

    `present` False is an unregistered supplier OR a GSTIN nobody read, and the
    check cannot tell which — so it names neither and fails neither. `valid` is
    None then, never True: "nothing to test" is not "tested and fine"."""
    raw = extracted.get("vendor_gstin")
    text = raw.strip() if isinstance(raw, str) else ""
    if not text:
        return {"checked": False, "present": False, "valid": None, "problem": None,
                "state_code": None,
                "note": "No supplier GSTIN was read from the document, so there is no "
                        "registration number to check."}
    problem = gstin_rule.problem_with(text)
    return {
        "checked": True,
        "present": True,
        "valid": problem is None,
        "problem": problem,
        # The state is offered only for a GSTIN that passed: a doubtful one's
        # first two characters are as doubtful as the rest.
        "state_code": text.upper()[:2] if problem is None else None,
        "note": None if problem is None else (
            f"The supplier GSTIN read from the document ({text.upper()}) is not a valid "
            f"GSTIN: {problem} It has probably been misread — check it against the invoice "
            "before relying on the vendor it matched."),
    }


def check_place_of_supply(extracted: dict, client: Optional[dict], gstin_check: dict) -> dict:
    """IGST against CGST + SGST, given the supplier's State and the client's."""
    def not_run(reason: str, **extra) -> dict:
        return {"checked": False, "agrees": None, "expected": None,
                "supplier_state": gstin_check.get("state_code"),
                "client_state": extra.get("client_state"), "reason": reason}

    cgst, sgst, igst = _p(extracted, "cgst_paise"), _p(extracted, "sgst_paise"), _p(extracted, "igst_paise")
    intra, inter = cgst + sgst, igst
    supplier_state = gstin_check.get("state_code")
    client_state = supplier_state_code(client)

    if not gstin_check.get("present"):
        return not_run("No supplier GSTIN was read, so the supplier's State is unknown.",
                       client_state=client_state)
    if not gstin_check.get("valid"):
        return not_run("The supplier GSTIN is not valid, so its State cannot be relied on.",
                       client_state=client_state)
    if client_state is None:
        return not_run("This client's State is not recorded (no GSTIN and no State on the "
                       "client), so there is nothing to compare the supplier's State with.")
    if intra <= _NIL_PAISE and inter <= _NIL_PAISE:
        return not_run("No tax is charged on the document, so there is no head to check.",
                       client_state=client_state)
    if intra > _NIL_PAISE and inter > _NIL_PAISE:
        return not_run("The document charges both IGST and CGST/SGST (a bill mixing intra- and "
                       "inter-State supplies), which this check does not judge.",
                       client_state=client_state)

    same_state = supplier_state == client_state
    expected = "intra" if same_state else "inter"
    reason = None
    if same_state and inter > _NIL_PAISE:
        reason = (
            f"{_rs(igst)} of IGST is charged, but the supplier's GSTIN (State {supplier_state}) "
            f"and this client (State {client_state}) are in the same State, which gives CGST and "
            "SGST. The tax head has probably been misread — unless the place of supply is "
            "another State (goods delivered, or a service performed, elsewhere), which only the "
            "invoice can show.")
    elif not same_state and intra > _NIL_PAISE:
        reason = (
            f"{_rs(cgst + sgst)} of CGST and SGST is charged, but the supplier's GSTIN (State "
            f"{supplier_state}) and this client (State {client_state}) are in different States, "
            "which gives IGST. The tax heads have probably been misread — unless the place of "
            "supply is the supplier's own State, which only the invoice can show.")
    return {"checked": True, "agrees": reason is None, "expected": expected,
            "supplier_state": supplier_state, "client_state": client_state, "reason": reason}


def check_supplier(extracted: dict, client: Optional[dict]) -> dict:
    """Both checks, and what to show: `failures` are the ones that ran and found
    something, as `{check, reason}` ready to render; `agrees` is False if any did.
    `client` is the client's row (its `gstin` and `state_code` are all that is
    read) or None where it could not be read."""
    g = check_gstin(extracted)
    p = check_place_of_supply(extracted, client, g)
    failures = []
    if g["checked"] and g["valid"] is False:
        failures.append({"check": GSTIN, "reason": g["note"]})
    if p["checked"] and p["agrees"] is False:
        failures.append({"check": PLACE_OF_SUPPLY, "reason": p["reason"]})
    return {"gstin": g, "place_of_supply": p, "failures": failures, "agrees": not failures}
