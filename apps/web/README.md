# apps/web — the PracticeSync product UI

The browser app a practising Chartered Accountant works in: clients, accounting, GST, TDS, income tax, payroll,
banking, the employee and client portals. Next.js 14 (App Router), TypeScript, Tailwind, shadcn-style primitives.

It is one of three apps in this repository: the FastAPI backend lives in `apps/api` and the separate public site
in `apps/marketing`. The design record for all three is [`CLAUDE.md`](../../CLAUDE.md) at the repository root; read the
section for the thing you are changing before you change it.

## What it is, and the three things that follow from that

**A static export.** `next.config.mjs` sets `output: "export"`, so `pnpm build` writes plain files to `out/` and
Cloudflare Pages serves them (the project is `practicesync-ai`, served at `caflow-ai.pages.dev`; the older
`caflow` spelling in names and URLs is known legacy, not a typo to fix). From that:

1. **There is no server and no runtime environment.** The only values the app can read are `NEXT_PUBLIC_*`, and
   those are inlined into the browser bundle at build time. A secret placed in `.env.local` is published. Every AI
   provider key and the Supabase service-role key live in `apps/api/.env`, never here. `.env.local.example` lists
   the three it needs: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` (public by
   design; row-level security is what protects the data) and `NEXT_PUBLIC_API_URL`. The last has a production
   fallback in `next.config.mjs` that must match `wrangler.toml`; `scripts/api-url.test.ts` fails if they disagree.
   Browser error reporting also reads an optional `NEXT_PUBLIC_SENTRY_DSN` (with a release and an environment tag):
   where no DSN is built in, nothing is reported (`lib/monitoring`).
2. **There is no business logic here.** Computation, validation and statutory rules live in `apps/api`. A screen
   asks the backend and renders the answer; where the browser holds a copy of a rule it is a keystroke mirror,
   pinned to the Python authority by a shared fixture (`shared/*.json`, or a test in `apps/api/tests`), and says so.
3. **Dynamic routes are scarce.** A static export cannot serve `/clients/<any id>/...`, so
   `scripts/generate-redirects.js` writes `public/_redirects` from the `app/` tree on every build (never edit it).
   Cloudflare Pages allows 100 dynamic rules and drops the rest silently. Do not add a page under a dynamic
   prefix such as `/clients/[id]`; a new client section is a query parameter on an existing route. The budget and
   the reason are in `CLAUDE.md`, "Deployment".

## Two ways to reach data

- **The API** (`lib/api`): every call carries the signed-in user's token and gets `{ success, data, error }` back.
  `lib/api` aborts at 45 seconds and never retries.
- **PostgREST directly** (`lib/data`, `lib/supabase`): about 320 reads and writes go straight to the database, so
  `rbac()` never runs on them and only row-level security decides. Treat a new one as a decision, not a shortcut.
  A response is capped near 1,000 rows without saying so: page it with `lib/supabase/selectAll.ts`.

Anything read from either is untrusted until checked: an array state variable is replaced from a payload only
through `arrayOrEmpty` / `objectOrNull` / `objectWithLists` (`lib/api/shape.ts`). A server that answers a refusal as
HTTP 200, a cold start or a deploy half-rolled-out will otherwise put `undefined` where a list was.

## Working on it

```bash
pnpm install
cp .env.local.example .env.local      # then fill in the Supabase values; the API defaults to localhost:8000
pnpm dev                              # http://localhost:3000, expects apps/api on :8000

pnpm lint                             # next lint
pnpm exec tsc --noEmit                # type-check the app
pnpm exec tsc -p tsconfig.test.json   # type-check the test files too (the app config excludes them)
pnpm test                             # node's built-in runner with --experimental-strip-types
pnpm build                            # regenerates redirects and known routes, then next build -> out/
```

`pnpm test` runs the `*.test.ts` files under `scripts/`, `lib/` and `components/`. Most of `scripts/` is **guards**: tests that read
the source tree and fail on a rule being broken (one parser for every rupee amount, no work stored in the browser,
every form field named, every keyboard-reachable control visibly focused, no heavy library in the first load). They
state the rule, not a spelling of it, and each says what it replaced. Read the failing one's header before changing
it to pass. The backend suite holds a further set that reads this app from the Python side (`apps/api/tests`,
run in CI as "browser contract" when only `apps/web` changed).

## Layout

| path | holds |
|---|---|
| `app/` | routes (one folder per screen, `page.tsx`); `layout.tsx` mounts `AppShell`, and the shells and the skip link are in `components/shell/` |
| `components/ui/` | vendored shadcn-style primitives. There is no `components.json`, so the shadcn CLI will not work: add a primitive by hand |
| `components/` | everything built from them, grouped by area (`accounting/`, `gst/`, `banking/`, `payroll/` …) |
| `lib/api/` | the backend client and the payload guards (`shape.ts`) |
| `lib/money/` | the one rupee parser (`rupeeInput.ts`) and the keystroke mirrors of the GST arithmetic |
| `lib/data/`, `lib/supabase/` | direct database access and its pager |
| `lib/monitoring/` | browser error reporting (errors only, scrubbed by shape, no session replay) |
| `scripts/` | build scripts (`generate-*.js`) and the guard tests |
| `public/` | static assets and the generated `_redirects` |

## Rules that bite

- **Money is integer paise** end to end. Parse a typed amount with `lib/money/rupeeInput.ts` and nothing else
  (`parseFloat(x) * 100` turns "1,25,000" into one rupee). Group rupees the Indian way, through `lib/money/format.ts`.
- **A year picker is derived from the clock**, never listed (`lib/dates/periods.ts`).
- **Never store the user's work in `localStorage`.** A remembered tab or an unsent draft is fine, with a reason.
- **Nothing is filed from here.** The product prepares; the CA files on the government portal. A screen that
  demonstrates filing says so in words and goes through the one shared demo wizard.
- Do not write an API URL path into a comment in a shared file: the reachability guard reads URL literals and credits
  a comment's to whatever unit it falls in.
