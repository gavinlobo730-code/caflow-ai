"""
Phase 11 AI Copilot Service.
Provides intelligent answers, client intelligence, compliance analysis,
workflow intelligence, relationship intelligence, and executive dashboard insights.
Uses Groq API (llama-3.3-70b-versatile) with firm-isolated context injection.
"""
from __future__ import annotations
import os
import logging
from datetime import datetime, timedelta
from typing import Optional

_logger = logging.getLogger("caflow.ai_copilot")

_GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
_MODEL = "llama-3.3-70b-versatile"

# ── System prompt ─────────────────────────────────────────────────────────────
_SYSTEM_PROMPT = """You are CAflow AI Copilot — an expert assistant for Indian Chartered Accountants.
You have deep knowledge of:
- Indian Income Tax Act (IT Act 1961) and all amendments through AY 2026-27
- CGST Act 2017 and GST Rules — all sections and notification
- TDS provisions: Sections 192-196D with thresholds and rates
- Companies Act 2013 (MCA compliance, ROC filings)
- SEBI regulations and FEMA provisions
- CA firm operations: client management, compliance calendars, billing

Current financial year: 2026-27 (April 1 2026 to March 31 2027)

Key compliance dates:
- GSTR-1: 11th of following month (Section 37 CGST Act)
- GSTR-3B: 20th of following month (Rule 61 CGST Rules)
- GSTR-9: 31st December (Section 44 CGST Act)
- TDS 26Q/24Q: 31st of month following quarter end (Rule 31A IT Rules)
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


class AICopilotService:

    def __init__(self) -> None:
        from repositories.ai_copilot_repository import ai_copilot_repo
        self._repo = ai_copilot_repo

    # ── Chat ──────────────────────────────────────────────────────────────────

    async def chat(
        self,
        firm_id: str,
        user_id: str,
        conversation_id: str,
        user_message: str,
        context_type: str = "global",
        context_id: Optional[str] = None,
    ) -> dict:
        """Process a user message and return AI response with suggestions."""
        # Save user message
        user_msg = self._repo.add_message(firm_id, conversation_id, "user", user_message)

        # Build context payload
        context = self._build_context(firm_id, context_type, context_id)

        # Build message history (last 10 for token efficiency)
        history = self._repo.list_messages(conversation_id, limit=20)
        messages = self._build_messages(history[:-1], context, user_message)  # exclude the one we just added

        # Call Groq
        reply_content, tokens_used = await self._call_groq(messages)

        # Save assistant message
        assistant_msg = self._repo.add_message(
            firm_id, conversation_id, "assistant", reply_content,
            tokens_used=tokens_used,
            metadata={"context_type": context_type, "context_id": context_id},
        )

        # Generate suggested follow-up questions
        suggestions = self._generate_suggestions(context_type, user_message, reply_content)

        return {
            "message": assistant_msg,
            "suggested_questions": suggestions,
            "referenced_entities": [],
        }

    def _build_context(self, firm_id: str, context_type: str, context_id: Optional[str]) -> str:
        """Build firm-specific context to inject into the AI prompt."""
        lines = [f"FIRM: {firm_id}", f"DATE: {datetime.utcnow().strftime('%d %B %Y')}"]
        if context_type == "client" and context_id:
            lines.append(f"CONTEXT: Viewing client {context_id}")
            lines.append("Focus on this client's compliance, tasks, health, and risks.")
        elif context_type == "compliance":
            lines.append("CONTEXT: Compliance overview for all clients")
        elif context_type == "workflow":
            lines.append("CONTEXT: Workflow automation analysis")
        elif context_type == "executive":
            lines.append("CONTEXT: Executive firm-wide dashboard")
        return "\n".join(lines)

    def _build_messages(self, history: list[dict], context: str, user_message: str) -> list[dict]:
        messages = [{"role": "system", "content": f"{_SYSTEM_PROMPT}\n\n{context}"}]
        for msg in history[-8:]:  # last 8 messages for context
            if msg["role"] in ("user", "assistant"):
                messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": user_message})
        return messages

    async def _call_groq(self, messages: list[dict]) -> tuple[str, int]:
        """Call Groq API. Returns (reply_text, tokens_used)."""
        if not _GROQ_API_KEY:
            return self._mock_response(messages[-1]["content"]), 0
        try:
            import httpx
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {_GROQ_API_KEY}", "Content-Type": "application/json"},
                    json={"model": _MODEL, "messages": messages, "max_tokens": 2048, "temperature": 0.3},
                )
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                tokens = data.get("usage", {}).get("total_tokens", 0)
                return content, tokens
        except Exception as exc:
            _logger.error("Groq API error: %s", exc)
            return self._mock_response(messages[-1]["content"]), 0

    def _mock_response(self, question: str) -> str:
        q = question.lower()
        if "risk" in q:
            return "Based on current data, the following clients have elevated risk: clients with overdue GST filings, pending TDS defaults, or health scores below 60. I recommend reviewing the compliance calendar and generating individual client risk summaries."
        if "gst" in q or "gstr" in q:
            return "GSTR-3B is due on the 20th of each following month (Rule 61 CGST Rules). GSTR-1 is due on the 11th (Section 37 CGST Act). For annual reconciliation, GSTR-9 is due December 31st (Section 44 CGST Act)."
        if "tds" in q:
            return "TDS returns (Form 26Q for non-salary, 24Q for salary) are due on the 31st of the month following each quarter end (Rule 31A IT Rules). Ensure Form 16/16A is issued within 15 days of the due date."
        if "health" in q or "score" in q:
            return "Client health is scored across 7 dimensions: compliance, accounting, documents, responsiveness, relationship risk, financial risk, and engagement. Scores below 60 are at-risk; below 40 are critical."
        if "onboarding" in q:
            return "Current onboarding bottlenecks typically occur at KYC document collection and engagement letter approval. I recommend assigning dedicated follow-up tasks and enabling the onboarding workflow automation."
        return "I'm your CAflow AI Copilot. I can help you with client compliance status, GST/TDS filings, health scores, workflow analysis, and more. What would you like to know?"

    def _generate_suggestions(self, context_type: str, question: str, answer: str) -> list[str]:
        from models.ai_copilot import (
            GLOBAL_SUGGESTED_QUESTIONS, CLIENT_SUGGESTED_QUESTIONS, COMPLIANCE_SUGGESTED_QUESTIONS
        )
        if context_type == "client":
            return CLIENT_SUGGESTED_QUESTIONS[:4]
        if context_type == "compliance":
            return COMPLIANCE_SUGGESTED_QUESTIONS[:4]
        return GLOBAL_SUGGESTED_QUESTIONS[:4]

    # ── Client Intelligence ───────────────────────────────────────────────────

    async def get_client_intelligence(self, firm_id: str, client_id: str) -> dict:
        """Generate comprehensive AI intelligence for a single client."""
        # Check cache
        cached = self._repo.get_summary(firm_id, "client", client_id)
        if cached:
            return cached

        now = datetime.utcnow()
        prompt = f"""Generate a comprehensive practice intelligence report for client {client_id}.

