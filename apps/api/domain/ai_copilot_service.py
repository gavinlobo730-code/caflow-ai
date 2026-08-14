"""
Phase 11 AI Copilot Service.

Provides intelligent answers, client intelligence, compliance analysis,
workflow intelligence, relationship intelligence, and executive dashboard
insights.

Context enrichment pattern:
  Before every Groq call the service fetches real data from the relevant
  repositories and injects it into the system-prompt context.  This ensures
  that questions like "which clients are at risk?" are answered from actual
  DB state rather than hallucinated figures.

Uses Groq API (llama-3.3-70b-versatile) with firm-isolated context injection.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Optional

_logger = logging.getLogger("caflow.ai_copilot")

_GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
_MODEL = "llama-3.3-70b-versatile"
_USE_MOCK = not os.environ.get("SUPABASE_URL")

# ── Repository accessors (lazy to avoid circular imports) ──────────────────────


def _get_client_repo():
    from repositories.client_repository import client_repo
    return client_repo


def _get_task_repo():
    from repositories.task_repository import task_repo
    return task_repo


def _get_compliance_records_repo():
    """The canonical compliance_records repo (compliance_tasks/System B is
    being retired, R3.13d). Unlike System B's repo, this one has no
    find_overdue()/find_due_within_days() helpers — filtered in Python here,
    matching the pattern services/compliance_obligation_service.py already uses."""
    from repositories.compliance_records_repository import compliance_records_repo
    return compliance_records_repo


def _overdue_compliance_records(firm_id=None, client_id=None):
    # Pushed server-side (status="Overdue") rather than fetching every status
    # and filtering in Python — the repo's find_all() supports an equality
    # filter on status.
    return _get_compliance_records_repo().find_all(firm_id=firm_id, client_id=client_id, status="Overdue")


def _due_within_days_compliance_records(days, firm_id=None, client_id=None):
    records = _get_compliance_records_repo().find_all(firm_id=firm_id, client_id=client_id)
    return _due_soon_from_records(records, days)


def _due_soon_from_records(records, days):
    from datetime import date
    today_s = date.today().isoformat()
    horizon_s = (date.today() + timedelta(days=days)).isoformat()
    return [
        r for r in records
        if r.get("status") not in ("Filed", "Completed")
        and today_s <= str(r.get("due_date", ""))[:10] <= horizon_s
    ]


def _get_workflow_repo():
    from repositories.workflow_repository import workflow_repo
    return workflow_repo


# ── System prompt ──────────────────────────────────────────────────────────────

_SYSTEM_PROMPT_TEMPLATE = """You are PracticeSync AI Copilot — an expert assistant for Indian Chartered Accountants.
You have deep knowledge of:
- Indian Income Tax Act (IT Act 1961)
- CGST Act 2017 and GST Rules — sections and notifications
- TDS provisions: Sections 192-196D with thresholds and rates
- Companies Act 2013 (MCA compliance, ROC filings)
- SEBI regulations and FEMA provisions
- CA firm operations: client management, compliance calendars, billing

Current financial year: {fy} (1 April {fy_start} to 31 March {fy_end})

Rates and thresholds change with each Finance Act. State which year a rate you
quote applies to, and if you cannot confirm it for the year being asked about,
say so rather than presenting it as current.

Key compliance dates (statutory, stable across years):
- GSTR-1: 11th of following month (Section 37 CGST Act)
- GSTR-3B: 20th of following month (Rule 61 CGST Rules)
- GSTR-9: 31st December (Section 44 CGST Act)
- TDS 26Q/24Q: Q1 31 July, Q2 31 October, Q3 31 January, Q4 31 MAY (Rule 31A IT
  Rules). Q4 is the exception — it is NOT the end of the month following quarter
  end, which would be 30 April.
- Advance Tax: 15 Jun (15%), 15 Sep (45%), 15 Dec (75%), 15 Mar (100%)
- ITR for companies: 31st October; individuals: 31st July
- MCA MGT-7: 60 days from AGM; AOC-4: 30 days from AGM

