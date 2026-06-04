export default function FinalLogoPage() {
  const logos = [
    { file: "01-icon.svg", label: "01 — Icon (Transparent)", bg: "#64748B", size: "200px" },
    { file: "02-dark-mode.svg", label: "02 — Dark Mode", bg: "#1E293B", size: "200px" },
    { file: "03-light-mode.svg", label: "03 — Light Mode", bg: "#E2E8F0", size: "200px" },
    { file: "06-app-icon.svg", label: "06 — App Icon", bg: "#1E293B", size: "200px" },
    { file: "09-monochrome-dark.svg", label: "09 — Monochrome Dark", bg: "#1E293B", size: "200px" },
    { file: "10-monochrome-light.svg", label: "10 — Monochrome Light", bg: "#E2E8F0", size: "200px" },
    { file: "11-production.svg", label: "11 — Production (Transparent)", bg: "#64748B", size: "200px" },
  ];

  const lockups = [
    { file: "04-horizontal-lockup-dark.svg", label: "04 — Horizontal Lockup Dark", bg: "#1E293B" },
    { file: "05-horizontal-lockup-light.svg", label: "05 — Horizontal Lockup Light", bg: "#E2E8F0" },
  ];

  const favicons = [
    { file: "07-favicon-32.svg", label: "07 — Favicon 32px", bg: "#64748B", size: "64px" },
    { file: "08-favicon-16.svg", label: "08 — Favicon 16px", bg: "#64748B", size: "48px" },
  ];

  return (
    <div className="min-h-screen bg-slate-950 p-10">
      <div className="max-w-5xl mx-auto space-y-12">
        <div>
          <h1 className="text-3xl font-bold text-white mb-1">PracticeSync — Final Logo System</h1>
          <p className="text-slate-400 text-sm">Production-ready deliverables • Layered workspace panel concept</p>
        </div>

        {/* Icons */}
        <section>
          <h2 className="text-slate-300 font-semibold text-lg mb-4 border-b border-slate-800 pb-2">Icons & App Icon</h2>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
            {logos.map((logo) => (
              <div key={logo.file} className="space-y-2">
                <div
                  className="rounded-xl flex items-center justify-center p-4"
                  style={{ background: logo.bg }}
                >
                  <img
                    src={`/logos/final/${logo.file}`}
                    alt={logo.label}
                    style={{ width: logo.size, height: logo.size, objectFit: "contain" }}
                  />
                </div>
                <p className="text-slate-400 text-xs text-center">{logo.label}</p>
              </div>
            ))}
          </div>
        </section>

        {/* Favicons */}
        <section>
          <h2 className="text-slate-300 font-semibold text-lg mb-4 border-b border-slate-800 pb-2">Favicons</h2>
          <div className="flex gap-8">
            {favicons.map((fav) => (
              <div key={fav.file} className="space-y-2">
                <div
                  className="rounded-xl flex items-center justify-center p-6"
                  style={{ background: fav.bg, width: "120px", height: "120px" }}
                >
                  <img
                    src={`/logos/final/${fav.file}`}
                    alt={fav.label}
                    style={{ width: fav.size, height: fav.size, imageRendering: "pixelated" }}
                  />
                </div>
                <p className="text-slate-400 text-xs text-center">{fav.label}</p>
              </div>
            ))}
          </div>
        </section>

        {/* Horizontal Lockups */}
        <section>
          <h2 className="text-slate-300 font-semibold text-lg mb-4 border-b border-slate-800 pb-2">Horizontal Lockups</h2>
          <div className="space-y-4">
            {lockups.map((lockup) => (
              <div key={lockup.file} className="space-y-2">
                <div
                  className="rounded-xl p-6 flex items-center"
                  style={{ background: lockup.bg }}
                >
                  <img
                    src={`/logos/final/${lockup.file}`}
                    alt={lockup.label}
                    style={{ height: "60px", objectFit: "contain" }}
                  />
                </div>
                <p className="text-slate-400 text-xs">{lockup.label}</p>
              </div>
            ))}
          </div>
        </section>

        {/* Color Palette */}
        <section>
          <h2 className="text-slate-300 font-semibold text-lg mb-4 border-b border-slate-800 pb-2">Brand Colors</h2>
          <div className="flex gap-4">
            {[
              { color: "#0F172A", label: "Primary #0F172A" },
              { color: "#1E3A5F", label: "Back Panel #1E3A5F" },
              { color: "#2563EB", label: "Mid Panel #2563EB" },
              { color: "#38BDF8", label: "Front Panel #38BDF8" },
            ].map((c) => (
              <div key={c.color} className="space-y-2">
                <div className="w-16 h-16 rounded-xl border border-slate-700" style={{ background: c.color }} />
                <p className="text-slate-400 text-xs">{c.label}</p>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
