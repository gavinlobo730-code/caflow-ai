/**
 * The GLSL the hero globe is drawn with.
 *
 * Kept out of HeroGlobe.tsx because that file is already a scene graph and a
 * composition, and shader source read in the middle of it made both harder to
 * follow. Nothing here touches Three.js — these are strings, and the component
 * decides what to do with them.
 *
 * ⚠️ NEVER WRITE A BACKTICK IN THIS FILE, comments included. Every shader below
 * is a JS template literal, and a backtick inside one terminates the string —
 * the build then fails somewhere else entirely with "TS1005: ',' expected",
 * which is what happened on 16-09-2026 to the word uSun quoted in a comment.
 *
 * WHY SHADERS AT ALL, when stock PointsMaterial / LineBasicMaterial exist.
 * Five things the reference image has and a stock material cannot give:
 *
 *   1. A globe that reads as a SPHERE. Flat-shaded dots at uniform brightness
 *      read as a disc of confetti. Dimming each point by how squarely it faces
 *      the camera is limb darkening, and it is what makes the edge curve away.
 *   2. A TERMINATOR. The brief asks for an Earth "emerging from darkness", and
 *      that is a direction the light comes from, applied to every layer at
 *      once — the ocean, the city lights and the atmosphere.
 *   3. An ATMOSPHERE that follows the silhouette. A flat radial sprite sits at
 *      a fixed screen size and does not; a fresnel term on a larger shell does.
 *   4. ORBITS THAT KNOW WHERE THEY ARE. An orbital path at one brightness all
 *      the way round reads as a hoop bolted onto the planet. These dim on the
 *      half that passes behind it, carry a gradient along their own length,
 *      and fade out before they reach the edge of the canvas rather than being
 *      guillotined by it.
 *   5. Arcs that glow and carry a travelling head. A LineBasicMaterial is one
 *      pixel wide at one opacity; the head had to be a second object chasing a
 *      sampled position along it. Here the ribbon, its fade at both ends, the
 *      head and its tail are one material and one uniform.
 *
 * EVERY TIME UNIFORM IS STILL HERE AND THE SCENE IS STATIC. `uTime` stays on
 * the arc, hub and orbit materials, and each already produces a fixed, varied
 * state at t = 0 — a spark parked partway along each arc, hubs at different
 * brightnesses, orbits with their bright arc in different places. Animation is
 * then one line in the component (advance uTime, render) rather than a rewrite
 * of the look, which is what the owner asked for on 17-09-2026: build the
 * static scene cleanly so animation can be added later without rebuilding it.
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
 * cloud, every arc and the half of every orbit that passes behind it.
 *
 * TWO GRADIENTS, NOT ONE. The first is a function of how squarely the surface
 * faces the camera and rounds the disc. The second is the terminator — the side
 * the light is on lifts a little out of black, and that is most of what stops a
 * night-side Earth reading as a flat cut-out. It is deliberately gentle: this
 * is a NIGHT globe, and a hard day side would put the city lights in daylight.
 */
export const CORE_VERTEX = SURFACE_VERTEX;
export const CORE_FRAGMENT = `
uniform vec3 uCentre;
uniform vec3 uLimb;
uniform vec3 uSun;
uniform float uShadow;
${SURFACE_VARYINGS}
void main() {
  vec3 n = normalize(vNormal);
  float facing = clamp(dot(n, normalize(-vView)), 0.0, 1.0);
  vec3 base = mix(uLimb, uCentre, smoothstep(0.0, 0.9, facing));
  float lit = smoothstep(-0.45, 0.95, dot(n, normalize(uSun)));
  gl_FragColor = vec4(base * mix(uShadow, 1.0, lit), 1.0);
}
`;

/**
 * The atmosphere.
 *
 * A slightly larger shell drawn BACK side with additive blending, so only the
 * part of it outside the planet's silhouette is visible and it reads as air
 * rather than a second sphere. abs() on the facing term is deliberate: with
 * back-face rendering the interpolated normal points away from the eye over
 * most of the shell, and without it the halo appears on the wrong side.
 *
 * THE RIM IS ELECTRIC BLUE AND THE GOLD IS A WHISPER. The brief (17-09-2026) is
 * explicit that the globe is cool and that the only warmth in the picture is
 * around India — so the lit edge runs blue toward a cool WHITE, and the warm
 * term is squared so what little there is of it sits at the very brightest
 * sliver of the limb instead of spreading halfway round the planet. The
 * previous revision ran this the other way and the result was an amber hoop.
 */
