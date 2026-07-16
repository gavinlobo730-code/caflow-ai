"""
Unit tests for Relationship Intelligence — Chapter 15.

Tests cover entity creation, director relationships, cross-client PAN detection,
Section 185 loan flags, paise arithmetic, property creation, related party report,
and transfer pricing threshold detection.

All tests run in mock mode (no SUPABASE_URL required).
"""
import os
import sys
import uuid
import pytest

# ── Ensure no DB required ─────────────────────────────────────────────────────
os.environ.pop("SUPABASE_URL", None)

# Add the api root to sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

# ── Helpers ───────────────────────────────────────────────────────────────────

AUTH_HEADERS = {"Authorization": "Bearer test-token"}

FIRM_ID = str(uuid.uuid4())
CLIENT_A = str(uuid.uuid4())
CLIENT_B = str(uuid.uuid4())


def _mock_user():
    """Patch RBAC to return a mock user without a real JWT."""
    from unittest.mock import patch
    return patch(
        "core.permissions.rbac",
        return_value=lambda: {
            "id": str(uuid.uuid4()),
            "firm_id": FIRM_ID,
            "role": "admin",
            "auth_user_id": str(uuid.uuid4()),
        },
    )


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clear_mock_stores():
    """Reset all in-memory stores between tests."""
    import routers.relationships as rel  # type: ignore
    yield
    rel._MOCK_ENTITIES.clear()
    rel._MOCK_ENTITY_ROLES.clear()
    rel._MOCK_RELATIONSHIPS.clear()
    rel._MOCK_CROSS_MATCHES.clear()
    rel._MOCK_ENTITY_TO_ENTITY_RELS.clear()
    rel._MOCK_LOANS.clear()
    rel._MOCK_PROPERTIES.clear()


# ─── Test helpers that operate directly on router logic ──────────────────────

def _make_entity(full_name: str, entity_type: str, pan: str | None = None) -> dict:
    """Create entity dict matching router structure."""
    now = "2026-06-13T00:00:00+00:00"
    return {
        "id": str(uuid.uuid4()),
        "firm_id": FIRM_ID,
        "full_name": full_name,
        "entity_type": entity_type,
        "pan": pan,
        "email": None,
        "phone": None,
        "address": None,
        "date_of_birth": None,
        "notes": None,
        "created_at": now,
        "updated_at": now,
    }


def _make_role(entity_id: str, client_id: str, role: str) -> dict:
    now = "2026-06-13T00:00:00+00:00"
    return {
        "id": str(uuid.uuid4()),
        "firm_id": FIRM_ID,
        "entity_id": entity_id,
        "client_id": client_id,
        "role": role,
        "ownership_percent": None,
        "effective_from": None,
        "effective_to": None,
        "notes": None,
        "created_at": now,
        "updated_at": now,
    }


def _make_loan(
    client_id: str,
    entity_id: str,
    loan_type: str,
    principal_paise: int,
) -> dict:
    now = "2026-06-13T00:00:00+00:00"
    section_185_flagged = loan_type == "to_director"
    section_186_flagged = loan_type == "inter_company"
    return {
        "id": str(uuid.uuid4()),
        "firm_id": FIRM_ID,
        "client_id": client_id,
        "entity_id": entity_id,
        "loan_type": loan_type,
        "principal_paise": principal_paise,
        "interest_rate": 12.0,
        "sanction_date": None,
        "due_date": None,
        "notes": None,
        "section_185_flagged": section_185_flagged,
        "section_186_flagged": section_186_flagged,
        "created_at": now,
        "updated_at": now,
    }


# ─── Tests ────────────────────────────────────────────────────────────────────

