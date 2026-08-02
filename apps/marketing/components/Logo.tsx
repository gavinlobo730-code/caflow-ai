import Link from "next/link";

// PracticeSync logo mark — the circular ring + accent arc + checkmark used on
// the homepage (the canonical brand mark). `theme` picks stroke contrast for
// the surface it sits on:
//   light → dark mark + wordmark on a light background (header)
//   dark  → light mark + wordmark on a dark background (footer, hero)
// The accent arc stays the same blue on both, matching the homepage exactly.
function LogoMark({ theme }: { theme: "light" | "dark" }) {
  const ring = theme === "light" ? "rgba(27,30,51,0.16)" : "rgba(242,242,246,0.25)";
  const check = theme === "light" ? "#1b1e33" : "#f2f2f6";
  return (
    <svg width="26" height="26" viewBox="0 0 64 64" fill="none" aria-hidden="true" className="shrink-0">
      <circle cx="32" cy="32" r="24" stroke={ring} strokeWidth="3" />
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
      <path d="M20,33 L28,41 L45,22" stroke={check} strokeWidth="6.5" strokeLinecap="round" strokeLinejoin="round" />
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
  const word = theme === "light" ? "text-brand-dark" : "text-white";

  const inner = (
    <span className="inline-flex items-center gap-2.5">
      <LogoMark theme={theme} />
      {/* leading-none matches the homepage's `font:700 17px/1` exactly. Tailwind's
          `text-[17px]` sets font-size only and leaves line-height at `normal`
          (~1.5); because the bar centres the LINE BOX, the taller box landed the
          glyphs ~1px off the homepage's on the same 68px bar. */}
      <span className={`text-[17px] font-bold leading-none tracking-tight ${word}`}>
        PracticeSync
      </span>
    </span>
  );

  if (href === null) return inner;
  return (
    <Link href={href} className="inline-flex" aria-label="PracticeSync home">
      {inner}
    </Link>
  );
}
