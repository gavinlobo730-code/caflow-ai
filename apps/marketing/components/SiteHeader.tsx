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
 * TRANSPARENT OVER THE TOP OF THE PAGE, NAVY ONCE SCROLLED — brief §3: "On the
 * hero, consider a transparent/dark navigation treatment so the page feels like
 * one continuous premium experience. On scroll, use a refined sticky navigation
 * with restrained contrast and no bulky header."
 *
 * THE SCROLLED STATE WAS AN OFF-WHITE UNTIL 16 SEPTEMBER 2026, and the owner
 * named it: "the top bar is grey right we shouldnt keep it gry you know we
 * should keep it blue the same blue that is our whole websote and the
 * platform." It was `#f3f5f8` — a colour the palette does not contain, on a
 * site whose every surface is either brand navy or ps-bg.
 *
 * MAKING IT NAVY DELETED A CLASS OF BUG RATHER THAN RECOLOURING ONE. The old
 * bar cross-faded between two palettes: the logo swapped mark, every nav link
 * swapped from white/75 to brand-dark/75, the mobile toggle swapped, and the
 * mobile sheet was a third colour again — all because the scrolled bar belonged
 * to a different colour family from the page it floated over. Navy in both
 * states means the logo is white always, links are white always, and there is
 * no `onNavy` fork left to get wrong. The only thing that now changes on scroll
 * is a background and a hairline fading in, which is what §3 actually asks for.
 *
 * THIS IS ONLY SAFE BECAUSE EVERY PAGE IN THIS GROUP OPENS DARK — the homepage
 * hero, and the first `<Panel theme="dark">` on story, products, pricing,
 * support, resources and demo alike. A treatment that applied to the homepage
 * alone is exactly the drift the redesign exists to end. If a page is ever
 * added that opens light, it is that page that has to change.
 *
 * NO SIZE CHANGE ON SCROLL. The earlier condense (shrinking height plus a
 * shadow) is what made the bar feel like it was jumping, and §3 asks for "no
 * bulky header" rather than a smaller one. The bar is a constant 68px, so
 * nothing below it moves — see the note on the element about why that hairline
 * is a shadow rather than a border.
 *
 * The threshold is deliberately small (24px): it has to fire before the reader
 * has scrolled far enough for anything to look unanchored.
 *
 * THE BAR IS FLUSH-LEFT ON THE HERO'S OWN GUTTER, not a centred column, and
 * that is an owner decision of 18-09-2026 reversing a trade the Hero's comment
 * used to record. `container-ps` was `max-width:1200px` with `margin:auto`, so
 * the logo's distance from the window edge GREW with the window — 57px at
 * 1280, 137 at 1440, 217 at 1600, 377 at 1920 — while the hero copy is pinned
 * flat at 72px. The two therefore matched at 1280 and diverged everywhere
 * above it, and on a 1600px window the logo sat 145px right of the headline it
 * reads as one lockup with. It now carries the hero's clamp verbatim.
 *
 * Both uses below take the class — the bar AND the mobile panel. Inlining the
 * gutter on one of them is how the sheet comes to start at a different edge
 * from the logo that opened it.
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
  const filled = solid || open;

  const linkCls =
    "text-[13px] font-medium leading-none text-white/70 transition-colors hover:text-white";

  return (
    // The hairline under the scrolled state is an INSET SHADOW, not a border. A
    // border — even a transparent one in the other state — adds a 69th pixel to
    // a bar that is exactly 68px everywhere else on the site, and a header that
    // changes height by a pixel as you start scrolling is precisely the drift
    // this redesign was meant to end. An inset shadow draws the same line and
    // costs no layout.
    // THE UNSCROLLED STATE CARRIES A SCRIM, and it is not cosmetic: without one
    // the nav is white text laid directly on the hero artwork. The hero's own
    // desktop scrim fades out at 58% of the viewport, so every link right of
    // that sits on raw picture — and the picture's top-right is the sunrise
    // glare and the planet rim, the brightest thing in the frame. Measured with
    // the header's own ink hidden, white-on-backdrop was 2.92:1 at 1600, 1.04:1
    // at 1920 and 1.84:1 at 2560 BEFORE the gutter moved; "Support" and
    // "Resources" were already unreadable at 1920 on the live site. Flushing the
    // bar left pushed the nav a further 145px into it, so this ships with it.
    //
    // A GRADIENT TALLER THAN THE BAR, not a background on it: a 68px block of
    // colour is the "bulky header" §3 rules out and would draw a hard edge
    // across the artwork. This fades to nothing 132px down, which reads as part
    // of the sky. It is drawn on a pseudo-element so the bar keeps its own
    // `bg-transparent` and the scrolled state is unchanged.
    //
    // Off whenever `filled` — the navy bar and the mobile sheet are opaque, so a
    // scrim under them is invisible at best and a seam over the open panel at
    // worst.
    <header
      className={`fixed inset-x-0 top-0 z-50 transition-[background-color,box-shadow,backdrop-filter] duration-300 before:pointer-events-none before:absolute before:inset-x-0 before:top-0 before:h-[132px] before:bg-[linear-gradient(to_bottom,rgba(2,8,22,0.80),rgba(2,8,22,0.46)_46%,rgba(2,8,22,0))] before:transition-opacity before:duration-300 ${
        filled
          ? "bg-brand-dark/85 shadow-[inset_0_-1px_0_rgba(175,210,250,0.14)] backdrop-blur-[14px] before:opacity-0"
          : "bg-transparent before:opacity-100"
      }`}
    >
      {/* `relative` so the bar's own contents paint ABOVE the scrim: the
          pseudo-element is positioned and would otherwise cover this static
          row, greying the logo and every link by 80%. */}
      <div className="container-ps relative flex h-[68px] items-center justify-between gap-4">
        {/* One mark, one colour, in both states — see the header note. */}
        <Logo theme="dark" />

        {/* Desktop nav */}
        <nav className="hidden items-center gap-[clamp(14px,2.5vw,34px)] lg:flex">
          {NAV.map((item) => (
            <Link key={item.href} href={item.href} className={linkCls}>
              {item.label}
            </Link>
          ))}
          {/* §3 wants "Sign in and Book a Demo prominent" (the brief's own
              capitalisation, quoted). Sign in is the word
              the destination itself uses — /access is headed "Sign in to
              PracticeSync." — where this said "Login", which matched neither the
              page nor the brief. */}
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
          className="rounded-lg p-2 text-white transition-colors hover:bg-white/10 lg:hidden"
          aria-label={open ? "Close menu" : "Open menu"}
          aria-expanded={open}
        >
          {open ? <X size={22} /> : <Menu size={22} />}
        </button>
      </div>

      {/* Mobile panel */}
      {open && (
        <div className="border-t border-white/10 bg-brand-dark lg:hidden">
          <div className="container-ps flex flex-col gap-1 py-4">
            {NAV.map((item, i) => (
              <Link
                key={item.href}
                href={item.href}
                onClick={() => setOpen(false)}
                className="fade-up rounded-lg px-3 py-2.5 text-[15px] font-medium text-white/80 hover:bg-white/[0.06]"
                style={{ animationDelay: `${i * 50}ms` }}
              >
                {item.label}
              </Link>
            ))}
            <div className="mt-2 flex flex-col gap-2 border-t border-white/10 pt-4">
              <Link
                href="/access"
                onClick={() => setOpen(false)}
                className="rounded-lg border border-white/20 px-4 py-2.5 text-center text-[15px] font-semibold text-white"
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
