import { ClientBar } from "./ClientBar";
import { CLIENT_MODULES, TOP_BAR } from "./productWords";

/**
 * The client workspace's front door, redrawn.
 *
 * Copied on 16-11-2026 from apps/web/app/clients/[id]/page.tsx, which renders
 * apps/web/components/client/ClientModuleGrid.tsx under the client top bar
 * (`ClientBar`, copied from components/shell/ClientTopBar.tsx). Since 25-09-2026
 * (D23 to D25) arriving at a client opens this: one card per module, in the
 * order the product lists them, and nothing else. The grid carries no figure on
 * purpose: the product took the live counts off it the day after it shipped,
 * because they arrived late and re-sorted the cards under the pointer, so a
 * figure drawn here would be one the product does not show.
 *
 * WHAT IT REPLACED, AND WHY IT IS NOW HELD BY A TEST (POST-A-121). The drawing
 * before this one was the client Overview page inside a navy 17-item sidebar,
 * copied on 16-09-2026; the product removed that sidebar on 25-09-2026 and the
 * drawing went on showing it for seven weeks. The module names now come from
 * `CLIENT_MODULES` in `productWords.ts`, and
 * `scripts/the-redrawn-screens-match-the-product.test.ts` fails when that list
 * and the product's `CLIENT_SECTIONS` differ in an id, a name or the order.
 *
 * The icons are a plain mark per card, not the product's icons. The client is
 * illustrative.
 */
export function ClientOverview() {
  return (
    <div className="min-w-[760px] bg-[#F8FAFC] text-[#0D1635]">
      <ClientBar module={TOP_BAR.allModules} />

      <div className="grid grid-cols-4 gap-2.5 px-8 py-8">
        {CLIENT_MODULES.map((m) => (
          <div
            key={m.id}
            className="flex min-w-0 items-center gap-2.5 rounded-xl border border-[#E2E8F0] bg-white px-3.5 py-3"
          >
            <span className="h-[15px] w-[15px] shrink-0 rounded-[4px] bg-[#64748B] opacity-30" aria-hidden="true" />
            <span className="truncate text-sm font-semibold text-[#0D1635]">{m.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
