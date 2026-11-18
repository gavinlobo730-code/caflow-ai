// What the sign-up wizard's first step's button does, decided from what is on the screen (POST-A-478).
//
// Once the password is set the step asks for nothing more: the button says "Continue" and needs no password. Typing a
// new password in either box makes it a change again ("Set Password & Continue") and then both boxes are needed.
//
// Dependency-free so it strips to plain JS for `node --experimental-strip-types`.

export type PasswordStepMode = "continue" | "save";

export function passwordStepMode(args: { passwordSet: boolean; pw: string; pw2: string }): PasswordStepMode {
  return args.passwordSet && args.pw === "" && args.pw2 === "" ? "continue" : "save";
}

/** Whether the step's button may be pressed. */
export function passwordStepButtonEnabled(args: {
  passwordSet: boolean; pw: string; pw2: string; saving: boolean; needsReauth: boolean;
}): boolean {
  if (args.saving || args.needsReauth) return false;
  return passwordStepMode(args) === "continue" || (args.pw !== "" && args.pw2 !== "");
}
