import { Upload, MessageSquare, Calendar, TrendingUp, AlertTriangle, CheckCircle } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import Link from "next/link";

const metrics = [
  {
    title: "Total Clients",
    value: "24",
    icon: TrendingUp,
    color: "text-blue-600",
    bg: "bg-blue-50",
  },
  {
    title: "Returns Due This Month",
    value: "8",
    icon: Calendar,
    color: "text-amber-600",
    bg: "bg-amber-50",
  },
  {
    title: "Overdue",
    value: "2",
    icon: AlertTriangle,
    color: "text-red-600",
    bg: "bg-red-50",
  },
];

const quickActions = [
  { label: "Upload Document", href: "/parser", icon: Upload, color: "bg-blue-600 hover:bg-blue-700" },
  { label: "Ask GST Question", href: "/assistant", icon: MessageSquare, color: "bg-purple-600 hover:bg-purple-700" },
  { label: "View Calendar", href: "/calendar", icon: Calendar, color: "bg-emerald-600 hover:bg-emerald-700" },
];

const recentActivity = [
  { id: 1, text: "GSTR-1 filed for Sharma Enterprises", time: "2 hours ago", status: "success" },
  { id: 2, text: "Form 16 parsed for Joshi Textiles employee", time: "4 hours ago", status: "success" },
  { id: 3, text: "GSTR-3B overdue reminder sent — Mehta Consulting", time: "6 hours ago", status: "warning" },
  { id: 4, text: "New client added: Desai Traders (GSTIN: 27AADCS9929B1ZE)", time: "Yesterday", status: "info" },
  { id: 5, text: "ITR filed for Patel & Sons FY 2023-24", time: "2 days ago", status: "success" },
];

export default function DashboardPage() {
  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
          <p className="text-gray-500 text-sm mt-1">Welcome back, Gavin Lobo, CA</p>
        </div>
        <Badge variant="outline" className="text-blue-700 border-blue-200 bg-blue-50 px-3 py-1">
          FY 2024-25
        </Badge>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {metrics.map((m) => (
          <Card key={m.title}>
            <CardContent className="pt-6">
              <div className="flex items-center gap-4">
                <div className={`p-3 rounded-xl ${m.bg}`}>
                  <m.icon className={`${m.color}`} size={22} />
                </div>
                <div>
                  <p className="text-sm text-gray-500">{m.title}</p>
                  <p className="text-3xl font-bold text-gray-900">{m.value}</p>
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <div>
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">Quick Actions</h2>
        <div className="flex flex-wrap gap-3">
          {quickActions.map((a) => (
            <Link
              key={a.href}
              href={a.href}
              className={`flex items-center gap-2 px-5 py-2.5 rounded-lg text-white text-sm font-medium transition-colors ${a.color}`}
            >
              <a.icon size={16} />
              {a.label}
            </Link>
          ))}
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Recent Activity</CardTitle>
        </CardHeader>
        <CardContent className="divide-y divide-gray-100">
          {recentActivity.map((item) => (
            <div key={item.id} className="flex items-start gap-3 py-3">
              <div className="mt-0.5 shrink-0">
                {item.status === "success" && <CheckCircle size={16} className="text-green-500" />}
                {item.status === "warning" && <AlertTriangle size={16} className="text-amber-500" />}
                {item.status === "info" && <TrendingUp size={16} className="text-blue-500" />}
              </div>
              <div className="flex-1">
                <p className="text-sm text-gray-800">{item.text}</p>
                <p className="text-xs text-gray-400 mt-0.5">{item.time}</p>
              </div>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
