"use client";

import type { ReactNode } from "react";
import { LogoIcon } from "@/components/LogoIcon";

/**
 * The page a person sees before they are inside the product (POST-A-446).
 *
 * The invitation page's blue-to-indigo wash, which the owner asked on 15-11-2026 to keep and use on the other
 * front-door pages, is ONE named style, `bg-front-door` in `tailwind.config.ts`, and this is the one layout that
 * wears it: the wash, the product's mark and name in white above, and the page's own content in a white card. The
 * sign-in page draws its own two columns on the same style, because its left half carries words of its own.
 *
 * WHERE A WORD MAY SIT. White reads at better than 5:1 over the top half and the left half of the wash and falls to
 * 2.5:1 at the bottom-right corner (the config says why), so the only words on the wash are the white wordmark,
 * which always sits above the card and therefore in the top half; everything else is inside a white surface.
 * `card={false}` is for a page that draws its own white surfaces (the engagement letter, whose sections are
 * already cards), and it must put nothing on the wash but white surfaces below its own heading.
 *
 * WHOSE NAME IS ABOVE THE CARD. The staff pages say "PracticeSync AI", as they did; the client and employee portals'
 * pages say "PracticeSync" (the client portal's already did, and the employee's first visit, which had no name, takes
 * the portal's). The engagement letter says NO product name (`mark={false}`): it is the firm's letter to its client, and
 * a platform's name above "from {firm}" could be read as the sender (the rule a mail to a client follows, that it names
 * whoever actually sends it).
 *
 * NEVER BEHIND A WORKING SCREEN. A register, a return or a dashboard is read for its figures, and a coloured wash
 * behind them competes; `scripts/a-front-door-page-wears-the-front-door.test.ts` holds the list of the pages that
 * wear it and refuses the style anywhere else.
 */
const WIDTH = {
  /** A sign-in, a password page, an invitation: one short form. */
  form: "max-w-[420px]",
  /** A message with a little more to say: an activation that lists what it found, an error. */
  wide: "max-w-md",
  /** A document to read before acting on it: the engagement letter. */
  letter: "max-w-2xl",
} as const;

/** The product's name above the card: "PracticeSync AI" on the staff pages, "PracticeSync" on the portals' (above). */
export type FrontDoorName = "PracticeSync AI" | "PracticeSync";

export function FrontDoorWordmark({ name = "PracticeSync AI", className = "" }: { name?: FrontDoorName; className?: string }) {
  return (
    <div className={`flex flex-col items-center gap-3 ${className}`}>
      <LogoIcon size="lg" />
      <span className="text-xl font-bold tracking-tight text-white">{name}</span>
    </div>
  );
}

export function FrontDoor({
  children,
  name,
  width = "form",
  card = true,
  mark = true,
}: {
  children: ReactNode;
  name?: FrontDoorName;
  width?: keyof typeof WIDTH;
  card?: boolean;
  /** False for a page that is somebody else's document (the engagement letter): the wash and no product name. */
  mark?: boolean;
}) {
  return (
    <div data-front-door="" className="min-h-screen bg-front-door flex items-center justify-center px-4 py-10 sm:px-6">
      <div className={`w-full ${WIDTH[width]}`}>
        {mark && <FrontDoorWordmark name={name} className="mb-6" />}
        {card ? (
          <div className="rounded-2xl bg-white p-8 shadow-2xl">{children}</div>
        ) : (
          children
        )}
      </div>
    </div>
  );
}
