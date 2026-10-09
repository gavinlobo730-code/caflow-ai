"""Reads the deployment's payment settings and answers "is online payment switched on?" (PRE-B-002 part 2).

The rule is `domain/payments/availability.py` (a pure function of a provider name and which settings are set).
This module is its one reader of the environment, and the one door the ROUTES ask:

  * `current()`                  the deployment's state, read at call time (no cache: a dashboard change plus a
                                 redeploy flips it, and a test can set the environment and see it);
  * `portal_block()` / `staff_block()`   the words for a signed-in client / a member of the practice;
  * `require_online_payment(audience)`   raises a 409 carrying those words when a link may not be made or sent.

WHY THE GATE IS A CALL AT THE ROUTE AND NOT INSIDE `payment_service.create_link`. The service is the engine the
tests drive directly with the test double (twenty-seven call sites), and a service that refuses the test double
cannot be tested; a check in the engine would also be one caller from being none the day a second route reaches
it. So the rule is held at the route layer by `tests/test_a_payment_link_is_never_made_or_sent_while_online_
payment_is_off.py`, which derives every function that reaches `create_link` or `send_link_email` from the source
and fails one that does not ask this module first.

Only the NAMES of settings are ever read for their presence and reported: no value is returned, logged or put in
a message.
"""
from __future__ import annotations

import os

from fastapi import HTTPException

from domain.payments import availability as rule
from services.payments.factory import configured_provider


def _is_set(name: str) -> bool:
    # A blank dashboard value is not a value (core/env.py): an empty or spaces-only key counts as missing.
    return bool((os.environ.get(name) or "").strip())


def current() -> rule.Availability:
    """The state of this deployment now. The provider name goes through the same reader the factory uses, so the
    two cannot disagree about what a blank value means."""
    names = {n for settings in rule.GATEWAY_SETTINGS.values() for n in settings}
    return rule.assess(configured_provider(), {n: _is_set(n) for n in names})


def portal_block() -> dict:
    return rule.portal_block(current())


def staff_block() -> dict:
    return rule.staff_block(current())


def require_online_payment(audience: str) -> None:
    """Refuse with a 409 and the server's own sentence unless a real gateway is set up.

    `audience` is `"portal"` (a client: no setting named) or `"staff"` (a member of the practice: the setting
    names). Call this at the top of a route that creates or sends a payment link, after the permission and
    ownership checks and before anything is read or written.
    """
    a = current()
    if not a.available:
        raise HTTPException(status_code=409, detail=rule.refusal_sentence(a, audience))
