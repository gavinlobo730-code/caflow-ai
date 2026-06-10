# Phase 1.3 — Intelligence Layer

Built directly on existing repositories and the existing Groq copilot — no
separate AI architecture. All scores are computed deterministically; the LLM
only narrates over computed context.

## Engines (`services/intelligence_service.py`)

### Predictive Compliance
- Per-client filing risk score 0–100 from: currently overdue records (+25 each,
  cap 50), records due within 7 days (+10 each, cap 30), late-filing history (+20).
- Levels: low / medium / high / critical. Predicted misses listed for clients
  with overdue items or late history.

### Relationship Intelligence
- Client health score 0–100: task delivery (40), payment behaviour (40),
  90-day engagement activity (20). Outstanding receivables in integer paise.
- Levels: healthy / at_risk / critical.

### Auto Journal Suggestions
- Pattern recognition over posted journal entries: same client + narration +
  account set appearing in ≥2 of the last 3 months but missing this month.
- Approval workflow: `POST /api/intelligence/journal-suggestions/approve`
  creates a DRAFT entry only (accounting.write); posting to the ledger still
  requires Partner approval via the existing accounting.approve flow. Nothing
  is ever auto-posted.

### Proactive Recommendations
- Rule-based, priority-sorted: compliance (high-risk clients), client
  (re-engagement, payment follow-up with outstanding ₹), operational
  (pending recurring journals).

### Workload Insights
- Capacity-aware overload, idle members, unassigned backlog.

## API (`routers/intelligence.py`)
| Endpoint | RBAC |
|---|---|
| GET /api/intelligence/compliance-risk | ai.read |
| GET /api/intelligence/relationship-health | ai.read |
| GET /api/intelligence/recommendations | ai.read |
| GET /api/intelligence/workload-insights | workload.read |
| GET /api/intelligence/journal-suggestions | accounting.read |
| POST /api/intelligence/journal-suggestions/approve | accounting.write |

## AI Copilot
- Firm-level copilot unchanged (`POST /api/ai-copilot/chat`).
- New client-level copilot: `POST /api/ai-copilot/client/{client_id}/chat`
  (ai.copilot RBAC, firm-scoped) — context includes client profile, open tasks,
  compliance records, and the computed risk/health scores above.
