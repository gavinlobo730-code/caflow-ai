/**
 * THE SENTENCE ABOUT WHAT A BLOCK REACHES, AS THE ACCESS DRAWER RECEIVES IT
 * (POST-A-005).
 *
 * `GET /api/identity/permission-vocabulary` serves a `notice`: one sentence
 * saying that a per-person block is enforced by the PracticeSync server and is
 * not consulted when a screen reads a table straight from the database. It is a
 * claim about the database's policies, so the words live beside the real-Postgres
 * guard that keeps them true and this app holds none of them.
 *
 * WHAT THIS DECIDES, AND IT IS ALL IT DECIDES. Whether the thing that arrived is
 * a sentence at all. The payload is not a string until something has checked
 * (`lib/api/shape.ts` is the same rule for lists and objects): a frontend that
 * is live before the backend that serves the field, or one talking to an older
 * backend, gets `undefined`; a redeploy window or a proxy can hand back
 * anything. An absent or blank notice is NOT TOLD, and not told is rendered as
 * nothing — never as a stand-in sentence this file made up, because a screen
 * that wrote its own reassurance in the notice's place would be the grid's
 * original mistake (a control whose words were not the server's) on the one
 * line that exists to prevent it. The string that does arrive is returned as it
 * came: not trimmed, not reworded, not truncated.
 */
export function denialNotice(value: unknown): string | null {
  return typeof value === "string" && value.trim() !== "" ? value : null;
}
