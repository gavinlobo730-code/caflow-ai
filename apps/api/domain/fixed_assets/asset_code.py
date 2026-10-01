"""A client's own asset tag — the one rule (FA-17, shared with accounting-18).

`FixedAssetIn` has refused a typed code in the generator's own shape since FA-17,
and the register-opening import (accounting-18) takes a code on EVERY row, because the
code is what lets uploading the same file twice recognise an asset it already
holds. Two doors asking one question need one answer, so the rule lives here and
`models.accounting.FixedAssetIn` delegates to it rather than the import carrying
a copy that agrees until somebody edits one of them.

WHY THE GENERATED SHAPE IS REFUSED
    `services/numbering.sequence_after` hands out the next `FA-{n:04d}` by taking
    the highest existing value that starts with `FA-` and whose tail is all
    digits, plus one. A CA typing their own `FA-0500` therefore does two things
    at once: it jumps the generated series to 0501, leaving 500 numbers that can
    never be issued, and a typed `FA-0001` collides head-on with the row the
    generator already gave that number to — a 23505 on migration 351's unique
    index, at the moment the asset is saved.

    Worse than either, `asset_code` is the identity every fixed-asset journal
    reference is built from (`FA-ACQ-{code}`, `FA-DEPN-{code}-{period}`) and the
    posting kernel dedupes on `(client_id, reference_no, entry_date)`. A
    collision there does not raise: the second asset's acquisition silently lands
    on the first asset's entry.

    Case-insensitive, because `fa-0500` reads as the same tag to a human and is a
    different row to a unique index.

Everything else is accepted, with only the two limits a journal reference
imposes: a bounded length and no whitespace or separator that would make
`FA-ACQ-{code}` ambiguous.
"""
from __future__ import annotations

import re
from typing import Optional

MAX_LENGTH = 32

_GENERATED_SHAPE = re.compile(r"FA-\d+", flags=re.IGNORECASE)
_ALLOWED = re.compile(r"[A-Za-z0-9][A-Za-z0-9/_.-]*")


def problem_with(code: str) -> Optional[str]:
    """What is wrong with a typed asset code, or None where it is usable.

    `code` is already stripped and non-blank — a blank box means "not stated",
    which is the CALLER's decision (the single form generates one; the import
    refuses the row because it has nothing to recognise a re-upload by).
    """
    if _GENERATED_SHAPE.fullmatch(code):
        return (
            f"'{code}' is the shape this register generates for itself "
            f"(FA-0001, FA-0002 …). Using it by hand skips numbers out of "
            f"that series or collides with a row that already has it. Leave "
            f"the box empty to take the next generated code, or use your "
            f"own tag in any other form.")
    if len(code) > MAX_LENGTH:
        return (
            "asset_code must be 32 characters or fewer — it is embedded in "
            "every acquisition and depreciation journal reference for this "
            "asset.")
    if not _ALLOWED.fullmatch(code):
        return (
            "asset_code may contain letters, digits, hyphen, slash, "
            "underscore and full stop only, and must start with a letter or "
            "a digit.")
    return None
