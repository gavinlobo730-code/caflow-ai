"""
Reading the Income Tax Department's ITR JSON schemas.

The schemas live in `schemas/` and are the Department's own documents, committed
verbatim (see that directory's README). This module does two things and nothing
else: it loads one, and it resolves a dotted field path against it.

It exists so the field mapping in itr_json.py can be CHECKED rather than
believed. Every path in that mapping is verified by
tests/test_itr_schema_paths.py against the committed schema — the path must
exist, and it must be an integer field. A mapping that drifts from the schema
fails the suite instead of producing a file the portal rejects.

No network. The schema is a file in the repo; it is never fetched at runtime,
so what the mapping was written against and what the code reads are the same
bytes.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"

# Which committed file backs each form, for AY 2026-27. The file name carries
# the Department's own version suffix; changing a file means changing this line,
# which is the point — the pairing is explicit rather than a glob that would
# silently pick up a different revision.
SCHEMA_FILES: dict[str, str] = {
    "ITR-1": "ITR1_2026_Main_V1.1.json",
    "ITR-2": "ITR2_2026_Main_V1.2.json",
    "ITR-3": "ITR3_2026_Main_V1.1.json",
    "ITR-4": "ITR4_2026_Main_V1.1.json",
    "ITR-5": "ITR5_2026_Main_V1.1.json",
    "ITR-6": "ITR6_2026_Main_V1.0.json",
    "ITR-7": "ITR7_2026_Main_V0.1.json",
}


class SchemaUnavailable(RuntimeError):
    """The committed schema for a form is missing or unreadable."""


@lru_cache(maxsize=None)
def load_schema(form: str) -> dict:
    name = SCHEMA_FILES.get(form)
    if not name:
        raise SchemaUnavailable(f"No schema is recorded for {form}.")
    path = SCHEMA_DIR / name
    if not path.exists():
        raise SchemaUnavailable(f"{name} is missing from {SCHEMA_DIR}.")
    return json.loads(path.read_text(encoding="utf-8"))


def _definitions(schema: dict) -> dict:
    return schema.get("definitions") or {}


def resolve(form: str, dotted_path: str) -> Optional[dict]:
    """Walk a dotted path through a schema, following $refs, and return the leaf.

    Returns the leaf's schema node, or None when any step does not exist. The
    caller decides what a missing path means; this reports, it does not judge.

    The first segment is the root property ("ITR"); the rest are properties of
    whatever each step resolves to.
    """
    schema = load_schema(form)
    defs = _definitions(schema)
    node: Any = schema

    for segment in dotted_path.split("."):
        props = (node or {}).get("properties") or {}
        nxt = props.get(segment)
        if nxt is None:
            return None
        ref = nxt.get("$ref")
        node = defs.get(ref.split("/")[-1]) if ref else nxt
        if node is None:
            return None
    return node


def is_integer_field(form: str, dotted_path: str) -> bool:
    """True when the path exists AND names a monetary integer field.

    Every amount in these schemas is `"type": "integer"` in whole rupees — never
    paise, never a decimal. A path that resolves to an object is a container,
    not somewhere a figure can be written, and treating one as a leaf is the
    mistake that puts a value in the wrong place.
    """
    leaf = resolve(form, dotted_path)
    return bool(leaf) and leaf.get("type") == "integer"
