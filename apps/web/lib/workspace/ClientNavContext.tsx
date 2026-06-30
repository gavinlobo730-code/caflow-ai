"use client";

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import { usePathname } from "next/navigation";

export type ClientSection =
  | "overview"
  | "accounting"
  | "sales"
  | "purchases"
  | "compliance"
  | "payroll"
  | "fixed-assets"
  | "year-end"
  | "tax"
  | "documents"
  | "tasks"
  | "reports"
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

export const CLIENT_SECTIONS: ClientSectionConfig[] = [
  { id: "overview",     label: "Overview",      href: (id) => `/clients/${id}/overview/` },
  { id: "accounting",   label: "Accounting",    href: (id) => `/clients/${id}/accounting/` },
  { id: "sales",        label: "Sales",         href: (id) => `/clients/${id}/sales/` },
  { id: "purchases",    label: "Purchases",     href: (id) => `/clients/${id}/purchases/` },
  { id: "compliance",   label: "Compliance",    href: (id) => `/clients/${id}/compliance/` },
  { id: "payroll",      label: "Payroll",       href: (id) => `/clients/${id}/payroll/` },
  { id: "year-end",     label: "Year End",      href: (id) => `/clients/${id}/year-end/` },
  { id: "tax",          label: "Tax",           href: (id) => `/clients/${id}/tax/` },
  { id: "documents",    label: "Documents",     href: (id) => `/clients/${id}/documents/` },
  { id: "tasks",        label: "Tasks",         href: (id) => `/clients/${id}/tasks/` },
  { id: "reports",      label: "Reports",       href: (id) => `/clients/${id}/reports/` },
  { id: "portal",        label: "Portal",         href: (id) => `/clients/${id}/portal/` },
  { id: "ai-insights",  label: "AI Insights",    href: (id) => `/clients/${id}/ai-insights/` },
  { id: "lifecycle",    label: "Lifecycle",      href: (id) => `/clients/${id}/lifecycle/` },
  { id: "relationships",label: "Relationships",  href: (id) => `/clients/${id}/relationships/` },
  { id: "health",       label: "Health",         href: (id) => `/clients/${id}/health/` },
  { id: "knowledge",    label: "Knowledge",      href: (id) => `/clients/${id}/knowledge/` },
  { id: "instructions", label: "Instructions",   href: (id) => `/clients/${id}/instructions/` },
];

/** localStorage key for the persisted financial-year selection. */
const FY_STORAGE_KEY = "caflow.financialYear";

export function getCurrentFinancialYear(): string {
  const now = new Date();
  const year = now.getFullYear();
  const month = now.getMonth() + 1; // 1-indexed
  const fyStart = month >= 4 ? year : year - 1;
  const fyEnd = (fyStart + 1).toString().slice(-2);
  return `${fyStart}-${fyEnd}`;
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
  activeSection: ClientSection;
  financialYear: string;
  setSection: (section: ClientSection) => void;
  setFinancialYear: (fy: string) => void;
}

const ClientNavContext = createContext<ClientNavContextValue | null>(null);

interface ClientNavProviderProps {
  initialSection?: ClientSection;
  children: React.ReactNode;
}

export function ClientNavProvider({
  initialSection = "overview",
  children,
}: ClientNavProviderProps) {
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
    setClientId(m ? decodeURIComponent(m[1]) : "");
  }, [pathname]);
  const [activeSection, setActiveSection] = useState<ClientSection>(initialSection);
  // Persist the selected FY so it survives a page refresh / direct link, instead
  // of silently resetting to the current FY on every mount. Priority on init:
  // ?fy= URL param → localStorage → current FY.
  const [financialYear, setFinancialYearState] = useState<string>(() => {
    if (typeof window === "undefined") return getCurrentFinancialYear();
    const fromUrl = new URLSearchParams(window.location.search).get("fy");
    if (fromUrl) return fromUrl;
    const stored = window.localStorage.getItem(FY_STORAGE_KEY);
    return stored || getCurrentFinancialYear();
  });

  const setSection = useCallback((section: ClientSection) => {
    setActiveSection(section);
  }, []);

  const setFinancialYear = useCallback((fy: string) => {
    setFinancialYearState(fy);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(FY_STORAGE_KEY, fy);
      const p = new URLSearchParams(window.location.search);
      p.set("fy", fy);
      window.history.replaceState(null, "", `${window.location.pathname}?${p.toString()}`);
    }
  }, []);

  const value: ClientNavContextValue = {
    clientId,
    activeSection,
    financialYear,
    setSection,
    setFinancialYear,
  };

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