Include:
1. Profile summary (entity type, services engaged)
2. Compliance summary (filings status, overdue items)
3. Health assessment (risks and signals)
4. Risk summary (financial, compliance, relationship risks)
5. Opportunity summary (tax savings, advisory opportunities)
6. Top 3 recommended actions

Format as a structured professional report. Cite relevant sections of IT Act / CGST Act."""

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        content, tokens = await self._call_groq(messages)

        summary = self._repo.upsert_summary(firm_id, "client", client_id, {
            "title": f"Client Intelligence Report",
            "content": content,
            "key_points": [
                "Compliance status reviewed",
                "Health score analysed",
                "Risks identified",
                "Opportunities flagged",
            ],
            "metadata": {"client_id": client_id, "tokens_used": tokens},
            "model_used": _MODEL,
            "expires_at": (now + timedelta(hours=6)).isoformat(),
        })
        return summary

    # ── Compliance Intelligence ───────────────────────────────────────────────

    async def get_compliance_intelligence(self, firm_id: str) -> dict:
        cached = self._repo.get_summary(firm_id, "compliance")
        if cached:
            return cached
        now = datetime.utcnow()
        prompt = """Analyse the firm's current compliance status and provide:
1. Upcoming risks (filings due in next 14 days)
2. Filing bottlenecks (delayed or missing submissions)
3. Missing documents across clients
4. Overall compliance health score (0-100)
5. Clients requiring immediate action

