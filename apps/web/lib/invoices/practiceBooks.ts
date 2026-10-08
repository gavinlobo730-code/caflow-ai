/**
 * What a firm-level fee screen knows about the practice's OWN books, as three
 * answers that are never interchangeable (PRE-A-018):
 *
 *   - `known`            the server named the practice's internal client, so the
 *                        screen can link into that client's sales workspace;
 *   - `not_provisioned`  the server answered, and said there is none — the
 *                        practice has not been set up, which is a thing to go
 *                        and DO (Practice settings);
 *   - `unknown`          nothing usable came back (the request failed, was
 *                        refused, or answered with something else) — a thing
 *                        that may be fixed by trying again, and NOT the same
 *                        as "not set up". Telling a Partner their practice is
 *                        not provisioned because a request timed out would send
 *                        them to provision a second one.
 *
 * `reply` is whatever `api.practice.get()` / `api.billing.serviceOptions()`
 * resolved to, or `undefined` when the call threw. It is typed `unknown`
 * because the response is a payload and not a promise about one (see
 * lib/api/shape). Pure, no I/O.
 */
import { practiceSalesHref } from "./workspaceNav.ts";

export type PracticeBooks =
  | { state: "known"; clientId: string }
  | { state: "not_provisioned" }
  | { state: "unknown" };

export function readPracticeBooks(reply: unknown): PracticeBooks {
  if (typeof reply !== "object" || reply === null) return { state: "unknown" };
  const envelope = reply as { success?: unknown; data?: unknown };
  if (envelope.success !== true) return { state: "unknown" };
  const data = envelope.data;
  if (typeof data !== "object" || data === null) return { state: "unknown" };
  const id = (data as { internal_client_id?: unknown }).internal_client_id;
  // An explicit null is the server saying "none". An absent key is a payload
  // from a backend that does not say, which is unknown and not "none".
  if (id === null) return { state: "not_provisioned" };
  // A string the sales link would refuse (blank, `_placeholder`) is not a
  // client we can open, so it cannot be "known" either.
  if (practiceSalesHref(id) === null) return { state: "unknown" };
  return { state: "known", clientId: id as string };
}
