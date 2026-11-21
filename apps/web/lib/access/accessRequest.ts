/**
 * A person's own requests for access, as the page that refused them reads them (POST-A-543, Request access).
 *
 * The server answers the caller's own requests (`GET /api/approvals/access-requests/mine`), newest first. This module
 * reads that answer without trusting its shape, and says which of three things is true of ONE permission: nothing has been
 * asked, a request is waiting, or the last one was declined. An answer that could not be read is none of the three, and
 * the caller keeps it apart: "could not be read" is not "nothing asked".
 *
 * Pure: no React and no request.
 */
import { arrayOrEmpty, objectOrNull } from "../api/shape.ts";

/** The request type the approval engine knows this by. */
export const ACCESS_REQUEST = "access_request";
export const NOTE_MAX = 300;

export interface MyAccessRequest {
  id: string;
  resource: string;
  action: string;
  status: string;
  askedAt: string | null;
  decidedAt: string | null;
  /** The Partner's reason, on a declined request only. */
  reason: string | null;
}

const text = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v : null);

/** The caller's requests, or null when the answer is not the list it should be. */
export function readMine(data: unknown): MyAccessRequest[] | null {
  const obj = objectOrNull<Record<string, unknown>>(data);
  if (!obj || !Array.isArray(obj.requests)) return null;
  const out: MyAccessRequest[] = [];
  for (const raw of arrayOrEmpty<unknown>(obj.requests)) {
    const row = objectOrNull<Record<string, unknown>>(raw);
    const id = text(row?.id), resource = text(row?.resource), action = text(row?.action), status = text(row?.status);
    if (!row || !id || !resource || !action || !status) continue;
    out.push({ id, resource, action, status, askedAt: text(row.asked_at), decidedAt: text(row.decided_at), reason: text(row.reason) });
  }
  return out;
}

export type Standing =
  | { kind: "none" }
  | { kind: "waiting"; askedAt: string | null }
  | { kind: "declined"; decidedAt: string | null; reason: string | null };

/**
 * Where one permission stands for this person: the NEWEST request for it decides (the list is newest first). An approved or
 * cancelled one is "none": if it was approved the page would not be refusing them, so a refusal now means the permission
 * was taken away since, and they may ask again.
 */
export function standingOf(rows: readonly MyAccessRequest[], resource: string, action: string): Standing {
  const latest = rows.find((r) => r.resource === resource && r.action === action);
  if (!latest) return { kind: "none" };
  if (latest.status === "pending") return { kind: "waiting", askedAt: latest.askedAt };
  if (latest.status === "rejected") return { kind: "declined", decidedAt: latest.decidedAt, reason: latest.reason };
  return { kind: "none" };
}
