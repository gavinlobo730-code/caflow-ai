"use client";

/**
 * MenuScrim — the dimmed page under an open shell menu (POST-A-130, last step).
 *
 * The workspace menu and a client's module menu drop from the top bar over the page, and the page under them is dimmed and blurred so
 * the menu reads as the thing in front. Each drew that layer by hand. This is the one definition: it starts under the 3rem top bar
 * (which stays live, so the button that opened the menu closes it), it is decoration to a screen reader (`aria-hidden`), and a click on
 * it closes the menu and goes no further, which is what a person expects of a dimmed page.
 *
 * IT IS NOT A DIALOG'S BACKDROP. These menus are disclosures (a region of links opened from a button that says it is expanded), not
 * dialogs: Tab is not kept inside and the page behind is not locked. A full-screen dialog is `Modal` or `Drawer`. Escape and focus are
 * `lib/ui/useMenuDismiss`.
 */
export function MenuScrim({ onClose }: { onClose: () => void }) {
  return (
    <div
      aria-hidden="true"
      data-menu-scrim
      className="fixed inset-0 top-12 z-30 bg-brand/20 backdrop-blur-[2px]"
      onClick={onClose}
    />
  );
}
