"""
A broken user lookup is a 503, not a 403.

WHAT WENT WRONG IN PRODUCTION
    The client Overview page showed five consecutive
    `GET /api/identity/permissions 403 (Forbidden)` in the console while
    `GET /health` was returning 503. Nothing about authorization was wrong: the
    firm had one user, Partner, is_active true, in an active, non-deleted firm,
    correctly linked by auth_user_id. The backend was simply unhealthy, the
    Supabase users lookup threw, and the except branch set user_data = None —
    which the caller could not tell apart from "no such user" and reported as
    "User not found in firm."

WHY THE STATUS CODE MATTERS
    403 is a statement that the caller is permanently not allowed. A client that
    believes it fails closed and stays closed; the frontend's permission helpers
    do exactly that, so the UI degrades as though the user had lost their role.
    503 says the opposite — the request could not be served right now, try
    again — which is the truth and is retryable.

    The distinction only became expressible when the query moved from single()
    to maybe_single(): single() raised on both zero rows and a failed query, so
    the two really were indistinguishable. maybe_single() returns data=None for
    zero rows without raising, so an exception now means the query itself broke.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import core.auth as auth


class _Boom:
    """A Supabase client whose users lookup fails the way a struggling
    instance's does — an exception, not an empty result."""

    def table(self, _name):
        return self

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        raise RuntimeError("connection reset by peer")


class _NoRow:
    """A working lookup that genuinely finds nobody."""

    def table(self, _name):
        return self

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        return type("R", (), {"data": None})()


@pytest.fixture(autouse=True)
def _clear_cache():
    # The lookup memoises per auth_user_id; a hit would skip the code under test.
    auth._user_lookup_cache.clear()
    yield
    auth._user_lookup_cache.clear()


def test_a_failed_lookup_raises_503_not_403():
    with pytest.raises(HTTPException) as e:
        auth._get_user_and_firm(_Boom(), "auth-user-1")
    assert e.value.status_code == 503, (
        "a transient lookup failure is being reported as an authorization "
        "decision — the frontend fails closed and the user appears to have lost "
        "their role")


def test_the_503_does_not_tell_the_user_their_account_is_wrong():
    """The old message sent people to their firm administrator for a problem no
    administrator could fix."""
    with pytest.raises(HTTPException) as e:
        auth._get_user_and_firm(_Boom(), "auth-user-1")
    assert "administrator" not in e.value.detail.lower()
    assert "again" in e.value.detail.lower(), "say that retrying is the fix"


def test_a_genuinely_missing_user_is_still_reported_as_missing():
    """The other half of the distinction. A working query that finds no row must
    keep returning (None, None) so the caller still raises its 403 — otherwise
    this change would turn a real authorization failure into a retry loop."""
    user, firm = auth._get_user_and_firm(_NoRow(), "auth-user-2")
    assert user is None and firm is None


def test_the_failure_is_not_cached():
    """A cached failure would make one bad second look like a broken account for
    the whole TTL."""
    with pytest.raises(HTTPException):
        auth._get_user_and_firm(_Boom(), "auth-user-3")
    assert "auth-user-3" not in auth._user_lookup_cache, (
        "a transient failure was memoised — the next request would be told the "
        "same thing without even retrying the lookup")
