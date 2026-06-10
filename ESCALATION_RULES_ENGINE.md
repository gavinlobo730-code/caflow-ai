# Escalation Rules Engine

Implements configurable escalation for overdue and due-soon tasks.

## Architecture

### Database Schema

#### escalation_rules
Defines escalation rules for a firm. Supports:
- `due_soon`: Notify when task is due in N days
- `overdue`: Notify when task is overdue by N+ days
- `reassign_overdue`: Auto-reassign task to role when overdue by N+ days
- `manager_notify`: Notify manager when task is overdue by N+ days

```sql
CREATE TABLE escalation_rules (
  id UUID PRIMARY KEY,
  firm_id UUID NOT NULL,
  rule_type TEXT CHECK (rule_type IN ('due_soon', 'overdue', 'reassign_overdue', 'manager_notify')),
  days_threshold INTEGER NOT NULL,
  escalate_to_role TEXT,
  reassign_to_role TEXT,
  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ
);
```

#### task_escalations
Audit trail of escalation events.

```sql
CREATE TABLE task_escalations (
  id UUID PRIMARY KEY,
  task_id UUID NOT NULL,
  escalation_rule_id UUID NOT NULL,
  escalated_at TIMESTAMPTZ DEFAULT NOW(),
  escalation_type TEXT CHECK (escalation_type IN ('due_soon', 'overdue', 'reassigned'))
);
```

## Components

### EscalationRuleRepository
Located: `apps/api/repositories/escalation_rule_repository.py`

Key methods:
- `find_active_by_firm(firm_id)`: Get all active rules for a firm
- `get_applicable_escalations(firm_id, task)`: Get rules that match a task's state
  - For `due_soon`: Matches when `(due_date - today) == days_threshold`
  - For `overdue`/`reassign_overdue`/`manager_notify`: Matches when `(today - due_date) >= days_threshold`

### EscalationService
Located: `apps/api/services/escalation_service.py`

Key methods:
- `escalate_due_soon_tasks(firm_id)`: Find tasks due soon, create notifications
- `escalate_overdue_tasks(firm_id)`: Handle overdue escalations (reassign, notify)
- `run_all_escalations(firm_id)`: Orchestrates all escalation checks

Behavior:
- **due_soon**: Creates notification to `escalate_to_role`
- **overdue**: Creates notification to manager
- **reassign_overdue**: Finds least-busy user with `reassign_to_role`, reassigns task, logs timeline event, notifies manager
- **manager_notify**: Notifies manager about overdue task

### Tasks Router Endpoint
Located: `apps/api/routers/tasks.py`

Endpoint: `POST /api/tasks/trigger-escalations`
- Requires: `task.write` permission
- Returns: `{due_soon_escalations, overdue_escalations, total_escalations}`

## Usage

### API Example
```bash
POST /api/tasks/trigger-escalations HTTP/1.1
Authorization: Bearer <token>

# Response
{
  "success": true,
  "data": {
    "due_soon_escalations": 3,
    "overdue_escalations": 2,
    "total_escalations": 5
  }
}
```

### Database Setup
```sql
INSERT INTO escalation_rules (firm_id, rule_type, days_threshold, escalate_to_role, is_active)
VALUES 
  ('firm-123', 'due_soon', 3, 'Manager', true),
  ('firm-123', 'overdue', 2, 'Manager', true),
  ('firm-123', 'reassign_overdue', 2, NULL, 'Manager', true),
  ('firm-123', 'manager_notify', 5, 'Manager', true);
```

## Acceptance Tests

1. **Task 3 days before due generates notification**
   - Task with due_date = today + 3 days
   - Rule: due_soon, threshold=3, escalate_to_role=Manager
   - Result: Notification created for Manager

2. **Overdue task triggers reassignment to manager**
   - Task with due_date = today - 2 days, assigned to Staff
   - Rule: reassign_overdue, threshold=2, reassign_to_role=Manager
   - Result: Task reassigned, timeline event logged, manager notified

3. **Clear notifications sent to appropriate users**
   - Overdue task with manager_notify rule
   - Result: Manager receives notification with task details and days_overdue metadata

## Testing

Unit tests in: `apps/api/tests/test_escalation_engine.py`
Integration tests in: `apps/api/tests/test_escalation_integration.py`

Run tests:
```bash
pytest apps/api/tests/test_escalation_engine.py -v
pytest apps/api/tests/test_escalation_integration.py -v
```

## Scalability Considerations

1. **Filtering**: The service filters tasks by firm_id to ensure tenant isolation
2. **Rule Matching**: Uses date-based thresholds to avoid expensive task history lookups
3. **Notifications**: Batches notifications per user role to reduce API calls
4. **Audit Trail**: task_escalations table enables compliance reporting and prevents duplicate escalations

## Future Enhancements

- Add deduplication logic to prevent duplicate escalations within N hours
- Implement task load-based assignment (least busy user lookup)
- Add escalation history for compliance reporting
- Support custom escalation chains (escalate to Manager, then Partner if no response)
- Support multi-role escalations in a single rule
