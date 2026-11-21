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

/** The firm's own practice: a second list, in a Partner's answer only (POST-A-533). */
export interface PracticeChecklist {
  steps: FirstRunStep[];
  total: number;
  done_count: number;
  complete: boolean;
  next_step: string | null;
  unreadable: string[];
  /** The practice's own record, for the links; `null` while the practice is not set up. */
  client_id: string | null;
}

export interface FirstRunChecklist {
  steps: FirstRunStep[];
  total: number;
  done_count: number;
  complete: boolean;
  next_step: string | null;
  unreadable: string[];
  visible: boolean;
  /** Whether THIS person dismissed the card for good (POST-A-002). `null` = the server could not read it, which is not a dismissal. */
  dismissed: boolean | null;
  minutes_to_first_invoice: number | null;
  /** `null` for everybody but a Partner, and when the server sent no usable list. */
  practice: PracticeChecklist | null;
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

/**
 * The screen each step of the firm's own practice opens (POST-A-533). They are screens of My practice: the fixed practice
 * screens, and the practice's own client workspace, whose address needs the practice's record id. While the practice is
 * not set up there is no workspace to open, and every step leads to Practice home, which is where it is set up.
 * `tests/test_a_partner_is_walked_through_the_firms_own_practice.py` holds the keys equal to Python's step ids.
 */
export const PRACTICE_STEP_ROUTES: Record<string, (practiceId: string | null) => string> = {
  practice_identity: () => "/practice",
  practice_books: (practiceId) => (practiceId ? `/clients/${practiceId}/accounting?tab=opening-balances` : "/practice"),
  practice_statement: (practiceId) => (practiceId ? `/clients/${practiceId}/bank` : "/practice"),
  practice_fee_bill: () => "/practice/billing",
};

export function practiceHrefFor(stepId: string, practiceId: string | null): string | null {
  return Object.prototype.hasOwnProperty.call(PRACTICE_STEP_ROUTES, stepId) ? PRACTICE_STEP_ROUTES[stepId](practiceId) : null;
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
/** The practice's list out of `first_run.practice`, or `null` when it is absent, not an object or has no steps. */
function practiceOf(raw: unknown): PracticeChecklist | null {
  const o = objectOrNull<Record<string, unknown>>(raw);
  if (!o) return null;
  const steps = arrayOrEmpty<unknown>(o.steps).map(stepOf).filter((s): s is FirstRunStep => s !== null);
  if (steps.length === 0) return null;
  return {
    steps,
    total: typeof o.total === "number" ? o.total : steps.length,
    done_count: typeof o.done_count === "number" ? o.done_count : steps.filter((s) => s.done === true).length,
    complete: o.complete === true,
    next_step: typeof o.next_step === "string" ? o.next_step : null,
    unreadable: arrayOrEmpty<unknown>(o.unreadable).filter((x): x is string => typeof x === "string"),
    client_id: typeof o.client_id === "string" && o.client_id !== "" ? o.client_id : null,
  };
}

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
    // Only an exact boolean is a statement; anything else is "could not tell", never a guess in either direction.
    dismissed: fr.dismissed === true ? true : fr.dismissed === false ? false : null,
    minutes_to_first_invoice:
      typeof fr.minutes_to_first_invoice === "number" ? fr.minutes_to_first_invoice : null,
    practice: practiceOf(fr.practice),
  };
}

/** What the card counts: both lists for a Partner, the four steps for everybody else. */
export function progressOf(checklist: FirstRunChecklist): { done: number; total: number } {
  const p = checklist.practice;
  return { done: checklist.done_count + (p ? p.done_count : 0), total: checklist.total + (p ? p.total : 0) };
}

/** The one step marked "Start here": the clients' next step, and the practice's only when the clients' list has none. */
export function startHere(checklist: FirstRunChecklist): string | null {
  return checklist.next_step ?? checklist.practice?.next_step ?? null;
}

/** Whether the card shows at all: the server said so and there is something to list. */
export function shouldShow(checklist: FirstRunChecklist | null): checklist is FirstRunChecklist {
  return checklist !== null && checklist.visible && checklist.steps.length > 0;
}
