// The homepage route (`/`) is served verbatim from the design reference —
// `public/practicesync-homepage.html` — rather than re-implemented in React.
// Every prior native-port attempt drifted from the reference's exact pixel
// values, timing and easing; embedding the reference file directly removes
// that translation step entirely; there is no animation/timing logic here
// to drop or approximate. Deliberately outside the `(site)` route group so
// none of the shared chrome (SiteHeader, SiteFooter, ScrollJackProvider,
// CustomCursor) mounts on this route — the reference brings its own full
// nav and footer baked into the HTML. Trade-off: this route doesn't share
// the site's real header/footer components, and other pages' "Our Story"
// link (`/#story`) can no longer deep-scroll into a section inside the
// iframe's own document — it lands on the homepage instead, same as any
// other nav link. Two static-export routes can't otherwise share a domain
// origin's path space with a rewrite (`output: "export"` has no server to
// rewrite with), so an iframe is the simplest static-compatible embed.
export default function HomePage() {
  return (
    <iframe
      src="/practicesync-homepage.html"
      title="PracticeSync — AI-first practice management for Indian CA firms"
      style={{ position: "fixed", inset: 0, width: "100vw", height: "100vh", border: 0 }}
    />
  );
}
