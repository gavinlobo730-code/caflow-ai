"""
Client-assignment scope on the engagement-letter router.

Unlike sales_invoices and purchase_bills, this router did import `core.authz` —
`create_engagement` had the check. Nothing else did, so an engagement id from
another manager's client was accepted by every other endpoint, including the
ones with real-world reach:

  * `/send` and `/resend` email the letter to the client's own signatory
  * `/recipient` changes the address the signing link goes to
  * `/sign` and `/reject` settle the engagement
  * `/pdf` and `/signing-link` hand over the document and the link itself

Two things are deliberately NOT guarded, and both are tested here rather than
merely asserted in a comment:

  * `/templates*` — `engagement_templates` has firm_id and no client_id
    (migration 115). A template is firm property.
  * an engagement whose `client_id` is NULL — the column is nullable because an
    engagement can be raised against a **lead**, before they are a client at all.
"""
import pytest
from fastapi import HTTPException

import routers.engagement_letters as el

FIRM, MINE, THEIRS = "firm-1", "client-mine", "client-theirs"
USER = {"id": "u1", "firm_id": FIRM, "role": "manager"}


@pytest.fixture
def deny(monkeypatch):
    """Refuse exactly one client, allow the rest — closer to a real assignment
    boundary than refusing everything, and it catches a guard that resolves the
    wrong id."""
    seen = []

    def _check(user, client_id):
        seen.append(client_id)
        if client_id == THEIRS:
            raise HTTPException(status_code=404, detail="Not found")

    monkeypatch.setattr(el, "assert_client_access", _check)
    return seen


@pytest.fixture
def seeded(monkeypatch):
    monkeypatch.setattr(el, "_MOCK_ENGAGEMENTS", [
        {"id": "E-MINE", "firm_id": FIRM, "client_id": MINE, "status": "Draft"},
        {"id": "E-THEIRS", "firm_id": FIRM, "client_id": THEIRS, "status": "Sent"},
        # No client_id at all: raised against a lead, before they are a client.
        {"id": "E-LEAD", "firm_id": FIRM, "client_id": None,
         "lead_id": "lead-1", "status": "Draft"},
    ])
    monkeypatch.setattr(el, "_MOCK_EVENTS", [])


# ══════════════════════════════════════════════════════════════════════════════
# The guard refuses
# ══════════════════════════════════════════════════════════════════════════════

def test_another_managers_engagement_is_refused(deny, seeded):
    with pytest.raises(HTTPException) as e:
        el.get_engagement("E-THEIRS", current_user=USER)
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_your_own_engagement_still_resolves(deny, seeded):
    assert el._assert_engagement_scope(None, USER, "E-MINE") == MINE
    assert deny == [MINE]


def test_sending_another_clients_letter_to_their_signatory_is_refused(deny, seeded):
    """`/send` emails the engagement letter out. A refusal after the email has
    gone is not a refusal."""
    with pytest.raises(HTTPException) as e:
        el.send_engagement("E-THEIRS", current_user=USER)
    assert e.value.status_code == 404


def test_changing_the_recipient_of_another_clients_letter_is_refused(deny, seeded):
    """The most dangerous one in the router: it redirects where the signing link
    goes, so a successful call hands the letter to an address of your choosing."""
    with pytest.raises(HTTPException) as e:
        el.change_recipient("E-THEIRS", body=None, current_user=USER)
    assert e.value.status_code == 404


def test_the_signing_link_of_another_clients_letter_is_refused(deny, seeded):
    with pytest.raises(HTTPException) as e:
        el.get_signing_link("E-THEIRS", current_user=USER)
    assert e.value.status_code == 404


def test_the_pdf_of_another_clients_letter_is_refused(deny, seeded):
    with pytest.raises(HTTPException) as e:
        el.download_engagement_pdf("E-THEIRS", current_user=USER)
    assert e.value.status_code == 404


def test_deleting_another_clients_engagement_is_refused(deny, seeded):
    with pytest.raises(HTTPException) as e:
        el.delete_engagement("E-THEIRS", current_user=USER)
    assert e.value.status_code == 404
    assert [e_["id"] for e_ in el._MOCK_ENGAGEMENTS] == ["E-MINE", "E-THEIRS", "E-LEAD"]


