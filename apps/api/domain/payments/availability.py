"""Whether online payment is switched on, and what a person is told when it is not (PRE-B-002 part 2).

THE RULE THIS HOLDS: A PAY CONTROL IS ENABLED, AND A PAYMENT LINK IS MADE OR SENT, ONLY WHEN A REAL GATEWAY IS
SET UP. Everything else is "Online payment is coming soon", said by the SERVER.

WHAT WAS WRONG. The portal's Pay Now button, the staff "Payment Link" modal and the emailed Pay Now button were
shown with no check of the configured provider. With `PAYMENT_PROVIDER` blank or `mock` (the production state: a
blank reads as the mock since 8 October 2026) the link was `https://mock-pay.local/pay/<id>`, an address that does
not exist, and the staff modal could mail it to a client's customer. The button also appeared on a DRAFT or a
CANCELLED invoice, because the portal's only test was `outstanding_paise > 0` and an outstanding figure is clamped
at zero but not tied to a status.

WHAT THIS MODULE IS. A pure rule: it reads no file, database or environment variable, so the environment is
read once, in `services/payments/availability.py`, and handed in (the clock is an argument too, defaulting to now). It answers four questions and every one of them is a function
of its arguments:

  * `assess`         which of four states the deployment is in (`live`, `setup_incomplete`, `not_switched_on`,
                     `unrecognised`), and whether a link may be made;
  * `portal_block` / `staff_block`   the words, one block per audience, so the browser holds none of them;
  * `invoice_is_payable`             which invoices a client may be offered a pay control for;
  * `link_problem` / `mask_link`     which stored links may be shown or emailed (a link made before online payment
                                     was switched on points nowhere and is never put in front of a person).

THE FOUR STATES ARE NOT INTERCHANGEABLE, because each sends a person somewhere different:

  * `not_switched_on`    no provider is chosen (blank), or it is `mock`, the test double that returns an address
                         that does not resolve. Nothing is wrong; nothing is set up.
  * `setup_incomplete`   a real gateway is chosen and a key or the webhook secret is missing. The webhook secret
                         matters as much as the keys: without it every delivery is unverified and refused, so a
                         payment could be captured at the gateway and no receipt ever posted.
  * `unrecognised`       a value the provider factory would refuse (`stripe`, a typo).
  * `live`               the only state in which `available` is True. NEVER `mock`.

WHO IS TOLD WHAT. The CLIENT's words say that online payment is coming soon and what to do meanwhile; they never
name a setting, a gateway or the test double (a client cannot act on any of them and the names are none of their
business). The STAFF words say why, in plain terms, and carry the NAMES of the settings to check (never a value),
because the person who sees them is the one who can change them.

THE WORDS (the house rule, `docs/open-items/coming-soon.md`): "coming soon" is for an ordinary product feature
decided and not yet switched on, and online payment is one. Nothing here says a registration is in motion: the
merchant account is the owner's and has not been opened. Nothing is ever sent to a client's customers
automatically (D27): "coming soon" never means a scheduled send.

Statutory note: none. Online payment moves money through the existing receipt engine on a verified capture only
(payment_service); this module decides nothing about GST or TDS.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Optional

LIVE = "live"
SETUP_INCOMPLETE = "setup_incomplete"
NOT_SWITCHED_ON = "not_switched_on"
UNRECOGNISED = "unrecognised"
STATES = (LIVE, SETUP_INCOMPLETE, NOT_SWITCHED_ON, UNRECOGNISED)

#: The one setting that chooses a provider.
PROVIDER_SETTING = "PAYMENT_PROVIDER"

#: A provider that is a real gateway, with the settings it cannot work without (names only: no value is ever held
#: here). A provider absent from this map and from `NOT_A_GATEWAY` is `unrecognised`.
GATEWAY_SETTINGS: dict[str, tuple[str, ...]] = {
    "razorpay": ("RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET", "RAZORPAY_WEBHOOK_SECRET"),
}

#: Providers that exist for tests and local work. `mock` returns `https://mock-pay.local/...`, which does not
#: resolve, so it is never a way to collect money and never "live".
NOT_A_GATEWAY = ("mock",)

#: A link row whose provider is one of these is never shown or sent: the address it carries goes nowhere.
NEVER_SHOWN_PROVIDERS = frozenset(NOT_A_GATEWAY)

#: An invoice a client may be offered a pay control for. The same two statuses `lib/invoices/hub.ts` calls
#: "collectible" and `portal_data_service._OPEN` calls open: a draft has not been issued and a cancelled invoice
#: is not owed, and a paid one has nothing left, however the outstanding figure reads.
PAYABLE_STATUSES = ("issued", "partially_paid")

HEADLINE = "Online payment is coming soon."
LABEL_LIVE = "Pay Now"
LABEL_COMING_SOON = "Pay Now · coming soon"

CLIENT_REASON = (
    "It has not been switched on yet, so for now please pay using the payment details on your invoice, "
    "or ask your accountant how to pay."
)

_STAFF_TAIL = "so no payment link can be created or emailed to a customer yet."
STAFF_REASONS: dict[str, str] = {
    NOT_SWITCHED_ON: "Online payment has not been switched on for this deployment, " + _STAFF_TAIL,
    SETUP_INCOMPLETE: (
        "A payment gateway has been chosen but its setup is incomplete (a key or the webhook secret is "
        "missing), " + _STAFF_TAIL
    ),
    UNRECOGNISED: "The payment setting names a gateway this product does not recognise, " + _STAFF_TAIL,
}

MASKED_LINK_NOTE = (
    "Made before online payment was switched on. It cannot be used and is not shown."
)


@dataclass(frozen=True)
class Availability:
    """The deployment's answer. `settings_to_check` is names only, and is empty when `live`."""

    state: str
    settings_to_check: tuple[str, ...] = ()

    @property
    def available(self) -> bool:
        return self.state == LIVE


