export default function LogoConceptsPage() {
  const variants = [
    {
      id: "v1",
      name: "Layered Panels",
      desc: "Three offset workspace cards with inner detail — refined from your reference. Represents stacked, connected modules.",
      src: "/logos/v1-layered-panels.svg",
    },
    {
      id: "v2",
      name: "Module Grid",
      desc: "2×2 connected squares with junction node. Unified workspace where every module is linked.",
      src: "/logos/v2-module-grid.svg",
    },
    {
      id: "v3",
      name: "Orbit Rings",
      desc: "Three concentric arcs — an OS / platform dial. Inner core = AI engine. Outer rings = firm operations layers.",
      src: "/logos/v3-orbit-rings.svg",
    },
    {
      id: "v4",
      name: "Stacked Arches",
      desc: "Three nested open arches. Suggests workspace depth, structure, and enterprise layering.",
      src: "/logos/v4-stacked-arches.svg",
    },
    {
      id: "v5",
      name: "Command Hub",
      desc: "Central workspace with four satellite modules. Firm operations hub-and-spoke model.",
      src: "/logos/v5-command-hub.svg",
    },
    {
      id: "v6",
      name: "PS Bar Monogram",
      desc: "P letterform deconstructed into three gradient bars. Also reads as layered workspace stacks — dual meaning.",
      src: "/logos/v6-ps-bars.svg",
    },
    {
      id: "v7",
      name: "Workspace Window",
      desc: "App frame with 2×2 dashboard panels. Premium SaaS look comparable to Notion / Linear.",
      src: "/logos/v7-workspace-window.svg",
    },
    {
      id: "v8",
      name: "Interlocked Frames",
      desc: "Two overlapping squares — sync between modules, connected workflows, unified data layer.",
      src: "/logos/v8-interlocked-frames.svg",
    },
    {
      id: "v9",
      name: "Bold Bars",
      desc: "Three descending gradient bars. Crisp at any size — perfect 16×16 favicon. Suggests data hierarchy and workflow.",
      src: "/logos/v9-bold-bars.svg",
    },
    {
      id: "v10",
      name: "Diamond Stack",
      desc: "Three nested rotated squares offset for depth. Precision, data layers, enterprise grade.",
      src: "/logos/v10-diamond-stack.svg",
    },
  ];

  return (
    <div className="min-h-screen bg-[#060d1f] p-10">
      <div className="max-w-5xl mx-auto">
        {/* Header */}
        <div className="mb-12">
          <h1 className="text-3xl font-bold text-white tracking-tight">
            PracticeSync AI — Logo Concepts
          </h1>
          <p className="text-slate-400 mt-2 text-sm">
            10 variations · Deep navy + electric blue + teal · Click any to see full size
          </p>
        </div>

        {/* Grid */}
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-6">
          {variants.map((v) => (
            <a
              key={v.id}
              href={v.src}
              target="_blank"
              rel="noopener noreferrer"
              className="group"
            >
              <div className="rounded-2xl overflow-hidden border border-white/5 hover:border-blue-500/40 transition-all duration-200 hover:scale-105 hover:shadow-xl hover:shadow-blue-900/30">
                <img
                  src={v.src}
                  alt={v.name}
                  className="w-full aspect-square"
                />
              </div>
              <div className="mt-3 px-1">
                <p className="text-white text-xs font-semibold">
                  <span className="text-blue-400 mr-1">{v.id.toUpperCase()}</span>
                  {v.name}
                </p>
                <p className="text-slate-500 text-[10px] mt-0.5 leading-relaxed">
                  {v.desc}
                </p>
              </div>
            </a>
          ))}
        </div>

        {/* Size preview -->*/}
        <div className="mt-16">
          <p className="text-slate-500 text-xs uppercase tracking-widest mb-6 font-semibold">
            Size preview — how they look at different scales
          </p>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-8">
            {variants.map((v) => (
              <div key={v.id} className="flex flex-col items-center gap-4">
                <p className="text-[10px] text-slate-500 uppercase tracking-widest">{v.id.toUpperCase()}</p>
                {/* 64px — sidebar/header */}
                <img src={v.src} alt="" className="w-16 h-16 rounded-xl"/>
                {/* 32px — mobile */}
                <img src={v.src} alt="" className="w-8 h-8 rounded-lg"/>
                {/* 16px — favicon simulation */}
                <img src={v.src} alt="" className="w-4 h-4 rounded"/>
              </div>
            ))}
          </div>
        </div>

        <p className="text-center text-slate-600 text-xs mt-16">
          PracticeSync AI · Logo Concept Review · {new Date().getFullYear()}
        </p>
      </div>
    </div>
  );
}
