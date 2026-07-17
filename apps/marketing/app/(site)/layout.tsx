import { SiteHeader } from "@/components/SiteHeader";
import { SiteFooter } from "@/components/SiteFooter";
import { ScrollJackProvider } from "@/components/ScrollJack";

// Shared chrome for the public marketing pages. The login gateway (/access)
// lives OUTSIDE this group so it renders as a clean, standalone chooser without
// the full site header/footer. The homepage (`/`) also lives outside this
// group — it's served verbatim from the static reference file via a Cloudflare
// Pages rewrite (see public/_redirects) and brings its own nav/footer baked in,
// so it doesn't want this shared chrome either.
//
// ScrollJackProvider is kept as the one shared place a future page-level scroll
// effect would plug into; nothing consumes it today.
export default function SiteLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <ScrollJackProvider>
      <SiteHeader />
      <main>{children}</main>
      <SiteFooter />
    </ScrollJackProvider>
  );
}
