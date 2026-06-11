import { cn } from "@/lib/utils";
import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

interface PageHeaderProps {
  icon: LucideIcon;
  iconColor?: string;
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  className?: string;
  /** @deprecated use iconColor */
  iconGradient?: string;
}

export function PageHeader({
  icon: Icon,
  iconColor = "bg-blue-50 text-blue-600",
  title,
  subtitle,
  actions,
  className,
}: PageHeaderProps) {
  return (
    <div className={cn("flex items-start justify-between gap-4 mb-6", className)}>
      <div className="flex items-center gap-3">
        <div className={cn("w-9 h-9 rounded-xl flex items-center justify-center shrink-0", iconColor)}>
          <Icon size={17} />
        </div>
        <div>
          <h1 className="text-[18px] font-semibold text-[#0F172A] tracking-tight">{title}</h1>
          {subtitle && <p className="text-[13px] text-[#64748B] mt-0.5">{subtitle}</p>}
        </div>
      </div>
      {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
    </div>
  );
}
