import type { ComplianceStatus, CompliancePriority, TaskStatus, TaskPriority } from "@/lib/types";

export function daysRemaining(dueDateStr: string): number {
  const due = new Date(dueDateStr);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((due.getTime() - today.getTime()) / 86_400_000);
}

export function computePriority(days: number): CompliancePriority {
  if (days < 0) return "critical";
  if (days <= 3) return "critical";
  if (days <= 7) return "high";
  if (days <= 15) return "medium";
  return "low";
}

export function computeStatus(days: number, current: ComplianceStatus): ComplianceStatus {
  if (current === "filed") return "filed";
  if (days < 0) return "overdue";
  return "pending";
}

export const priorityColor: Record<CompliancePriority, string> = {
  critical: "text-red-700 bg-red-100",
  high: "text-orange-700 bg-orange-100",
  medium: "text-amber-700 bg-amber-100",
  low: "text-green-700 bg-green-100",
};

export const statusColor: Record<ComplianceStatus, string> = {
  overdue: "text-red-700 bg-red-100",
  pending: "text-amber-700 bg-amber-100",
  in_progress: "text-blue-700 bg-blue-100",
  filed: "text-green-700 bg-green-100",
  not_applicable: "text-gray-500 bg-gray-100",
};

export function formatDueDateLabel(days: number): string {
  if (days < 0) return `${Math.abs(days)}d overdue`;
  if (days === 0) return "Due today";
  if (days === 1) return "Due tomorrow";
  return `${days}d remaining`;
}

export const taskStatusColor: Record<TaskStatus, string> = {
  todo: "bg-gray-100 text-gray-700",
  in_progress: "bg-blue-100 text-blue-700",
  waiting_client: "bg-purple-100 text-purple-700",
  review_required: "bg-amber-100 text-amber-700",
  completed: "bg-green-100 text-green-700",
};

export const taskStatusLabel: Record<TaskStatus, string> = {
  todo: "To Do",
  in_progress: "In Progress",
  waiting_client: "Waiting Client",
  review_required: "Review Required",
  completed: "Completed",
};

export const priorityDotColor: Record<TaskPriority, string> = {
  critical: "bg-red-500",
  high: "bg-orange-400",
  medium: "bg-amber-400",
  low: "bg-gray-300",
};