Rules you MUST follow:
1. Always cite the relevant Section/Rule (e.g., "Section 50 CGST Act")
2. NEVER advise auto-submission to any government portal
3. All monetary amounts in ₹ with clear denomination
4. If uncertain, say so and recommend CA review
5. Keep responses concise and actionable
6. Flag time-sensitive issues prominently"""


def _system_prompt() -> str:
    """The copilot brief, with the financial year resolved at call time.

    The year used to be the literal string "2026-27" in the template. That is
    correct for exactly twelve months and then silently wrong — on 1 April 2027
    the copilot would still introduce itself as working in FY 2026-27, and
    every "this year" answer would be off by one until somebody noticed and
    shipped a deploy. Rendering it from the IST clock costs one function call
    and cannot go stale.

    ist_fy_label() is the same helper the compliance calendar uses, so the
    copilot and the obligations it talks about can never disagree about which
    year it is.
    """
    from core.ist_clock import ist_fy_label

    fy = ist_fy_label()                      # e.g. "2026-27"
    fy_start = int(fy.split("-")[0])         # 2026
    return _SYSTEM_PROMPT_TEMPLATE.format(fy=fy, fy_start=fy_start, fy_end=fy_start + 1)


class AICopilotService:

    def __init__(self) -> None:
        from repositories.ai_copilot_repository import ai_copilot_repo
        self._repo = ai_copilot_repo

    # ── Chat ───────────────────────────────────────────────────────────────────

    async def chat(
        self,
        firm_id: str,
        user_id: str,
        conversation_id: str,
        user_message: str,
        context_type: str = "global",
        context_id: Optional[str] = None,
        allowed_client_ids: Optional[set] = None,
    ) -> dict:
        """Process a user message and return AI response with suggestions.

        allowed_client_ids restricts which clients may appear in the injected
        context (None = firm-wide, for Partner/Manager). Set by the router from
        core.authz.effective_client_ids so the AI never sees clients the caller
        is not authorized to access.
        """
        # Save user message
        self._repo.add_message(firm_id, conversation_id, "user", user_message)

        # Build enriched context payload from real data
        context = self._build_context(firm_id, context_type, context_id, allowed_client_ids)

        # Build message history (last 20 for token efficiency)
        history = self._repo.list_messages(conversation_id, limit=20)
        messages = self._build_messages(history[:-1], context, user_message)

        # Call Groq
        reply_content, tokens_used = await self._call_groq(messages)

        # Save assistant message
        assistant_msg = self._repo.add_message(
            firm_id,
            conversation_id,
            "assistant",
            reply_content,
            tokens_used=tokens_used,
            metadata={"context_type": context_type, "context_id": context_id},
        )

        suggestions = self._generate_suggestions(context_type, user_message, reply_content)

        return {
            "message": assistant_msg,
            "suggested_questions": suggestions,
            "referenced_entities": [],
        }

    def _build_context(
        self,
        firm_id: str,
        context_type: str,
        context_id: Optional[str],
        allowed_client_ids: Optional[set] = None,
    ) -> str:
        """
        Build a firm-specific context string to inject into the AI prompt.

        Fetches real data from repositories so that every Groq call is
        grounded in current DB state.  Failures are silently swallowed so
        that a repo outage never breaks the chat flow.
        """
        lines = [
            f"FIRM: {firm_id}",
            f"DATE: {datetime.utcnow().strftime('%d %B %Y')}",
            f"CONTEXT TYPE: {context_type}",
        ]

        try:
            if context_type in ("global", "client"):
                clients = _get_client_repo().find_all(firm_id=firm_id)
                # M2: restrict context to the caller's authorized clients
                # (None ⇒ firm-wide for Partner/Manager).
                if allowed_client_ids is not None:
                    clients = [c for c in clients if str(c.get("id")) in allowed_client_ids]
                total = len(clients)
                active = len([c for c in clients if c.get("status") == "active"])
                at_risk = len([
                    c for c in clients
                    if c.get("health_score", 100) < 60
                    or c.get("status") in ("at_risk", "critical")
                ])
                critical = len([
                    c for c in clients
                    if c.get("health_score", 100) < 40
                    or c.get("status") == "critical"
                ])
                lines += [
                    f"TOTAL CLIENTS: {total}",
                    f"ACTIVE CLIENTS: {active}",
                    f"AT-RISK CLIENTS: {at_risk}",
                    f"CRITICAL CLIENTS: {critical}",
                ]

                if context_type == "client" and context_id:
                    # M2: never inject a client the caller isn't authorized for.
                    if allowed_client_ids is not None and str(context_id) not in allowed_client_ids:
                        client = None
                    else:
                        client = _get_client_repo().find_by_id(context_id)
                    if client:
                        lines += [
                            f"CLIENT NAME: {client.get('client_name', 'Unknown')}",
                            f"GSTIN: {client.get('gstin', 'N/A')}",
                            f"PAN: {client.get('pan', 'N/A')}",
                            f"CLIENT STATUS: {client.get('status', 'unknown')}",
                            f"HEALTH SCORE: {client.get('health_score', 'N/A')}",
                            f"LIFECYCLE STAGE: {client.get('lifecycle_stage', 'N/A')}",
                        ]
                        # Compliance records for this client
                        try:
                            comp_records = _get_compliance_records_repo().find_all(
                                firm_id=firm_id, client_id=context_id
                            )
                            overdue_ct = [t for t in comp_records if t.get("status") == "Overdue"]
                            pending_ct = [t for t in comp_records if t.get("status") == "Not Started"]
                            lines += [
                                f"CLIENT OVERDUE COMPLIANCE TASKS: {len(overdue_ct)}",
                                f"CLIENT PENDING COMPLIANCE TASKS: {len(pending_ct)}",
                            ]
                        except Exception:
                            pass
        except Exception:
            pass

        try:
            if context_type in ("global", "compliance"):
                overdue_tasks = _get_task_repo().find_overdue(firm_id=firm_id)
                lines.append(f"OVERDUE TASKS: {len(overdue_tasks)}")
                # One fetch, not two — comp_overdue and due_soon are both
                # derived from the same result set instead of each doing its
                # own full-history find_all() for the same firm.
                comp_records = _get_compliance_records_repo().find_all(firm_id=firm_id)
                comp_overdue = [r for r in comp_records if r.get("status") == "Overdue"]
                due_soon = _due_soon_from_records(comp_records, 7)
                lines.append(f"OVERDUE COMPLIANCE FILINGS: {len(comp_overdue)}")
                lines.append(f"COMPLIANCE FILINGS DUE IN 7 DAYS: {len(due_soon)}")
        except Exception:
            pass

        try:
            if context_type in ("global", "workflow"):
                wf_repo = _get_workflow_repo()
                failures = wf_repo.list_failures(firm_id, resolved=False, limit=10)
                approvals = wf_repo.list_approvals(firm_id, status="pending", limit=10)
                now_iso = datetime.utcnow().isoformat()
                overdue_approvals = [
                    a for a in approvals
                    if a.get("due_at") and a["due_at"] < now_iso
                ]
                lines += [
                    f"UNRESOLVED WORKFLOW FAILURES: {len(failures)}",
                    f"PENDING APPROVALS: {len(approvals)}",
                    f"OVERDUE APPROVALS: {len(overdue_approvals)}",
                ]
        except Exception:
            pass

        return "\n".join(lines)

    def _build_messages(
        self, history: list[dict], context: str, user_message: str
    ) -> list[dict]:
        messages = [{"role": "system", "content": f"{_system_prompt()}\n\n{context}"}]
        for msg in history[-8:]:
            if msg["role"] in ("user", "assistant"):
                messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": user_message})
        return messages

    async def _call_groq(self, messages: list[dict]) -> tuple[str, int]:
        """Call Groq API. Returns (reply_text, tokens_used)."""
        if not _GROQ_API_KEY:
            last_user = next(
                (m["content"] for m in reversed(messages) if m["role"] == "user"), ""
            )
            return self._mock_response(last_user), 0
        try:
            import httpx

            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {_GROQ_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": _MODEL,
                        "messages": messages,
                        "max_tokens": 2048,
                        "temperature": 0.3,
                    },
                )
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                tokens = data.get("usage", {}).get("total_tokens", 0)
                return content, tokens
        except Exception as exc:
            _logger.error("Groq API error: %s", exc)
            last_user = next(
                (m["content"] for m in reversed(messages) if m["role"] == "user"), ""
            )
            return self._mock_response(last_user), 0

    def _mock_response(self, question: str) -> str:
        q = question.lower()
        if "risk" in q:
            return (
                "Based on current data, clients with health scores below 60 or overdue GSTR-3B/TDS "
                "filings are at elevated risk. Review the compliance calendar and generate individual "
                "client risk summaries. Interest accrues at 18% p.a. under Section 50 CGST Act."
            )
        if "gst" in q or "gstr" in q:
            return (
                "GSTR-3B is due on the 20th of each following month (Rule 61 CGST Rules). "
                "GSTR-1 is due on the 11th (Section 37 CGST Act). "
                "For annual reconciliation, GSTR-9 is due December 31st (Section 44 CGST Act)."
            )
        if "tds" in q:
            return (
                "TDS returns (Form 26Q for non-salary, 24Q for salary) are due on the 31st of the month "
                "following each quarter end (Rule 31A IT Rules). Ensure Form 16/16A is issued within 15 "
                "days of the due date."
            )
        if "health" in q or "score" in q:
            return (
                "Client health is scored across 7 dimensions: compliance, accounting, documents, "
                "responsiveness, relationship risk, financial risk, and engagement. "
                "Scores below 60 are at-risk; below 40 are critical."
            )
        if "onboarding" in q:
            return (
                "Current onboarding bottlenecks typically occur at KYC document collection and engagement "
                "letter approval. Assign dedicated follow-up tasks and enable the onboarding workflow automation."
            )
        return (
            "I'm your PracticeSync AI Copilot. I can help you with client compliance status, GST/TDS filings, "
            "health scores, workflow analysis, and more. What would you like to know?"
        )

    def _generate_suggestions(
        self, context_type: str, question: str, answer: str
    ) -> list[str]:
        from models.ai_copilot import (
            GLOBAL_SUGGESTED_QUESTIONS,
            CLIENT_SUGGESTED_QUESTIONS,
            COMPLIANCE_SUGGESTED_QUESTIONS,
        )
        if context_type == "client":
            return CLIENT_SUGGESTED_QUESTIONS[:4]
        if context_type == "compliance":
            return COMPLIANCE_SUGGESTED_QUESTIONS[:4]
        return GLOBAL_SUGGESTED_QUESTIONS[:4]

    # ── Client Intelligence ────────────────────────────────────────────────────

    async def get_client_intelligence(self, firm_id: str, client_id: str) -> dict:
        """Generate comprehensive AI intelligence for a single client."""
        cached = self._repo.get_summary(firm_id, "client", client_id)
        if cached:
            return cached

        now = datetime.utcnow()

        # Fetch real client data before calling Groq
        client_name = client_id
        client_pan = "N/A"
        client_gstin = "N/A"
        client_status = "unknown"
        client_health = "N/A"
        overdue_count = 0
        pending_count = 0
        compliance_types: list[str] = []

        try:
            client = _get_client_repo().find_by_id(client_id, firm_id=firm_id)
            if client:
                client_name = client.get("client_name", client_id)
                client_pan = client.get("pan", "N/A")
                client_gstin = client.get("gstin", "N/A")
                client_status = client.get("status", "unknown")
                client_health = client.get("health_score", "N/A")
        except Exception:
            pass

        try:
            comp_records = _get_compliance_records_repo().find_all(
                firm_id=firm_id, client_id=client_id
            )
            overdue_count = len([t for t in comp_records if t.get("status") == "Overdue"])
            pending_count = len([t for t in comp_records if t.get("status") == "Not Started"])
            compliance_types = list({t.get("compliance_type", "") for t in comp_records if t.get("compliance_type")})
        except Exception:
            pass

        prompt = f"""Generate a comprehensive practice intelligence report for the following client.