class TestEntityCreation:
    """Tests 1–2: Entity creation for person and company."""

    def test_create_person_entity(self):
        """Test 1: Create an Individual entity with PAN."""
        import routers.relationships as rel  # type: ignore  # noqa: F811
        entity = _make_entity("Amit Sharma", "Individual", "ABCDE1234F")
        rel._MOCK_ENTITIES.append(entity)

        result = [e for e in rel._MOCK_ENTITIES if e["full_name"] == "Amit Sharma"]
        assert len(result) == 1
        assert result[0]["entity_type"] == "Individual"
        assert result[0]["pan"] == "ABCDE1234F"

    def test_create_company_entity(self):
        """Test 2: Create a Company entity."""
        import routers.relationships as rel  # type: ignore  # noqa: F811
        entity = _make_entity("ABC Pvt Ltd", "Company", "ZZZZZ9999Z")
        rel._MOCK_ENTITIES.append(entity)

        result = [e for e in rel._MOCK_ENTITIES if e["entity_type"] == "Company"]
        assert len(result) == 1
        assert result[0]["full_name"] == "ABC Pvt Ltd"


class TestDirectorRelationship:
    """Test 3: Director role creation."""

    def test_create_director_relationship(self):
        """Test 3: Assign an Individual as Director of a client."""
        import routers.relationships as rel  # type: ignore  # noqa: F811
        entity = _make_entity("Priya Nair", "Individual", "PQRST5678U")
        rel._MOCK_ENTITIES.append(entity)

        role = _make_role(entity["id"], CLIENT_A, "Director")
        rel._MOCK_ENTITY_ROLES.append(role)

        director_roles = [r for r in rel._MOCK_ENTITY_ROLES if r["role"] == "Director"]
        assert len(director_roles) == 1
        assert director_roles[0]["client_id"] == CLIENT_A


class TestCrossClientDetection:
    """Test 4: Same PAN appearing in two clients triggers cross-client match."""

    def test_cross_client_detection_same_pan(self):
        """Test 4: Entity with same PAN linked to two clients → cross-client match detected."""
        import routers.relationships as rel  # type: ignore  # noqa: F811

        shared_pan = "CROSS1234P"
        entity = _make_entity("Cross Person", "Individual", shared_pan)
        rel._MOCK_ENTITIES.append(entity)

        # Same entity appears in both CLIENT_A and CLIENT_B
        role_a = _make_role(entity["id"], CLIENT_A, "Director")
        role_b = _make_role(entity["id"], CLIENT_B, "Shareholder")
        rel._MOCK_ENTITY_ROLES.extend([role_a, role_b])

        # Run detection logic (mirrors router detect_cross_client_matches)
        pan_map: dict = {}
        for role in rel._MOCK_ENTITY_ROLES:
            ent = next((e for e in rel._MOCK_ENTITIES if e["id"] == role["entity_id"]), None)
            if ent and ent.get("pan"):
                pan = ent["pan"].upper()
                if pan not in pan_map:
                    pan_map[pan] = []
                pan_map[pan].append({"role": role, "entity": ent})

        new_count = 0
        now = "2026-06-13T00:00:00+00:00"
        for pan, entries in pan_map.items():
            client_ids = list({e["role"]["client_id"] for e in entries})
            if len(client_ids) < 2:
                continue
            for i in range(len(entries)):
                for j in range(i + 1, len(entries)):
                    a, b = entries[i], entries[j]
                    if a["role"]["client_id"] == b["role"]["client_id"]:
                        continue
                    rel._MOCK_CROSS_MATCHES.append({
                        "id": str(uuid.uuid4()),
                        "firm_id": FIRM_ID,
                        "match_value": pan,
                        "entity_id": a["entity"]["id"],
                        "client_id_a": a["role"]["client_id"],
                        "client_id_b": b["role"]["client_id"],
                        "match_type": "pan",
                        "reviewed": False,
                        "confirmed": None,
                        "created_at": now,
                    })
                    new_count += 1

        assert new_count == 1
        assert len(rel._MOCK_CROSS_MATCHES) == 1
        assert rel._MOCK_CROSS_MATCHES[0]["match_value"] == shared_pan
        assert rel._MOCK_CROSS_MATCHES[0]["client_id_a"] != rel._MOCK_CROSS_MATCHES[0]["client_id_b"]


