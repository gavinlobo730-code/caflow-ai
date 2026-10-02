/**
 * An UNSENT draft kept in this tab, offered back after a reload (frontend_ux-23).
 *
 * WHAT THIS IS, AND WHAT IT IS NOT
 *     A CA entering a forty-line journal who presses F5, or drags the wrong
 *     gesture on a trackpad, loses twenty minutes of typing. `useUnsavedChanges`
 *     warns before that happens; this is what is left when the warning is
 *     dismissed or the browser crashes: the fields as TYPED, in `sessionStorage`,
 *     offered back — never applied — on the next visit to the same screen.
 *
 *     It is a per-viewer convenience and says so. `a-browser-only-screen-says-so`
 *     records the rule that the user's WORK belongs in a table, and a voucher is
 *     work: this is not where one is saved. A draft here is a half-typed form
 *     that nothing else in the product can see, no report reads, and that
 *     disappears with the tab. The document the CA SAVES goes to the server like
 *     any other.
 *
 * THE RULES, each one a decision
 *   * `sessionStorage`, never `localStorage`. The draft is per tab and ends with
 *     the tab; a draft that outlived the session would be the CA's work living
 *     in a browser, and would be offered to whoever sat down next.
 *   * Raw fields only. The caller hands over what the person TYPED or PICKED —
 *     strings, booleans, ids chosen from a list — and NOTHING DERIVED: no totals,
 *     no tax split, no balanced/unbalanced verdict, no server object. Everything
 *     that matters is recomputed by the server from what is sent on save, so a
 *     tampered draft can only ever put text in a box the person is about to read.
 *   * Validated on the way back in. The caller's `validate` rebuilds the fields
 *     from unknown JSON, field by field, and returns null for anything it does
 *     not recognise: a draft written by an older build, edited by hand in the
 *     dev tools, or half-written when the tab died is dropped, not trusted.
 *   * Every storage call is inside try/catch. Safari private windows, a full
 *     quota, a blocked-site-data setting and `window.sessionStorage` itself
 *     throwing a SecurityError are all ordinary, and a draft that cannot be kept
 *     must leave the editor working exactly as it did before this existed.
 *   * Never restored silently — see `useUnsentDraft`, which only ever OFFERS.
 *   * Scoped by person, kind, client and entity, so a second client's journal
 *     cannot be offered into the first, and a different person signing in on the
 *     same tab is offered nothing of the last person's.
 *   * Bounded in size and age. A draft that stopped being plausible — a day old,
 *     or too large to be a form — is removed instead of offered.
 *
 * Pure TypeScript with an injected storage: unit-tested by plain `node --test`.
 */

/** The slice of the Storage interface this uses — a `Map`-backed fake satisfies it. */
export interface DraftStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
  readonly length: number;
  key(index: number): string | null;
}

export const DRAFT_PREFIX = "ps:draft:v1:";
/** A draft is a form, not a file. */
export const MAX_DRAFT_CHARS = 200_000;
/** Older than a working day is not "the thing I was just doing". */
export const MAX_DRAFT_AGE_MS = 24 * 60 * 60 * 1000;

/** The editors that keep a draft. A third is a decision about what may be kept in
 *  a browser (see the frozen list in
 *  scripts/an-unsent-draft-is-offered-and-never-restored-silently.test.ts), so
 *  the union is closed by hand rather than open to any string. */
export type DraftKind = "journal" | "purchase-bill";

export interface StoredDraft<T> {
  v: 1;
  /** ISO instant the draft was written; shown to the person in IST. */
  savedAt: string;
  fields: T;
}

export interface DraftScope {
  /** The signed-in person — a draft is theirs and nobody else's. */
  userId: string | null | undefined;
  kind: DraftKind;
  clientId: string | null | undefined;
  /** The document's own id, or the literal `"new"`. */
  entityId: string | null | undefined;
}

/** A key part may not carry the separator, or two scopes could collide
 *  (`a:b` + `c` against `a` + `b:c`). */
function safePart(part: string | null | undefined): string | null {
  if (!part) return null;
  // The static export serves every dynamic route from one `_placeholder` page;
  // a draft keyed on it would be offered into the wrong client.
  if (part === "_placeholder") return null;
  return part.replace(/[^A-Za-z0-9_-]/g, "_");
}

/** The key for a scope, or `null` when any part is not yet known — which means
 *  "keep no draft", never "keep one under a half-formed key". */
