/**
 * WHICH PERMISSION OPENS WHICH AREA AND WHICH SCREEN: the one table the firm menu, the page gate and the guide read
 * (POST-A-543, the owner's decision of 21-11-2026).
 *
 * THE RULE THE OWNER SET. What a member of staff sees on the menu, and what opens when they type an address, is decided by
 * one thing: the permission pairs a Partner has ticked for them. A role only sets the ticks a person starts with. Before
 * this, two things decided and they disagreed: the menu followed the ROLE (fixed lists here in the web app hid Deadlines,
 * Work and the tax desks from an Executive and a Reviewer) while the server followed the pairs, so an Executive could open
 * by address a list no menu showed them, and a Partner's tick moved the server and not the menu.
 *
 * WHAT A RULE IS. `all`: every pair must be held. `any`: at least one must be. `partnerOnly`: My practice, which the server
 * decides by the role itself (`internal_client_service`), so no tick opens it and none is offered. An area's rule decides
 * whether the area is on the menu; a screen is open when its AREA's rule holds and its OWN rule (if it has one) holds too,
 * so a screen is never reachable inside an area the menu does not show.
 *
 * WHERE THE PAIRS COME FROM. Each is the pair the server asks for that screen's main read, read off the route
 * (`rbac("…", "…")` in `apps/api/routers`). Where a screen's reads ask more than one resource and any of them shows it
 * something, the rule is `any`, so the gate never refuses a screen the server would have filled.
 * `scripts/the-menu-the-gate-and-the-guide-read-one-table.test.ts` holds every menu entry that names a pair of its own to
 * this table, and `screenAccess.test.ts` holds every pair here to the server's table (`apps/api/core/permissions.py`).
 *
 * NOT A SECURITY BOUNDARY. `rbac()` on the server is. This decides what is OFFERED and what a typed address SAYS.
 *
 * THE SETTINGS PAGES ARE IN THE TABLE TOO (POST-A-545). They used to be opened by a role (a guard on each page naming
 * Partner, or Partner and Manager) while the server asked a pair, so a Partner's tick moved the server and not the screen.
 * Each is now a screen rule here, and the Settings links read it (`lib/settings/groups.ts`).
 *
 * NOT COVERED, AND SAID. The screens inside a client keep their own rule (`ClientNavContext`).
 *
 * Pure: it imports only the route-ownership chain, which has no imports, so a test can load it.
 */
import { getActiveWorkspaceForPathname } from "../workspace/routeOwnership.ts";

export type Pair = readonly [resource: string, action: string];

export interface AccessRule {
  /** Every one of these must be held. */
  all?: readonly Pair[];
  /** At least one of these must be held. */
  any?: readonly Pair[];
  /** A Partner's alone, by role, on the server as well: no tick opens it. */
  partnerOnly?: boolean;
}

const read = (resource: string): Pair => [resource, "read"];

/** The rule for each area of the firm menu. An area with an empty rule is always offered. */
export const AREA_RULES: Readonly<Record<string, AccessRule>> = {
  home: {},
  clients: { all: [read("client")] },
  deadlines: { any: [read("compliance"), read("compliance_record"), read("gst"), read("income_tax"), read("tds"), read("mca")] },
  work: { any: [read("task"), read("time_entry"), read("workflow")] },
  team: { any: [read("team"), read("assignment"), read("approval"), read("workload")] },
  ai: { any: [read("ai"), read("copilot"), read("risk"), read("report")] },
  accounting: { all: [read("accounting")] },
  payroll: { all: [read("payroll")] },
  relationships: { all: [read("client")] },
  health: { all: [read("client")] },
  practice: { partnerOnly: true },
  knowledge: { all: [read("knowledge")] },
  engagements: { all: [read("engagement")] },
};

/**
 * Firm screens whose own reads ask a pair beyond their area's. The address and everything under it; the LONGEST matching
 * prefix is the screen's rule. A screen that is not here is opened by its area's rule alone.
 */
