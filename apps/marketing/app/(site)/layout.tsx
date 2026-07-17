import { SiteHeader } from "@/components/SiteHeader";
import { SiteFooter } from "@/components/SiteFooter";
import { CustomCursor } from "@/components/Cursor";
import { ScrollJackProvider } from "@/components/ScrollJack";

// Shared chrome for the public marketing pages. The login gateway (/access)
// lives OUTSIDE this group so it renders as a clean, standalone chooser without
// the full site header/footer — mirroring account.capium.com/Account/Login.
// The homepage (`/`) also lives outside this group — it's served verbatim
// from a static reference file via an iframe (see app/page.tsx) and brings
// its own nav/footer baked in, so it doesn't want this shared chrome either.
// CustomCursor is mounted once here so it's live across every page in the
// group without each page needing to remember to include it.
//
// ScrollJackProvider wraps everything (not just `main`) so SiteHeader's own
// scroll-condense effect can read the same signal as any page that mounts
// `<ScrollJack>` — see ScrollJack.tsx's doc comment. No page in this group
// currently does; the provider's `contentRef` stays null and SiteHeader's
// effect falls back to plain `window.scrollY`, same as it always has for
// every page in this group.
export default function SiteLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <ScrollJackProvider>
      <CustomCursor />
      <SiteHeader />
      <main>{children}</main>
      <SiteFooter />
    </ScrollJackProvider>
  );
}
