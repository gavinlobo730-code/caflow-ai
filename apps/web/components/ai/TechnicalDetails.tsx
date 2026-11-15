import type { ReactNode } from "react";

/**
 * The exact model codes behind PracticeSync AI, folded away until someone asks (POST-A-448).
 *
 * The owner, opening the AI status page on 16-11-2026, asked why it led with `openai/gpt-oss-120b` and
 * `gemini-3.5-flash` instead of presenting the AI as the product's own. A model code helps only the person
 * working out why a provider stopped answering, and `openai/...` reads as though content goes to OpenAI when
 * Groq serves that model, which is a wrong impression on a screen about where data goes. So a code is shown
 * here and only here, closed by default. The PROVIDER is not hidden: the company that receives a CA's content
 * stays named on the card, in every send-time notice (`lib/ai/disclosure.ts`) and on the usage table.
 *
 * A native `details` element, so it opens from the keyboard and a screen reader announces it as collapsed.
 */
export function TechnicalDetails({ children, label = "Technical details" }: { children: ReactNode; label?: string }) {
  return (
    <details data-technical-details="" className="group py-2">
      <summary className="cursor-pointer select-none text-xs font-medium text-ps-label hover:text-ps-ink">
        {label}
      </summary>
      <div className="mt-2">{children}</div>
    </details>
  );
}
