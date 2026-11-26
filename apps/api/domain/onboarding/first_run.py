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
  * Nothing about the FIRM is stored. A person can dismiss the card for good (POST-A-002,
    migration 557: `users.first_run_dismissed_at`), and that is a fact about the person and
    not about the firm: a second Partner who has not dismissed it still sees it. The browser
    may also COLLAPSE the card on one device, a per-viewer convenience and not a record.
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

# THE FIRM'S OWN PRACTICE (POST-A-533). The four steps above are all about clients, so a new CA could finish the card
# without learning that the firm's own books exist. These are the same idea for the firm itself, and they are a SECOND
# list and not four more rows of the first: only a Partner reaches the practice's own record (guardrail G1), so only a
# Partner is sent them, and a Manager's card is the four steps it always was. Each ticks from the practice's own rows.
PRACTICE_STEPS: tuple[StepDef, ...] = (
    StepDef("practice_identity", "Check your own firm's details",
            "Your firm is kept as a client of itself, so it has books of its own. They are set up from "
            "the firm's PAN and legal form: check both before the first entry goes in."),
    StepDef("practice_books", "Start your own firm's books",
            "Enter the opening balances from your earlier books, or post the first entry. Until "
            "then every statement of your own firm is empty."),
    StepDef("practice_statement", "Import your firm's own bank statement",
            "The firm's own bank account is reconciled the way a client's is, from a worklist "
            "of proposed entries."),
    StepDef("practice_fee_bill", "Raise your first fee bill",
            "A fee bill issued from My practice posts to your own firm's books and is what its "
            "own GST return is built from."),
)

PRACTICE_STEP_IDS: tuple[str, ...] = tuple(s.id for s in PRACTICE_STEPS)


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
        # Not a timestamp. A timestamptz column always reads back as ISO text, so a stored instant never lands here: this is an absent value or a
        # hand-built one, and None says there is no instant.
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


def _listed(definitions: tuple[StepDef, ...], facts: Mapping[str, Fact]) -> dict:
    """One list of steps with its own counts. A step the facts omit reads as unreadable."""
    steps = []
    for definition in definitions:
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
    return {
        "steps": steps,
        "total": len(steps),
        "done_count": done_count,
        "complete": done_count == len(steps),
        "next_step": next((s["id"] for s in steps if s["done"] is False), None),
        "unreadable": unreadable,
    }


def _has_something_to_do(listed: dict) -> bool:
    """Not finished, and at least one step could be read: a list that is all question marks asks for nothing."""
    return (not listed["complete"]) and len(listed["unreadable"]) < listed["total"]


def build(facts: Mapping[str, Fact], *, firm_created_at: object = None, dismissed: Optional[bool] = None,
          practice_facts: Optional[Mapping[str, Fact]] = None, practice_client_id: Optional[str] = None) -> dict:
    """The checklist for one firm, as one PERSON sees it. `facts` may omit a step, which reads as unreadable.

    `dismissed` is whether THIS person dismissed the card for good: True hides it, and False and None leave it to the steps. None is
    "could not be read", which is not a dismissal: a card the person did not ask to lose stays, and the answer says `dismissed: None`.

    `practice_facts` is given for a PARTNER and for nobody else (None): the firm's own practice is the Partner's alone, so
    its steps, and the id of its record that their links open, are in a Partner's answer only. `practice` is then a
    second list with its own counts, and the card stays while EITHER list has something to do."""
    clients = _listed(STEPS, facts)
    steps, done_count, unreadable = clients["steps"], clients["done_count"], clients["unreadable"]
    complete, next_step = clients["complete"], clients["next_step"]

    practice = None
    if practice_facts is not None:
        practice = {**_listed(PRACTICE_STEPS, practice_facts),
                    # The practice's own record, for the links; None while it is not set up, and the first step says so.
                    "client_id": str(practice_client_id) if practice_client_id else None}
    to_do = _has_something_to_do(clients) or (practice is not None and _has_something_to_do(practice))

    first_invoice = facts.get("first_invoice") or Fact(None)
    return {
        "steps": steps,
        "total": len(steps),
        "done_count": done_count,
        "complete": complete,
        "next_step": next_step,
        "unreadable": unreadable,
        "dismissed": dismissed if dismissed in (True, False) else None,
        "visible": to_do and dismissed is not True,
        # The firm's own practice: a second list, in a Partner's answer only (None for everybody else).
        "practice": practice,
        "minutes_to_first_invoice": (
            minutes_between(firm_created_at, first_invoice.at) if first_invoice.done is True else None),
    }
