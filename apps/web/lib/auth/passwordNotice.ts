// A "password updated" sentence that survives the page being unmounted while it was being set (POST-A-493).
//
// Saving a password on Settings > Security first proves the current one with signInWithPassword, which REPLACES the browser's
// session with a new one: the sign-in service announces SIGNED_IN with a different token, and that is an announcement the guard
// must read afresh (it may be a new session at a lower level), so the page under it is unmounted and mounted again. The request is
// still in flight; its answer finds the old page gone, and the sentence that says the password was saved was set on nothing, so it
// was never shown. The wizard solved the same thing by keeping its memory outside the component; this is that, for one sentence.
//
// A SENTENCE, ONCE. It is written only when the page that asked is no longer there, and read, and forgotten, by the next page that
// mounts. A page that is still mounted shows its own sentence and writes nothing, so a notice never outlives the visit it belongs to.
//
// Dependency-free so it strips to plain JS for `node --experimental-strip-types`.

let pending: string | null = null;

export function rememberPasswordNotice(sentence: string): void {
  pending = sentence;
}

/** The sentence a previous, unmounted page left, once; null when there is none. */
export function takePasswordNotice(): string | null {
  const s = pending;
  pending = null;
  return s;
}
