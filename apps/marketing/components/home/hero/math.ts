/**
 * The arithmetic the hero scene is built on.
 *
 * Three things live here because more than one module needs them and two
 * copies of any of them is two scenes that agree until one is edited:
 * the sphere-to-screen projection, the lat/lon convention, and the
 * deterministic hash that stands in for Math.random.
 *
 * THE HASH IS NOT A CONVENIENCE. Every scattered element in this scene — a
 * star, a rural light, an asteroid, a node on an orbit — is placed from
 * `hash01(i)` rather than `Math.random()`, so the composition is the same on
 * every load and on every machine. That is what makes it reviewable: when the
 * owner says a card collides with an asteroid, the asteroid is in the same
 * place when I go and look. A random scene cannot be critiqued, only
 * re-rolled.
 */

/** Deterministic [0,1) from an integer. Sine-hash: no state, no seeding. */
export function hash01(i: number): number {
  const x = Math.sin(i * 127.1 + 311.7) * 43758.5453123;
  return x - Math.floor(x);
}

/** Deterministic [lo,hi) from an integer. */
export function hashRange(i: number, lo: number, hi: number): number {
  return lo + hash01(i) * (hi - lo);
}

/**
 * Latitude/longitude to a point on the unit sphere.
 *
 * North-positive, east-positive — the ordinary convention, and the ONLY place
 * in the scene that converts. The longitude offset puts lon 0 on the +Z face
 * so that rotating the globe by `-INDIA.lon` brings India to the camera.
 */
export function latLonToVec3(lat: number, lon: number, r = 1): [number, number, number] {
  const phi = (90 - lat) * (Math.PI / 180);
  const theta = (lon + 180) * (Math.PI / 180);
  return [
    -r * Math.sin(phi) * Math.cos(theta),
    r * Math.cos(phi),
    r * Math.sin(phi) * Math.sin(theta),
  ];
}

/**
 * What fraction of the canvas HEIGHT a sphere of radius r occupies, viewed
 * down a `fovDeg` lens from distance d.
 *
 * The visible silhouette of a sphere is NOT its diameter — the camera sees the
 * tangent circle, which subtends asin(r/d), so the half-angle is r/sqrt(d^2-r^2)
 * rather than r/d. At the distances used here the difference is about 2%, which
 * is the difference between "55-65% of the right-side visual area" being met
 * and being missed by a hair.
 *
 * This exists so the globe's size is a CALCULATION rather than a nudge: the
 * brief states a target as a percentage, and a constant picked by eye cannot be
 * checked against it. `describeSize` prints the answer.
 */
export function sphereHeightFraction(r: number, d: number, fovDeg: number): number {
  if (d <= r) return Infinity;
  const half = r / Math.sqrt(d * d - r * r);
  return half / Math.tan((fovDeg * Math.PI) / 360);
}

/** Smooth Hermite step, matching GLSL's smoothstep, for CPU-side falloffs. */
export function smoothstep(edge0: number, edge1: number, x: number): number {
  const t = Math.min(1, Math.max(0, (x - edge0) / (edge1 - edge0)));
  return t * t * (3 - 2 * t);
}

export function clamp(x: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, x));
}
