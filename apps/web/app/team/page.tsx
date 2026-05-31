import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

const MOCK_TEAM = [
  {
    id: "tm-001",
    name: "Gavin Lobo",
    email: "gavin@caflow.in",
    role: "owner",
    is_active: true,
    assigned_open_tasks: 6,
    completed_tasks: 12,
    workload_pct: 100,
    pending_reviews: 1,
  },
];

const MOCK_WORKLOAD_TASKS = [
  { id: "task-007", title: "CA Review — GSTR-1 Sharma Enterprises", status: "review_required", priority: "critical", client: "Sharma Enterprises" },
  { id: "task-001", title: "Collect Sales Data — GSTR-1", status: "in_progress", priority: "critical", client: "Sharma Enterprises" },
  { id: "task-003", title: "GSTR-3B — Mehta Consulting", status: "waiting_client", priority: "critical", client: "Mehta Consulting" },
  { id: "task-004", title: "Tax Liability — GSTR-3B Patel & Sons", status: "todo", priority: "high", client: "Patel & Sons" },
  { id: "task-005", title: "ITR Documents — Joshi Textiles", status: "in_progress", priority: "high", client: "Joshi Textiles" },
  { id: "task-002", title: "Classify Supplies — GSTR-1", status: "todo", priority: "critical", client: "Sharma Enterprises" },
];

const statusColor: Record<string, string> = {
  review_required: "bg-amber-100 text-amber-700",
  waiting_client: "bg-purple-100 text-purple-700",
  in_progress: "bg-blue-100 text-blue-700",
  todo: "bg-gray-100 text-gray-600",
  completed: "bg-green-100 text-green-700",
};

const statusLabel: Record<string, string> = {
  review_required: "Review",
  waiting_client: "Waiting",
  in_progress: "Active",
  todo: "Todo",
  completed: "Done",
};

const priorityColor: Record<string, string> = {
  critical: "bg-red-100 text-red-700",
  high: "bg-orange-100 text-orange-700",
  medium: "bg-amber-100 text-amber-700",
  low: "bg-gray-100 text-gray-600",
};

function WorkloadBar({ pct }: { pct: number }) {
  const color = pct >= 90 ? "bg-red-500" : pct >= 70 ? "bg-amber-500" : "bg-green-500";
  return (
    <div className="w-full bg-gray-100 rounded-full h-2 mt-1">
      <div className={`h-2 rounded-full ${color} transition-all`} style={{ width: `${Math.min(pct, 100)}%` }} />
    </div>
  );
}

export default function TeamPage() {
  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Team</h1>
        <p className="text-gray-500 text-sm mt-1">{MOCK_TEAM.length} member{MOCK_TEAM.length !== 1 ? "s" : ""}</p>
      </div>

      {MOCK_TEAM.map((member) => (
        <Card key={member.id}>
          <CardHeader className="pb-4">
            <div className="flex items-start gap-4">
              <div className="w-12 h-12 rounded-full bg-blue-700 text-white flex items-center justify-center font-bold text-lg shrink-0">
                {member.name.split(" ").map((n) => n[0]).join("")}
              </div>
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <h2 className="text-base font-semibold text-gray-900">{member.name}</h2>
                  <Badge variant="secondary" className="text-xs capitalize">{member.role}</Badge>
                  {member.is_active && <Badge variant="secondary" className="bg-green-100 text-green-700 text-xs">Active</Badge>}
                </div>
                <p className="text-sm text-gray-500 mt-0.5">{member.email}</p>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
              <div className="text-center p-3 bg-gray-50 rounded-lg">
                <p className="text-xl font-bold text-gray-900">{member.assigned_open_tasks}</p>
                <p className="text-xs text-gray-500 mt-0.5">Open Tasks</p>
              </div>
              <div className="text-center p-3 bg-green-50 rounded-lg">
                <p className="text-xl font-bold text-green-700">{member.completed_tasks}</p>
                <p className="text-xs text-gray-500 mt-0.5">Completed</p>
              </div>
              <div className="text-center p-3 bg-amber-50 rounded-lg">
                <p className="text-xl font-bold text-amber-700">{member.pending_reviews}</p>
                <p className="text-xs text-gray-500 mt-0.5">Pending Review</p>
              </div>
              <div className="p-3 bg-gray-50 rounded-lg">
                <div className="flex items-center justify-between">
                  <p className="text-xs text-gray-500">Workload</p>
                  <p className="text-sm font-bold text-gray-900">{member.workload_pct}%</p>
                </div>
                <WorkloadBar pct={member.workload_pct} />
              </div>
            </div>

            <div>
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">Assigned Tasks</p>
              <div className="divide-y divide-gray-50">
                {MOCK_WORKLOAD_TASKS.map((task) => (
                  <div key={task.id} className="flex items-center gap-3 py-2.5">
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-gray-900 truncate">{task.title}</p>
                      <p className="text-xs text-gray-500">{task.client}</p>
                    </div>
                    <span className={`text-xs px-2 py-0.5 rounded-full ${statusColor[task.status]}`}>
                      {statusLabel[task.status]}
                    </span>
                    <span className={`text-xs px-2 py-0.5 rounded-full ${priorityColor[task.priority]}`}>
                      {task.priority}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