export const SCREEN_RULES: ReadonlyArray<readonly [prefix: string, rule: AccessRule]> = [
  // Home
  ["/calendar", { any: [read("compliance"), read("compliance_record")] }],
  ["/insights", { all: [read("ai")] }],
  // Clients
  ["/pipeline", { all: [read("pipeline")] }],
  ["/client-portal", { all: [read("portal")] }],
  ["/documents", { all: [read("document")] }],
  ["/clients/documents", { all: [read("document")] }],
  // Deadlines: the calendar, and each tax desk by its own tick
  ["/deadlines", { any: [read("compliance"), read("compliance_record")] }],
  ["/compliance", { any: [read("compliance"), read("compliance_record")] }],
  ["/gst", { all: [read("gst")] }],
  ["/einvoice", { any: [read("gst"), read("einvoice")] }],
  ["/income-tax", { all: [read("income_tax")] }],
  ["/income-tax/book-to-tax", { all: [["income_tax", "compute"]] }],
  ["/income-tax/section-32", { all: [["income_tax", "compute"]] }],
  ["/income-tax/deductions", { all: [["income_tax", "compute"]] }],
  ["/tds", { all: [read("tds")] }],
  ["/mca", { all: [read("mca")] }],
  // Work
  ["/work", { all: [read("task")] }],
  ["/tasks", { all: [read("task")] }],
  ["/workflows", { any: [read("task"), read("workflow")] }],
  ["/time", { all: [read("time_entry")] }],
  // Team
  ["/team", { all: [read("team")] }],
  ["/team/assignments", { all: [read("assignment")] }],
  ["/team/workload", { all: [read("workload")] }],
  ["/team/login-history", { all: [read("team")] }],
  ["/approvals", { all: [read("approval")] }],
  // AI
  ["/ai-assistant", { all: [read("ai")] }],
  ["/assistant", { all: [read("ai")] }],
  ["/copilot", { any: [read("task"), read("copilot"), read("ai")] }],
  ["/memory", { all: [read("copilot")] }],
  ["/risks", { all: [read("risk")] }],
  ["/reports", { any: [read("report"), read("accounting")] }],
  // Accounting: the screens whose reads ask something other than the books
  ["/accounting/coa-import", { all: [["accounting", "write"]] }],
  ["/accounting/trial-balance-import", { all: [["accounting", "write"]] }],
  ["/accounting/lock-year", { all: [["accounting", "approve"]] }],
  ["/accounting/suppliers", { all: [read("client")] }],
  ["/accounting/msme-tracker", { all: [["income_tax", "compute"]] }],
  ["/accounting/retainer", { all: [read("billing")] }],
  ["/accounting/banking", { all: [read("client")] }],
  ["/accounting/invoices", { all: [read("client")] }],
  ["/accounting/purchases", { all: [read("client")] }],
  ["/accounting/fixed-assets", { all: [read("client")] }],
  ["/accounting/year-end", { all: [read("client")] }],
  // Settings (POST-A-545): no area owns these addresses, so each page is opened by its own rule alone. The pair is the one the
  // page's own READ asks on the server; what CHANGES the page is a second pair, and a person who holds only the first is
  // shown the page with its controls switched off (`components/settings/ChangePart.tsx`). The Settings home, the security
  // page, the scheduled reports and the signature tracker are every member's and are not named here.
  ["/settings/ai", { all: [["firm", "admin"]] }],
  ["/settings/audit-log", { all: [["accounting", "approve"]] }],
  ["/settings/branding", { all: [read("branding")] }],
  ["/settings/email-templates", { all: [read("branding")] }],
  ["/settings/invoice-settings", { all: [read("branding")] }],
  ["/settings/invoice-templates", { all: [read("branding")] }],
  ["/settings/firm-hsn-library", { all: [read("accounting")] }],
  ["/settings/journal-approval", { all: [read("accounting")] }],
  ["/settings/multi-currency", { all: [read("settings")] }],
  ["/settings/statutory-values", { all: [read("payroll")] }],
  ["/settings/treaty-rates", { all: [read("tds")] }],
];

export interface Asker {
  can: (resource: string, action: string) => boolean;
  isPartner: boolean;
}

