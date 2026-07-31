import { SiteHeader } from "@/components/SiteHeader";
import { SiteFooter } from "@/components/SiteFooter";
import { ScrollJackProvider } from "@/components/ScrollJack";
import { instrumentSerif, manrope } from "@/lib/fonts";

// Shared chrome for the public marketing pages. The login gateway (/access)
// lives OUTSIDE this group so it renders as a clean, standalone chooser without
// the full site header/footer. The homepage (`/`) also lives outside this
// group — it's served verbatim from the static reference file via a Cloudflare
// Pages rewrite (see public/_redirects) and brings its own nav/footer baked in,
// so it doesn't want this shared chrome either.
//
// ScrollJackProvider is kept as the one shared place a future page-level scroll
// effect would plug into; nothing consumes it today.
//
// SiteHeader is `position: fixed` (not sticky) to match the homepage's own nav
// exactly. `main` deliberately has NO top padding to compensate: every page's
// own hero (cinematic.tsx's Panel, seam="none") already has 96-150px of top
// padding on its inner content, well clear of the 68px header — and the
// section's own BACKGROUND must start at y:0 so it extends full-bleed behind
// the fixed header. An earlier version added `pt-[68px]` here to "compensate"
// for the fixed header, which seemed to fix layout but actually broke the
// header's translucency: that padding pushed the hero SECTION itself down,
// leaving `main`'s own transparent padding — showing plain white body —
// directly behind the header instead of the dark hero, so backdrop-blur had
// nothing but white to blend with (verified by testing without the padding:
// the header's blur/blend immediately matched the homepage's).
export default function SiteLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <ScrollJackProvider>
      {/* Manrope is applied HERE, around the chrome — not only inside each
          page's own wrapper. SiteHeader/SiteFooter render outside `children`,
          so when the font variables lived only on the page wrappers the nav
          and footer silently fell back to the root layout's Inter while the
          content between them was Manrope — the whole top bar and footer in a
          different typeface from the homepage's. Plain class names (no
          transform/filter/will-change) so SiteHeader's `position: fixed`
          still resolves against the viewport. */}
      <div className={`${instrumentSerif.variable} ${manrope.variable} font-manrope`}>
        <SiteHeader />
        <main>{children}</main>
        <SiteFooter />
      </div>
    </ScrollJackProvider>
  );
}
