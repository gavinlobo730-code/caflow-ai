"""
Notification Service.
Types: task_assigned | risk_detected | document_processed | compliance_due | ai_recommendation | status_changed
"""
from datetime import date, timedelta, datetime
from typing import Optional
import uuid

today = date.today()

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
        "created_at": (today - timedelta(days=10)).isoformat(),
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
        "created_at": (today - timedelta(days=10)).isoformat(),
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
        "created_at": (today - timedelta(days=3)).isoformat(),
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
        "created_at": (today - timedelta(days=10)).isoformat(),
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
        "created_at": (today - timedelta(days=15)).isoformat(),
    },
    {
        "id": "notif-006",
        "type": "compliance_due",
        "title": "GSTR-1 Due in 3 Days — Sharma Enterprises",
        "body": "GSTR-1 due " + (today + timedelta(days=3)).strftime("%d %b %Y") + ". Preparation not started.",
        "severity": "high",
        "is_read": False,
        "client_id": "c-001",
        "user_id": "tm-001",
        "action_url": "/compliance",
        "created_at": today.isoformat(),
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
        "created_at": (today - timedelta(days=3)).isoformat(),
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
        "created_at": (today - timedelta(days=11)).isoformat(),
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
        "created_at": (today - timedelta(days=1)).isoformat(),
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
        "created_at": (today - timedelta(days=1)).isoformat(),
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
        "created_at": (today - timedelta(days=7)).isoformat(),
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
        "created_at": (today - timedelta(days=2)).isoformat(),
    },
]

_notif_index = {n["id"]: n for n in MOCK_NOTIFICATIONS}


def create_notification(
    type: str,
    title: str,
    body: str,
    severity: str,
    client_id: Optional[str] = None,
    user_id: Optional[str] = None,
    action_url: Optional[str] = None,
) -> dict:
    nid = f"notif-{str(uuid.uuid4())[:8]}"
    notif = {
        "id": nid,
        "type": type,
        "title": title,
        "body": body,
        "severity": severity,
        "is_read": False,
        "client_id": client_id,
        "user_id": user_id,
        "action_url": action_url,
        "created_at": datetime.utcnow().isoformat(),
    }
    MOCK_NOTIFICATIONS.append(notif)
    _notif_index[nid] = notif
    return notif


def get_notifications(user_id: Optional[str] = None, unread_only: bool = False) -> list[dict]:
    notifications = list(MOCK_NOTIFICATIONS)
    if user_id:
        notifications = [n for n in notifications if n.get("user_id") == user_id or n.get("user_id") is None]
    if unread_only:
        notifications = [n for n in notifications if not n["is_read"]]
    return sorted(notifications, key=lambda n: n["created_at"], reverse=True)


def mark_read(notification_id: str) -> dict | None:
    notif = _notif_index.get(notification_id)
    if notif:
        notif["is_read"] = True
    return notif


def mark_all_read(user_id: Optional[str] = None) -> int:
    count = 0
    for notif in MOCK_NOTIFICATIONS:
        if not notif["is_read"]:
            if user_id is None or notif.get("user_id") == user_id:
                notif["is_read"] = True
                count += 1
    return count


def get_unread_count() -> int:
    return len([n for n in MOCK_NOTIFICATIONS if not n["is_read"]])


def get_notification_stats() -> dict:
    total = len(MOCK_NOTIFICATIONS)
    unread = get_unread_count()
    by_type: dict[str, int] = {}
    for n in MOCK_NOTIFICATIONS:
        by_type[n["type"]] = by_type.get(n["type"], 0) + 1
    return {"total": total, "unread": unread, "by_type": by_type}
