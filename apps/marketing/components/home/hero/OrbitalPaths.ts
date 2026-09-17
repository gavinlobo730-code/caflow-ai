/**
 * The trajectories.
 *
 * §8 calls this "a critical part of the visual" and asks for paths at
 * different angles, radii, orientations and depths, some passing behind the
 * Earth and some in front. Three decisions carry that:
 *
 * THEY ARE RIBBONS, NOT LINES. WebGL caps gl_LineWidth at 1 on virtually every
 * desktop driver, so a THREE.Line is one device pixel — half a CSS pixel at
 * the DPR this renders at, which aliases into a dashed grey thread. Each path
 * is a camera-facing strip instead, two triangles per segment, which gives a
 * width in WORLD units that thins correctly with distance. §8 rules out thick
 * glowing tubes and these are 0.006-0.014 of the planet's radius: a hairline
 * that survives being drawn.
 *
 * DEPTH IS TESTED AND ALSO SHADED. The planet is opaque, so the depth buffer
 * hides the part of an orbit that crosses the disc. That is occlusion, and it
 * is not the same as distance — a path clearing the disc into open space is
 * unoccluded whether it is in front or behind, and at equal brightness the
 * scene flattens. ORBIT_FRAGMENT dims by view depth as well, which is what
 * makes a far sweep read as far.
 *
 * SCREEN ANGLE COMES FROM ry, NOT rz. An orbit is a ring in its own plane, so
 * rotating it about its own normal (rz) moves nothing you can see. What sets
 * the angle it crosses the screen at is where its normal points after the
 * Y-then-X pair. Two paths were once given different rz values to separate
 * them, stayed exactly where they were, and drew a large X over the middle of
 * the composition.
 */

import { hash01 } from "./math";
import {
  ORBIT_VERTEX,
  ORBIT_FRAGMENT,
  POINT_VERTEX,
  POINT_FRAGMENT,
} from "./shaders";

type OrbitDef = {
  /** Semi-major axis, in planet radii. */
  a: number;
  /** Semi-minor as a fraction of the major, so 1 is a circle. */
  b: number;
  /** Rotation about Y then X, radians. See the header on why there is no rz. */
  ry: number;
  rx: number;
  /** Centre offset in world units. Negative z pushes the path behind. */
  ox: number;
  oy: number;
  oz: number;
  width: number;
  opacity: number;
  color: number;
  /** Where the bright part of the sweep sits, 0..1 round the path. */
  sweep: number;
  /** How many illuminated nodes ride on it. */
  nodes: number;
};

/**
 * Seven paths.
 *
 * Every field differs from its neighbours somewhere — §8 is explicit that they
 * must NOT all be identical circles, and the failure mode of a table like this
 * is varying one column and leaving the rest.
 *
 * Six are blue or blue-white. ONE is warm, at low opacity, because §8 allows
 * "a very restrained amount of warm light" and a single warm trajectory ties
 * the orbital system to India's champagne rather than leaving the two as
 * unrelated colour stories. A second warm path would read as a scheme.
 */
const ORBITS: OrbitDef[] = [
  // Wide and near-equatorial: the one that sweeps the whole composition.
  { a: 1.62, b: 0.34, ry: 0.10, rx: 0.30, ox: 0, oy: -0.04, oz: 0, width: 0.011, opacity: 0.50, color: 0x5fa3ff, sweep: 0.10, nodes: 3 },
  // Steep, crossing the first near the poles.
  { a: 1.44, b: 0.92, ry: -0.62, rx: 0.18, ox: 0.05, oy: 0, oz: -0.10, width: 0.008, opacity: 0.34, color: 0x4a86f0, sweep: 0.55, nodes: 2 },
  // Tilted the other way, so the two make a lens rather than an X.
  { a: 1.30, b: 0.58, ry: 0.78, rx: -0.26, ox: -0.03, oy: 0.06, oz: 0.05, width: 0.009, opacity: 0.40, color: 0x7ab6ff, sweep: 0.80, nodes: 3 },
  // Close in and shallow, hugging the atmosphere.
  { a: 1.17, b: 0.26, ry: -0.20, rx: 0.46, ox: 0, oy: 0.02, oz: 0.02, width: 0.007, opacity: 0.44, color: 0x9fccff, sweep: 0.35, nodes: 2 },
  // The warm one. Low opacity; it is an accent, not a member of the set.
  { a: 1.50, b: 0.45, ry: 0.42, rx: -0.10, ox: 0.02, oy: -0.08, oz: -0.04, width: 0.008, opacity: 0.26, color: 0xffc98a, sweep: 0.62, nodes: 2 },
  // Far and faint, mostly behind: the brief's far layer, as a trajectory.
  { a: 2.05, b: 0.70, ry: -0.95, rx: 0.34, ox: -0.10, oy: 0.05, oz: -0.55, width: 0.006, opacity: 0.17, color: 0x3f7ad8, sweep: 0.20, nodes: 2 },
  // Farther again, nearly edge-on, clipping the top of the frame.
  { a: 2.45, b: 0.18, ry: 0.28, rx: -0.44, ox: 0.06, oy: 0.10, oz: -0.85, width: 0.006, opacity: 0.13, color: 0x3a6fc8, sweep: 0.88, nodes: 1 },
];

