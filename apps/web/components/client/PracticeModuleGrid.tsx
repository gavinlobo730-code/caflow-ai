"use client";

/**
 * THE MODULES OF MY PRACTICE: THE FIRM'S OWN BOOKS, AND THE SCREENS ABOUT RUNNING THE PRACTICE (POST-A-532).
 *
 * The same tiles a client's workspace draws (`ClientModuleGrid`), in two groups, because they are two kinds of thing a CA
 * looks for by different words: "my books" (the ledger, sales, purchases, the bank, tax: the client workspace's own
 * sections, opened on the practice's own client) and "my practice" (what it bills, what it is owed, what it earns: the
 * fixed `/practice/…` screens). `lib/workspace/practiceWorkspace.ts` says which sections each group holds and why some
 * client sections are left out. A third, short group points at the team and its hours, which stay in the firm's own menus.
 *
 * THE BOOKS NEED THE PRACTICE'S CLIENT ID, AND FOUR ANSWERS ARE KEPT APART. While it is being read the group waits with
 * placeholders; a practice that is not set up says so and points at the screen that sets it up; a read that failed says
 * it could not be read. None of the three draws tiles that lead nowhere.
 */
import Link from "next/link";
import {
  BarChart3, Building2, ClipboardList, Clock, FileText, Gauge, History, IndianRupee, Receipt, ShieldCheck, StickyNote, TrendingUp,
  UserCheck, Wallet,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { sectionsOffered } from "@/lib/workspace/ClientNavContext";
import { PRACTICE_SECTIONS, PRACTICE_TEAM_SECTIONS, booksSectionsFor } from "@/lib/workspace/practiceWorkspace";
import type { PracticeLookup } from "@/lib/workspace/usePracticeClient";
import { usePermissions } from "@/lib/auth/AuthContext";
import { SECTION_ICONS, type GridVariant } from "@/components/client/ClientModuleGrid";
import { LoadingRegion, Skeleton } from "@/components/ui/skeleton";

const PRACTICE_ICONS: Record<string, React.ElementType> = {
  home: Building2,
  billing: Receipt,
  collections: Wallet,
  ar: ClipboardList,
  revenue: IndianRupee,
  profitability: TrendingUp,
  benchmark: BarChart3,
  compliance: ShieldCheck,
  instructions: StickyNote,
  "earlier-bills": History,
  "earlier-receivables": ClipboardList,
  team: UserCheck,
  workload: Gauge,
  time: Clock,
};

function Tile({ href, label, icon: Icon, active, onNavigate }: {
  href: string; label: string; icon: React.ElementType; active: boolean; onNavigate?: () => void;
}) {
  return (
    <Link
      href={href}
      prefetch={false}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={cn(
        "module-card group flex items-center gap-2.5 rounded-xl border bg-white px-3.5 py-3 min-w-0",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-brand",
        active ? "border-brand ring-1 ring-brand" : "border-ps-border hover:border-brand",
      )}
    >
      <Icon size={15} className={cn("shrink-0", active ? "text-brand" : "text-ps-hint group-hover:text-brand")} />
      <span className="text-sm font-semibold text-ps-ink truncate">{label}</span>
    </Link>
  );
}

export function PracticeModuleGrid({
  practice,
  variant = "page",
  activeId,
  onNavigate,
}: {
  /** The practice's own client, as the shell or `usePracticeClient` resolved it. */
  practice: PracticeLookup;
  variant?: GridVariant;
  /** The client section or practice screen that is open, so its tile is marked. */
  activeId?: string | null;
  onNavigate?: () => void;
}) {
  const compact = variant === "overlay";
  const { can, resolved } = usePermissions();
  const books = booksSectionsFor(sectionsOffered(can, resolved));
  const grid = cn("grid gap-2.5", compact ? "grid-cols-2 sm:grid-cols-3 lg:grid-cols-4" : "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4");
  const heading = "mb-2 text-2xs font-semibold uppercase tracking-wide text-ps-label";

  return (
    <div className={cn("space-y-5", compact ? "p-4" : "px-4 py-6 md:px-8 md:py-8")} data-practice-modules>
      <section aria-labelledby="practice-books-heading">
        <h2 id="practice-books-heading" className={heading}>Your firm&apos;s books</h2>
        {practice.state === "ready" ? (
          <div className={grid}>
            {books.map((s) => (
              <Tile key={s.id} href={s.href(practice.practiceId)} label={s.label} icon={SECTION_ICONS[s.id] ?? FileText}
                active={activeId === s.id} onNavigate={onNavigate} />
            ))}
          </div>
        ) : practice.state === "not-set-up" ? (
          <p className="text-sm text-ps-body">
            Your firm&apos;s own books are not set up yet.{" "}
            <Link href="/practice/" onClick={onNavigate} className="font-medium text-brand underline underline-offset-2">Open Practice home</Link>{" "}
            to set them up.
          </p>
        ) : practice.state === "unavailable" ? (
          <p role="alert" className="text-sm text-state-problem">
            Your firm&apos;s books could not be read just now, so they are not listed. The practice&apos;s other screens below still open.
          </p>
        ) : (
          <LoadingRegion label="Loading your firm's books" className={grid}>
            {Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-11 rounded-xl" />)}
          </LoadingRegion>
        )}
      </section>
      <section aria-labelledby="practice-running-heading">
        <h2 id="practice-running-heading" className={heading}>Running the practice</h2>
        <div className={grid}>
          {PRACTICE_SECTIONS.map((s) => (
            <Tile key={s.id} href={s.href} label={s.label} icon={PRACTICE_ICONS[s.id] ?? FileText}
              active={activeId === `practice:${s.id}`} onNavigate={onNavigate} />
          ))}
        </div>
      </section>
      <section aria-labelledby="practice-team-heading">
        <h2 id="practice-team-heading" className={heading}>Your team and its hours</h2>
        <p className="mb-2 text-xs text-ps-body">These open in the firm&apos;s Team and Work menus.</p>
        <div className={grid}>
          {PRACTICE_TEAM_SECTIONS.map((s) => (
            <Tile key={s.id} href={s.href} label={s.label} icon={PRACTICE_ICONS[s.id] ?? FileText}
              active={false} onNavigate={onNavigate} />
          ))}
        </div>
      </section>
    </div>
  );
}