CLIENT DETAILS:
- Name: {client_name}
- PAN: {client_pan}
- GSTIN: {client_gstin}
- Status: {client_status}
- Health Score: {client_health}/100
- Overdue compliance tasks: {overdue_count}
- Pending compliance tasks: {pending_count}
- Active compliance types: {', '.join(compliance_types) if compliance_types else 'Not on record'}

Include:
1. Profile summary (entity type, services engaged)
2. Compliance summary (filings status, overdue items)
3. Health assessment (risks and signals)
4. Risk summary (financial, compliance, relationship risks)
5. Opportunity summary (tax savings, advisory opportunities)
6. Top 3 recommended actions

Format as a structured professional report. Cite relevant sections of IT Act / CGST Act."""

        messages = [
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": prompt},
        ]
        content, tokens = await self._call_groq(messages)

        summary = self._repo.upsert_summary(
            firm_id,
            "client",
            client_id,
            {
                "title": "Client Intelligence Report",
                "content": content,
                "key_points": [
                    f"Health score: {client_health}",
                    f"{overdue_count} overdue compliance tasks",
                    f"{pending_count} pending tasks",
                    "Opportunities flagged",
                ],
                "metadata": {
                    "client_id": client_id,
                    "tokens_used": tokens,
                    "client_name": client_name,
                },
                "model_used": _MODEL,
                "expires_at": (now + timedelta(hours=6)).isoformat(),
            },
        )
        return summary

    # ── Compliance Intelligence ────────────────────────────────────────────────

    async def get_compliance_intelligence(self, firm_id: str) -> dict:
        cached = self._repo.get_summary(firm_id, "compliance")
        if cached:
            return cached

        now = datetime.utcnow()

        # Fetch real compliance data
        overdue_tasks: list[dict] = []
        due_soon_tasks: list[dict] = []
        all_tasks: list[dict] = []

        try:
            # One fetch instead of three — all_tasks, overdue_tasks and
            # due_soon_tasks were each independently re-fetching the firm's
            # entire compliance_records history.
            all_tasks = _get_compliance_records_repo().find_all(firm_id=firm_id)
            overdue_tasks = [r for r in all_tasks if r.get("status") == "Overdue"]
            due_soon_tasks = _due_soon_from_records(all_tasks, 14)
        except Exception:
            pass

        # Unique clients with overdue filings
        overdue_clients = list({t.get("client_id") for t in overdue_tasks if t.get("client_id")})
        due_soon_by_type: dict[str, int] = {}
        for t in due_soon_tasks:
            ct = t.get("compliance_type", "Other")
            due_soon_by_type[ct] = due_soon_by_type.get(ct, 0) + 1

        compliance_score = max(0, 100 - len(overdue_tasks) * 5)

        prompt = f"""Analyse the firm's current compliance status and provide actionable insights.

