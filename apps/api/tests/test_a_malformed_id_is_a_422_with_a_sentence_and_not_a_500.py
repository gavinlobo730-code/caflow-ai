"""A malformed id in a path or a query answers 422 with a sentence, not 500 "Internal server error" (POST-A-296).

WHAT WAS WRONG
    `GET /api/clients/not-a-uuid`, and every route that filters on a `client_id` it was given as text
    (`/api/tds-workspace/deductions?client_id=not-a-uuid`, `/api/tds/deductor`, `/api/tds-workspace/deposit-state`), passes
    the text to Postgres, which refuses it as a bad `uuid` (SQLSTATE 22P02, invalid_text_representation), and the caller was
    told `Internal server error (reference ...)` with a traceback in the log. A mistyped link or a stale bookmark is the
    CALLER's mistake, and 500 told the browser it might work next time.

THE FIX IS AT THE ONE SPEAKER, NOT ON THE ROUTES
    The ledger line suggested a typed parameter applied by a rule over the route table (the `FYLabel` shape). That shape
    leaves the next route that goes in bare answering 500, and a route table holds ~1,000 operations whose id parameters are
    typed `str` for good reasons (legacy text ids, ids of other systems). `core.exceptions.unhandled_failure`, which
    `main.py` applies to every uncaught exception, now answers 22P02 as 422 with a sentence, so there is no route to forget.
    The sentence does not quote the text the caller sent.

WHAT IT DOES NOT DO
    It does not name the parameter (the speaker cannot know it) and it speaks only for 22P02: any other SQLSTATE keeps its
    answer, and an exception with no SQLSTATE is still an honest 500.
"""
import pytest
from fastapi.testclient import TestClient

import main
from core.exceptions import unhandled_failure


class ApiError(Exception):
    """Shaped like supabase-py's APIError: code and message on the instance AND in args[0]."""

    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__({"code": code, "message": message})


UUID_REFUSAL = 'invalid input syntax for type uuid: "not-a-uuid"'


def test_a_text_that_is_not_a_uuid_is_a_422_that_says_so():
    status, message = unhandled_failure(ApiError("22P02", UUID_REFUSAL))
    assert status == 422
    assert message == "That is not a valid id."


def test_the_sentence_does_not_repeat_what_the_caller_typed():
    """The database's message quotes the value, and the value is the caller's text."""
    for refusal in (UUID_REFUSAL, 'invalid input syntax for type uuid: "<script>alert(1)</script>"',
                    'invalid input syntax for type integer: "12abc"'):
        _, message = unhandled_failure(ApiError("22P02", refusal))
        assert "not-a-uuid" not in message and "<script>" not in message and "12abc" not in message, message


def test_another_type_the_database_could_not_read_is_a_422_with_its_own_sentence():
    status, message = unhandled_failure(ApiError("22P02", 'invalid input syntax for type integer: "12abc"'))
    assert status == 422
    assert message == "A value sent is not in the form that field takes."
    assert "id" not in message.split(), "an integer is not an id"


def test_a_refusal_with_no_message_still_gets_a_sentence():
    status, message = unhandled_failure(ApiError("22P02", ""))
    assert status == 422 and message.strip() and "{" not in message


@pytest.mark.parametrize("code,status", [("23514", 400), ("23505", 409), ("42501", 500), ("23503", 400)])
def test_every_other_state_keeps_the_answer_it_had(code, status):
    got, _ = unhandled_failure(ApiError(code, "boom"))
    assert got == status


def test_an_exception_with_no_state_is_still_an_internal_error():
    assert unhandled_failure(KeyError("client_id")) is None


# ── End to end, through the real middleware stack ────────────────────────────

@pytest.fixture(scope="module")
def client():
    @main.app.get("/__test__/refuses-a-bad-uuid")
    def _refuses_a_bad_uuid():
        raise ApiError("22P02", UUID_REFUSAL)

    return TestClient(main.app, raise_server_exceptions=False)


def test_the_caller_sees_a_422_in_the_house_envelope(client):
    res = client.get("/__test__/refuses-a-bad-uuid")
    assert res.status_code == 422
    body = res.json()
    assert set(body) == {"success", "data", "error"}
    assert body["success"] is False and body["data"] is None
    assert body["error"] == "That is not a valid id."
    assert "reference" not in body["error"], "a fault of the caller does not need a support reference"
    assert "not-a-uuid" not in res.text
