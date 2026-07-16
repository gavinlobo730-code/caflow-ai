import { Instrument_Serif, Manrope } from "next/font/google";

// Home-page-only typefaces for the cinematic rebuild (see
// tailwind.config.ts's fontFamily.display/manrope). The rest of the site
// keeps the root layout's Inter untouched — these are applied via CSS
// variable only on the home page's own root element.
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