def assess(provider: Optional[str], present: Mapping[str, bool]) -> Availability:
    """The state a deployment is in.

    `provider` is the configured provider name (lower case, blank allowed: the factory reads a blank as `mock`,
    so a blank here is `not_switched_on` as well). `present` says which settings hold a non-blank value, by name;
    a name absent from it is treated as not set.
    """
    name = (provider or "").strip().lower()
    if name == "" or name in NOT_A_GATEWAY:
        return Availability(NOT_SWITCHED_ON, (PROVIDER_SETTING,))
    required = GATEWAY_SETTINGS.get(name)
    if required is None:
        return Availability(UNRECOGNISED, (PROVIDER_SETTING,))
    missing = tuple(s for s in required if not present.get(s))
    if missing:
        return Availability(SETUP_INCOMPLETE, missing)
    return Availability(LIVE)


# ── the words, one block per audience ────────────────────────────────────────────────────────────────────────


def portal_block(a: Availability) -> dict:
    """What a signed-in CLIENT is shown. No state, no setting name, no gateway name."""
    if a.available:
        return {"available": True, "label": LABEL_LIVE, "headline": None, "reason": None}
    return {"available": False, "label": LABEL_COMING_SOON, "headline": HEADLINE, "reason": CLIENT_REASON}


def staff_block(a: Availability) -> dict:
    """What a member of the practice is shown: the same labels plus the state and the names of the settings."""
    out = portal_block(a)
    if not a.available:
        out["reason"] = STAFF_REASONS[a.state]
    out["state"] = a.state
    out["settings_to_check"] = list(a.settings_to_check)
    return out


def refusal_sentence(a: Availability, audience: str) -> str:
    """The sentence a 409 carries: the headline and the reason for that audience, as one string."""
    block = portal_block(a) if audience == "portal" else staff_block(a)
    return f"{block['headline']} {block['reason']}"


# ── which invoices, which links ──────────────────────────────────────────────────────────────────────────────


def invoice_is_payable(status: Optional[str], outstanding_paise: Optional[int]) -> bool:
    """True for an issued or part-paid invoice with something still owed. Integer paise; a missing figure is no."""
    try:
        owed = int(outstanding_paise or 0)
    except (TypeError, ValueError):
        return False
    return (status or "").strip().lower() in PAYABLE_STATUSES and owed > 0


def mask_link(link: dict) -> dict:
    """The link as a screen may show it: a link made by the test double has no address and says why."""
    if (link.get("provider") or "").strip().lower() in NEVER_SHOWN_PROVIDERS:
        return {**link, "short_url": None, "note": MASKED_LINK_NOTE}
    return link


def _parse_instant(value: object) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def link_problem(link: dict, configured_provider: str, now: Optional[datetime] = None) -> Optional[str]:
    """Why this stored link must not be emailed, or None when it may be.

    A link is sent only if it was made by the provider that is configured now (so a link made before online
    payment was switched on, or under another gateway, is never mailed), it is `active` (not half-made, paid,
    expired or cancelled), it has an address, and its own expiry has not passed (nothing yet sets `expired`, so
    the date is what says so).
    """
    provider = (link.get("provider") or "").strip().lower()
    if provider in NEVER_SHOWN_PROVIDERS or provider != (configured_provider or "").strip().lower():
        return ("This payment link was made before online payment was switched on, or under another gateway, "
                "so it is not emailed. Create a new one once online payment is available.")
    status = (link.get("status") or "").strip().lower()
    if status != "active":
        return f"This payment link is not active (its status is {status or 'unknown'}), so it is not emailed."
    if not (link.get("short_url") or "").strip():
        return "This payment link has no address to send."
    expires = _parse_instant(link.get("expires_at"))
    if expires is not None and expires <= (now or datetime.now(timezone.utc)):
        return "This payment link has expired and cannot be emailed. Create a new one."
    return None
