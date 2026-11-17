import {
  ArrowLeft,
  Building,
  ChevronDown,
  ChevronsUpDown,
  LayoutGrid,
  Search,
  Settings,
} from "../../icons";
import { HEALTH, TOP_BAR } from "./productWords";

/**
 * The client workspace's 48px top bar, redrawn (D23 to D25).
 *
 * Copied on 16-11-2026 from apps/web/components/shell/ClientTopBar.tsx, with the
 * health pill from components/HealthBadge.tsx and the three controls on the right
 * from components/shell/UtilityCluster.tsx. Inside a client the product shows
 * this bar and nothing else as chrome: the way out ("All clients") first, the
 * client's name (which is the client switcher), its entity type and GSTIN, the
 * module switcher (which reads "All modules" on the front door and the module's
 * name inside one), the health score with its band and trend, then search,
 * settings and the account. The firm's rail and the old 21-item client sidebar
 * are gone, which is why the recreation it replaced (a navy sidebar) was wrong.
 *
 * The client, its GSTIN and its score are illustrative. The GSTIN is
 * well-formed, check digit included, because a CA will read it. The entity
 * chip and the GSTIN are drawn one grey darker than the product's (#6B7280 on
 * #F3F4F6 is just under WCAG's 4.5:1, which a trial axe scan of the home page
 * reported), so the picture passes on a public page.
 */
export const CLIENT = {
  name: "Vaidehi Textiles Private Limited",
  entityType: "Private Limited",
  gstin: "27AACCV4721K1Z6",
  score: 84,
};

export function ClientBar({ module }: { module: string }) {
  return (
    <div className="flex h-12 items-center gap-3 border-b border-[#E5E7EB] bg-white px-4">
      <span className="flex h-8 shrink-0 items-center gap-1.5 rounded-lg border border-[#E2E8F0] px-2.5 text-xs font-medium text-[#475569]">
        <ArrowLeft size={14} />
        {TOP_BAR.exit}
      </span>

      <span className="h-5 w-px shrink-0 bg-[#E2E8F0]" aria-hidden="true" />

      <Building size={15} className="shrink-0 text-[#9CA3AF]" />

      <span className="flex min-w-0 items-center gap-3">
        <span className="inline-flex min-w-0 items-center gap-1.5">
          <span className="truncate text-sm font-semibold text-[#182350]">{CLIENT.name}</span>
          <ChevronsUpDown size={13} className="shrink-0 text-[#64748B]" />
        </span>
        <span className="shrink-0 rounded bg-[#F3F4F6] px-1.5 py-0.5 text-[10px] font-medium text-[#4B5563]">
          {CLIENT.entityType}
        </span>
        <span className="hidden shrink-0 font-mono text-[10px] text-[#4B5563] xl:inline">
          {CLIENT.gstin}
        </span>
      </span>

      <span className="flex h-8 shrink-0 items-center gap-1.5 rounded-lg px-2.5 text-xs font-semibold text-[#0D1635]">
        <LayoutGrid size={13} className="shrink-0" />
        <span className="max-w-[9rem] truncate">{module}</span>
        <ChevronDown size={13} className="shrink-0" />
      </span>

      <span className="min-w-0 flex-1" />

      <span className="inline-flex items-center gap-1 rounded-full bg-[#ECFDF5] px-2 py-0.5 text-[10px] font-semibold text-[#047857] ring-1 ring-[#A7F3D0]">
        <span>{CLIENT.score}</span>
        <span className="font-normal">{HEALTH.band}</span>
        <span className="text-[10px] text-[#059669]" aria-hidden="true">
          ↑
        </span>
      </span>

      <span className="flex shrink-0 items-center gap-1">
        <span className="flex h-8 w-8 items-center justify-center rounded-lg text-[#64748B]">
          <Search size={15} />
        </span>
        <span className="flex h-8 w-8 items-center justify-center rounded-lg text-[#64748B]">
          <Settings size={15} />
        </span>
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-[#182350] text-[10px] font-bold text-white">
          PR
        </span>
      </span>
    </div>
  );
}
