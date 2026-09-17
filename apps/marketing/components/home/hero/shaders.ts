/**
 * Every shader in the hero scene.
 *
 * ⚠️ NEVER WRITE A BACKTICK IN THIS FILE, COMMENTS INCLUDED. Each shader is a
 * JavaScript template literal, so a stray backtick terminates the string and
 * the rest of the file becomes syntax. The failure is a TS1005 pointing at a
 * line hundreds down from the real one, which cost an hour the first time.
 * Quote GLSL identifiers in comments with plain words, never with code marks.
 *
 * They live together rather than beside the meshes they belong to because the
 * varyings have to agree across four programs: the surface, the atmosphere and
 * both line materials all read the same view vector, and a varying renamed in
 * one place and not another links cleanly and renders wrong.
 */

/** Shared by the surface and the atmosphere so the rim maths cannot diverge. */
const VIEW_VARYINGS = `
varying vec3 vNormal;
varying vec3 vView;
`;

/**
 * Fade anything continuous out before it reaches the edge of the canvas.
 *
 * ⚠️ THE CANVAS IS NOT THE VIEWPORT, AND THIS IS THE CONSEQUENCE. It is hung
 * 134% x 138% of a 640px grid cell, which at 1440x900 is 858x994 starting at
 * x=552 — so it has HARD EDGES a third of the way across the hero, and the
 * page's own background continues past them. Measured: six of the seven
 * orbital paths have a semi-major axis that reaches beyond the canvas's left
 * boundary at x=-1.221 in scene coordinates.
 *
 * What that looked like was a pale horizontal bar floating to the left of the
 * planet, stopping dead in a vertical line. It is the widest orbit's turning
 * point — where the ellipse doubles back, the ribbon is briefly seen along its
 * own length and reads as a patch rather than a line — sliced off mid-stroke.
 *
 * Shrinking the orbits would fix it and is the wrong fix: §8 asks for paths
 * that "extend farther into the surrounding space", and the same cut would
 * come back on any viewport where the canvas lands differently. Fading in
 * SCREEN space solves it for every element, width and zoom at once. Points and
 * sprites do not need it — a star that vanishes at the boundary is one star,
 * not a line — so only the two continuous line materials carry it.
 */
const EDGE_FADE = `
uniform vec2 uResolution;
uniform float uEdge;
float edgeFade() {
  vec2 d = min(gl_FragCoord.xy, uResolution - gl_FragCoord.xy);
  return smoothstep(0.0, uEdge, d.x) * smoothstep(0.0, uEdge, d.y);
}
`;

// ── Earth surface ────────────────────────────────────────────────────────────

export const EARTH_VERTEX = `
varying vec2 vUv;
${VIEW_VARYINGS}
void main() {
  vUv = uv;
  vNormal = normalize(normalMatrix * normal);
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  vView = mv.xyz;
  gl_Position = projectionMatrix * mv;
}
`;

/**
 * The night Earth.
 *
 * Six terms, in the order the brief's own lighting hierarchy puts them (§19),
 * and the ORDER is the design: the base is almost black, everything visible is
 * added on top, so nothing can wash the planet out by accident.
 *
 * 1. base        land/ocean mix, both very dark
 * 2. terminator  a soft day/night falloff from a fixed view-space sun
 * 3. limb        darkening toward the silhouette, which is what reads as a ball
 * 4. lights      the city network, ADDED, gated to the night side
 * 5. rim         a fresnel atmosphere edge, ADDED
 * 6. flare       a warm limb kiss where the sun grazes the edge
 *
 * THE LIGHTS ARE GATED BUT NOT EXTINGUISHED. A physical night Earth shows its
 * cities only in darkness, and a strict gate would put half this globe in
 * plain shadow with nothing in it. The reference shows lights across the whole
 * visible face with the terminator reading as a gradient over them, so the
 * gate goes to uNightFloor rather than to zero.
 */
