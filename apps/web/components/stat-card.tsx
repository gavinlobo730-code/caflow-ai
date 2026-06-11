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
  iconColor = "bg-blue-500/10 text-blue-400",
  trend, href, alert,
}: StatCardProps) {
  const content = (
    <div className={cn(
      "relative bg-[#131620] rounded-xl border border-white/[0.07] p-5 overflow-hidden transition-colors duration-150",
      href && "cursor-pointer hover:bg-white/[0.025]",
      alert && "ring-1 ring-red-500/20"
    )}>
      <div className="flex items-start justify-between">
        <div className={cn("w-9 h-9 rounded-xl flex items-center justify-center shrink-0", iconColor)}>
          <Icon size={17} />
        </div>
        {href && <ArrowUpRight size={14} className="text-white/20 mt-1" />}
        {alert && !href && <span className="w-2 h-2 rounded-full bg-red-400 mt-1 shrink-0" />}
      </div>
      <p className={cn("text-3xl font-bold mt-4 tracking-tight", alert ? "text-red-400" : "text-white/85")}>
        {typeof value === "number" ? value.toLocaleString("en-IN") : value}
      </p>
      <p className="text-[12px] text-white/35 mt-1 font-medium leading-tight">{label}</p>
      {trend && (
        <div className={cn("flex items-center gap-1 mt-2 text-[12px] font-semibold", trend.up ? "text-emerald-400" : "text-red-400")}>
          {trend.up ? <TrendingUp size={11} /> : <TrendingDown size={11} />}
          {trend.value}
        </div>
      )}
    </div>
  );
  return href ? <Link href={href}>{content}</Link> : content;
}
