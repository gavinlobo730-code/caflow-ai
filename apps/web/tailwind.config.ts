import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class"],
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        /* ── PracticeSync brand tokens ── */
        brand: {
          DEFAULT: "#182350",
          light:   "#AFD2FA",
          dark:    "#0D1635",
        },
        gold: {
          DEFAULT: "#B9915E",
          surface: "#FEFAEF",
        },
        ps: {
          bg:      "#F8FAFC",
          surface: "#FFFFFF",
          border:  "#E2E8F0",
          muted:   "#F1F5F9",
        },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      boxShadow: {
        card:        "0 1px 3px rgba(24,35,80,0.06), 0 1px 2px rgba(24,35,80,0.04)",
        "card-hover":"0 4px 16px rgba(24,35,80,0.10)",
        modal:       "0 20px 60px rgba(24,35,80,0.20)",
      },
    },
  },
  plugins: [],
};
export default config;
