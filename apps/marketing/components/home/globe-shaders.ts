/**
 * The GLSL the hero globe is drawn with.
 *
 * Kept out of HeroGlobe.tsx because that file is already a scene graph, a
 * render loop and five performance guards, and shader source read in the middle
 * of it made all three harder to follow. Nothing here touches Three.js — these
 * are strings, and the component decides what to do with them.
 *
 * WHY SHADERS AT ALL, when the scene this replaced used PointsMaterial and
 * LineBasicMaterial. Three things the reference image has and a stock material
 * cannot give:
 *
 *   1. A globe that reads as a SPHERE. Flat-shaded dots at uniform brightness
 *      read as a disc of confetti. Dimming each point by how squarely it faces
 *      the camera is limb darkening, and it is what makes the edge curve away.
 *   2. An ATMOSPHERE. The old scene faked it with a flat radial sprite behind
 *      the globe, which sits at a fixed screen size and does not follow the
 *      silhouette. A fresnel term on a slightly larger shell does.
 *   3. Arcs that GLOW AND TRAVEL. A LineBasicMaterial is one pixel wide at one
 *      opacity; the pulse had to be a second object (a Points) chasing a
 *      sampled position along it. Here the ribbon, its fade at both ends, the
 *      comet head and its tail are one material and one uniform.
 *
 * All of it is per-fragment arithmetic on geometry that is already being
 * rasterised, so it costs fill rate rather than draw calls — and the scene is
 * capped at 30fps at a capped device pixel ratio precisely because fill rate is
 * the budget on the integrated GPUs this has to run on.
 */

/** Shared: hand the fragment stage a view-space normal and position, which is
 *  all any of the lighting terms below actually need. */
const SURFACE_VARYINGS = `
varying vec3 vNormal;
varying vec3 vView;
`;

const SURFACE_VERTEX = `
${SURFACE_VARYINGS}
void main() {
  vNormal = normalize(normalMatrix * normal);
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  vView = mv.xyz;
  gl_Position = projectionMatrix * mv;
}
`;

/**
 * The ocean-dark body of the planet.
 *
 * Opaque and depth-writing, so it is what occludes the far side of every point
 * cloud and every arc. The gradient is a function of how squarely the surface
 * faces the camera, not of a light position — the globe has no sun, and giving
 * it one would put a hard terminator across a shape whose job is to be legible.
 */
export const CORE_VERTEX = SURFACE_VERTEX;
export const CORE_FRAGMENT = `
uniform vec3 uCentre;
uniform vec3 uLimb;
${SURFACE_VARYINGS}
void main() {
  float facing = clamp(dot(vNormal, normalize(-vView)), 0.0, 1.0);
  gl_FragColor = vec4(mix(uLimb, uCentre, smoothstep(0.0, 0.9, facing)), 1.0);
}
`;

/**
 * The atmosphere.
 *
 * A slightly larger shell drawn BACK side with additive blending, so only the
 * part of it behind the planet's silhouette is visible and it reads as air
 * rather than a second sphere. `abs()` on the facing term is deliberate: with
 * back-face rendering the interpolated normal points away from the eye over
 * most of the shell, and without it the halo appears on the wrong side.
 */
export const ATMOSPHERE_VERTEX = SURFACE_VERTEX;
export const ATMOSPHERE_FRAGMENT = `
uniform vec3 uColor;
uniform float uPower;
uniform float uIntensity;
${SURFACE_VARYINGS}
void main() {
  float rim = 1.0 - abs(dot(vNormal, normalize(-vView)));
  gl_FragColor = vec4(uColor, pow(rim, uPower) * uIntensity);
}
`;

/**
 * The land point field — the continents.
 *
 * Each point carries its own size and colour, because the field is doing three
 * jobs at once: ordinary land, a warmer band over India, and the bright hubs
 * where the cities are.
 *
 * THE BACK HEMISPHERE IS DISCARDED IN THE SHADER rather than left to the depth
 * test. Points are billboards with no depth of their own, so a point on the far
 * side of the planet sits at the sphere's radius and the opaque core does hide
 * it — but only just, and at the silhouette it wins by a fraction of a pixel and
 * flickers. Discarding anything facing away is exact and costs nothing.
 */