export const EARTH_FRAGMENT = `
uniform sampler2D uLand;
uniform sampler2D uLights;
uniform vec3 uOcean;
uniform vec3 uLandCol;
uniform vec3 uRim;
uniform vec3 uSun;
uniform float uShadow;
uniform float uLightGain;
uniform float uNightFloor;
varying vec2 vUv;
${VIEW_VARYINGS}

void main() {
  vec3 n = normalize(vNormal);
  vec3 sun = normalize(uSun);

  float land = texture2D(uLand, vUv).r;
  vec3 lights = texture2D(uLights, vUv).rgb;

  // How squarely this fragment faces the camera. 1 at the centre of the disc,
  // 0 exactly on the silhouette.
  float facing = clamp(dot(n, normalize(-vView)), 0.0, 1.0);

  // Day/night. The lower edge is below zero so the terminator is a wide soft
  // band rather than a hard line, which is what a thick atmosphere does.
  float lit = smoothstep(-0.55, 0.95, dot(n, sun));

  vec3 col = mix(uOcean, uLandCol, land);
  col *= mix(uShadow, 1.0, lit);
  col *= mix(0.42, 1.0, smoothstep(0.0, 0.72, facing));

  // Cities. Squared facing term so the lights fade before the silhouette and
  // do not fringe the limb with warm pixels.
  float nightGate = mix(1.0, uNightFloor, lit);
  col += lights * uLightGain * nightGate * smoothstep(0.0, 0.30, facing) * facing;

  // Atmosphere seen through the body of the planet.
  //
  // The exponent is 4.4 and was 2.9, which is the difference between a rim and
  // a wash. pow(1-facing, 2.9) is still at a fifth of its peak a quarter of
  // the way in from the silhouette, so on a sphere this large it laid blue
  // over everything near the edge and Africa — which sits on the left limb
  // from this viewpoint — came out grey-blue instead of dark. A tighter
  // falloff keeps the same brightness exactly at the edge, where the reference
  // has it, and gives the disc back to the surface.
  float rim = pow(1.0 - facing, 4.4);
  col += uRim * rim * (0.40 + 0.60 * lit);

  gl_FragColor = vec4(col, 1.0);
}
`;

// ── Atmosphere shell ─────────────────────────────────────────────────────────

export const ATMOSPHERE_VERTEX = EARTH_VERTEX.replace("varying vec2 vUv;", "").replace(
  "vUv = uv;",
  ""
);

/**
 * The glow OUTSIDE the silhouette.
 *
 * Drawn on a slightly larger back-faced sphere with additive blending, so what
 * reaches the screen is only the ring beyond the planet's own edge. The alpha
 * is a band rather than a plain fresnel: a fresnel alone peaks exactly at the
 * silhouette and falls away outward, which draws a hard bright hoop. Two
 * smoothsteps multiplied give a soft shell with a falloff on both sides.
 *
 * THE SUN TERM HAS A FLOOR AND THAT FLOOR IS LOAD-BEARING. With alpha running
 * as band * (1.0 + lit) the shaded half of the rim stayed at full strength and
 * the whole thing read as a drawn hoop rather than a lit limb. The floor is
 * what makes it an atmosphere.
 */
export const ATMOSPHERE_FRAGMENT = `
uniform vec3 uTint;
uniform vec3 uSun;
uniform float uIntensity;
${VIEW_VARYINGS}

void main() {
  vec3 n = normalize(vNormal);
  float facing = clamp(dot(n, normalize(-vView)), 0.0, 1.0);

  float band = smoothstep(0.0, 0.42, facing) * (1.0 - smoothstep(0.30, 0.92, facing));
  float lit = smoothstep(-0.7, 0.85, dot(n, normalize(uSun)));

  gl_FragColor = vec4(uTint, band * uIntensity * (0.42 + lit * 1.5));
}
`;

// ── Orbital paths ────────────────────────────────────────────────────────────

