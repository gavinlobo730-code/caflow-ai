/**
 * The globe every visitor who does not get WebGL sees.
 *
 * `canRunGlobe()` says no to four populations — reduced motion, under 900px,
 * four gigabytes or less of device memory, and no WebGL context — and on a
 * marketing homepage the second of those is most of the traffic. So this is
 * not a degraded placeholder that happens to be there; for a lot of people it
 * IS the hero, and §25 asks that the mobile version keep the Earth, India, the
 * network and the atmosphere while shedding complexity.
 *
 * It is always rendered, and the WebGL canvas is simply drawn on top when it
 * succeeds. That ordering is what makes the failure path free: there is no
 * detection to get wrong and nothing to swap in, because the fallback was
 * never removed.
 *
 * IT IS BUILT FROM THE SAME COASTLINE AS THE 3D SCENE. The dots come from
 * landmask.ts through an orthographic projection of the visible hemisphere, so
 * the small globe and the large one show the same world rather than two
 * different artists' idea of one. Generated at module scope from a fixed
 * lattice, so it is identical on the server and the client and React never
 * reports a hydration mismatch.
 */

import { isLand } from "../landmask";
import { INDIA_CENTRE, INDIA_LIGHTS } from "./cities";
import { hash01 } from "./math";

type Dot = { x: number; y: number; r: number; o: number; warm: boolean };

const R = 100;
const LAT0 = (INDIA_CENTRE.lat * Math.PI) / 180;
const LON0 = INDIA_CENTRE.lon;

/**
 * Orthographic projection of a lat/lon onto the visible disc.
 *
 * Returns null for the far hemisphere — the cos(c) term is the standard
 * visibility test, and without it the back of the planet folds forward and
 * doubles every continent.
 */
function project(lat: number, lon: number): { x: number; y: number; k: number } | null {
  const la = (lat * Math.PI) / 180;
  const dl = ((lon - LON0) * Math.PI) / 180;
  const cosc = Math.sin(LAT0) * Math.sin(la) + Math.cos(LAT0) * Math.cos(la) * Math.cos(dl);
  if (cosc <= 0.06) return null;
  return {
    x: R * Math.cos(la) * Math.sin(dl),
    y: -R * (Math.cos(LAT0) * Math.sin(la) - Math.sin(LAT0) * Math.cos(la) * Math.cos(dl)),
    // How square-on this point is: used to fade the dots toward the limb, so
    // the disc does not end in a hard ring of full-brightness pixels.
    k: cosc,
  };
}

function inSubcontinent(lat: number, lon: number): boolean {
  return lat > 5 && lat < 36 && lon > 66 && lon < 93;
}

/**
 * The land dots.
 *
 * A 3-degree lattice, which is 7,200 candidates reduced to a few hundred after
 * the land test, the hemisphere test and a deterministic thin-out. §26 warns
 * against thousands of DOM elements and this is the screen where that matters
 * most — it is the one phones get.
 */
const DOTS: Dot[] = (() => {
  const out: Dot[] = [];
  let i = 0;
  for (let lat = -84; lat <= 84; lat += 3) {
    for (let lon = -180; lon < 180; lon += 3) {
      i++;
      if (!isLand(lat, lon)) continue;
      const p = project(lat, lon);
      if (!p) continue;
      const warm = inSubcontinent(lat, lon);
      // Keep the subcontinent dense and thin the rest, so India reads as the
      // busiest region without being a different colour block.
      if (!warm && hash01(i) > 0.5) continue;
      const edge = Math.min(1, p.k * 1.5);
      // JITTERED, because a 3-degree lattice draws its own rows and columns.
      // Unjittered this is the "flat dotted world map" read the desktop globe
      // was rebuilt to escape, reproduced on the screen most visitors see.
      // Half a cell: enough to break the grid, not enough to move a dot off
      // the coastline it was tested against.
      out.push({
        x: p.x + (hash01(i * 11 + 1) - 0.5) * 2.1,
        y: p.y + (hash01(i * 11 + 2) - 0.5) * 2.1,
        r: warm ? 0.95 : 0.7 + hash01(i * 3) * 0.35,
        o: (warm ? 0.85 : 0.3 + hash01(i * 5) * 0.34) * edge,
        warm,
      });
    }
  }
  return out;
})();

