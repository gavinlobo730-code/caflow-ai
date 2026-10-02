/**
 * A same-tick repeat-click guard that does not wait for a render.
 *
 * THE DEFECT IT CLOSES (frontend_ux-09)
 *     `disabled={saving}` — a flag in React state — is the guard most screens
 *     here hand-rolled, and it lags the click by one render. Two click events
 *     dispatched back to back (a double-click, a trackpad double-tap that is
 *     physically one action and two browser events) are each run to completion
 *     before React commits the first one's `setSaving(true)`, so BOTH read
 *     `saving === false`, both pass validation and both reach the network. That
 *     is how one Post Entry produced eleven journals.
 *
 *     The guard has to be something a SECOND call can see on the same
 *     synchronous tick: a plain variable, set before the handler's first
 *     `await`. That is all this module is.
 *
 * THE RULES
 *   * A call while another is unresolved is IGNORED, not queued. A queued second
 *     Post would run after the first and write the same voucher again.
 *   * The guard is released when the promise SETTLES, on resolve or reject — an
 *     error must leave the CA able to retry — and a handler that THROWS before
 *     returning a promise releases it too.
 *   * A handler that returns something other than a promise is not an "async
 *     action": the guard is released at once and nothing is announced.
 *   * A REJECTION IS NOT SWALLOWED. `result` is the original promise's outcome,
 *     so a handler that throws still surfaces as an unhandled rejection exactly
 *     as a raw async `onClick` always did; this module only adds the guard.
 *
 * ONE FLIGHT MAY GUARD SEVERAL BUTTONS. Save Draft and Post Entry are two
 * controls over one action — a click on each in the same tick is two
 * vouchers — so a form creates one flight and hands it to both
 * (`components/ui/button.tsx`'s `flight` prop). The `owner` says which control
 * started it, so the others can show "disabled" while only the one that was
 * pressed shows "working".
 *
 * Pure TypeScript, no React and no DOM: `useSingleFlight` adapts it, and it is
 * unit-tested by plain `node --test`.
 */

export interface FlightState {
  /** True from the moment a promise-returning handler starts until it settles. */
  readonly busy: boolean;
  /** Who started the flight in progress, when the caller said. */
  readonly owner: string | null;
}

export type FlightResult<T> =
  | { started: false }
  | { started: true; result: T | Promise<T> };

export interface SingleFlight {
  /** The current state. The SAME object until the state changes, so it can be
   *  handed to `useSyncExternalStore` as a snapshot. */
  getState(): FlightState;
  /** Is a flight in progress? A synchronous read — no render sits between a
   *  call and what the next call sees. */
  busy(): boolean;
  subscribe(listener: () => void): () => void;
  /** Run `fn` unless a flight is already in progress. Returns whether it ran. */
  run<T>(fn: () => T | Promise<T>, owner?: string): FlightResult<T>;
}

const IDLE: FlightState = Object.freeze({ busy: false, owner: null });

/** The idle snapshot, for a server render that has nothing in flight. */
export function idleFlightState(): FlightState {
  return IDLE;
}

function isThenable(value: unknown): value is PromiseLike<unknown> {
  return (
    value !== null &&
    (typeof value === "object" || typeof value === "function") &&
    typeof (value as { then?: unknown }).then === "function"
  );
}

export function createSingleFlight(): SingleFlight {
  // Plain variables, deliberately: `active` is what a SECOND call reads on the
  // same tick, and `state` is the immutable view subscribers re-render from.
  let active = false;
  let state: FlightState = IDLE;
  const listeners = new Set<() => void>();

  const publish = (next: FlightState): void => {
    state = next;
    // Copy first: a listener may unsubscribe while it is being notified.
    Array.from(listeners).forEach((l) => l());
  };

  return {
    getState: () => state,
    busy: () => active,
    subscribe(listener) {
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    },
    run<T>(fn: () => T | Promise<T>, owner?: string): FlightResult<T> {
      if (active) return { started: false };
      active = true;

      let out: T | Promise<T>;
      try {
        out = fn();
      } catch (e) {
        // A handler that throws before it hands back a promise leaves nothing
        // in flight, or the button would be dead until the page reloaded.
        active = false;
        throw e;
      }

      if (!isThenable(out)) {
        active = false;
        return { started: true, result: out };
      }

      publish({ busy: true, owner: owner ?? null });
      const release = (): void => {
        active = false;
        publish(IDLE);
      };
      const settled = Promise.resolve(out).then(
        (value) => { release(); return value; },
        (error) => { release(); throw error; },
      );
      return { started: true, result: settled as Promise<T> };
    },
  };
}
