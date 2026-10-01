"""The four things a new firm does first, and how each one is KNOWN to be done
(market_and_trust-16).

WHAT WAS WRONG. After sign-up a new owner went through a magic link, a password, a
firm profile, an optional HSN step and, for a Partner or Manager, authenticator
enrolment — and landed on a dismissible welcome card with five links that appeared
ONCE (`?welcome=1`) and was gone for good. Nothing tracked progress, so a firm that
closed the tab after adding a client had no way to see that the invoice and the
statement were still ahead of it, and nothing could say how long the first sitting took.

THE RULE, which is the whole of this module: a step is done when the FIRM'S OWN DATA
says so. Nothing is stored. A tick that was a stored flag would drift the first time
a row was deleted or created by a door that forgot to set it — the reason migration 278
made `outstanding_paise` a generated column — and "persists across logins" falls out of
it for free, because the answer is computed from the firm's rows and not from anybody's
session. A second Partner who signs in next week sees exactly what the first one did.

  first_client      a client that is not the firm's own practice record
  first_invoice     a sales invoice that has been ISSUED for a client — not a draft, and
                    not an opening-balance document (`is_opening`: the old system's
                    invoice carried over, which the CA did not raise here)
  first_statement   a bank statement imported
  invite_colleague  a second active person in the firm — invited or joined, because the
                    invite is a `users` row from the moment it is sent

THE THREE STATES. A step's `done` is True, False or None, and None is "this could not be
read", which is NOT "not done": a read that failed rendered as an unticked step tells a
firm to repeat something it has already done, and rendered as a tick tells it something
nobody checked. Unreadable steps are named in `unreadable` and are not counted.

`visible` is decided HERE and not in the browser: the card shows while the firm has
something to do and at least one step could be read. A firm that has done all four sees
nothing; a read that failed everywhere sees nothing rather than four question marks.

TIME TO FIRST VALUE is derived, not logged: `minutes_to_first_invoice` is the gap
between the firm's own `created_at` and the earliest qualifying invoice's. It needs no
table because both timestamps already exist, and it is served whether or not the card
is still showing, so a person rehearsing the sign-up can read it off afterwards.

WHAT THIS DELIBERATELY DOES NOT DO.
  * No "dismiss for good". That needs a column (`users.first_run_dismissed_at`) and no
    migration number was left for it; the browser may COLLAPSE the card on this device,
    which is a per-viewer convenience and not a record. The card stays as one line.
  * It does not count the practice's own FEE invoices (`fee_invoices`): the step is about
    the books of a client, which is what the product is for, and a pure-billing firm
    that never raises a client invoice will see that step stay open.
  * It does not offer sample data or load the demo practice.

REHEARSAL (a human step, and the finding's other half). Someone outside the team, with
a fresh email address and no authenticator app, signs up and tries to reach a first
issued invoice unaided: sign-up -> magic link -> password -> firm profile -> HSN (skip)
-> dashboard. They are not told where anything is. Afterwards the facts are in the data:
`GET /api/onboarding/status` returns `first_run.minutes_to_first_invoice`, and the step
`done_at` stamps show where the time went. What they could not find, and any step the
card said was done that was not, is the list to fix. Nothing in this repository can do
that for them.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Optional


@dataclass(frozen=True)
class StepDef:
    id: str
    title: str
    why: str


# The order is a suggestion — each step ticks on its own — and it is the order a firm
# meets the product in: somebody to do the work for, the books, the bank, the team.
STEPS: tuple[StepDef, ...] = (
    StepDef("first_client", "Add your first client",
            "Every ledger, return and deadline in PracticeSync belongs to a client, so "
            "nothing else can start until one exists."),
    StepDef("first_invoice", "Raise your first invoice",
            "An issued sales invoice posts to the client's books and is what the GST "
            "return is built from. A draft or an opening-balance document does not count."),
    StepDef("first_statement", "Import a bank statement",
            "Every line arrives with a proposed entry already on it, so reconciling starts "
            "from a worklist and not from a blank page."),
    StepDef("invite_colleague", "Invite a colleague",
            "Work can be assigned and a second person can review it. A Partner invites "
            "staff from the Team screen."),
)

STEP_IDS: tuple[str, ...] = tuple(s.id for s in STEPS)


@dataclass(frozen=True)
class Fact:
    """What the firm's data says about one step. `done` None means UNREADABLE."""
    done: Optional[bool]
    at: Optional[str] = None  # ISO timestamp of the earliest qualifying row


def _parse(ts: object) -> Optional[datetime]:
    if not isinstance(ts, str) or not ts.strip():
        return None
    try:
        parsed = datetime.fromisoformat(ts.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    # A timestamptz comes back with an offset; a bare one was written as UTC.
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def minutes_between(start: object, end: object) -> Optional[int]:
    """Whole minutes from `start` to `end`, or None when either is missing or the
    order is backwards (a document carried over from before the firm existed here is
    not a time to first value)."""
    a, b = _parse(start), _parse(end)
    if a is None or b is None or b < a:
        return None
    return int((b - a).total_seconds() // 60)


def build(facts: Mapping[str, Fact], *, firm_created_at: object = None) -> dict:
    """The checklist for one firm. `facts` may omit a step, which reads as unreadable."""
    steps = []
    for definition in STEPS:
        fact = facts.get(definition.id) or Fact(None)
        steps.append({
            "id": definition.id,
            "title": definition.title,
            "why": definition.why,
            "done": fact.done if fact.done in (True, False) else None,
            "done_at": fact.at if fact.done is True else None,
        })

    done_count = sum(1 for s in steps if s["done"] is True)
    unreadable = [s["id"] for s in steps if s["done"] is None]
    complete = done_count == len(steps)
    next_step = next((s["id"] for s in steps if s["done"] is False), None)
    readable = len(unreadable) < len(steps)

    first_invoice = facts.get("first_invoice") or Fact(None)
    return {
        "steps": steps,
        "total": len(steps),
        "done_count": done_count,
        "complete": complete,
        "next_step": next_step,
        "unreadable": unreadable,
        "visible": (not complete) and readable,
        "minutes_to_first_invoice": (
            minutes_between(firm_created_at, first_invoice.at) if first_invoice.done is True else None),
    }
