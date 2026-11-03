/**
 * Which open dialog is the TOP one (POST-A-128).
 *
 * Every shared dialog listens for Escape on the document, so two open at once (a dialog opened from inside another, a confirmation shown over
 * a dialog, a Modal over a Drawer) would both hear one press, and the lower one would close with the top one or, worse, in its place: the
 * Modal listens in the capture phase and stops the event, so a ConfirmDialog opened above it never heard Escape at all and the Modal beneath
 * it closed instead. The rule is one line, "only the top one acts", and this is where it is kept.
 *
 * `openOverlay()` is called when a dialog opens and returns a handle; `isTop()` says whether this dialog is the newest one still open, and
 * `close()` takes it off (calling it twice is the same as once). Registration order is the stacking order, which is right for a dialog that
 * is opened by a person's action after the one beneath it. It is NOT right for two that mount in the same render, where React runs the inner
 * one's effect first; no dialog in the product does that, and the Modal's own drive opens them one after the other.
 */
export interface OverlayHandle {
  /** True while this is the newest dialog still open. */
  isTop(): boolean;
  /** Take it off the stack. Safe to call twice. */
  close(): void;
}

const open: symbol[] = [];

export function openOverlay(): OverlayHandle {
  const token = Symbol("overlay");
  open.push(token);
  return {
    isTop: () => open[open.length - 1] === token,
    close: () => {
      const at = open.indexOf(token);
      if (at !== -1) open.splice(at, 1);
    },
  };
}

/** How many dialogs are open: for the tests, and for a screen that wants to know whether anything is. */
export function openOverlayCount(): number {
  return open.length;
}

/** What this needs of an event target: the one DOM call, so a test can hand it a stand-in. */
export interface PickerProbe {
  closest(selector: string): unknown;
}

/** An open ledger/party picker's search box: the one element whose Escape means "close the list", not "close the dialog". */
export const OPEN_PICKER_SELECTOR = '[role="combobox"][aria-expanded="true"]';

/**
 * True when an Escape was pressed inside an OPEN picker. The Modal listens in the capture phase and stops the event, so without this the
 * picker's own Escape never ran: a person who opened a ledger picker inside the split dialog and pressed Escape to dismiss the list lost the
 * whole dialog and every line typed in it. A dialog leaves such an Escape alone, and the picker (which runs next) closes its list.
 */
export function escapeBelongsToAnOpenPicker(target: PickerProbe | null | undefined): boolean {
  return !!target && typeof target.closest === "function" && target.closest(OPEN_PICKER_SELECTOR) !== null;
}

