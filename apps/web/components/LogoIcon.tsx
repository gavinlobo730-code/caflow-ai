"use client";

// PracticeSync AI logo mark — two-arc sync symbol in an indigo-violet gradient tile
export function LogoIcon({ size = "md" }: { size?: "sm" | "md" | "lg" | "xl" }) {
  const dims: Record<string, { box: string; svg: number; stroke: number }> = {
    sm:  { box: "w-7 h-7 rounded-lg",   svg: 15, stroke: 1.6 },
    md:  { box: "w-9 h-9 rounded-xl",   svg: 18, stroke: 1.8 },
    lg:  { box: "w-11 h-11 rounded-xl", svg: 22, stroke: 2.0 },
    xl:  { box: "w-14 h-14 rounded-2xl",svg: 28, stroke: 2.2 },
  };
  const { box, svg, stroke } = dims[size];

  return (
    <div
      className={`${box} bg-gradient-to-br from-violet-500 via-indigo-500 to-blue-600 flex items-center justify-center shadow-lg shrink-0`}
    >
      {/* Sync / refresh arc symbol */}
      <svg
        width={svg}
        height={svg}
        viewBox="0 0 20 20"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
      >
        {/* Top-right arc */}
        <path
          d="M3.5 10 A6.5 6.5 0 0 1 14.8 5.2"
          stroke="white"
          strokeWidth={stroke}
          strokeLinecap="round"
        />
        {/* Arrow head top */}
        <path
          d="M12.8 2.8 L15.4 5.0 L12.6 6.8"
          stroke="white"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        {/* Bottom-left arc */}
        <path
          d="M16.5 10 A6.5 6.5 0 0 1 5.2 14.8"
          stroke="white"
          strokeWidth={stroke}
          strokeLinecap="round"
        />
        {/* Arrow head bottom */}
        <path
          d="M7.2 17.2 L4.6 15.0 L7.4 13.2"
          stroke="white"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </div>
  );
}
