"use client";

import { useState, useEffect } from "react";
import { Users, Clock, AlertTriangle, FileText, Shield, Calendar } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import Link from "next/link";
import { getClients } from "@/lib/data/clients";
import { getTasks } from "@/lib/data/tasks";
import { getComplianceCalendar, type ComplianceEntry } from "@/lib/data/compliance";
import { getTransactions, type Transaction } from "@/lib/data/transactions";
import type { Client, Task } from "@/lib/types";

const statusColor: Record<string, string> = {
  review_required: "bg-amber-100 text-amber-700",
  waiting_client: "bg-purple-100 text-purple-700",
  in_progress: "bg-blue-100 text-blue-700",
  todo: "bg-gray-100 text-gray-600",
  completed: "bg-green-100 text-green-700",
};

interface LiveStats {
  activeClients: string;
  tasksDueToday: string;
  overdueTasks: string;
  gstDeadlines7Days: string;
  pendingInvoices: string;
  waitingClient: string;
  totalOpenTasks: string;
  reviewRequired: string;
  complianceDueWeek: string;
  complianceOverdue: string;
}

export default function DashboardContent() {
  const [stats, setStats] = useState<LiveStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const today = new Date().toISOString().split("T")[0];
        const in7Days = new Date(Date.now() + 7 * 86400000).toISOString().split("T")[0];
        const in14Days = new Date(Date.now() + 14 * 86400000).toISOString().split("T")[0];
        const monthStart = today.slice(0, 7) + "-01";

        const [clients, tasks, compliance, transactions]: [Client[], Task[], ComplianceEntry[], Transaction[]] = await Promise.all([
          getClients().catch(() => []),
          getTasks().catch(() => []),
          getComplianceCalendar().catch(() => []),
          getTransactions().catch(() => []),
        ]);

        const activeClients = clients.filter(c => c.status === "active").length;
        const tasksDueToday = tasks.filter(t => t.due_date === today && t.status !== "completed").length;
        const overdueTasks = tasks.filter(t => t.due_date && t.due_date < today && t.status !== "completed").length;
        const gstDeadlines7Days = compliance.filter(c =>
          c.due_date >= today && c.due_date <= in7Days && c.filing_status !== "filed"
        ).length;
        const pendingInvoices = transactions.filter(t =>
          t.status === "draft" && t.transaction_date >= monthStart
        ).length;
        const waitingClient = tasks.filter(t => t.status === "waiting_client").length;
        const totalOpenTasks = tasks.filter(t => t.status !== "completed").length;
        const reviewRequired = tasks.filter(t => t.status === "review_required").length;
        const complianceDueWeek = compliance.filter(c =>
          c.due_date >= today && c.due_date <= in14Days && c.filing_status !== "filed"
        ).length;
        const complianceOverdue = compliance.filter(c =>
          c.due_date < today && c.filing_status !== "filed"
        ).length;

        setStats({
          activeClients: String(activeClients),
          tasksDueToday: String(tasksDueToday),
          overdueTasks: String(overdueTasks),
          gstDeadlines7Days: String(gstDeadlines7Days),
          pendingInvoices: String(pendingInvoices),
          waitingClient: String(waitingClient),
          totalOpenTasks: String(totalOpenTasks),
          reviewRequired: String(reviewRequired),
          complianceDueWeek: String(complianceDueWeek),
          complianceOverdue: String(complianceOverdue),
        });
      } catch {
        setStats({
          activeClients: "0", tasksDueToday: "0", overdueTasks: "0",
          gstDeadlines7Days: "0", pendingInvoices: "0", waitingClient: "0",
          totalOpenTasks: "0", reviewRequired: "0", complianceDueWeek: "0",
          complianceOverdue: "0",
        });
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  const s = stats ?? {
    activeClients: "…", tasksDueToday: "…", overdueTasks: "…",
    gstDeadlines7Days: "…", pendingInvoices: "…", waitingClient: "…",
    totalOpenTasks: "…", reviewRequired: "…", complianceDueWeek: "…",
    complianceOverdue: "…",
  };

  const DASHBOARD_STATS = [
    { label: "Active Clients", value: loading ? "…" : s.activeClients, icon: Users, color: "text-blue-600", bg: "bg-blue-50", href: "/clients" },
    { label: "Tasks Due Today", value: loading ? "…" : s.tasksDueToday, icon: Clock, color: "text-amber-600", bg: "bg-amber-50", href: "/tasks" },
    { label: "Overdue Tasks", value: loading ? "…" : s.overdueTasks, icon: AlertTriangle, color: "text-red-600", bg: "bg-red-50", href: "/tasks?status=overdue" },
    { label: "GST Deadlines (7d)", value: loading ? "…" : s.gstDeadlines7Days, icon: Calendar, color: "text-orange-600", bg: "bg-orange-50", href: "/compliance" },
    { label: "Pending Invoices", value: loading ? "…" : s.pendingInvoices, icon: FileText, color: "text-purple-600", bg: "bg-purple-50", href: "/gst" },
    { label: "Waiting on Client", value: loading ? "…" : s.waitingClient, icon: Shield, color: "text-indigo-600", bg: "bg-indigo-50", href: "/tasks?status=waiting_client" },
  ];

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Operations Dashboard</h1>
          <p className="text-gray-500 text-sm mt-1">Gavin Lobo &amp; Associates — CA Practice</p>
        </div>
        <Badge variant="outline" className="text-blue-700 border-blue-200 bg-blue-50 px-3 py-1">
          FY 2025-26
        </Badge>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        {DASHBOARD_STATS.map((stat) => (
          <Link key={stat.label} href={stat.href}>
            <Card className="hover:shadow-md transition-shadow cursor-pointer h-full">
              <CardContent className="pt-5 pb-4">
                <div className={`w-9 h-9 rounded-lg ${stat.bg} flex items-center justify-center mb-3`}>
                  <stat.icon className={stat.color} size={18} />
                </div>
                <p className="text-2xl font-bold text-gray-900">{stat.value}</p>
                <p className="text-xs text-gray-500 mt-0.5 leading-tight">{stat.label}</p>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        {/* Tasks summary */}
        <div className="lg:col-span-3">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-3">
              <CardTitle className="text-sm">Task Overview</CardTitle>
              <Link href="/tasks" className="text-xs text-blue-600 hover:underline">View all →</Link>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 gap-3">
                {[
                  { label: "Total Open", value: loading ? "…" : s.totalOpenTasks, status: "in_progress" },
                  { label: "Waiting Client", value: loading ? "…" : s.waitingClient, status: "waiting_client" },
                  { label: "Review Required", value: loading ? "…" : s.reviewRequired, status: "review_required" },
                  { label: "Compliance Due (14d)", value: loading ? "…" : s.complianceDueWeek, status: "todo" },
                ].map((item) => (
                  <div key={item.label} className="flex items-center justify-between py-2 px-3 rounded-lg bg-gray-50">
                    <span className="text-sm text-gray-700">{item.label}</span>
                    <span className={`text-xs px-2 py-0.5 rounded-full ${statusColor[item.status]}`}>
                      {item.value}
                    </span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Compliance summary */}
        <div className="lg:col-span-2">
          <Card className="h-full">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm">Compliance Summary</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {[
                { label: "Overdue Filings", value: loading ? "…" : s.complianceOverdue, color: "text-red-600" },
                { label: "Due Next 14 Days", value: loading ? "…" : s.complianceDueWeek, color: "text-amber-600" },
                { label: "GST Deadlines (7d)", value: loading ? "…" : s.gstDeadlines7Days, color: "text-orange-600" },
                { label: "Pending Invoices", value: loading ? "…" : s.pendingInvoices, color: "text-blue-600" },
              ].map((item) => (
                <div key={item.label} className="flex items-center justify-between">
                  <span className="text-xs text-gray-600">{item.label}</span>
                  <span className={`text-sm font-bold ${item.color}`}>{item.value}</span>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