/**
 * A trajectory, dimmed where it runs behind the planet.
 *
 * DEPTH TESTING ALONE IS NOT ENOUGH. The globe is opaque, so the far half of
 * an orbit is hidden by the depth buffer wherever it passes across the disc —
 * but the parts that clear the disc into open space read at full strength, and
 * a path at the same brightness whether it is 2 units in front or 2 behind is
 * what makes a scene look flat. So the depth is carried in a varying and the
 * far side is dimmed explicitly. That is the difference between an orbit
 * OCCLUDED by the planet and an orbit that is BEHIND it.
 *
 * uv.x runs 0..1 along the path, which gives the sweep: a trajectory that is
 * uniformly bright all the way round reads as a drawn ellipse, and one that
 * fades reads as something travelling.
 */
export const ORBIT_VERTEX = `
uniform float uCameraZ;
varying float vDepth;
varying vec2 vUv;
void main() {
  vUv = uv;
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  // 0 at the camera-facing extreme, 1 at the far extreme, roughly.
  vDepth = clamp((-mv.z - (uCameraZ - 1.6)) / 3.2, 0.0, 1.0);
  gl_Position = projectionMatrix * mv;
}
`;

export const ORBIT_FRAGMENT = `
uniform vec3 uColor;
uniform float uOpacity;
uniform float uSweep;
varying float vDepth;
varying vec2 vUv;
${EDGE_FADE}

void main() {
  // Behind the planet: dimmer and cooler.
  float depthFade = mix(1.0, 0.28, vDepth);

  // One soft pass round the ellipse, so the path has a head and a tail.
  float s = 0.55 + 0.45 * sin((vUv.x + uSweep) * 6.2831853);
  s = 0.35 + 0.65 * s;

  gl_FragColor = vec4(uColor, uOpacity * depthFade * s * edgeFade());
}
`;

// ── Network ──────────────────────────────────────────────────────────────────

/**
 * The mesh over the surface.
 *
 * Same depth dimming as the orbits and for the same reason, but with a
 * stronger far-side cut: these links sit close to the sphere, so the ones on
 * the back are seen through the whole planet and should be nearly gone.
 * Per-vertex alpha lets one draw call carry links of different strengths.
 */
export const NETWORK_VERTEX = `
uniform float uCameraZ;
attribute float aAlpha;
varying float vDepth;
varying float vAlpha;
void main() {
  vAlpha = aAlpha;
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  vDepth = clamp((-mv.z - (uCameraZ - 1.2)) / 2.4, 0.0, 1.0);
  gl_Position = projectionMatrix * mv;
}
`;

export const NETWORK_FRAGMENT = `
uniform vec3 uColor;
uniform float uOpacity;
varying float vDepth;
varying float vAlpha;
${EDGE_FADE}
void main() {
  gl_FragColor = vec4(uColor, uOpacity * vAlpha * mix(1.0, 0.12, vDepth) * edgeFade());
}
`;

// ── Points: city nodes, orbit nodes, stars ───────────────────────────────────

/**
 * A point sized in WORLD units rather than pixels.
 *
 * gl_PointSize is in device pixels, so a constant makes near and far points
 * identical and kills the perspective. Dividing a world-space size by view
 * depth restores it. uScale carries (canvasHeightInDevicePixels / 2) / tan(fov/2)
 * so the arithmetic matches the projection the rest of the scene uses; the
 * caller recomputes it on resize.
 */
export const POINT_VERTEX = `
uniform float uScale;
attribute float aSize;
attribute float aGlow;
attribute vec3 aColor;
varying float vGlow;
varying vec3 vColor;
void main() {
  vGlow = aGlow;
  vColor = aColor;
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  gl_PointSize = max(1.0, aSize * uScale / max(0.001, -mv.z));
  gl_Position = projectionMatrix * mv;
}
`;

/** A soft round dot. Squared falloff reads as a glow rather than a disc. */
export const POINT_FRAGMENT = `
uniform float uOpacity;
varying float vGlow;
varying vec3 vColor;
void main() {
  vec2 d = gl_PointCoord - vec2(0.5);
  float r = length(d) * 2.0;
  if (r > 1.0) discard;
  float a = pow(1.0 - r, 2.2);
  gl_FragColor = vec4(vColor, a * vGlow * uOpacity);
}
`;

