# PracticeSync — Marketing Site

The public website for PracticeSync (`practicesync.com`): marketing pages plus the
login gateway. It is a **separate app** from the product (`apps/web`) and holds
**no business logic and no authentication** of its own — it only *links* to the
app for login, the client portal and signup.

```
apps/web        →  app.practicesync.com    the application (dashboard, login, portal)
apps/marketing  →  practicesync.com         this site (marketing + login gateway)
```

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

| Variable              | Dev default             | Production                    |
| --------------------- | ----------------------- | ----------------------------- |
| `NEXT_PUBLIC_APP_URL` | `http://localhost:3000` | `https://app.practicesync.com`|

It is inlined at build time (static export), so set it in the Cloudflare Pages
build environment for production. Update `wrangler.toml` and `next.config.mjs` if
your app subdomain differs.

## Build

```bash
pnpm build       # static export to ./out
```

Same toolchain as `apps/web`: `output: "export"`, `trailingSlash: true`.

## Deploy (Cloudflare Pages)

This site is a **second Cloudflare Pages project**, parallel to `apps/web`
(`practicesync-ai`). That is the whole "subdomain" setup — two projects, two DNS
records:

1. **Create a Pages project** pointing at this folder:
   - Build command: `pnpm build`
   - Build output directory: `out`
   - Root directory: `apps/marketing`
   - Environment variable: `NEXT_PUBLIC_APP_URL = https://app.practicesync.com`
2. **DNS (in Cloudflare):**
   - `practicesync.com` (apex) → this marketing Pages project
   - `app.practicesync.com` → the existing `apps/web` Pages project
     _(this is the "add `app` + your URL" subdomain record)_

Cloudflare provides SSL and CDN for both automatically once the custom domains
are attached to their projects.
