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
    <div className={`${cls} shrink-0 overflow-hidden`} style={{ borderRadius: rx }}>
      <svg
        viewBox="0 0 200 200"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className="w-full h-full"
        aria-label="PracticeSync AI"
      >
        <defs>
          <linearGradient id="ps-bg" x1="0" y1="0" x2="200" y2="200" gradientUnits="userSpaceOnUse">
            <stop offset="0%"   stopColor="#0B1635" />
            <stop offset="100%" stopColor="#142256" />
          </linearGradient>
          <linearGradient id="ps-sg" x1="90" y1="44" x2="168" y2="160" gradientUnits="userSpaceOnUse">
            <stop offset="0%"   stopColor="#3B82F6" />
            <stop offset="100%" stopColor="#22D3EE" />
          </linearGradient>
        </defs>

        <rect width="200" height="200" fill="url(#ps-bg)" />
        <rect x="2" y="2" width="196" height="196" rx="36"
              stroke="white" strokeOpacity={0.07} strokeWidth={1.5} />

        {/* S lower arc — behind P spine */}
        <path
          d="M 130,110 Q 46,110 46,142 Q 46,156 74,156"
          stroke="url(#ps-sg)" strokeWidth={16}
          strokeLinecap="round" strokeLinejoin="round"
        />

        {/* P spine — covers the S lower arc at the crossing */}
        <rect x="38" y="44" width="16" height="112" rx="8" fill="white" />

        {/* P bowl — D-shape opening right */}
        <path
          d="M 46,44 Q 116,44 116,78 Q 116,112 46,112"
          stroke="white" strokeWidth={16} fill="none"
          strokeLinecap="round" strokeLinejoin="round"
        />

        {/* S upper arc — in front of P */}
        <path
          d="M 130,44 Q 168,44 168,78 Q 168,112 130,112"
          stroke="url(#ps-sg)" strokeWidth={16} fill="none"
          strokeLinecap="round" strokeLinejoin="round"
        />

        {/* Junction dot — meeting point of P and S */}
        <circle cx="130" cy="111" r="5.5" fill="#22D3EE" fillOpacity={0.8} />
      </svg>
    </div>
  );
}

export function LogoWordmark({ size = "md" }: { size?: "sm" | "md" }) {
  return (
    <div className="flex items-center gap-2.5">
      <LogoIcon size={size} />
      <div className="leading-none">
        <span className={`font-bold tracking-tight text-white ${size === "sm" ? "text-[13px]" : "text-base"}`}>
          PracticeSync
        </span>
        <span className={`font-bold tracking-tight text-blue-400 ${size === "sm" ? "text-[13px]" : "text-base"}`}>
          {" "}AI
        </span>
      </div>
    </div>
  );
}
