/**
 * How the dashboard reads the first-run checklist (market_and_trust-16).
 *
 * THE SERVER DECIDES EVERY TICK. `GET /api/onboarding/status` carries `first_run`,
 * built by `domain/onboarding/first_run` from the firm's own rows: a step is done when
 * the data says so, nothing is stored, and whether the card is `visible` at all is the
 * server's answer. This module computes none of that. It turns the payload into
 * something a `.map` cannot throw on, and it keeps the ONE thing that is the browser's
 * to know: which screen a step's button opens.
 *
 * THE STEP VOCABULARY IS PYTHON'S, THE ROUTE MAP IS THE BROWSER'S — the shape of
 * `lib/accounting/sourceDocument.ts`. A step the server sends that has no route here
 * renders without a link rather than disappearing, and
 * `tests/test_a_new_firm_is_walked_through_its_first_four_things.py` fails from the
 * Python side if a step has no route or a route has no step, so the two cannot drift
 * quietly in either direction.
 *
 * THREE STATES, AND THE THIRD IS NOT A TICK. `done` is `true`, `false` or `null`:
 * `null` means the server could not read that step, which is a different statement
 * from "not done". It renders as "could not check", never as an empty circle that
 * tells a firm to repeat what it has already done.
 */
import { arrayOrEmpty, objectOrNull } from "../api/shape.ts";

export interface FirstRunStep {
  id: string;
  title: string;
  why: string;
  /** `null` = the server could not read it — NOT the same as `false`. */
  done: boolean | null;
  done_at: string | null;
}

export interface FirstRunChecklist {
  steps: FirstRunStep[];
  total: number;
  done_count: number;
  complete: boolean;
  next_step: string | null;
  unreadable: string[];
  visible: boolean;
  minutes_to_first_invoice: number | null;
}

/**
 * The screen each step's button opens. Keyed by the step id the server sends; these are
 * existing screens (the Clients list, the Sales worklist, the Banking worklist, Team) —
 * a section of a client is a query parameter on an existing route, never a new one.
 */
export const STEP_ROUTES: Record<string, string> = {
  first_client: "/clients",
  first_invoice: "/accounting/invoices",
  first_statement: "/accounting/banking",
  invite_colleague: "/team",
};

export function hrefFor(stepId: string): string | null {
  return Object.prototype.hasOwnProperty.call(STEP_ROUTES, stepId) ? STEP_ROUTES[stepId] : null;
}

function stepOf(raw: unknown): FirstRunStep | null {
  const o = objectOrNull<Record<string, unknown>>(raw);
  if (!o || typeof o.id !== "string" || o.id === "") return null;
  return {
    id: o.id,
    title: typeof o.title === "string" ? o.title : o.id,
    why: typeof o.why === "string" ? o.why : "",
    // anything that is not exactly true or false is UNKNOWN, never a guess in either direction
    done: o.done === true ? true : o.done === false ? false : null,
    done_at: typeof o.done_at === "string" ? o.done_at : null,
  };
}

/**
 * The checklist out of the `/api/onboarding/status` payload, or `null` when the payload
 * has no usable `first_run` — which hides the card. A payload that is not the right shape
 * is NO DATA, not a crash (`lib/api/shape.ts`), and `{}` is not a checklist: `steps` is a
 * list the card maps over, so it is made one here rather than trusted.
 */
export function readFirstRun(data: unknown): FirstRunChecklist | null {
  const root = objectOrNull<Record<string, unknown>>(data);
  const fr = root ? objectOrNull<Record<string, unknown>>(root.first_run) : null;
  if (!fr) return null;
  const steps = arrayOrEmpty<unknown>(fr.steps)
    .map(stepOf)
    .filter((s): s is FirstRunStep => s !== null);
  return {
    steps,
    total: typeof fr.total === "number" ? fr.total : steps.length,
    done_count: typeof fr.done_count === "number" ? fr.done_count : steps.filter((s) => s.done === true).length,
    complete: fr.complete === true,
    next_step: typeof fr.next_step === "string" ? fr.next_step : null,
    unreadable: arrayOrEmpty<unknown>(fr.unreadable).filter((x): x is string => typeof x === "string"),
    // An absent `visible` is NOT visible: a frontend ahead of its backend must not
    // invent a card the server never asked for.
    visible: fr.visible === true,
    minutes_to_first_invoice:
      typeof fr.minutes_to_first_invoice === "number" ? fr.minutes_to_first_invoice : null,
  };
}

/** Whether the card shows at all: the server said so and there is something to list. */
export function shouldShow(checklist: FirstRunChecklist | null): checklist is FirstRunChecklist {
  return checklist !== null && checklist.visible && checklist.steps.length > 0;
}
