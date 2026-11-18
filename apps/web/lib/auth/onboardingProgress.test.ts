// node --experimental-strip-types --test lib/auth/onboardingProgress.test.ts
//
// POST-A-478. Saving a password makes AuthGuard unmount the sign-up wizard for
// a round trip, so it mounted again at step 1 with the password already set.
// What the wizard knows has to live outside the component.
import test from "node:test";
import assert from "node:assert/strict";
import {
  ONBOARDING_PROGRESS_KEY,
  createOnboardingProgressStore,
  passwordIsSetFor,
  progressFor,
  restoredStep,
  type ProgressStorage,
} from "./onboardingProgress.ts";

function fakeStorage(initial: Record<string, string> = {}): ProgressStorage & { data: Record<string, string> } {
  const data = { ...initial };
  return {
    data,
    getItem: (k) => (k in data ? data[k] : null),
    setItem: (k, v) => { data[k] = v; },
    removeItem: (k) => { delete data[k]; },
  };
}

test("nothing is remembered until a password is set", () => {
  const store = createOnboardingProgressStore(() => fakeStorage());
  assert.equal(store.get(), null);
  assert.equal(passwordIsSetFor(store.get(), "u1"), false);
});

test("a password set before a remount is still set after it: a second instance over the same storage reads it", () => {
  const storage = fakeStorage();
  const first = createOnboardingProgressStore(() => storage);
  first.markPasswordSet("u1");
  // A reload builds a new module instance over the same session storage.
  const second = createOnboardingProgressStore(() => storage);
  assert.equal(passwordIsSetFor(second.get(), "u1"), true);
});

test("the SAME store answers a component that mounts after the flag was written (the remount that does not reload)", () => {
  const store = createOnboardingProgressStore(() => null);
  store.markPasswordSet("u1");
  assert.equal(passwordIsSetFor(store.get(), "u1"), true);
});

test("it is never read for somebody else", () => {
  const store = createOnboardingProgressStore(() => fakeStorage());
  store.markPasswordSet("u1");
  assert.equal(passwordIsSetFor(store.get(), "u2"), false);
  assert.equal(passwordIsSetFor(store.get(), null), false);
  assert.equal(passwordIsSetFor(store.get(), undefined), false);
  assert.equal(passwordIsSetFor(null, "u1"), false);
});

test("a subscriber hears about a change, and the snapshot is the same object until something changes", () => {
  const store = createOnboardingProgressStore(() => fakeStorage());
  let heard = 0;
  const off = store.subscribe(() => { heard += 1; });
  store.markPasswordSet("u1");
  const a = store.get();
  assert.equal(heard, 1);
  store.markPasswordSet("u1"); // nothing new
  assert.equal(heard, 1);
  assert.equal(store.get(), a);
  off();
  store.clear();
  assert.equal(heard, 1);
  assert.equal(store.get(), null);
});

test("clear removes it from storage as well", () => {
  const storage = fakeStorage();
  const store = createOnboardingProgressStore(() => storage);
  store.markPasswordSet("u1");
  assert.ok(ONBOARDING_PROGRESS_KEY in storage.data);
  store.clear();
  assert.ok(!(ONBOARDING_PROGRESS_KEY in storage.data));
});

test("a stored value that is not a progress record is no progress", () => {
  for (const raw of ["", "not json", "null", "[]", '{"userId":"u1"}', '{"userId":"","passwordSet":true}', '{"userId":"u1","passwordSet":false}',
                     '{"userId":"u1","passwordSet":"yes"}', '{"userId":5,"passwordSet":true}']) {
    const store = createOnboardingProgressStore(() => fakeStorage({ [ONBOARDING_PROGRESS_KEY]: raw }));
    assert.equal(store.get(), null, raw);
  }
});

test("storage that throws is a convenience that failed, never an error", () => {
  const throwing: ProgressStorage = {
    getItem() { throw new Error("blocked"); },
    setItem() { throw new Error("blocked"); },
    removeItem() { throw new Error("blocked"); },
  };
  const store = createOnboardingProgressStore(() => throwing);
  assert.equal(store.get(), null);
  store.markPasswordSet("u1");
  assert.equal(passwordIsSetFor(store.get(), "u1"), true);
  store.clear();
  assert.equal(store.get(), null);
  const noStorage = createOnboardingProgressStore(() => { throw new Error("no window"); });
  noStorage.markPasswordSet("u1");
  assert.equal(passwordIsSetFor(noStorage.get(), "u1"), true);
});

test("an empty id is not remembered", () => {
  const store = createOnboardingProgressStore(() => fakeStorage());
  store.markPasswordSet("");
  assert.equal(store.get(), null);
});

test("a firm created and a reauthentication pending are remembered with the password, for this person only", () => {
  const storage = fakeStorage();
  const store = createOnboardingProgressStore(() => storage);
  store.markPasswordSet("u1");
  store.markReauthPending("u1", true);
  assert.deepEqual(store.get(), { userId: "u1", passwordSet: true, firmCreated: false, reauthPending: true });
  // saving the password ends the pending code
  store.markPasswordSet("u1");
  assert.equal(store.get()?.reauthPending, false);
  store.markFirmCreated("u1");
  const reloaded = createOnboardingProgressStore(() => storage);
  assert.deepEqual(reloaded.get(), { userId: "u1", passwordSet: true, firmCreated: true, reauthPending: false });
  // another person's mark replaces the record, never mixes into it
  store.markPasswordSet("u2");
  assert.deepEqual(store.get(), { userId: "u2", passwordSet: true, firmCreated: false, reauthPending: false });
  assert.equal(progressFor(store.get(), "u1"), null);
});

test("clearing a pending code with nothing else remembered leaves no record at all", () => {
  const storage = fakeStorage();
  const store = createOnboardingProgressStore(() => storage);
  store.markReauthPending("u1", true);
  assert.ok(ONBOARDING_PROGRESS_KEY in storage.data);
  store.markReauthPending("u1", false);
  assert.equal(store.get(), null);
  assert.ok(!(ONBOARDING_PROGRESS_KEY in storage.data));
});

test("restoredStep: nothing remembered is step 1, a set password with a name is step 2, a created firm is step 3", () => {
  const store = createOnboardingProgressStore(() => fakeStorage());
  assert.equal(restoredStep({ progress: store.get(), userId: "u1", ownerName: "Asha" }), 1);
  store.markPasswordSet("u1");
  assert.equal(restoredStep({ progress: store.get(), userId: "u1", ownerName: "Asha" }), 2);
  store.markFirmCreated("u1");
  assert.equal(restoredStep({ progress: store.get(), userId: "u1", ownerName: "Asha" }), 3);
  // ... never for somebody else, and never before the person is known
  assert.equal(restoredStep({ progress: store.get(), userId: "u2", ownerName: "Asha" }), 1);
  assert.equal(restoredStep({ progress: store.get(), userId: null, ownerName: "Asha" }), 1);
});

test("restoredStep: a set password with no name stays on step 1, because a firm made without one is made in the email address", () => {
  const store = createOnboardingProgressStore(() => fakeStorage());
  store.markPasswordSet("u1");
  assert.equal(restoredStep({ progress: store.get(), userId: "u1", ownerName: "" }), 1);
  assert.equal(restoredStep({ progress: store.get(), userId: "u1", ownerName: "   " }), 1);
  // the created firm wins over a missing name: the name was needed to create it
  store.markFirmCreated("u1");
  assert.equal(restoredStep({ progress: store.get(), userId: "u1", ownerName: "" }), 3);
});
