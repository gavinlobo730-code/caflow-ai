"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Logo } from "./Logo";
import { Magnetic } from "./Cursor";
import { Menu, X } from "./icons";
import { NAV } from "@/lib/site";

/**
 * The site header.
 *
 * TRANSPARENT OVER THE TOP OF THE PAGE, FROSTED ONCE SCROLLED — brief §3:
 * "On the hero, consider a transparent/dark navigation treatment so the page
 * feels like one continuous premium experience. On scroll, use a refined sticky
 * navigation with restrained contrast and no bulky header."
 *
 * THIS IS ONLY SAFE BECAUSE EVERY PAGE IN THIS GROUP OPENS DARK. The homepage
 * hero, and the first `<Panel theme="dark">` on products, pricing, support,
 * resources and demo alike — so the transparent state always sits on navy and
 * always reads in white, on every route. A treatment that applied to the
 * homepage alone is exactly the drift the whole redesign exists to end: for
 * months the homepage was a standalone HTML file whose nav looked subtly
 * different from this one, and every one of those differences had to be found
 * and fixed twice. There is one header, it behaves identically everywhere, and
 * if a page is ever added that opens light, it is that page that has to change.
 *
 * NO SIZE CHANGE ON SCROLL. The earlier condense (shrinking height plus a
 * shadow) is what made the bar feel like it was jumping, and §3 asks for "no
 * bulky header" rather than a smaller one. Only the background, the hairline
 * and the text colour cross-fade; the bar is a constant 68px, so nothing
 * below it moves — see the note on the element about why that hairline is a
 * shadow rather than a border.
 *
 * The threshold is deliberately small (24px). It has to fire before the reader
 * has scrolled far enough for the navy to leave the top of the viewport, or
 * there is a moment of white-on-white.
 */

const SOLID_AFTER_PX = 24;

export function SiteHeader() {
  const [open, setOpen] = useState(false);
  const [solid, setSolid] = useState(false);

  useEffect(() => {
    let raf = 0;
    const apply = () => {
      raf = 0;
      setSolid(window.scrollY > SOLID_AFTER_PX);
    };
    const onScroll = () => {
      if (!raf) raf = requestAnimationFrame(apply);
    };
    apply();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      window.removeEventListener("scroll", onScroll);
      cancelAnimationFrame(raf);
    };
  }, []);

  // The mobile panel is opaque whatever the scroll position — a translucent
  // sheet over a moving page is unreadable, and it is the one surface here that
  // carries a full list of links.
  const onNavy = !solid && !open;

  const linkCls = onNavy
    ? "text-[13px] font-medium leading-none text-white/75 transition-colors hover:text-white"
    : "text-[13px] font-medium leading-none text-brand-dark/75 transition-colors hover:text-brand-dark";

  return (
    // The hairline under the scrolled state is an INSET SHADOW, not a border.
    // A border — even a transparent one in the other state — adds a 69th pixel
    // to a bar that is exactly 68px everywhere else on the site, and a header
    // that changes height by a pixel as you start scrolling is precisely the
    // drift this redesign was meant to end. An inset shadow draws the same line
    // and costs no layout.
    <header
      className={`fixed inset-x-0 top-0 z-50 transition-[background-color,box-shadow,backdrop-filter] duration-300 ${
        onNavy
          ? "bg-transparent"
          : "bg-[#f3f5f8]/80 shadow-[inset_0_-1px_0_rgba(0,0,0,0.06)] backdrop-blur-[10px]"
      }`}
    >
      <div className="container-ps flex h-[68px] items-center justify-between gap-4">
        <Logo theme={onNavy ? "dark" : "light"} />

        {/* Desktop nav */}
        <nav className="hidden items-center gap-[clamp(14px,2.5vw,34px)] lg:flex">
          {NAV.map((item) => (
            <Link key={item.href} href={item.href} className={linkCls}>
              {item.label}
            </Link>
          ))}
          {/* §3 wants "Sign in and Book a Demo prominent". Sign in is the word
              the destination itself uses — /access is headed "Sign in to
              PracticeSync." — where this said "Login", which matched neither
              the page nor the brief. */}
          <Link href="/access" className={linkCls}>
            Sign in
          </Link>
          <Magnetic max={10}>
            {/* No trailing arrow: the icon made this button 20px wider and 7px
                taller than the one in the hero it is meant to match. */}
            <Link
              href="/demo"
              className="inline-flex items-center rounded-md bg-[#5876c7] px-[18px] py-2.5 text-[13px] font-semibold leading-none text-white transition-colors hover:bg-[#4d68af]"
            >
              Book a demo
            </Link>
          </Magnetic>
        </nav>

        {/* Mobile toggle */}
        <button
          onClick={() => setOpen((v) => !v)}
          className={`rounded-lg p-2 transition-colors lg:hidden ${
            onNavy ? "text-white hover:bg-white/10" : "text-brand hover:bg-black/[0.04]"
          }`}
          aria-label={open ? "Close menu" : "Open menu"}
          aria-expanded={open}
        >
          {open ? <X size={22} /> : <Menu size={22} />}
        </button>
      </div>

      {/* Mobile panel */}
      {open && (
        <div className="border-t border-black/[0.06] bg-[#f3f4f6] lg:hidden">
          <div className="container-ps flex flex-col gap-1 py-4">
            {NAV.map((item, i) => (
              <Link
                key={item.href}
                href={item.href}
                onClick={() => setOpen(false)}
                className="fade-up rounded-lg px-3 py-2.5 text-[15px] font-medium text-brand-dark/80 hover:bg-black/[0.04]"
                style={{ animationDelay: `${i * 50}ms` }}
              >
                {item.label}
              </Link>
            ))}
            <div className="mt-2 flex flex-col gap-2 border-t border-black/[0.06] pt-4">
              <Link
                href="/access"
                onClick={() => setOpen(false)}
                className="rounded-lg border border-black/10 px-4 py-2.5 text-center text-[15px] font-semibold text-brand"
              >
                Sign in
              </Link>
              <Link
                href="/demo"
                onClick={() => setOpen(false)}
                className="rounded-lg bg-[#5876c7] px-4 py-2.5 text-center text-[15px] font-semibold text-white"
              >
                Book a demo
              </Link>
            </div>
          </div>
        </div>
      )}
    </header>
  );
}
