// The one call a signed-in tab makes to say it is still being used (POST-A-486). Kept out of the session keeper on purpose: the keeper
// counts what a PERSON does (a key, a pointer, a touch), and a guard holds it free of any request of its own, because an API call
// must never count as activity. Best-effort and silent: a missed report only makes the session look quieter than it is.
export function reportSeen(): void {
  void import("@/lib/api").then(({ api }) => api.identity.sessionSeen()).catch(() => { /* best-effort */ });
}
