// What the sign-up wizard remembers about a person between one mount of the
// page and the next (POST-A-478).
//
// Saving a password makes the sign-in service announce a change. AuthContext
// answers every such change by setting the sign-in assurance to "unresolved",
// and AuthGuard renders nothing while it is (guardDecision.mayRenderProtected:
// unresolved is not permission), so the wizard is UNMOUNTED for a round trip
// and mounts again at step 1 with every box empty, having just saved the
// password. Seen live on 18-11-2026 at 17:05 IST: the update was accepted (200)
// and the screen came back to "Create your password" with no error, and typing
// the same password again is refused as the same password. A tester saved his
// password eight times in eight minutes for the same reason.
//
// The guard's rule is right and stays. The wizard's own memory has to survive
// it, so what the person has DONE lives HERE, outside the component, in a
// module that outlives the remount and in session storage that outlives a
// reload. It is keyed on the signed-in person's id, so it is never read for
// somebody else, and it holds no secret: flags, never the password.
//
// Three facts are kept, because three remounts are possible:
//   passwordSet   the password step is done: a remount goes on to step 2 (once the person's name is known);
//   firmCreated   step 2 created the firm: a remount goes on to step 3, never back to a blank step 2 whose save would
//                 overwrite the profile just entered;
//   reauthPending a verification code was emailed and the person went to read it, which signs them in again and
//                 remounts the page: the code box comes back (the password has to be typed again, it is never kept).
//
// Dependency-free so it strips to plain JS for `node --experimental-strip-types`.

export interface OnboardingProgress {
  /** The signed-in person this belongs to. */
  userId: string;
  passwordSet: boolean;
  firmCreated: boolean;
  reauthPending: boolean;
}

/** The slice of the browser's Storage the store uses, so a test can supply its own. */
export interface ProgressStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

export const ONBOARDING_PROGRESS_KEY = "practicesync_onboarding_progress";

export interface OnboardingProgressStore {
  /** The same object until something changes, which `useSyncExternalStore` requires. */
  get(): OnboardingProgress | null;
  subscribe(listener: () => void): () => void;
  markPasswordSet(userId: string): void;
  markFirmCreated(userId: string): void;
  markReauthPending(userId: string, pending: boolean): void;
  clear(): void;
}

function parse(raw: string | null): OnboardingProgress | null {
  if (!raw) return null;
  try {
    const v: unknown = JSON.parse(raw);
    if (v && typeof v === "object") {
      const o = v as Record<string, unknown>;
      if (typeof o.userId === "string" && o.userId !== "") {
        const p: OnboardingProgress = {
          userId: o.userId,
          passwordSet: o.passwordSet === true,
          firmCreated: o.firmCreated === true,
          reauthPending: o.reauthPending === true,
        };
        if (p.passwordSet || p.firmCreated || p.reauthPending) return p;
      }
    }
  } catch {
    // An unreadable value is no progress, not an error to show.
  }
  return null;
}

export function createOnboardingProgressStore(getStorage: () => ProgressStorage | null): OnboardingProgressStore {
  let current: OnboardingProgress | null | undefined; // undefined = not read yet
  const listeners = new Set<() => void>();

  function storage(): ProgressStorage | null {
    try { return getStorage(); } catch { return null; }
  }
  function notify() { listeners.forEach((l) => l()); }

  // Plain functions, not methods: `useSyncExternalStore(store.subscribe, store.get)`
  // hands them over unbound.
  function get(): OnboardingProgress | null {
    if (current === undefined) {
      try { current = parse(storage()?.getItem(ONBOARDING_PROGRESS_KEY) ?? null); } catch { current = null; }
    }
    return current;
  }
  function subscribe(listener: () => void): () => void {
    listeners.add(listener);
    return () => { listeners.delete(listener); };
  }
  /** Merge a change into THIS person's record (another person's record is replaced, never mixed). */
  function change(userId: string, patch: Partial<Omit<OnboardingProgress, "userId">>): void {
    if (!userId) return;
    const now = get();
    const base: OnboardingProgress = now && now.userId === userId
      ? now
      : { userId, passwordSet: false, firmCreated: false, reauthPending: false };
    const next: OnboardingProgress = { ...base, ...patch };
    if (next.passwordSet === base.passwordSet && next.firmCreated === base.firmCreated
        && next.reauthPending === base.reauthPending && base === now) return;
    current = (next.passwordSet || next.firmCreated || next.reauthPending) ? next : null;
    try {
      if (current) storage()?.setItem(ONBOARDING_PROGRESS_KEY, JSON.stringify(current));
      else storage()?.removeItem(ONBOARDING_PROGRESS_KEY);
    } catch { /* storage is a convenience */ }
    notify();
  }
  function markPasswordSet(userId: string): void { change(userId, { passwordSet: true, reauthPending: false }); }
  function markFirmCreated(userId: string): void { change(userId, { firmCreated: true }); }
  function markReauthPending(userId: string, pending: boolean): void { change(userId, { reauthPending: pending }); }
  function clear(): void {
    if (get() === null) return;
    current = null;
    try { storage()?.removeItem(ONBOARDING_PROGRESS_KEY); } catch { /* storage is a convenience */ }
    notify();
  }

  return { get, subscribe, markPasswordSet, markFirmCreated, markReauthPending, clear };
}

/** The progress that belongs to this person, or null. */
export function progressFor(progress: OnboardingProgress | null, userId: string | null | undefined): OnboardingProgress | null {
  return progress && userId && progress.userId === userId ? progress : null;
}

/** Whether `progress` says this person's password is already set. */
export function passwordIsSetFor(progress: OnboardingProgress | null, userId: string | null | undefined): boolean {
  return progressFor(progress, userId)?.passwordSet === true;
}

/**
 * Where a wizard that has just mounted should stand (1, 2 or 3).
 *
 *   - nothing remembered for this person: step 1, as ever;
 *   - the firm was created: step 3 (its profile was saved with it; step 2 again would show a blank form whose save
 *     overwrites it);
 *   - the password is set and the person's name is known: step 2;
 *   - the password is set but no name is known (the sign-up stash was not in this browser): STAY on step 1, which then
 *     offers Continue and the name box, because a firm made without a name is made in the person's email address.
 */
export function restoredStep(args: {
  progress: OnboardingProgress | null;
  userId: string | null | undefined;
  ownerName: string;
}): 1 | 2 | 3 {
  const p = progressFor(args.progress, args.userId);
  if (!p) return 1;
  if (p.firmCreated) return 3;
  if (p.passwordSet && args.ownerName.trim() !== "") return 2;
  return 1;
}

function browserSessionStorage(): ProgressStorage | null {
  return typeof window === "undefined" ? null : window.sessionStorage;
}

/** The wizard's one store, in this browser tab's session storage. */
export const onboardingProgress: OnboardingProgressStore = createOnboardingProgressStore(browserSessionStorage);
