"""
Significant Accounting Policies — Schedule III, Division I, General Instructions.

The notes must disclose the entity's significant accounting policies, and there
was no such note at all: the generated set went straight to Fixed Assets.

Most policies are the CA's JUDGEMENTS and the system has no basis for asserting
them. Two are facts about how these books were kept rather than opinions about
them, and only those are stated:

  * depreciation — read off each row's fixed_assets.depreciation_method
  * inventory — moving average, because domain/inventory_service costs stock
    that way by construction

Everything else is named as outstanding. This follows the pattern task #240
established for gst_tds: an honest placeholder, never a plausible-looking
fabricated number — and a policies note is the worst place to invent text,
because it reads as boilerplate, nobody re-reads it, and it ends up attached to
a filed AOC-4 asserting a policy the client does not follow.
"""
import pytest

import routers.year_end_notes as yen
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "firm-1"
CLIENT = "client-1"
USER = {"id": "u1", "firm_id": FIRM, "role": "Partner",
        "email": "p@f.test", "auth_user_id": "auth-1"}


@pytest.fixture
def db(monkeypatch):
    import routers.year_end as year_end_mod
    d = FakeDB()
    wire_e2e(monkeypatch, d, [yen, year_end_mod])
    monkeypatch.setattr(yen, "_USE_MOCK", False)
    # _assert_engagement_scope lives in routers.year_end and is called by name
    # from routers.year_end_notes; its OWN _USE_MOCK governs which branch it
    # takes, independently of this module's, so it has to be flipped here too
    # or the resolver reads the (empty) in-memory mock store instead of FakeDB.
    # Same trap documented in test_r3_8_year_end_review_workflow.
    monkeypatch.setattr(year_end_mod, "_USE_MOCK", False)
    d.seed("clients", {"id": CLIENT, "firm_id": FIRM,
                       "entity_type": "Private Limited"})
    return d


def _policies(db):
    return yen._compute_accounting_policies_data(db, FIRM, CLIENT, "2025-03-31")


# ── What the books actually say ──────────────────────────────────────────────

def test_the_depreciation_method_is_read_off_the_register():
    """Not assumed. The Fixed Assets note used to assert "Written Down Value
    method" as flat text for every client, which is false for any client whose
    assets are on straight line."""
    d = FakeDB()
    d.seed("clients", {"id": CLIENT, "firm_id": FIRM, "entity_type": "Private Limited"})
    for i in range(3):
        d.seed("fixed_assets", {"id": f"a{i}", "firm_id": FIRM, "client_id": CLIENT,
                                "is_disposed": False, "depreciation_method": "SL"})
    data = yen._compute_accounting_policies_data(d, FIRM, CLIENT, "2025-03-31")
    assert data["has_fixed_assets"] is True
    assert data["depreciation_methods"] == ["SL"]
    assert "Straight Line" in yen._accounting_policies_text(data)
    assert "Written Down Value" not in yen._accounting_policies_text(data)


def test_a_register_using_both_methods_says_so_rather_than_picking_one():
    """Mixed methods within one register are legitimate, and a CA should see it
    at a glance rather than have one silently chosen for the disclosure."""
    d = FakeDB()
    d.seed("clients", {"id": CLIENT, "firm_id": FIRM, "entity_type": "Private Limited"})
    d.seed("fixed_assets", {"id": "a1", "firm_id": FIRM, "client_id": CLIENT,
                            "is_disposed": False, "depreciation_method": "SL"})
    d.seed("fixed_assets", {"id": "a2", "firm_id": FIRM, "client_id": CLIENT,
                            "is_disposed": False, "depreciation_method": "WDV"})
    data = yen._compute_accounting_policies_data(d, FIRM, CLIENT, "2025-03-31")
    assert data["depreciation_methods"] == ["SL", "WDV"]
    text = yen._accounting_policies_text(data)
    assert "more than one method" in text
    assert "Straight Line" in text and "Written Down Value" in text


def test_no_fixed_assets_means_no_depreciation_policy_is_stated():
    """A service business with no register gets no depreciation policy at all.
    Stating one would disclose a basis for assets that do not exist."""
    d = FakeDB()
    d.seed("clients", {"id": CLIENT, "firm_id": FIRM, "entity_type": "Private Limited"})
    data = yen._compute_accounting_policies_data(d, FIRM, CLIENT, "2025-03-31")
    assert data["has_fixed_assets"] is False
    assert "Depreciation" not in yen._accounting_policies_text(data)


def test_inventory_is_stated_only_for_a_stock_tracked_client():
    """domain/inventory_service costs stock on moving average by construction,
    so for a client that tracks stock this is a fact about the books. For one
    that does not, the policy is omitted rather than stated as nil."""
    d = FakeDB()
    d.seed("clients", {"id": CLIENT, "firm_id": FIRM, "entity_type": "Private Limited"})
    assert "Inventories" not in yen._accounting_policies_text(
        yen._compute_accounting_policies_data(d, FIRM, CLIENT, "2025-03-31"))

    d.seed("service_catalogue", {"id": "s1", "firm_id": FIRM, "client_id": CLIENT,
                                 "kind": "good"})
    data = yen._compute_accounting_policies_data(d, FIRM, CLIENT, "2025-03-31")
    assert data["inventory_is_stock_tracked"] is True
    assert data["inventory_valuation_basis"] == "moving average"
    assert "moving average" in yen._accounting_policies_text(data)


