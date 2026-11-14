"""Every request-model field the date-field guard counts as typed refuses, when it is BUILT, what is not a day (POST-A-380).

WHY THIS AND NOT ONLY THE GUARD
    `test_a_date_field_on_a_request_model_is_a_real_date_or_is_on_the_frozen_list.py` reads ANNOTATIONS: a field spelled `IsoDate`, `OptionalIsoDate` or
    `PatchIsoDate` counts as judged. A spelling can be right while the field is not (a `Field(...)` that replaces the annotation's metadata, a class that
    redefines the field in a subclass, a module that shadows the name). This builds each such field as Pydantic will and asks it.

    What a date that is not a day did before the type, measured on the production database on 14-11-2026: its `DateStyle` is `ISO, MDY`, so
    `'01/02/2026'::date` is 2 JANUARY. A caller that wrote an Indian slash date to one of these fields had the wrong day stored with no error, which is
    why the slash date is the first thing each field is asked.

WHAT EACH KIND MUST DO WITH A BLANK
    `IsoDate` refuses it (the date must be there); `OptionalIsoDate` reads it as no date (a new record, or an edit whose null clears the stored value);
    `PatchIsoDate` refuses it (the route drops a null as "nothing to change", so a blank read as absent would report a success for a date not cleared).
"""
from __future__ import annotations

import ast
import importlib

import pytest
from pydantic import ValidationError, create_model

from tests.test_a_date_field_on_a_request_model_is_a_real_date_or_is_on_the_frozen_list import API, scan

NOT_A_DAY = ("01/02/2026", "14/11/2026", "2026-02-30", "soon", "2026-11-14T10:00:00", 20261114)


def _kinds() -> dict[str, str]:
    """`file::Class.field` -> the date type its annotation names, for every typed field the guard sees."""
    _, typed = scan()
    out: dict[str, str] = {}
    for entry in typed:
        rel, rest = entry.split("::")
        cls_name, field = rest.split(".")
        tree = ast.parse((API / rel).read_text(encoding="utf-8"))
        for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == cls_name):
            for stmt in cls.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and stmt.target.id == field:
                    out[entry] = ast.unparse(stmt.annotation).replace('"', "").replace("'", "")
    return out


def _probe(entry: str):
    """A model holding only this field, built from the field's own FieldInfo, so a default, an alias or a `Field()` on it is what is asked."""
    rel, rest = entry.split("::")
    cls_name, field = rest.split(".")
    module = importlib.import_module(rel[:-3].replace("/", "."))
    cls = getattr(module, cls_name, None)
    if cls is None or field not in getattr(cls, "model_fields", {}):
        return None
    info = cls.model_fields[field]
    return create_model(f"Probe_{cls_name}_{field}", **{field: (info.rebuild_annotation(), info)}), field


ENTRIES = sorted(_kinds().items())


def test_the_probe_reaches_the_fields_it_is_for():
    built = [e for e, _ in ENTRIES if _probe(e) is not None]
    # A class defined inside a function is in the scan and not on its module, so it cannot be built here; the floor is on what is built.
    assert len(built) >= 130, f"only {len(built)} typed date fields could be built"
    assert {k for _, k in ENTRIES} == {"IsoDate", "OptionalIsoDate", "PatchIsoDate"}


@pytest.mark.parametrize("entry,kind", ENTRIES, ids=[e for e, _ in ENTRIES])
def test_a_typed_date_field_refuses_what_is_not_a_day(entry, kind):
    probe = _probe(entry)
    if probe is None:
        pytest.skip(f"{entry} is not a module-level model")
    model, field = probe
    assert getattr(model(**{field: "2026-11-14"}), field) == "2026-11-14"
    for value in NOT_A_DAY:
        with pytest.raises(ValidationError) as caught:
            model(**{field: value})
        # The SENTENCE names the field, not only Pydantic's location line (which always would): a validator that raised "bad" fails here.
        assert f"{field} must be a date written YYYY-MM-DD" in str(caught.value), f"{entry}: the refusal of {value!r} is not the sentence"
    if kind == "OptionalIsoDate":
        assert getattr(model(**{field: ""}), field) is None, f"{entry}: a blank on an optional date is no date"
        assert getattr(model(**{field: None}), field) is None
    else:
        with pytest.raises(ValidationError):
            model(**{field: ""})
        if kind == "PatchIsoDate":
            assert getattr(model(**{field: None}), field) is None, f"{entry}: an edit that does not send the date keeps it"


def test_a_correction_cannot_clear_an_assets_purchase_date():
    """The fixed-asset correction is read with exclude_unset, so an explicit null is a CHANGE there and would repost the acquisition with no date."""
    from models.accounting import FixedAssetUpdateIn
    assert "purchase_date" not in FixedAssetUpdateIn(reason="x").model_dump(exclude_unset=True)
    for value in (None, ""):
        with pytest.raises(ValidationError) as caught:
            FixedAssetUpdateIn(purchase_date=value, reason="x")
        assert "purchase_date" in str(caught.value) and "cannot be cleared" in str(caught.value)
