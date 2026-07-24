"""
Task #244 — medium cross-tenant/confidentiality gaps: relationships.py's
mock-store branches never scoped by firm_id, task_recurring's caller-supplied
client_id/template_id inserted unchecked (then leaked back out through
list_recurring's unscoped enrichment lookups), and task_templates.py's
get/update/delete/instantiate never verified template ownership at all.

Every finding here shares the same root cause as tasks #230/#231/#234/#235:
a caller-supplied id (client_id/entity_id/template_id/role_id/match_id) used
in a read or write path without checking it belongs to the caller's own firm.
"""
import os

import pytest
from fastapi import HTTPException

import core.authz as authz

os.environ.pop("SUPABASE_URL", None)  # keep relationships.py on its mock-store path

FIRM_A, FIRM_B = "firm-A", "firm-B"
USER_A = {"id": "u1", "firm_id": FIRM_A, "role": "Partner", "auth_user_id": "auth-1", "email": "a@a.test"}
USER_B = {"id": "u2", "firm_id": FIRM_B, "role": "Partner", "auth_user_id": "auth-2", "email": "b@b.test"}


# ─────────────────────────────────────────────────────────────────────────────
# Area 1 — relationships.py mock-store branches
# ─────────────────────────────────────────────────────────────────────────────

import routers.relationships as rel


@pytest.fixture(autouse=True)
def _clear_relationships_mock_stores():
    yield
    rel._MOCK_ENTITIES.clear()
    rel._MOCK_ENTITY_ROLES.clear()
    rel._MOCK_RELATIONSHIPS.clear()
    rel._MOCK_CROSS_MATCHES.clear()
    rel._MOCK_ENTITY_TO_ENTITY_RELS.clear()
    rel._MOCK_LOANS.clear()
    rel._MOCK_PROPERTIES.clear()


def test_list_entities_excludes_another_firms_entities():
    rel._MOCK_ENTITIES.append({"id": "e-a", "firm_id": FIRM_A, "full_name": "Firm A Entity", "entity_type": "Individual", "pan": None, "email": None})
    rel._MOCK_ENTITIES.append({"id": "e-b", "firm_id": FIRM_B, "full_name": "Firm B Entity", "entity_type": "Individual", "pan": None, "email": None})

    resp = rel.list_entities(entity_type=None, search=None, limit=50, offset=0, current_user=USER_A)
    names = [e["full_name"] for e in resp["data"]]
    assert names == ["Firm A Entity"]


def test_get_entity_404s_on_another_firms_entity():
    rel._MOCK_ENTITIES.append({"id": "e-b", "firm_id": FIRM_B, "full_name": "Firm B Entity", "notes": "confidential"})

    with pytest.raises(HTTPException) as ei:
        rel.get_entity("e-b", current_user=USER_A)
    assert ei.value.status_code == 404


def test_get_entity_scopes_roles_and_relationships_to_the_caller_firm():
    rel._MOCK_ENTITIES.append({"id": "e-a", "firm_id": FIRM_A, "full_name": "Firm A Entity", "notes": None})
    rel._MOCK_ENTITY_ROLES.append({"id": "r-a", "firm_id": FIRM_A, "entity_id": "e-a", "role": "Director"})
    rel._MOCK_ENTITY_ROLES.append({"id": "r-b", "firm_id": FIRM_B, "entity_id": "e-a", "role": "Director"})

    resp = rel.get_entity("e-a", current_user=USER_A)
    assert [r["id"] for r in resp["data"]["roles"]] == ["r-a"]


def test_update_entity_404s_on_another_firms_entity():
    rel._MOCK_ENTITIES.append({"id": "e-b", "firm_id": FIRM_B, "full_name": "Firm B Entity"})

    with pytest.raises(HTTPException) as ei:
        rel.update_entity("e-b", rel.EntityUpdateIn(full_name="Hijacked"), current_user=USER_A)
    assert ei.value.status_code == 404
    assert rel._MOCK_ENTITIES[0]["full_name"] == "Firm B Entity"  # unchanged


def test_remove_entity_role_404s_on_another_firms_role():
    rel._MOCK_ENTITY_ROLES.append({"id": "role-b", "firm_id": FIRM_B, "entity_id": "e-b"})

    with pytest.raises(HTTPException) as ei:
        rel.remove_entity_role("role-b", current_user=USER_A)
    assert ei.value.status_code == 404
    assert len(rel._MOCK_ENTITY_ROLES) == 1  # not deleted


