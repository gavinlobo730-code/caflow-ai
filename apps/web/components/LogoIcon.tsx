"use client";

const SIZES: Record<string, { cls: string; rx: number }> = {
  sm: { cls: "w-7 h-7",   rx: 10 },
  md: { cls: "w-9 h-9",   rx: 12 },
  lg: { cls: "w-11 h-11", rx: 14 },
  xl: { cls: "w-14 h-14", rx: 18 },
};

// `spin` turns the mark into a loading indicator — the accent arc rotates
// continuously (see .logo-arc-spin in globals.css). Used by PageLoader, the
// CSV import modal and the auth gate so loading states show the brand mark
// instead of a generic spinner. Respects prefers-reduced-motion (holds still).
export function LogoIcon({ size = "md", spin = false }: { size?: "sm" | "md" | "lg" | "xl"; spin?: boolean }) {
  const { cls, rx } = SIZES[size];

  // The canonical PracticeSync mark — circular ring + accent arc + checkmark,
  // identical to the marketing site / homepage logo. Dark strokes since it sits
  // in the white badge tile. Kept in the existing tile so the app chrome layout
  // is unchanged; only the glyph is unified.
  return (
    <div className={`${cls} shrink-0 grid place-items-center bg-white`} style={{ borderRadius: rx }}>
      <svg
        viewBox="0 0 64 64"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className="w-3/4 h-3/4"
        aria-label="PracticeSync"
      >
        <circle cx="32" cy="32" r="24" stroke="rgba(27,30,51,0.16)" strokeWidth="3" />
        <circle
          cx="32"
          cy="32"
          r="24"
          stroke="#4f71cc"
          strokeWidth="5"
          strokeLinecap="round"
          strokeDasharray="29.3 121.5"
          className={spin ? "logo-arc-spin" : undefined}
          transform={spin ? undefined : "rotate(-50 32 32)"}
        />
        <path d="M20,33 L28,41 L45,22" stroke="#1b1e33" strokeWidth="6.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </div>
  );
}

export function LogoWordmark({ size = "md" }: { size?: "sm" | "md" }) {
  return (
    <div className="flex items-center gap-2.5">
      <LogoIcon size={size} />
      <span className={`font-bold tracking-tight text-white ${size === "sm" ? "text-[13px]" : "text-base"}`}>
        PracticeSync
      </span>
    </div>
  );
}
