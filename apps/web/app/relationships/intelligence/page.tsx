"use client";

import { useState, useEffect, useCallback } from "react";
import { AlertTriangle, Building2, FileText, TrendingUp } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { getSupabaseClient } from "@/lib/supabase/client";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function apiFetch(path: string, opts?: RequestInit) {
  const {
    data: { session },
  } = await getSupabaseClient().auth.getSession();
  const token = session?.access_token ?? "";
  const res = await fetch(`${API}${path}`, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(opts?.headers ?? {}),
    },
  });
  return res.json();
}

// ─── Types ────────────────────────────────────────────────────────────────────

interface Loan {
  id: string;
  client_id: string;
  entity_id: string;
  loan_type: string;
  principal_paise: number;
  interest_rate: number;
  sanction_date: string | null;
  due_date: string | null;
  section_185_flagged: boolean;
  section_186_flagged: boolean;
  notes: string | null;
}

interface Property {
  id: string;
  client_id: string;
  entity_id: string | null;
  address: string;
  property_type: string;
  cost_paise: number;
  annual_rent_paise: number;
  acquisition_date: string | null;
}

interface CrossClientMatch {
  id: string;
  entity_id: string;
  client_id_a: string;
  client_id_b: string;
  match_type: string;
  match_value: string;
  reviewed: boolean;
  confirmed: boolean | null;
}

interface ApiResponse<T> {
  success: boolean;
  data: T;
  error: string | null;
}

type Tab = "loans" | "properties" | "cross-client";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatPaise(paise: number): string {
  // All amounts are integer paise — convert to rupees for display only
  const rupees = Math.floor(paise / 100);
  if (rupees >= 1_00_00_000) {
    return `₹${(rupees / 1_00_00_000).toFixed(2)} Cr`;
  }
  if (rupees >= 1_00_000) {
    return `₹${(rupees / 1_00_000).toFixed(2)} L`;
  }
  return `₹${rupees.toLocaleString("en-IN")}`;
}

const LOAN_TYPE_LABELS: Record<string, string> = {
  to_director: "To Director",
  from_director: "From Director",
  inter_company: "Inter-Company",
  other: "Other",
};

const PROPERTY_TYPE_COLORS: Record<string, string> = {
  residential: "bg-blue-100 text-blue-700",
  commercial: "bg-violet-100 text-violet-700",
  land: "bg-emerald-100 text-emerald-700",
  industrial: "bg-orange-100 text-orange-700",
};

// ─── Component ────────────────────────────────────────────────────────────────

