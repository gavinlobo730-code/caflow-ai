import Link from "next/link";

// PracticeSync wordmark. `theme` picks contrast for the surface it sits on:
//   light → dark wordmark on a light background (header)
//   dark  → light wordmark on a dark background (footer, hero)
export function Logo({
  theme = "light",
  href = "/" as string | null,
}: {
  theme?: "light" | "dark";
  href?: string | null;
}) {
  const tile =
    theme === "light"
      ? "bg-brand text-white ring-1 ring-black/5"
      : "bg-brand-light text-brand ring-1 ring-white/20";
  const word = theme === "light" ? "text-brand-dark" : "text-white";

  const inner = (
    <span className="inline-flex items-center gap-2.5">
      <span
        className={`grid h-8 w-8 place-items-center rounded-lg text-[15px] font-extrabold ${tile}`}
      >
        P
      </span>
      <span className={`text-[17px] font-bold tracking-tight ${word}`}>
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