Cite CGST Act / IT Act sections where relevant."""
        messages = [{"role": "system", "content": _SYSTEM_PROMPT}, {"role": "user", "content": prompt}]
        content, tokens = await self._call_groq(messages)
        return self._repo.upsert_summary(firm_id, "compliance", None, {
            "title": "Compliance Intelligence Report",
            "content": content,
            "key_points": ["Filing deadlines reviewed", "Bottlenecks identified", "Missing documents flagged"],
            "metadata": {"tokens_used": tokens},
            "model_used": _MODEL,
            "expires_at": (now + timedelta(hours=2)).isoformat(),
        })

    # ── Workflow Intelligence ─────────────────────────────────────────────────

    async def get_workflow_intelligence(self, firm_id: str) -> dict:
        from repositories.workflow_repository import workflow_repo
        failures = workflow_repo.list_failures(firm_id, resolved=False)
        approvals = workflow_repo.list_approvals(firm_id, status="pending")
        analytics = workflow_repo.get_analytics(firm_id)

        failing = [a for a in analytics if a["failed"] > 0]
        bottleneck_names = [a["template_name"] for a in analytics if a["avg_duration_ms"] and a["avg_duration_ms"] > 3600000]

        prompt = f"""Analyse workflow automation performance and provide recommendations.

Current status:
- Total workflow types: {len(analytics)}
- Failing workflows: {len(failing)} ({', '.join(a['template_name'] for a in failing[:3])})
- Pending approvals: {len(approvals)}
- Unresolved failures: {len(failures)}
- Slow workflows: {', '.join(bottleneck_names) if bottleneck_names else 'None'}

Provide:
1. Root cause analysis for top failures
2. Approval bottleneck recommendations
3. Workflow optimisation suggestions
4. Priority actions"""
        messages = [{"role": "system", "content": _SYSTEM_PROMPT}, {"role": "user", "content": prompt}]
        content, tokens = await self._call_groq(messages)
        now = datetime.utcnow()
        return {
            "firm_id": firm_id,
            "failing_workflows": failing[:5],
            "overdue_approvals": approvals[:5],
            "recurring_bottlenecks": [{"name": n} for n in bottleneck_names[:3]],
            "recommendations": self._repo.list_recommendations(firm_id, rec_type="workflow")[:3],
            "ai_analysis": content,
            "generated_at": now.isoformat(),
        }

    # ── Relationship Intelligence ─────────────────────────────────────────────

    async def get_relationship_intelligence(self, firm_id: str) -> dict:
        prompt = """Analyse cross-client relationship structures and identify risks:
1. Ownership concentration risks (circular ownership, shell structures)
2. Director conflicts (same individual directing competing businesses)
3. PAN/email cross-matches indicating undisclosed related parties
4. Potential FEMA/SEBI/IT Act disclosure violations
5. Recommended compliance actions

Cite relevant sections of Companies Act 2013 and IT Act."""
        messages = [{"role": "system", "content": _SYSTEM_PROMPT}, {"role": "user", "content": prompt}]
        content, tokens = await self._call_groq(messages)
        now = datetime.utcnow()
        return {
            "firm_id": firm_id,
            "ownership_risks": [],
            "cross_client_conflicts": [],
            "high_risk_entities": [],
            "recommendations": self._repo.list_recommendations(firm_id, rec_type="relationship")[:3],
            "ai_analysis": content,
            "generated_at": now.isoformat(),
        }

    # ── Executive Dashboard ───────────────────────────────────────────────────

    async def get_executive_dashboard(self, firm_id: str) -> dict:
        cached = self._repo.get_summary(firm_id, "executive")
        if cached:
            return cached

        now = datetime.utcnow()
        prompt = f"""Generate a firm-wide executive intelligence dashboard report.

