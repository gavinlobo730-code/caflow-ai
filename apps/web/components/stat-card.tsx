import { cn } from "@/lib/utils";
import type { LucideIcon } from "lucide-react";
import Link from "next/link";

interface StatCardProps {
  label: string;
  value: string | number;
  icon: LucideIcon;
  iconColor?: string;
  iconBg?: string;
  trend?: { value: string; up?: boolean };
  href?: string;
  alert?: boolean;
}

export function StatCard({ label, value, icon: Icon, iconColor = "text-blue-600", iconBg = "bg-blue-50", trend, href, alert }: StatCardProps) {
  const content = (
    <div className={cn(
      "bg-white rounded-xl border border-gray-100 p-4 hover:border-gray-200 transition-colors",
      href && "cursor-pointer",
      alert && "border-red-200 bg-red-50"
    )}>
      <div className="flex items-start justify-between">
        <div className={cn("w-8 h-8 rounded-lg flex items-center justify-center", iconBg)}>
          <Icon size={16} className={iconColor} />
        </div>
        {alert && <span className="w-2 h-2 rounded-full bg-red-500 mt-1" />}
      </div>
      <p className={cn("text-2xl font-bold mt-3", alert ? "text-red-700" : "text-gray-900")}>{value}</p>
      <p className="text-xs text-gray-500 mt-0.5">{label}</p>
      {trend && (
        <p className={cn("text-xs mt-1 font-medium", trend.up ? "text-green-600" : "text-red-600")}>
          {trend.up ? "↑" : "↓"} {trend.value}
        </p>
      )}
    </div>
  );
  return href ? <Link href={href}>{content}</Link> : content;
}
