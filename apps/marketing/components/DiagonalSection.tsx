import type { CSSProperties, ReactNode } from "react";

/**
 * Diagonal section-seam wrapper matching the reference design: each section
 * overlaps the previous by 64px and is clipped with a polygon so a
 * dark<->light transition reads as a hard angled cut instead of a straight
 * line or a fade. Callers own their own top padding (which varies per
 * section) and must add 64px on top of it themselves to keep real content
 * clear of the clipped sliver — this component only owns the seam/clip and
 * the decorative page-number watermark.
 */
export function DiagonalSection({
  id,
  numeral,
  numeralCorner = "top-right",
  numeralItalic = false,
  seam,
  className = "",
  style,
  children,
}: {
  id?: string;
  /** Decorative page-number/quote watermark. Omit for sections the reference
   * leaves un-numbered (stats, final CTA). */
  numeral?: string;
  numeralCorner?: "top-right" | "bottom-left" | "top-left";
  numeralItalic?: boolean;
  /** Which way the section's top edge rises. */
  seam: "rising-left" | "rising-right";
  className?: string;
  style?: CSSProperties;
  children: ReactNode;
}) {
  const clipPath =
    seam === "rising-right"
      ? "polygon(0 64px, 100% 0, 100% 100%, 0 100%)"
      : "polygon(0 0, 100% 64px, 100% 100%, 0 100%)";

  const numeralStyle: CSSProperties =
    numeralCorner === "top-right"
      ? { top: "-60px", right: "-20px" }
      : numeralCorner === "top-left"
        ? { top: "-60px", left: "0px" }
        : { bottom: "-40px", left: "-30px" };

  return (
    <section id={id} className={`relative -mt-16 overflow-hidden ${className}`} style={{ clipPath, ...style }}>
      {numeral ? (
        <div
          aria-hidden="true"
          className={`pointer-events-none absolute z-0 select-none font-display text-[clamp(200px,28vw,400px)] leading-none opacity-[0.05] ${numeralItalic ? "italic" : ""}`}
          style={numeralStyle}
        >
          {numeral}
        </div>
      ) : null}
      <div className="relative z-10">{children}</div>
    </section>
  );
}
