/**
 * What a screen says when the firm's client list could not be read (POST-A-515 (d)).
 *
 * The client picker on a payroll or statement screen is filled from one read of the firm's clients. When that read failed the picker
 * simply stayed empty, and an empty picker reads as a firm with no clients (or, on the Schedule III screen, as one whose only choice is
 * "All Clients"). A list that could not be read is not a list with nothing in it, so the screen says so, once, beside the picker.
 */
export const CLIENT_LIST_UNREAD =
  "The list of clients could not be read, so no client can be chosen yet. It is not empty; reload this page to read it again.";
