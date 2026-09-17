/**
 * The mesh the planet is wrapped in, and the sparser cage beyond it.
 *
 * This is the element that carries §28's "a network connecting everything" —
 * it is what separates a picture of the Earth from a picture of the Earth
 * being RUN by something. Two layers, and the difference between them is
 * depth rather than decoration (§20):
 *
 *   SURFACE  nodes just clear of the ground with short links to their nearest
 *            neighbours. Reads as infrastructure ON the planet.
 *   CAGE     a much sparser lattice at 1.28x radius with long links. Reads as
 *            a system AROUND it, and is the brief's "far network" layer.
 *
 * EVERYTHING IS TWO DRAW CALLS. All the nodes are one Points, all the links
 * one LineSegments, per layer — §26 rules out excessive draw calls, and the
 * honest reason is simpler: one mesh per node would be 110 matrix updates a
 * frame the moment this starts moving.
 *
 * Placement is a Fibonacci sphere, which gives near-uniform spacing without
 * the pole crowding of a lat/lon grid and without the clumping of a random
 * scatter. It is then jittered, because a perfect Fibonacci lattice shows its
 * own spiral as faint diagonal seams once you draw lines along it — the exact
 * artefact the dotted globe that preceded this had, and the reason the jitter
 * is half a lattice spacing rather than a whole one.
 */

import { hash01, latLonToVec3 } from "./math";
import { NETWORK_VERTEX, NETWORK_FRAGMENT, POINT_VERTEX, POINT_FRAGMENT } from "./shaders";
import { INDIA_LIGHTS } from "./cities";

const GOLDEN = Math.PI * (3 - Math.sqrt(5));

type Vec3 = [number, number, number];

/** N near-evenly spaced points on a sphere of the given radius. */
function fibonacciSphere(n: number, radius: number, jitter: number, seed: number): Vec3[] {
  const out: Vec3[] = [];
  for (let i = 0; i < n; i++) {
    const y = 1 - (i / (n - 1)) * 2;
    const r = Math.sqrt(Math.max(0, 1 - y * y));
    const th = GOLDEN * i;
    const j = jitter;
    out.push([
      (Math.cos(th) * r + (hash01(i * 3 + seed) - 0.5) * j) * radius,
      (y + (hash01(i * 3 + seed + 1) - 0.5) * j) * radius,
      (Math.sin(th) * r + (hash01(i * 3 + seed + 2) - 0.5) * j) * radius,
    ]);
  }
  return out;
}

function dist2(a: Vec3, b: Vec3): number {
  const dx = a[0] - b[0];
  const dy = a[1] - b[1];
  const dz = a[2] - b[2];
  return dx * dx + dy * dy + dz * dz;
}

/**
 * Link each node to its k nearest neighbours, de-duplicated.
 *
 * O(n^2) over about 120 nodes is 14,400 comparisons once, at build time. A
 * spatial index would be the right answer at ten times the count and is
 * unjustifiable complexity at this one.
 */
function nearestLinks(pts: Vec3[], k: number, maxDist: number): Array<[number, number]> {
  const seen = new Set<string>();
  const links: Array<[number, number]> = [];
  const max2 = maxDist * maxDist;

  for (let i = 0; i < pts.length; i++) {
    const order = pts
      .map((p, j) => ({ j, d: dist2(pts[i], p) }))
      .filter((e) => e.j !== i && e.d <= max2)
      .sort((a, b) => a.d - b.d)
      .slice(0, k);
    for (const { j } of order) {
      const key = i < j ? `${i}:${j}` : `${j}:${i}`;
      if (seen.has(key)) continue;
      seen.add(key);
      links.push([i, j]);
    }
  }
  return links;
}