def test_list_relationships_excludes_another_firms_relationship_for_the_same_entity_id():
    # Same entity_id string reused across two firms — a plausible id collision
    # or a guessed id; each firm must only ever see its own relationship rows.
    rel._MOCK_RELATIONSHIPS.append({"id": "rel-a", "firm_id": FIRM_A, "from_entity_id": "shared-id", "to_entity_id": "x", "description": "Firm A's link"})
    rel._MOCK_RELATIONSHIPS.append({"id": "rel-b", "firm_id": FIRM_B, "from_entity_id": "shared-id", "to_entity_id": "y", "description": "Firm B's link"})

    resp = rel.list_relationships(entity_id="shared-id", current_user=USER_A)
    assert [r["id"] for r in resp["data"]] == ["rel-a"]


def test_list_cross_client_matches_excludes_another_firm():
    rel._MOCK_CROSS_MATCHES.append({"id": "m-a", "firm_id": FIRM_A, "reviewed": False})
    rel._MOCK_CROSS_MATCHES.append({"id": "m-b", "firm_id": FIRM_B, "reviewed": False})

    resp = rel.list_cross_client_matches(entity_id=None, reviewed=None, current_user=USER_A)
    assert [m["id"] for m in resp["data"]] == ["m-a"]


def test_review_cross_client_match_404s_on_another_firms_match():
    rel._MOCK_CROSS_MATCHES.append({"id": "m-b", "firm_id": FIRM_B, "reviewed": False, "confirmed": None})

    with pytest.raises(HTTPException) as ei:
        rel.review_cross_client_match("m-b", rel.CrossMatchReviewIn(is_confirmed=True), current_user=USER_A)
    assert ei.value.status_code == 404
    assert rel._MOCK_CROSS_MATCHES[0]["reviewed"] is False  # not mutated


def test_list_entity_to_entity_relationships_excludes_another_firm():
    rel._MOCK_ENTITY_TO_ENTITY_RELS.append({"id": "e2e-a", "firm_id": FIRM_A, "from_entity_id": "shared", "to_entity_id": "x"})
    rel._MOCK_ENTITY_TO_ENTITY_RELS.append({"id": "e2e-b", "firm_id": FIRM_B, "from_entity_id": "shared", "to_entity_id": "y"})

    resp = rel.list_entity_to_entity_relationships(entity_id="shared", current_user=USER_A)
    assert [r["id"] for r in resp["data"]] == ["e2e-a"]


def test_list_loans_excludes_another_firm():
    rel._MOCK_LOANS.append({"id": "loan-a", "firm_id": FIRM_A, "client_id": "c1", "principal_paise": 100, "section_185_flagged": False, "section_186_flagged": False})
    rel._MOCK_LOANS.append({"id": "loan-b", "firm_id": FIRM_B, "client_id": "c1", "principal_paise": 999999900, "section_185_flagged": False, "section_186_flagged": False})

    resp = rel.list_loans(client_id=None, flagged_only=False, current_user=USER_A)
    assert [l["id"] for l in resp["data"]] == ["loan-a"]


def test_section_185_report_excludes_another_firms_flagged_loans():
    rel._MOCK_LOANS.append({"id": "loan-a", "firm_id": FIRM_A, "client_id": "c1", "principal_paise": 100, "section_185_flagged": True})
    rel._MOCK_LOANS.append({"id": "loan-b", "firm_id": FIRM_B, "client_id": "c1", "principal_paise": 999999900, "section_185_flagged": True})

    resp = rel.section_185_report(client_id=None, current_user=USER_A)
    assert resp["data"]["count"] == 1
    assert resp["data"]["total_principal_paise"] == 100  # Firm B's principal never leaks into the total


def test_list_properties_excludes_another_firm():
    rel._MOCK_PROPERTIES.append({"id": "prop-a", "firm_id": FIRM_A, "client_id": "c1", "entity_id": None})
    rel._MOCK_PROPERTIES.append({"id": "prop-b", "firm_id": FIRM_B, "client_id": "c1", "entity_id": None})

    resp = rel.list_properties(client_id=None, entity_id=None, current_user=USER_A)
    assert [p["id"] for p in resp["data"]] == ["prop-a"]


