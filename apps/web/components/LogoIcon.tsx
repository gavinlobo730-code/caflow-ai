"use client";

const SIZES: Record<string, { cls: string; rx: number }> = {
  sm: { cls: "w-7 h-7",   rx: 10 },
  md: { cls: "w-9 h-9",   rx: 12 },
  lg: { cls: "w-11 h-11", rx: 14 },
  xl: { cls: "w-14 h-14", rx: 18 },
};

export function LogoIcon({ size = "md" }: { size?: "sm" | "md" | "lg" | "xl" }) {
  const { cls, rx } = SIZES[size];

  return (
    <div className={`${cls} shrink-0 overflow-hidden bg-[#0F172A]`} style={{ borderRadius: rx }}>
      <svg
        viewBox="0 0 200 200"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className="w-full h-full"
        aria-label="PracticeSync"
      >
        <rect x="66" y="81" width="92" height="62" rx="10" fill="#1E3A5F" />
        <rect x="54" y="69" width="92" height="62" rx="10" fill="#2563EB" />
        <rect x="42" y="57" width="92" height="62" rx="10" fill="#38BDF8" />
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
