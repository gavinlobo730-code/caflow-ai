"use client";

/**
 * useMenuDismiss — how a menu opened from a button closes (POST-A-130, last step).
 *
 * WHAT IT REPLACES. The shell's three menus (the account menu, the workspace menu and a client's module menu) each closed on a click on a
 * layer drawn over the whole window, and two of them on an Escape listener of their own that left focus on nothing: the link that held
 * focus went with the menu. The account menu had no Escape at all, and its layer was invisible, so the first click anywhere after
 * opening it was swallowed.
 *
 * WHAT IT DOES, while `open`:
 *   • Escape closes the menu and puts focus back on the button that opened it, and is this menu's alone (a dialog behind does not hear
 *     the same press);
 *   • with `outsideClick`, a click outside the menu and its button closes it and is NOT swallowed, so the thing clicked still acts. A
 *     click on the button itself is left to the button, which toggles. A menu that dims the page behind it leaves this off and closes on
 *     its scrim (`components/ui/menu-scrim`), where swallowing the click is what a person expects of a dimmed page;
 *   • with `focusMenu`, focus moves to the menu's first link or button when it opens. The two menus that drop from the top bar come
 *     after the whole bar in the document, so without this the next Tab from the button went to the bar's other buttons and the menu
 *     was four or five presses away (found in a browser, 23-11-2026).
 *
 * The latest `close` is read when it is needed, so a caller may pass an inline arrow without re-registering the listeners.
 */
import { useEffect, useRef, type RefObject } from "react";

export function useMenuDismiss(
  open: boolean,
  close: () => void,
  refs: { opener: RefObject<HTMLElement | null>; menu?: RefObject<HTMLElement | null> },
  { outsideClick = false, focusMenu = false }: { outsideClick?: boolean; focusMenu?: boolean } = {},
): void {
  const closeRef = useRef(close);
  closeRef.current = close;
  const { opener, menu } = refs;

  useEffect(() => {
    if (!open) return;
    if (focusMenu) menu?.current?.querySelector<HTMLElement>("a[href], button:not([disabled])")?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key !== "Escape" || e.defaultPrevented) return;
      e.stopPropagation();
      closeRef.current();
      opener.current?.focus();
    }
    function onClick(e: MouseEvent) {
      const target = e.target as Node | null;
      if (!target || menu?.current?.contains(target) || opener.current?.contains(target)) return;
      closeRef.current();
    }
    document.addEventListener("keydown", onKey, true);
    if (outsideClick) document.addEventListener("click", onClick, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      if (outsideClick) document.removeEventListener("click", onClick, true);
    };
  }, [open, opener, menu, outsideClick, focusMenu]);
}