export const ATMOSPHERE_VERTEX = SURFACE_VERTEX;
export const ATMOSPHERE_FRAGMENT = `
uniform vec3 uColor;
uniform vec3 uHot;
uniform vec3 uWarm;
uniform vec3 uSun;
uniform float uPower;
uniform float uIntensity;
uniform float uWarmGain;
${SURFACE_VARYINGS}
void main() {
  float rim = 1.0 - abs(dot(normalize(vNormal), normalize(-vView)));
  float band = pow(rim, uPower);

  // smoothstep rather than a raw dot: the daylight edge on a real limb is a
  // narrow band, and a linear falloff spreads the highlight halfway round the
  // sphere. The WINDOW is what decides whether this is a sunrise or a ring.
  float lit = smoothstep(0.34, 0.98, dot(normalize(vNormal), normalize(uSun)));

  vec3 tint = mix(uColor, uHot, lit);
  tint = mix(tint, uWarm, lit * lit * uWarmGain);

  // THE FLOOR IS 0.45, NOT 1.0, AND THAT IS THE DIFFERENCE BETWEEN A LIMB AND
  // A HOOP. The first draft ran this at (1.0 + lit * 1.2), so the shaded side's
  // rim was at full strength and the ring was the brightest thing in the frame
  // all the way round — a glowing blue band bolted to the planet, exactly what
  // the brief rules out. A lit atmosphere is nearly invisible on the night side
  // and fierce on the day side; this is that ratio.
  gl_FragColor = vec4(tint, band * uIntensity * (0.45 + lit * 1.7));
}
`;

/**
 * The land point field — the continents, as city lights.
 *
 * Each point carries its own size and colour, because the field is doing four
 * jobs at once: ordinary inland land, a brighter coastline, a warm band over
 * India, and the density variation that makes a night-lights composite look
 * like one rather than like a uniform stipple. All four are decided on the CPU,
 * where the latitude and longitude are in hand; this shader only lights them.
 *
 * THE BACK HEMISPHERE IS DISCARDED HERE rather than left to the depth test.
 * Points are billboards with no depth of their own, so a point on the far side
 * sits at the sphere's radius and the opaque core does hide it — but only just,
 * and at the silhouette it wins by a fraction of a pixel and flickers.
 * Discarding anything facing away is exact and costs nothing.
 */
export const LAND_VERTEX = `
attribute float aSize;
attribute vec3 aColor;
uniform float uScale;
uniform vec3 uSun;
varying vec3 vColor;
varying float vFacing;
varying float vLit;
varying float vWorldY;
void main() {
  vec3 n = normalize(normalMatrix * normalize(position));
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  vFacing = dot(n, normalize(-mv.xyz));
  vColor = aColor;

  // How much of the light this point catches. A WIDE window on purpose: a
  // narrow one puts a hard terminator across the continents, and the picture
  // wants a planet emerging from darkness rather than one cut in half.
  vLit = smoothstep(-0.40, 0.92, dot(n, normalize(uSun)));

  // World height, so the mirrored copy below can fade out with depth. It is
  // the only way the reflection knows how far under the globe it has got.
  vWorldY = (modelMatrix * vec4(position, 1.0)).y;

  gl_Position = projectionMatrix * mv;
  gl_PointSize = aSize * uScale / max(0.0001, -mv.z);
}
`;
export const LAND_FRAGMENT = `
uniform float uOpacity;
uniform float uShadow;
uniform float uFadeFrom;
uniform float uFadeTo;
varying vec3 vColor;
varying float vFacing;
varying float vLit;
varying float vWorldY;
void main() {
  if (vFacing < 0.035) discard;
  // A round, soft-edged dot. Without this every point is a hard square and the
  // continents read as a mosaic.
  float r = length(gl_PointCoord - vec2(0.5));
  if (r > 0.5) discard;
  float disc = smoothstep(0.5, 0.06, r);

  // Limb darkening, GENTLY. The floor is what matters: a point at the very edge
  // keeps half its brightness rather than a sixth, so coastlines stay legible
  // almost to the silhouette and the atmosphere does the rounding instead.
  float limb = smoothstep(0.02, 0.32, vFacing);

  // The terminator. Lights on the shaded side keep uShadow of their brightness
  // rather than going out — this is a night-lights Earth, so the unlit half is
  // exactly where the cities read strongest, only dimmer overall.
  vec3 c = vColor * mix(uShadow, 1.0, vLit);
  c *= 1.0 + vLit * vLit * 0.30;

  // uFadeTo equal to uFadeFrom disables the fade, which is what the real globe
  // passes; only the mirrored copy sets a window.
  float depth = uFadeTo == uFadeFrom
    ? 1.0
    : clamp((vWorldY - uFadeTo) / (uFadeFrom - uFadeTo), 0.0, 1.0);

  gl_FragColor = vec4(c, disc * (0.5 + 0.5 * limb) * uOpacity * depth);
}
`;

