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
// Position, per corner, exactly as specified per-section in the design
// reference (each section's ghost numeral bleeds off a slightly different
// offset — these are not one shared constant).
const NUMERAL_POSITION: Record<"top-right" | "bottom-left" | "top-left", CSSProperties> = {
  "top-right": { top: "-60px", right: "-40px" }, // "The Platform" ghost "03"
  "bottom-left": { bottom: "-40px", left: "-30px" }, // "The Problem" ghost "02"
  "top-left": { top: "-60px", left: "0px" }, // Testimonial's quote mark
};

export function DiagonalSection({
  id,
  numeral,
  numeralCorner = "top-right",
  numeralItalic = false,
  numeralStyle,
  numeralFontSize = "clamp(200px,28vw,400px)",
  numeralOpacity = 0.05,
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
  /** Per-instance position override — e.g. Control & Trust's ghost "04" sits
   * at bottom:-50px, not Problem's -40px, despite sharing the bottom-left
   * corner. Merged over NUMERAL_POSITION's per-corner default. */
  numeralStyle?: CSSProperties;
  /** Testimonial's quote mark uses a different clamp than the page numerals. */
  numeralFontSize?: string;
  numeralOpacity?: number;
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

  return (
    <section id={id} className={`relative -mt-16 overflow-hidden ${className}`} style={{ clipPath, ...style }}>
      {numeral ? (
        <div
          aria-hidden="true"
          className={`pointer-events-none absolute z-0 select-none font-display leading-none ${numeralItalic ? "italic" : ""}`}
          style={{
            fontSize: numeralFontSize,
            opacity: numeralOpacity,
            ...NUMERAL_POSITION[numeralCorner],
            ...numeralStyle,
          }}
        >
          {numeral}
        </div>
      ) : null}
      <div className="relative z-10">{children}</div>
    </section>
  );
}
