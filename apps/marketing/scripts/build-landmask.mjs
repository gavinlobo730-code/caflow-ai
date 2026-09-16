/**
 * Generates components/home/landmask.ts — the world's coastline as a bitmask.
 *
 *     node scripts/build-landmask.mjs
 *
 * No install, no network, no dependencies. See "why" below.
 *
 * ── WHY THIS EXISTS ────────────────────────────────────────────────────────
 * The hero globe used to be a wireframe: a graticule grid and a Fibonacci point
 * cloud brightened near India, with no continents at all. geography.ts recorded
 * the reason — a coastline "would have to be written from memory here, and a
 * world map with the wrong coastline on the homepage of a product sold to
 * Indian professionals is a worse error than no map at all."
 *
 * That reasoning was right and its premise turned out to be false. The
 * coastline beside this file is Natural Earth's, public domain, published as
 * world-atlas@2's land-110m.json — a measured shoreline, not a recollection of
 * one. So the objection is answered rather than overruled.
 *
 * ── WHY THE SOURCE IS VENDORED AND NOTHING IS A DEPENDENCY ─────────────────
 * The obvious shape was `devDependencies: { world-atlas, topojson-client }`.
 * Measured: that is 8.0 MB installed, of which this script reads 55 KB, on
 * every Cloudflare Pages build — for a script that never runs there, because
 * its OUTPUT is committed. It also puts a registry fetch on the deploy path of
 * a file that cannot change without somebody editing it.
 *
 * So land-110m.json sits beside this script (55 KB, its LICENSE next to it) and
 * the TopoJSON decode is the twenty lines below rather than a package. That
 * decoder was checked against topojson-client's own `feature()` before the
 * package was dropped: 126 rings, 5,123 points, maximum coordinate difference
 * ZERO. It is in `scripts/` and not `public/`, so Next never serves it.
 *
 * This is the same discipline as domain/income_tax/schemas/ — the artefact is
 * committed, a person regenerates it deliberately, and the build just reads it.
 *
 * ── WHY A BITMASK RATHER THAN THE POLYGONS ─────────────────────────────────
 * The scene needs "is this point on land", asked ~9,000 times at startup, not a
 * coastline to draw. A 0.5-degree grid answers that in one array lookup, costs
 * 5.3 KB over the wire once gzipped, and leaves the point COUNT to be chosen at
 * runtime (denser on a desktop) rather than baked in here.
 *
 * ── WHY SCANLINE FILL RATHER THAN POINT-IN-POLYGON ─────────────────────────
 * Testing all 259,200 cells against 4,997 edges is 1.3 billion operations.
 * Intersecting each of the 360 latitude rows with the edge list is 1.8 million
 * and gives the identical answer: even-odd along a row IS the point-in-polygon
 * test, evaluated for a whole row at once. Even-odd across all rings together
 * is sound because land polygons do not overlap, and it handles lakes (interior
 * rings) for free.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = resolve(HERE, "land-110m.json");
const OUT = resolve(HERE, "../components/home/landmask.ts");

// 0.5-degree cells. At the size this globe renders (~600px across) a cell is
// well under a pixel, so a finer grid would cost bytes and change nothing.
const W = 720;
const H = 360;

const topo = JSON.parse(readFileSync(SRC, "utf8"));

/**
 * TopoJSON to rings of [lon, lat].
 *
 * Arcs are quantised and DELTA encoded, so each is decoded by running sum and
 * then affine-transformed by the topology's own scale/translate. A geometry
 * refers to arcs by index; a NEGATIVE index means arc ~i traversed backwards,
 * and consecutive arcs in one ring share an endpoint, which is why the second
 * and later arcs of a ring skip their first point.
 */
function ringsOf(topology, objectName) {
  const [sx, sy] = topology.transform.scale;
  const [tx, ty] = topology.transform.translate;
  const arcs = topology.arcs.map((arc) => {
    let x = 0;
    let y = 0;
    return arc.map(([dx, dy]) => {
      x += dx;
      y += dy;
      return [x * sx + tx, y * sy + ty];
    });
  });

  const assemble = (indices) => {
    const out = [];
    for (const i of indices) {
      const a = i < 0 ? arcs[~i].slice().reverse() : arcs[i];
      for (let k = out.length ? 1 : 0; k < a.length; k++) out.push(a[k]);
    }
    return out;
  };

  const rings = [];
  const walk = (g) => {
    if (g.type === "GeometryCollection") {
      g.geometries.forEach(walk);
      return;
    }
    const polys = g.type === "Polygon" ? [g.arcs] : g.type === "MultiPolygon" ? g.arcs : [];
    for (const poly of polys) for (const r of poly) rings.push(assemble(r));
  };
  walk(topology.objects[objectName]);
  return rings;
}