REAL DATA AS OF {now.strftime('%d %B %Y')}:
- Total compliance tasks on record: {len(all_tasks)}
- Overdue filings: {len(overdue_tasks)} (affecting {len(overdue_clients)} clients)
- Filings due in next 14 days: {len(due_soon_tasks)}
- Breakdown by type (due soon): {due_soon_by_type if due_soon_by_type else 'None'}
- Estimated compliance health score: {compliance_score}/100

Provide:
1. Upcoming risks (filings due in next 14 days)
2. Filing bottlenecks (delayed or missing submissions)
3. Missing documents across clients
4. Overall compliance health score assessment
5. Clients requiring immediate action

Cite CGST Act / IT Act sections where relevant."""

        messages = [
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": prompt},
        ]
        content, tokens = await self._call_groq(messages)

        return self._repo.upsert_summary(
            firm_id,
            "compliance",
            None,
            {
                "title": "Compliance Intelligence Report",
                "content": content,
                "key_points": [
                    f"{len(overdue_tasks)} overdue filings",
                    f"{len(due_soon_tasks)} due in 14 days",
                    f"{len(overdue_clients)} clients require immediate attention",
                    f"Compliance health score: {compliance_score}/100",
                ],
                "metadata": {"tokens_used": tokens, "overdue_count": len(overdue_tasks)},
                "model_used": _MODEL,
                "expires_at": (now + timedelta(hours=2)).isoformat(),
            },
        )

    # ── Workflow Intelligence ──────────────────────────────────────────────────

    async def get_workflow_intelligence(self, firm_id: str) -> dict:
        wf_repo = _get_workflow_repo()

        failures: list[dict] = []
        approvals: list[dict] = []
        analytics: list[dict] = []

        try:
            failures = wf_repo.list_failures(firm_id, resolved=False)
            approvals = wf_repo.list_approvals(firm_id, status="pending")
            analytics = wf_repo.get_analytics(firm_id)
        except Exception:
            pass

        failing = [a for a in analytics if a.get("failed", 0) > 0]
        bottleneck_names = [
            a["template_name"]
            for a in analytics
            if a.get("avg_duration_ms") and a["avg_duration_ms"] > 3_600_000
        ]
        now_iso = datetime.utcnow().isoformat()
        overdue_approvals = [
            a for a in approvals
            if a.get("due_at") and a["due_at"] < now_iso
        ]

        # Top recurring failure reasons
        failure_reasons: dict[str, int] = {}
        for f in failures:
            reason = f.get("error_type") or f.get("step_name") or "unknown"
            failure_reasons[reason] = failure_reasons.get(reason, 0) + 1

        prompt = f"""Analyse workflow automation performance and provide recommendations.

