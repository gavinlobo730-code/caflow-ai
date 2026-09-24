"""
The in-memory notification store MOCK MODE runs against. Not a service.

WHY THIS FILE IS NAMED WHAT IT IS NOW
    It was `domain/notification_service.py`, one import away from
    `services/notification_service.py`, which is the live one that
    routers/tasks.py calls. Two files with one basename, one of them a fixture
    list, is the `public.suppliers` shape: a future reader reaches for the
    name, gets the mock, and writes notifications nobody receives.

    It also carried SIX module-level functions — create_notification,
    get_notifications, mark_read, mark_all_read, get_unread_count,
    get_notification_stats — which read as an API and had ZERO callers. Every
    apparent reference was either `routers/notifications.py`'s own endpoint
    function or `repositories/notifications_repository.py`'s own method sharing
    the name, which is exactly why a grep count did not settle it. They are
    deleted; the two modules that really answer those questions are the router
    and the repository.

WHAT IS LEFT IS USED, AND THE RECORDED BELIEF ABOUT IT WAS WRONG TWICE
    `docs/audits/questions-for-the-owner.md` recorded a decision to DELETE this
    file as "imported by nothing", and
    `tests/test_a_domain_module_has_a_reader.py` said "nothing in the
    production tree imports it". Both were false:
    `repositories/notifications_repository.py` imports MOCK_NOTIFICATIONS and
    _notif_index, inside an `if _USE_MOCK:` block — a conditional import at
    module top, which is why neither a reader nor a scan noticed. Deleting the
    file would have broken mock mode, which is what the entire ~15,800-test
    suite runs in.

    So the fixtures stay and the name stops competing with the service.
"""
from datetime import date, timedelta, datetime
from typing import Optional
import uuid
from core.ist_clock import ist_today

# THE DAY THE FIXTURES BELOW WERE BUILT, AND NOTHING ELSE. `ist_today()` at
# module level is evaluated ONCE, at import, so on the long-lived uvicorn
# process `apps/api` runs it is the DEPLOY date for the life of that process.
# The name says which moment it is, so nothing reads it as the current day.
_FIXTURES_BUILT_ON = ist_today()

