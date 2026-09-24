import type { Config } from "tailwindcss";

const config: Config = {
  /* THERE IS NO DARK MODE AND `darkMode: ["class"]` IS NOT HOW ONE WOULD BE
     ADDED. It sat here from the shadcn scaffold and was provably inert: zero
     `dark:` utilities in `app/`, `components/` and `lib/`, no `.dark` selector
     anywhere, and `globals.css` declares `html { color-scheme: light }`. Left
     in, it reads as a switch somebody could flip — and flipping it would emit
     a dark variant with nothing defined behind it, so the first `dark:` class
     written against it would be the only styled thing on an otherwise
     unchanged screen. A real dark theme is a second value for every token
     below, not a line here. */
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
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
        /* ── PracticeSync brand tokens ── */
        brand: {
          DEFAULT: "#182350",
          light:   "#AFD2FA",
          dark:    "#0D1635",
          /* A tinted fill behind a brand-ish or ACTIVE mark — an icon chip, an
             empty state's medallion. Added 24-09-2026 while tokenising the
             three screens that thread colour through `style={{}}`; it is not
             an invented colour but the value those screens already wrote in
             three places for exactly this one role, which is the same method
             the ink steps below were fixed by.

             NOT `ps.hover`. That token means a row UNDER THE CURSOR, and a
             static fill borrowing it is the mistake the PDF palette recorded
             refusing: there the nearest hex to a "this reconciles" fill was
             `state.ready-hover`, which means a ready row being pointed at —
             something a printed page does not have. Map by ROLE, never by
             nearest value. */
          surface: "#EFF6FF",
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
             reads as unconsidered.

             ── THE TWO LIGHT STEPS MOVED DOWN, AND THE MEASUREMENT IS WHY ──
             The scale named four roles; the app wrote SEVEN greys, two or
             three spellings per role, and the token file had picked the
             LIGHTER spelling of each of the bottom two:

               role     spellings in the code            token held
               ink      #0F172A (801) #1E293B (333)      #0D1635 (13)
               body     #334155 (1,070)                  #334155  ✓
               label    #64748B (1,388) #475569 (894)    #64748B  ← lighter
               hint     #94A3B8 (1,567)                  #94A3B8  ← unreadable

             `hint` at #94A3B8 is **2.56:1 on white** — the single most-used
             colour in the product, far below WCAG 1.4.3's 4.5:1, and most of
             its 1,567 sites are `text-[10px]` or `text-[11px]`. `label` at
             #64748B is 4.76 on white and **4.34 on `ps.muted`**, so it failed
             on the very fill a table header uses it over.

             Each moves down ONE spelling, to a value the product already uses
             for the same role, so nothing is invented:

               label  #64748B → #475569   7.58 white · 7.24 bg · 6.92 muted
               hint   #94A3B8 → #64748B   4.76 white · 4.55 bg · 4.34 muted

             THE HOVER PAIRS ALL STILL MOVE, which is the invariant that had to
             hold and was checked over every `text-[#a] hover:text-[#b]` pair in
             the tree: the dominant one is #94A3B8 → #475569 (95 sites), which
             becomes hint → label with the TARGET unchanged and only the base
             darkened. The only pairs that collapse are seven already spelling
             #182350 → #182350 today.

             ⚠️ `hint` is 4.34 on `ps.muted` — below 4.5 — and 18 sites put it
             there. A hint belongs on white or on `ps.bg`, both of which it
             passes; those 18 want `label`. Named rather than solved, because
             solving it means a grey the product does not already use.

             `disabled` is deliberately left failing: WCAG 1.4.3 exempts text in
             an inactive control, and darkening it would stop it reading as
             inactive, which is the one thing it has to say. */
          ink:      "#0D1635",  /* headings, figures, anything load-bearing */
          body:     "#334155",  /* body copy, and the hover target */
          label:    "#475569",  /* labels, secondary copy, quiet controls */
          hint:     "#64748B",  /* hints, placeholders, empty states */
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
      /* ── The two steps below Tailwind's smallest ────────────────────────
         Tailwind stops at `text-xs` (12px). A CA screen does not: the product
         writes `text-[10px]` 999 times and `text-[11px]` 861 times — a detail
         line under a figure, a column header, a chip — because there was no
         name for either. 2,252 arbitrary `text-[Npx]` in all, against a scale
         with nothing at that end to converge on.

         DELIBERATELY BARE — a font size and NO line-height, which is what
         `text-[10px]` already emits. Tailwind's tuple form would pin a leading
         as well, and a site nested inside `text-sm` currently inherits 20px
         rather than 1.5×10px, so pinning one changes the rendering of an
         unknown share of 1,860 places. The rename has to be pixel-identical or
         it is not a rename. What the leading should be is a real question and
         it belongs with the reference screens, where it can be looked at.

         `text-[9px]` (29 sites) gets no name on purpose: it is below the size
         at which the remaining steps are distinguishable, and naming it would
         bless it. */
      fontSize: {
        "3xs": "10px",
        "2xs": "11px",
      },
      /* ── How wide a page is, decided by what it HOLDS (D11) ──────────────
         59 pages rendered a DataTable or a <table> inside a centred container
         and did it at NINE different widths — from `max-w-xl` (576px, the
         payroll reports screen) to `max-w-[1400px]` — with `max-w-5xl` and
         `max-w-7xl` both common. Nobody chose that spread; each page picked
         one when it was written. A register squeezed into 576px on a 1440
         screen scrolls sideways or truncates every column, which is the one
         thing a CA reading a ledger cannot afford.

         ONE TOKEN, NAMED FOR THE ROLE rather than the number, so the value
         can move without 59 edits. 1600px is D11's own figure, and what it
         BUYS depends on the monitor, which is worth knowing before reading a
         screenshot: `AppShell`'s two rails take 272px and a page's own gutter
         another 48, so a 1440 laptop leaves ~1120px of content — narrower
         than `max-w-6xl` — and on that screen the change is invisible for
         every page that was already 6xl or wider, and moves only the ones
         that were 5xl (1024), 4xl (896) and 3xl (768). On a 1920 monitor the
         token binds just barely, which is the point: fill the space, stop
         before a row is too wide to track across.

         THERE IS DELIBERATELY NO `ps-read` TOKEN. D11 has a second half —
         prose, forms and single-column reads keep a 65-75 character measure —
         and it is ALREADY TRUE here: of 102 pages that centre a container,
         exactly ONE runs to a data width without holding data, and that one
         renders its rows through a custom component rather than a table, so
         it is a misreading of the scan rather than a defect. Declaring a
         token nothing reads is the shape this file already refuses twice
         below. */
      maxWidth: {
        "ps-data": "1600px",
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      /* NO ELEVATION TOKENS. `shadow-card`, `shadow-card-hover` and
         `shadow-modal` were declared here and used ZERO times — every card in
         the product writes Tailwind's own `shadow-sm` or a `shadow-[...]`
         arbitrary value. Three names nothing reads are three names the next
         author has to check before trusting, which is the `capital_wip` shape
         this codebase keeps finding. A real elevation scale is part of the
         reference screens, where it can be looked at against a card; declaring
         one here first would just re-create what was deleted. */
    },
  },
  plugins: [],
};
export default config;