/**
 * A star. Flatter core than a node, with a faint cross so the brighter ones
 * read as stars rather than as dust. The cross is cheap: two axis-aligned
 * bands, which at two or three pixels across is all a star ever is.
 */
export const STAR_FRAGMENT = `
uniform float uOpacity;
varying float vGlow;
varying vec3 vColor;
void main() {
  vec2 d = gl_PointCoord - vec2(0.5);
  float r = length(d) * 2.0;
  if (r > 1.0) discard;
  float core = pow(1.0 - r, 3.0);
  float cross = max(
    smoothstep(0.10, 0.0, abs(d.x)) * smoothstep(1.0, 0.0, abs(d.y) * 2.0),
    smoothstep(0.10, 0.0, abs(d.y)) * smoothstep(1.0, 0.0, abs(d.x) * 2.0)
  );
  float a = core + cross * 0.35 * vGlow;
  gl_FragColor = vec4(vColor, clamp(a, 0.0, 1.0) * vGlow * uOpacity);
}
`;

// ── Billboards: the sun flare and the background haze ────────────────────────

export const SPRITE_VERTEX = `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

/**
 * The warm burst where the sun grazes the limb.
 *
 * A round core plus a horizontal streak, which is what a real anamorphic lens
 * does and what the reference shows. Deliberately NOT a lens-flare chain of
 * coloured rings down the frame: §27 rules out excessive neon and a ring chain
 * would cross the hero copy.
 */
export const FLARE_FRAGMENT = `
uniform vec3 uColor;
uniform float uIntensity;
varying vec2 vUv;
void main() {
  vec2 d = (vUv - 0.5) * 2.0;
  float core = pow(max(0.0, 1.0 - length(d)), 3.4);
  float streak = pow(max(0.0, 1.0 - abs(d.x) * 0.55), 6.0)
               * pow(max(0.0, 1.0 - abs(d.y) * 7.5), 3.0);
  float a = core + streak * 0.55;
  gl_FragColor = vec4(uColor, clamp(a, 0.0, 1.0) * uIntensity);
}
`;

/**
 * The cosmic haze behind the planet.
 *
 * A single very soft radial wash. §11 asks for "extremely restrained" nebula
 * and §12 explicitly forbids the purple galaxy the earlier concept had, so
 * this carries one cool tint at low intensity and no structure at all — its
 * whole job is to stop the background being flat black behind the globe.
 */
export const HAZE_FRAGMENT = `
uniform vec3 uColor;
uniform float uIntensity;
varying vec2 vUv;
void main() {
  vec2 d = (vUv - 0.5) * 2.0;
  float a = pow(max(0.0, 1.0 - length(d)), 2.6);
  gl_FragColor = vec4(uColor, a * uIntensity);
}
`;

// ── Distant bodies ───────────────────────────────────────────────────────────

/**
 * A moon or a far planet, and an asteroid.
 *
 * One program for both: a lambert term against the same view-space sun the
 * Earth uses, a dark ambient floor so the unlit side is a silhouette rather
 * than a hole, and a thin terminator rim. §13 requires these stay subtle, so
 * there is no texture and no specular — the shape and the lit edge are the
 * whole read at the size they appear.
 */
export const BODY_VERTEX = EARTH_VERTEX.replace("varying vec2 vUv;", "").replace(
  "vUv = uv;",
  ""
);

export const BODY_FRAGMENT = `
uniform vec3 uColor;
uniform vec3 uSun;
uniform float uAmbient;
uniform float uRimGain;
${VIEW_VARYINGS}
void main() {
  vec3 n = normalize(vNormal);
  float lit = smoothstep(-0.25, 0.85, dot(n, normalize(uSun)));
  float facing = clamp(dot(n, normalize(-vView)), 0.0, 1.0);
  vec3 col = uColor * mix(uAmbient, 1.0, lit);
  col += vec3(0.40, 0.58, 0.95) * pow(1.0 - facing, 3.0) * uRimGain * lit;
  gl_FragColor = vec4(col, 1.0);
}
`;