def test_an_unknown_engagement_is_the_same_404_as_a_forbidden_one(deny, seeded):
    """Two reasons, one answer — otherwise the status code is an oracle for
    which engagement ids exist."""
    with pytest.raises(HTTPException) as missing:
        el._assert_engagement_scope(None, USER, "no-such-id")
    with pytest.raises(HTTPException) as hidden:
        el._assert_engagement_scope(None, USER, "E-THEIRS")
    assert missing.value.status_code == hidden.value.status_code == 404


def test_the_lookup_is_still_firm_scoped(seeded):
    """Assignment scope is an ADDITION to tenant scope, not a replacement."""
    other_firm = {"id": "u2", "firm_id": "firm-2", "role": "partner"}
    assert el._engagement_owner(None, other_firm, "E-MINE") == (False, None)


# ══════════════════════════════════════════════════════════════════════════════
# A lead-stage engagement has no client to scope to
# ══════════════════════════════════════════════════════════════════════════════

def test_an_engagement_raised_against_a_lead_is_not_404d_for_having_no_client(deny, seeded):
    """`engagements.client_id` is nullable — the letter may precede the client
    existing. Collapsing "no client_id" into "not found" would 404 every
    pre-client engagement in the firm."""
    assert el._engagement_owner(None, USER, "E-LEAD") == (True, None)
    assert el._assert_engagement_scope(None, USER, "E-LEAD") is None
    # It IS still put to the check — as a firm-level resource, which is what
    # assert_client_access(user, None) means.
    assert deny == [None]


def test_a_lead_engagement_survives_the_firm_wide_list_narrowing(monkeypatch, seeded):
    """filter_by_client keeps rows with no client_id. If it did not, narrowing
    the firm-wide view would silently delete the entire pre-client pipeline."""
    monkeypatch.setattr(el, "filter_by_client",
                        lambda user, rows: [r for r in rows
                                            if not r.get("client_id")
                                            or r["client_id"] == MINE])
    out = el.list_engagements(status=None, lead_id=None, client_id=None,
                              current_user=USER)
    ids = [e["id"] for e in out["data"]["engagements"]]
    assert ids == ["E-MINE", "E-LEAD"]


def test_naming_a_client_checks_it_instead_of_narrowing(deny, seeded, monkeypatch):
    monkeypatch.setattr(el, "filter_by_client",
                        lambda *_a: pytest.fail("should not narrow a named request"))
    with pytest.raises(HTTPException):
        el.list_engagements(status=None, lead_id=None, client_id=THEIRS,
                            current_user=USER)
    assert deny == [THEIRS]


# ══════════════════════════════════════════════════════════════════════════════
# Templates are firm property — guarding them would be theatre
# ══════════════════════════════════════════════════════════════════════════════

def test_templates_are_reachable_by_anyone_in_the_firm(monkeypatch):
    """`engagement_templates` has firm_id and no client_id (migration 115).
    There is no client to check, and inventing one would either block a
    legitimate user or check something meaningless.

    This is the counterweight to the sweep: over-guarding is a real failure
    mode, not a safe default."""
    monkeypatch.setattr(el, "assert_client_access",
                        lambda *_a: pytest.fail("templates have no client to scope to"))
    monkeypatch.setattr(el, "_MOCK_TEMPLATES", [
        {"id": "T1", "firm_id": FIRM, "name": "Audit", "service_type": "audit",
         "is_deleted": False, "content": "", "version": 1, "is_default": True},
    ])
    out = el.list_templates(current_user=USER)
    assert [t["id"] for t in out["data"]["templates"]] == ["T1"]


def test_a_template_from_another_firm_is_still_out_of_reach(monkeypatch):
    """Exempt from CLIENT scope, not from tenant scope. (The handler seeds six
    firm defaults when it finds none of its own, so the assertion is that the
    OTHER firm's template is absent, not that the list is empty.)"""
    monkeypatch.setattr(el, "_MOCK_TEMPLATES", [
        {"id": "T1", "firm_id": "firm-2", "name": "Audit", "service_type": "audit",
         "is_deleted": False, "content": "", "version": 1, "is_default": True},
    ])
    out = el.list_templates(current_user=USER)
    returned = out["data"]["templates"]
    assert "T1" not in [t["id"] for t in returned]
    assert {t["firm_id"] for t in returned} == {FIRM}
