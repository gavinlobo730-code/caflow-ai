"use client";

import React, {
  createContext,
  useContext,
  useEffect,
  useState,
} from "react";
import { usePathname } from "next/navigation";
import { currentFinancialYearLabel } from "@/lib/dateMath";

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

// "reports" is omitted, and its route no longer exists. It was a static
// "Coming in Phase 1" placeholder with no data behind it, already pulled from
// this list for Closed Beta (Beta-readiness Part 1) because every client saw a
// permanent dead nav link. The page was kept around for a future revival, but
// it was costing 2 of Cloudflare Pages' 100 dynamic _redirects rules to serve a
// card nobody could navigate to — and that budget is the binding constraint on
// adding real routes (see scripts/generate-redirects.js). Deleted when the Bank
// section needed a slot. Per-client reporting lands in the Accounting Reports
// hub, not here; the firm-wide /reports/ page is a separate, fully working
// feature and is unaffected.
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
  { id: "documents",    label: "Documents",     href: (id) => `/clients/${id}/documents/` },
  { id: "tasks",        label: "Tasks",         href: (id) => `/clients/${id}/tasks/` },
  { id: "portal",        label: "Portal",         href: (id) => `/clients/${id}/portal/` },
  { id: "ai-insights",  label: "AI Insights",    href: (id) => `/clients/${id}/ai-insights/` },
  { id: "lifecycle",    label: "Lifecycle",      href: (id) => `/clients/${id}/lifecycle/` },
  { id: "relationships",label: "Relationships",  href: (id) => `/clients/${id}/relationships/` },
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

export interface ClientNavContextValue {
  clientId: string;
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
  const value: ClientNavContextValue = { clientId };

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
