"""The one place a property test's settings are decided (engineering-23).

IMPORTED BY the modules that generate their inputs with Hypothesis, and not a test itself. It is a separate file
because the same three decisions have to hold for every one of them, and three copies of a settings block are how
one of them ends up non-deterministic.

WHAT IT DECIDES

  * DETERMINISTIC. `derandomize=True` makes Hypothesis derive its examples from the test's own source instead of
    from entropy, so a run on a laptop and a run in CI try the same inputs, and a red build is a red build rather
    than a lucky draw. A property test that fails one run in twenty is a test nobody trusts, and the repository's
    other guards are exact for the same reason. (The cost is that it explores the same space every time; the
    breadth comes from `max_examples`, and a person who wants a wider search runs it with a bigger number by hand.)
  * NO REPLAY DATABASE. `database=None` stores no examples and replays nobody else's failures. With derandomize it
    would not be consulted anyway. It does NOT keep a `.hypothesis/` directory out of the tree: Hypothesis writes a
    small cache of its own there (`.hypothesis/constants`, about 3 MB after a full run), whatever the database
    setting, which is why .gitignore ignores the directory.
  * A DEADLINE THAT CANNOT FLAKE. Two seconds an example, where the functions under test take microseconds. It
    exists to catch a kernel that has become quadratic, not to time a loaded runner: Hypothesis's default is 200 ms
    and has failed healthy code on shared CI machines. `HealthCheck.too_slow` is suppressed for the same reason: it
    measures how long GENERATING inputs took, which on a busy runner says nothing about the code.

NO HYPOTHESIS, NO PROPERTY TESTS, AND SAYING SO ONLY WHERE IT IS SAFE
    Hypothesis is in requirements-dev.txt, not requirements.txt, so a checkout that has only the application's
    requirements skips these modules. Where `CI` is set it is an ERROR instead: a property test that did not run is
    not a passing one, and requirements-dev.txt is what the test job installs.
"""
from __future__ import annotations

import os
from datetime import timedelta

import pytest

try:
    from hypothesis import HealthCheck, settings
    from hypothesis import strategies as st
except ImportError:  # pragma: no cover - exercised only where hypothesis is absent
    if os.environ.get("CI"):
        raise
    pytest.skip("hypothesis is not installed here (requirements-dev.txt pins it)", allow_module_level=True)

PROFILE = settings(
    derandomize=True,
    database=None,
    deadline=timedelta(milliseconds=2000),
    max_examples=300,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
    print_blob=True,
)


def kernel(**overrides) -> settings:
    """The profile, with any setting this one test genuinely needs different."""
    return settings(PROFILE, **overrides)


#: A single document's amount, in paise: up to ₹10,000 crore. Far above any bill this product has seen, and low
#: enough that a kernel which does its division in `Decimal` (28 significant digits) is still exact. The magnitude
#: tests that go past 2^53 are written for the kernels that are pure integer arithmetic.
PAISE_MAX = 10 ** 12

#: Past 2^53 (about 9.0e15), where a float can no longer hold every integer. A pure-integer kernel must not care.
HUGE_PAISE_MAX = 10 ** 19


def paise(min_value: int = 0, max_value: int = PAISE_MAX):
    return st.integers(min_value=min_value, max_value=max_value)


@st.composite
def weights(draw, min_size: int = 1, max_size: int = 12, max_value: int = PAISE_MAX):
    """A list of non-negative whole weights with at least one that is not nil.

    Built rather than filtered: one weight is drawn positive and placed at a drawn position among the rest, so
    no example is thrown away for being all zeros (a `.filter` here made Hypothesis discard and retry draws, which
    on a slow runner is what trips its health checks)."""
    rest = draw(st.lists(st.integers(min_value=0, max_value=max_value), min_size=max(0, min_size - 1),
                         max_size=max_size - 1))
    positive = draw(st.integers(min_value=1, max_value=max_value))
    at = draw(st.integers(min_value=0, max_value=len(rest)))
    return [*rest[:at], positive, *rest[at:]]


#: The GST rate, in basis points, for the arithmetic tests: every figure from nil to the 40% IGST ceiling
#: (IGST Act §5(1)), so the odd rates (0.1%, 0.25%, 1.5%, 7.5%) that lose a paisa are all reachable.
rate_bps = st.integers(min_value=0, max_value=4000)
