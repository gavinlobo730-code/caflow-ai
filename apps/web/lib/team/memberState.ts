/**
 * The words the Team screen shows for a member's state (PRE-A-020).
 *
 * The server decides the state (`GET /api/identity/users` serves `member_state` on each row, from
 * `apps/api/domain/firm/member_state.py`): a staff invitation creates the row before the person ever signs in,
 * and the screen used to read `is_active` alone, so someone who had never accepted showed as Active. This
 * module only turns the server's word into the badge's words; it decides nothing about the member.
 *
 * A row without the field (a backend not yet carrying it) is not guessed at: the badge says "—" and the
 * counts fall back to `is_active`, which is all such a backend can say.
 */

export type MemberState = "active" | "invited" | "invite_expired" | "inactive";

const KNOWN: readonly string[] = ["active", "invited", "invite_expired", "inactive"];

export interface MemberStateRow {
  member_state?: string | null;
  is_active?: boolean;
  invite_expires_at?: string | null;
  auth_user_id?: string | null;
}

/** The server's state, or null when the row carries none or one this screen does not know. */
export function memberState(row: MemberStateRow): MemberState | null {
  const s = row.member_state;
  return typeof s === "string" && KNOWN.includes(s) ? (s as MemberState) : null;
}

/** Whether the member counts as working here (the "N active" figure and the access matrix). */
export function countsAsActive(row: MemberStateRow): boolean {
  const s = memberState(row);
  return s === null ? row.is_active !== false : s === "active";
}

export interface MemberBadge {
  label: string;
  tone: "ready" | "attention" | "muted" | "unknown";
}

/**
 * The badge for a row. `formatDay` is the screen's own date formatter, passed in so this module stays free of
 * the browser's clock and locale.
 */
export function memberBadge(row: MemberStateRow, formatDay: (iso: string) => string): MemberBadge {
  switch (memberState(row)) {
    case "active":
      return { label: "Active", tone: "ready" };
    case "invited":
      return {
        label: row.invite_expires_at ? `Invited · link valid until ${formatDay(row.invite_expires_at)}` : "Invited",
        tone: "attention",
      };
    case "invite_expired":
      return { label: "Invite expired", tone: "attention" };
    case "inactive":
      return { label: "Inactive", tone: "muted" };
    default:
      return { label: "—", tone: "unknown" };
  }
}

/** The action that switches a member off or back on, in the words that fit their state. */
export function switchActionLabel(row: MemberStateRow): string {
  const s = memberState(row);
  if (s === "invited" || s === "invite_expired") return "Withdraw invite";
  if (s === null) return row.is_active === false ? "Activate" : "Deactivate";
  return s === "inactive" ? "Activate" : "Deactivate";
}

/**
 * Whether the member has joined, so the Joined column shows a date rather than "—". An inactive row joined
 * only if it was ever linked to a sign-in: a withdrawn invitation never was.
 */
export function hasJoined(row: MemberStateRow): boolean {
  const s = memberState(row);
  if (s === null || s === "active") return true;
  return s === "inactive" && !!row.auth_user_id;
}

/**
 * Whether the row offers Resend invite (POST-A-445): somebody still waiting to join, whose invitation is live or has
 * lapsed. A withdrawn invitation is switched back on first (Activate), and the server refuses a resend otherwise.
 */
export function offersResend(row: MemberStateRow): boolean {
  const s = memberState(row);
  return s === "invited" || s === "invite_expired";
}

/** What the server says it did with an invitation's email (POST-A-445). */
export interface InviteMailAnswer {
  invite_mail?: { sent?: boolean; problem?: string | null; kept_previous?: boolean } | null;
  invite_expires_at?: string | null;
}

export interface TeamNotice {
  tone: "ready" | "problem";
  text: string;
}

/**
 * The sentence after a resend, from the server's answer. A fresh link replaces the old one when the email went; when
 * it did not, the server puts the earlier invitation back and says so (`kept_previous`), and only then does the
 * sentence say the earlier link still works. An answer that does not say the mail went is never read as sent.
 */
export function resendNotice(name: string, email: string, answer: InviteMailAnswer,
                             formatDay: (iso: string) => string): TeamNotice {
  const until = answer.invite_expires_at ? ` It can be used until ${formatDay(answer.invite_expires_at)}.` : "";
  if (answer.invite_mail?.sent === true) {
    return { tone: "ready",
             text: `A new invitation went to ${email}. The link in any earlier email no longer works.${until}` };
  }
  const problem = answer.invite_mail?.problem ?? "The server did not say whether the email went.";
  if (answer.invite_mail?.kept_previous === true) {
    return { tone: "problem",
             text: `The new invitation's email to ${email} did not go, so ${name}'s earlier invitation was kept: the link in it still works until it expires. ${problem}` };
  }
  return { tone: "problem",
           text: `A new invitation for ${name} was saved, but its email to ${email} did not go, and the link in any earlier email no longer works. ${problem}` };
}