/** India's own cities, as the few brighter nodes. */
const HUBS = INDIA_LIGHTS.filter((l) => l.w >= 1.7)
  .map((l) => ({ p: project(l.lat, l.lon), w: l.w }))
  .filter((h) => h.p !== null) as Array<{ p: { x: number; y: number; k: number }; w: number }>;

export function GlobeFallback({ className = "" }: { className?: string }) {
  return (
    <svg
      viewBox="-170 -170 340 340"
      className={className}
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        <radialGradient id="psf-body" cx="38%" cy="32%" r="78%">
          <stop offset="0%" stopColor="#152544" />
          <stop offset="55%" stopColor="#0a1327" />
          <stop offset="100%" stopColor="#03060f" />
        </radialGradient>
        <radialGradient id="psf-halo" cx="50%" cy="50%" r="50%">
          <stop offset="62%" stopColor="rgba(61,134,255,0)" />
          <stop offset="82%" stopColor="rgba(61,134,255,0.22)" />
          <stop offset="100%" stopColor="rgba(61,134,255,0)" />
        </radialGradient>
        <radialGradient id="psf-india" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="rgba(255,206,150,0.5)" />
          <stop offset="100%" stopColor="rgba(255,206,150,0)" />
        </radialGradient>
        <radialGradient id="psf-sun" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="rgba(255,217,168,0.85)" />
          <stop offset="100%" stopColor="rgba(255,217,168,0)" />
        </radialGradient>
      </defs>

      {/* Stars. Kept off the left, matching §14 in the 3D scene. */}
      {Array.from({ length: 46 }).map((_, i) => {
        const a = hash01(i * 7 + 1) * Math.PI * 2;
        const rad = 120 + hash01(i * 7 + 2) * 48;
        const x = Math.cos(a) * rad;
        const y = Math.sin(a) * rad;
        const fade = x < -40 ? 0.3 : 1;
        return (
          <circle
            key={`s${i}`}
            cx={x}
            cy={y}
            r={0.5 + hash01(i * 7 + 3) * 0.9}
            fill="#dce9ff"
            opacity={(0.16 + hash01(i * 7 + 4) * 0.5) * fade}
          />
        );
      })}

      {/* Outer glow, then the body. */}
      <circle cx="0" cy="0" r="150" fill="url(#psf-halo)" />
      <circle cx="0" cy="0" r={R} fill="url(#psf-body)" />

      {/* Orbits: three, at different sizes and angles, as in the 3D scene. */}
      <g fill="none" strokeLinecap="round">
        <ellipse cx="0" cy="0" rx="144" ry="34" stroke="rgba(95,163,255,0.34)" strokeWidth="0.9" transform="rotate(-14)" />
        <ellipse cx="0" cy="0" rx="126" ry="74" stroke="rgba(74,134,240,0.2)" strokeWidth="0.8" transform="rotate(28)" />
        <ellipse cx="0" cy="0" rx="116" ry="26" stroke="rgba(159,204,255,0.26)" strokeWidth="0.7" transform="rotate(8)" />
      </g>

      {/* The land. */}
      <g>
        {DOTS.map((d, i) => (
          <circle
            key={`d${i}`}
            cx={d.x}
            cy={d.y}
            r={d.r}
            fill={d.warm ? "#ffce96" : "#7fb2ff"}
            opacity={d.o}
          />
        ))}
      </g>

      {/* India's warm accent — restrained, and under the hubs so they read. */}
      {(() => {
        const p = project(INDIA_CENTRE.lat, INDIA_CENTRE.lon);
        if (!p) return null;
        return <circle cx={p.x} cy={p.y} r="42" fill="url(#psf-india)" />;
      })()}

      {HUBS.map((h, i) => (
        <circle key={`h${i}`} cx={h.p.x} cy={h.p.y} r={0.9 + h.w * 0.35} fill="#fff1dc" opacity="0.92" />
      ))}

      {/* Limb: a bright inner edge and the atmosphere just outside it. */}
      <circle cx="0" cy="0" r={R} fill="none" stroke="rgba(93,160,255,0.5)" strokeWidth="1.1" />
      <circle cx="0" cy="0" r={R + 3.5} fill="none" stroke="rgba(61,134,255,0.16)" strokeWidth="5" />

      {/* The sun, upper right, where the 3D scene puts it. */}
      <circle cx={R * 0.72} cy={-R * 0.6} r="34" fill="url(#psf-sun)" />
    </svg>
  );
}
