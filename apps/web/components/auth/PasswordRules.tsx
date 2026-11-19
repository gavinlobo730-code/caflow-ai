"use client";

import { CheckCircle, Circle } from "lucide-react";
import { passwordRules } from "@/lib/auth/passwordRules";

/** What a new password must contain, ticked off as the person types (POST-A-477).
 *  The rules are lib/auth/passwordRules, the same ones the screen checks before it
 *  sends anything, so a person is never refused for a rule they were not shown.
 *  `id` is what the password box points `aria-describedby` at. */
export function PasswordRules({ password, id }: { password: string; id: string }) {
  const rules = passwordRules(password);
  return (
    <div id={id} className="rounded-lg border border-ps-border bg-ps-bg px-3 py-2">
      <p className="text-xs font-medium text-ps-label mb-1">Your password needs:</p>
      <ul className="space-y-0.5">
        {rules.map((r) => (
          <li
            key={r.id}
            data-rule={r.id}
            data-met={r.met ? "true" : "false"}
            className={`flex items-center gap-1.5 text-xs ${r.met ? "text-state-ready" : "text-ps-label"}`}
          >
            {r.met ? <CheckCircle size={13} aria-hidden="true" /> : <Circle size={13} aria-hidden="true" />}
            <span>{r.label}</span>
            <span className="sr-only">{r.met ? " (done)" : " (not yet)"}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
