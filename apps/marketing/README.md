# PracticeSync — Marketing Site

The public website for PracticeSync (`practicesync.com`): marketing pages plus the
login gateway. It is a **separate app** from the product (`apps/web`) and holds
**no business logic and no authentication** of its own — it only *links* to the
app for login, the client portal and signup.

```
Today (no custom domain — both on *.pages.dev):
  apps/web        →  caflow-ai.pages.dev       the application (dashboard, login, portal)
  apps/marketing  →  practicesync.pages.dev    this site (marketing + login gateway)

Later (once a custom domain is attached):
  apps/web        →  app.<yourdomain>
  apps/marketing  →  <yourdomain>
```

> The `apps/web` Cloudflare project is labeled **`practicesync-ai`** in the
> dashboard, but its `*.pages.dev` subdomain is `caflow-ai.pages.dev` — that
> subdomain is fixed at project creation and doesn't change on a dashboard
> rename. Always use the actual subdomain (`caflow-ai.pages.dev`) in config;
> the dashboard label is cosmetic.

## Pages

| Route        | What it is                                                        |
| ------------ | ----------------------------------------------------------------- |
| `/`          | Home — hero, why, product overview, trust, testimonial, CTA       |
| `/products`  | The six modules in detail + security                              |
| `/pricing`   | Plans + FAQ                                                        |
| `/support`   | Help channels + contact                                           |
| `/resources` | Guides + Indian statutory compliance calendar                     |
| `/access`    | **Login gateway** — two cards (Firm workspace / Client portal)    |

The `/access` gateway's cards link into `apps/web`: the firm card → `/login`, the
client card → `/portal/dashboard`, and "Start a free trial" → `/signup`.

## Local development

```bash
cd apps/marketing
pnpm install
pnpm dev        # http://localhost:3001
```

Run `apps/web` alongside it on `http://localhost:3000` so the login/portal links
resolve during development (that's the default `NEXT_PUBLIC_APP_URL` in dev).

## Configuration

One environment variable controls where "log in / sign up" send visitors:

| Variable              | Dev default             | Production (now)                   |
| --------------------- | ----------------------- | ---------------------------------- |
| `NEXT_PUBLIC_APP_URL` | `http://localhost:3000` | `https://caflow-ai.pages.dev`|

It is inlined at build time (static export). `next.config.mjs` already falls back
to the values above, so no dashboard config is strictly required. Once a custom
domain is attached, change it to `https://app.<yourdomain>` (in the Cloudflare
build environment, or in `next.config.mjs`/`wrangler.toml`) and redeploy.

## Build

```bash
pnpm build       # static export to ./out
```

Same toolchain as `apps/web`: `output: "export"`, `trailingSlash: true`.

## Deploy (Cloudflare Pages)

A **second Cloudflare Pages project**, parallel to `apps/web` (`practicesync-ai`).

### Now — no custom domain (both sites on `*.pages.dev`)

1. **Create a Pages project** connected to this repo:
   - Root directory: `apps/marketing`
   - Build command: `pnpm build`
   - Build output directory: `out`
   - Production branch: `main`
   - Build env var (optional — `next.config.mjs` already falls back to it):
     `NEXT_PUBLIC_APP_URL = https://caflow-ai.pages.dev`
2. **Deploy.** The site goes live at `https://practicesync.pages.dev`,
   and its login gateway links across to `https://caflow-ai.pages.dev`.

No DNS work is needed at this stage — Cloudflare gives each project a
`*.pages.dev` URL with SSL automatically.

### Later — attaching a custom domain

1. Add your domain to Cloudflare (point nameservers to Cloudflare, or use
   Cloudflare Registrar) and wait until the zone is **Active**.
2. **Custom domains:** on the marketing project add the apex (`<yourdomain>`);
   on the `practicesync-ai` project add `app.<yourdomain>`. Cloudflare creates
   the DNS records for you — that is the whole "add `app` + your URL" step.
3. Set `NEXT_PUBLIC_APP_URL = https://app.<yourdomain>` (dashboard build var or
   `next.config.mjs`) and redeploy so the gateway targets the app subdomain.
