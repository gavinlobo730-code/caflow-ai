"use client";

/**
 * WHO MAY PUT A MANUAL JOURNAL ON THE BOOKS IS THE SERVER'S ANSWER (POST-A-456).
 *
 * A firm may have a Partner approve every manual journal (`firms.manual_journals_need_approval`, migration 681). The four doors that
 * post or change a manual journal ask `services/journal_approval_rule` on the server, and `GET /api/accounting/journal-approval`
 * serves the same function's answer for the person asking. This hook reads it so the journal editor and the Approvals tab offer
 * Post only where the server will take it. Nothing is decided here.
 *
 * While the answer is being read, and when it could not be read, `mayPost` is `null` (unknown, never false and never true): a
 * screen keeps offering Post to someone the route admits, says when the rule could not be read, and the server decides.
 */
import { useEffect, useState } from "react";
import { api, type JournalApprovalRule } from "@/lib/api";
import { objectOrNull } from "@/lib/api/shape";

export interface JournalApprovalState {
  rule: JournalApprovalRule | null;
  /** The server's answer for this person, or null while it is being read or when it could not be. */
  mayPost: boolean | null;
  /** The sentence to show when the rule could not be read; null otherwise. */
  error: string | null;
}

export const RULE_UNREAD =
  "Could not read whether this firm has a Partner approve manual journals, so Post is offered and the server decides.";

/** The rule as the server sent it, or null when the payload is not that shape (a payload is not a rule until something checked). */
export function readJournalApprovalRule(data: unknown): JournalApprovalRule | null {
  const o = objectOrNull<Record<string, unknown>>(data);
  if (!o) return null;
  const keys = ["approval_required", "may_post", "may_approve", "may_change_setting"] as const;
  if (!keys.every((k) => typeof o[k] === "boolean")) return null;
  return o as unknown as JournalApprovalRule;
}

export function useJournalApprovalRule(reloadKey = 0): JournalApprovalState {
  const [state, setState] = useState<JournalApprovalState>({ rule: null, mayPost: null, error: null });
  useEffect(() => {
    let cancelled = false;
    setState((s) => ({ ...s, error: null }));
    api.accounting.journalApproval()
      .then((res) => {
        if (cancelled) return;
        const rule = res?.success ? readJournalApprovalRule(res.data) : null;
        setState(rule ? { rule, mayPost: rule.may_post, error: null } : { rule: null, mayPost: null, error: RULE_UNREAD });
      })
      .catch(() => { if (!cancelled) setState({ rule: null, mayPost: null, error: RULE_UNREAD }); });
    return () => { cancelled = true; };
  }, [reloadKey]);
  return state;
}
