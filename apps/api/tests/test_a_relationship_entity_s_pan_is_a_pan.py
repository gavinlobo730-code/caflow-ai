"""A relationship entity's PAN is validated at both doors (sweep-relationships-hub-05).

'Add Entity' stored a malformed PAN verbatim. The entity graph matches people
across clients on it, so a typo splits one director into two — and CLAUDE.md's
PAN rule (AAAAA9999A) applies platform-wide.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from routers.relationships import EntityIn, EntityUpdateIn


@pytest.mark.parametrize("model", [EntityIn, EntityUpdateIn])
def test_a_malformed_pan_is_refused(model):
    with pytest.raises(ValidationError) as exc:
        model(full_name="A", entity_type="Individual", pan="ABCD1234")
    assert "PAN format is invalid" in str(exc.value)


@pytest.mark.parametrize("model", [EntityIn, EntityUpdateIn])
def test_a_well_formed_pan_is_stored_upper_case_and_trimmed(model):
    assert model(full_name="A", entity_type="Individual", pan=" abcde1234f ").pan == "ABCDE1234F"


@pytest.mark.parametrize("model", [EntityIn, EntityUpdateIn])
@pytest.mark.parametrize("blank", [None, "", "   "])
def test_no_pan_is_allowed_and_stored_as_absent(model, blank):
    assert model(full_name="A", entity_type="Individual", pan=blank).pan is None


# ── GSTIN (relationships-hub-06) ───────────────────────────────────────────

_GOOD_GSTIN = "27AAPFU0939F1ZV"


@pytest.mark.parametrize("model", [EntityIn, EntityUpdateIn])
def test_a_gstin_is_kept_not_silently_dropped(model):
    assert model(full_name="A", entity_type="Company", gstin=_GOOD_GSTIN.lower()).gstin == _GOOD_GSTIN


@pytest.mark.parametrize("model", [EntityIn, EntityUpdateIn])
def test_a_malformed_gstin_is_refused_not_dropped(model):
    with pytest.raises(ValidationError):
        model(full_name="A", entity_type="Company", gstin="27ABCDE1234F1Z")


def test_a_duplicate_pan_is_answered_with_a_sentence():
    from core.exceptions import duplicate_document

    class _APIError(Exception):
        code = "23505"

    exc = _APIError('duplicate key value violates unique constraint "entities_pan_unique"')
    assert "already recorded in this firm" in (duplicate_document(exc) or "")