type Vec3 = [number, number, number];

/** Rotate about Y then X — the order the definitions above assume. */
function orient(p: Vec3, ry: number, rx: number): Vec3 {
  const [x, y, z] = p;
  const x1 = x * Math.cos(ry) + z * Math.sin(ry);
  const z1 = -x * Math.sin(ry) + z * Math.cos(ry);
  const y2 = y * Math.cos(rx) - z1 * Math.sin(rx);
  const z2 = y * Math.sin(rx) + z1 * Math.cos(rx);
  return [x1, y2, z2];
}

function ellipsePoints(d: OrbitDef, radius: number, segments: number): Vec3[] {
  const pts: Vec3[] = [];
  for (let i = 0; i <= segments; i++) {
    const t = (i / segments) * Math.PI * 2;
    const local: Vec3 = [Math.cos(t) * d.a * radius, 0, Math.sin(t) * d.a * d.b * radius];
    const o = orient(local, d.ry, d.rx);
    pts.push([o[0] + d.ox, o[1] + d.oy, o[2] + d.oz]);
  }
  return pts;
}

function sub(a: Vec3, b: Vec3): Vec3 {
  return [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
}
function cross(a: Vec3, b: Vec3): Vec3 {
  return [
    a[1] * b[2] - a[2] * b[1],
    a[2] * b[0] - a[0] * b[2],
    a[0] * b[1] - a[1] * b[0],
  ];
}
function norm(a: Vec3): Vec3 {
  const l = Math.hypot(a[0], a[1], a[2]) || 1;
  return [a[0] / l, a[1] / l, a[2] / l];
}

/**
 * A strip that faces the camera along its whole length.
 *
 * The offset at each point is perpendicular to both the path's tangent and
 * the direction to the eye, which is what keeps a ribbon from vanishing when
 * it turns edge-on. Computed once at build time because the camera does not
 * move; when it does, this becomes a vertex shader that takes the eye as a
 * uniform, and the geometry it produces is unchanged.
 */
function ribbonGeometry(
  THREE: any,
  pts: Vec3[],
  width: number,
  eye: Vec3
) {
  const n = pts.length;
  const pos = new Float32Array(n * 2 * 3);
  const uv = new Float32Array(n * 2 * 2);
  const idx: number[] = [];

  for (let i = 0; i < n; i++) {
    const prev = pts[(i - 1 + n) % n];
    const next = pts[(i + 1) % n];
    const tangent = norm(sub(next, prev));
    const toEye = norm(sub(eye, pts[i]));
    let side = cross(tangent, toEye);
    if (Math.hypot(side[0], side[1], side[2]) < 1e-6) side = [0, 1, 0];
    side = norm(side);

    const t = i / (n - 1);
    for (let s = 0; s < 2; s++) {
      const sign = s === 0 ? 1 : -1;
      const k = (i * 2 + s) * 3;
      pos[k] = pts[i][0] + side[0] * width * sign;
      pos[k + 1] = pts[i][1] + side[1] * width * sign;
      pos[k + 2] = pts[i][2] + side[2] * width * sign;
      uv[(i * 2 + s) * 2] = t;
      uv[(i * 2 + s) * 2 + 1] = s;
    }

    if (i < n - 1) {
      const a = i * 2;
      idx.push(a, a + 1, a + 2, a + 1, a + 3, a + 2);
    }
  }

  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  g.setAttribute("uv", new THREE.BufferAttribute(uv, 2));
  g.setIndex(idx);
  return g;
}

export type OrbitOptions = { radius: number; cameraZ: number };

export function createOrbitalPaths(THREE: any, opts: OrbitOptions) {
  const meshes: any[] = [];
  const scales: Array<{ value: number }> = [];
  const edges: Array<{ value: any }> = [];
  const eye: Vec3 = [0, 0, opts.cameraZ];

  const nodePts: Vec3[] = [];
  const nodeSizes: number[] = [];
  const nodeGlow: number[] = [];
  const nodeCols: Array<[number, number, number]> = [];

  ORBITS.forEach((d, oi) => {
    const pts = ellipsePoints(d, opts.radius, 220);
    const geo = ribbonGeometry(THREE, pts, d.width * opts.radius, eye);

    const mat = new THREE.ShaderMaterial({
      uniforms: {
        uColor: { value: new THREE.Color(d.color) },
        uOpacity: { value: d.opacity },
        uSweep: { value: d.sweep },
        uCameraZ: { value: opts.cameraZ },
        uResolution: { value: new THREE.Vector2(1, 1) },
        uEdge: { value: 120 },
      },
      vertexShader: ORBIT_VERTEX,
      fragmentShader: ORBIT_FRAGMENT,
      transparent: true,
      depthWrite: false,
      side: THREE.DoubleSide,
      blending: THREE.AdditiveBlending,
    });

    const mesh = new THREE.Mesh(geo, mat);
    edges.push(mat.uniforms.uResolution);
    // Behind the planet in the queue when the path itself is behind it, so the
    // additive blend does not lighten the planet through its own body.
    mesh.renderOrder = d.oz < -0.4 ? 1 : 6;
    meshes.push(mesh);

    // Nodes riding the path. §8: they should look as though they could be
    // moving later, which means sitting ON the trajectory rather than near it,
    // so they are sampled from the same point list the ribbon was built from.
    for (let k = 0; k < d.nodes; k++) {
      const t = hash01(oi * 37 + k * 11 + 3);
      const p = pts[Math.floor(t * (pts.length - 1))];
      nodePts.push(p);
      nodeSizes.push(0.022 + hash01(oi * 41 + k) * 0.014);
      nodeGlow.push(0.55 + hash01(oi * 43 + k) * 0.45);
      const warm = d.color === 0xffc98a;
      nodeCols.push(warm ? [1.0, 0.82, 0.58] : [0.72, 0.87, 1.0]);
    }
  });

  // One Points for every node on every path.
  const g = new THREE.BufferGeometry();
  const pos = new Float32Array(nodePts.length * 3);
  const col = new Float32Array(nodePts.length * 3);
  nodePts.forEach((p, i) => {
    pos[i * 3] = p[0];
    pos[i * 3 + 1] = p[1];
    pos[i * 3 + 2] = p[2];
    col[i * 3] = nodeCols[i][0];
    col[i * 3 + 1] = nodeCols[i][1];
    col[i * 3 + 2] = nodeCols[i][2];
  });
  g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  g.setAttribute("aColor", new THREE.BufferAttribute(col, 3));
  g.setAttribute("aSize", new THREE.BufferAttribute(new Float32Array(nodeSizes), 1));
  g.setAttribute("aGlow", new THREE.BufferAttribute(new Float32Array(nodeGlow), 1));

  const uniforms = { uScale: { value: 600 }, uOpacity: { value: 0.95 } };
  const nodes = new THREE.Points(
    g,
    new THREE.ShaderMaterial({
      uniforms,
      vertexShader: POINT_VERTEX,
      fragmentShader: POINT_FRAGMENT,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    })
  );
  nodes.renderOrder = 6;
  meshes.push(nodes);
  scales.push(uniforms.uScale);

  return { meshes, scales, edges };
}
