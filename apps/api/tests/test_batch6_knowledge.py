"""
Batch 6 (Amendment v1.1) — Knowledge Base + Client Instructions, application-layer
tests (mock mode). Covers the security-critical visibility/authoring helpers (the
PRIMARY control, since service-role bypasses RLS) and RBAC. DB-level assignment-gated
RLS + version immutability are verified in test_batch6_migration.py.
"""
import pytest

from core.permissions import can
import services.knowledge_service as kb

PARTNER = {"role": "Partner"}
MANAGER = {"role": "Manager"}
EXEC = {"role": "Executive"}
REVIEWER = {"role": "Reviewer"}
CLIENT = {"role": "Client"}


def view(user, internal, assigned):
    return kb.can_view_client_content(user, "C1", internal, assigned)


def test_view_partner_sees_everything():
    assert view(PARTNER, internal=False, assigned=False) is True
    assert view(PARTNER, internal=True, assigned=False) is True   # internal: partner-only allows


def test_view_manager_firm_wide_but_not_internal():
    assert view(MANAGER, internal=False, assigned=False) is True  # firm-wide, no assignment needed
    assert view(MANAGER, internal=True, assigned=True) is False   # internal -> partner-only (G1)


def test_view_executive_assignment_gated():
    assert view(EXEC, internal=False, assigned=True) is True
    assert view(EXEC, internal=False, assigned=False) is False
    assert view(EXEC, internal=True, assigned=True) is False      # internal -> partner-only


def test_view_reviewer_assignment_gated():
    assert view(REVIEWER, internal=False, assigned=True) is True
    assert view(REVIEWER, internal=False, assigned=False) is False


def test_view_client_never():
    assert view(CLIENT, internal=False, assigned=True) is False


def test_write_instruction_matrix():
    assert kb.can_write_instruction(PARTNER, False, False) is True
    assert kb.can_write_instruction(MANAGER, False, False) is True       # firm-wide
    assert kb.can_write_instruction(MANAGER, True, True) is False        # internal -> partner-only
    assert kb.can_write_instruction(EXEC, False, True) is True           # assigned
    assert kb.can_write_instruction(EXEC, False, False) is False         # unassigned
    assert kb.can_write_instruction(REVIEWER, False, True) is False      # reviewer read-only
    assert kb.can_write_instruction(CLIENT, False, True) is False
    assert kb.can_write_instruction(PARTNER, True, False) is True        # internal: partner ok


def test_next_version():
    assert kb.next_version(1) == 2
    assert kb.next_version(7) == 8


def test_rbac_resources():
    # Knowledge articles: Manager+ author, all staff read.
    assert can("Manager", "knowledge", "write") is True
    assert can("Executive", "knowledge", "write") is False
    assert can("Executive", "knowledge", "read") is True
    assert can("Reviewer", "knowledge", "read") is True
    # Client instructions: Executive+ write, Reviewer read-only.
    assert can("Executive", "client_instruction", "write") is True
    assert can("Reviewer", "client_instruction", "write") is False
    assert can("Reviewer", "client_instruction", "read") is True
    assert can("Manager", "client_instruction", "write") is True
