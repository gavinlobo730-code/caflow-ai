"use client";

import { useEffect, useState } from "react";
import { Building2, Mail, Phone, MapPin, Calendar } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { getClient } from "@/lib/data/clients";
import { getTasks } from "@/lib/data/tasks";
import { getComplianceCalendar } from "@/lib/data/compliance";
import type { Client } from "@/lib/types";
import type { Task } from "@/lib/types";
import type { ComplianceEntry } from "@/lib/data/compliance";
import { formatDate, ENTITY_TYPE_LABELS } from "@/lib/services/formatting";
import { useClientNav } from "@/lib/workspace/ClientNavContext";

const TASK_STATUS_COLORS: Record<string, string> = {
  todo: "bg-gray-100 text-gray-600",
  in_progress: "bg-blue-100 text-blue-700",
  waiting_client: "bg-purple-100 text-purple-700",
  review_required: "bg-amber-100 text-amber-700",
  completed: "bg-green-100 text-green-700",
};

function LoadingSkeleton() {
  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6 animate-pulse">
      <div className="h-8 bg-gray-200 rounded w-64" />
      <div className="grid grid-cols-2 gap-4">
        <div className="h-40 bg-gray-100 rounded-xl" />
        <div className="h-40 bg-gray-100 rounded-xl" />
      </div>
    </div>
  );
}

export default function OverviewPage() {
  const { clientId } = useClientNav();
  const [client, setClient] = useState<Client | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [compliance, setCompliance] = useState<ComplianceEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!clientId || clientId === "_placeholder") return;
    async function load() {
      setLoading(true);
      try {
        const [c, t, comp] = await Promise.all([
          getClient(clientId),
          getTasks(clientId).catch(() => [] as Task[]),
          getComplianceCalendar(clientId).catch(() => [] as ComplianceEntry[]),
        ]);
        setClient(c);
        setTasks(t);
        setCompliance(comp);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load client");
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [clientId]);

  if (loading) return <LoadingSkeleton />;
  if (error) return <div className="p-6 text-red-500">{error}</div>;
  if (!client) return <div className="p-6 text-gray-400">Client not found.</div>;

  const overdueTasks = tasks.filter((t) => t.status !== "completed");
  const pendingCompliance = compliance.filter((c) => c.filing_status === "pending" || c.filing_status === "overdue");

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      {/* Client info card */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Building2 size={16} />
            {client.client_name}
            {client.entity_type && (
              <Badge variant="outline" className="text-xs">
                {ENTITY_TYPE_LABELS[client.entity_type] ?? client.entity_type}
              </Badge>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-2 gap-4 text-sm">
          {(client as Client & { email?: string }).email && (
            <div className="flex items-center gap-2 text-gray-600">
              <Mail size={13} />
              <span>{(client as Client & { email?: string }).email}</span>
            </div>
          )}
          {(client as Client & { phone?: string }).phone && (
            <div className="flex items-center gap-2 text-gray-600">
              <Phone size={13} />
              <span>{(client as Client & { phone?: string }).phone}</span>
            </div>
          )}
          {(client as Client & { address?: string }).address && (
            <div className="flex items-center gap-2 text-gray-600">
              <MapPin size={13} />
              <span>{(client as Client & { address?: string }).address}</span>
            </div>
          )}
          {client.gstin && (
            <div className="flex items-center gap-2 text-gray-600 font-mono text-xs">
              <span className="font-sans font-medium text-gray-500">GSTIN:</span>
              {client.gstin}
            </div>
          )}
          {client.pan && (
            <div className="flex items-center gap-2 text-gray-600 font-mono text-xs">
              <span className="font-sans font-medium text-gray-500">PAN:</span>
              {client.pan}
            </div>
          )}
          {(client as Client & { registered_on?: string }).registered_on && (
            <div className="flex items-center gap-2 text-gray-600">
              <Calendar size={13} />
              <span>Since {formatDate((client as Client & { registered_on?: string }).registered_on!)}</span>
            </div>
          )}
        </CardContent>
      </Card>

      {/* At-a-glance stats */}
      <div className="grid grid-cols-3 gap-4">
        <Card>
          <CardContent className="p-4">
            <p className="text-xs text-gray-500 mb-1">Open Tasks</p>
            <p className="text-2xl font-bold text-gray-900">{overdueTasks.length}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <p className="text-xs text-gray-500 mb-1">Pending Filings</p>
            <p className="text-2xl font-bold text-amber-600">{pendingCompliance.length}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <p className="text-xs text-gray-500 mb-1">Completed Tasks</p>
            <p className="text-2xl font-bold text-green-600">
              {tasks.filter((t) => t.status === "completed").length}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Recent open tasks */}
      {overdueTasks.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-semibold">Open Tasks</CardTitle>
          </CardHeader>
          <CardContent className="divide-y divide-gray-100">
            {overdueTasks.slice(0, 5).map((task) => (
              <div key={task.id} className="py-2.5 flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-gray-800">{task.title}</p>
                  {task.due_date && (
                    <p className="text-xs text-gray-400">Due {formatDate(task.due_date)}</p>
                  )}
                </div>
                <span className={`text-[11px] font-medium px-2 py-0.5 rounded-full ${TASK_STATUS_COLORS[task.status] ?? "bg-gray-100 text-gray-600"}`}>
                  {task.status.replace(/_/g, " ")}
                </span>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
