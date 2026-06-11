import { cn } from "@/lib/utils";
import type { LucideIcon } from "lucide-react";
import Link from "next/link";
import { ArrowUpRight, TrendingUp, TrendingDown } from "lucide-react";

interface StatCardProps {
  label: string;
  value: string | number;
  icon: LucideIcon;
  iconColor?: string;
  trend?: { value: string; up?: boolean };
  href?: string;
  alert?: boolean;
  /** @deprecated use iconColor */
  gradient?: string;
}

export function StatCard({
  label, value, icon: Icon,
  iconColor = "bg-blue-50 text-blue-600",
  trend, href, alert,
}: StatCardProps) {
  const content = (
    <div className={cn(
      "relative bg-white rounded-2xl border border-[#E2E8F0] p-5 overflow-hidden card-hover",
      href && "cursor-pointer",
      alert && "ring-1 ring-red-200 border-red-100"
    )}>
      <div className="flex items-start justify-between">
        <div className={cn("w-9 h-9 rounded-xl flex items-center justify-center shrink-0", iconColor)}>
          <Icon size={17} />
        </div>
        {href && <ArrowUpRight size={14} className="text-[#CBD5E1] mt-1" />}
        {alert && !href && <span className="w-2 h-2 rounded-full bg-red-500 mt-1 shrink-0" />}
      </div>
      <p className={cn("text-3xl font-bold mt-4 tracking-tight", alert ? "text-red-600" : "text-[#0F172A]")}>
        {typeof value === "number" ? value.toLocaleString("en-IN") : value}
      </p>
      <p className="text-[12px] text-[#64748B] mt-1 font-medium leading-tight">{label}</p>
      {trend && (
        <div className={cn("flex items-center gap-1 mt-2 text-[12px] font-semibold", trend.up ? "text-emerald-600" : "text-red-500")}>
          {trend.up ? <TrendingUp size={11} /> : <TrendingDown size={11} />}
          {trend.value}
        </div>
      )}
    </div>
  );
  return href ? <Link href={href}>{content}</Link> : content;
}
