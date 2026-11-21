"use client";

import { useState } from "react";
import Link from "next/link";
import { ChevronDown, ChevronRight, MoreHorizontal } from "lucide-react";
import { cn } from "@/lib/utils";
import { useWorkspace } from "@/lib/workspace/WorkspaceContext";
import { WORKSPACE_CONFIGS, type WorkspaceConfig } from "@/lib/workspace/workspaceConfig";
import { useScreenAccess } from "@/lib/access/useScreenAccess";
import { MORE_ID, areaShown, outerMenu } from "@/lib/workspace/outerMenu";
import { ContextPanel } from "@/components/ContextPanel";

/**
 * The firm-level "sidebar", as an overlay rather than a permanent column.
 *
 * WHAT THIS REPLACES. `WorkspaceRail` (64px, vertical, always on screen) plus
 * `ContextPanel` (220px, always on screen) — two columns, 284px, on every firm
 * screen. `ClientModuleGrid` proved the shape this wants instead: a switcher
 * that opens on demand and closes on navigate, so the screen underneath it
 * gets the whole width back. This is that shape at firm level, and it is a
 * MEGA MENU rather than a flat grid because — unlike a client's `CLIENT_
 * SECTIONS`, which are all leaves — a firm workspace's own sub-navigation is
 * exactly what `ContextPanel` already renders, and duplicating it as a
 * second, flatter list here is the "two vocabularies" mistake this codebase
 * keeps recording (see ContextPanel's own history). So this reuses it
 * unchanged: the left column picks a workspace, the right column IS that
 * workspace's ordinary panel, rendered wider than its old 220px cage.
 *
 * `ContextPanel`'s `workspaceOverride` prop exists for exactly this — it lets
 * this menu preview a workspace the URL has not navigated to yet, so pointing
 * at "Payroll" while standing on a Clients page shows Payroll's own list
 * without a click.
 *
 * WHICH AREAS ARE LISTED IS ONE RULE (POST-A-543): the permissions a Partner ticked for the person, asked of the one table
 * (`lib/access/screenAccess.ts`) through `useScreenAccess().areaOn`. Nothing is withheld on a permission until the
 * permissions are known, so an area does not flash in and then out on the first frame; My practice is asked of the role,
 * which is known sooner, and is never offered to somebody who is not a Partner.
 *
 * THE LIST SHOWS LESS, AND AN ENTRY IS A LINK (the owner's review of the live Test Firm, 21-11-2026). Three things were
 * wrong with the left column. It listed thirteen areas at once; `lib/workspace/outerMenu.ts` now says which are listed
 * first and which sit under "More", and that somebody with My practice has no separate Team entry. A CLICK on an area did
 * nothing but change the preview, so the commonest thing a person does to a menu entry went nowhere; each entry is a link to
 * the area's own first screen now, and pointing at it still previews its list. And the preview followed KEYBOARD FOCUS as
 * well as the pointer, so the button that had just been clicked could hold the list on an area the person was not looking
 * at; the preview follows the pointer only, and a keyboard opens the area with Enter.
 *
 * "MORE" IS A DISCLOSURE IN THE SAME COLUMN, not a second menu: pointing at it or pressing it opens its areas under it, each
 * an ordinary entry, and the right column lists them with a line saying what each is. It starts open when the address is in
 * one of its areas, so the person can see where they are.
 *
 * CLOSING: `WorkspaceTopBar` closes this on every pathname change, and `onNavigate` closes it at the click as well, because a
 * click on the area the person is already in changes no pathname and would leave the menu open over the screen they asked
 * for. The reused panels' own links still close it by the pathname change alone.
 */
const MORE_REGION_ID = "workspace-menu-more";

