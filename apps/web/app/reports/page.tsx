
import { BarChart3, Users, TrendingUp, CheckSquare, Download } from "lucide-react";

const SECTIONS = [
  {
    title: "Compliance Reports",
    icon: CheckSquare,
    reports: [
      { name: "Monthly Compliance Summary", description: "Overview of all filings due, filed, and overdue", formats: ["PDF", "Excel"] },
      { name: "GSTR Filing Status Report", description: "Client-wise GST return status across periods", formats: ["PDF", "Excel"] },
      { name: "ITR Status Report", description: "Assessment-year-wise ITR filing tracker", formats: ["PDF", "Excel"] },
      { name: "TDS Compliance Report", description: "Quarterly TDS return and certificate tracker", formats: ["PDF"] },
    ],
  },
  {
    title: "Client Reports",
    icon: Users,
    reports: [
      { name: "Client Portfolio Summary", description: "All clients with compliance health scores", formats: ["PDF", "Excel"] },
      { name: "Outstanding Documents", description: "Clients with pending document submissions", formats: ["Excel"] },
      { name: "Client Activity Log", description: "Timeline of all actions per client", formats: ["PDF"] },
    ],
  },
  {
    title: "Revenue Reports",
    icon: TrendingUp,
    reports: [
      { name: "Monthly Revenue Statement", description: "Fee collection and outstanding receivables", formats: ["PDF", "Excel"] },
      { name: "Service-wise Revenue", description: "Revenue breakdown by GST, ITR, TDS, MCA", formats: ["Excel"] },
    ],
  },
  {
    title: "Team Productivity",
    icon: BarChart3,
    reports: [
      { name: "Team Workload Report", description: "Tasks assigned, completed, and pending per member", formats: ["PDF", "Excel"] },
      { name: "Turnaround Time Analysis", description: "Average time from task creation to completion", formats: ["Excel"] },
    ],
  },
];

export default function ReportsPage() {
  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-gray-900">Reports</h1>
        <p className="text-sm text-gray-500 mt-0.5">Generate and export practice reports</p>
      </div>

      <div className="space-y-6">
        {SECTIONS.map((section) => (
          <div key={section.title} className="bg-white rounded-xl border border-gray-100 overflow-hidden">
            <div className="flex items-center gap-2.5 px-5 py-4 border-b border-gray-50">
              <section.icon size={16} className="text-gray-500" />
              <h2 className="text-sm font-semibold text-gray-900">{section.title}</h2>
            </div>
            <div className="divide-y divide-gray-50">
              {section.reports.map((report) => (
                <div key={report.name} className="flex items-center gap-4 px-5 py-3.5">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-900">{report.name}</p>
                    <p className="text-xs text-gray-400 mt-0.5">{report.description}</p>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {report.formats.map((fmt) => (
                      <button key={fmt} className="flex items-center gap-1 px-3 py-1.5 text-xs font-medium border border-gray-200 rounded-lg text-gray-600 hover:bg-gray-50 hover:border-gray-300 transition-colors">
                        <Download size={11} />
                        {fmt}
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
