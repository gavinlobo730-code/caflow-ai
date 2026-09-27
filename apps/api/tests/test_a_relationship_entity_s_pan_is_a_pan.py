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
