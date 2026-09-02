"""
A database refusal that no router caught must still reach the CA as a sentence.

WHAT WAS WRONG
    core.exceptions.document_failure_detail turns a refused write into words a
    CA can act on, and exactly FIVE routers call it — accounting, receipts,
    tds, purchase_bills, purchase_payments. Every other router's database
    failure fell through to main.py's two catch-alls, which answered

        500  {"success": false, "data": null, "error": "Internal server error"}

    for everything, and wrote the real cause to a log the CA cannot read.

    Walking a client with foreign suppliers through a year hit it on an
    engagement: a CHECK constraint refused the row because a value was not in
    its allowed set, and the CA was told the server had a problem. Nothing
    about a refused CHECK is internal, and 500 tells the browser this might
    work next time about a request that never can.

WHAT THE FIX IS NOT
    It is not "surface everything". The catch-alls see every exception in the
    process — a KeyError, a timeout, a bug — and those really are internal.
    core.exceptions.unhandled_failure speaks only where the exception carries
    a SQLSTATE it recognises and returns None otherwise, which is why these
    tests check the silence as carefully as the speech.
"""
import pytest
from fastapi.testclient import TestClient

import main
from core.exceptions import unhandled_failure


class ApiError(Exception):
    """Shaped like supabase-py's APIError: code and message on the instance AND
    in args[0], because it has kept them in both places across versions."""

    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__({"code": code, "message": message})


# ── What the classifier says, and what it refuses to say ─────────────────────

def test_a_check_violation_is_the_callers_fault_not_the_servers():
    """The engagement case. A value outside a CHECK's allowed set is a bad
    request, and the message names which constraint refused it."""
    status, message = unhandled_failure(
        ApiError("23514", 'new row for relation "engagements" violates check '
                          'constraint "engagements_status_check"'))
    assert status == 400, "a refused CHECK is not a server error"
    assert "engagements_status_check" in message
    assert "Internal server error" not in message


def test_a_database_rule_reaches_the_ca_in_its_own_words():
    """RAISE EXCEPTION in plpgsql lands as P0001, and those sentences are
    written FOR the CA. Wrapping one in a category label loses the only
    useful thing in it."""
    rule = "GSTR-3B covering this date was filed on 18 Jul 2026."
    status, message = unhandled_failure(ApiError("P0001", rule))
    assert status == 400
    assert message == rule


def test_a_duplicate_is_409_not_500():
    status, message = unhandled_failure(
        ApiError("23505", 'duplicate key value violates unique constraint '
                          '"uq_purchase_bills_vendor_invoice"'))
    assert status == 409, "a duplicate is a conflict, not a server fault"
    assert "already exists" in message


@pytest.mark.parametrize("state", ["23503", "23502"])
def test_a_missing_reference_or_a_missing_required_value_is_400(state):
    status, _ = unhandled_failure(ApiError(state, "boom"))
    assert status == 400


@pytest.mark.parametrize("state", ["42501", "42P01", "42703"])
def test_an_infrastructure_fault_stays_500_but_says_which_kind(state):
    """A permission or a missing table IS our fault, so the status is right —
    but "Internal server error" invites a retry, and the walkthrough's 24th
    purchase bill failed exactly like its first on 42501."""
    status, message = unhandled_failure(ApiError(state, "permission denied"))
    assert status == 500
    assert "report it" in message
    assert "try again" not in message.lower()


# ── The silence, which matters as much ───────────────────────────────────────

@pytest.mark.parametrize("exc", [
    KeyError("client_id"),
    ValueError("bad"),
    TimeoutError(),
    RuntimeError("something broke in our own code"),
])
def test_an_ordinary_bug_is_not_dressed_up_as_a_database_refusal(exc):
    """These have no SQLSTATE. "Internal server error" is the honest answer
    for them, and surfacing str(exc) would leak our internals for nothing."""
    assert unhandled_failure(exc) is None


def test_an_unrecognised_sqlstate_says_nothing():
    """40001 is a serialisation failure — genuinely transient, genuinely a
    500. Speaking only about states we have thought about is how this stays
    honest as new ones appear."""
    assert unhandled_failure(ApiError("40001", "could not serialize access")) is None


def test_classifying_never_becomes_a_second_failure():
    """This runs while reporting a failure. An exception whose own attributes
    raise is exactly the shape that has broken error reporting before."""
    class Hostile(Exception):
        @property
        def code(self):
            raise RuntimeError("nope")

        @property
        def message(self):
            raise RuntimeError("nope")

    assert unhandled_failure(Hostile()) is None


def test_a_sqlstate_with_no_message_still_produces_a_sentence():
    """postgres_message falls back to the class name and then to str(exc).
    Both are right for a log line and neither is a sentence: an APIError with
    an empty message renders as {'code': '23514', 'message': ''}, and pasting
    that after "One of the values sent is not allowed" hands a CA a dict repr
    with Python's quoting showing through. Where there is nothing to say, the
    category sentence has to stand on its own."""
    _, message = unhandled_failure(ApiError("23514", ""))
    assert message.strip()
    assert "ApiError" not in message
    assert "{" not in message and "'code'" not in message, (
        f"a dict repr reached the CA: {message}")


def test_a_rule_with_nothing_to_say_still_says_something():
    """P0001's shape is the message alone, so an empty one leaves nothing at
    all — and a blank error field renders as no error."""
    status, message = unhandled_failure(ApiError("P0001", ""))
    assert status == 400
    assert message.strip() and "{" not in message


# ── End to end, through the real middleware stack ────────────────────────────

@pytest.fixture(scope="module")
def client():
    """Routes added here are unique paths on the real app, so they exercise the
    real middleware ordering — which is the point: _errors_with_cors is the
    INNERMOST user middleware and is what actually catches a route's exception.

    raise_server_exceptions=False makes TestClient behave like a real server
    and return the handler's response instead of re-raising."""
    @main.app.get("/__test__/refuses-check")
    def _refuses_check():
        raise ApiError("23514", 'violates check constraint "engagements_status_check"')

    @main.app.get("/__test__/breaks")
    def _breaks():
        raise KeyError("client_id")

    return TestClient(main.app, raise_server_exceptions=False)


def test_the_ca_sees_the_constraint_and_a_400(client):
    res = client.get("/__test__/refuses-check")
    assert res.status_code == 400
    body = res.json()
    assert body["success"] is False and body["data"] is None
    assert "engagements_status_check" in body["error"]


def test_a_real_internal_error_is_still_called_one(client):
    res = client.get("/__test__/breaks")
    assert res.status_code == 500
    assert res.json()["error"] == "Internal server error"


def test_the_response_still_follows_the_api_response_shape(client):
    for path in ("/__test__/refuses-check", "/__test__/breaks"):
        assert set(client.get(path).json()) == {"success", "data", "error"}


# ── The two catch-alls must not drift apart ──────────────────────────────────

def test_both_catch_alls_answer_through_the_same_function():
    """main.py has two: the _errors_with_cors middleware, which catches a
    route's exception, and the @app.exception_handler(Exception) backstop for
    anything raised outside it. Two copies of this classification would drift,
    and the one that drifted would be the one nobody was looking at."""
    src = open("main.py").read()
    assert src.count("return _failure_response(request, exc)") == 2
    assert src.count('"error": "Internal server error"') == 0, (
        "the literal now lives in _failure_response's fallback only")