def test_related_party_report_excludes_another_firms_data_for_the_same_client_id():
    rel._MOCK_ENTITY_ROLES.append({"id": "r-a", "firm_id": FIRM_A, "client_id": "shared-client", "entity_id": "e-a", "role": "Director"})
    rel._MOCK_ENTITY_ROLES.append({"id": "r-b", "firm_id": FIRM_B, "client_id": "shared-client", "entity_id": "e-b", "role": "Director"})

    resp = rel.related_party_report(client_id="shared-client", current_user=USER_A)
    assert resp["data"]["related_party_count"] == 1


def test_create_relationship_rejects_entity_owned_by_another_firm():
    rel._MOCK_ENTITIES.append({"id": "e-b", "firm_id": FIRM_B, "full_name": "Firm B Entity"})
    body = rel.RelationshipIn(from_entity_id="e-b", to_entity_id="e-b", relationship_type="Associated Company")

    with pytest.raises(HTTPException) as ei:
        rel.create_relationship(body, current_user=USER_A)
    assert ei.value.status_code == 404
    assert rel._MOCK_RELATIONSHIPS == []  # nothing planted


def test_create_entity_to_entity_relationship_rejects_entity_owned_by_another_firm():
    rel._MOCK_ENTITIES.append({"id": "e-b", "firm_id": FIRM_B, "full_name": "Firm B Entity"})
    body = rel.EntityToEntityRelIn(from_entity_id="e-b", to_entity_id="e-b", relationship_type="subsidiary")

    with pytest.raises(HTTPException) as ei:
        rel.create_entity_to_entity_relationship(body, current_user=USER_A)
    assert ei.value.status_code == 404
    assert rel._MOCK_ENTITY_TO_ENTITY_RELS == []


def test_create_loan_rejects_entity_owned_by_another_firm(monkeypatch):
    monkeypatch.setattr(authz, "_USE_MOCK", True)  # assert_client_access permissive; entity check is what's under test
    rel._MOCK_ENTITIES.append({"id": "e-b", "firm_id": FIRM_B, "full_name": "Firm B Entity"})
    body = rel.LoanIn(client_id="c1", entity_id="e-b", loan_type="to_director", principal_paise=1000, interest_rate=10.0)

    with pytest.raises(HTTPException) as ei:
        rel.create_loan(body, current_user=USER_A)
    assert ei.value.status_code == 404
    assert rel._MOCK_LOANS == []


def test_create_property_rejects_entity_owned_by_another_firm(monkeypatch):
    monkeypatch.setattr(authz, "_USE_MOCK", True)
    rel._MOCK_ENTITIES.append({"id": "e-b", "firm_id": FIRM_B, "full_name": "Firm B Entity"})
    body = rel.PropertyIn(client_id="c1", entity_id="e-b", address="1 Sneaky St", property_type="residential", cost_paise=1000)

    with pytest.raises(HTTPException) as ei:
        rel.create_property(body, current_user=USER_A)
    assert ei.value.status_code == 404
    assert rel._MOCK_PROPERTIES == []


# ─────────────────────────────────────────────────────────────────────────────
# Area 2 — task_recurring.py: unchecked client_id/template_id + unscoped
# enrichment lookups in list_recurring
# ─────────────────────────────────────────────────────────────────────────────

import routers.task_recurring as rec_router
from routers.task_recurring import RecurringCreate
from tests.e2e_harness import FakeDB


@pytest.fixture
def enforced(monkeypatch):
    """Real (non-mock) client-ownership enforcement, same fixture pattern as
    test_r231/test_r235: c1 belongs to Firm A, c-other belongs to Firm B."""
    monkeypatch.setattr(authz, "_USE_MOCK", False)

    def fake_belongs(client_id, firm_id):
        if client_id == "c-other":
            return firm_id == FIRM_B
        return firm_id == FIRM_A
    monkeypatch.setattr(authz, "_client_belongs_to_firm", fake_belongs)
    yield


def test_create_recurring_rejects_another_firms_client(monkeypatch, enforced):
    db = FakeDB()
    monkeypatch.setattr(rec_router, "_get_db", lambda: db)
    body = RecurringCreate(client_id="c-other", title="Sneaky", frequency="monthly", next_due_date="2026-08-01")

    with pytest.raises(HTTPException) as ei:
        rec_router.create_recurring(body, current_user=USER_A)
    assert ei.value.status_code == 404
    assert db.table("task_recurring_configs").select("*").execute().data == []


