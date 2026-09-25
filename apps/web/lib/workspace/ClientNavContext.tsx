"use client";

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { usePathname } from "next/navigation";
import { currentFinancialYearLabel } from "@/lib/dateMath";
import { getSupabaseClient } from "@/lib/supabase/client";
import { PLACEHOLDER_CLIENT_ID, type ClientResolution } from "./clientGate";

export { PLACEHOLDER_CLIENT_ID } from "./clientGate";
export type { ClientResolution, GateVerdict } from "./clientGate";
export { gateVerdict, refusalAddress, clientSectionSegment } from "./clientGate";

export type ClientSection =
  | "overview"
  | "accounting"
  | "sales"
  | "purchases"
  | "bank"
  | "inventory"
  | "compliance"
  | "payroll"
  | "fixed-assets"
  | "year-end"
  | "tax"
  | "reports"
  | "documents"
  | "tasks"
  | "portal"
  | "ai-insights"
  | "lifecycle"
  | "relationships"
  | "health"
  | "knowledge"
  | "instructions";

export interface ClientSectionConfig {
  id: ClientSection;
  label: string;
  href: (clientId: string) => string;
}

// "reports" IS BACK, and the reasons it was pulled are worth keeping in view.
// It was a static "Coming in Phase 1" placeholder with no data behind it, so
// every client saw a permanent dead nav link, and it cost 2 of Cloudflare Pages'
// 100 dynamic _redirects rules to serve a card nobody could use — that budget is
// the binding constraint on adding real routes (see scripts/generate-redirects.js),
// and overrunning it once made the whole client workspace 404.
//
// What is different: it is not a placeholder this time. The section opens onto
// the reports that ALREADY exist across the workspace, so it is useful on the
// day it ships and has somewhere to grow, rather than promising a later phase.
// The rule budget was checked before adding it back, not after — 88 of 100 in
// use, and a section costs 2. Check it again before adding the next one.
//
// The firm-wide /reports/ page is a separate, fully working feature and is
// unaffected.
//
// "products-services" is likewise omitted: Products & Services management
// lives entirely inside ServiceCataloguePicker's "+ Add Product/Service"
// overlay (ProductServiceManagerPanel, mode="overlay") on a Sales Invoice
// line — there is no standalone sidebar destination for it.
export const CLIENT_SECTIONS: ClientSectionConfig[] = [
  { id: "overview",     label: "Overview",      href: (id) => `/clients/${id}/overview/` },
  { id: "accounting",   label: "Accounting",    href: (id) => `/clients/${id}/accounting/` },
  { id: "sales",        label: "Sales",         href: (id) => `/clients/${id}/sales/` },
  { id: "purchases",    label: "Purchases",     href: (id) => `/clients/${id}/purchases/` },
  // Banking is its own section rather than an Accounting tab: it is a
  // sequential pipeline (import -> categorize -> post -> reconcile) done in
  // order, where the financial statements next door are jumped to directly.
  { id: "bank",         label: "Bank",          href: (id) => `/clients/${id}/bank/` },
  { id: "inventory",    label: "Inventory",     href: (id) => `/clients/${id}/inventory/` },
  { id: "compliance",   label: "Compliance",    href: (id) => `/clients/${id}/compliance/` },
  { id: "payroll",      label: "Payroll",       href: (id) => `/clients/${id}/payroll/` },
  { id: "fixed-assets", label: "Fixed Assets",  href: (id) => `/clients/${id}/fixed-assets/` },
  { id: "year-end",     label: "Year End",      href: (id) => `/clients/${id}/year-end/` },
  { id: "tax",          label: "Tax",           href: (id) => `/clients/${id}/tax/` },
  { id: "reports",      label: "Reports",       href: (id) => `/clients/${id}/reports/` },
  { id: "documents",    label: "Documents",     href: (id) => `/clients/${id}/documents/` },
  { id: "tasks",        label: "Tasks",         href: (id) => `/clients/${id}/tasks/` },
  { id: "portal",        label: "Portal",         href: (id) => `/clients/${id}/portal/` },
  { id: "ai-insights",  label: "AI Insights",    href: (id) => `/clients/${id}/ai-insights/` },
  { id: "lifecycle",    label: "Lifecycle",      href: (id) => `/clients/${id}/lifecycle/` },
  // "Related Parties", not "Relationships", and the ROUTE deliberately does not
  // move. The section is the input side of the AS 18 disclosure, Companies Act
  // s.185 and s.188 — a compliance note a statutory audit cannot omit — and the
  // old name read as CRM, which is most of why it looked like dead weight.
  // Renaming the SEGMENT would cost 2 of D10's 2 remaining redirect rules and
  // buy nothing: the label is what a CA reads.
  { id: "relationships",label: "Related Parties", href: (id) => `/clients/${id}/relationships/` },
  { id: "health",       label: "Health",         href: (id) => `/clients/${id}/health/` },
  { id: "knowledge",    label: "Knowledge",      href: (id) => `/clients/${id}/knowledge/` },
  { id: "instructions", label: "Instructions",   href: (id) => `/clients/${id}/instructions/` },
];

