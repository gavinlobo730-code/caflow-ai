
import { Users, Clock, AlertTriangle, MessageSquare, Shield, Activity } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import Link from "next/link";

// Structured to match GET /api/tasks/summary/dashboard response shape.
// Swap data source to real fetch when backend is running.
const SUMMARY = {
  active_clients: 5,
  tasks_due_today: 1,
  overdue_tasks: 1,
  waiting_client: 1,
  review_required: 1,
  total_open_tasks: 6,
  documents_pending_review: 2,
  overdue_compliance: 2,
  compliance_due_week: 4,
  compliance_overdue: 2,
  high_risk_clients: 1,
  returns_due_week: 4,
};

const DASHBOARD_STATS = [
  { label: "Active Clients", value: String(SUMMARY.active_clients), icon: Users, color: "text-blue-600", bg: "bg-blue-50", href: "/clients" },
  { label: "Tasks Due Today", value: String(SUMMARY.tasks_due_today), icon: Clock, color: "text-amber-600", bg: "bg-amber-50", href: "/tasks" },
  { label: "Overdue Tasks", value: String(SUMMARY.overdue_tasks), icon: AlertTriangle, color: "text-red-600", bg: "bg-red-50", href: "/tasks?status=overdue" },
  { label: "Compliance Overdue", value: String(SUMMARY.compliance_overdue), icon: Shield, color: "text-orange-600", bg: "bg-orange-50", href: "/compliance" },
  { label: "High-Risk Clients", value: String(SUMMARY.high_risk_clients), icon: Activity, color: "text-red-700", bg: "bg-red-50", href: "/compliance" },
  { label: "Pending Reviews", value: String(SUMMARY.review_required), icon: MessageSquare, color: "text-purple-600", bg: "bg-purple-50", href: "/tasks?status=review_required" },
];

const URGENT_TASKS = [
  { id: "task-007", client: "Sharma Enterprises", title: "CA Review — GSTR-1", status: "review_required", priority: "critical", due: "2 days", href: "/tasks" },
  { id: "task-003", client: "Mehta Consulting", title: "Compute Tax Liability — GSTR-3B", status: "waiting_client", priority: "critical", due: "Overdue 10d", href: "/tasks" },
  { id: "task-001", client: "Sharma Enterprises", title: "Collect Sales Data — GSTR-1", status: "in_progress", priority: "critical", due: "2 days", href: "/tasks" },
  { id: "task-005", client: "Joshi Textiles", title: "Collect Documents — ITR", status: "in_progress", priority: "high", due: "10 days", href: "/tasks" },
  { id: "task-004", client: "Patel & Sons", title: "Compute Tax Liability — GSTR-3B", status: "todo", priority: "high", due: "8 days", href: "/tasks" },
];

const RECENT_ACTIVITY = [
  { id: 1, text: "CA Review task created for Sharma Enterprises GSTR-1", time: "1h ago", type: "task" },
  { id: 2, text: "GSTR-3B filed for Desai Traders — ₹0 liability", time: "2h ago", type: "filed" },
  { id: 3, text: "WhatsApp reminder pending for Mehta Consulting (overdue)", time: "3h ago", type: "reminder" },
  { id: 4, text: "ITR workflow started for Joshi Textiles", time: "Yesterday", type: "workflow" },
  { id: 5, text: "GST invoice uploaded — Sharma Enterprises", time: "Yesterday", type: "document" },
];

const priorityColor: Record<string, string> = {
  critical: "bg-red-100 text-red-700",
  high: "bg-orange-100 text-orange-700",
  medium: "bg-amber-100 text-amber-700",
  low: "bg-gray-100 text-gray-600",
};

const statusColor: Record<string, string> = {
  review_required: "bg-amber-100 text-amber-700",
  waiting_client: "bg-purple-100 text-purple-700",
  in_progress: "bg-blue-100 text-blue-700",
  todo: "bg-gray-100 text-gray-600",
  completed: "bg-green-100 text-green-700",
};

const statusLabel: Record<string, string> = {
  review_required: "Review Required",
  waiting_client: "Waiting Client",
  in_progress: "In Progress",
  todo: "To Do",
  completed: "Done",
};

export default function DashboardPage() {
  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Operations Dashboard</h1>
          <p className="text-gray-500 text-sm mt-1">Gavin Lobo &amp; Associates — CA Practice</p>
        </div>
        <Badge variant="outline" className="text-blue-700 border-blue-200 bg-blue-50 px-3 py-1">
          FY 2024-25
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
        {/* Urgent tasks — 3 cols */}
        <div className="lg:col-span-3">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-3">
              <CardTitle className="text-sm">Urgent Tasks</CardTitle>
              <Link href="/tasks" className="text-xs text-blue-600 hover:underline">View all →</Link>
            </CardHeader>
            <CardContent className="divide-y divide-gray-50">
              {URGENT_TASKS.map((task) => (
                <div key={task.id} className="flex items-center gap-3 py-3">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-900 truncate">{task.title}</p>
                    <p className="text-xs text-gray-500 mt-0.5">{task.client}</p>
                  </div>
                  <span className={`text-xs px-2 py-0.5 rounded-full shrink-0 ${statusColor[task.status]}`}>
                    {statusLabel[task.status]}
                  </span>
                  <span className={`text-xs px-2 py-0.5 rounded-full shrink-0 ${priorityColor[task.priority]}`}>
                    {task.priority}
                  </span>
                  <span className="text-xs text-gray-400 shrink-0 w-16 text-right">{task.due}</span>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>

        {/* Activity — 2 cols */}
        <div className="lg:col-span-2">
          <Card className="h-full">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm">Recent Activity</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {RECENT_ACTIVITY.map((item) => (
                <div key={item.id} className="flex items-start gap-2">
                  <div className="w-1.5 h-1.5 rounded-full bg-blue-400 mt-2 shrink-0" />
                  <div>
                    <p className="text-xs text-gray-700 leading-snug">{item.text}</p>
                    <p className="text-xs text-gray-400 mt-0.5">{item.time}</p>
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