function pointsMesh(
  THREE: any,
  pts: Vec3[],
  sizes: number[],
  glows: number[],
  colors: Array<[number, number, number]>,
  opacity: number,
  fragment: string,
  renderOrder: number
) {
  const g = new THREE.BufferGeometry();
  const pos = new Float32Array(pts.length * 3);
  const col = new Float32Array(pts.length * 3);
  pts.forEach((p, i) => {
    pos[i * 3] = p[0];
    pos[i * 3 + 1] = p[1];
    pos[i * 3 + 2] = p[2];
    col[i * 3] = colors[i][0];
    col[i * 3 + 1] = colors[i][1];
    col[i * 3 + 2] = colors[i][2];
  });
  g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  g.setAttribute("aColor", new THREE.BufferAttribute(col, 3));
  g.setAttribute("aSize", new THREE.BufferAttribute(new Float32Array(sizes), 1));
  g.setAttribute("aGlow", new THREE.BufferAttribute(new Float32Array(glows), 1));

  const uniforms = { uScale: { value: 600 }, uOpacity: { value: opacity } };
  const mesh = new THREE.Points(
    g,
    new THREE.ShaderMaterial({
      uniforms,
      vertexShader: POINT_VERTEX,
      fragmentShader: fragment,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    })
  );
  mesh.renderOrder = renderOrder;
  return { mesh, uniforms };
}

function linksMesh(
  THREE: any,
  pts: Vec3[],
  links: Array<[number, number]>,
  color: number,
  opacity: number,
  cameraZ: number,
  renderOrder: number,
  seed: number
) {
  const g = new THREE.BufferGeometry();
  const pos = new Float32Array(links.length * 6);
  const alpha = new Float32Array(links.length * 2);
  links.forEach(([a, b], i) => {
    const pa = pts[a];
    const pb = pts[b];
    for (let k = 0; k < 3; k++) {
      pos[i * 6 + k] = pa[k];
      pos[i * 6 + 3 + k] = pb[k];
    }
    // Per-link strength, so the mesh has a few bright trunks and many faint
    // capillaries instead of one uniform wireframe.
    const s = 0.35 + hash01(i * 13 + seed) * 0.65;
    alpha[i * 2] = s;
    alpha[i * 2 + 1] = s;
  });
  g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  g.setAttribute("aAlpha", new THREE.BufferAttribute(alpha, 1));

  const uniforms = {
    uColor: { value: new THREE.Color(color) },
    uOpacity: { value: opacity },
    uCameraZ: { value: cameraZ },
    uResolution: { value: new THREE.Vector2(1, 1) },
    uEdge: { value: 120 },
  };
  const mesh = new THREE.LineSegments(
    g,
    new THREE.ShaderMaterial({
      uniforms,
      vertexShader: NETWORK_VERTEX,
      fragmentShader: NETWORK_FRAGMENT,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    })
  );
  mesh.renderOrder = renderOrder;
  return { mesh, uniforms };
}

export type NetworkOptions = { radius: number; cameraZ: number };