def test_a_services_only_catalogue_does_not_make_it_stock_tracked():
    d = FakeDB()
    d.seed("clients", {"id": CLIENT, "firm_id": FIRM, "entity_type": "Private Limited"})
    d.seed("service_catalogue", {"id": "s1", "firm_id": FIRM, "client_id": CLIENT,
                                 "kind": "service"})
    data = yen._compute_accounting_policies_data(d, FIRM, CLIENT, "2025-03-31")
    assert data["inventory_is_stock_tracked"] is False


def test_a_foreign_currency_policy_is_required_only_when_there_are_such_entries():
    """Multi-currency is dormant for most clients (migration 147 defaults
    txn_currency to INR), so this normally stays off the list."""
    # txn_currency lives on journal_LINES, not journal_entries — migration 147
    # puts it on the leg because the rate is frozen per leg. Reading it off the
    # entry returns nothing and reports "no foreign currency" for every client;
    # tests/test_backend_columns_exist_pg caught exactly that.
    d = FakeDB()
    d.seed("clients", {"id": CLIENT, "firm_id": FIRM, "entity_type": "Private Limited"})
    data = yen._compute_accounting_policies_data(d, FIRM, CLIENT, "2025-03-31")
    assert data["has_foreign_currency_transactions"] is False
    assert not any("Foreign currency" in p for p in data["ca_input_required"])


# ── What the system must NOT assert ──────────────────────────────────────────

def test_the_judgement_policies_are_named_as_outstanding_never_filled_in():
    """Revenue recognition, employee benefits, provisions, taxes on income and
    borrowing costs are the CA's assertions about the entity. Pre-filling them
    with boilerplate is the failure mode this note is most exposed to."""
    d = FakeDB()
    d.seed("clients", {"id": CLIENT, "firm_id": FIRM, "entity_type": "Private Limited"})
    data = yen._compute_accounting_policies_data(d, FIRM, CLIENT, "2025-03-31")
    outstanding = data["ca_input_required"]
    for policy in ("Revenue recognition", "Employee benefits",
                   "Taxes on income, including deferred tax", "Borrowing costs"):
        assert policy in outstanding
    text = yen._accounting_policies_text(data)
    assert "require the CA's input" in text
    assert "deliberately left blank rather than pre-filled" in text


def test_the_note_always_requires_ca_review():
    """Even the derived policies are a starting point the CA confirms, not a
    disclosure the software makes on their behalf."""
    d = FakeDB()
    d.seed("clients", {"id": CLIENT, "firm_id": FIRM, "entity_type": "Private Limited"})
    d.seed("fixed_assets", {"id": "a1", "firm_id": FIRM, "client_id": CLIENT,
                            "is_disposed": False, "depreciation_method": "WDV"})
    assert yen._compute_accounting_policies_data(
        d, FIRM, CLIENT, "2025-03-31")["requires_ca_review"] is True


def test_unavailable_books_do_not_invent_policies():
    data = yen._compute_accounting_policies_data(None, FIRM, CLIENT, "2025-03-31")
    assert data["depreciation_methods"] == []
    assert data["requires_ca_review"] is True
    assert "requires the CA's input" in data["review_note"]


# ── Position and numbering ───────────────────────────────────────────────────

def test_policies_is_the_first_note(db):
    db.seed("year_end_engagements", {"id": "E1", "firm_id": FIRM, "client_id": CLIENT,
                                     "financial_year": "2024-25", "status": "draft",
                                     "fy_start": "2024-04-01", "fy_end": "2025-03-31"})
    notes = yen.generate_notes("E1", current_user=USER)["data"]
    assert notes[0]["note_type"] == "accounting_policies"
    assert notes[0]["sequence_no"] == 1
    assert notes[0]["title"].startswith("Note 1 — Significant Accounting Policies")


def test_every_note_is_numbered_by_its_position(db):
    """Each title used to hardcode its own number, so inserting a note ahead of
    them left "Note 1 — Fixed Assets" sitting at sequence 2 — and the note
    references on the face of the statements pointing at the wrong note."""
    db.seed("year_end_engagements", {"id": "E2", "firm_id": FIRM, "client_id": CLIENT,
                                     "financial_year": "2024-25", "status": "draft",
                                     "fy_start": "2024-04-01", "fy_end": "2025-03-31"})
    notes = yen.generate_notes("E2", current_user=USER)["data"]
    for note in notes:
        assert note["title"].startswith(f"Note {note['sequence_no']} — "), note["title"]
    assert [n["sequence_no"] for n in notes] == list(range(1, len(notes) + 1))


def test_the_fixed_assets_note_no_longer_asserts_a_depreciation_method(db):
    """It said "Depreciation is provided on Written Down Value method" for
    every client. The basis belongs to the policies note, derived from the
    register — and stating it in two places is how the two come to disagree."""
    db.seed("year_end_engagements", {"id": "E3", "firm_id": FIRM, "client_id": CLIENT,
                                     "financial_year": "2024-25", "status": "draft",
                                     "fy_start": "2024-04-01", "fy_end": "2025-03-31"})
    notes = yen.generate_notes("E3", current_user=USER)["data"]
    fa = next(n for n in notes if n["note_type"] == "fixed_assets")
    assert "Written Down Value" not in fa["content"]
    assert "Significant Accounting Policies note" in fa["content"]
