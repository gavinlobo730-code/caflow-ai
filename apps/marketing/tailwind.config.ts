import type { Config } from "tailwindcss";

// Brand tokens mirror apps/web/tailwind.config.ts so the marketing site and the
// application read as one product. Values are the canonical PracticeSync palette
// documented in apps/web/app/globals.css.
//
// THAT CLAIM IS NOW ENFORCED, and it was not before:
// `apps/api/tests/test_the_marketing_site_reads_as_one_product.py` reads BOTH
// configs and requires every colour declared here to equal the product's at the
// same path — and refuses one the product does not declare at all. A comment
// asserting a mirror that nothing checks is the drift shape CLAUDE.md records
// three times, and it had already drifted: `brand.hover: #0F1A3D` existed in
// this file and nowhere in the product, for a role `apps/web` expresses as
// `brand-dark` at fifteen sites. It is gone and both call sites use
// `brand-dark`.
const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: "#182350", // Deep Blue — identity, primary actions
          light: "#AFD2FA", // Powder Blue — hover, selection, accents
          dark: "#0D1635", // near-black navy — headings
        },
        gold: {
          DEFAULT: "#B9915E", // Premium Gold — AI / intelligence accents
          surface: "#FEFAEF",
        },
        ps: {
          bg: "#F8FAFC",
          surface: "#FFFFFF",
          border: "#E2E8F0",
          muted: "#F1F5F9",
        },
      },
      // THREE DEAD SHADOW TOKENS WERE HERE — `card`, `card-hover` and `modal`,
      // the same three T3-a deleted from apps/web/tailwind.config.ts. Nothing
      // in this app referenced any of them (`grep -r "shadow-card"` was empty),
      // so they were a palette the site declared and never wore. Removed for
      // T3-a's reason rather than a new one.
      // Home-page-only typefaces (cinematic rebuild). The CSS vars only get
      // a real value where app/(site)/page.tsx's next/font/google loaders
      // are actually mounted — everywhere else these fall back to the
      // generic keyword, matching the site-wide Inter body font untouched.
      fontFamily: {
        display: ["var(--font-instrument-serif)", "serif"],
        manrope: ["var(--font-manrope)", "sans-serif"],
      },
      maxWidth: {
        // Matches the homepage reference's panel content width exactly
        // (public/practicesync-homepage.html uses max-width:1100px on every
        // panel's inner content, dark and light alike — not 1200px).
        content: "1100px",
      },
    },
  },
  plugins: [],
};

export default config;
