"use client";

import React, {
  createContext,
  useCallback,
  useContext,
  useState,
} from "react";
import { useParams } from "next/navigation";

export type ClientSection =
  | "overview"
  | "accounting"
  | "sales"
  | "purchases"
  | "compliance"
  | "payroll"
  | "year-end"
  | "tax"
  | "documents"
  | "tasks"
  | "reports"
  | "portal"
  | "ai-insights";

export interface ClientSectionConfig {
  id: ClientSection;
  label: string;
  href: (clientId: string) => string;
}

export const CLIENT_SECTIONS: ClientSectionConfig[] = [
  { id: "overview",     label: "Overview",      href: (id) => `/clients/${id}/overview` },
  { id: "accounting",   label: "Accounting",    href: (id) => `/clients/${id}/accounting` },
  { id: "sales",        label: "Sales",         href: (id) => `/clients/${id}/sales` },
  { id: "purchases",    label: "Purchases",     href: (id) => `/clients/${id}/purchases` },
  { id: "compliance",   label: "Compliance",    href: (id) => `/clients/${id}/compliance` },
  { id: "payroll",      label: "Payroll",       href: (id) => `/clients/${id}/payroll` },
  { id: "year-end",     label: "Year End",      href: (id) => `/clients/${id}/year-end` },
  { id: "tax",          label: "Tax",           href: (id) => `/clients/${id}/tax` },
  { id: "documents",    label: "Documents",     href: (id) => `/clients/${id}/documents` },
  { id: "tasks",        label: "Tasks",         href: (id) => `/clients/${id}/tasks` },
  { id: "reports",      label: "Reports",       href: (id) => `/clients/${id}/reports` },
  { id: "portal",       label: "Portal",        href: (id) => `/clients/${id}/portal` },
  { id: "ai-insights",  label: "AI Insights",   href: (id) => `/clients/${id}/ai-insights` },
];

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
  const params = useParams<{ id: string }>();
  const clientId = params?.id || "";
  const [activeSection, setActiveSection] = useState<ClientSection>(initialSection);
  const [financialYear, setFinancialYear] = useState(getCurrentFinancialYear());

  const setSection = useCallback((section: ClientSection) => {
    setActiveSection(section);
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