MOCK_NOTIFICATIONS: list[dict] = [
    {
        "id": "notif-001",
        "type": "risk_detected",
        "title": "Critical: TDS Mismatch — Joshi Textiles",
        "body": "Form 16 TDS ₹1.8L vs 26AS ₹1.4L. Reconcile before ITR filing.",
        "severity": "critical",
        "is_read": False,
        "client_id": "c-005",
        "user_id": "tm-001",
        "action_url": "/risks",
        "created_at": (_FIXTURES_BUILT_ON - timedelta(days=10)).isoformat(),
    },
    {
        "id": "notif-002",
        "type": "compliance_due",
        "title": "GSTR-3B Overdue — Mehta Consulting",
        "body": "GSTR-3B is 10 days overdue. Late fee ₹500 accrued. File immediately.",
        "severity": "critical",
        "is_read": False,
        "client_id": "c-003",
        "user_id": "tm-001",
        "action_url": "/compliance",
        "created_at": (_FIXTURES_BUILT_ON - timedelta(days=10)).isoformat(),
    },
    {
        "id": "notif-003",
        "type": "task_assigned",
        "title": "Task Assigned: Collect Sales Data",
        "body": "You have been assigned: Collect Sales Data — Sharma Enterprises. Due in 2 days.",
        "severity": "high",
        "is_read": False,
        "client_id": "c-001",
        "user_id": "tm-001",
        "action_url": "/tasks",
        "created_at": (_FIXTURES_BUILT_ON - timedelta(days=3)).isoformat(),
    },
    {
        "id": "notif-004",
        "type": "document_processed",
        "title": "Document Extracted: Form 16 — Joshi Textiles",
        "body": "Form 16 for FY 2024-25 extracted with 91% confidence. Review recommended.",
        "severity": "medium",
        "is_read": False,
        "client_id": "c-005",
        "user_id": "tm-001",
        "action_url": "/documents",
        "created_at": (_FIXTURES_BUILT_ON - timedelta(days=10)).isoformat(),
    },
    {
        "id": "notif-005",
        "type": "ai_recommendation",
        "title": "AI Insight: Tax Audit Threshold Alert",
        "body": "Joshi Textiles projected turnover ₹98L. Monitor Q4 for potential tax audit requirement.",
        "severity": "medium",
        "is_read": True,
        "client_id": "c-005",
        "user_id": "tm-001",
        "action_url": "/ai-assistant",
        "created_at": (_FIXTURES_BUILT_ON - timedelta(days=15)).isoformat(),
    },
    {
        "id": "notif-006",
        "type": "compliance_due",
        "title": "GSTR-1 Due in 3 Days — Sharma Enterprises",
        "body": "GSTR-1 due " + (_FIXTURES_BUILT_ON + timedelta(days=3)).strftime("%d %b %Y") + ". Preparation not started.",
        "severity": "high",
        "is_read": False,
        "client_id": "c-001",
        "user_id": "tm-001",
        "action_url": "/compliance",
        "created_at": _FIXTURES_BUILT_ON.isoformat(),
    },
    {
        "id": "notif-007",
        "type": "risk_detected",
        "title": "Document Extraction Failed — Patel & Sons",
        "body": "Bank statement extraction confidence 41%. Manual review required.",
        "severity": "high",
        "is_read": False,
        "client_id": "c-002",
        "user_id": "tm-001",
        "action_url": "/documents",
        "created_at": (_FIXTURES_BUILT_ON - timedelta(days=3)).isoformat(),
    },
    {
        "id": "notif-008",
        "type": "status_changed",
        "title": "GSTR-3B Filed — Desai Traders",
        "body": "GSTR-3B for previous period filed successfully. Acknowledgement received.",
        "severity": "info",
        "is_read": True,
        "client_id": "c-004",
        "user_id": "tm-001",
        "action_url": "/compliance",
        "created_at": (_FIXTURES_BUILT_ON - timedelta(days=11)).isoformat(),
    },
    {
        "id": "notif-009",
        "type": "ai_recommendation",
        "title": "AI Copilot: 5 Insights Generated",
        "body": "AI Copilot generated 5 new insights for your client portfolio. Review recommended.",
        "severity": "info",
        "is_read": True,
        "client_id": None,
        "user_id": "tm-001",
        "action_url": "/ai-assistant",
        "created_at": (_FIXTURES_BUILT_ON - timedelta(days=1)).isoformat(),
    },
    {
        "id": "notif-010",
        "type": "task_assigned",
        "title": "Task: CA Review Required — GSTR-1",
        "body": "Sharma Enterprises GSTR-1 ready for CA review before filing. Due in 2 days.",
        "severity": "critical",
        "is_read": False,
        "client_id": "c-001",
        "user_id": "tm-001",
        "action_url": "/tasks",
        "created_at": (_FIXTURES_BUILT_ON - timedelta(days=1)).isoformat(),
    },
    {
        "id": "notif-011",
        "type": "risk_detected",
        "title": "AIS Income Mismatch — Mehta Consulting",
        "body": "AIS income ₹8.5L vs books ₹7.3L. Gap ₹1.2L may attract IT scrutiny.",
        "severity": "high",
        "is_read": False,
        "client_id": "c-003",
        "user_id": "tm-001",
        "action_url": "/risks",
        "created_at": (_FIXTURES_BUILT_ON - timedelta(days=7)).isoformat(),
    },
    {
        "id": "notif-012",
        "type": "compliance_due",
        "title": "Advance Tax Due 15 Jun — Desai Traders",
        "body": "15% advance tax instalment due 15 Jun 2025. Non-payment attracts Section 234C interest.",
        "severity": "high",
        "is_read": False,
        "client_id": "c-004",
        "user_id": "tm-001",
        "action_url": "/compliance",
        "created_at": (_FIXTURES_BUILT_ON - timedelta(days=2)).isoformat(),
    },
]

_notif_index = {n["id"]: n for n in MOCK_NOTIFICATIONS}
