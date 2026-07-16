import { SiteHeader } from "@/components/SiteHeader";
import { SiteFooter } from "@/components/SiteFooter";
import { CustomCursor } from "@/components/Cursor";

// Shared chrome for the public marketing pages. The login gateway (/access)
// lives OUTSIDE this group so it renders as a clean, standalone chooser without
// the full site header/footer — mirroring account.capium.com/Account/Login.
// CustomCursor is mounted once here so it's live across every page in the
// group without each page needing to remember to include it.
//
// NOT wrapped in components/SmoothScroll.tsx (site-wide eased scroll): it
// fundamentally conflicts with `position: sticky`, which every pin mechanism
// on the home page (StoryStage, ScrollStage x2) depends on. Sticky needs an
// ancestor that *actually, natively* scrolls to compute its stuck state
// against; SmoothScroll fakes scrolling with a transform on a fixed
// (never-scrolling) ancestor instead, and confirmed by hand, multiple pinned
// sections ended up rendering stacked/overlapping — the rail stuck on
// "Scattered" while Trust-chapter content bled through underneath it. Fixing
// that properly means replacing every sticky pin with a JS-driven one (the
// standard fix libraries like GSAP ScrollSmoother document for this same
// conflict), which is a much larger, riskier rewrite of already-verified
// mechanisms than "add smooth scroll" was ever scoped to be.
export default function SiteLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <>
      <CustomCursor />
      <SiteHeader />
      <main>{children}</main>
      <SiteFooter />
    </>
  );
}
