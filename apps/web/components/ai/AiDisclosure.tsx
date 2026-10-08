import { cn } from "@/lib/utils";
import { AI_DISCLOSURES, type AiDisclosureSurface } from "@/lib/ai/disclosure";

/**
 * The plain sentence a screen shows before it sends content to an AI provider
 * (PRE-A-006): who receives it, what goes, and that it leaves India.
 *
 * The words live in `lib/ai/disclosure.ts` and are held to the backend from the
 * Python side; this renders them and decides nothing. It renders a `span` that is
 * `display: block` and not a `p`, because one of its homes is inside the `label` of
 * the statement-scan checkbox, where flow content is not allowed, and the sentence
 * belongs to that checkbox's accessible description (it is read before ticking).
 *
 * The default colour is a text token that passes contrast on white; a caller on a
 * tinted surface passes the sibling note's own colour, as the Extract box does.
 */
export function AiDisclosure({
  surface,
  className,
  id,
}: {
  surface: AiDisclosureSurface;
  className?: string;
  /** Lets the control the notice is about point at it with `aria-describedby`, so a
   *  screen reader reads who receives the file when the control takes focus. */
  id?: string;
}) {
  return (
    <span
      id={id}
      data-ai-surface={surface}
      className={cn("block text-3xs leading-snug text-ps-label", className)}
    >
      {AI_DISCLOSURES[surface].sentence}
    </span>
  );
}
