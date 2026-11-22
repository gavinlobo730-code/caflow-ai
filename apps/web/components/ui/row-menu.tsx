"use client";

/**
 * RowMenu — the small list of actions a table row's "more" button opens (POST-A-130).
 *
 * WHAT IT REPLACES. Eight row menus on the Sales and Purchases screens were each built by hand as two siblings: an invisible layer over
 * the whole window (`fixed inset-0`) whose only job was to catch the click that closes the menu, and the menu itself. The layer made the
 * menu a mouse-only thing: opened from the keyboard, focus stayed on the row's button behind it, Escape did nothing, and the first click
 * anywhere (another row's own button included) was swallowed by the layer, so reaching the next row's actions took two clicks.
 *
 * WHAT IT IS. A labelled GROUP of the buttons it is given, drawn where `lib/ui/rowMenuPosition` says (under the row's button, or above it
 * near the foot of the window), with no layer behind it:
 *   • focus moves to its first action when it opens, and back to the button that opened it when it closes with focus still inside
 *     (Escape, or an action that opens a dialog: the dialog then gives focus back to that button when it closes, not to nothing);
 *   • Escape closes it; ArrowDown, ArrowUp, Home and End move between its actions; Tab leaves it and closes it;
 *   • a click anywhere outside closes it and is NOT swallowed, so another row's button opens that row's menu at once; a click on the
 *     button that opened it only closes it.
 *
 * WHY A GROUP AND NOT role="menu". A menu must own `menuitem`s, and its actions here are ordinary buttons, several of them the shared
 * guarded Button that a write goes through. A group of buttons opened from a button that says it is expanded is the disclosure pattern,
 * and it leaves every action the button it already was.
 */
import { useEffect, useLayoutEffect, useRef, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from "react";
import type { RowMenuPlace } from "@/lib/ui/rowMenuPosition";
import { nextActionIndex } from "@/lib/ui/rowMenuKeys";

/** What focus can move to inside the menu. */
const ACTIONS = "button:not([disabled]), a[href]";

export function RowMenu({
  place,
  onClose,
  children,
  widthClass = "w-44",
  label = "Row actions",
}: {
  /** Where to draw it: the answer of `rowMenuAt` for the row's button. */
  place: RowMenuPlace;
  onClose: () => void;
  children: ReactNode;
  widthClass?: string;
  /** The group's accessible name. It must not repeat the opening button's own label, or the two are one name for two things. */
  label?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const openerRef = useRef<HTMLElement | null>(null);
  // Callers pass an inline arrow: read the latest at the moment it is needed, so the effects below run once per opening.
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  // Focus in on opening; and on closing, back to the opener WHILE the menu is still in the document (a layout effect's cleanup runs
  // before the node is removed), so "is focus still inside?" can be asked. Focus that has already gone elsewhere is left where it is.
  useLayoutEffect(() => {
    const menu = ref.current;
    openerRef.current = (document.activeElement as HTMLElement | null) ?? null;
    (menu?.querySelector<HTMLElement>(ACTIONS) ?? menu)?.focus();
    return () => {
      if (menu && menu.contains(document.activeElement)) openerRef.current?.focus?.();
    };
  }, []);

  // A click outside closes it. Capture phase, so it is seen before the thing clicked acts; it is not stopped, so that thing still acts,
  // EXCEPT the button that opened this menu, whose own handler would open it again in the same click.
  useEffect(() => {
    function onClick(e: MouseEvent) {
      const target = e.target as Node | null;
      if (!target || ref.current?.contains(target)) return;
      if (openerRef.current?.contains(target)) e.stopPropagation();
      onCloseRef.current();
    }
    document.addEventListener("click", onClick, true);
    return () => document.removeEventListener("click", onClick, true);
  }, []);

  function onKeyDown(e: ReactKeyboardEvent<HTMLDivElement>) {
    if (e.key === "Escape") {
      // This menu's Escape and nobody else's: a panel or dialog behind it does not hear the same press.
      e.stopPropagation();
      onCloseRef.current();
      return;
    }
    if (e.key === "Tab") {
      // Leaving by Tab closes it; focus goes back to the opener first (the cleanup above), and Tab then moves on from there.
      onCloseRef.current();
      return;
    }
    const actions = Array.from(ref.current?.querySelectorAll<HTMLElement>(ACTIONS) ?? []);
    const next = nextActionIndex(e.key, actions.indexOf(document.activeElement as HTMLElement), actions.length);
    if (next === null) return;
    e.preventDefault();
    actions[next]?.focus();
  }

  return (
    <div
      ref={ref}
      role="group"
      aria-label={label}
      tabIndex={-1}
      data-row-menu
      onKeyDown={onKeyDown}
      className={`fixed z-50 ${widthClass} bg-white rounded-lg border border-ps-border shadow-lg py-1 text-xs outline-none focus:ring-2 focus:ring-brand`}
      style={{ top: place.top, bottom: place.bottom, left: place.left }}
    >
      {children}
    </div>
  );
}
