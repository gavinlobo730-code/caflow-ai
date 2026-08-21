"""
A refusal written for a CA must arrive as a sentence, not as a dict repr.

WHAT WAS WRONG
    The journal edit and discard paths both surfaced an RPC failure with
    str(exc). For a supabase-py APIError that renders the WHOLE payload, and
    what a CA actually saw the first time a discard was refused was:

        API error 422: {"detail":{'code': 'P0001', 'details': None,
         'hint': None, 'message': 'This entry IS a reversal. Discarding it
         would leave the entry it reversed marked as reversed with nothing to
         show for it.'}}

    The sentence is in there, and it is the only part that matters — buried
    behind a SQLSTATE, inside a dict repr, with Python's None literals showing
    through. Every one of those messages was written to be read by a CA, and
    the wrapper is what stopped that happening.

    RAISE EXCEPTION in plpgsql always lands as P0001, so the code carries
    nothing the message does not.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.exceptions import postgres_message  # noqa: E402


class FakeAPIError(Exception):
    """supabase-py's APIError: str() renders the whole payload."""

    def __init__(self, payload: dict):
        super().__init__(payload)
        self.message = payload.get("message")
        self.code = payload.get("code")

    def __str__(self):
        return str(self.args[0])


REFUSAL = ("This entry IS a reversal. Discarding it would leave the entry it "
           "reversed marked as reversed with nothing to show for it.")


def test_the_sentence_arrives_on_its_own():
    exc = FakeAPIError({"code": "P0001", "details": None, "hint": None,
                        "message": REFUSAL})
    assert postgres_message(exc) == REFUSAL


def test_the_sqlstate_and_the_nulls_are_gone():
    exc = FakeAPIError({"code": "P0001", "details": None, "hint": None,
                        "message": REFUSAL})
    got = postgres_message(exc)
    for noise in ("P0001", "None", "hint", "details", "{", "}"):
        assert noise not in got, f"{noise!r} leaked into the CA-facing message: {got}"


def test_a_message_only_in_args_is_still_found():
    """supabase-py has moved where it puts this between versions."""
    class ArgsOnly(Exception):
        def __str__(self): return str(self.args[0])

    exc = ArgsOnly({"code": "P0001", "message": REFUSAL})
    assert postgres_message(exc) == REFUSAL


def test_an_error_with_no_message_still_says_something():
    """A wrapper beats an empty string — this runs while reporting a failure and
    must never make it worse."""
    assert postgres_message(RuntimeError("connection reset")) == "connection reset"


def test_a_blank_message_falls_back_rather_than_returning_nothing():
    exc = FakeAPIError({"code": "P0001", "message": "   "})
    assert postgres_message(exc).strip(), "an all-whitespace message must not win"


def test_it_never_raises_on_a_hostile_exception():
    class Hostile(Exception):
        @property
        def message(self): raise RuntimeError("nope")
        def __str__(self): return "fallback text"

    try:
        postgres_message(Hostile())
    except Exception as exc:  # pragma: no cover
        raise AssertionError(f"postgres_message raised while reporting: {exc}")