/** Whether the person holds what the rule asks. */
export function ruleHeld(rule: AccessRule, who: Asker): boolean {
  if (rule.partnerOnly) return who.isPartner;
  if (rule.all && !rule.all.every(([r, a]) => who.can(r, a))) return false;
  if (rule.any && rule.any.length > 0 && !rule.any.some(([r, a]) => who.can(r, a))) return false;
  return true;
}

/**
 * The pair to name when a rule is not held: the first of `all` the person lacks, else the first of `any`. It is what the
 * page's notice carries and what a request for access asks for. Null for a Partner-only rule, which no tick opens.
 */
export function pairToAsk(rule: AccessRule, who: Asker): Pair | null {
  if (rule.partnerOnly) return null;
  const lacking = rule.all?.find(([r, a]) => !who.can(r, a));
  if (lacking) return lacking;
  if (rule.any && rule.any.length > 0 && !rule.any.some(([r, a]) => who.can(r, a))) return rule.any[0];
  return null;
}

/** Whether the area is on this person's firm menu. An area this table does not name is offered (and a test names it). */
export function areaOffered(areaId: string, who: Asker): boolean {
  const rule = AREA_RULES[areaId];
  return rule ? ruleHeld(rule, who) : true;
}

/** The address without its query, fragment or trailing slash. */
function bare(href: string): string {
  const path = href.split(/[?#]/)[0];
  return path.length > 1 ? path.replace(/\/+$/, "") : path;
}

/** The screen's own rule: the longest prefix in `SCREEN_RULES` that the address is, or is under. */
export function screenRule(href: string): AccessRule | null {
  const path = bare(href);
  let best: readonly [string, AccessRule] | null = null;
  for (const entry of SCREEN_RULES) {
    const prefix = entry[0];
    if ((path === prefix || path.startsWith(prefix + "/")) && (!best || prefix.length > best[0].length)) best = entry;
  }
  return best ? best[1] : null;
}

export interface Verdict {
  allowed: boolean;
  /** The area the address is in, or null for one no area owns (Settings, search). */
  area: string | null;
  /** True when what refused is the Partner-only rule, which no tick opens. */
  partnerOnly: boolean;
  /** The pair to name in the notice and to ask for, or null when allowed or Partner-only. */
  ask: Pair | null;
  /** True when it is the AREA that is not held (the notice then names the area), false when it is the screen itself. */
  byArea: boolean;
}

/**
 * Whether this person may open this firm address, by the area's rule and then the screen's own. The inside of a client is
 * not this table's (see the header) and is answered `allowed` here once the Clients area is held.
 */
export function mayOpen(href: string, who: Asker): Verdict {
  const path = bare(href);
  const area = getActiveWorkspaceForPathname(path);
  const open: Verdict = { allowed: true, area, partnerOnly: false, ask: null, byArea: false };
  const areaRule = area ? AREA_RULES[area] : undefined;
  if (areaRule && !ruleHeld(areaRule, who)) {
    return { allowed: false, area, partnerOnly: !!areaRule.partnerOnly, ask: pairToAsk(areaRule, who), byArea: true };
  }
  // The screens inside a client's workspace have their own rules (`ClientNavContext`); only the area's is asked for them.
  if (/^\/clients\/[^/]+\/.+/.test(path) && !path.startsWith("/clients/documents") && !path.startsWith("/clients/onboarding")) return open;
  const own = screenRule(path);
  if (own && !ruleHeld(own, who)) {
    return { allowed: false, area, partnerOnly: !!own.partnerOnly, ask: pairToAsk(own, who), byArea: false };
  }
  return open;
}

/** Every pair this table names, for the test that holds them to the server's table. */
export function everyPair(): Pair[] {
  const out: Pair[] = [];
  const add = (rule: AccessRule) => { for (const p of [...(rule.all ?? []), ...(rule.any ?? [])]) out.push(p); };
  Object.values(AREA_RULES).forEach(add);
  SCREEN_RULES.forEach(([, rule]) => add(rule));
  return out;
}