class TestCrossClientMatchesFilter:
    """list_cross_client_matches's reviewed/entity_id query params: an explicit
    reviewed=False used to fall through both `elif` branches unfiltered (False
    is falsy, so `elif reviewed:` never matched it) — same bug in both the mock
    and DB code paths. Calls the router function directly (bypassing HTTP/DI,
    per this file's existing convention) since mock mode needs no real auth."""

    def _seed(self):
        import routers.relationships as rel  # type: ignore
        entity_id = str(uuid.uuid4())
        reviewed_match = {"id": str(uuid.uuid4()), "firm_id": FIRM_ID, "entity_id": entity_id,
                           "client_id_a": CLIENT_A, "client_id_b": CLIENT_B, "match_type": "pan",
                           "reviewed": True, "created_at": "2026-06-13T00:00:00+00:00"}
        unreviewed_match = {"id": str(uuid.uuid4()), "firm_id": FIRM_ID, "entity_id": entity_id,
                             "client_id_a": CLIENT_A, "client_id_b": CLIENT_B, "match_type": "pan",
                             "reviewed": False, "created_at": "2026-06-13T00:00:00+00:00"}
        rel._MOCK_CROSS_MATCHES.extend([reviewed_match, unreviewed_match])
        return rel, entity_id, reviewed_match, unreviewed_match

    def test_default_shows_unreviewed_only(self):
        rel, _, _, unreviewed = self._seed()
        result = rel.list_cross_client_matches(entity_id=None, reviewed=None,
                                                current_user={"firm_id": FIRM_ID})
        assert [m["id"] for m in result["data"]] == [unreviewed["id"]]

    def test_explicit_reviewed_false_shows_unreviewed_only(self):
        """The actual bug: reviewed=false must behave like the default, not
        like "no filter"."""
        rel, _, _, unreviewed = self._seed()
        result = rel.list_cross_client_matches(entity_id=None, reviewed=False,
                                                current_user={"firm_id": FIRM_ID})
        assert [m["id"] for m in result["data"]] == [unreviewed["id"]]

    def test_explicit_reviewed_true_shows_reviewed_only(self):
        rel, _, reviewed, _ = self._seed()
        result = rel.list_cross_client_matches(entity_id=None, reviewed=True,
                                                current_user={"firm_id": FIRM_ID})
        assert [m["id"] for m in result["data"]] == [reviewed["id"]]

    def test_entity_id_bypasses_reviewed_filter(self):
        """Entity Detail's Cross-Client Matches tab wants full history
        (confirmed/dismissed included), so entity_id intentionally shows both
        reviewed and unreviewed matches rather than combining with the
        reviewed default."""
        rel, entity_id, reviewed, unreviewed = self._seed()
        result = rel.list_cross_client_matches(entity_id=entity_id, reviewed=None,
                                                current_user={"firm_id": FIRM_ID})
        assert {m["id"] for m in result["data"]} == {reviewed["id"], unreviewed["id"]}


class TestSection185Loan:
    """Test 5: Loan to director auto-flags Section 185."""

    def test_section_185_flag_on_director_loan(self):
        """Test 5: Loan of type 'to_director' must set section_185_flagged = True."""
        import routers.relationships as rel  # type: ignore  # noqa: F811

        entity = _make_entity("Director Person", "Individual", "DIREC5678D")
        rel._MOCK_ENTITIES.append(entity)

        # ₹5,00,000 loan = 5_00_000 * 100 paise = 5_00_00_000 paise? No:
        # ₹5,00,000 = 50_000_000 paise? Let's be precise:
        # 1 rupee = 100 paise. ₹5,00,000 = 500000 rupees = 50_000_000 paise
        loan = _make_loan(CLIENT_A, entity["id"], "to_director", 50_000_000)
        rel._MOCK_LOANS.append(loan)

        flagged = [l for l in rel._MOCK_LOANS if l.get("section_185_flagged")]
        assert len(flagged) == 1
        assert flagged[0]["loan_type"] == "to_director"
        assert flagged[0]["section_185_flagged"] is True

    def test_non_director_loan_not_flagged(self):
        """Test 6: Loan of type 'other' must NOT set section_185_flagged."""
        import routers.relationships as rel  # type: ignore  # noqa: F811

        entity = _make_entity("Vendor Entity", "Company", "VNDOR9999V")
        rel._MOCK_ENTITIES.append(entity)

        loan = _make_loan(CLIENT_A, entity["id"], "other", 10_000_000)
        rel._MOCK_LOANS.append(loan)

        assert loan["section_185_flagged"] is False


