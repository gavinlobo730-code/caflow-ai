// The way to add a client from anywhere in the product (POST-A-488).
//
// "Add Client" lived on the Clients page alone, so a tester who looked for it in the client dropdown or in the sidebar's
// Clients panel did not find it and reported that there was no way to add a company. The form is that page's (it holds
// the list the new client joins, and the list is where the person lands), so the other places are LINKS to it: the page
// opens the form when the address asks for it and removes the request from the address at once, so a reload does not
// open it again.
//
// WHO IS OFFERED IT is the server's own answer, `can("client", "write")` (a Manager or a Partner: `rbac("client","write")`
// on every client route and the same pair in the database's policy), read from the permission map and never from a role
// list copied here. A member without it sees no way in, because the form would only end in a refusal.
//
// Dependency-free so it strips to plain JS for `node --experimental-strip-types`.

/** The Clients page's address with the request to open the new-client form. A trailing slash: the site is exported with them. */
export const ADD_CLIENT_HREF = "/clients/?add=1";

/** The words every entry point shows. */
export const ADD_CLIENT_LABEL = "Add a new client";

/** Whether an address's query string (`window.location.search`) asks for the new-client form. */
export function wantsToAddClient(search: string): boolean {
  try {
    return new URLSearchParams(search).get("add") === "1";
  } catch {
    return false;
  }
}
