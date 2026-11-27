/**
 * THE SETTINGS GROUPS, ONCE (PRE-A-023).
 *
 * Settings was one column of fourteen cards in no order a practice would recognise, and the owner, looking for
 * the security status on 16-11-2026, could not find it: it sat behind a card titled Security whose only link read
 * "Manage 2FA". The owner asked for it grouped the way a practice thinks, with the groups as tabs across the top of
 * the page (the platform's own navigation is a bar across the top, never a left-hand panel).
 *
 * This module is the one list. The tab row across every Settings page (`components/settings/SettingsTabs.tsx`),
 * the Settings home's tab content and the Settings panel inside the workspace menu all read it, so a screen added
 * to one cannot be missing from the others. It moves no page: every screen keeps the address it had, and a tab is
 * the Settings home with `?tab=` (no new route, so no redirect rule).
 *
 * WHO IS SHOWN A LINK IS THE ONE TABLE'S ANSWER (POST-A-545). Each link used to repeat the roles its page's own role guard
 * admitted. The pages now follow the permissions a Partner ticks, like every other firm screen: a link is listed when
 * `mayOpen` (`lib/access/screenAccess.ts`) opens its address, which is the pair the page's own read asks on the server. So a
 * link, the page gate and the "Where is…?" guide cannot disagree, and a tick a Partner changes moves all three. A link to a
 * CARD on a page (a fragment) names the pair that card is shown on (`requires`), since the table knows pages and not cards.
 * It decides nothing about access: the server's permission check is what refuses.
 */

import { mayOpen, type Asker, type Pair } from "../access/screenAccess.ts";

export type SettingsGroupId = "profile" | "firm" | "security" | "documents" | "statutory" | "ai";

export interface SettingsLink {
  /** The page's address, unchanged from before the redesign. */
  href: string;
  /** What the link opens, in words a CA would use. */
  label: string;
  /** One sentence saying what is there. */
  says: string;
  /**
   * For a link to a CARD on a page (its address carries a fragment): the pair that card is shown on. A link to a page names
   * none, because the one table answers for the page.
   */
  requires?: Pair;
}

export interface SettingsGroup {
  id: SettingsGroupId;
  /** The tab's words. */
  label: string;
  /** One line under the tab row saying what the group holds. */
  says: string;
  links: SettingsLink[];
  /**
   * What the Settings home shows above the links on this tab, rendered by the page itself: the forms that save
   * in place rather than on a page of their own.
   */
  inline?: Array<"personal-profile" | "firm-profile" | "financial-year">;
}

export const SETTINGS_GROUPS: readonly SettingsGroup[] = [
  {
    id: "profile",
    label: "Your profile",
    says: "Your name, your password and the authenticator app you sign in with.",
    inline: ["personal-profile"],
    links: [
      {
        href: "/settings/security",
        label: "Password and authenticator app",
        says: "Change your password, and set up or replace the authenticator app you sign in with.",
      },
    ],
  },
  {
    id: "firm",
    label: "The firm",
    says: "The practice's own details, its financial year, its team, the currencies it records and who approves manual journals.",
    inline: ["firm-profile", "financial-year"],
    links: [
      {
        href: "/team",
        label: "Team and roles",
        says: "Invite colleagues, set each one's role and choose which clients each can open.",
      },
      {
        href: "/settings/multi-currency",
        label: "Foreign currency",
        says: "Whether this firm records foreign-currency documents at all, and which clients may. Off unless a Partner switches it on.",
      },
      {
        href: "/settings/journal-approval",
        label: "Journal approval",
        says: "Whether every manual journal waits for someone who may approve journal entries before it reaches a client's books. Off unless it is switched on.",
      },
    ],
  },
  {
    id: "security",
    label: "Security and access",
    says: "How sign-in is protected, how this deployment is set up, who can reach what, and the record of changes.",
    links: [
      {
        href: "/settings/security",
        label: "Your authenticator app and password",
        says: "Set up or replace the authenticator app, and change your password.",
      },
      {
        href: "/settings/security#deployment",
        label: "How this deployment is set up",
        says: "The security settings this deployment is running with, read from the server, with what each one means.",
        // The card on that page is shown to whoever may administer the firm (`can("firm", "admin")` there).
        requires: ["firm", "admin"],
      },
      {
        href: "/team",
        label: "Team access",
        says: "Each member's role, the clients they are assigned and anything a Partner has added or blocked for them.",
      },
      {
        href: "/settings/audit-log",
        label: "Audit log",
        says: "Who created, changed or deleted a client, a document or a ledger entry, and when.",
      },
    ],
  },
  {
    id: "documents",
    label: "Invoices and documents",
    says: "What the practice's own invoices look like and are numbered, the mails it sends, and the codes it bills against.",
    links: [
      {
        href: "/settings/branding",
        label: "Branding",
        says: "Logo, tagline and primary colour for your practice's own invoices; the other settings are kept on file.",
      },
      {
        href: "/settings/invoice-settings",
        label: "Invoice numbering and payment details",
        says: "Invoice numbering format, bank details, UPI and footer text.",
      },
      {
        href: "/settings/invoice-templates",
        label: "Invoice templates",
        says: "Where the logo and the signature sit on your practice's own invoices.",
      },
      {
        href: "/settings/email-templates",
        label: "Email templates",
        says: "The wording of the mails sent for invoices, engagements, documents and reminders.",
      },
      {
        href: "/settings/firm-hsn-library",
        label: "HSN and SAC codes",
        says: "The HSN and SAC codes your firm bills against. You keep this list; nothing is suggested or shipped.",
      },
      {
        href: "/settings/scheduled-reports",
        label: "Scheduled reports",
        says: "Plan which reports go to which clients, and when. Sending them is coming soon: nothing is emailed automatically yet.",
      },
    ],
  },
  {
    id: "statutory",
    label: "Tax and statutory values",
    says: "The statutory figures your firm records once for every client, and the clients' digital signature certificates.",
    links: [
      {
        href: "/settings/statutory-values",
        label: "Professional tax and other statutory values",
        says: "Your firm's reading of the state professional-tax notifications. Four states are built in; the rest deduct nothing until you record them here.",
      },
      {
        href: "/settings/treaty-rates",
        label: "DTAA treaty rates",
        says: "Your firm's reading of the treaty rates it withholds under, per country and nature of income. Empty until you record them.",
      },
      {
        href: "/settings/dsc-tracker",
        label: "DSC tracker",
        says: "The clients' digital signature certificates and when each one expires.",
      },
    ],
  },
  {
    id: "ai",
    label: "AI and connections",
    says: "Whether the AI features can reach their providers, and the firm's own monthly allowance.",
    links: [
      {
        href: "/settings/ai",
        label: "PracticeSync AI status and allowance",
        says: "Whether PracticeSync AI (the assistant, the copilot and the invoice and notice readers) can reach its two providers, and the firm's monthly allowance.",
      },
    ],
  },
];

