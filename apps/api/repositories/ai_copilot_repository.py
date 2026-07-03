"""Repository for Phase 11 AI Copilot Platform.

Dual-path: uses Supabase when SUPABASE_URL is set, otherwise falls back to
in-memory mock data so the dev server still works without credentials.

Tables used:
    ai_conversations, ai_messages, ai_summaries,
    ai_recommendations, ai_actions, ai_feedback
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta
from typing import Optional

from repositories.base import BaseRepository

_USE_MOCK = not os.environ.get("SUPABASE_URL")


def _get_db():
    from core.supabase_client import get_supabase
    return get_supabase()


def _now() -> str:
    return datetime.utcnow().isoformat()


def _uid() -> str:
    return str(uuid.uuid4())


class AICopilotRepository(BaseRepository):

    # ── Conversations ─────────────────────────────────────────────────────────

    def list_conversations(
        self,
        firm_id: str,
        user_id: str,
        is_archived: bool = False,
        limit: int = 30,
    ) -> list[dict]:
        if _USE_MOCK:
            convs = [
                c for c in MOCK_CONVERSATIONS
                if c["firm_id"] == firm_id
                and c["user_id"] == user_id
                and c["is_archived"] == is_archived
            ]
            convs.sort(
                key=lambda c: c.get("last_message_at") or c["created_at"],
                reverse=True,
            )
            return convs[:limit]

        result = (
            _get_db()
            .table("ai_conversations")
            .select("*")
            .eq("firm_id", firm_id)
            .eq("user_id", user_id)
            .eq("is_archived", is_archived)
            .order("last_message_at", desc=True, nullsfirst=False)
            .limit(limit)
            .execute()
        )
        return result.data or []

    def get_conversation(self, firm_id: str, conversation_id: str) -> Optional[dict]:
        if _USE_MOCK:
            conv = next(
                (c for c in MOCK_CONVERSATIONS
                 if c["id"] == conversation_id and c["firm_id"] == firm_id),
                None,
            )
            if conv:
                conv = dict(conv)
                conv["messages"] = self.list_messages(conversation_id)
            return conv

        result = (
            _get_db()
            .table("ai_conversations")
            .select("*")
            .eq("id", conversation_id)
            .eq("firm_id", firm_id)
            .maybe_single()
            .execute()
        )
        conv = result.data
        if conv:
            conv["messages"] = self.list_messages(conversation_id)
        return conv

    def create_conversation(self, firm_id: str, user_id: str, data: dict) -> dict:
        record = {
            "id": _uid(),
            "firm_id": firm_id,
            "user_id": user_id,
            "title": data.get("title") or "New Conversation",
            "context_type": data.get("context_type", "global"),
            "context_id": data.get("context_id"),
            "message_count": 0,
            "last_message_at": None,
            "is_archived": False,
            "created_at": _now(),
            "updated_at": _now(),
        }
        if _USE_MOCK:
            MOCK_CONVERSATIONS.append(record)
            return record

        result = _get_db().table("ai_conversations").insert(record).execute()
        return result.data[0]

    def archive_conversation(self, firm_id: str, conversation_id: str) -> Optional[dict]:
        if _USE_MOCK:
            for c in MOCK_CONVERSATIONS:
                if c["id"] == conversation_id and c["firm_id"] == firm_id:
                    c["is_archived"] = True
                    c["updated_at"] = _now()
                    return c
            return None

        result = (
            _get_db()
            .table("ai_conversations")
            .update({"is_archived": True, "updated_at": _now()})
            .eq("id", conversation_id)
            .eq("firm_id", firm_id)
            .execute()
        )
        return result.data[0] if result.data else None

    def update_conversation_title(
        self, conversation_id: str, title: str
    ) -> Optional[dict]:
        if _USE_MOCK:
            for c in MOCK_CONVERSATIONS:
                if c["id"] == conversation_id:
                    c["title"] = title
                    c["updated_at"] = _now()
                    return c
            return None

        result = (
            _get_db()
            .table("ai_conversations")
            .update({"title": title, "updated_at": _now()})
            .eq("id", conversation_id)
            .execute()
        )
        return result.data[0] if result.data else None

    # ── Messages ──────────────────────────────────────────────────────────────

    def list_messages(self, conversation_id: str, limit: int = 100) -> list[dict]:
        if _USE_MOCK:
            msgs = [m for m in MOCK_MESSAGES if m["conversation_id"] == conversation_id]
            msgs.sort(key=lambda m: m["created_at"])
            return msgs[-limit:]

        result = (
            _get_db()
            .table("ai_messages")
            .select("*")
            .eq("conversation_id", conversation_id)
            .order("created_at")
            .limit(limit)
            .execute()
        )
        return result.data or []

    def add_message(
        self,
        firm_id: str,
        conversation_id: str,
        role: str,
        content: str,
        tokens_used: Optional[int] = None,
        metadata: Optional[dict] = None,
        model_used: str = "llama-3.3-70b-versatile",
    ) -> dict:
        now = _now()
        msg = {
            "id": _uid(),
            "conversation_id": conversation_id,
            "firm_id": firm_id,
            "role": role,
            "content": content,
            "tokens_used": tokens_used,
            "model_used": model_used,
            "metadata": metadata or {},
            "feedback_rating": None,
            "created_at": now,
        }

        if _USE_MOCK:
            MOCK_MESSAGES.append(msg)
            for c in MOCK_CONVERSATIONS:
                if c["id"] == conversation_id:
                    c["message_count"] = c.get("message_count", 0) + 1
                    c["last_message_at"] = now
                    c["updated_at"] = now
                    if role == "user" and c["message_count"] == 1:
                        c["title"] = content[:60] + ("..." if len(content) > 60 else "")
                    break
            return msg

        result = _get_db().table("ai_messages").insert(msg).execute()
        saved = result.data[0]
        # Conversation stats: the RPC atomically increments message_count and
        # stamps last_message_at/updated_at (migration 156). The previous code
        # wrapped this call in a second .update() that wrote the RPC's return
        # value back into message_count — the function returned void, so
        # `.data or 0` permanently reset the count to 0 on every message
        # (caught by the R2.2 adversarial review).
        _get_db().rpc("increment_message_count", {"conv_id": conversation_id}).execute()
        return saved

    def rate_message(
        self, firm_id: str, message_id: str, rating: int
    ) -> Optional[dict]:
        if _USE_MOCK:
            for m in MOCK_MESSAGES:
                if m["id"] == message_id and m["firm_id"] == firm_id:
                    m["feedback_rating"] = rating
                    return m
            return None

        result = (
            _get_db()
            .table("ai_messages")
            .update({"feedback_rating": rating})
            .eq("id", message_id)
            .eq("firm_id", firm_id)
            .execute()
        )
        return result.data[0] if result.data else None

    # ── Summaries ─────────────────────────────────────────────────────────────

    def get_summary(
        self,
        firm_id: str,
        summary_type: str,
        entity_id: Optional[str] = None,
    ) -> Optional[dict]:
        if _USE_MOCK:
            for s in MOCK_SUMMARIES:
                if (
                    s["firm_id"] == firm_id
                    and s["summary_type"] == summary_type
                    and s.get("entity_id") == entity_id
                    and not s["is_stale"]
                ):
                    if s.get("expires_at") and s["expires_at"] < _now():
                        s["is_stale"] = True
                        continue
                    return s
            return None

        query = (
            _get_db()
            .table("ai_summaries")
            .select("*")
            .eq("firm_id", firm_id)
            .eq("summary_type", summary_type)
            .eq("is_stale", False)
            .gt("expires_at", _now())
        )
        if entity_id is not None:
            query = query.eq("entity_id", entity_id)
        else:
            query = query.is_("entity_id", None)
        result = query.order("generated_at", desc=True).limit(1).execute()
        return result.data[0] if result.data else None

    def upsert_summary(
        self,
        firm_id: str,
        summary_type: str,
        entity_id: Optional[str],
        data: dict,
    ) -> dict:
        if _USE_MOCK:
            for s in MOCK_SUMMARIES:
                if (
                    s["firm_id"] == firm_id
                    and s["summary_type"] == summary_type
                    and s.get("entity_id") == entity_id
                ):
                    s["is_stale"] = True
            summary = {
                "id": _uid(),
                "firm_id": firm_id,
                "summary_type": summary_type,
                "entity_id": entity_id,
                "is_stale": False,
                "generated_at": _now(),
                **data,
            }
            MOCK_SUMMARIES.append(summary)
            return summary

        # Mark old summaries stale
        stale_query = (
            _get_db()
            .table("ai_summaries")
            .update({"is_stale": True})
            .eq("firm_id", firm_id)
            .eq("summary_type", summary_type)
        )
        if entity_id is not None:
            stale_query = stale_query.eq("entity_id", entity_id)
        else:
            stale_query = stale_query.is_("entity_id", None)
        stale_query.execute()

        record = {
            "id": _uid(),
            "firm_id": firm_id,
            "summary_type": summary_type,
            "entity_id": entity_id,
            "is_stale": False,
            "generated_at": _now(),
            **data,
        }
        result = _get_db().table("ai_summaries").insert(record).execute()
        return result.data[0]

    # ── Recommendations ───────────────────────────────────────────────────────

    def list_recommendations(
        self,
        firm_id: str,
        client_id: Optional[str] = None,
        status: Optional[str] = "pending",
        rec_type: Optional[str] = None,
        priority: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        if _USE_MOCK:
            recs = [r for r in MOCK_RECOMMENDATIONS if r["firm_id"] == firm_id]
            if client_id:
                recs = [r for r in recs if r.get("client_id") == client_id]
            if status:
                recs = [r for r in recs if r["status"] == status]
            if rec_type:
                recs = [r for r in recs if r["recommendation_type"] == rec_type]
            if priority:
                recs = [r for r in recs if r["priority"] == priority]
            priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
            recs.sort(
                key=lambda r: (priority_order.get(r["priority"], 9), r["created_at"])
            )
            return recs[:limit]

        query = (
            _get_db()
            .table("ai_recommendations")
            .select("*")
            .eq("firm_id", firm_id)
        )
        if client_id:
            query = query.eq("client_id", client_id)
        if status:
            query = query.eq("status", status)
        if rec_type:
            query = query.eq("recommendation_type", rec_type)
        if priority:
            query = query.eq("priority", priority)
        result = (
            query.order("created_at", desc=True).limit(limit).execute()
        )
        return result.data or []

    def get_recommendation(self, firm_id: str, rec_id: str) -> Optional[dict]:
        if _USE_MOCK:
            return next(
                (r for r in MOCK_RECOMMENDATIONS
                 if r["id"] == rec_id and r["firm_id"] == firm_id),
                None,
            )

        result = (
            _get_db()
            .table("ai_recommendations")
            .select("*")
            .eq("id", rec_id)
            .eq("firm_id", firm_id)
            .maybe_single()
            .execute()
        )
        return result.data

    def create_recommendation(self, firm_id: str, data: dict) -> dict:
        record = {
            "id": _uid(),
            "firm_id": firm_id,
            "status": "pending",
            "snoozed_until": None,
            "acted_by": None,
            "acted_at": None,
            "model_used": "llama-3.3-70b-versatile",
            "source_context": {},
            "created_at": _now(),
            "updated_at": _now(),
            **data,
        }
        if _USE_MOCK:
            MOCK_RECOMMENDATIONS.append(record)
            return record

        result = _get_db().table("ai_recommendations").insert(record).execute()
        return result.data[0]

    def update_recommendation_status(
        self,
        firm_id: str,
        rec_id: str,
        status: str,
        user_id: str,
        snooze_until: Optional[str] = None,
    ) -> Optional[dict]:
        updates = {
            "status": status,
            "acted_by": user_id,
            "acted_at": _now(),
            "updated_at": _now(),
        }
        if snooze_until:
            updates["snoozed_until"] = snooze_until

        if _USE_MOCK:
            for r in MOCK_RECOMMENDATIONS:
                if r["id"] == rec_id and r["firm_id"] == firm_id:
                    r.update(updates)
                    return r
            return None

        result = (
            _get_db()
            .table("ai_recommendations")
            .update(updates)
            .eq("id", rec_id)
            .eq("firm_id", firm_id)
            .execute()
        )
        return result.data[0] if result.data else None

    # ── AI Actions ────────────────────────────────────────────────────────────

    def create_ai_action(self, firm_id: str, data: dict) -> dict:
        record = {
            "id": _uid(),
            "firm_id": firm_id,
            "status": "pending",
            "executed_by": None,
            "executed_at": None,
            "result_data": None,
            "error_message": None,
            "created_at": _now(),
            **data,
        }
        if _USE_MOCK:
            MOCK_AI_ACTIONS.append(record)
            return record

        result = _get_db().table("ai_actions").insert(record).execute()
        return result.data[0]

    def complete_ai_action(
        self,
        action_id: str,
        result_data: dict,
        user_id: Optional[str] = None,
    ) -> Optional[dict]:
        updates = {
            "status": "executed",
            "result_data": result_data,
            "executed_by": user_id,
            "executed_at": _now(),
        }
        if _USE_MOCK:
            for a in MOCK_AI_ACTIONS:
                if a["id"] == action_id:
                    a.update(updates)
                    return a
            return None

        result = (
            _get_db()
            .table("ai_actions")
            .update(updates)
            .eq("id", action_id)
            .execute()
        )
        return result.data[0] if result.data else None

    def fail_ai_action(self, action_id: str, error_message: str) -> Optional[dict]:
        updates = {"status": "failed", "error_message": error_message}
        if _USE_MOCK:
            for a in MOCK_AI_ACTIONS:
                if a["id"] == action_id:
                    a.update(updates)
                    return a
            return None

        result = (
            _get_db()
            .table("ai_actions")
            .update(updates)
            .eq("id", action_id)
            .execute()
        )
        return result.data[0] if result.data else None

    # ── Feedback ──────────────────────────────────────────────────────────────

    def add_feedback(
        self,
        firm_id: str,
        message_id: str,
        user_id: str,
        rating: int,
        feedback_text: Optional[str] = None,
        tags: Optional[list] = None,
    ) -> dict:
        record = {
            "id": _uid(),
            "firm_id": firm_id,
            "message_id": message_id,
            "user_id": user_id,
            "rating": rating,
            "feedback_text": feedback_text,
            "tags": tags or [],
            "created_at": _now(),
        }
        if _USE_MOCK:
            MOCK_FEEDBACK.append(record)
            self.rate_message(firm_id, message_id, rating)
            return record

        result = _get_db().table("ai_feedback").insert(record).execute()
        self.rate_message(firm_id, message_id, rating)
        return result.data[0]


ai_copilot_repo = AICopilotRepository()


# ── Mock data ─────────────────────────────────────────────────────────────────
_d = lambda days: (datetime.utcnow() - timedelta(days=days)).isoformat()

MOCK_CONVERSATIONS: list[dict] = [
    {
        "id": "aicv-001",
        "firm_id": "firm-001",
        "user_id": "user-001",
        "title": "GST filing status for Q1 FY27",
        "context_type": "compliance",
        "context_id": None,
        "message_count": 4,
        "last_message_at": _d(1),
        "is_archived": False,
        "created_at": _d(3),
        "updated_at": _d(1),
    },
    {
        "id": "aicv-002",
        "firm_id": "firm-001",
        "user_id": "user-001",
        "title": "Risk clients this month",
        "context_type": "global",
        "context_id": None,
        "message_count": 2,
        "last_message_at": _d(2),
        "is_archived": False,
        "created_at": _d(2),
        "updated_at": _d(2),
    },
]

MOCK_MESSAGES: list[dict] = []

MOCK_SUMMARIES: list[dict] = []

MOCK_RECOMMENDATIONS: list[dict] = [
    {
        "id": "airec-001",
        "firm_id": "firm-001",
        "client_id": "c-003",
        "recommendation_type": "risk",
        "priority": "critical",
        "title": "GSTR-3B Overdue — Immediate Action Required",
        "description": (
            "Client Mehta Textiles has not filed GSTR-3B for 2 consecutive months. "
            "Interest and penalty will accrue."
        ),
        "rationale": (
            "2 missed filings detected in compliance records. "
            "Interest @ 18% p.a. under Section 50 CGST Act."
        ),
        "action_label": "Create Filing Task",
        "action_data": {
            "action_type": "create_task",
            "client_id": "c-003",
            "title": "File GSTR-3B immediately",
        },
        "status": "pending",
        "snoozed_until": None,
        "acted_by": None,
        "acted_at": None,
        "model_used": "llama-3.3-70b-versatile",
        "source_context": {"filing_type": "GSTR-3B", "months_overdue": 2},
        "created_at": _d(1),
        "updated_at": _d(1),
    },
    {
        "id": "airec-002",
        "firm_id": "firm-001",
        "client_id": "c-005",
        "recommendation_type": "opportunity",
        "priority": "medium",
        "title": "Tax Saving Opportunity — Capital Gain Harvesting",
        "description": (
            "Client Sharma Family has unrealized losses in equity portfolio. "
            "Harvesting before March 31 can offset capital gains."
        ),
        "rationale": (
            "Portfolio data shows unrealized losses of ₹2.4L. "
            "Section 74 CGST Act allows set-off."
        ),
        "action_label": "Schedule Advisory Call",
        "action_data": {
            "action_type": "create_task",
            "client_id": "c-005",
            "title": "Tax Planning Call — Capital Gain Harvesting",
        },
        "status": "pending",
        "snoozed_until": None,
        "acted_by": None,
        "acted_at": None,
        "model_used": "llama-3.3-70b-versatile",
        "source_context": {
            "opportunity_type": "capital_gain_harvest",
            "estimated_saving_paise": 72000,
        },
        "created_at": _d(2),
        "updated_at": _d(2),
    },
    {
        "id": "airec-003",
        "firm_id": "firm-001",
        "client_id": None,
        "recommendation_type": "workflow",
        "priority": "high",
        "title": "3 Workflows have repeated failures",
        "description": (
            "GST Filing Reminder workflow has failed 2 times due to missing client assignments. "
            "Review template configuration."
        ),
        "rationale": "Workflow failure analysis across last 30 days.",
        "action_label": "Review Workflow",
        "action_data": {
            "action_type": "trigger_workflow",
            "template_id": "wft-001",
        },
        "status": "pending",
        "snoozed_until": None,
        "acted_by": None,
        "acted_at": None,
        "model_used": "llama-3.3-70b-versatile",
        "source_context": {"template_id": "wft-001", "failure_count": 2},
        "created_at": _d(3),
        "updated_at": _d(3),
    },
]

MOCK_AI_ACTIONS: list[dict] = []
MOCK_FEEDBACK: list[dict] = []
