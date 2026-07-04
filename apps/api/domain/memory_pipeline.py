"""
Phase 13 — AI Memory & Compounding Intelligence Pipeline
Transforms raw event data into structured semantic memory.
"""
import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger("caflow.memory")

_USE_MOCK = not os.environ.get("SUPABASE_URL")


def _get_client_repo():
    from repositories.client_repository import client_repo
    return client_repo

def _get_task_repo():
    from repositories.task_repository import task_repo
    return task_repo

def _get_compliance_records_repo():
    """The canonical compliance_records repo (compliance_tasks/System B is
    being retired; this AI-memory pipeline is the only genuinely live
    consumer of compliance data found during that consolidation)."""
    from repositories.compliance_records_repository import compliance_records_repo
    return compliance_records_repo

def _get_workflow_repo():
    from repositories.workflow_repository import workflow_repo
    return workflow_repo

def _get_memory_repo():
    from repositories.memory_repository import memory_repo
    return memory_repo


class MemoryPipeline:
    """
    Episodic → Semantic memory transformation pipeline.
    Reads raw events from existing tables and generates structured intelligence.
    """

    # ── Client Profile Generation ─────────────────────────────────────────────

    def compute_client_profile(self, firm_id: str, client_id: str) -> dict:
        """
        Generate a full behavioural + compliance + financial profile for a client.
        Uses real data from tasks, compliance, and workflow history.
        Returns the profile dict (also persists via memory_repo).
        """
        client = _get_client_repo().find_by_id(client_id)
        if not client:
            raise ValueError(f"Client {client_id} not found")

        profile_data = {}
        data_points = 0

        # ── Behavioural profile ──────────────────────────────────────────────
        try:
            all_tasks = _get_task_repo().find_all(firm_id=firm_id, client_id=client_id) if hasattr(_get_task_repo(), 'find_all') else []
            data_points += len(all_tasks)

            total = len(all_tasks)
            completed = [t for t in all_tasks if t.get("status") == "completed"]
            overdue = [t for t in all_tasks if t.get("status") == "overdue"]

            # Response time: average days between task creation and completion
            response_times = []
            for t in completed:
                if t.get("created_at") and t.get("updated_at"):
                    try:
                        created = datetime.fromisoformat(t["created_at"].replace("Z", "+00:00"))
                        updated = datetime.fromisoformat(t["updated_at"].replace("Z", "+00:00"))
                        days = (updated - created).days
                        if 0 <= days <= 365:
                            response_times.append(days)
                    except Exception:
                        pass

            avg_response = round(sum(response_times) / len(response_times), 1) if response_times else None
            # Portal engagement = % of tasks completed on time
            on_time = len([t for t in completed
                          if t.get("due_date") and t.get("updated_at")
                          and t["updated_at"] <= t.get("due_date", "9999")])
            engagement_score = round((len(completed) / total) * 100, 1) if total > 0 else 50.0

            profile_data["avg_response_time_days"] = avg_response
            profile_data["portal_engagement"] = engagement_score
            profile_data["doc_upload_reliability"] = round(100 - (len(overdue) / max(1, total) * 100), 1)
        except Exception as e:
            logger.warning("Behavioural profile error for %s: %s", client_id, e)

        # ── Compliance history ────────────────────────────────────────────────
        try:
            compliance_items = _get_compliance_records_repo().find_all(firm_id=firm_id)
            client_compliance = [c for c in compliance_items if c.get("client_id") == client_id]
            data_points += len(client_compliance)

            missed = [c for c in client_compliance if c.get("status") == "Overdue"]

            profile_data["missed_deadline_count"] = len(missed)
            profile_data["compliance_score"] = max(0, round(100 - (len(missed) / max(1, len(client_compliance)) * 50), 1))

            # Recurring issues: look for types that appear more than once as overdue
            issue_counts = {}
            for c in missed:
                ct = c.get("compliance_type", "unknown")
                issue_counts[ct] = issue_counts.get(ct, 0) + 1
            recurring = [{"type": k, "count": v, "issue": f"Recurring {k} delays"}
                        for k, v in issue_counts.items() if v >= 2]
            profile_data["recurring_issues"] = recurring
        except Exception as e:
            logger.warning("Compliance profile error for %s: %s", client_id, e)

        # ── Financial patterns ────────────────────────────────────────────────
        try:
            # Derive from task activity patterns by month
            all_tasks_raw = _get_task_repo().find_all(firm_id=firm_id, client_id=client_id) if hasattr(_get_task_repo(), 'find_all') else []
            month_activity = {}
            for t in all_tasks_raw:
                if t.get("created_at"):
                    try:
                        month = datetime.fromisoformat(t["created_at"].replace("Z", "+00:00")).strftime("%B")
                        month_activity[month] = month_activity.get(month, 0) + 1
                    except Exception:
                        pass

            if month_activity:
                peak_month = max(month_activity, key=month_activity.get)
                # Cash flow risk: months with highest task load typically correlate with pressure
                sorted_months = sorted(month_activity.items(), key=lambda x: x[1], reverse=True)
                cash_risk_months = [m for m, _ in sorted_months[:2]]
                profile_data["seasonal_revenue_peak"] = peak_month
                profile_data["cash_flow_risk_months"] = cash_risk_months
        except Exception as e:
            logger.warning("Financial pattern error for %s: %s", client_id, e)

        # ── Year-end patterns ─────────────────────────────────────────────────
        try:
            # Year-end tasks: look for tasks with "year end", "audit", "provisions" in name
            all_tasks_raw = _get_task_repo().find_all(firm_id=firm_id, client_id=client_id) if hasattr(_get_task_repo(), 'find_all') else []
            ye_keywords = ["year end", "audit", "provision", "annual", "closing", "finalization"]
            ye_tasks = [t for t in all_tasks_raw
                       if any(kw in (t.get("title", "") + t.get("description", "")).lower()
                              for kw in ye_keywords)]

            if ye_tasks:
                # Estimate average year-end duration from first to last year-end task
                common_requests = list({t.get("title", "")[:50] for t in ye_tasks if t.get("title")})[:5]
                profile_data["avg_year_end_duration_days"] = 30  # default estimate
                profile_data["common_auditor_requests"] = common_requests
        except Exception as e:
            logger.warning("Year-end pattern error for %s: %s", client_id, e)

        profile_data["data_points_used"] = data_points
        profile_data["last_computed_at"] = datetime.now(timezone.utc).isoformat()

        # Persist profile
        try:
            return _get_memory_repo().upsert_profile(firm_id, client_id, profile_data)
        except Exception as e:
            logger.error("Failed to persist profile for %s: %s", client_id, e)
            return {"firm_id": firm_id, "client_id": client_id, **profile_data}

    def compute_all_client_profiles(self, firm_id: str) -> list[dict]:
        """Compute profiles for all active clients in a firm."""
        clients = _get_client_repo().find_all(firm_id=firm_id)
        results = []
        for client in clients:
            try:
                profile = self.compute_client_profile(firm_id, client["id"])
                results.append(profile)
            except Exception as e:
                logger.error("Profile failed for client %s: %s", client["id"], e)
        return results

    def compute_firm_profile(self, firm_id: str) -> dict:
        """Generate firm-level intelligence from all client and workflow data."""
        clients = _get_client_repo().find_all(firm_id=firm_id)

        profile_data = {}

        try:
            # Portfolio health
            health_scores = [c.get("health_score", 75) for c in clients if c.get("health_score")]
            avg_health = round(sum(health_scores) / len(health_scores), 1) if health_scores else 75.0
            critical = len([c for c in clients if c.get("health_score", 100) < 40])
            at_risk = len([c for c in clients if 40 <= c.get("health_score", 100) < 70])

            profile_data["portfolio_compliance_score"] = avg_health
            profile_data["common_risk_categories"] = ["gst_delay", "document_missing"] if critical > 0 else []
            portfolio_trend = "declining" if critical > len(clients) * 0.2 else "stable"
            profile_data["portfolio_health_trend"] = portfolio_trend
        except Exception as e:
            logger.warning("Portfolio profile error: %s", e)

        try:
            # Workflow intelligence
            wf_repo = _get_workflow_repo()
            templates = wf_repo.list_templates(firm_id)
            active_automations = len([t for t in templates if t.get("is_active")])

            # Capacity: derive from task load
            all_tasks = _get_task_repo().find_all(firm_id=firm_id) if hasattr(_get_task_repo(), 'find_all') else []
            month_counts = {}
            for t in all_tasks:
                if t.get("created_at"):
                    try:
                        month = datetime.fromisoformat(t["created_at"].replace("Z", "+00:00")).strftime("%B")
                        month_counts[month] = month_counts.get(month, 0) + 1
                    except Exception:
                        pass

            if month_counts:
                sorted_months = sorted(month_counts.items(), key=lambda x: x[1], reverse=True)
                peak_months = [m for m, _ in sorted_months[:3]]
                profile_data["peak_workload_months"] = peak_months
                # Capacity risk: months with >20% above average
                avg_tasks_per_month = sum(month_counts.values()) / len(month_counts)
                capacity_risk = [m for m, c in month_counts.items() if c > avg_tasks_per_month * 1.2]
                profile_data["capacity_risk_months"] = capacity_risk

            profile_data["avg_tasks_per_client"] = round(len(all_tasks) / max(1, len(clients)), 1)

            # Deadline concentration by month
            compliance_items = _get_compliance_records_repo().find_all(firm_id=firm_id)
            deadline_counts = {}
            for c in compliance_items:
                if c.get("due_date"):
                    try:
                        month = datetime.fromisoformat(c["due_date"].replace("Z", "+00:00")).strftime("%B")
                        deadline_counts[month] = deadline_counts.get(month, 0) + 1
                    except Exception:
                        pass
            profile_data["deadline_concentration"] = deadline_counts
        except Exception as e:
            logger.warning("Workflow firm profile error: %s", e)

        profile_data["last_computed_at"] = datetime.now(timezone.utc).isoformat()

        try:
            return _get_memory_repo().upsert_firm_profile(firm_id, profile_data)
        except Exception as e:
            logger.error("Failed to persist firm profile: %s", e)
            return {"firm_id": firm_id, **profile_data}

    # ── Trigger Detection ─────────────────────────────────────────────────────

    def detect_repeat_issues(self, firm_id: str, client_id: str) -> list[dict]:
        """
        Detect if current conditions match historical issue patterns.
        Returns list of triggered warnings.
        """
        triggers = []
        profile = _get_memory_repo().get_current_profile(firm_id, client_id)
        if not profile:
            return triggers

        recurring = profile.get("recurring_issues", [])
        if not recurring:
            return triggers

        # Check if current period has conditions resembling historical issues
        compliance_items = _get_compliance_records_repo().find_all(firm_id=firm_id)
        client_compliance = [c for c in compliance_items
                            if c.get("client_id") == client_id
                            and c.get("status") not in ("Filed", "Completed")]

        for issue in recurring:
            issue_type = issue.get("type", "")
            count = issue.get("count", 0)

            # Check if we have upcoming items of same type
            matching_upcoming = [c for c in client_compliance
                                if issue_type.lower() in c.get("compliance_type", "").lower()]

            if matching_upcoming and count >= 2:
                confidence = min(95, 50 + count * 10)

                # Check for dedup — don't re-create if already active within 30 days
                recent = _get_memory_repo().get_recent_triggers(
                    firm_id, client_id, "repeat_issue", days=30)
                existing = [r for r in recent if issue_type in r.get("title", "")]
                if existing:
                    continue

                evidence = [
                    f"Historical pattern: {issue_type} delayed {count} times in past",
                    f"{len(matching_upcoming)} upcoming {issue_type} filing(s) detected",
                    f"Average compliance score: {profile.get('compliance_score', 75)}",
                ]

                trigger = _get_memory_repo().create_trigger(
                    firm_id=firm_id,
                    client_id=client_id,
                    trigger_type="repeat_issue",
                    title=f"Repeat Issue Risk: {issue_type.upper()} Filing",
                    what_detected=f"Client historically experiences {issue_type} delays. Current period has {len(matching_upcoming)} upcoming {issue_type} filing(s).",
                    evidence=evidence,
                    why_it_matters=f"This client has delayed {issue_type} filings {count} times historically, increasing penalty risk.",
                    recommended_action=f"Proactively contact client 2 weeks before {issue_type} deadline. Escalate if documents not received within 7 days.",
                    confidence=confidence,
                    severity="high" if count >= 3 else "medium",
                )
                triggers.append(trigger)

        return triggers

    def detect_deadline_at_risk(self, firm_id: str, client_id: str) -> list[dict]:
        """
        Predict deadline risk based on behavioural profile and response time history.
        """
        triggers = []
        profile = _get_memory_repo().get_current_profile(firm_id, client_id)
        avg_response_days = (profile or {}).get("avg_response_time_days") or 5

        now = datetime.now(timezone.utc)
        compliance_items = _get_compliance_records_repo().find_all(firm_id=firm_id)
        upcoming = [c for c in compliance_items
                   if c.get("client_id") == client_id
                   and c.get("status") not in ("Filed", "Completed")
                   and c.get("due_date")]

        for item in upcoming:
            try:
                due = datetime.fromisoformat(item["due_date"].replace("Z", "+00:00"))
                days_until_due = (due - now).days
            except Exception:
                continue

            # At risk if avg response time > days remaining
            if 0 < days_until_due <= avg_response_days + 2:
                # Dedup check
                recent = _get_memory_repo().get_recent_triggers(
                    firm_id, client_id, "deadline_at_risk", days=7)
                ct = item.get("compliance_type", "filing")
                existing = [r for r in recent if ct in r.get("title", "")]
                if existing:
                    continue

                confidence = min(95, round(70 + (avg_response_days - days_until_due) * 5))
                evidence = [
                    f"Client avg response time: {avg_response_days} days",
                    f"Days until {ct} deadline: {days_until_due}",
                    f"Portal engagement score: {(profile or {}).get('portal_engagement', 50)}",
                ]

                trigger = _get_memory_repo().create_trigger(
                    firm_id=firm_id,
                    client_id=client_id,
                    trigger_type="deadline_at_risk",
                    title=f"Deadline At Risk: {ct} due in {days_until_due} days",
                    what_detected=f"Client typically takes {avg_response_days} days to respond but {ct} deadline is only {days_until_due} days away.",
                    evidence=evidence,
                    why_it_matters=f"Based on historical response patterns, this client is unlikely to meet the {ct} deadline without proactive intervention.",
                    recommended_action=f"Contact client immediately. Expedite document collection. Consider filing extension if available.",
                    confidence=confidence,
                    severity="critical" if days_until_due <= 2 else "high",
                )
                triggers.append(trigger)

        return triggers

    def detect_cash_flow_warnings(self, firm_id: str, client_id: str) -> list[dict]:
        """Detect cash flow risk periods based on seasonal patterns."""
        triggers = []
        profile = _get_memory_repo().get_current_profile(firm_id, client_id)
        if not profile:
            return triggers

        risk_months = profile.get("cash_flow_risk_months", [])
        current_month = datetime.now().strftime("%B")

        if current_month in risk_months:
            # Dedup
            recent = _get_memory_repo().get_recent_triggers(
                firm_id, client_id, "cash_flow_warning", days=25)
            if recent:
                return triggers

            evidence = [
                f"Historically high activity month: {current_month}",
                f"Cash flow risk months identified: {', '.join(risk_months)}",
                f"Seasonal peak month: {profile.get('seasonal_revenue_peak', 'N/A')}",
            ]

            trigger = _get_memory_repo().create_trigger(
                firm_id=firm_id,
                client_id=client_id,
                trigger_type="cash_flow_warning",
                title=f"Cash Flow Pressure Period: {current_month}",
                what_detected=f"Historical patterns show {current_month} is a high-pressure period for this client with elevated tax obligations and operational costs.",
                evidence=evidence,
                why_it_matters="Clients under cash flow pressure may delay fee payments and require additional support. Proactive planning reduces defaults.",
                recommended_action="Review outstanding invoices. Consider payment plan options. Prepare advance tax calculation if applicable.",
                confidence=72.0,
                severity="medium",
            )
            triggers.append(trigger)

        return triggers

    def detect_year_end_readiness(self, firm_id: str, client_id: str) -> Optional[dict]:
        """
        60-90 days before March 31 year-end, generate a year-end readiness report.
        Only fires once per financial year.
        """
        now = datetime.now(timezone.utc)
        # Indian FY ends March 31
        current_year = now.year
        fy_end = datetime(current_year, 3, 31, tzinfo=timezone.utc)
        if now > fy_end:
            fy_end = datetime(current_year + 1, 3, 31, tzinfo=timezone.utc)

        days_to_ye = (fy_end - now).days
        if not (30 <= days_to_ye <= 90):
            return None  # Not in the year-end window

        fy_label = f"{fy_end.year - 1}-{str(fy_end.year)[2:]}"

        # Check if already generated for this FY
        existing = _get_memory_repo().get_year_end_report(firm_id, client_id, fy_label)
        if existing:
            return existing

        profile = _get_memory_repo().get_current_profile(firm_id, client_id)

        lessons = []
        provisions = profile.get("common_provisions", []) if profile else []
        auditor_requests = profile.get("common_auditor_requests", []) if profile else []
        bottlenecks = []

        if profile:
            if profile.get("missed_deadline_count", 0) > 0:
                lessons.append(f"Client missed {profile['missed_deadline_count']} deadlines this year — build earlier reminders.")
            if profile.get("avg_response_time_days"):
                lessons.append(f"Avg document response time: {profile['avg_response_time_days']} days — request documents 2 weeks early.")
            recurring = profile.get("recurring_issues", [])
            for issue in recurring:
                bottlenecks.append(f"Recurring {issue.get('type')} issue — pre-verify before filing")

        recommendations = [
            "Request all supporting documents by Feb 28",
            "Schedule client review meeting before March 15",
            "Prepare draft financials by March 20",
        ]
        if auditor_requests:
            recommendations.insert(0, f"Pre-prepare: {', '.join(auditor_requests[:3])}")

        report = _get_memory_repo().create_year_end_report(
            firm_id=firm_id,
            client_id=client_id,
            financial_year=fy_label,
            data={
                "prior_year_lessons": lessons,
                "recurring_provisions": provisions,
                "auditor_requests": auditor_requests,
                "historical_bottlenecks": bottlenecks,
                "planning_recommendations": recommendations,
                "ai_narrative": f"Year-end {fy_label} planning report. {days_to_ye} days remaining. Based on {profile.get('data_points_used', 0) if profile else 0} historical data points.",
            }
        )

        # Also create a memory trigger
        _get_memory_repo().create_trigger(
            firm_id=firm_id,
            client_id=client_id,
            trigger_type="year_end_readiness",
            title=f"Year-End Planning: FY {fy_label}",
            what_detected=f"{days_to_ye} days until March 31 year-end. Year-end planning report generated based on historical patterns.",
            evidence=lessons + [f"Auditor requests: {len(auditor_requests)}", f"Bottlenecks identified: {len(bottlenecks)}"],
            why_it_matters="Early year-end preparation prevents last-minute scrambles, reduces errors, and improves client satisfaction.",
            recommended_action="Review year-end planning report and initiate document collection immediately.",
            confidence=90.0,
            severity="high",
        )

        return report

    def detect_pattern_anomalies(self, firm_id: str, client_id: str) -> list[dict]:
        """Detect statistical anomalies in task/compliance activity."""
        anomalies = []

        try:
            all_tasks = _get_task_repo().find_all(firm_id=firm_id, client_id=client_id) if hasattr(_get_task_repo(), 'find_all') else []
            if len(all_tasks) < 6:
                return anomalies  # Not enough data for meaningful baseline

            # Monthly task volume baseline
            month_counts = {}
            for t in all_tasks:
                if t.get("created_at"):
                    try:
                        month_key = datetime.fromisoformat(t["created_at"].replace("Z", "+00:00")).strftime("%Y-%m")
                        month_counts[month_key] = month_counts.get(month_key, 0) + 1
                    except Exception:
                        pass

            if len(month_counts) >= 3:
                values = list(month_counts.values())
                avg = sum(values) / len(values)
                if avg > 0:
                    # Simple std dev
                    variance = sum((v - avg) ** 2 for v in values) / len(values)
                    std_dev = variance ** 0.5

                    # Current month
                    current_month_key = datetime.now().strftime("%Y-%m")
                    current_count = month_counts.get(current_month_key, 0)

                    if std_dev > 0:
                        deviation_score = abs(current_count - avg) / std_dev
                        deviation_pct = ((current_count - avg) / avg) * 100

                        if deviation_score >= 2.0:  # 2 sigma
                            anomaly_type = "activity_spike" if current_count > avg else "activity_drop"
                            explanation = (
                                f"Task activity this month ({current_count}) is "
                                f"{abs(round(deviation_pct))}% {'above' if current_count > avg else 'below'} "
                                f"the {len(values)}-month average ({round(avg, 1)})."
                            )
                            anomaly = _get_memory_repo().create_anomaly(
                                firm_id=firm_id,
                                client_id=client_id,
                                anomaly_type=anomaly_type,
                                metric_name="monthly_task_volume",
                                baseline=round(avg, 2),
                                actual=float(current_count),
                                period=current_month_key,
                                explanation=explanation,
                                evidence=[
                                    f"Baseline avg: {round(avg, 1)} tasks/month",
                                    f"Current month: {current_count} tasks",
                                    f"Deviation: {round(deviation_score, 2)} sigma",
                                    f"Historical months analyzed: {len(values)}",
                                ],
                            )
                            anomalies.append(anomaly)
        except Exception as e:
            logger.warning("Anomaly detection error for %s: %s", client_id, e)

        return anomalies

    def run_full_pipeline(self, firm_id: str) -> dict:
        """Run complete memory pipeline for all clients in a firm."""
        results = {
            "profiles_updated": 0,
            "triggers_created": 0,
            "anomalies_detected": 0,
            "year_end_reports": 0,
            "errors": [],
        }

        clients = _get_client_repo().find_all(firm_id=firm_id)

        # Firm profile
        try:
            self.compute_firm_profile(firm_id)
        except Exception as e:
            results["errors"].append(f"Firm profile: {e}")

        for client in clients:
            cid = client["id"]
            try:
                self.compute_client_profile(firm_id, cid)
                results["profiles_updated"] += 1
            except Exception as e:
                results["errors"].append(f"Profile {cid}: {e}")

            for detector in [
                self.detect_repeat_issues,
                self.detect_deadline_at_risk,
                self.detect_cash_flow_warnings,
                self.detect_pattern_anomalies,
            ]:
                try:
                    items = detector(firm_id, cid)
                    if detector == self.detect_pattern_anomalies:
                        results["anomalies_detected"] += len(items)
                    else:
                        results["triggers_created"] += len(items)
                except Exception as e:
                    results["errors"].append(f"{detector.__name__} {cid}: {e}")

            try:
                report = self.detect_year_end_readiness(firm_id, cid)
                if report:
                    results["year_end_reports"] += 1
            except Exception as e:
                results["errors"].append(f"YE {cid}: {e}")

        return results


memory_pipeline = MemoryPipeline()