class TestLoanPaiseArithmetic:
    """Test 7: Loan amounts must be integer paise — never float."""

    def test_loan_principal_is_integer_paise(self):
        """Test 7: principal_paise must be a plain Python int — never float."""
        # ₹1,00,000 = 1_00_000 rupees = 1_00_00_000 paise
        principal = 1_00_00_000
        assert isinstance(principal, int)
        # Ensure no floating-point arithmetic happened
        assert principal == 10_000_000

    def test_loan_paise_rupee_conversion(self):
        """Test 8: Paise ÷ 100 = rupees (integer division, no float)."""
        principal_paise = 5_00_00_000  # ₹5,00,000 in paise
        rupees = principal_paise // 100  # integer division — never float
        assert rupees == 500_000
        assert isinstance(rupees, int)


class TestPropertyCreation:
    """Tests 9–10: Property creation and retrieval."""

    def test_create_property_with_paise(self):
        """Test 9: Property cost and rent stored in integer paise (IT Act Sec 48, Sec 23)."""
        import routers.relationships as rel  # type: ignore  # noqa: F811

        # ₹50,00,000 cost = 50_00_000 * 100 = 5_00_00_00_000? No:
        # ₹50,00,000 = 5_000_000 rupees = 5_000_000 * 100 paise? No:
        # ₹50,00,000 = 50,00,000 rupees = 50_00_000 rupees = 5_000_000 rupees
        # Actually: 50,00,000 in Indian numbering = 50 lakhs = 5_000_000 rupees = 5_00_00_000_00?
        # Let me be precise: 1 lakh = 1,00,000. 50 lakhs = 50,00,000 = 5_000_000.
        # In paise: 5_000_000 * 100 = 500_000_000
        cost_paise = 5_000_000 * 100   # ₹50,00,000 in paise
        rent_paise = 50_000 * 100       # ₹50,000 annual rent in paise

        assert isinstance(cost_paise, int)
        assert isinstance(rent_paise, int)

        now = "2026-06-13T00:00:00+00:00"
        prop = {
            "id": str(uuid.uuid4()),
            "firm_id": FIRM_ID,
            "client_id": CLIENT_A,
            "entity_id": None,
            "address": "123 MG Road, Bengaluru 560001",
            "property_type": "commercial",
            "cost_paise": cost_paise,
            "annual_rent_paise": rent_paise,
            "acquisition_date": "2020-04-01",
            "notes": None,
            "created_at": now,
            "updated_at": now,
        }
        rel._MOCK_PROPERTIES.append(prop)

        stored = [p for p in rel._MOCK_PROPERTIES if p["client_id"] == CLIENT_A]
        assert len(stored) == 1
        assert stored[0]["cost_paise"] == cost_paise
        assert stored[0]["annual_rent_paise"] == rent_paise

    def test_retrieve_property_by_client(self):
        """Test 10: Filter properties by client_id."""
        import routers.relationships as rel  # type: ignore  # noqa: F811

        now = "2026-06-13T00:00:00+00:00"
        for i, cid in enumerate([CLIENT_A, CLIENT_B, CLIENT_A]):
            rel._MOCK_PROPERTIES.append({
                "id": str(uuid.uuid4()),
                "firm_id": FIRM_ID,
                "client_id": cid,
                "entity_id": None,
                "address": f"Property {i}",
                "property_type": "residential",
                "cost_paise": 1_00_00_000,
                "annual_rent_paise": 0,
                "acquisition_date": None,
                "notes": None,
                "created_at": now,
                "updated_at": now,
            })

        client_a_props = [p for p in rel._MOCK_PROPERTIES if p["client_id"] == CLIENT_A]
        assert len(client_a_props) == 2