export function createNetwork(THREE: any, opts: NetworkOptions) {
  const meshes: any[] = [];
  const scales: Array<{ value: number }> = [];
  const edges: Array<{ value: any }> = [];

  // ── Surface layer ────────────────────────────────────────────────────────
  const SURFACE_N = 128;
  const surfacePts = fibonacciSphere(SURFACE_N, opts.radius * 1.012, 0.035, 5);
  const surfaceLinks = nearestLinks(surfacePts, 3, opts.radius * 0.52);

  const sizes: number[] = [];
  const glows: number[] = [];
  const colors: Array<[number, number, number]> = [];
  for (let i = 0; i < SURFACE_N; i++) {
    const hub = hash01(i * 17 + 3) > 0.88;
    sizes.push(hub ? 0.03 : 0.016 + hash01(i * 17 + 5) * 0.009);
    glows.push(hub ? 1.0 : 0.42 + hash01(i * 17 + 7) * 0.4);
    // Cool white-blue. §18 keeps the network blue and leaves the warmth to
    // the surface lights, so nothing here competes with India.
    colors.push([0.62, 0.81, 1.0]);
  }

  const surfaceNodes = pointsMesh(
    THREE, surfacePts, sizes, glows, colors, 0.95, POINT_FRAGMENT, 4
  );
  meshes.push(surfaceNodes.mesh);
  scales.push(surfaceNodes.uniforms.uScale);
  const surfaceLinks3 = linksMesh(THREE, surfacePts, surfaceLinks, 0x4a8dff, 0.4, opts.cameraZ, 4, 31);
  meshes.push(surfaceLinks3.mesh);
  edges.push(surfaceLinks3.uniforms.uResolution);

  // ── India's own arcs ─────────────────────────────────────────────────────
  // The one place the mesh is not uniform: the subcontinent's cities are
  // joined to each other, so the densest part of the network sits over the
  // brightest part of the surface. §6 wants India's light to look as though it
  // "originates naturally from the network", and this is that claim made
  // structural rather than painted on.
  const indiaPts: Vec3[] = INDIA_LIGHTS.filter((l) => l.w >= 1.5).map(
    (l) => latLonToVec3(l.lat, l.lon, opts.radius * 1.014) as Vec3
  );
  const indiaLinks = nearestLinks(indiaPts, 2, opts.radius * 0.30);

  // ⚠️ THESE ARE THE DIMMEST NODES IN THE SCENE, NOT THE BRIGHTEST, AND THAT
  // IS THE CORRECTION THIS FEATURE NEEDED MOST.
  //
  // The first build gave them full glow at [0.85, 0.93, 1.0] — near white —
  // on top of surface lights that were already the brightest region of the
  // texture. Additive blending took the sum past 1.0 and clipped, so the
  // subcontinent rendered as a WHITE constellation: a blown-out patch with
  // visible lines drawn between its points, sitting on the planet rather than
  // belonging to it.
  //
  // That fails §6 twice over. It forbids India looking "pasted onto the globe"
  // and asks for the light to appear to "originate naturally from the network
  // of Indian cities" — and white is further from champagne than the solid
  // gold the same section rules out, because at least gold is the right hue.
  //
  // So the nodes are warm rather than white, are roughly a third the glow, and
  // the links they hang on are halved again. The network over India is now
  // something you notice after the glow, which is the order §6 asks for.
  const indiaNodes = pointsMesh(
    THREE,
    indiaPts,
    indiaPts.map((_, i) => 0.013 + hash01(i * 23) * 0.008),
    indiaPts.map((_, i) => 0.3 + hash01(i * 29) * 0.22),
    indiaPts.map(() => [1.0, 0.9, 0.76] as [number, number, number]),
    0.8,
    POINT_FRAGMENT,
    5
  );
  meshes.push(indiaNodes.mesh);
  scales.push(indiaNodes.uniforms.uScale);
  const indiaLinks3 = linksMesh(THREE, indiaPts, indiaLinks, 0x86a8e0, 0.2, opts.cameraZ, 5, 71);
  meshes.push(indiaLinks3.mesh);
  edges.push(indiaLinks3.uniforms.uResolution);

  // ── Far cage ─────────────────────────────────────────────────────────────
  const CAGE_N = 52;
  const cagePts = fibonacciSphere(CAGE_N, opts.radius * 1.285, 0.08, 91);
  const cageLinks = nearestLinks(cagePts, 2, opts.radius * 0.95);
  const cageNodes = pointsMesh(
    THREE,
    cagePts,
    cagePts.map((_, i) => 0.012 + hash01(i * 29) * 0.008),
    cagePts.map((_, i) => 0.2 + hash01(i * 31) * 0.3),
    cagePts.map(() => [0.5, 0.7, 1.0] as [number, number, number]),
    0.55,
    POINT_FRAGMENT,
    1
  );
  meshes.push(cageNodes.mesh);
  scales.push(cageNodes.uniforms.uScale);
  const cageLinks3 = linksMesh(THREE, cagePts, cageLinks, 0x2f6fd8, 0.17, opts.cameraZ, 1, 131);
  meshes.push(cageLinks3.mesh);
  edges.push(cageLinks3.uniforms.uResolution);

  return { meshes, scales, edges };
}