export default function RelationshipIntelligencePage() {
  const [activeTab, setActiveTab] = useState<Tab>("loans");
  const [loans, setLoans] = useState<Loan[]>([]);
  const [properties, setProperties] = useState<Property[]>([]);
  const [crossMatches, setCrossMatches] = useState<CrossClientMatch[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadLoans = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res: ApiResponse<Loan[]> = await apiFetch(
        "/api/relationships/loans"
      );
      if (!res.success) throw new Error(res.error ?? "Failed to load loans");
      setLoans(res.data ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load loans");
    } finally {
      setLoading(false);
    }
  }, []);

  const loadProperties = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res: ApiResponse<Property[]> = await apiFetch(
        "/api/relationships/properties"
      );
      if (!res.success)
        throw new Error(res.error ?? "Failed to load properties");
      setProperties(res.data ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load properties");
    } finally {
      setLoading(false);
    }
  }, []);

  const loadCrossMatches = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res: ApiResponse<CrossClientMatch[]> = await apiFetch(
        "/api/relationships/cross-client-matches"
      );
      if (!res.success)
        throw new Error(res.error ?? "Failed to load cross-client matches");
      setCrossMatches(res.data ?? []);
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Failed to load cross-client matches"
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (activeTab === "loans") loadLoans();
    else if (activeTab === "properties") loadProperties();
    else if (activeTab === "cross-client") loadCrossMatches();
  }, [activeTab, loadLoans, loadProperties, loadCrossMatches]);

  const sec185Loans = loans.filter((l) => l.section_185_flagged);
  const transferPricingLoans = loans.filter(
    // Sec 92 IT Act — inter-company > ₹1 crore = 10_000_000_00 paise
    (l) => l.loan_type === "inter_company" && l.principal_paise >= 10_000_000_00
  );

  const tabs: { key: Tab; label: string; icon: React.ReactNode; count?: number }[] = [
    {
      key: "loans",
      label: "Loan Intelligence",
      icon: <AlertTriangle size={14} />,
      count: sec185Loans.length,
    },
    {
      key: "properties",
      label: "Properties",
      icon: <Building2 size={14} />,
    },
    {
      key: "cross-client",
      label: "Cross-Client Links",
      icon: <TrendingUp size={14} />,
      count: crossMatches.filter((m) => !m.reviewed).length,
    },
  ];

  return (
    <div className="p-6 space-y-5 bg-[#F8FAFC] min-h-full">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[#182350] flex items-center gap-2">
            <FileText size={20} />
            Relationship Intelligence
          </h1>
          <p className="text-sm text-gray-500 mt-0.5">
            Loans (Sec 185/186), properties, and cross-client entity links
          </p>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-gray-200">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
              activeTab === tab.key
                ? "border-[#182350] text-[#182350]"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            {tab.icon}
            {tab.label}
            {tab.count !== undefined && tab.count > 0 && (
              <span className="ml-1 bg-red-100 text-red-600 text-xs rounded-full px-1.5 py-0.5 leading-none">
                {tab.count}
              </span>
            )}
          </button>
        ))}
      </div>

      {loading && (
        <div className="flex items-center justify-center py-16">
          <div className="w-5 h-5 border-2 border-[#182350] border-t-transparent rounded-full animate-spin" />
        </div>
      )}

      {error && (
        <Card className="bg-red-50 border-red-200">
          <CardContent className="p-4 text-sm text-red-600">{error}</CardContent>
        </Card>
      )}

      {/* ── Loans Tab ─────────────────────────────────────────────────────── */}
      {!loading && !error && activeTab === "loans" && (
        <div className="space-y-4">
          {/* Section 185 alert banner */}
          {sec185Loans.length > 0 && (
            <div className="flex items-start gap-3 bg-amber-50 border border-amber-200 rounded-lg px-4 py-3">
              <AlertTriangle size={16} className="text-amber-600 mt-0.5 shrink-0" />
              <div>
                <p className="text-sm font-medium text-amber-800">
                  Section 185 Alert — {sec185Loans.length} loan
                  {sec185Loans.length !== 1 ? "s" : ""} to director(s) detected
                </p>
                <p className="text-xs text-amber-600 mt-0.5">
                  Companies Act Sec 185 prohibits loans to directors without
                  special resolution. CA review required before any action.
                </p>
              </div>
            </div>
          )}

          {/* Transfer pricing banner */}
          {transferPricingLoans.length > 0 && (
            <div className="flex items-start gap-3 bg-blue-50 border border-blue-200 rounded-lg px-4 py-3">
              <TrendingUp size={16} className="text-blue-600 mt-0.5 shrink-0" />
              <div>
                <p className="text-sm font-medium text-blue-800">
                  Transfer Pricing — {transferPricingLoans.length} inter-company
                  transaction{transferPricingLoans.length !== 1 ? "s" : ""} above ₹1 crore
                </p>
                <p className="text-xs text-blue-600 mt-0.5">
                  IT Act Sec 92 — international related party transactions
                  above ₹1 crore require transfer pricing documentation.
                </p>
              </div>
            </div>
          )}

          {loans.length === 0 ? (
            <div className="text-center py-16 text-gray-400 text-sm">
              No loans recorded yet.
            </div>
          ) : (
            <Card className="bg-white border-gray-200 shadow-sm">
              <CardContent className="p-0">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-xs text-gray-500 border-b border-gray-200">
                      <th className="px-5 py-3 text-left font-medium">Type</th>
                      <th className="px-3 py-3 text-left font-medium">Principal</th>
                      <th className="px-3 py-3 text-left font-medium">Rate</th>
                      <th className="px-3 py-3 text-left font-medium">Sanction Date</th>
                      <th className="px-3 py-3 text-left font-medium">Flags</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {loans.map((loan) => (
                      <tr
                        key={loan.id}
                        className={
                          loan.section_185_flagged
                            ? "bg-amber-50/40"
                            : "hover:bg-gray-50"
                        }
                      >
                        <td className="px-5 py-3 text-gray-800 font-medium">
                          {LOAN_TYPE_LABELS[loan.loan_type] ?? loan.loan_type}
                        </td>
                        <td className="px-3 py-3 font-mono text-gray-700">
                          {formatPaise(loan.principal_paise)}
                        </td>
                        <td className="px-3 py-3 text-gray-600">
                          {loan.interest_rate}%
                        </td>
                        <td className="px-3 py-3 text-gray-500 text-xs">
                          {loan.sanction_date ?? "—"}
                        </td>
                        <td className="px-3 py-3">
                          <div className="flex gap-1 flex-wrap">
                            {loan.section_185_flagged && (
                              <Badge className="bg-amber-100 text-amber-700 text-[10px]">
                                Sec 185
                              </Badge>
                            )}
                            {loan.section_186_flagged && (
                              <Badge className="bg-orange-100 text-orange-700 text-[10px]">
                                Sec 186
                              </Badge>
                            )}
                            {loan.loan_type === "inter_company" &&
                              loan.principal_paise >= 10_000_000_00 && (
                                <Badge className="bg-blue-100 text-blue-700 text-[10px]">
                                  TP Risk
                                </Badge>
                              )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {/* ── Properties Tab ────────────────────────────────────────────────── */}
      {!loading && !error && activeTab === "properties" && (
        <div className="space-y-3">
          {properties.length === 0 ? (
            <div className="text-center py-16 text-gray-400 text-sm">
              No properties recorded yet.
            </div>
          ) : (
            properties.map((prop) => (
              <Card key={prop.id} className="bg-white border-gray-200 shadow-sm">
                <CardContent className="p-4">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-gray-800 font-medium truncate">
                          {prop.address}
                        </span>
                        <Badge
                          className={
                            PROPERTY_TYPE_COLORS[prop.property_type] ??
                            "bg-gray-100 text-gray-600"
                          }
                        >
                          {prop.property_type}
                        </Badge>
                      </div>
                      <div className="flex gap-4 mt-2 text-xs text-gray-500">
                        <span>
                          Cost:{" "}
                          <span className="font-mono text-gray-700">
                            {formatPaise(prop.cost_paise)}
                          </span>
                        </span>
                        <span>
                          Annual Rent:{" "}
                          <span className="font-mono text-gray-700">
                            {formatPaise(prop.annual_rent_paise)}
                          </span>
                        </span>
                        {prop.acquisition_date && (
                          <span>Acquired: {prop.acquisition_date}</span>
                        )}
                      </div>
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))
          )}
        </div>
      )}

      {/* ── Cross-Client Tab ──────────────────────────────────────────────── */}
      {!loading && !error && activeTab === "cross-client" && (
        <div className="space-y-3">
          {crossMatches.length === 0 ? (
            <div className="text-center py-16 text-gray-400 text-sm">
              No cross-client entity links found.
            </div>
          ) : (
            crossMatches.map((m) => (
              <Card key={m.id} className="bg-white border-gray-200 shadow-sm">
                <CardContent className="p-4">
                  <div className="flex items-center justify-between gap-4">
                    <div>
                      <p className="text-sm font-medium text-gray-800">
                        PAN{" "}
                        <span className="font-mono">{m.match_value}</span>{" "}
                        appears in multiple clients
                      </p>
                      <p className="text-xs text-gray-500 mt-0.5">
                        Client A: <span className="font-mono">{m.client_id_a}</span>
                        {" "}&rarr;{" "}
                        Client B: <span className="font-mono">{m.client_id_b}</span>
                      </p>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <Badge className="capitalize bg-gray-100 text-gray-600 text-[10px]">
                        {m.match_type}
                      </Badge>
                      {m.reviewed ? (
                        <Badge
                          className={
                            m.confirmed
                              ? "bg-emerald-100 text-emerald-700"
                              : "bg-red-100 text-red-700"
                          }
                        >
                          {m.confirmed ? "Confirmed" : "Rejected"}
                        </Badge>
                      ) : (
                        <Badge className="bg-yellow-100 text-yellow-700">
                          Pending Review
                        </Badge>
                      )}
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))
          )}
        </div>
      )}
    </div>
  );
}
