import { Instrument_Serif, Manrope } from "next/font/google";

// The site's two typefaces (see tailwind.config.ts's fontFamily.display and
// fontFamily.manrope), applied through CSS variables.
//
// ⚠️ THE COMMENT HERE USED TO SAY "the rest of the site keeps the root
// layout's Inter untouched", and that was how it started: these were loaded
// for the cinematic homepage only. Every page sets them for itself now — the
// `(site)` group around its chrome, `/access` on its own root — and as of
// 18-09-2026 so does the ROOT layout, which had been loading Inter from Google
// and putting it on `<body>` for a fallback nothing should reach. That was a
// whole extra font file fetched on every page for a face the design does not
// use, and it had already caught someone out once: see the note in
// `(site)/layout.tsx` about the header and footer "silently falling back to
// the root layout's Inter".
export const instrumentSerif = Instrument_Serif({
  subsets: ["latin"],
  weight: "400",
  style: ["normal", "italic"],
  variable: "--font-instrument-serif",
  display: "swap",
});

export const manrope = Manrope({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-manrope",
  display: "swap",
});
