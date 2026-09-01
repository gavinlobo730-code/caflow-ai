"""Domain exceptions for CAflow AI."""


class CAflowError(Exception):
    """Base exception."""


class NotFoundError(CAflowError):
    def __init__(self, entity: str, id: str):
        super().__init__(f"{entity} not found: {id}")
        self.entity = entity
        self.id = id


class PermissionDeniedError(CAflowError):
    def __init__(self, action: str, resource: str):
        super().__init__(f"Permission denied: cannot {action} {resource}")
        self.action = action
        self.resource = resource


class ValidationError(CAflowError):
    def __init__(self, field: str, message: str):
        super().__init__(f"Validation error on {field}: {message}")
        self.field = field


def postgres_message(exc: Exception) -> str:
    """The human sentence out of a supabase-py APIError, without the wrapper.

    WHAT WAS WRONG
        Both the journal edit path and the discard path surfaced an RPC failure
        with str(exc), which for an APIError renders the WHOLE payload:

            API error 422: {"detail":{'code': 'P0001', 'details': None,
             'hint': None, 'message': 'This entry IS a reversal. Discarding it
             would leave the entry it reversed marked as reversed with nothing
             to show for it.'}}

        The sentence is in there, written for a CA, and it is the only part
        that matters — buried in a dict repr, behind a SQLSTATE, with Python's
        None literals showing through. A message a CA has to excavate is a
        message that did not get read.

    RAISE EXCEPTION in a plpgsql function always lands as P0001, so the code
    carries no information the message does not. Anything without a message
    falls back to str(exc), because a wrapper is better than an empty string.
    """
    # Every read is guarded. This runs while reporting a failure, so it must
    # never become a second one — the same rule core/observability._capture
    # follows, and the same way it was got wrong first: an attribute that
    # raises, on an object built by code that was already failing.
    try:
        message = getattr(exc, "message", None)
        if isinstance(message, str) and message.strip():
            return message.strip()
    except Exception:
        pass

    # supabase-py has changed where it puts this between versions; the args
    # tuple is the other place it has lived.
    try:
        for arg in getattr(exc, "args", ()):
            if isinstance(arg, dict):
                nested = arg.get("message")
                if isinstance(nested, str) and nested.strip():
                    return nested.strip()
    except Exception:
        pass

    try:
        text = str(exc).strip()
    except Exception:
        text = ""
    return text or exc.__class__.__name__


# ── Why a document could not be written ──────────────────────────────────────

def _sqlstate(exc: Exception) -> str:
    """The five-character SQLSTATE, if the driver kept one. Every read guarded:
    this runs while reporting a failure and must never become a second one."""
    for source in (lambda: getattr(exc, "code", None),
                   lambda: (getattr(exc, "args", ()) or [{}])[0]):
        try:
            got = source()
            if isinstance(got, dict):
                got = got.get("code")
            if isinstance(got, str) and len(got.strip()) == 5:
                return got.strip()
        except Exception:
            pass
    return ""


# SQLSTATEs a retry cannot fix. Saying "please try again" to any of these is
# advice that has never once worked — the walkthrough's 24th purchase bill
# failed exactly like its first, on 42501.
_NOT_TRANSIENT = {
    "42501": ("The server is not permitted to write this table. That is a "
              "configuration fault on our side, not something retrying will "
              "fix — please report it."),
    "42P01": ("A table this operation needs does not exist. A migration has "
              "not reached this database; please report it."),
    "42703": ("A column this operation needs does not exist. A migration has "
              "not reached this database; please report it."),
}


def document_failure_detail(exc: Exception, *, action: str) -> str:
    """A sentence a CA can act on, for a document that would not save.

    WHAT THIS REPLACES
        "Unable to create purchase bill. Please try again." — returned for
        every failure, transient or not, with the real cause logged and then
        discarded. Driving a client through a full year hit it 24 times in a
        row on SQLSTATE 42501, and there was no way to tell it apart from a
        network blip and nothing to hand support.

    THE THREE CASES, because they need different words
      * A business rule the database enforces (RAISE EXCEPTION lands as P0001,
        and check/foreign-key violations) — the message is already written for
        a human, so it is surfaced. This is what routers/accounting.py already
        does for the journal paths.
      * An infrastructure fault (permission, missing table or column) — the CA
        can do nothing, so it says so plainly and asks them to report it
        rather than inviting a retry that cannot succeed.
      * Anything else — the underlying message, and a retry suggestion, which
        is only honest here because this branch really might be transient.
    """
    state = _sqlstate(exc)
    if state in _NOT_TRANSIENT:
        return f"Could not {action}. {_NOT_TRANSIENT[state]}"

    message = postgres_message(exc)
    # postgres_message falls back to the exception's CLASS NAME when there is no
    # message, which is right for a log line and useless to a CA — "Could not
    # save. APIError" reads as a glitch. Treat it as nothing to say.
    if message == exc.__class__.__name__:
        message = ""
    if state == "23514":                       # check constraint
        return (f"Could not {action}: one of the values sent is not allowed by "
                f"the database. {message}")
    if state in ("23503", "23505", "P0001", "23502"):
        return f"Could not {action}: {message}"
    return f"Could not {action}. {message}" if message else \
           f"Could not {action}. Please try again."
