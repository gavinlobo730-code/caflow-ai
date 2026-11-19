"use client";

import { useState } from "react";
import { Eye, EyeOff } from "lucide-react";

/**
 * A password box that can show what was typed, drawn the same way on every screen that asks for a password (POST-A-513).
 *
 * WHY ONE COMPONENT. The sign-in screen had no way to show the password being typed while every other password screen had one,
 * and Settings → Security drove three boxes from ONE setting that was drawn beside only the new-password box, so the owner's
 * screenshot showed the current password in clear text with no eye beside it. Each box now owns its own "shown" setting, so an
 * eye hides and shows its own box and no other, and the eye is a real button with a name and a pressed state.
 *
 * WHAT IT KEEPS. The input is a plain controlled input with the `id`, `name` and `autoComplete` the screen gives it, so the
 * browser's saved-password fill still finds the sign-in box (the type flips between "password" and "text" only when the person
 * asks, and an input that is not shown is exactly the input the screens had before).
 */
export function PasswordField({
  value,
  onChange,
  label,
  autoComplete,
  inputClassName,
  id,
  name,
  required,
  placeholder,
  autoFocus,
  disabled,
  ariaLabel,
  ariaDescribedBy,
  ariaInvalid,
  spellCheck,
  onKeyDown,
  eyeSize = 16,
}: {
  value: string;
  onChange: (next: string) => void;
  /** The box's own name for a person who cannot see it: "password", "current password", "new password". The eye is named from it. */
  label: string;
  autoComplete: "current-password" | "new-password";
  /** The classes the screen already gave its input; the right padding that makes room for the eye is added here. */
  inputClassName: string;
  id?: string;
  name?: string;
  required?: boolean;
  placeholder?: string;
  autoFocus?: boolean;
  disabled?: boolean;
  /** Set where the box has no visible `<label>` pointing at it. */
  ariaLabel?: string;
  ariaDescribedBy?: string;
  ariaInvalid?: boolean;
  spellCheck?: boolean;
  onKeyDown?: (e: React.KeyboardEvent<HTMLInputElement>) => unknown;
  eyeSize?: number;
}) {
  const [shown, setShown] = useState(false);
  return (
    <div className="relative">
      <input
        id={id}
        name={name}
        type={shown ? "text" : "password"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        autoComplete={autoComplete}
        required={required}
        placeholder={placeholder}
        autoFocus={autoFocus}
        disabled={disabled}
        aria-label={ariaLabel}
        aria-describedby={ariaDescribedBy}
        aria-invalid={ariaInvalid}
        spellCheck={spellCheck}
        onKeyDown={onKeyDown}
        className={`${inputClassName} pr-10`}
      />
      <button
        type="button"
        onClick={() => setShown((s) => !s)}
        aria-label={shown ? `Hide ${label}` : `Show ${label}`}
        aria-pressed={shown}
        className="absolute right-3 top-1/2 -translate-y-1/2 text-ps-hint hover:text-ps-label"
      >
        {shown ? <EyeOff size={eyeSize} aria-hidden="true" /> : <Eye size={eyeSize} aria-hidden="true" />}
      </button>
    </div>
  );
}