REAL DATA AS OF {datetime.utcnow().strftime('%d %B %Y')}:
- Total workflow types: {len(analytics)}
- Failing workflows: {len(failing)} ({', '.join(a['template_name'] for a in failing[:3])})
- Pending approvals: {len(approvals)} ({len(overdue_approvals)} overdue)
- Unresolved failures: {len(failures)}
- Slow workflows (>1h avg): {', '.join(bottleneck_names) if bottleneck_names else 'None'}
- Top failure reasons: {failure_reasons if failure_reasons else 'None recorded'}

Provide:
1. Root cause analysis for top failures
2. Approval bottleneck recommendations
3. Workflow optimisation suggestions
4. Priority actions"""

        messages = [
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": prompt},
        ]
        content, tokens = await self._call_groq(messages)
        now = datetime.utcnow()
        return {
            "firm_id": firm_id,
            "failing_workflows": failing[:5],
            "overdue_approvals": overdue_approvals[:5],
            "recurring_bottlenecks": [{"name": n} for n in bottleneck_names[:3]],
            "recommendations": self._repo.list_recommendations(firm_id, rec_type="workflow")[:3],
            "ai_analysis": content,
            "generated_at": now.isoformat(),
        }

    # ── Relationship Intelligence ──────────────────────────────────────────────

    async def get_relationship_intelligence(self, firm_id: str) -> dict:
        # Fetch client data to ground the analysis
        clients: list[dict] = []
        multi_entity_pans: list[str] = []
        duplicate_email_domains: list[str] = []

        try:
            clients = _get_client_repo().find_all(firm_id=firm_id)
            # Detect PAN cross-matches (same individual directing multiple entities)
            pan_counts: dict[str, int] = {}
            for c in clients:
                pan = c.get("pan")
                if pan:
                    pan_counts[pan] = pan_counts.get(pan, 0) + 1
            multi_entity_pans = [pan for pan, count in pan_counts.items() if count > 1]
            # Email domain clustering (proxy for related parties)
            domain_counts: dict[str, int] = {}
            for c in clients:
                email = c.get("email") or ""
                if "@" in email:
                    domain = email.split("@")[1].lower()
                    if domain not in ("gmail.com", "yahoo.com", "hotmail.com", "outlook.com"):
                        domain_counts[domain] = domain_counts.get(domain, 0) + 1
            duplicate_email_domains = [d for d, count in domain_counts.items() if count > 1]
        except Exception:
            pass

        prompt = f"""Analyse cross-client relationship structures and identify risks.

