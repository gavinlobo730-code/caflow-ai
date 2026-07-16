"use client";

import { usePathname } from "next/navigation";
import { SiteHeader } from "@/components/SiteHeader";
import { SiteFooter } from "@/components/SiteFooter";
import { CustomCursor } from "@/components/Cursor";
import { ScrollJackProvider } from "@/components/ScrollJack";

// Shared chrome for the public marketing pages. The login gateway (/access)
// lives OUTSIDE this group so it renders as a clean, standalone chooser without
// the full site header/footer — mirroring account.capium.com/Account/Login.
// CustomCursor is mounted once here so it's live across every page in the
// group without each page needing to remember to include it.
//
// ScrollJackProvider wraps everything (not just `main`) so SiteHeader's own
// scroll-condense effect can read the same signal as the home page's content
// — see ScrollJack.tsx's doc comment. The provider itself applies no
// transform and costs nothing on the 5 pages that never mount `<ScrollJack>`.
//
// The home page renders its own footer (inside its <ScrollJack>, so it's
// part of the same fake-scrolled content — anything outside that wrapper
// would be unreachable once native scroll is disabled) instead of this
// shared one, hence the isHome check below.
export default function SiteLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const isHome = pathname === "/";

  return (
    <ScrollJackProvider>
      <CustomCursor />
      <SiteHeader />
      <main>{children}</main>
      {!isHome && <SiteFooter />}
    </ScrollJackProvider>
  );
}
