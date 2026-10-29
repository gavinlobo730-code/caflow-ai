/**
 * What stands between a saved draft invoice and its issue, as the SERVER lists it (POST-A-125).
 *
 * `GET /api/sales-invoices/{id}/issue-preflight` returns the same blockers the issue route refuses from, each with a stable `code`, the
 * server's sentence and an `action` the screen may offer. This module is the browser's whole decision about that payload, kept out of the
 * component so it is tested as a decision. It holds NO rule: which things block an issue (a locked year, a placeholder number, a missing
 * place of supply, a chart of accounts without an account the posting needs) is `domain/sales/issue_readiness` and
 * `services/issue_readiness_service`, and the sentence is the server's, shown as received.
 *
 * WHAT IT DECIDES
 *   * a payload that is not the shape is NO ANSWER, never "ready": an unknown is not a value, and "nothing in the way" is a claim the
 *     screen may make only when the server made it;
 *   * an action of a kind this build does not know is dropped to "no action" and its sentence still shows, so a server that learns a
 *     new action before the browser does costs a button and not the whole panel;
 *   * `ready` is read from the blockers (an empty list), not trusted beside a non-empty one;
 *   * a click on Save & Issue is held only when the server's answer is current: if the CA has changed anything since the draft was
 *     last saved, the answer describes a draft that no longer exists, and the save-then-issue chain asks the server again.
 */

export type IssueBlockerAction =
  | { kind: "fix_in_editor"; field: "invoice_no" | "supply_state"; label: string }
  | { kind: "seed_chart_of_accounts"; label: string };

export type IssueBlocker = { code: string; message: string; action: IssueBlockerAction | null };

export type IssuePreflight = { ready: boolean; blockers: IssueBlocker[] };

/** What the panel knows: it has not asked, the answer is on its way, the answer could not be had, or it is the server's. */
export type ReadinessState =
  | { status: "loading" }
  | { status: "unknown"; reason: string }
  | { status: "ready" }
  | { status: "blocked"; blockers: IssueBlocker[] };

const EDITOR_FIELDS = ["invoice_no", "supply_state"] as const;

function isRecord(v: unknown): v is Record<string, unknown> {
  return v !== null && typeof v === "object" && !Array.isArray(v);
}

function readAction(v: unknown): IssueBlockerAction | null {
  if (!isRecord(v) || typeof v.label !== "string" || !v.label.trim()) return null;
  if (v.kind === "seed_chart_of_accounts") return { kind: "seed_chart_of_accounts", label: v.label };
  if (v.kind === "fix_in_editor" && (EDITOR_FIELDS as readonly unknown[]).includes(v.field)) {
    return { kind: "fix_in_editor", field: v.field as (typeof EDITOR_FIELDS)[number], label: v.label };
  }
  return null;
}

function readBlocker(v: unknown): IssueBlocker | null {
  if (!isRecord(v) || typeof v.message !== "string" || !v.message.trim()) return null;
  return {
    code: typeof v.code === "string" ? v.code : "",
    message: v.message,
    action: readAction(v.action),
  };
}

/** The pre-flight payload, or null when `data` is not the shape (an array, a scalar, no `blockers` list). */
export function readIssuePreflight(data: unknown): IssuePreflight | null {
  if (!isRecord(data) || !Array.isArray(data.blockers)) return null;
  const blockers: IssueBlocker[] = [];
  for (const raw of data.blockers) {
    const b = readBlocker(raw);
    // A blocker that carries no sentence makes the whole answer unreadable. Skipping it would let a list with a blocker in it read as
    // "ready", and the screen would then say the one thing it must never say without the server's word.
    if (!b) return null;
    blockers.push(b);
  }
  return { ready: blockers.length === 0, blockers };
}

/** The panel's state for one answer from `api.salesInvoices.issuePreflight`. */
export function readinessFrom(res: { success?: boolean; data?: unknown; error?: string | null } | null | undefined): ReadinessState {
  if (!res || !res.success) {
    return { status: "unknown", reason: (res?.error ?? "").trim() || "The server did not answer." };
  }
  const read = readIssuePreflight(res.data);
  if (!read) return { status: "unknown", reason: "The server's answer was not in the shape this screen reads." };
  return read.ready ? { status: "ready" } : { status: "blocked", blockers: read.blockers };
}

/**
 * Whether Save & Issue is held. Only when the server has said the draft cannot be issued AND nothing has changed since the draft
 * was last saved, because then the click can only fail. With unsaved changes the answer describes the old draft, and the chain
 * (save, then issue, which asks the server again) is exactly how a blocker gets fixed.
 */
export function holdsTheIssue(state: ReadinessState, hasUnsavedChanges: boolean): boolean {
  return state.status === "blocked" && !hasUnsavedChanges;
}

/** The sentence under the button when it is held. */
export const HELD_SENTENCE = "The draft as saved cannot be issued yet. What is in the way is listed in the panel on the right.";
