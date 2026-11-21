/**
 * WHETHER THIS BROWSER'S LAST SIGNED-IN PERSON MAY OPEN MY PRACTICE, REMEMBERED FOR ONE MOMENT OF ONE PAGE LOAD.
 *
 * A People screen (`practiceWorkspace.isPeoplePath`) is drawn in the My practice frame for somebody who may open My practice
 * and in the firm's frame for everybody else. Who is looking is known a round trip after the page starts (the role is read
 * from the server once the session is known), and the two frames are two components: choosing the firm's and then changing to
 * the other redraws the bar in another colour and starts the screen under it again, on every reload of the Team screen by a
 * Partner. So the last answer is kept here and used ONLY until the real one arrives; then the role decides, and the answer
 * here is replaced.
 *
 * It is a convenience and never a permission. A wrong answer draws the other frame for that moment and discloses nothing: the
 * My practice bar holds the words "My practice" and a lookup the server refuses to anybody but a Partner. Storage that is
 * blocked or empty answers "no", which is the firm's frame, the one everybody may see.
 */
const KEY = "practicesync_may_open_practice";

export function rememberedPracticeAccess(): boolean {
  try {
    return typeof window !== "undefined" && window.localStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
}

export function rememberPracticeAccess(may: boolean): void {
  try {
    if (typeof window !== "undefined") window.localStorage.setItem(KEY, may ? "1" : "0");
  } catch {
    // A browser that refuses storage keeps no answer, and the next load starts in the firm's frame.
  }
}
