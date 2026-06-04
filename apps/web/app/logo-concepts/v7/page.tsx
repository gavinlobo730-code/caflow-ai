export default function V7RefinementsPage() {
  const all = [
    { id:"r01", name:"Bold Minimal",      group:"dark",  desc:"Frame + header + clean 2×2. Maximum clarity at all sizes." },
    { id:"r02", name:"Dominant Panel",    group:"dark",  desc:"One large accent + 2 small. Clear visual hierarchy." },
    { id:"r03", name:"Corner Lit",        group:"dark",  desc:"Single illuminated quadrant. Instantly iconic at 16px." },
    { id:"r04", name:"Two Column",        group:"dark",  desc:"Header + 2 tall columns. Notion-level simplicity." },
    { id:"r05", name:"Three Row",         group:"dark",  desc:"Header + 3 stacked rows. Perfect favicon." },
    { id:"r06", name:"Solid Grid",        group:"dark",  desc:"Solid blue fill, white dividers. Bold and inverted." },
    { id:"r07", name:"Oversized Header",  group:"dark",  desc:"Header 45% height. Strong brand identity." },
    { id:"r08", name:"L-Shape",           group:"dark",  desc:"Accent spans header + left col. Distinctive silhouette." },
    { id:"r09", name:"Compact 3-Col",     group:"dark",  desc:"3-column layout, tight padding. Modern SaaS density." },
    { id:"r10", name:"Floating Tiles",    group:"dark",  desc:"No outer frame — tiles ARE the logo." },
    { id:"r11", name:"Notch",             group:"dark",  desc:"Teal pill in header. Premium, device-inspired." },
    { id:"r12", name:"Thick Border",      group:"dark",  desc:"Gradient stroke frame. Enterprise-grade boldness." },
    { id:"r13", name:"Light Classic",     group:"light", desc:"White bg, navy header, blue accent." },
    { id:"r14", name:"Light Blue Border", group:"light", desc:"White bg, gradient stroke, soft fills." },
    { id:"r15", name:"Light Minimal",     group:"light", desc:"Outline frame, single accent cell." },
    { id:"r16", name:"Light Warm",        group:"light", desc:"Off-white bg, navy header, pastel panels." },
    { id:"r17", name:"Mono Dark",         group:"mono",  desc:"Single blue tone, opacity depth." },
    { id:"r18", name:"Mono Outline",      group:"mono",  desc:"Pure line art, works on any background." },
    { id:"r19", name:"App Icon iOS",      group:"app",   desc:"iOS rounded square, gradient, frosted panels." },
    { id:"r20", name:"App Icon Premium",  group:"app",   desc:"Deep navy + glow. Linear / Stripe quality." },
  ];

  const slug = (n: string) => n.toLowerCase().replace(/[\s\/]+/g,"-").replace(/[^a-z0-9-]/g,"");
  const src = (v: typeof all[0]) => `/logos/v7/${v.id}-${slug(v.name)}.svg`;

  const groupMeta: Record<string, {label:string;color:string}> = {
    dark:  {label:"Dark Mode",    color:"text-blue-400"},
    light: {label:"Light Mode",   color:"text-slate-300"},
    mono:  {label:"Monochrome",   color:"text-slate-500"},
    app:   {label:"App Icons",    color:"text-violet-400"},
  };

  return (
    <div className="min-h-screen bg-[#050c1e] px-8 py-10">
      <div className="max-w-5xl mx-auto">
        <div className="mb-10">
          <p className="text-blue-500 text-xs font-semibold uppercase tracking-widest mb-1">V7 Workspace Window</p>
          <h1 className="text-3xl font-bold text-white">20 Refined Variations</h1>
          <p className="text-slate-500 text-sm mt-1">Dark · Light · Monochrome · App Icon</p>
        </div>

        {(["dark","light","mono","app"] as const).map(group => {
          const items = all.filter(v => v.group === group);
          const meta = groupMeta[group];
          return (
            <div key={group} className="mb-12">
              <p className={`text-[11px] font-bold uppercase tracking-widest mb-4 ${meta.color}`}>{meta.label}</p>
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-4">
                {items.map(v => (
                  <a key={v.id} href={src(v)} target="_blank" rel="noopener noreferrer" className="group">
                    <div className="rounded-2xl overflow-hidden border border-white/5 group-hover:border-blue-500/50 transition-all group-hover:scale-105 group-hover:shadow-xl group-hover:shadow-blue-950/50">
                      <img src={src(v)} alt={v.name} className="w-full aspect-square" loading="lazy"/>
                    </div>
                    <p className="mt-2 text-[11px] font-semibold text-white px-0.5">
                      <span className="text-blue-500 mr-1">{v.id.toUpperCase()}</span>{v.name}
                    </p>
                    <p className="text-[10px] text-slate-600 px-0.5 leading-snug">{v.desc}</p>
                  </a>
                ))}
              </div>
            </div>
          );
        })}

        <div className="mb-10">
          <p className="text-[11px] font-bold uppercase tracking-widest mb-4 text-amber-400">Favicon simulation — 16×16</p>
          <div className="flex flex-wrap gap-5 items-end bg-[#0a1628] rounded-2xl p-6">
            {all.map(v => (
              <div key={v.id} className="flex flex-col items-center gap-1.5">
                <img src={src(v)} alt={v.id} className="w-4 h-4 rounded-sm"/>
                <span className="text-[8px] text-slate-600">{v.id}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