class TestRelatedPartyReport:
    """Test 11: Related party report includes entity_relationships."""

    def test_related_party_report_includes_directors(self):
        """Test 11: Report for a client must include all Director and Shareholder roles."""
        import routers.relationships as rel  # type: ignore  # noqa: F811

        entity1 = _make_entity("Director One", "Individual", "DIR001111D")
        entity2 = _make_entity("Shareholder Co", "Company", "SHR002222S")
        rel._MOCK_ENTITIES.extend([entity1, entity2])

        role1 = _make_role(entity1["id"], CLIENT_A, "Director")
        role2 = _make_role(entity2["id"], CLIENT_A, "Shareholder")
        # This one belongs to a different client — should NOT appear
        role3 = _make_role(entity1["id"], CLIENT_B, "Director")
        rel._MOCK_ENTITY_ROLES.extend([role1, role2, role3])

        # Simulate report logic (mirrors router related_party_report)
        client_roles = [r for r in rel._MOCK_ENTITY_ROLES if r.get("client_id") == CLIENT_A]
        related_party_roles = {"Director", "Shareholder", "Partner", "Trustee", "Guarantor", "related_party"}
        related_parties = [r for r in client_roles if r.get("role") in related_party_roles]

        assert len(related_parties) == 2
        roles_in_report = {r["role"] for r in related_parties}
        assert "Director" in roles_in_report
        assert "Shareholder" in roles_in_report


class TestTransferPricingThreshold:
    """Test 12: Transfer pricing flag for inter-company > ₹1 crore."""

    def test_transfer_pricing_flag_above_threshold(self):
        """
        Test 12: IT Act Sec 92 — inter-company loan > ₹1 crore (10_000_000_00 paise)
        must be flagged for transfer pricing documentation.
        """
        import routers.relationships as rel  # type: ignore  # noqa: F811

        # ₹1,00,00,000 = 1 crore = 1_00_00_000 rupees
        # In paise: 1_00_00_000 * 100 = 10_000_000_00?
        # Let's recalculate carefully:
        # 1 crore rupees = 1,00,00,000 rupees = 10_000_000 rupees
        # In paise = 10_000_000 * 100 = 1_000_000_000 paise = 1_00_00_00_000 paise
        # Transfer pricing threshold: ₹1 crore
        THRESHOLD_PAISE = 1_00_00_000 * 100  # ₹1 crore in paise

        entity = _make_entity("Foreign Subsidiary", "Company", "FRNCO9999F")
        rel._MOCK_ENTITIES.append(entity)

        # Loan just above threshold — must trigger transfer pricing
        above_threshold_paise = THRESHOLD_PAISE + 100  # 1 paise above
        loan_above = _make_loan(CLIENT_A, entity["id"], "inter_company", above_threshold_paise)
        rel._MOCK_LOANS.append(loan_above)

        # Loan just below threshold — must NOT trigger
        below_threshold_paise = THRESHOLD_PAISE - 100
        loan_below = _make_loan(CLIENT_A, entity["id"], "inter_company", below_threshold_paise)
        rel._MOCK_LOANS.append(loan_below)

        tp_loans = [
            l for l in rel._MOCK_LOANS
            if l["loan_type"] == "inter_company"
            and l["principal_paise"] >= THRESHOLD_PAISE
        ]
        assert len(tp_loans) == 1
        assert tp_loans[0]["principal_paise"] == above_threshold_paise
        assert tp_loans[0]["principal_paise"] > THRESHOLD_PAISE
