"""Module 9.0 / M3 — assignment repository CRUD (mock store)."""
import pytest
import repositories.assignment_repository as mod
from repositories.assignment_repository import assignment_repo


@pytest.fixture(autouse=True)
def _clear():
    mod._MOCK_ASSIGNMENTS.clear()
    yield
    mod._MOCK_ASSIGNMENTS.clear()


def test_create_and_list():
    assignment_repo.create("F1", "u1", "C1")
    assignment_repo.create("F1", "u1", "C2")
    assignment_repo.create("F1", "u2", "C1")
    assert set(assignment_repo.list_for_user("F1", "u1")) == {"C1", "C2"}
    assert set(assignment_repo.list_for_client("F1", "C1")) == {"u1", "u2"}


def test_create_is_idempotent():
    assignment_repo.create("F1", "u1", "C1")
    assignment_repo.create("F1", "u1", "C1")
    assert assignment_repo.list_for_user("F1", "u1") == ["C1"]


def test_remove():
    assignment_repo.create("F1", "u1", "C1")
    assert assignment_repo.remove("F1", "u1", "C1") is True
    assert assignment_repo.list_for_user("F1", "u1") == []
    # removing again is a no-op
    assert assignment_repo.remove("F1", "u1", "C1") is False


def test_exists_and_firm_isolation():
    assignment_repo.create("F1", "u1", "C1")
    assert assignment_repo.exists("F1", "u1", "C1") is True
    # a different firm does not see the assignment
    assert assignment_repo.list_for_user("F2", "u1") == []
