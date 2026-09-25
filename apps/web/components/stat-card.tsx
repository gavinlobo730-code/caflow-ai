import { cn } from "@/lib/utils";
import type { LucideIcon } from "lucide-react";
import Link from "next/link";
import { ArrowUpRight, TrendingUp, TrendingDown } from "lucide-react";

interface StatCardProps {
  label: string;
  value: string | number;
  icon: LucideIcon;
  /**
   * The icon chip's fill and ink, as a pair of token classes. Defaults to the
   * brand chip, which is what a tile with nothing particular to say should be.
   *
   * ⚠️ THERE USED TO BE A `gradient` PROP HERE AND IT WAS DROPPED ON THE
   * FLOOR. It was declared on this interface, marked `@deprecated use
   * iconColor`, and never destructured out of the props object — so the four
   * `gradient="bg-gradient-to-br from-…"` values the income-tax page passed
   * were type-checked, accepted and discarded, and all four tiles rendered
   * this default. That is the `InvoiceLineIn.is_service` shape (migration
   * 411): a field a caller sets, a validator accepts, and no writer mentions.
   * A deprecation notice on a prop nothing reads is worse than no prop,
   * because it reads as "still works, prefer the other one".
   *
   * It is deleted rather than implemented. Four stat tiles in four different
   * hues is the multi-accent pattern the palette exists to stop, and the
   * screen has rendered one chip colour for as long as anyone has looked at
   * it — implementing the prop would be a visual CHANGE dressed as a fix.
   */
  iconColor?: string;
  trend?: { value: string; up?: boolean };
  href?: string;
  alert?: boolean;
}

export function StatCard({
  label, value, icon: Icon,
  iconColor = "bg-brand-surface text-brand",
  trend, href, alert,
}: StatCardProps) {
  const content = (
    <div className={cn(
      "relative bg-white rounded-2xl border border-ps-border p-5 overflow-hidden card-hover",
      href && "cursor-pointer",
      alert && "ring-1 ring-state-problem-border border-state-problem-border"
    )}>
      <div className="flex items-start justify-between">
        <div className={cn("w-9 h-9 rounded-xl flex items-center justify-center shrink-0", iconColor)}>
          <Icon size={17} />
        </div>
        {href && <ArrowUpRight size={14} className="text-ps-disabled mt-1" />}
        {alert && !href && <span className="w-2 h-2 rounded-full bg-state-problem mt-1 shrink-0" />}
      </div>
      <p className={cn("text-3xl font-bold mt-4 tracking-tight", alert ? "text-state-problem" : "text-ps-ink")}>
        {typeof value === "number" ? value.toLocaleString("en-IN") : value}
      </p>
      <p className="text-xs text-ps-label mt-1 font-medium leading-tight">{label}</p>
      {trend && (
        /* A trend is a DIRECTION, and the two directions are the two ends of
           the severity ramp rather than a pair of raw greens and reds —
           `state.ready` and `state.problem`, which the token file already
           notes are the same values `severity.ok` and `severity.critical`
           take, deliberately. */
        <div className={cn("flex items-center gap-1 mt-2 text-xs font-semibold", trend.up ? "text-state-ready" : "text-state-problem")}>
          {trend.up ? <TrendingUp size={11} /> : <TrendingDown size={11} />}
          {trend.value}
        </div>
      )}
    </div>
  );
  return href ? <Link href={href}>{content}</Link> : content;
}
