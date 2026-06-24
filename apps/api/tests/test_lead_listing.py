"""
Regression tests for GET /api/lifecycle/leads filtering.

The pipeline must only ever receive ACTIVE leads. Two classes of rows must be
excluded at the query level (not just client-side):
  - soft-deleted leads (stage == "_deleted")
  - converted leads (is_converted is true)

is_converted is a NULLABLE column (DEFAULT false), so the filter must treat
NULL as "not converted" — otherwise legitimately-active leads would vanish.
"""
from unittest.mock import patch, MagicMock

USER_MANAGER = {"auth_user_id": "u-mgr", "firm_id": "firm-aaa", "role": "Manager"}


def _self_chaining_query(rows):
    """A MagicMock query builder where every filter returns self, so all
    .neq()/.or_() calls land on one mock and execute() yields `rows`."""
    q = MagicMock()
    for method in ("select", "eq", "neq", "or_", "order", "range"):
        getattr(q, method).return_value = q
    q.execute.return_value = MagicMock(data=rows)
    return q


class TestListLeadsMockPath:
    """In-memory (no-DB) path filters deleted + converted leads."""

    def test_excludes_deleted_and_converted_keeps_null(self):
        from routers.lifecycle import list_leads
        fake_leads = [
            {"id": "1", "firm_id": "firm-aaa", "stage": "Lead",      "is_converted": False},
            {"id": "2", "firm_id": "firm-aaa", "stage": "_deleted",  "is_converted": False},
            {"id": "3", "firm_id": "firm-aaa", "stage": "Active",    "is_converted": True},
            {"id": "4", "firm_id": "firm-aaa", "stage": "Qualified", "is_converted": None},
        ]
        with patch("routers.lifecycle._db", return_value=None), \
             patch("routers.lifecycle._MOCK_LEADS", fake_leads):
            result = list_leads(stage=None, assigned_to=None, limit=50, offset=0,
                                current_user=USER_MANAGER)
        assert result["success"] is True
        ids = {l["id"] for l in result["data"]}
        # active (False) and NULL-converted kept; deleted + converted dropped
        assert ids == {"1", "4"}


class TestListLeadsDbPath:
    """Supabase path applies the exclusions as query filters."""

    def test_applies_deleted_and_converted_filters(self):
        from routers.lifecycle import list_leads
        q = _self_chaining_query([{"id": "1"}])
        mock_db = MagicMock()
        mock_db.table.return_value = q

        with patch("routers.lifecycle._db", return_value=mock_db):
            result = list_leads(stage=None, assigned_to=None, limit=50, offset=0,
                                current_user=USER_MANAGER)

        assert result["success"] is True
        # _deleted rows excluded; converted rows excluded with NULL treated as active
        q.neq.assert_any_call("stage", "_deleted")
        q.or_.assert_any_call("is_converted.is.null,is_converted.is.false")
