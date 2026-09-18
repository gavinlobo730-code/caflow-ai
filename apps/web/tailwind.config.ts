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
        /* ── PracticeSync surfaces, ink and state ────────────────────────────
           THE PALETTE EXISTED AND NOTHING READ IT. Before this, `brand`,
           `gold` and the four `ps` tokens below were declared here and used
           ZERO times in the banking module and barely anywhere else: the app
           carried 10,933 raw hex literals across 263 files, all of them
           shadcn's default slate, so the product looked like a template rather
           than like PracticeSync. That is the same failure this codebase keeps
           finding in its data layer — one authority, nothing reads it, copies
           drift — and the fix is the same: make the authority sufficient, then
           make everything read it.

           The set was not sufficient, which is part of why. `ps` had surfaces
           and no INK, so every screen reached for `text-[#0F172A]`; there were
           no STATE colours, so each screen picked its own emerald and amber;
           and there was no single primary, so three were in use at once —
           brand navy here, indigo #4338CA in banking, blue-700 on the Team
           screen. What follows closes all three. */
        ps: {
          /* Surfaces, lightest to heaviest. */
          bg:      "#F8FAFC",   /* the application background */
          surface: "#FFFFFF",   /* a card, a row, a panel */
          muted:   "#F1F5F9",   /* a table header, a quiet fill */
          hover:   "#E9EFF6",   /* powder-tinted, not grey — it is the brand */
          border:  "#E2E8F0",
          "border-strong": "#CBD5E1",

          /* Ink, by ROLE rather than by number. A numbered scale is just slate
             with different names and gives the next author no guidance; a role
             says which one to reach for.

             FOUR STEPS, NOT THREE, and the hover pairs are why. The app had
             two hover conventions running side by side — 104 sites darkening
             hint->label and 67 darkening label->body — so a three-step scale
             collapsed one of them and the hover silently stopped changing
             anything. One convention now: interactive muted text darkens one
             step, and every existing pair still moves.

             The navy cast is deliberate. A pure slate grey beside a navy brand
             reads as unconsidered. */
          ink:      "#0D1635",  /* headings, figures, anything load-bearing */
          body:     "#334155",  /* body copy, and the hover target */
          label:    "#64748B",  /* labels, secondary copy, quiet controls */
          hint:     "#94A3B8",  /* hints, placeholders, empty states */
          disabled: "#CBD5E1",
        },

        /* ── State, and why it is not the Tailwind palette ────────────────────
           A CA screen is read for STATE before it is read for text — is this
           line ready, does it need me, did something go wrong — so state is a
           first-class token rather than whichever green a given file reached
           for. `surface` is the row or chip fill, `ink` the text on it,
           `border` the hairline, `solid` a filled button.

           These are deliberately NOT the accent: the accent is the brand, and
           a screen that renders "ready" in brand navy has spent its one loud
           colour on a status. */
        state: {
          ready:            "#047857",  /* nothing left to do — act on it */
          "ready-surface":  "#ECFDF5",
          "ready-border":   "#A7F3D0",
          "ready-solid":    "#059669",

          attention:        "#B45309",  /* a person has to answer something */
          "attention-surface": "#FFFBEB",
          "attention-border":  "#FDE68A",

          problem:          "#B91C1C",  /* it failed, or it will */
          "problem-surface":"#FEF2F2",
          "problem-border": "#FECACA",

          "ready-hover":    "#DCFCE7",  /* a ready ROW under the cursor */

          done:             "#475569",  /* settled, kept for the record */
          "done-surface":   "#F8FAFC",
          "done-border":    "#E2E8F0",
        },

        /* ── Money direction, which is NOT state ─────────────────────────────
           Found while tokenising the banking module: a first pass mapped
           "Deposits" to the ready green and "Withdrawals" to the problem red,
           because those were the greens and reds the file happened to use. Both
           are false signals. A withdrawal is not a problem — it is half of what
           a bank account does — and a deposit is not something to act on.
           Money DIRECTION is its own axis and gets its own tokens, so a
           figure's colour never accidentally says a CA has work to do.

           `negative` is a third thing again: a BALANCE below zero is a fact
           about a position, not a movement, and an overdraft is a legitimate
           one. It is emphatic without being alarming. */
        money: {
          in:       "#15803D",  /* received, deposited, credited */
          out:      "#9F1239",  /* paid, withdrawn, debited */
          negative: "#7F1D1D",  /* a balance below zero */
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
