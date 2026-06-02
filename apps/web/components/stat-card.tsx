import { cn } from "@/lib/utils";
import type { LucideIcon } from "lucide-react";
import Link from "next/link";
import { ArrowUpRight, TrendingUp, TrendingDown } from "lucide-react";

interface StatCardProps {
  label: string;
  value: string | number;
  icon: LucideIcon;
  gradient?: string;
  trend?: { value: string; up?: boolean };
  href?: string;
  alert?: boolean;
}

export function StatCard({
  label, value, icon: Icon,
  gradient = "bg-gradient-to-br from-indigo-500 to-indigo-600",
  trend, href, alert,
}: StatCardProps) {
  const content = (
    <div className={cn(
      "relative bg-white rounded-2xl border border-gray-100 p-5 shadow-sm overflow-hidden card-hover",
      href && "cursor-pointer",
      alert && "ring-1 ring-red-200"
    )}>
      <div className={cn("absolute -top-4 -right-4 w-20 h-20 rounded-full opacity-10", gradient)} />
      <div className="flex items-start justify-between">
        <div className={cn("w-10 h-10 rounded-xl flex items-center justify-center shadow-sm", gradient)}>
          <Icon size={18} className="text-white" />
        </div>
        {href && <ArrowUpRight size={14} className="text-gray-300 mt-1" />}
        {alert && !href && <span className="w-2 h-2 rounded-full bg-red-500 mt-1 shrink-0" />}
      </div>
      <p className={cn("text-3xl font-bold mt-4 tracking-tight", alert ? "text-red-600" : "text-gray-900")}>
        {typeof value === "number" ? value.toLocaleString("en-IN") : value}
      </p>
      <p className="text-xs text-gray-500 mt-1 font-medium leading-tight">{label}</p>
      {trend && (
        <div className={cn("flex items-center gap-1 mt-2 text-xs font-semibold", trend.up ? "text-emerald-600" : "text-red-500")}>
          {trend.up ? <TrendingUp size={11} /> : <TrendingDown size={11} />}
          {trend.value}
        </div>
      )}
    </div>
  );
  return href ? <Link href={href}>{content}</Link> : content;
}
