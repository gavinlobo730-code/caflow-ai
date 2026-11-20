/**
 * THE GUIDED TIPS, ONCE (POST-A-531).
 *
 * The owner, on the live Test Firm on 20-11-2026: "I am the one who has been with you and I still do not know the software."
 * A tip is a short pop-up beside the thing it explains, on the screen that thing is on, shown once to each person until they
 * close it, with a switch in Settings to turn all of them off. This file is every tip there is.
 *
 * A TIP IS A CLAIM ABOUT A SCREEN, SO IT IS HELD TO THE SCREEN. Each tip names:
 *   - `anchor`: the value of a `data-tip` attribute, and `source`: the file that carries it. The guard
 *     (`scripts/a-guided-tip-points-at-something-on-its-screen.test.ts`) fails a tip whose anchor is not in that file, and an
 *     anchor in the tree that no tip uses.
 *   - `holds`: every label the words quote (“Add Client”), with the file it is written in. The guard fails a quoted label
 *     that is not held, and a held label its file no longer contains. So a button that is renamed breaks the tip that names
 *     it on the same pull request, the way a sentence on the public site is held to the code.
 * What a tip may say: where something is and what pressing it does. It gives no statutory figure, date or rate, and it
 * promises nothing the product does not do.
 *
 * THE SERVER KEEPS WHO HAS CLOSED WHAT (`/api/guided-tips`), by `id`. An id is a slug, never reused for a different tip: a
 * person who closed the old one would never see the new one. To reword a tip, keep its id; to replace it, give the new one
 * a new id and delete the old.
 *
 * `roles`: who the tip is for, where the thing it points at is only drawn for some roles. It decides nothing about access;
 * it keeps the "Next" link from sending a person to a screen where they will be shown nothing.
 */
import type { UserRole } from "@/lib/auth/permissions";

export interface HeldLabel {
  /** The label exactly as the screen writes it, and as the tip quotes it between “ and ”. */
  text: string;
  /** The file under apps/web that writes it. */
  file: string;
}

export interface Tip {
  id: string;
  /** The screen's address, with no trailing slash. */
  path: string;
  anchor: string;
  source: string;
  title: string;
  body: string;
  holds: HeldLabel[];
  roles?: readonly UserRole[];
}

/**
 * The order of the screens a person is walked through. A tip's "Next" link goes to the next screen in this list that still
 * has a tip this person has not closed, so the tour is one path however many tips a screen carries.
 */
export const TOUR: readonly string[] = ["/", "/clients", "/deadlines", "/practice", "/practice/billing"];

/** What each stop of the tour is called on the "Next" link that leads to it. */
export const TOUR_LABELS: Readonly<Record<string, string>> = {
  "/": "the dashboard",
  "/clients": "your clients",
  "/deadlines": "deadlines",
  "/practice": "your own firm's books",
  "/practice/billing": "billing your clients",
};

export const TIPS: readonly Tip[] = [
  {
    id: "start-menu",
    path: "/",
    anchor: "workspace-menu",
    source: "components/shell/WorkspaceTopBar.tsx",
    title: "Everything opens from this menu",
    body: "This button opens the whole product: “Clients”, “Deadlines”, “Accounting”, “Payroll” and the rest. “My practice” is your own firm: its books, its billing and its revenue.",
    holds: [
      { text: "Clients", file: "lib/workspace/workspaceConfig.ts" },
      { text: "Deadlines", file: "lib/workspace/workspaceConfig.ts" },
      { text: "Accounting", file: "lib/workspace/workspaceConfig.ts" },
      { text: "Payroll", file: "lib/workspace/workspaceConfig.ts" },
      { text: "My practice", file: "lib/workspace/workspaceConfig.ts" },
    ],
  },
  {
    id: "start-search",
    path: "/",
    anchor: "open-search",
    source: "components/shell/UtilityCluster.tsx",
    title: "Find anything by name",
    body: "Search finds a client, a screen or a document from wherever you are. Ctrl+K opens it from the keyboard (Command+K on a Mac).",
    holds: [],
  },
  {
    id: "add-client",
    path: "/clients",
    anchor: "add-client",
    source: "app/clients/page.tsx",
    title: "Start with a client",
    body: "“Add Client” creates one client. Each client has a workspace of its own, where its books, returns, payroll and documents are kept apart from every other client's.",
    holds: [{ text: "Add Client", file: "app/clients/page.tsx" }],
    roles: ["Partner", "Manager"],
  },
  {
    id: "deadlines-triage",
    path: "/deadlines",
    anchor: "deadline-counts",
    source: "app/deadlines/page.tsx",
    title: "Your clients' due dates in one place",
    body: "This screen brings your clients' compliance dates into one list. Decide here what to work on; each return is prepared inside its client's own workspace.",
    holds: [],
  },
  {
    // The id is kept from when this tip sat on the Accounting overview's "Practice books" button: a person who closed it
    // there has been told where the firm's own books are, and is not told again.
    id: "own-books",
    path: "/practice",
    anchor: "practice-menu",
    source: "components/shell/ClientTopBar.tsx",
    title: "Everything about your own firm is here",
    body: "This is “My practice”. Your firm is kept as a client of itself, so it has the same books a client has, with its fee billing, its own payroll and what it earns. The button this tip points at opens every part of it. Only a Partner sees it.",
    holds: [{ text: "My practice", file: "components/shell/ClientTopBar.tsx" }],
    roles: ["Partner"],
  },
  {
    id: "billing-schedule",
    path: "/practice/billing",
    anchor: "new-billing-schedule",
    source: "app/practice/billing/page.tsx",
    title: "Bill a client on a schedule",
    body: "“New schedule” sets up what you bill a client and how often. “Generate draft” on a schedule's row prepares that period's invoice as a draft in your own firm's books; nothing reaches the client until you issue it.",
    holds: [
      { text: "New schedule", file: "app/practice/billing/page.tsx" },
      { text: "Generate draft", file: "app/practice/billing/page.tsx" },
    ],
    roles: ["Partner"],
  },
];