// THE FINANCIAL YEAR IS NOT IN THIS CONTEXT ANY MORE
//
// It used to be: a `financialYear` + `setFinancialYear` pair, persisted to
// localStorage under "caflow.financialYear" and mirrored into ?fy=, driven by
// a selector in the client header.
//
// Eleven of the twenty-odd client pages read it. The rest ignored it. So the
// header could say "FY 2026-27" over a Tasks or Bank screen the year had no
// bearing on, and — worse — over a Sales screen whose own period filter said
// "Last Financial Year (FY 2025-26)" and was showing exactly that. Two
// controls, each correct, describing different periods, with the rows below
// belonging to one of them and no way to tell which.
//
// A period now belongs to the control that scopes the query, on the page that
// runs it. Removing the value from the context rather than merely hiding the
// selector is the point: while it is reachable here, the next page to want a
// year reaches for the global one and the whole shape comes back.
//
// getCurrentFinancialYear() stays — a page that needs a default needs this,
// and it is a pure function of the date rather than a shared mutable setting.

export function getCurrentFinancialYear(): string {
  return currentFinancialYearLabel();
}

export function getSectionForPathname(pathname: string): ClientSection {
  const segments = pathname.split("/");
  // /clients/[id]/[section]
  const section = segments[3] as ClientSection | undefined;
  if (section && CLIENT_SECTIONS.some((s) => s.id === section)) return section;
  return "overview";
}

/**
 * ONE LOOKUP, TWO READERS.
 *
 * `ClientTopBar` used to run this query itself and keep the answer private, so
 * every screen under `/clients/[id]/**` rendered as though a client that does
 * not exist were simply slow to arrive. The bar and the layout's gate now read
 * the same answer; two lookups would be two answers, which is the mistake this
 * codebase keeps having to delete.
 *
 * The six states, and why "still loading", "does not exist" and "the lookup
 * failed" are three of them rather than one, are in `clientGate.ts` — which
 * has no imports so a `node --test` guard can exercise the decision itself.
 */
export interface ResolvedClient {
  id: string;
  client_name: string;
  entity_type?: string;
  gstin?: string;
}

export interface ClientNavContextValue {
  clientId: string;
  /** The row, or null in every state but `"resolved"`. */
  client: ResolvedClient | null;
  resolution: ClientResolution;
  /** Re-run the lookup. For the `"unavailable"` state's Try again. */
  reloadClient: () => void;
}

const ClientNavContext = createContext<ClientNavContextValue | null>(null);

interface ClientNavProviderProps {
  children: React.ReactNode;
}