def test_create_recurring_rejects_another_firms_private_template(monkeypatch, enforced):
    db = FakeDB()
    db.seed("task_templates", {"id": "tpl-b", "firm_id": FIRM_B, "name": "Firm B's private template"})
    monkeypatch.setattr(rec_router, "_get_db", lambda: db)
    body = RecurringCreate(template_id="tpl-b", frequency="monthly", next_due_date="2026-08-01")

    with pytest.raises(HTTPException) as ei:
        rec_router.create_recurring(body, current_user=USER_A)
    assert ei.value.status_code == 404
    assert db.table("task_recurring_configs").select("*").execute().data == []


def test_create_recurring_accepts_own_client_and_system_template(monkeypatch, enforced):
    db = FakeDB()
    db.seed("task_templates", {"id": "tpl-sys", "firm_id": None, "name": "Shared System Template"})
    monkeypatch.setattr(rec_router, "_get_db", lambda: db)
    body = RecurringCreate(client_id="c1", template_id="tpl-sys", frequency="monthly", next_due_date="2026-08-01")

    result = rec_router.create_recurring(body, current_user=USER_A)
    assert result["success"] is True
    assert result["data"]["config"]["client_id"] == "c1"


def test_list_recurring_never_leaks_another_firms_template_or_client_name(monkeypatch):
    """Even if a config row somehow references another firm's private
    template_id/client_id (e.g. a legacy row from before task #244's
    create_recurring fix), the enrichment step in list_recurring must not
    resolve and leak that firm's template_name/client_name."""
    db = FakeDB()
    db.seed("task_recurring_configs", {
        "id": "cfg-1", "firm_id": FIRM_A, "title": "Config", "frequency": "monthly",
        "next_due_date": "2026-08-01", "is_active": True,
        "template_id": "tpl-b", "client_id": "client-b",
    })
    db.seed("task_templates", {"id": "tpl-b", "firm_id": FIRM_B, "name": "Firm B's Secret Template"})
    db.seed("clients", {"id": "client-b", "firm_id": FIRM_B, "client_name": "Firm B's Secret Client"})
    monkeypatch.setattr(rec_router, "_get_db", lambda: db)

    result = rec_router.list_recurring(current_user=USER_A)
    cfg = result["data"]["configs"][0]
    assert cfg["template_name"] is None
    assert cfg["client_name"] is None


def test_list_recurring_resolves_own_firms_and_system_template_names(monkeypatch):
    db = FakeDB()
    db.seed("task_recurring_configs", {
        "id": "cfg-1", "firm_id": FIRM_A, "title": None, "frequency": "monthly",
        "next_due_date": "2026-08-01", "is_active": True,
        "template_id": "tpl-sys", "client_id": "client-a",
    })
    db.seed("task_templates", {"id": "tpl-sys", "firm_id": None, "name": "Shared Template"})
    db.seed("clients", {"id": "client-a", "firm_id": FIRM_A, "client_name": "Firm A's Client"})
    monkeypatch.setattr(rec_router, "_get_db", lambda: db)

    result = rec_router.list_recurring(current_user=USER_A)
    cfg = result["data"]["configs"][0]
    assert cfg["template_name"] == "Shared Template"
    assert cfg["client_name"] == "Firm A's Client"


def test_update_recurring_does_not_update_another_firms_config(monkeypatch):
    """update_recurring's existence pre-check was firm-scoped, but the actual
    UPDATE call itself was not — defense-in-depth regression guard."""
    db = FakeDB()
    db.seed("task_recurring_configs", {
        "id": "cfg-b", "firm_id": FIRM_B, "title": "Firm B Config", "frequency": "monthly",
        "next_due_date": "2026-08-01", "is_active": True,
    })
    monkeypatch.setattr(rec_router, "_get_db", lambda: db)

    with pytest.raises(HTTPException) as ei:
        rec_router.update_recurring("cfg-b", rec_router.RecurringUpdate(title="Hijacked"), current_user=USER_A)
    assert ei.value.status_code == 404
    assert db.table("task_recurring_configs").select("*").eq("id", "cfg-b").execute().data[0]["title"] == "Firm B Config"


# ─────────────────────────────────────────────────────────────────────────────
# Area 3 — task_templates.py: get/update/delete/instantiate never verified
# template ownership
# ─────────────────────────────────────────────────────────────────────────────

import routers.task_templates as tpl_router
from routers.task_templates import TemplateUpdate, InstantiateRequest


