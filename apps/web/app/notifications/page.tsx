"use client";

import { Bell } from "lucide-react";

export default function NotificationsPage() {
  return (
    <div className="p-6 max-w-4xl mx-auto">
      <h1 className="text-xl font-semibold text-gray-900">Notifications</h1>
      <p className="text-sm text-gray-500 mt-1">Alerts for tasks, compliance, and AI insights</p>
      <div className="mt-8 bg-gray-50 rounded-xl border border-gray-100 p-12 text-center">
        <Bell size={40} className="text-gray-300 mx-auto mb-3" />
        <p className="text-sm font-medium text-gray-600 mb-1">Coming in next sprint</p>
        <p className="text-xs text-gray-400">Real-time notifications for compliance deadlines, risk alerts, and AI recommendations.</p>
      </div>
    </div>
  );
}
