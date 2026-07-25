import type { Config } from "tailwindcss";

// Brand tokens mirror apps/web/tailwind.config.ts so the marketing site and the
// application read as one product. Values are the canonical PracticeSync palette
// documented in apps/web/app/globals.css.
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
          hover: "#0F1A3D",
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
      boxShadow: {
        card: "0 1px 3px rgba(24,35,80,0.06), 0 1px 2px rgba(24,35,80,0.04)",
        "card-hover": "0 10px 40px rgba(24,35,80,0.12)",
        modal: "0 20px 60px rgba(24,35,80,0.20)",
      },
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
