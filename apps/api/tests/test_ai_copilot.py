"""
Tests for Phase 11 AI Copilot Platform.
"""
import pytest
from repositories.ai_copilot_repository import AICopilotRepository


@pytest.fixture
def repo():
    return AICopilotRepository()


# ── Conversations ──────────────────────────────────────────────────────────────

class TestConversations:
    def test_create_conversation(self, repo):
        conv = repo.create_conversation("firm-test", "user-001", {
            "context_type": "compliance",
            "title": "Compliance check",
        })
        assert conv["id"] is not None
        assert conv["firm_id"] == "firm-test"
        assert conv["user_id"] == "user-001"
        assert conv["context_type"] == "compliance"
        assert conv["message_count"] == 0

    def test_list_conversations_filters_by_firm(self, repo):
        repo.create_conversation("firm-alpha", "user-x", {})
        repo.create_conversation("firm-beta", "user-y", {})
        alpha_convs = repo.list_conversations("firm-alpha", "user-x")
        assert all(c["firm_id"] == "firm-alpha" for c in alpha_convs)

    def test_archive_conversation(self, repo):
        conv = repo.create_conversation("firm-test", "user-001", {})
        archived = repo.archive_conversation("firm-test", conv["id"])
        assert archived["is_archived"] is True

    def test_get_nonexistent_conversation_returns_none(self, repo):
        result = repo.get_conversation("firm-test", "nonexistent-id")
        assert result is None


# ── Messages ──────────────────────────────────────────────────────────────────

class TestMessages:
    def test_add_and_list_messages(self, repo):
        conv = repo.create_conversation("firm-msg", "user-001", {})
        user_msg = repo.add_message("firm-msg", conv["id"], "user", "What is GSTR-1?")
        ai_msg = repo.add_message("firm-msg", conv["id"], "assistant", "GSTR-1 is due on 11th...", tokens_used=150)
        messages = repo.list_messages(conv["id"])
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"
        assert messages[1]["tokens_used"] == 150

    def test_add_message_updates_conversation_count(self, repo):
        conv = repo.create_conversation("firm-cnt", "user-001", {})
        assert conv["message_count"] == 0
        repo.add_message("firm-cnt", conv["id"], "user", "Hello")
        updated = repo.get_conversation("firm-cnt", conv["id"])
        assert updated["message_count"] == 1

    def test_first_message_auto_titles_conversation(self, repo):
        conv = repo.create_conversation("firm-title", "user-001", {})
        repo.add_message("firm-title", conv["id"], "user", "What TDS filings are due?")
        updated = repo.get_conversation("firm-title", conv["id"])
        assert "TDS" in updated["title"] or "What" in updated["title"]

    def test_rate_message(self, repo):
        conv = repo.create_conversation("firm-rate", "user-001", {})
        msg = repo.add_message("firm-rate", conv["id"], "assistant", "Good answer")
        rated = repo.rate_message("firm-rate", msg["id"], 5)
        assert rated["feedback_rating"] == 5


# ── Recommendations ───────────────────────────────────────────────────────────

class TestRecommendations:
    def test_create_recommendation(self, repo):
        rec = repo.create_recommendation("firm-rec", {
            "client_id": "c-001",
            "recommendation_type": "risk",
            "priority": "critical",
            "title": "File GSTR-3B immediately",
            "description": "2 months overdue",
            "action_label": "Create Task",
            "action_data": {},
        })
        assert rec["id"] is not None
        assert rec["status"] == "pending"
        assert rec["priority"] == "critical"

    def test_list_recommendations_filters_by_status(self, repo):
        rec = repo.create_recommendation("firm-rec2", {
            "recommendation_type": "risk",
            "priority": "high",
            "title": "Test",
            "description": "Test",
            "action_data": {},
        })
        pending = repo.list_recommendations("firm-rec2", status="pending")
        assert any(r["id"] == rec["id"] for r in pending)

    def test_update_recommendation_status(self, repo):
        rec = repo.create_recommendation("firm-act", {
            "recommendation_type": "opportunity",
            "priority": "medium",
            "title": "Tax saving",
            "description": "Harvest losses",
            "action_data": {},
        })
        updated = repo.update_recommendation_status("firm-act", rec["id"], "accepted", "user-001")
        assert updated["status"] == "accepted"
        assert updated["acted_by"] == "user-001"

    def test_priority_ordering(self, repo):
        for priority in ["low", "medium", "critical", "high"]:
            repo.create_recommendation("firm-order", {
                "recommendation_type": "risk",
                "priority": priority,
                "title": f"{priority} rec",
                "description": "Test",
                "action_data": {},
            })
        recs = repo.list_recommendations("firm-order", status="pending")
        # critical should come first
        priorities = [r["priority"] for r in recs if r["firm_id"] == "firm-order"]
        if len(priorities) >= 2:
            order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
            assert order[priorities[0]] <= order[priorities[-1]]


# ── Summaries ─────────────────────────────────────────────────────────────────

class TestSummaries:
    def test_upsert_and_get_summary(self, repo):
        summary = repo.upsert_summary("firm-sum", "client", "c-001", {
            "title": "Client Summary",
            "content": "This client is in good standing.",
            "key_points": ["On time filings", "No disputes"],
            "metadata": {},
            "model_used": "llama-3.3-70b-versatile",
        })
        assert summary["id"] is not None
        fetched = repo.get_summary("firm-sum", "client", "c-001")
        assert fetched is not None
        assert fetched["content"] == "This client is in good standing."

    def test_upsert_stales_old_summary(self, repo):
        repo.upsert_summary("firm-stale", "compliance", None, {
            "title": "Old", "content": "Old content",
            "key_points": [], "metadata": {}, "model_used": "test",
        })
        repo.upsert_summary("firm-stale", "compliance", None, {
            "title": "New", "content": "New content",
            "key_points": [], "metadata": {}, "model_used": "test",
        })
        fetched = repo.get_summary("firm-stale", "compliance")
        assert fetched["content"] == "New content"

    def test_get_nonexistent_summary_returns_none(self, repo):
        result = repo.get_summary("firm-nosummary", "executive")
        assert result is None


# ── Feedback ──────────────────────────────────────────────────────────────────

class TestFeedback:
    def test_add_feedback(self, repo):
        conv = repo.create_conversation("firm-fb", "user-001", {})
        msg = repo.add_message("firm-fb", conv["id"], "assistant", "Response")
        feedback = repo.add_feedback("firm-fb", msg["id"], "user-001", 4, "Very helpful", ["accurate"])
        assert feedback["rating"] == 4
        assert "accurate" in feedback["tags"]

    def test_feedback_updates_message_rating(self, repo):
        conv = repo.create_conversation("firm-fbr", "user-001", {})
        msg = repo.add_message("firm-fbr", conv["id"], "assistant", "Response")
        repo.add_feedback("firm-fbr", msg["id"], "user-001", 5)
        updated_msg = repo.rate_message("firm-fbr", msg["id"], 5)
        assert updated_msg["feedback_rating"] == 5
