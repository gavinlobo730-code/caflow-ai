"use client";

import { useEffect, useState } from "react";
import { Mail, Phone, MapPin, Calendar, TrendingUp, CheckSquare, Shield } from "lucide-react";
import { getClient } from "@/lib/data/clients";
import { getTasks } from "@/lib/data/tasks";
import { getComplianceCalendar, seedComplianceCalendar } from "@/lib/data/compliance";
import { getFirmId } from "@/lib/data/getFirmId";
import { snapshotHealthScore, getLatestHealthScore } from "@/lib/services/health-score-compute";
import { ClientTimeline } from "@/components/ClientTimeline";
import { HealthBadge } from "@/components/HealthBadge";
import type { Client } from "@/lib/types";
import type { Task } from "@/lib/types";
import type { ComplianceEntry } from "@/lib/data/compliance";
import { formatDate, ENTITY_TYPE_LABELS } from "@/lib/services/formatting";
import { useClientNav } from "@/lib/workspace/ClientNavContext";

interface HealthSnapshot {
  overall_score: number;
  compliance_score: number;
  trend: "improving" | "stable" | "declining" | null;
}

export default function OverviewPage() {
  const { clientId, financialYear } = useClientNav();
  const [client, setClient] = useState<Client | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [compliance, setCompliance] = useState<ComplianceEntry[]>([]);
  const [health, setHealth] = useState<HealthSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!clientId || clientId === "_placeholder") return;
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [c, t, firmId] = await Promise.all([
          getClient(clientId),
          getTasks(clientId).catch(() => [] as Task[]),
          getFirmId().catch(() => null),
        ]);
        if (cancelled) return;
        setClient(c);
        setTasks(t);

        // Load compliance calendar, seed if empty
        let comp = await getComplianceCalendar(clientId).catch(() => [] as ComplianceEntry[]);
        if (comp.length === 0 && firmId) {
          await seedComplianceCalendar(clientId).catch(() => undefined);
          comp = await getComplianceCalendar(clientId).catch(() => [] as ComplianceEntry[]);
        }
        if (cancelled) return;
        setCompliance(comp);

        // Load or compute health score
        if (firmId) {
          const existing = await getLatestHealthScore(clientId);
          const currentPeriod = new Date().toISOString().slice(0, 7);
          if (existing && existing.snapshot_period === currentPeriod) {
            setHealth({
              overall_score: existing.overall_score,
              compliance_score: existing.compliance_score,
              trend: null,
            });
          } else if (comp.length > 0) {
            const result = await snapshotHealthScore(clientId, firmId, comp);
            if (!cancelled) {
              setHealth({
                overall_score: result.overall_score,
                compliance_score: result.compliance_score,
                trend: result.trend,
              });
            }
          }
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load client");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  }, [clientId, financialYear]);

  if (loading) return <OverviewSkeleton />;
  if (error) return <div className="p-6 text-red-500 text-sm">{error}</div>;
  if (!client) return <div className="p-6 text-gray-400 text-sm">Client not found.</div>;

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

        {/* Stat strip */}
        <div className="grid grid-cols-3 gap-3">
          <StatCard
            icon={<CheckSquare size={14} className="text-indigo-400" />}
            label="Open Tasks"
            value={openTasks.length}
            accent={openTasks.length > 0 ? "indigo" : "neutral"}
          />
          <StatCard
            icon={<Shield size={14} className="text-amber-400" />}
            label="Overdue Filings"
            value={overdueFiling.length}
            accent={overdueFiling.length > 0 ? "amber" : "neutral"}
          />
          <StatCard
            icon={<TrendingUp size={14} className="text-emerald-400" />}
            label="Filed This FY"
            value={filedCount}
            accent="neutral"
          />
        </div>

        {/* Timeline */}
        <div className="bg-[#0f0f18] rounded-xl border border-white/[0.05] p-4">
          <p className="text-[11px] font-semibold uppercase tracking-widest text-white/30 mb-3">
            Activity · FY {financialYear}
          </p>
          <ClientTimeline clientId={clientId} financialYear={financialYear} />
        </div>
      </div>

      {/* ── Right sidebar ───────────────────────────────────── */}
      <div className="w-[240px] shrink-0 border-l border-white/[0.05] overflow-y-auto p-4 space-y-4 hidden lg:block">
        {/* Health score */}
        {health && (
          <div className="bg-[#0f0f18] rounded-xl border border-white/[0.05] p-3 space-y-2">
            <p className="text-[10px] font-semibold uppercase tracking-widest text-white/25">
              Health Score
            </p>
            <div className="flex items-center gap-2">
              <HealthBadge score={health.overall_score} size="md" trend={health.trend} />
            </div>
            <div className="space-y-1.5 mt-1">
              <ScoreRow label="Compliance" value={health.compliance_score} />
              <ScoreRow label="Accounting" value={50} muted />
              <ScoreRow label="Responsiveness" value={50} muted />
            </div>
            <p className="text-[9px] text-white/15 mt-1">
              Other dimensions activate in Phase 1.1
            </p>
          </div>
        )}

        {/* Client info */}
        <div className="bg-[#0f0f18] rounded-xl border border-white/[0.05] p-3 space-y-2">
          <p className="text-[10px] font-semibold uppercase tracking-widest text-white/25">
            Client
          </p>
          <p className="text-[13px] font-semibold text-white/80 leading-snug">{client.client_name}</p>
          <p className="text-[10px] text-white/35">
            {ENTITY_TYPE_LABELS[client.entity_type] ?? client.entity_type}
          </p>
          <div className="space-y-1.5 pt-1 border-t border-white/5">
            {client.pan && (
              <InfoRow label="PAN" value={client.pan} mono />
            )}
            {client.gstin && (
              <InfoRow label="GSTIN" value={client.gstin} mono />
            )}
            {client.email && (
              <div className="flex items-center gap-1.5 text-[11px] text-white/40">
                <Mail size={11} className="shrink-0" />
                <span className="truncate">{client.email}</span>
              </div>
            )}
            {client.mobile && (
              <div className="flex items-center gap-1.5 text-[11px] text-white/40">
                <Phone size={11} className="shrink-0" />
                <span>{client.mobile}</span>
              </div>
            )}
            {client.city && (
              <div className="flex items-center gap-1.5 text-[11px] text-white/40">
                <MapPin size={11} className="shrink-0" />
                <span>{client.city}{client.state ? `, ${client.state}` : ""}</span>
              </div>
            )}
            {client.gst_filing_frequency && (
              <div className="flex items-center gap-1.5 text-[11px] text-white/40">
                <Calendar size={11} className="shrink-0" />
                <span>GST: {client.gst_filing_frequency}</span>
              </div>
            )}
          </div>
        </div>

        {/* Upcoming deadlines */}
        {compliance.filter((c) => c.filing_status !== "filed" && c.due_date >= today).length > 0 && (
          <div className="bg-[#0f0f18] rounded-xl border border-white/[0.05] p-3 space-y-2">
            <p className="text-[10px] font-semibold uppercase tracking-widest text-white/25">
              Upcoming
            </p>
            <div className="space-y-2">
              {compliance
                .filter((c) => c.filing_status !== "filed" && c.due_date >= today)
                .slice(0, 4)
                .map((c) => (
                  <div key={c.id} className="flex items-center justify-between gap-2">
                    <p className="text-[11px] text-white/55 truncate">{c.compliance_type}</p>
                    <p className={`text-[10px] font-mono shrink-0 ${
                      daysUntil(c.due_date) <= 7 ? "text-amber-400" : "text-white/25"
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
  const bg = accent === "indigo" && value > 0 ? "bg-indigo-500/10 border-indigo-500/15"
    : accent === "amber" && value > 0 ? "bg-amber-500/10 border-amber-500/15"
    : "bg-white/[0.03] border-white/[0.05]";
  return (
    <div className={`rounded-xl border p-3 space-y-1 ${bg}`}>
      <div className="flex items-center gap-1.5">
        {icon}
        <p className="text-[10px] text-white/35">{label}</p>
      </div>
      <p className="text-2xl font-bold text-white/80 tabular-nums">{value}</p>
    </div>
  );
}

function ScoreRow({ label, value, muted }: { label: string; value: number; muted?: boolean }) {
  const pct = Math.min(100, value);
  const color = value >= 80 ? "bg-emerald-500" : value >= 60 ? "bg-yellow-500" : value >= 40 ? "bg-orange-500" : "bg-red-500";
  return (
    <div className="space-y-0.5">
      <div className="flex items-center justify-between">
        <span className={`text-[10px] ${muted ? "text-white/20" : "text-white/45"}`}>{label}</span>
        <span className={`text-[10px] font-semibold tabular-nums ${muted ? "text-white/20" : "text-white/60"}`}>
          {value}
        </span>
      </div>
      <div className="h-1 rounded-full bg-white/5 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${muted ? "bg-white/10" : color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function InfoRow({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-start gap-1.5">
      <span className="text-[9px] text-white/20 mt-0.5 shrink-0 w-10">{label}</span>
      <span className={`text-[11px] text-white/50 break-all ${mono ? "font-mono" : ""}`}>{value}</span>
    </div>
  );
}

function OverviewSkeleton() {
  return (
    <div className="flex h-full overflow-hidden">
      <div className="flex-1 p-5 space-y-4">
        <div className="grid grid-cols-3 gap-3">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-16 rounded-xl bg-white/[0.03] animate-pulse" />
          ))}
        </div>
        <div className="h-64 rounded-xl bg-white/[0.03] animate-pulse" />
      </div>
      <div className="w-[240px] p-4 space-y-4 hidden lg:block">
        <div className="h-32 rounded-xl bg-white/[0.03] animate-pulse" />
        <div className="h-48 rounded-xl bg-white/[0.03] animate-pulse" />
      </div>
    </div>
  );
}