/**
 * The city hubs.
 *
 * Same discard rules as the land field, but each hub is a soft halo with a hot
 * centre. aPhase is per-point, so at a FIXED uTime the twenty hubs sit at
 * twenty different brightnesses — which is what a static frame needs — and
 * advancing uTime later turns the same expression into a breath.
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
  float breathe = 0.74 + 0.26 * sin(uTime * 1.7 + aPhase * 6.2831853);
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
 * A network arc, and the head travelling along it.
 *
 * Drawn on a tube, so uv.x runs 0 to 1 along the path and the whole effect is a
 * function of that one coordinate:
 *
 *   body   fades in and out at both ends, so an arc emerges from its city
 *          rather than starting abruptly in mid-air;
 *   trail  an exponential decay BEHIND the head — the further back, the dimmer;
 *   spark  a tight bright core at the head itself.
 *
 * fract() on the head means an arc that has finished simply starts again;
 * uPhase staggers the arcs, and at uTime = 0 it is also what parks each head at
 * a different point along its own path. That is the brief's static reading of
 * this element: "the particles should simply be positioned as if they are
 * travelling along those paths."
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

/**
 * An orbital path.
 *
 * THREE THINGS A TorusGeometry WITH A MeshBasicMaterial CANNOT DO, and all
 * three are why the previous four rings read as a diagram rather than as a
 * system:
 *
 *   1. KNOW WHETHER IT IS IN FRONT. The depth buffer hides the part of an orbit
 *      that passes behind the planet, but the part that clears the silhouette
 *      on the far side is still drawn at full brightness, so the ring reads as
 *      a flat hoop laid over the image. vDepth is view-space distance and the
 *      far half is dimmed to a fifth, which is what gives the orbit a near side
 *      and a far side.
 *   2. VARY ALONG ITS OWN LENGTH. A path at one opacity all the way round is a
 *      drawn circle. One sine over uv.x gives it a bright stretch and a faint
 *      one, and uPhase puts each orbit's bright stretch somewhere different.
 *   3. STOP WITHOUT A HARD EDGE. The globe is now large enough that the outer
 *      orbits genuinely run off the canvas, which is right — but a bright line
 *      guillotined at the frame edge is not. uResolution is in the shader for
 *      exactly this: the last tenth of the frame fades to nothing, so an orbit
 *      leaves the picture instead of being cut off by it.
 */
export const ORBIT_VERTEX = `
varying float vU;
varying float vDepth;
void main() {
  vU = uv.x;
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  vDepth = -mv.z;
  gl_Position = projectionMatrix * mv;
}
`;
export const ORBIT_FRAGMENT = `
uniform vec3 uColor;
uniform vec3 uHot;
uniform float uOpacity;
uniform float uCentreDepth;
uniform float uPhase;
uniform float uSweep;
uniform vec2 uResolution;
uniform float uEdge;
varying float vU;
varying float vDepth;
void main() {
  float front = 1.0 - smoothstep(uCentreDepth - 0.85, uCentreDepth + 0.85, vDepth);
  float depthDim = mix(0.18, 1.0, front);

  float sweep = mix(1.0, 0.46 + 0.54 * sin(vU * 6.2831853 + uPhase), uSweep);

  vec2 uv = gl_FragCoord.xy / uResolution;
  float edge =
    smoothstep(0.0, uEdge, uv.x) * smoothstep(1.0, 1.0 - uEdge, uv.x) *
    smoothstep(0.0, uEdge, uv.y) * smoothstep(1.0, 1.0 - uEdge, uv.y);

  vec3 c = mix(uColor, uHot, front * sweep * 0.5);
  gl_FragColor = vec4(c, uOpacity * depthDim * sweep * edge);
}
`;