export function draftKey(scope: DraftScope): string | null {
  const user = safePart(scope.userId);
  const client = safePart(scope.clientId);
  const entity = safePart(scope.entityId);
  if (!user || !client || !entity) return null;
  return `${DRAFT_PREFIX}${user}:${scope.kind}:${client}:${entity}`;
}

/** The tab's sessionStorage, or `null` where there is none or touching it throws. */
export function browserSessionStorage(): DraftStorage | null {
  try {
    if (typeof window === "undefined") return null;
    return window.sessionStorage ?? null;
  } catch {
    return null;
  }
}

export type SaveOutcome = "saved" | "too_large" | "unavailable";

export function saveDraft<T>(
  storage: DraftStorage | null, key: string | null, fields: T, now: number = Date.now(),
): SaveOutcome {
  if (!storage || !key) return "unavailable";
  try {
    const body: StoredDraft<T> = { v: 1, savedAt: new Date(now).toISOString(), fields };
    const text = JSON.stringify(body);
    if (text.length > MAX_DRAFT_CHARS) {
      // An over-large draft is dropped rather than half-kept: a stale smaller
      // one left behind would be offered as if it were the latest.
      storage.removeItem(key);
      return "too_large";
    }
    storage.setItem(key, text);
    return "saved";
  } catch {
    return "unavailable";
  }
}

export interface ReadDraft<T> {
  fields: T;
  savedAt: string;
}

/** The stored draft for `key`, rebuilt through `validate`; `null` when there is
 *  none, it is malformed, it is from another version, or it is too old. A draft
 *  that is unusable is REMOVED, so it is not re-read on every visit. */
export function readDraft<T>(
  storage: DraftStorage | null,
  key: string | null,
  validate: (raw: unknown) => T | null,
  now: number = Date.now(),
): ReadDraft<T> | null {
  if (!storage || !key) return null;
  try {
    const text = storage.getItem(key);
    if (text === null) return null;
    const drop = (): null => { try { storage.removeItem(key); } catch { /* nothing to do */ } return null; };
    if (text.length > MAX_DRAFT_CHARS) return drop();
    let parsed: unknown;
    try { parsed = JSON.parse(text); } catch { return drop(); }
    if (!parsed || typeof parsed !== "object") return drop();
    const body = parsed as Partial<StoredDraft<unknown>>;
    if (body.v !== 1 || typeof body.savedAt !== "string") return drop();
    const at = Date.parse(body.savedAt);
    if (Number.isNaN(at) || now - at > MAX_DRAFT_AGE_MS || at - now > 60_000) return drop();
    const fields = validate(body.fields);
    if (fields === null) return drop();
    return { fields, savedAt: body.savedAt };
  } catch {
    return null;
  }
}

export function clearDraft(storage: DraftStorage | null, key: string | null): void {
  if (!storage || !key) return;
  try { storage.removeItem(key); } catch { /* a draft that cannot be removed expires with the tab */ }
}

/** Remove every draft this module wrote — on sign-out, so the next person to
 *  use this tab is offered nothing of the last one's. */
export function clearAllDrafts(storage: DraftStorage | null): void {
  if (!storage) return;
  try {
    const doomed: string[] = [];
    for (let i = 0; i < storage.length; i++) {
      const k = storage.key(i);
      if (k && k.startsWith(DRAFT_PREFIX)) doomed.push(k);
    }
    doomed.forEach((k) => storage.removeItem(k));
  } catch { /* best effort */ }
}

// ─── building a validator ───────────────────────────────────────────────────

/** Field readers for `validate` functions. Each takes unknown and returns the
 *  typed value or `undefined`, so a validator reads as a list of fields and
 *  cannot let a number through where a string is expected. */
export const readField = {
  string(raw: unknown, maxLength = 2_000): string | undefined {
    return typeof raw === "string" && raw.length <= maxLength ? raw : undefined;
  },
  boolean(raw: unknown): boolean | undefined {
    return typeof raw === "boolean" ? raw : undefined;
  },
  finiteNumber(raw: unknown): number | undefined {
    return typeof raw === "number" && Number.isFinite(raw) ? raw : undefined;
  },
  record(raw: unknown): Record<string, unknown> | undefined {
    return raw && typeof raw === "object" && !Array.isArray(raw) ? (raw as Record<string, unknown>) : undefined;
  },
  /** An array of at most `max` items, or undefined. */
  list(raw: unknown, max = 500): unknown[] | undefined {
    return Array.isArray(raw) && raw.length <= max ? raw : undefined;
  },
};
