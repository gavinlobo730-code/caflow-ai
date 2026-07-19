"use client";

import { useEffect, useState } from "react";
import { Mail, Phone, MapPin, Calendar, TrendingUp, CheckSquare, Shield, AlertTriangle, AlertCircle, Info } from "lucide-react";
import { getClient } from "@/lib/data/clients";
import { getTasks } from "@/lib/data/tasks";
import { getComplianceCalendar, seedComplianceCalendar } from "@/lib/data/compliance";
import { getFirmId } from "@/lib/data/getFirmId";
import { getOrCalculateClientHealth, deriveHealthAlerts, DIMENSION_LABELS, type ClientHealth, type HealthAlert } from "@/lib/services/health-score-compute";
import { ClientTimeline } from "@/components/ClientTimeline";
import { ClientInstructions } from "@/components/knowledge/ClientInstructions";
import { HealthBadge } from "@/components/HealthBadge";
import type { Client } from "@/lib/types";
import type { Task } from "@/lib/types";
import type { ComplianceEntry } from "@/lib/data/compliance";
import { formatDate, ENTITY_TYPE_LABELS } from "@/lib/services/formatting";
import { useClientNav } from "@/lib/workspace/ClientNavContext";

export default function OverviewPage() {
  const { clientId, financialYear } = useClientNav();
  const [client, setClient] = useState<Client | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [compliance, setCompliance] = useState<ComplianceEntry[]>([]);
  const [health, setHealth] = useState<ClientHealth | null>(null);
  const [alerts, setAlerts] = useState<HealthAlert[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // M17: the per-fetch `.catch(() => [])` fallbacks below silently degrade a
  // failed tasks/compliance/health load into "0 open tasks / 0 overdue filings"
  // and drop the Health card — reassuring, and wrong. Track whether any of them
  // actually failed so we can show a retryable error instead of stale zeros.
  const [loadFailed, setLoadFailed] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (!clientId || clientId === "_placeholder") return;
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      setLoadFailed(false);
      try {
        // Every one of these is independent of the others — firing them
        // together instead of as a waterfall matters a lot here: the health
        // score fetch/calculate is the single heaviest call in the app (a
        // full 7-dimension server-side aggregation when nothing is cached
        // yet, e.g. a client's first visit), and it used to run dead LAST,
        // paying for its own latency on top of everything before it. Same
        // for the compliance calendar's first-visit seed step. Running them
        // concurrently drops the critical path from "sum of every step" to
        // roughly "the slowest single step".
        let anyFailed = false;
        const [c, t, firmId, comp0, health] = await Promise.all([
          getClient(clientId),
          getTasks({ clientId, limit: 50 }).catch(() => { anyFailed = true; return [] as Task[]; }),
          getFirmId().catch(() => { anyFailed = true; return null; }),
          getComplianceCalendar(clientId).catch(() => { anyFailed = true; return [] as ComplianceEntry[]; }),
          getOrCalculateClientHealth(clientId).catch(() => { anyFailed = true; return null; }),
        ]);
        if (cancelled) return;
        setClient(c);
        setTasks(t);
        if (health) {
          setHealth(health);
          setAlerts(deriveHealthAlerts(health));
        }

        // Seed the compliance calendar only if this really is a first visit
        // (still empty after the concurrent fetch above) — this write-then-
        // refetch pair genuinely must be sequential (it needs to know the
        // calendar was empty, and firmId, before deciding to seed at all).
        let comp = comp0;
        if (comp.length === 0 && firmId) {
          await seedComplianceCalendar(clientId).catch(() => undefined);
          comp = await getComplianceCalendar(clientId).catch(() => { anyFailed = true; return [] as ComplianceEntry[]; });
        }
        if (cancelled) return;
        setCompliance(comp);
        setLoadFailed(anyFailed);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load client");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  }, [clientId, financialYear, reloadKey]);

  if (loading) return <OverviewSkeleton />;
  if (error) return <div className="p-6 text-red-500 text-sm">{error}</div>;
  if (loadFailed) return (
    <div className="p-6">
      <div className="flex items-center justify-between gap-4 rounded-lg border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-700">
        <span>Couldn&apos;t load this client&apos;s overview — the request failed or timed out. Some figures may be incomplete, so they aren&apos;t shown.</span>
        <button
          onClick={() => setReloadKey((k) => k + 1)}
          className="shrink-0 text-xs font-medium text-red-700 underline"
        >
          Retry
        </button>
      </div>
    </div>
  );
  if (!client) return <div className="p-6 text-[#94A3B8] text-sm">Client not found.</div>;

  const today = new Date().toISOString().split("T")[0];
  const openTasks = tasks.filter((t) => t.status !== "completed");
  const overdueFiling = compliance.filter(
    (c) => c.due_date < today && c.filing_status !== "filed"
  );
  const filedCount = compliance.filter((c) => c.filing_status === "filed").length;

  return (
    <div className="flex h-full overflow-hidden">
      {/* ── Main feed (left) ─────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto p-5 space-y-4 min-w-0">

        {/* Pinned client instructions (Amendment v1.1 FR-KB-02) */}
        <ClientInstructions clientId={clientId} pinnedOnly />

        {/* Stat strip */}
        <div className="grid grid-cols-3 gap-3">
          <StatCard
            icon={<CheckSquare size={14} className="text-blue-600" />}
            label="Open Tasks"
            value={openTasks.length}
            accent={openTasks.length > 0 ? "indigo" : "neutral"}
          />
          <StatCard
            icon={<Shield size={14} className="text-amber-600" />}
            label="Overdue Filings"
            value={overdueFiling.length}
            accent={overdueFiling.length > 0 ? "amber" : "neutral"}
          />
          <StatCard
            icon={<TrendingUp size={14} className="text-emerald-600" />}
            label="Filed This FY"
            value={filedCount}
            accent="neutral"
          />
        </div>

        {/* Timeline */}
        <div className="bg-white rounded-xl border border-[#E2E8F0] p-4">
          <p className="text-[11px] font-semibold uppercase tracking-widest text-[#94A3B8] mb-3">
            Activity · FY {financialYear}
          </p>
          <ClientTimeline clientId={clientId} financialYear={financialYear} />
        </div>
      </div>

      {/* ── Right sidebar ───────────────────────────────────── */}
      <div className="w-[240px] shrink-0 border-l border-[#F1F5F9] overflow-y-auto p-4 space-y-4 hidden lg:block">
        {/* Health Alerts */}
        {alerts.length > 0 && (
          <div className="space-y-1">
            {alerts.map((alert, i) => {
              const Icon = alert.severity === "critical" ? AlertCircle
                : alert.severity === "warning" ? AlertTriangle : Info;
              const colors = alert.severity === "critical"
                ? "bg-red-50 border-red-200 text-red-600"
                : alert.severity === "warning"
                ? "bg-amber-50 border-amber-200 text-amber-600"
                : "bg-blue-50 border-blue-200 text-blue-600";
              return (
                <div key={i} className={`rounded-lg border px-2.5 py-2 flex items-start gap-2 ${colors}`}>
                  <Icon size={11} className="shrink-0 mt-0.5" />
                  <div>
                    <p className="text-[10px] font-semibold">{alert.dimension}</p>
                    <p className="text-[10px] opacity-80 leading-snug">{alert.message}</p>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* Health score */}
        {health && (
          <div className="bg-white rounded-xl border border-[#E2E8F0] p-3 space-y-2">
            <p className="text-[10px] font-semibold uppercase tracking-widest text-[#94A3B8]">
              Health Score
            </p>
            <div className="flex items-center gap-2">
              <HealthBadge score={health.overall_score} size="md" trend={health.trend} />
            </div>
            <div className="space-y-1.5 mt-1">
              {Object.entries(health.dimensions).map(([key, dim]) => (
                <ScoreRow key={key} label={DIMENSION_LABELS[key] ?? key} value={dim.score} />
              ))}
            </div>
          </div>
        )}

        {/* Client info */}
        <div className="bg-white rounded-xl border border-[#E2E8F0] p-3 space-y-2">
          <p className="text-[10px] font-semibold uppercase tracking-widest text-[#94A3B8]">
            Client
          </p>
          <p className="text-[13px] font-semibold text-[#1E293B] leading-snug">{client.client_name}</p>
          <p className="text-[10px] text-[#94A3B8]">
            {ENTITY_TYPE_LABELS[client.entity_type] ?? client.entity_type}
          </p>
          <div className="space-y-1.5 pt-1 border-t border-[#E2E8F0]">
            {client.pan && (
              <InfoRow label="PAN" value={client.pan} mono />
            )}
            {client.gstin && (
              <InfoRow label="GSTIN" value={client.gstin} mono />
            )}
            {client.email && (
              <div className="flex items-center gap-1.5 text-[11px] text-[#64748B]">
                <Mail size={11} className="shrink-0" />
                <span className="truncate">{client.email}</span>
              </div>
            )}
            {client.mobile && (
              <div className="flex items-center gap-1.5 text-[11px] text-[#64748B]">
                <Phone size={11} className="shrink-0" />
                <span>{client.mobile}</span>
              </div>
            )}
            {client.city && (
              <div className="flex items-center gap-1.5 text-[11px] text-[#64748B]">
                <MapPin size={11} className="shrink-0" />
                <span>{client.city}{client.state ? `, ${client.state}` : ""}</span>
              </div>
            )}
            {client.gst_filing_frequency && (
              <div className="flex items-center gap-1.5 text-[11px] text-[#64748B]">
                <Calendar size={11} className="shrink-0" />
                <span>GST: {client.gst_filing_frequency}</span>
              </div>
            )}
          </div>
        </div>

        {/* Upcoming deadlines */}
        {compliance.filter((c) => c.filing_status !== "filed" && c.due_date >= today).length > 0 && (
          <div className="bg-white rounded-xl border border-[#E2E8F0] p-3 space-y-2">
            <p className="text-[10px] font-semibold uppercase tracking-widest text-[#94A3B8]">
              Upcoming
            </p>
            <div className="space-y-2">
              {compliance
                .filter((c) => c.filing_status !== "filed" && c.due_date >= today)
                .slice(0, 4)
                .map((c) => (
                  <div key={c.id} className="flex items-center justify-between gap-2">
                    <p className="text-[11px] text-[#475569] truncate">{c.compliance_type}</p>
                    <p className={`text-[10px] font-mono shrink-0 ${
                      daysUntil(c.due_date) <= 7 ? "text-amber-600" : "text-[#64748B]"
                    }`}>
                      {formatDate(c.due_date)}
                    </p>
                  </div>
                ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function daysUntil(dateStr: string): number {
  return Math.ceil((new Date(dateStr).getTime() - Date.now()) / 86400000);
}

function StatCard({
  icon, label, value, accent,
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
  accent: "indigo" | "amber" | "neutral";
}) {
  const bg = accent === "indigo" && value > 0 ? "bg-blue-50 border-blue-500/20/15"
    : accent === "amber" && value > 0 ? "bg-amber-50 border-amber-500/15"
    : "bg-[#F8FAFC] border-[#F1F5F9]";
  return (
    <div className={`rounded-xl border p-3 space-y-1 ${bg}`}>
      <div className="flex items-center gap-1.5">
        {icon}
        <p className="text-[10px] text-[#94A3B8]">{label}</p>
      </div>
      <p className="text-2xl font-bold text-[#1E293B] tabular-nums">{value}</p>
    </div>
  );
}

function ScoreRow({ label, value }: { label: string; value: number }) {
  const pct = Math.min(100, value);
  const color = value >= 80 ? "bg-emerald-500" : value >= 60 ? "bg-yellow-500" : value >= 40 ? "bg-orange-500" : "bg-red-500";
  return (
    <div className="space-y-0.5">
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-[#64748B]">{label}</span>
        <span className="text-[10px] font-semibold tabular-nums text-[#1E293B]">
          {value}
        </span>
      </div>
      <div className="h-1 rounded-full bg-[#E2E8F0] overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function InfoRow({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-start gap-1.5">
      <span className="text-[9px] text-[#94A3B8] mt-0.5 shrink-0 w-10">{label}</span>
      <span className={`text-[11px] text-[#475569] break-all ${mono ? "font-mono" : ""}`}>{value}</span>
    </div>
  );
}

function OverviewSkeleton() {
  return (
    <div className="flex h-full overflow-hidden">
      <div className="flex-1 p-5 space-y-4">
        <div className="grid grid-cols-3 gap-3">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-16 rounded-xl bg-[#F8FAFC] animate-pulse" />
          ))}
        </div>
        <div className="h-64 rounded-xl bg-[#F8FAFC] animate-pulse" />
      </div>
      <div className="w-[240px] p-4 space-y-4 hidden lg:block">
        <div className="h-32 rounded-xl bg-[#F8FAFC] animate-pulse" />
        <div className="h-48 rounded-xl bg-[#F8FAFC] animate-pulse" />
      </div>
    </div>
  );
}
