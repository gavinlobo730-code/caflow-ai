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
