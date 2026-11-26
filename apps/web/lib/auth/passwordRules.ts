// What a new password has to contain, in the words the screen shows, so a
// person is told the rules BEFORE they type and is never refused for one they
// were not shown (POST-A-477).
//
// The project's sign-in service refuses a password unless it holds at least one
// lowercase letter, one capital letter, one digit and one symbol. Read from the
// live sign-in log on 18-11-2026: a password update answered 422 with "Password
// should contain at least one character of each: abcdefghijklmnopqrstuvwxyz,
// ABCDEFGHIJKLMNOPQRSTUVWXYZ, 0123456789, !@#$%^&*()_+-=[]{};'\:"|<>?,./`~."
// and NO error code, while every password screen said only "At least 10
// characters" and checked only the length. PASSWORD_SYMBOLS is that message's
// own symbol list. The setting itself is the owner's to read (POST-C-215): if
// it changes, `authErrorMessage` still words the server's refusal from the
// groups the server names, so a screen that is a step behind is not silent.
//
// Dependency-free so it strips to plain JS for `node --experimental-strip-types`.

/** The shortest password the screens accept. */
export const PASSWORD_MIN_LENGTH = 10;

/** The symbols the sign-in service counts, exactly as its refusal lists them. */
export const PASSWORD_SYMBOLS = "!@#$%^&*()_+-=[]{};'\\:\"|<>?,./`~";

export type PasswordRuleId = "length" | "lower" | "upper" | "digit" | "symbol";

export interface PasswordRule {
  id: PasswordRuleId;
  /** The line the screen shows beside its tick. */
  label: string;
  /** The same rule inside a sentence: "your password still needs ...". */
  need: string;
  met: boolean;
}

/** Each rule, in the order the screen lists them, with whether `pw` meets it. */
export function passwordRules(pw: string): PasswordRule[] {
  return [
    {
      id: "length",
      label: `At least ${PASSWORD_MIN_LENGTH} characters`,
      need: `at least ${PASSWORD_MIN_LENGTH} characters`,
      met: pw.length >= PASSWORD_MIN_LENGTH,
    },
    { id: "lower", label: "A lowercase letter (a to z)", need: "a lowercase letter", met: /[a-z]/.test(pw) },
    { id: "upper", label: "A capital letter (A to Z)", need: "a capital letter", met: /[A-Z]/.test(pw) },
    { id: "digit", label: "A digit (0 to 9)", need: "a digit", met: /[0-9]/.test(pw) },
    {
      id: "symbol",
      label: "A symbol, for example ! @ # $ %",
      need: "a symbol (for example ! @ # $ %)",
      met: Array.from(pw).some((c) => PASSWORD_SYMBOLS.includes(c)),
    },
  ];
}

/** "a", "a and b", "a, b and c". */
export function joinWithAnd(parts: readonly string[]): string {
  if (parts.length <= 1) return parts.join("");
  return `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;
}

/** The sentence naming what `pw` still lacks, or null when it meets every rule. */
export function passwordProblem(pw: string): string | null {
  const missing = passwordRules(pw).filter((r) => !r.met);
  if (missing.length === 0) return null;
  return `Your password still needs ${joinWithAnd(missing.map((r) => r.need))}.`;
}