export const LAND_VERTEX = `
attribute float aSize;
attribute vec3 aColor;
uniform float uScale;
varying vec3 vColor;
varying float vFacing;
void main() {
  vec3 n = normalize(normalMatrix * normalize(position));
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  vFacing = dot(n, normalize(-mv.xyz));
  vColor = aColor;
  gl_Position = projectionMatrix * mv;
  gl_PointSize = aSize * uScale / max(0.0001, -mv.z);
}
`;
export const LAND_FRAGMENT = `
varying vec3 vColor;
varying float vFacing;
void main() {
  if (vFacing < 0.04) discard;
  // A round, soft-edged dot. Without this every point is a hard square and the
  // continents read as a mosaic.
  float r = length(gl_PointCoord - vec2(0.5));
  if (r > 0.5) discard;
  float disc = smoothstep(0.5, 0.08, r);
  // Limb darkening: points near the silhouette are seen at a glancing angle and
  // fade, which is what makes a flat field of dots read as a sphere.
  //
  // GENTLY. At (0.16 + 0.84 * limb) over a 0.04-0.42 ramp the outer third of
  // every continent dissolved, so Africa and East Asia were ghosts at the
  // edges — the reference keeps its coastlines lit almost to the silhouette
  // and lets the atmosphere do the rounding instead. The floor is what matters
  // here: a point at the limb keeps half its brightness rather than a sixth.
  float limb = smoothstep(0.02, 0.3, vFacing);
  gl_FragColor = vec4(vColor, disc * (0.48 + 0.52 * limb));
}
`;

/**
 * The city hubs.
 *
 * Same discard rules as the land field, but each hub is a soft halo with a hot
 * centre and it breathes. The phase is per-point so twenty hubs do not pulse in
 * unison, which reads as a flashing light rather than a living network.
 */
export const HUB_VERTEX = `
attribute float aSize;
attribute float aPhase;
uniform float uScale;
uniform float uTime;
varying float vFacing;
varying float vGlow;
void main() {
  vec3 n = normalize(normalMatrix * normalize(position));
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  vFacing = dot(n, normalize(-mv.xyz));
  float breathe = 0.78 + 0.22 * sin(uTime * 1.7 + aPhase * 6.2831);
  vGlow = breathe;
  gl_Position = projectionMatrix * mv;
  gl_PointSize = aSize * breathe * uScale / max(0.0001, -mv.z);
}
`;
export const HUB_FRAGMENT = `
uniform vec3 uCore;
uniform vec3 uHalo;
varying float vFacing;
varying float vGlow;
void main() {
  if (vFacing < 0.05) discard;
  float r = length(gl_PointCoord - vec2(0.5));
  if (r > 0.5) discard;
  float halo = smoothstep(0.5, 0.0, r);
  float core = smoothstep(0.17, 0.0, r);
  float limb = smoothstep(0.05, 0.4, vFacing);
  vec3 c = mix(uHalo, uCore, core);
  gl_FragColor = vec4(c, (halo * 0.5 + core * 0.9) * vGlow * limb);
}
`;

/**
 * A network arc, and the pulse travelling along it.
 *
 * Drawn on a tube, so `uv.x` runs 0 to 1 along the path and the whole effect is
 * a function of that one coordinate:
 *
 *   body   fades in and out at both ends, so an arc emerges from its city
 *          rather than starting abruptly in mid-air;
 *   trail  an exponential decay BEHIND the head — the further back, the dimmer;
 *   spark  a tight bright core at the head itself.
 *
 * `fract()` on the head means an arc that has finished simply starts again;
 * `uPhase` staggers the twelve arcs so they are not one synchronised wave.
 *
 * Additively blended and not depth-writing, but it DOES depth-test, so the half
 * of an arc that passes behind the planet is correctly hidden by the core.
 */
export const ARC_VERTEX = `
varying float vU;
void main() {
  vU = uv.x;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;
export const ARC_FRAGMENT = `
uniform vec3 uColor;
uniform vec3 uSpark;
uniform float uTime;
uniform float uPhase;
uniform float uSpeed;
uniform float uBase;
varying float vU;
void main() {
  float body = smoothstep(0.0, 0.16, vU) * smoothstep(1.0, 0.84, vU);
  float head = fract(uTime * uSpeed + uPhase);
  float behind = head - vU;
  float trail = behind >= 0.0 ? exp(-behind * 13.0) : 0.0;
  float spark = exp(-abs(behind) * 55.0);
  vec3 c = mix(uColor, uSpark, clamp(spark + trail * 0.35, 0.0, 1.0));
  gl_FragColor = vec4(c, body * (uBase + 0.85 * trail + 0.9 * spark));
}
`;
