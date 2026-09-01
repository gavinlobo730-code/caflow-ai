"""
A document that would not save has to say WHY, and must not invite a retry that
cannot work.

WHAT WAS WRONG
    Every failure on the money-document paths returned one sentence — "Unable
    to create purchase bill. Please try again." — with the real cause logged
    and then discarded. Driving a client through a full financial year hit it
    24 times consecutively on SQLSTATE 42501 (permission denied). The 24th
    attempt failed exactly like the first. A CA had no way to tell it apart
    from a network blip and nothing to hand support.

    "Please try again" is not neutral filler when the fault is a permission or
    a missing table. It is advice, and it is wrong.
"""
import pytest

from core.exceptions import document_failure_detail, postgres_message


class ApiError(Exception):
    """Shaped like supabase-py's APIError: a code and message on the instance
    AND in args[0], because it has kept them in both places across versions."""

    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__({"code": code, "message": message})


# ── The faults a retry cannot fix ────────────────────────────────────────────

@pytest.mark.parametrize("state,fragment", [
    ("42501", "not permitted to write"),
    ("42P01", "does not exist"),
    ("42703", "does not exist"),
])
def test_an_infrastructure_fault_does_not_invite_a_retry(state, fragment):
    out = document_failure_detail(ApiError(state, "permission denied for table x"),
                                  action="create the purchase bill")
    assert fragment in out
    assert "try again" not in out.lower(), (
        "a permission or missing-object fault is not transient; telling a CA to "
        "retry is advice that has never once worked")
    assert "report it" in out


def test_the_permission_case_is_the_one_the_walkthrough_hit():
    out = document_failure_detail(
        ApiError("42501", "permission denied for table purchase_bills"),
        action="create the purchase bill")
    assert out.startswith("Could not create the purchase bill.")
    assert "configuration fault" in out


# ── Business rules, whose messages are written for a human ───────────────────

def test_a_rule_the_database_enforces_is_surfaced_verbatim():
    """RAISE EXCEPTION in plpgsql lands as P0001, and those sentences are
    written FOR the CA — 'GSTR-3B covering this date was filed on 18 Jul 2026'.
    Replacing one with a generic message loses the only useful thing."""
    msg = "GSTR-3B covering this date was filed on 18 Jul 2026"
    out = document_failure_detail(ApiError("P0001", msg), action="receive the bill")
    assert msg in out
    assert "try again" not in out.lower()


def test_a_check_constraint_names_itself():
    """The walkthrough's payments died on
    purchase_payments_payment_mode_check. Naming the constraint is what lets a
    CA — or support — see that a field value was wrong rather than the server."""
    out = document_failure_detail(
        ApiError("23514", 'new row violates check constraint "purchase_payments_payment_mode_check"'),
        action="complete the payment")
    assert "purchase_payments_payment_mode_check" in out
    assert "not allowed" in out


@pytest.mark.parametrize("state", ["23503", "23505", "23502"])
def test_the_other_constraint_classes_carry_their_message(state):
    out = document_failure_detail(ApiError(state, "duplicate key value"), action="save")
    assert "duplicate key value" in out


# ── Anything else ────────────────────────────────────────────────────────────

def test_an_unclassified_failure_still_carries_what_is_known():
    out = document_failure_detail(RuntimeError("connection reset by peer"), action="save")
    assert "connection reset by peer" in out


def test_a_failure_with_nothing_to_say_falls_back_to_a_retry():
    """The one place 'try again' is honest: no code, no message, so it really
    might be transient."""
    class Bare(Exception):
        def __str__(self): return ""
    out = document_failure_detail(Bare(), action="save")
    assert "Please try again" in out


# ── It must never become a second failure ────────────────────────────────────

def test_an_exception_whose_attributes_raise_is_still_reported():
    """This runs while reporting a failure, on an object built by code that was
    already failing — the same rule core/observability._capture follows."""
    class Hostile(Exception):
        @property
        def code(self): raise ValueError("boom")
        @property
        def message(self): raise ValueError("boom")

    out = document_failure_detail(Hostile(), action="save")
    assert out and "Could not save" in out


def test_postgres_message_is_still_the_underlying_unwrapper():
    assert postgres_message(ApiError("P0001", "a sentence")) == "a sentence"
