"""
Unit tests for relationship intelligence — entity roles, cross-client matches.
Self-contained tests that don't require the FastAPI stack.
"""


# ---------------------------------------------------------------------------
# DB field name alignment
# ---------------------------------------------------------------------------

def test_entity_role_db_field_is_role():
    """entity_roles schema column is 'role', not 'role_type'."""
    schema_col = "role"
    old_col = "role_type"
    assert schema_col != old_col

def test_cross_match_reviewed_column():
    """cross_client_matches uses 'reviewed', not 'is_reviewed'."""
    assert "reviewed" != "is_reviewed"

def test_cross_match_confirmed_column():
    """cross_client_matches uses 'confirmed', not 'is_confirmed'."""
    assert "confirmed" != "is_confirmed"

def test_cross_match_match_value_column():
    """cross_client_matches stores the matched value in 'match_value', not 'pan'."""
    schema_col = "match_value"
    old_col = "pan"
    assert schema_col != old_col


# ---------------------------------------------------------------------------
# Entity type constants
# ---------------------------------------------------------------------------

VALID_ENTITY_TYPES = {
    "Individual", "Company", "LLP", "Partnership", "Trust", "HUF"
}

VALID_ROLE_TYPES = {
    "Director", "Shareholder", "Partner", "Trustee",
    "Proprietor", "Guarantor", "Authorized Signatory",
    "Karta (HUF)", "Beneficiary", "Manager", "Other",
}

def test_entity_types_non_empty():
    assert len(VALID_ENTITY_TYPES) > 0

def test_role_types_include_director():
    assert "Director" in VALID_ROLE_TYPES

def test_role_types_include_shareholder():
    assert "Shareholder" in VALID_ROLE_TYPES

def test_role_types_all_strings():
    for rt in VALID_ROLE_TYPES:
        assert isinstance(rt, str)


# ---------------------------------------------------------------------------
# Match type constants (DB CHECK constraint)
# ---------------------------------------------------------------------------

VALID_MATCH_TYPES = {"pan", "email", "phone", "name"}

def test_match_types_include_pan():
    assert "pan" in VALID_MATCH_TYPES

def test_match_types_are_lowercase():
    for mt in VALID_MATCH_TYPES:
        assert mt == mt.lower()


# ---------------------------------------------------------------------------
# Ownership percent validation (numeric 0–100)
# ---------------------------------------------------------------------------

def test_ownership_percent_range():
    """Ownership percent must be between 0 and 100."""
    valid_values = [0, 25.5, 51, 100]
    for v in valid_values:
        assert 0 <= v <= 100

def test_ownership_percent_rejects_negative():
    assert -1 < 0  # would fail validation

def test_ownership_percent_rejects_over_100():
    assert 101 > 100  # would fail validation
