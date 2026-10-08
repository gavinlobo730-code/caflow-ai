"""Environment values as a deployment really presents them.

A BLANK VALUE IS NOT AN UNSET ONE. Render lists every `sync: false` key of render.yaml in the dashboard whether or
not anyone has filled it in, and an empty box reaches the process as an empty string, not as a missing variable.
`os.environ.get(<name>, <default>)` returns the empty string for it (the default only covers a variable that is
absent), so a setting that was never touched silently overrode its own default:

  * `PAYMENT_PROVIDER` blank read as a provider called "" and creating a payment link raised
    `Unsupported PAYMENT_PROVIDER` instead of falling back to the mock;
  * `EMAIL_FROM` blank gave an empty sender, which the mail provider refuses;
  * `MFA_REQUIRED_ROLES` blank meant MFA is required of nobody;
  * `SENTRY_TRACES_SAMPLE_RATE` blank crashed start-up on `float("")`.

`env_or_default` is the one way to read a setting that has a default: a value that is unset, empty or only spaces
is "not set" and the default applies. `tests/test_a_blank_dashboard_value_reads_as_not_set.py` fails any server
read that gives `os.environ.get` / `os.getenv` a non-empty default of its own, so the next one cannot be written
the old way. A KILL SWITCH is the deliberate exception (`ENABLE_FILING_SIMULATION`: anything that is not an explicit yes is OFF, so a
blank is an operator turning it off, pinned by tests/test_filing_simulation_never_files.py) and is named in the guard.
A setting with NO default, where blank and absent already mean the same (`(x or "").strip()`), is not
affected and does not need this.
"""
from __future__ import annotations

import os


def env_or_default(name: str, default: str) -> str:
    """The variable's value with surrounding spaces removed, or `default` when it is unset, empty or blank."""
    value = (os.environ.get(name) or "").strip()
    return value or default
