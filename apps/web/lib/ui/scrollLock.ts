/**
 * Stop the page behind an open dialog from scrolling (POST-A-130).
 *
 * Reference-counted, because a dialog can open over another one (a Modal over a Drawer): the page must stay locked until the LAST one
 * closes, and must go back to whatever `overflow` it had before the first one opened, not to a guess.
 */
let holders = 0;
let before = "";

/** Lock the page's scroll and return the function that gives it back. Calling that function twice releases once. */
export function lockBodyScroll(): () => void {
  if (typeof document === "undefined" || !document.body) return () => {};
  if (holders === 0) {
    before = document.body.style.overflow;
    document.body.style.overflow = "hidden";
  }
  holders += 1;
  let released = false;
  return () => {
    if (released) return;
    released = true;
    holders -= 1;
    if (holders === 0) document.body.style.overflow = before;
  };
}