export function WorkspaceMegaMenu({ onOpenSearch, onNavigate }: { onOpenSearch: () => void; onNavigate?: () => void }) {
  const { activeWorkspace } = useWorkspace();
  const [hovered, setHovered] = useState<string | null>(null);

  // One rule (POST-A-543): an area is on the menu when the person holds what `screenAccess.AREA_RULES` asks for it.
  const { areaOn } = useScreenAccess();
  const offered = WORKSPACE_CONFIGS.filter((ws) => areaOn(ws.id));
  const byId = new Map<string, WorkspaceConfig>(offered.map((ws) => [ws.id, ws]));
  const menu = outerMenu(offered.map((ws) => ws.id));
  const [moreOpen, setMoreOpen] = useState<boolean>(() => activeWorkspace !== null && menu.more.includes(activeWorkspace));

  const shown = areaShown(hovered, activeWorkspace, menu);
  const moreIsOpen = moreOpen || menu.more.includes(shown);

  function entry(id: string, nested: boolean) {
    const ws = byId.get(id);
    if (!ws) return null;
    const Icon = ws.icon;
    const isShown = ws.id === shown;
    return (
      <Link
        key={ws.id}
        href={ws.defaultRoute}
        prefetch={false}
        onMouseEnter={() => setHovered(ws.id)}
        onClick={onNavigate}
        aria-current={ws.id === activeWorkspace ? "page" : undefined}
        data-area={ws.id}
        className={cn(
          "flex w-full items-center gap-2.5 border-l-2 py-2.5 pr-4 text-left text-xs font-semibold transition-colors",
          nested ? "pl-7" : "pl-4",
          "focus:outline-none focus-visible:bg-white focus-visible:text-brand",
          isShown
            ? "border-brand bg-white text-brand"
            : "border-transparent text-ps-label hover:bg-white/60 hover:text-ps-ink",
        )}
      >
        <Icon size={15} className="shrink-0" />
        <span className="flex-1 truncate">{ws.label}</span>
        <ChevronRight
          size={13}
          className={cn("shrink-0 transition-opacity", isShown ? "opacity-100" : "opacity-0")}
        />
      </Link>
    );
  }

  return (
    // Side by side from `sm` up (two independently-scrolling columns, each
    // capped by the shared max-height). Below `sm` the two columns cannot fit
    // a phone's width at once (196px + 260px = 456px), so they stack — the
    // workspace list gets a capped height of its own so the panel underneath,
    // which is what someone actually came here to click, keeps most of the
    // room rather than being pushed below the list.
    <div className="flex max-h-[75vh] min-h-[22rem] flex-col sm:flex-row">
      <nav
        aria-label="Workspaces"
        className="max-h-40 shrink-0 overflow-y-auto border-b border-ps-border bg-ps-bg/60 py-2 sm:max-h-none sm:w-[196px] sm:border-b-0 sm:border-r"
      >
        {menu.main.map((id) => entry(id, false))}
        {menu.more.length > 0 && (
          <>
            <button
              type="button"
              onMouseEnter={() => { setHovered(MORE_ID); setMoreOpen(true); }}
              onClick={() => { setHovered(MORE_ID); setMoreOpen(true); }}
              aria-expanded={moreIsOpen}
              aria-controls={MORE_REGION_ID}
              data-area={MORE_ID}
              className={cn(
                "flex w-full items-center gap-2.5 border-l-2 px-4 py-2.5 text-left text-xs font-semibold transition-colors",
                "focus:outline-none focus-visible:bg-white focus-visible:text-brand",
                shown === MORE_ID
                  ? "border-brand bg-white text-brand"
                  : "border-transparent text-ps-label hover:bg-white/60 hover:text-ps-ink",
              )}
            >
              <MoreHorizontal size={15} className="shrink-0" />
              <span className="flex-1 truncate">More</span>
              <ChevronDown size={13} className={cn("shrink-0 transition-transform", moreIsOpen && "rotate-180")} />
            </button>
            <div id={MORE_REGION_ID} role="group" aria-label="More areas" hidden={!moreIsOpen}>
              {moreIsOpen && menu.more.map((id) => entry(id, true))}
            </div>
          </>
        )}
      </nav>
      <div className="min-h-0 flex-1 overflow-y-auto bg-white sm:w-[260px] sm:flex-none">
        {shown === MORE_ID ? (
          <div className="flex h-full flex-col" data-more-areas>
            <div className="shrink-0 border-b border-gray-200 px-4 py-3">
              <p className="text-sm font-semibold text-brand">More</p>
              <p className="mt-0.5 text-2xs text-gray-500">The other areas of the firm</p>
            </div>
            <ul className="flex-1 overflow-y-auto px-2 py-2">
              {menu.more.map((id) => {
                const ws = byId.get(id);
                if (!ws) return null;
                const Icon = ws.icon;
                return (
                  <li key={id}>
                    <Link
                      href={ws.defaultRoute}
                      prefetch={false}
                      onClick={onNavigate}
                      className="flex items-start gap-2.5 rounded-[7px] px-2.5 py-2 text-gray-600 transition-colors hover:bg-ps-bg hover:text-brand"
                    >
                      <Icon size={15} className="mt-0.5 shrink-0 text-gray-500" />
                      <span className="min-w-0">
                        <span className="block truncate text-xs font-medium">{ws.label}</span>
                        <span className="block text-2xs text-gray-500">{ws.description}</span>
                      </span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ) : (
          <ContextPanel onOpenSearch={onOpenSearch} workspaceOverride={shown} />
        )}
      </div>
    </div>
  );
}
