/**
 * A FIRM-LEVEL PAYROLL SCREEN OPENED FOR ONE CLIENT, WHICH MAY BE THE FIRM'S OWN PRACTICE (POST-A-534).
 *
 * The firm runs its own staff's payroll on the practice's own record (POST-A-532), and the practice is in no list of the
 * firm's clients (guardrail G2): every client picker reads `is_internal = false`. So the firm-level Statutory, Declarations
 * and Reports screens could not be opened for it at all. They take `?client=<id>` now, the address a client's own Payroll
 * page links with, the way Attendance has since PAY-15:
 *
 *   - an id that is one of the firm's listed clients is simply chosen;
 *   - the practice's own id is OFFERED ONLY WHEN THE SCREEN WAS OPENED FOR IT, named "My practice", and chosen. Arriving
 *     from the menu the picker is the firm's clients and nothing else, so the practice is still in no list of clients;
 *   - any other id is ignored. A stale or mistyped address leaves the screen as it opens from the menu, and never a 404.
 *
 * WHETHER AN ID IS THE PRACTICE IS THE SERVER'S ANSWER (`GET /api/practice`, Partner-only), never inferred from "it is
 * not in the client list": a client list that failed to load would name an ordinary client "My practice". The question is
 * asked only of a Partner, because the practice's own payroll is the Partner's alone (G4) and every payroll door refuses
 * anybody else whatever this screen does. The hook that asks is lib/payroll/useOpenedFor; this file is the rule alone, so
 * a test can read it without a browser.
 */
/** What the practice is called wherever a payroll screen names it. The attendance sheet uses the same words. */
export const MY_PRACTICE = "My practice";

export type PickerClient = { id: string; client_name: string };

export type OpenedForChoice = {
  /** What the picker offers: the firm's clients, with the practice first when the screen was opened for it. */
  clients: PickerClient[];
  /** The id to choose on arrival, or null where the address names nothing this screen can open. */
  choose: string | null;
  /** True when what was opened is the firm's own practice. */
  isPractice: boolean;
};

/** The rule above, as a function of what was read. `practiceId` is null until, and unless, the server names it. */
export function openedForChoice(clients: PickerClient[], openedFor: string, practiceId: string | null): OpenedForChoice {
  if (!openedFor) return { clients, choose: null, isPractice: false };
  if (clients.some((c) => c.id === openedFor)) return { clients, choose: openedFor, isPractice: false };
  if (practiceId && practiceId === openedFor) {
    return { clients: [{ id: practiceId, client_name: MY_PRACTICE }, ...clients], choose: practiceId, isPractice: true };
  }
  return { clients, choose: null, isPractice: false };
}

/** The address a client's Payroll page opens a firm-level payroll screen with. */
export function openedForHref(path: string, clientId: string): string {
  return `${path}?client=${encodeURIComponent(clientId)}`;
}