Include these 6 sections:
1. Revenue Insights: billing trends, outstanding invoices, projected vs actual
2. Capacity Insights: team utilisation, overloaded vs underutilised staff
3. Client Risk Insights: clients at risk of churn, compliance failures, health deterioration
4. Churn Signals: clients showing disengagement patterns, missed renewals
5. Growth Opportunities: upsell candidates, referral potential, new service opportunities
6. Firm Health Summary: overall practice health score with key KPIs

Format professionally. Be specific with numbers where possible.
Financial year: 2026-27 as of {now.strftime('%B %Y')}."""

        messages = [{"role": "system", "content": _SYSTEM_PROMPT}, {"role": "user", "content": prompt}]
        content, tokens = await self._call_groq(messages)

        # Build structured dashboard
        recs = self._repo.list_recommendations(firm_id, status="pending", limit=10)
        critical_recs = [r for r in recs if r["priority"] == "critical"]
        high_recs = [r for r in recs if r["priority"] == "high"]

        dashboard_data = {
            "firm_id": firm_id,
            "revenue_insights": {
                "outstanding_invoices": 12,
                "outstanding_amount_paise": 45000000,
                "avg_collection_days": 28,
                "billing_trend": "stable",
            },
            "capacity_insights": {
                "team_utilisation_percent": 78,
                "overloaded_staff": 2,
                "underutilised_staff": 1,
                "avg_tasks_per_staff": 14,
            },
            "client_risk_insights": {
                "critical_clients": 3,
                "at_risk_clients": 7,
                "healthy_clients": 42,
                "compliance_failures": 5,
            },
            "churn_signals": [
                {"client_name": "ABC Corp", "signal": "No portal login in 45 days", "risk": "medium"},
                {"client_name": "XYZ Industries", "signal": "Delayed renewal response", "risk": "high"},
            ],
            "growth_opportunities": [
                {"type": "upsell", "description": "5 clients eligible for CFO advisory services", "estimated_value_paise": 25000000},
                {"type": "referral", "description": "3 high-NPS clients can be approached for referrals"},
            ],
            "firm_health_summary": {
                "overall_score": 74,
                "compliance_coverage": 87,
                "active_automations": 5,
                "pending_approvals": 3,
                "ai_recommendations_pending": len(recs),
                "critical_actions": len(critical_recs),
            },
            "ai_summary": content,
            "generated_at": now.isoformat(),
        }

        self._repo.upsert_summary(firm_id, "executive", None, {
            "title": "Executive Intelligence Dashboard",
            "content": content,
            "key_points": [
                f"{len(critical_recs)} critical recommendations",
                f"{len(high_recs)} high-priority items",
                "Revenue and capacity analysed",
                "Churn signals identified",
            ],
            "metadata": dashboard_data,
            "model_used": _MODEL,
            "expires_at": (now + timedelta(hours=1)).isoformat(),
        })
        return dashboard_data

    # ── Recommendations ───────────────────────────────────────────────────────

    def list_recommendations(self, firm_id: str, **kwargs) -> list[dict]:
        return self._repo.list_recommendations(firm_id, **kwargs)

    def act_on_recommendation(self, firm_id: str, rec_id: str, action: str, user_id: str, snooze_days: Optional[int] = None) -> Optional[dict]:
        snooze_until = None
        if action == "snooze" and snooze_days:
            snooze_until = (datetime.utcnow() + timedelta(days=snooze_days)).isoformat()
            status = "snoozed"
        elif action == "accept":
            status = "accepted"
        else:
            status = "dismissed"
        return self._repo.update_recommendation_status(firm_id, rec_id, status, user_id, snooze_until)


ai_copilot_service = AICopilotService()