export function ClientNavProvider({ children }: ClientNavProviderProps) {
  // window.location.pathname is always the real browser URL, even when
  // Cloudflare's 200-rewrite serves _placeholder HTML for a real client ID.
  // useParams() would return "_placeholder" (from pre-rendered HTML data).
  const [clientId, setClientId] = useState<string>(() => {
    if (typeof window === "undefined") return "";
    const m = window.location.pathname.match(/^\/clients\/([^/]+)/);
    return m ? decodeURIComponent(m[1]) : "";
  });
  // usePathname() returns _placeholder during hydration (the pre-rendered segment),
  // so we use it only as a trigger and always read the real UUID from window.location.
  const pathname = usePathname();
  useEffect(() => {
    const m = window.location.pathname.match(/^\/clients\/([^/]+)/);
    const id = m ? decodeURIComponent(m[1]) : "";
    setClientId(id);
  }, [pathname]);

  const [client, setClient] = useState<ResolvedClient | null>(null);
  // The state the SERVER renders, and it must be one that renders the page:
  // `output: "export"` builds this HTML with no window, so `clientId` is ""
  // there and every client screen would otherwise be pre-rendered as its own
  // refusal.
  const [resolution, setResolution] = useState<ClientResolution>("off-route");
  const [attempt, setAttempt] = useState(0);
  const reloadClient = useCallback(() => setAttempt((n) => n + 1), []);

  useEffect(() => {
    if (!clientId) { setClient(null); setResolution("off-route"); return; }
    if (clientId === PLACEHOLDER_CLIENT_ID) {
      // No lookup: `id=eq._placeholder` against a uuid column is SQLSTATE
      // 22P02, which was logged in production on every client page load
      // before ClientTopBar grew the same guard.
      setClient(null);
      setResolution("unnamed");
      return;
    }
    let cancelled = false;
    setClient(null);
    setResolution("resolving");
    let supabase;
    try {
      supabase = getSupabaseClient();
    } catch (e) {
      // A missing key throws here rather than answering an error, and an
      // unconfigured browser must not be told the client does not exist.
      console.error("ClientNavProvider: no Supabase client", e);
      setResolution("unavailable");
      return;
    }
    supabase
      .from("clients")
      .select("id, client_name, entity_type, gstin")
      .eq("id", clientId)
      // `.maybeSingle()`, deliberately, where the bar used `.single()`: single
      // answers an ERROR for zero rows, so "this client does not exist" and
      // "the request failed" arrive down one channel and cannot be told apart.
      // maybeSingle answers `data: null, error: null` for zero rows, which is
      // what makes `absent` and `unavailable` two states rather than a guess.
      .maybeSingle()
      .then(({ data, error }) => {
        if (cancelled) return;
        if (error) {
          console.error("ClientNavProvider: client lookup failed", error);
          setResolution("unavailable");
          return;
        }
        if (!data) { setResolution("absent"); return; }
        setClient(data as ResolvedClient);
        setResolution("resolved");
      },
      // The rejection handler is the SECOND ARGUMENT rather than a `.catch()`
      // because the builder is a PromiseLike, not a Promise, and has no
      // `.catch` to chain — the type checker says so and it is worth keeping.
      // A thrown request resolves nothing and the default state renders the
      // page, so without this a transport failure would leave every screen in
      // `resolving` for ever, which is the defect being fixed.
      (e: unknown) => {
        if (cancelled) return;
        console.error("ClientNavProvider: client lookup threw", e);
        setResolution("unavailable");
      });
    return () => { cancelled = true; };
  }, [clientId, attempt]);

  const value: ClientNavContextValue = useMemo(
    () => ({ clientId, client, resolution, reloadClient }),
    [clientId, client, resolution, reloadClient],
  );

  return (
    <ClientNavContext.Provider value={value}>
      {children}
    </ClientNavContext.Provider>
  );
}

export function useClientNav(): ClientNavContextValue {
  const ctx = useContext(ClientNavContext);
  if (!ctx) throw new Error("useClientNav must be used within ClientNavProvider");
  return ctx;
}
