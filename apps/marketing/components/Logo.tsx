import Link from "next/link";

// PracticeSync logo mark — the circular ring + accent arc + checkmark used on
// the homepage (the canonical brand mark). `theme` picks stroke contrast for
// the surface it sits on:
//   light → dark mark + wordmark on a light background (header)
//   dark  → light mark + wordmark on a dark background (footer, hero)
// The accent arc stays the same blue on both, matching the homepage exactly.
// The ring and the tick are drawn in `currentColor` rather than a literal per
// theme, so the mark CROSS-FADES with the wordmark when the header goes from
// transparent-over-navy to frosted-over-light on scroll. Two hard-coded hexes
// swapped by a prop would snap between them on the same frame the background is
// easing, which is the one moment anybody is looking at the bar. The accent arc
// stays the same blue on both, matching the reference exactly.
function LogoMark() {
  return (
    <svg width="26" height="26" viewBox="0 0 64 64" fill="none" aria-hidden="true" className="shrink-0">
      <circle cx="32" cy="32" r="24" stroke="currentColor" strokeOpacity="0.2" strokeWidth="3" />
      <circle
        cx="32"
        cy="32"
        r="24"
        stroke="#4f71cc"
        strokeWidth="5"
        strokeLinecap="round"
        strokeDasharray="29.3 121.5"
        className="logo-arc"
      />
      <path
        d="M20,33 L28,41 L45,22"
        stroke="currentColor"
        strokeWidth="6.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function Logo({
  theme = "light",
  href = "/" as string | null,
}: {
  theme?: "light" | "dark";
  href?: string | null;
}) {
  const tone = theme === "light" ? "text-brand-dark" : "text-white";

  const inner = (
    <span className={`inline-flex items-center gap-2.5 transition-colors duration-300 ${tone}`}>
      <LogoMark />
      {/* leading-none matches the reference's `font:700 17px/1` exactly. Tailwind's
          `text-[17px]` sets font-size only and leaves line-height at `normal`
          (~1.5); because the bar centres the LINE BOX, the taller box landed the
          glyphs ~1px off on the same 68px bar. */}
      <span className="text-[17px] font-bold leading-none tracking-tight">PracticeSync</span>
    </span>
  );

  if (href === null) return inner;
  return (
    <Link href={href} className="inline-flex" aria-label="PracticeSync home">
      {inner}
    </Link>
  );
}
