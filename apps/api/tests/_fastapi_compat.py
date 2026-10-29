"""What a test reads off a FastAPI body parameter, the same on the version in the lock and on the next one.

`route.dependant.body_params` holds pydantic-compat `ModelField`s. Up to FastAPI 0.109 a field carried its annotation as `type_`;
0.141 keeps it on `field_info.annotation` and has no `type_`. Two test modules read the model a route takes as its body, so the
spelling lives here once (POST-A-171).
"""
from __future__ import annotations


def body_annotation(param):
    """The type a body parameter was annotated with (a model class for a JSON object), or None."""
    info = getattr(param, "field_info", None)
    annotation = getattr(info, "annotation", None)
    return annotation if annotation is not None else getattr(param, "type_", None)