REAL DATA AS OF {datetime.utcnow().strftime('%d %B %Y')}:
- Total clients: {len(clients)}
- PANs appearing across multiple entities: {len(multi_entity_pans)} (potential related-party risk)
- Shared corporate email domains: {len(duplicate_email_domains)} (possible group structures)

Analyse and provide:
1. Ownership concentration risks (circular ownership, shell structures)
2. Director conflicts (same individual directing competing businesses)
3. PAN/email cross-matches indicating undisclosed related parties
4. Potential FEMA/SEBI/IT Act disclosure violations
5. Recommended compliance actions

Cite relevant sections of Companies Act 2013 and IT Act."""

        messages = [
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": prompt},
        ]
        content, tokens = await self._call_groq(messages)
        now = datetime.utcnow()
        return {
            "firm_id": firm_id,
            "ownership_risks": [],
            "cross_client_conflicts": [
                {"type": "multi_entity_pan", "count": len(multi_entity_pans)}
            ] if multi_entity_pans else [],
            "high_risk_entities": [],
            "recommendations": self._repo.list_recommendations(
                firm_id, rec_type="relationship"
            )[:3],
            "ai_analysis": content,
            "generated_at": now.isoformat(),
        }

    # ── Executive Dashboard ────────────────────────────────────────────────────

    async def get_executive_dashboard(self, firm_id: str) -> dict:
        cached = self._repo.get_summary(firm_id, "executive")
        if cached:
            return cached

        now = datetime.utcnow()

        # ── Gather real data ────────────────────────────────────────────────
        clients: list[dict] = []
        tasks_overdue = 0
        wf_failures = 0
        pending_approvals = 0
        active_automations = 0
        all_tasks: list[dict] = []

        try:
            clients = _get_client_repo().find_all(firm_id=firm_id)
        except Exception:
            pass

        try:
            wf_repo = _get_workflow_repo()
            failures = wf_repo.list_failures(firm_id, resolved=False, limit=100)
            wf_failures = len(failures)
            approvals = wf_repo.list_approvals(firm_id, status="pending", limit=100)
            pending_approvals = len(approvals)
            templates = wf_repo.list_templates(firm_id, is_active=True)
            active_automations = len([t for t in templates if t.get("is_active")])
        except Exception:
            pass

        try:
            all_tasks = _get_task_repo().find_overdue(firm_id=firm_id)
            tasks_overdue = len(all_tasks)
        except Exception:
            pass

        # ── Client risk breakdown ───────────────────────────────────────────
        critical = len([
            c for c in clients
            if c.get("health_score", 100) < 40 or c.get("status") == "critical"
        ])
        at_risk = len([
            c for c in clients
            if (40 <= c.get("health_score", 100) < 70)
            or c.get("status") == "at_risk"
        ])
        healthy = max(0, len(clients) - critical - at_risk)

        # ── Churn signals ───────────────────────────────────────────────────
        churn_signals: list[dict] = []
        for c in clients:
            score = c.get("health_score", 100)
            if score < 50:
                churn_signals.append({
                    "client_name": c.get("client_name", "Unknown"),
                    "signal": f"Health score {score} — below threshold (50)",
                    "risk": "high" if score < 30 else "medium",
                })
        churn_signals = sorted(
            churn_signals, key=lambda x: 0 if x["risk"] == "high" else 1
        )[:5]

        # ── Growth opportunities ────────────────────────────────────────────
        growth_opportunities: list[dict] = []
        inactive = [c for c in clients if c.get("status") == "inactive"]
        if inactive:
            # All monetary values stored in integer paise (₹5,000 = 500000 paise)
            growth_opportunities.append({
                "type": "reactivation",
                "description": f"{len(inactive)} inactive clients could be re-engaged",
                "estimated_value_paise": len(inactive) * 500_000,  # ₹5,000 per client
            })
        # Clients without GST registration may be candidates for advisory
        no_gst = [
            c for c in clients
            if not c.get("gstin") and c.get("status") == "active"
        ]
        if no_gst:
            growth_opportunities.append({
                "type": "advisory",
                "description": f"{len(no_gst)} active clients without GSTIN — GST advisory opportunity",
                "estimated_value_paise": len(no_gst) * 300_000,  # ₹3,000 per client
            })

        # ── Health metrics ──────────────────────────────────────────────────
        scores = [c["health_score"] for c in clients if c.get("health_score") is not None]
        avg_score = int(sum(scores) / len(scores)) if scores else 75
        compliance_coverage = min(100, max(0, 100 - tasks_overdue * 5))

        # ── AI summary (uses real numbers) ──────────────────────────────────
        summary_prompt = f"""Summarise this CA firm's current operational status for an executive in 3 concise sentences.