def test_get_template_404s_on_another_firms_private_template(monkeypatch):
    db = FakeDB()
    db.seed("task_templates", {"id": "tpl-b", "firm_id": FIRM_B, "name": "Firm B's private template"})
    import repositories.task_template_repository as ttr_mod
    monkeypatch.setattr(ttr_mod, "_get_db", lambda: db)

    with pytest.raises(HTTPException) as ei:
        tpl_router.get_template("tpl-b", current_user=USER_A)
    assert ei.value.status_code == 404


def test_get_template_allows_shared_system_template(monkeypatch):
    db = FakeDB()
    db.seed("task_templates", {"id": "tpl-sys", "firm_id": None, "name": "Shared Template"})
    import repositories.task_template_repository as ttr_mod
    monkeypatch.setattr(ttr_mod, "_get_db", lambda: db)

    result = tpl_router.get_template("tpl-sys", current_user=USER_A)
    assert result["data"]["template"]["name"] == "Shared Template"


def test_update_template_404s_on_another_firms_template(monkeypatch):
    db = FakeDB()
    db.seed("task_templates", {"id": "tpl-b", "firm_id": FIRM_B, "name": "Firm B's private template"})
    import repositories.task_template_repository as ttr_mod
    monkeypatch.setattr(ttr_mod, "_get_db", lambda: db)

    with pytest.raises(HTTPException) as ei:
        tpl_router.update_template("tpl-b", TemplateUpdate(name="Hijacked"), current_user=USER_A)
    assert ei.value.status_code == 404
    assert db.table("task_templates").select("*").eq("id", "tpl-b").execute().data[0]["name"] == "Firm B's private template"


def test_update_template_rejects_editing_a_shared_system_template(monkeypatch):
    db = FakeDB()
    db.seed("task_templates", {"id": "tpl-sys", "firm_id": None, "name": "Shared Template"})
    import repositories.task_template_repository as ttr_mod
    monkeypatch.setattr(ttr_mod, "_get_db", lambda: db)

    with pytest.raises(HTTPException) as ei:
        tpl_router.update_template("tpl-sys", TemplateUpdate(name="Hijacked"), current_user=USER_A)
    assert ei.value.status_code == 403
    assert db.table("task_templates").select("*").eq("id", "tpl-sys").execute().data[0]["name"] == "Shared Template"


def test_delete_template_404s_on_another_firms_template(monkeypatch):
    db = FakeDB()
    db.seed("task_templates", {"id": "tpl-b", "firm_id": FIRM_B, "name": "Firm B's private template"})
    import repositories.task_template_repository as ttr_mod
    monkeypatch.setattr(ttr_mod, "_get_db", lambda: db)

    with pytest.raises(HTTPException) as ei:
        tpl_router.delete_template("tpl-b", current_user=USER_A)
    assert ei.value.status_code == 404
    assert len(db.table("task_templates").select("*").execute().data) == 1  # not deleted


def test_instantiate_template_rejects_another_firms_client(monkeypatch, enforced):
    db = FakeDB()
    db.seed("task_templates", {"id": "tpl-a", "firm_id": FIRM_A, "name": "Firm A's template", "tags": []})
    import repositories.task_template_repository as ttr_mod
    monkeypatch.setattr(ttr_mod, "_get_db", lambda: db)
    import core.supabase_client as sc_mod
    monkeypatch.setattr(sc_mod, "get_supabase", lambda: db)  # instantiate_template imports it locally each call

    body = InstantiateRequest(client_id="c-other")
    with pytest.raises(HTTPException) as ei:
        tpl_router.instantiate_template("tpl-a", body, current_user=USER_A)
    assert ei.value.status_code == 404


def test_instantiate_template_rejects_another_firms_private_template(monkeypatch, enforced):
    db = FakeDB()
    db.seed("task_templates", {"id": "tpl-b", "firm_id": FIRM_B, "name": "Firm B's private template", "tags": []})
    import repositories.task_template_repository as ttr_mod
    monkeypatch.setattr(ttr_mod, "_get_db", lambda: db)
    import core.supabase_client as sc_mod
    monkeypatch.setattr(sc_mod, "get_supabase", lambda: db)  # instantiate_template imports it locally each call

    body = InstantiateRequest(client_id="c1")
    with pytest.raises(HTTPException) as ei:
        tpl_router.instantiate_template("tpl-b", body, current_user=USER_A)
    assert ei.value.status_code == 404
    assert db.table("tasks").select("*").execute().data == []  # no task created from the stolen template