/**
 * The network laid over the Earth's surface — the fine lines between the land
 * nodes.
 *
 * A LineBasicMaterial with vertex colours would draw these, and it would draw
 * them WRONG in one specific way: the lines that reach the silhouette would be
 * at full brightness there, and lines on the shadow side would be as bright as
 * lines on the lit side. Both are things the eye reads as "flat", and the whole
 * point of this layer is that it should look wrapped around a sphere.
 *
 * So the same two terms the land field uses — the facing angle and the
 * terminator — are applied here. They cannot be baked into the vertex colours
 * even though the globe is currently posed and still: bake them and the first
 * frame of rotation is wrong.
 */
export const NETWORK_VERTEX = `
attribute vec3 aColor;
uniform vec3 uSun;
varying vec3 vColor;
varying float vFacing;
varying float vLit;
void main() {
  vec3 n = normalize(normalMatrix * normalize(position));
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  vFacing = dot(n, normalize(-mv.xyz));
  vLit = smoothstep(-0.40, 0.92, dot(n, normalize(uSun)));
  vColor = aColor;
  gl_Position = projectionMatrix * mv;
}
`;
export const NETWORK_FRAGMENT = `
uniform float uOpacity;
uniform float uShadow;
varying vec3 vColor;
varying float vFacing;
varying float vLit;
void main() {
  if (vFacing < 0.02) discard;
  float limb = smoothstep(0.0, 0.36, vFacing);
  gl_FragColor = vec4(vColor * mix(uShadow, 1.0, vLit), uOpacity * limb);
}
`;

/**
 * A billboard point with a world-space size — the shared vertex stage for the
 * orbital nodes, the drifting motes and the background star field.
 *
 * World units rather than pixels, converted here, for the reason written out at
 * LAND_DOT_WORLD in HeroGlobe.tsx: a point size scaled by something convenient
 * like the canvas height is what drew the first version of this planet as one
 * solid white disc.
 */
export const SPRITE_POINT_VERTEX = `
attribute float aSize;
attribute float aGlow;
attribute vec3 aColor;
uniform float uScale;
varying float vGlow;
varying vec3 vColor;
void main() {
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  vGlow = aGlow;
  vColor = aColor;
  gl_Position = projectionMatrix * mv;
  gl_PointSize = aSize * uScale / max(0.0001, -mv.z);
}
`;

/**
 * A luminous node sitting on an orbital path: a hot core inside a soft halo.
 *
 * Deliberately NOT the hub shader, though they look alike. That one discards on
 * dot(normalize(position), view), which is a surface normal for a point ON the
 * sphere and is nothing of the sort for a point orbiting outside it — a node at
 * the left edge of a wide orbit has that dot near zero and would vanish exactly
 * where it is most visible. These depth-test instead, so the planet hides the
 * ones genuinely behind it and nothing else does.
 */
export const NODE_FRAGMENT = `
varying float vGlow;
varying vec3 vColor;
void main() {
  float r = length(gl_PointCoord - vec2(0.5));
  if (r > 0.5) discard;
  float halo = smoothstep(0.5, 0.0, r);
  float core = smoothstep(0.16, 0.0, r);
  gl_FragColor = vec4(vColor + core * 0.55, (halo * 0.42 + core * 0.95) * vGlow);
}
`;

/** The background star field and the drifting motes: a soft dot, nothing more. */
export const STAR_FRAGMENT = `
varying float vGlow;
varying vec3 vColor;
void main() {
  float r = length(gl_PointCoord - vec2(0.5));
  if (r > 0.5) discard;
  gl_FragColor = vec4(vColor, smoothstep(0.5, 0.0, r) * vGlow);
}
`;