Be specific with numbers. Highlight the most urgent issue first.

Firm data as of {now.strftime('%d %B %Y')}:
- Total clients: {len(clients)} | Critical: {critical} | At-risk: {at_risk} | Healthy: {healthy}
- Overdue tasks: {tasks_overdue}
- Workflow failures: {wf_failures} | Pending approvals: {pending_approvals}
- Active automations: {active_automations}
- Average client health score: {avg_score}/100
- Compliance coverage: {compliance_coverage}%"""

        ai_summary = (
            f"Firm has {len(clients)} clients with {critical} critical and {at_risk} at-risk. "
            f"{tasks_overdue} overdue tasks require attention."
        )
        try:
            messages = [
                {"role": "system", "content": _system_prompt()},
                {"role": "user", "content": summary_prompt},
            ]
            ai_summary_raw, _ = await self._call_groq(messages)
            if ai_summary_raw:
                ai_summary = ai_summary_raw
        except Exception:
            pass

        recs = self._repo.list_recommendations(firm_id, status="pending", limit=10)
        critical_recs = [r for r in recs if r["priority"] == "critical"]

        dashboard_data = {
            "firm_id": firm_id,
            "revenue_insights": {
                "outstanding_invoices": 0,
                "outstanding_amount_paise": 0,
                "avg_collection_days": 0,
                "billing_trend": "stable",
            },
            "capacity_insights": {
                "team_utilisation_percent": min(100, tasks_overdue * 5 + 50),
                "overloaded_staff": 0,
                "underutilised_staff": 0,
                "avg_tasks_per_staff": 0,
            },
            "client_risk_insights": {
                "critical_clients": critical,
                "at_risk_clients": at_risk,
                "healthy_clients": healthy,
                "compliance_failures": tasks_overdue,
            },
            "churn_signals": churn_signals,
            "growth_opportunities": growth_opportunities,
            "firm_health_summary": {
                "overall_score": avg_score,
                "compliance_coverage": compliance_coverage,
                "active_automations": active_automations,
                "pending_approvals": pending_approvals,
                "ai_recommendations_pending": len(recs),
                "critical_actions": critical + wf_failures,
            },
            "ai_summary": ai_summary,
            "generated_at": now.isoformat(),
        }

        high_recs = [r for r in recs if r["priority"] == "high"]
        self._repo.upsert_summary(
            firm_id,
            "executive",
            None,
            {
                "title": "Executive Intelligence Dashboard",
                "content": ai_summary,
                "key_points": [
                    f"{len(critical_recs)} critical recommendations",
                    f"{len(high_recs)} high-priority items",
                    f"{len(clients)} total clients, {critical} critical",
                    f"{tasks_overdue} overdue tasks",
                ],
                "metadata": dashboard_data,
                "model_used": _MODEL,
                "expires_at": (now + timedelta(hours=1)).isoformat(),
            },
        )
        return dashboard_data

    # ── Recommendations ────────────────────────────────────────────────────────

    def list_recommendations(self, firm_id: str, **kwargs) -> list[dict]:
        return self._repo.list_recommendations(firm_id, **kwargs)

    def act_on_recommendation(
        self,
        firm_id: str,
        rec_id: str,
        action: str,
        user_id: str,
        snooze_days: Optional[int] = None,
    ) -> Optional[dict]:
        snooze_until = None
        if action == "snooze" and snooze_days:
            snooze_until = (
                datetime.utcnow() + timedelta(days=snooze_days)
            ).isoformat()
            status = "snoozed"
        elif action == "accept":
            status = "accepted"
        else:
            status = "dismissed"
        return self._repo.update_recommendation_status(
            firm_id, rec_id, status, user_id, snooze_until
        )


ai_copilot_service = AICopilotService()