const IDS: readonly string[] = SETTINGS_GROUPS.map((g) => g.id);

/** The group a `?tab=` value names, or the first group when it names none. */
export function groupFromTab(tab: string | null | undefined): SettingsGroupId {
  return tab && IDS.includes(tab) ? (tab as SettingsGroupId) : "profile";
}

/** The address of a tab: the Settings home, with `?tab=` for every group but the first. */
export function settingsTabHref(id: SettingsGroupId): string {
  return id === "profile" ? "/settings" : `/settings?tab=${id}`;
}

function pathOf(href: string): string {
  const cut = href.split("#")[0].split("?")[0];
  return cut.length > 1 ? cut.replace(/\/+$/, "") : cut;
}

/**
 * The group a Settings page belongs to, so its tab is the lit one. On the Settings home it is the `?tab=` value;
 * on any other page it is the LAST group that lists the page, because Your profile repeats one link that Security
 * and access owns (the password and authenticator page) and that page belongs with security. A page no group
 * lists lights no tab.
 */
export function groupForPage(pathname: string, tab: string | null | undefined): SettingsGroupId | null {
  const path = pathOf(pathname);
  if (path === "/settings") return groupFromTab(tab);
  const owners = SETTINGS_GROUPS.filter((g) => g.links.some((l) => pathOf(l.href) === path));
  return owners.length ? owners[owners.length - 1].id : null;
}

/** Every distinct page the groups link to, without fragments: what the Settings panel lists. */
export function everySettingsPage(): string[] {
  const seen: string[] = [];
  for (const g of SETTINGS_GROUPS) {
    for (const l of g.links) {
      const p = pathOf(l.href);
      if (!seen.includes(p)) seen.push(p);
    }
  }
  return seen;
}

/** The signed-in person as the one table asks about them (`useScreenAccess()` returns exactly this, and more). */
export interface SettingsAsker {
  who: Asker;
  /** False until the permissions are known. */
  resolved: boolean;
}

/** UNTIL THE PERMISSIONS ARE KNOWN NOTHING IS WITHHELD ON A PAIR, the choice every menu here makes (`useScreenAccess`). */
function asking(access: SettingsAsker): Asker {
  return access.resolved ? access.who : { can: () => true, isPartner: access.who.isPartner };
}

/** Whether this person is shown a link: the one table opens its page, and they hold the pair of the card it names, if any. */
export function linkShownTo(link: SettingsLink, access: SettingsAsker): boolean {
  const who = asking(access);
  if (link.requires && !who.can(link.requires[0], link.requires[1])) return false;
  return mayOpen(link.href, who).allowed;
}

/** The links a person sees on a tab. */
export function visibleLinks(group: SettingsGroup, access: SettingsAsker): SettingsLink[] {
  return group.links.filter((l) => linkShownTo(l, access));
}

/** Whether the Firm Profile card is drawn: its read asks `firm` `read` on the server (saving it asks `firm` `write`). */
export function firmProfileShown(access: SettingsAsker): boolean {
  return asking(access).can("firm", "read");
}

/** Whether a tab has anything to show the person: a form the page renders, or a link they may see. */
export function groupHasContent(group: SettingsGroup, access: SettingsAsker): boolean {
  const inline = (group.inline ?? []).filter((f) => f !== "firm-profile" || firmProfileShown(access));
  return inline.length > 0 || visibleLinks(group, access).length > 0;
}
