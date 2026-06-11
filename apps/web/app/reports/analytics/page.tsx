"use client";

import React, { useState, useEffect, useCallback } from "react";
import {
  Users, BarChart3, Building2, Loader2, AlertCircle,
  TrendingUp, Clock, IndianRupee,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  getTeamAnalytics,
  getClientAnalytics,
  getFirmAnalytics,
  formatRupees,
  formatHours,
  type AnalyticsPeriod,
} from "@/lib/data/analytics";
import type {
  TeamAnalyticsReport,
  ClientAnalyticsReport,
  FirmAnalyticsReport,
} from "@/lib/types";

type ActiveTab = "team" | "clients" | "firm";

const PERIOD_LABELS: Record<AnalyticsPeriod, string> = {
  week: "This Week",
  month: "This Month",
  quarter: "This Quarter",
};

function UtilBar({ pct }: { pct: number }) {
  const clamped = Math.min(100, Math.max(0, pct));
  const color = clamped > 80 ? "bg-red-400" : clamped > 60 ? "bg-amber-400" : "bg-green-500";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-[#F1F5F9] rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${clamped}%` }} />
      </div>
      <span className="text-[11px] text-[#94A3B8] w-8 text-right">{clamped}%</span>
    </div>
  );
}

export default function AnalyticsPage() {
  const [tab, setTab] = useState<ActiveTab>("firm");
  const [period, setPeriod] = useState<AnalyticsPeriod>("month");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [teamData, setTeamData] = useState<TeamAnalyticsReport | null>(null);
  const [clientData, setClientData] = useState<ClientAnalyticsReport | null>(null);
  const [firmData, setFirmData] = useState<FirmAnalyticsReport | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      if (tab === "firm" || !firmData) {
        const [firm, team, clients] = await Promise.all([
          getFirmAnalytics(period),
          getTeamAnalytics(period),
          getClientAnalytics(period),
        ]);
        setFirmData(firm);
        setTeamData(team);
        setClientData(clients);
      } else if (tab === "team" && !teamData) {
        setTeamData(await getTeamAnalytics(period));
      } else if (tab === "clients" && !clientData) {
        setClientData(await getClientAnalytics(period));
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load analytics");
    } finally {
      setLoading(false);
    }
  }, [tab, period, firmData, teamData, clientData]);

  useEffect(() => {
    setTeamData(null);
    setClientData(null);
    setFirmData(null);
  }, [period]);

  useEffect(() => { load(); }, [load]);

  const tabs: { id: ActiveTab; label: string; icon: React.ReactNode }[] = [
    { id: "firm", label: "Firm Overview", icon: <Building2 size={13} /> },
    { id: "team", label: "Team", icon: <Users size={13} /> },
    { id: "clients", label: "Clients", icon: <BarChart3 size={13} /> },
  ];

  return (
    <div className="p-6 space-y-6 max-w-6xl mx-auto">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-[#0F172A]">Productivity Analytics</h1>
          <p className="text-sm text-[#64748B] mt-0.5">Revenue, utilisation, and efficiency insights</p>
        </div>
        <div className="flex gap-2">
          {(Object.keys(PERIOD_LABELS) as AnalyticsPeriod[]).map(p => (
            <Button
              key={p}
              variant={period === p ? "default" : "outline"}
              size="sm"
              onClick={() => setPeriod(p)}
              className="text-xs"
            >
              {PERIOD_LABELS[p]}
            </Button>
          ))}
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2 text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-4 py-3">
          <AlertCircle size={14} /> {error}
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 border-b">
        {tabs.map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
              tab === t.id
                ? "border-blue-500/20 text-blue-600"
                : "border-transparent text-[#64748B] hover:text-[#334155]"
            }`}
          >
            {t.icon} {t.label}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-20 text-[#94A3B8]">
          <Loader2 className="animate-spin mr-2" size={18} /> Loading analytics…
        </div>
      ) : (
        <>
          {/* Firm Overview Tab */}
          {tab === "firm" && firmData && (
            <div className="space-y-5">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <Card>
                  <CardContent className="py-4">
                    <div className="flex items-center gap-1.5 text-xs text-[#64748B] mb-1">
                      <Clock size={11} /> Total Hours
                    </div>
                    <p className="text-2xl font-bold text-[#0F172A]">{formatHours(firmData.total_minutes)}</p>
                    <p className="text-[11px] text-[#94A3B8] mt-0.5">{formatHours(firmData.billable_minutes)} billable</p>
                  </CardContent>
                </Card>
                <Card>
                  <CardContent className="py-4">
                    <div className="flex items-center gap-1.5 text-xs text-[#64748B] mb-1">
                      <TrendingUp size={11} /> Utilisation
                    </div>
                    <p className="text-2xl font-bold text-[#0F172A]">{firmData.utilisation_pct}%</p>
                    <UtilBar pct={firmData.utilisation_pct} />
                  </CardContent>
                </Card>
                <Card>
                  <CardContent className="py-4">
                    <div className="flex items-center gap-1.5 text-xs text-[#64748B] mb-1">
                      <IndianRupee size={11} /> Revenue
                    </div>
                    <p className="text-2xl font-bold text-[#0F172A]">{formatRupees(firmData.revenue_paise)}</p>
                    <p className="text-[11px] text-[#94A3B8] mt-0.5">{formatRupees(firmData.outstanding_paise)} outstanding</p>
                  </CardContent>
                </Card>
                <Card>
                  <CardContent className="py-4">
                    <div className="flex items-center gap-1.5 text-xs text-[#64748B] mb-1">
                      <BarChart3 size={11} /> Tasks
                    </div>
                    <p className="text-2xl font-bold text-[#0F172A]">{firmData.tasks_completed}</p>
                    <p className="text-[11px] text-[#94A3B8] mt-0.5">
                      {firmData.tasks_active} active · {firmData.tasks_overdue > 0 ?
                        <span className="text-red-500">{firmData.tasks_overdue} overdue</span> :
                        "0 overdue"
                      }
                    </p>
                  </CardContent>
                </Card>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm">Invoice Summary</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-2">
                    <div className="flex justify-between text-sm">
                      <span className="text-[#64748B]">Issued</span>
                      <span className="font-medium">{firmData.invoices_issued}</span>
                    </div>
                    <div className="flex justify-between text-sm">
                      <span className="text-[#64748B]">Paid</span>
                      <span className="font-medium text-green-700">{firmData.invoices_paid}</span>
                    </div>
                    <div className="flex justify-between text-sm">
                      <span className="text-[#64748B]">Outstanding</span>
                      <span className="font-medium text-amber-700">{firmData.invoices_issued - firmData.invoices_paid}</span>
                    </div>
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm">Hours Breakdown</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-2">
                    <div className="flex justify-between text-sm">
                      <span className="text-[#64748B]">Total Logged</span>
                      <span className="font-medium">{formatHours(firmData.total_minutes)}</span>
                    </div>
                    <div className="flex justify-between text-sm">
                      <span className="text-[#64748B]">Billable</span>
                      <span className="font-medium text-blue-600">{formatHours(firmData.billable_minutes)}</span>
                    </div>
                    <div className="flex justify-between text-sm">
                      <span className="text-[#64748B]">Non-billable</span>
                      <span className="font-medium">{formatHours(firmData.total_minutes - firmData.billable_minutes)}</span>
                    </div>
                  </CardContent>
                </Card>
              </div>
            </div>
          )}

          {/* Team Tab */}
          {tab === "team" && teamData && (
            <div className="space-y-4">
              <div className="grid grid-cols-3 gap-4">
                <Card>
                  <CardContent className="py-4">
                    <p className="text-xs text-[#64748B]">Total Hours</p>
                    <p className="text-2xl font-bold text-[#0F172A] mt-1">{formatHours(teamData.total_minutes)}</p>
                  </CardContent>
                </Card>
                <Card>
                  <CardContent className="py-4">
                    <p className="text-xs text-[#64748B]">Billable Hours</p>
                    <p className="text-2xl font-bold text-blue-600 mt-1">{formatHours(teamData.billable_minutes)}</p>
                  </CardContent>
                </Card>
                <Card>
                  <CardContent className="py-4">
                    <p className="text-xs text-[#64748B]">Avg Utilisation</p>
                    <p className="text-2xl font-bold text-[#0F172A] mt-1">{teamData.avg_utilisation_pct}%</p>
                  </CardContent>
                </Card>
              </div>

              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm">Team Members</CardTitle>
                </CardHeader>
                <CardContent className="p-0">
                  <div className="divide-y">
                    {teamData.members.length === 0 ? (
                      <p className="py-8 text-center text-sm text-[#94A3B8]">No data for this period</p>
                    ) : (
                      teamData.members.map(m => (
                        <div key={m.user_id} className="px-5 py-3 flex items-center gap-4">
                          <div className="w-7 h-7 rounded-full bg-gradient-to-br from-blue-600 to-blue-400 text-white flex items-center justify-center text-[10px] font-bold shrink-0">
                            {m.user_name.split(" ").map(n => n[0]).join("").slice(0, 2).toUpperCase()}
                          </div>
                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-medium text-[#0F172A] truncate">{m.user_name}</p>
                            <UtilBar pct={m.utilisation_pct} />
                          </div>
                          <div className="grid grid-cols-3 gap-4 text-center shrink-0">
                            <div>
                              <p className="text-sm font-semibold">{formatHours(m.total_minutes)}</p>
                              <p className="text-[10px] text-[#94A3B8]">Total</p>
                            </div>
                            <div>
                              <p className="text-sm font-semibold text-blue-600">{formatHours(m.billable_minutes)}</p>
                              <p className="text-[10px] text-[#94A3B8]">Billable</p>
                            </div>
                            <div>
                              <p className="text-sm font-semibold text-green-600">{m.tasks_completed}</p>
                              <p className="text-[10px] text-[#94A3B8]">Done</p>
                            </div>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </CardContent>
              </Card>
            </div>
          )}

          {/* Clients Tab */}
          {tab === "clients" && clientData && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <Card>
                  <CardContent className="py-4">
                    <p className="text-xs text-[#64748B]">Total Hours</p>
                    <p className="text-2xl font-bold text-[#0F172A] mt-1">{formatHours(clientData.total_minutes)}</p>
                  </CardContent>
                </Card>
                <Card>
                  <CardContent className="py-4">
                    <p className="text-xs text-[#64748B]">Total Revenue</p>
                    <p className="text-2xl font-bold text-[#0F172A] mt-1">{formatRupees(clientData.total_revenue_paise)}</p>
                  </CardContent>
                </Card>
              </div>

              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm">By Client</CardTitle>
                </CardHeader>
                <CardContent className="p-0">
                  <div className="divide-y">
                    {clientData.clients.length === 0 ? (
                      <p className="py-8 text-center text-sm text-[#94A3B8]">No data for this period</p>
                    ) : (
                      clientData.clients
                        .sort((a, b) => b.total_minutes - a.total_minutes)
                        .map(c => (
                          <div key={c.client_id} className="px-5 py-3 flex items-center gap-4">
                            <div className="flex-1 min-w-0">
                              <p className="text-sm font-medium text-[#0F172A] truncate">{c.client_name}</p>
                              <p className="text-[11px] text-[#94A3B8]">
                                {c.tasks_completed} completed · {c.tasks_active} active
                              </p>
                            </div>
                            <div className="grid grid-cols-2 gap-4 text-right shrink-0">
                              <div>
                                <p className="text-sm font-semibold">{formatHours(c.total_minutes)}</p>
                                <p className="text-[10px] text-[#94A3B8]">Hours</p>
                              </div>
                              <div>
                                <p className="text-sm font-semibold text-blue-600">{formatRupees(c.revenue_paise)}</p>
                                <p className="text-[10px] text-[#94A3B8]">Revenue</p>
                              </div>
                            </div>
                          </div>
                        ))
                    )}
                  </div>
                </CardContent>
              </Card>
            </div>
          )}
        </>
      )}
    </div>
  );
}