const edges = [];
for (const ring of ringsOf(topo, "land")) {
  for (let i = 0; i < ring.length - 1; i++) {
    edges.push([ring[i][0], ring[i][1], ring[i + 1][0], ring[i + 1][1]]);
  }
}

const bytes = new Uint8Array(Math.ceil((W * H) / 8));
for (let row = 0; row < H; row++) {
  // The latitude through the middle of this row of cells.
  const lat = 90 - (row + 0.5) * (180 / H);
  const xs = [];
  for (const [x1, y1, x2, y2] of edges) {
    // Half-open in y so a vertex sitting exactly on the scanline is counted
    // once rather than twice — the standard crossing rule. Counting it twice
    // punches a hole in the fill at that latitude.
    if ((y1 <= lat && y2 > lat) || (y2 <= lat && y1 > lat)) {
      xs.push(x1 + ((lat - y1) / (y2 - y1)) * (x2 - x1));
    }
  }
  xs.sort((a, b) => a - b);
  for (let k = 0; k + 1 < xs.length; k += 2) {
    let c0 = Math.ceil(((xs[k] + 180) / 360) * W - 0.5);
    let c1 = Math.floor(((xs[k + 1] + 180) / 360) * W - 0.5);
    if (c0 < 0) c0 = 0;
    if (c1 > W - 1) c1 = W - 1;
    for (let c = c0; c <= c1; c++) {
      const i = row * W + c;
      bytes[i >> 3] |= 1 << (i & 7);
    }
  }
}

let onCells = 0;
for (let i = 0; i < W * H; i++) if (bytes[i >> 3] & (1 << (i & 7))) onCells++;
const pct = ((100 * onCells) / (W * H)).toFixed(1);

const b64 = Buffer.from(bytes).toString("base64");
const gz = gzipSync(Buffer.from(b64)).length;
const n = (v) => v.toLocaleString("en-US");

writeFileSync(
  OUT,
  `// GENERATED by scripts/build-landmask.mjs — do not edit by hand.
//
// The world's land as a ${W}x${H} bitmask (0.5-degree cells), row 0 at +90 lat and
// column 0 at -180 lon, packed LSB-first and base64 encoded. Source data is
// Natural Earth via world-atlas@2's land-110m, public domain; the copy this was
// built from is scripts/land-110m.json with its licence beside it.
//
// ${n(onCells)} of ${n(W * H)} cells are land (${pct}%), against a real figure of
// about 29%. ${n(b64.length)} characters here; ${n(gz)} bytes on the wire once
// Cloudflare gzips it, which is what a world map costs when it is a mask rather
// than a texture.
//
// apps/api/tests/test_the_marketing_site_says_what_the_product_does.py decodes
// this and checks eleven named coordinates fall on the right side of the
// coastline, so a regenerated mask that puts Mumbai in the sea fails rather
// than ships.

export const MASK_W = ${W};
export const MASK_H = ${H};

const PACKED =
  "${b64}";

let bits: Uint8Array | null = null;

/** Decoded lazily. Only the WebGL scene and the SVG fallback ask, and neither
 *  runs during the static export's server render. */
function decode(): Uint8Array {
  if (bits) return bits;
  const bin =
    typeof atob === "function"
      ? atob(PACKED)
      : Buffer.from(PACKED, "base64").toString("binary");
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  bits = out;
  return out;
}

/**
 * Is this coordinate on land?
 *
 * Longitude is WRAPPED rather than clamped: a Fibonacci sphere walked with the
 * golden angle produces longitudes far outside [-180, 180], and clamping them
 * would pile every overflow onto the date line — a stripe of false land down
 * the Pacific.
 */
export function isLand(lat: number, lon: number): boolean {
  const b = decode();
  const wrapped = ((((lon + 180) % 360) + 360) % 360) - 180;
  let row = Math.floor(((90 - lat) / 180) * MASK_H);
  let col = Math.floor(((wrapped + 180) / 360) * MASK_W);
  if (row < 0) row = 0;
  else if (row > MASK_H - 1) row = MASK_H - 1;
  if (col < 0) col = 0;
  else if (col > MASK_W - 1) col = MASK_W - 1;
  const i = row * MASK_W + col;
  return (b[i >> 3] & (1 << (i & 7))) !== 0;
}
`
);

console.log(`rings/edges    ${edges.length} edges`);
console.log(`land cells     ${onCells} of ${W * H} = ${pct}%  (real land is about 29%)`);
console.log(`base64         ${b64.length} chars`);
console.log(`gzipped        ${gz} bytes`);
console.log(`wrote          ${OUT}`);
