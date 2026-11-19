// What the page a sign-up link opens decides (POST-A-485, 497), kept apart from the page so each rule can be tested without a browser.
//
// The link is kept by the SERVER and says what it was asked for (the address, the firm's name and the person's name). The page asks first
// (`look`), signs nobody in, and waits for a press, so a mail scanner that opens the page spends nothing and a second click works.
//
//   checking       the page is asking the server what the link is for
//   ready          the link is live; one button signs the person in as the link's address and carries on to the wizard
//   other_account  this browser is signed in as somebody ELSE: say so, and ask before signing them out
//   gone           the link is expired, replaced by a newer one, or used up by creating the practice (the server says one sentence for all
//                  of them, because telling them apart would only let a stranger probe)
//   problem        the page could not ask, or the server could not sign in: the sentence says what, and the person may try again
//
// Dependency-free so it strips to plain JS for `node --experimental-strip-types`.

export type ContinueView = "checking" | "ready" | "other_account" | "gone" | "problem";

export type LinkState = "checking" | "live" | "gone" | "problem";

/** The server's one answer for a link that cannot be used (`services/signup_link_service.NOT_ACTIVE`). A Python test holds the two together. */
export const LINK_NOT_ACTIVE = /no longer active/i;

/** Whether two addresses are the same one: trimmed and not case-sensitive, and never equal when either is empty. */
export function sameAddress(a: string | null | undefined, b: string | null | undefined): boolean {
  const x = (a ?? "").trim().toLowerCase();
  const y = (b ?? "").trim().toLowerCase();
  return x !== "" && x === y;
}

/** What the page shows, from what the server said about the link and who this browser is signed in as. */
export function viewFor(input: { link: LinkState; signedInAs: string | null | undefined; linkAddress: string | null | undefined }): ContinueView {
  if (input.link === "checking") return "checking";
  if (input.link === "gone") return "gone";
  if (input.link === "problem") return "problem";
  const signedIn = (input.signedInAs ?? "").trim();
  if (signedIn !== "" && !sameAddress(signedIn, input.linkAddress)) return "other_account";
  return "ready";
}

/** How the press goes: a browser already signed in as the link's address has nothing to sign in to and carries on; any other signs in. */
export function pressFor(signedInAs: string | null | undefined, linkAddress: string | null | undefined): "carry_on" | "sign_in" {
  return sameAddress(signedInAs, linkAddress) ? "carry_on" : "sign_in";
}

/** The stash the wizard reads (`lib/auth/signupStash`), from what the SERVER says the link was asked for: the intent travels with the link,
 *  in whichever browser it is opened, and never depends on a note the browser that sent the form happened to keep. */
export function stashFrom(link: { email: string; firm_name: string; full_name: string }): { firmName: string; fullName: string; email: string } {
  return { firmName: link.firm_name, fullName: link.full_name, email: link.email };
}

/** Whether a stash holds everything a new link needs asking for with (the address and both names). */
export function canAskAgain(stash: { firmName?: string; fullName?: string; email?: string }): boolean {
  return !!(stash.email && stash.firmName && stash.fullName);
}
