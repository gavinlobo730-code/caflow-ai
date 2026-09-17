"use client";

import { useEffect, useRef, useState } from "react";
import { loadThree, canRunGlobe } from "./three-loader";
import { CITIES, ARCS, INDIA_CENTRE } from "./geography";
import { isLand } from "./landmask";
import {
  CORE_VERTEX,
  CORE_FRAGMENT,
  ATMOSPHERE_VERTEX,
  ATMOSPHERE_FRAGMENT,
  LAND_VERTEX,
  LAND_FRAGMENT,
  NETWORK_VERTEX,
  NETWORK_FRAGMENT,
  HUB_VERTEX,
  HUB_FRAGMENT,
  ARC_VERTEX,
  ARC_FRAGMENT,
  ORBIT_VERTEX,
  ORBIT_FRAGMENT,
  SPRITE_POINT_VERTEX,
  NODE_FRAGMENT,
  STAR_FRAGMENT,
} from "./globe-shaders";

/**
 * The hero globe.
 *
 * ── WHAT CHANGED ON 17 SEPTEMBER 2026, AND WHY ────────────────────────────
 * Owner brief: "The current globe is too small and too flat. Do not solve this
 * simply by increasing its CSS width. The actual visual complexity and depth
 * need to increase." And: "Do NOT make it interactive or animated yet … first
 * we need to get the STATIC visual looking exceptional."
 *
 * Both halves of that are structural, so both are answered structurally.
 *
 * ── 1. THE SCENE IS DRAWN ONCE ────────────────────────────────────────────
 * There is no requestAnimationFrame loop. `draw()` renders a single frame, and
 * runs again only when the stage resizes. That is not a lesser version of the
 * animated scene — it is what lets everything else here be affordable:
 *
 *   - the render resolution goes UP rather than down (RENDER_DPR is now 2, and
 *     was 1.25) because a sharp frame costs once instead of thirty times a
 *     second. That single change does more for "premium" than any amount of
 *     colour tuning: at 1.25 the one-pixel city lights were being resampled and
 *     the continents read as a smear;
 *   - the land field can be twice as dense, the orbits can be real tube
 *     geometry at 240 segments, and a surface network can be drawn on top of
 *     both, none of which was affordable inside a 33ms budget;
 *   - the scroll-quiet window, the frame cap and the viewport check are all
 *     moot and are gone. A scene that never draws cannot be the reason the hero
 *     drops frames, which is what the whole previous guard stack existed for.
 *
 * EVERY ANIMATABLE THING IS STILL PARAMETERISED BY TIME. `uTime` remains on the
 * arc, hub and orbit materials; the globe's pose is a rotation on a group; the
 * orbital nodes are positioned from a parameter along their own path. Animation
 * is `advance the uniforms, call draw()` in a rAF — the look does not have to be
 * rebuilt for it, which is exactly what the brief asked to be left possible.
 *
 * ── 2. THE PLANET IS 81% WIDER, AND MORE DETAILED WITH IT ─────────────────
 * The camera dolly alone would have been "increasing its CSS width" by another
 * name. What actually changed:
 *
 *   - the palette INVERTED. The world is cool blue and white; the warm gold is
 *     now confined to India and its neighbourhood, per the brief's "the rest of
 *     the globe primarily uses cool blue/white illumination";
 *   - COASTLINES are detected from the mask and drawn brighter and larger, so
 *     the continents have an edge rather than a uniform fill. This is most of
 *     what makes a night-lights Earth read as geography;
 *   - DENSITY VARIES. A smooth field over the sphere decides how likely a land
 *     cell is to be lit at all, so the Sahara and Siberia are sparse and the
 *     coasts and river valleys are dense — as they are on a real composite;
 *   - a SURFACE NETWORK of nodes and fine great-circle links is drawn over the
 *     whole planet, cool and faint, which is the brief's "connected network
 *     nodes; fine lines across the surface". India's own arcs then sit on top
 *     of it, brighter and warmer, so the subcontinent EMERGES from a global
 *     structure instead of being a glowing outline pasted onto one;
 *   - the orbits are ELLIPSES with their own inclinations, eccentricities and
 *     centre offsets rather than four concentric circles, and each knows
 *     whether it is passing in front of the planet or behind it.
 *
 * ── 3. THE REFLECTION IS GONE, AND THAT IS A DECISION ─────────────────────
 * The previous revision mirrored the land field below the south pole, because
 * the reference image it was copying stood the globe on a dark surface and the
 * owner asked for it by name. The 17-09 brief replaces that reference with a
 * SPACE composition — "deep navy/black atmospheric space", three depth layers,
 * orbital paths passing behind and in front — and a floor reflection
 * contradicts it. At this size it would also be clipped to a 56px sliver by the
 * bottom of the stage. Restoring it is a mirrored group and a fade window; it
 * is left out rather than lost.
 *
 * ── 4. THE FALLBACK IS STILL THE MAJORITY'S VIEW ──────────────────────────
 * `canRunGlobe()` says no to reduced motion, to every phone, to <=4GB of memory
 * and to a browser with no WebGL. In each of those cases three.min.js is never
 * downloaded and the StaticGlobe SVG at the foot of this file IS the hero
 * visual — so it carries the same palette change, the same coastline emphasis
 * and the same varied orbits. It is rendered either way and simply never
 * covered, which is also what keeps the hero from shifting while the scene
 * loads.
 */

const R = 1;

/**
 * How far the camera sits from the planet's centre.
 *
 * This is the size control, and it is arithmetic rather than taste. A sphere of
 * radius r at distance d projects to a circle whose radius, as a fraction of
 * half the canvas height, is (r / sqrt(d^2 - r^2)) / tan(fov/2). At d = 4.3 and
 * a 40-degree vertical field that is 0.657, so the planet's DIAMETER is 65.7%
 * of the canvas height — and the canvas is deliberately larger than the grid
 * cell it sits in (see HeroVisual), which is what the brief's "may extend
 * beyond the normal boundaries of the hero composition slightly" means here.
 *
 * It was 5.05, giving 55.5% of a canvas that WAS the cell. Together with the
 * oversized canvas that is 643 CSS pixels of planet on the hero's own stage,
 * where it used to be 355.
 */
const CAMERA_Z = 4.3;

/** Vertical field of view, degrees. The point shaders need it — see projScale. */
const FOV = 40;

/**
 * How many candidate points are walked to build the land field.
 *
 * About 29% of the globe is land and roughly two thirds of those survive the
 * density cull below, so this yields around 38,000 points on the continents —
 * up from 26,000. It is a startup cost only, paid once on a thread that is
 * already past first paint with the SVG globe on screen, and NOT a per-frame
 * cost: the draw is one Points object whatever the count.
 *
 * The lat/lon conversion runs for every candidate; everything more expensive
 * than that (the density field, the coastline probe, the distance to India)
 * runs only for the ~29% that are land. That ordering is what keeps this in the
 * tens of milliseconds rather than the hundreds.
 */
const LAND_CANDIDATES = 200000;

/**
 * The X tilt that puts INDIA WHERE THE COMPOSITION NEEDS IT — above the centre
 * of the disc, not on it.
 *
 * Measurable rather than a taste: the centre mark sits at the middle of the
 * stage, and India has to be clear above it.
 *
 * Rotating the group about +X by `a` sends a surface point (0, y, z) to
 * y' = y*cos a - z*sin a. India is at latitude 22N facing the camera, so
 * (y, z) = (sin 22, cos 22) = (0.375, 0.927), and solving
 * 0.375*cos a - 0.927*sin a = 0.41 gives a = -0.045. NEGATIVE — a positive
 * tilt tips the north pole toward the viewer and pushes India DOWN onto the
 * mark, which is what it used to do.
 */
const INDIA_TILT_X = -0.045;

/**
 * The diameter, in WORLD units, of an ordinary land dot.
 *
 * Point sizes are world-space and the shader converts them to pixels, rather
 * than being pixel figures scaled by something convenient. The first draft of
 * this globe did the convenient thing — gl_PointSize = aSize * canvasHeight *
 * 0.55 / -z with aSize starting at 1 — which made every dot about 70 pixels
 * across and rendered the planet as one white disc.
 *
 * At the hero's size a point on the front face sits at depth CAMERA_Z - 1, so
 * this lands an ordinary dot a little over 1.5 CSS pixels: fine enough to read
 * as lights rather than as a grid of circles, at a density where the coastlines
 * still join up.
 */
const LAND_DOT_WORLD = 0.0042;

/** Radius of a city hub's halo, in world units. Major cities, then the rest. */
const HUB_DOT_WORLD = { major: 0.058, minor: 0.036 };

/**
 * Where the light comes from, in VIEW space.
 *
 * View space rather than world space on purpose: the terminator is a
 * composition decision — the light is from the upper right — and anchoring it
 * to the camera keeps it there whatever pose the globe is put in. A world-space
 * light would swing the shaded side around as INDIA_TILT_X is tuned, which is
 * two things fighting over one number.
 */
const SUN_DIR: [number, number, number] = [0.72, 0.52, 0.45];

/**
 * How much of its brightness a light on the UNLIT side keeps.
 *
 * Not zero, and that is the difference between "a planet emerging from
 * darkness" and "a planet cut in half". This is a night-side Earth: the cities
 * on the shaded side are the ones that read strongest, they are simply dimmer
 * overall. Shared by the ocean, the land field and the surface network so the
 * three cannot disagree about where the terminator is.
 */
const NIGHT_SHADOW = 0.68;

/** Warm accent — India's own lights, its atmosphere sliver and its bloom. */
const WARM = 0xffc27a;

/**
 * The orbital paths.
 *
 * ELLIPSES, NOT CIRCLES, and the brief is explicit about why: "Include several
 * thin orbital paths … They should NOT be identical circles. Vary the angles,
 * depths, sizes and trajectories." A TorusGeometry can only be a circle
 * centred on the origin, so these are parameterised instead — semi-axes, a
 * three-axis tilt of the orbital plane, and a small offset of the centre so
 * they are not all concentric either.
 *
 * `nodes` are parameters along the path (0 to 1) where a luminous point sits.
 * On a static frame that is the brief's own reading of the travelling
 * particles: "the particles should simply be positioned as if they are
 * travelling along those paths."
 *
 * The last entry is deliberately INSIDE the atmosphere shell (1.085) and nearly
 * edge-on, so it reads as a close orbit hugging the planet and disappears
 * behind it for half its length.
 */
type OrbitDef = {
  a: number;
  b: number;
  rx: number;
  ry: number;
  rz: number;
  ox: number;
  oy: number;
  oz: number;
  tube: number;
  opacity: number;
  phase: number;
  sweep: number;
  nodes: number[];
};

const ORBITS: OrbitDef[] = [
  { a: 1.17, b: 1.13, rx: 0.36, ry: 0.08, rz: 0.10, ox: 0.02, oy: -0.03, oz: 0,
    tube: 0.0042, opacity: 0.80, phase: 0.4, sweep: 0.55, nodes: [0.08, 0.42, 0.71] },
  { a: 1.38, b: 1.27, rx: -1.26, ry: 0.46, rz: 0.24, ox: -0.05, oy: 0.04, oz: 0.02,
    tube: 0.0036, opacity: 0.54, phase: 2.1, sweep: 0.70, nodes: [0.22, 0.63] },
  { a: 1.62, b: 1.38, rx: 0.18, ry: -0.92, rz: 1.06, ox: 0.07, oy: 0.05, oz: -0.03,
    tube: 0.0038, opacity: 0.58, phase: 4.0, sweep: 0.60, nodes: [0.05, 0.36, 0.55, 0.88] },
  { a: 1.90, b: 1.63, rx: 1.12, ry: 0.55, rz: 0.34, ox: -0.09, oy: -0.06, oz: 0,
    tube: 0.0032, opacity: 0.40, phase: 1.2, sweep: 0.75, nodes: [0.18, 0.66] },
  { a: 2.20, b: 2.05, rx: -0.30, ry: 0.58, rz: -0.52, ox: 0.10, oy: 0.09, oz: 0.04,
    tube: 0.0030, opacity: 0.30, phase: 5.2, sweep: 0.80, nodes: [0.30, 0.79] },
  { a: 2.58, b: 1.96, rx: 0.88, ry: 0.22, rz: 0.98, ox: -0.12, oy: 0.02, oz: 0,
    tube: 0.0028, opacity: 0.24, phase: 3.1, sweep: 0.85, nodes: [0.46] },
  { a: 1.05, b: 1.05, rx: 1.35, ry: -0.62, rz: 0, ox: 0.15, oy: -0.21, oz: 0,
    tube: 0.0026, opacity: 0.36, phase: 0.9, sweep: 0.40, nodes: [0.13, 0.62] },
];

/** The background star field and the drifting motes between the orbits. */
const STAR_COUNT = 460;
const MOTE_COUNT = 150;

/** Geographic latitude/longitude to a point on a sphere of radius `r`. */
function latLonToVec3(lat: number, lon: number, r: number): [number, number, number] {
  const phi = ((90 - lat) * Math.PI) / 180;
  const theta = ((lon + 180) * Math.PI) / 180;
  return [
    -r * Math.sin(phi) * Math.cos(theta),
    r * Math.cos(phi),
    r * Math.sin(phi) * Math.sin(theta),
  ];
}

/**
 * The Y rotation that brings a given longitude round to face the camera (+Z).
 *
 * With the mapping above, a point at longitude L sits at (180 - (L + 180))
 * degrees measured from +X toward +Z, i.e. at -L. Rotating the group by `a`
 * about +Y moves a point at angle p to p - a, and the camera looks down -Z at
 * the +Z face (p = 90). So -L - a = 90, hence a = -(L + 90).
 */
function rotationFacing(lon: number): number {
  return (-(lon + 90) * Math.PI) / 180;
}

/** Longitude folded back into [-180, 180). */
function wrapLon(lon: number): number {
  return ((((lon + 180) % 360) + 360) % 360) - 180;
}

/** Angular distance in degrees between two lat/lon points. */
function angularDistanceDeg(aLat: number, aLon: number, bLat: number, bLon: number): number {
  const toRad = Math.PI / 180;
  const p1 = aLat * toRad;
  const p2 = bLat * toRad;
  const dl = (bLon - aLon) * toRad;
  const c = Math.sin(p1) * Math.sin(p2) + Math.cos(p1) * Math.cos(p2) * Math.cos(dl);
  return (Math.acos(Math.max(-1, Math.min(1, c))) * 180) / Math.PI;
}

/** Points along the great circle between two unit vectors, bulged outward. */
function arcPoints(
  a: [number, number, number],
  b: [number, number, number],
  segments: number,
  bulge: number
): [number, number, number][] {
  const dot = Math.max(-1, Math.min(1, a[0] * b[0] + a[1] * b[1] + a[2] * b[2]));
  const omega = Math.acos(dot);
  const sinO = Math.sin(omega);
  const out: [number, number, number][] = [];
  for (let i = 0; i <= segments; i++) {
    const t = i / segments;
    // Degenerate (coincident) endpoints would divide by zero; fall back to a
    // straight lerp, which for identical points is simply the point itself.
    let x: number, y: number, z: number;
    if (sinO < 1e-6) {
      x = a[0] + (b[0] - a[0]) * t;
      y = a[1] + (b[1] - a[1]) * t;
      z = a[2] + (b[2] - a[2]) * t;
    } else {
      const wa = Math.sin((1 - t) * omega) / sinO;
      const wb = Math.sin(t * omega) / sinO;
      x = a[0] * wa + b[0] * wb;
      y = a[1] * wa + b[1] * wb;
      z = a[2] * wa + b[2] * wb;
    }
    const lift = 1 + bulge * Math.sin(Math.PI * t);
    out.push([x * lift, y * lift, z * lift]);
  }
  return out;
}

/**
 * A smooth pseudo-random field over the sphere, 0 to 1.
 *
 * WHAT IT IS FOR. A night-lights Earth is not uniformly lit: the coasts, the
 * river valleys and the industrial belts are dense and the Sahara, the Amazon
 * and Siberia are nearly dark. Drawing every land cell at one density is the
 * single thing that makes a masked point field read as a stencil rather than as
 * a photograph, and no amount of colour work fixes it afterwards.
 *
 * Three octaves of products of sines rather than real value noise: it is
 * deterministic, needs no table, and at this scale the difference is not
 * visible. Determinism matters — the hero is the first thing on the page and a
 * scene that differs between two loads is a scene nobody can compare a
 * screenshot of.
 */
function surfaceField(x: number, y: number, z: number): number {
  let v = Math.sin(x * 4.1 + 1.3) * Math.cos(y * 3.7 - 0.6) * Math.sin(z * 4.9 + 2.2);
  v += 0.58 * Math.sin(x * 9.3 - 2.1) * Math.cos(z * 8.1 + 0.4) * Math.sin(y * 7.7 + 1.1);
  v += 0.30 * Math.sin(x * 18.7 + 0.7) * Math.sin(y * 17.3 - 1.4) * Math.cos(z * 18.1);
  return Math.min(1, Math.max(0, 0.5 + v * 0.58));
}

/** A deterministic 0-to-1 hash of an integer, for the density cull. */
function hash01(i: number): number {
  const s = Math.sin(i * 12.9898) * 43758.5453;
  return s - Math.floor(s);
}

/** Does this land cell touch the sea? One mask probe in each direction. */
function isCoastal(lat: number, lon: number): boolean {
  // 0.55 degrees steps exactly one 0.5-degree cell. The longitude step widens
  // with latitude so the probe is the same distance ON THE GROUND everywhere —
  // a fixed degree step near the poles probes a cell it has already read.
  const dl = 0.55 / Math.max(0.12, Math.cos((lat * Math.PI) / 180));
  return (
    !isLand(lat + 0.55, lon) ||
    !isLand(lat - 0.55, lon) ||
    !isLand(lat, lon + dl) ||
    !isLand(lat, lon - dl)
  );
}

/**
 * The land point field — the continents, as city lights.
 *
 * A Fibonacci sphere walked point by point, keeping only what the mask calls
 * land. Fibonacci rather than a random lat/lon because random clusters hard at
 * the poles — which on this globe would be a bright Arctic and a sparse
 * equator, the opposite of what the picture wants.
 *
 * FOUR FACTS DECIDE EACH POINT and all four are settled here, on the CPU, where
 * the latitude and longitude are in hand. The shader only lights them.
 *
 *   density   surfaceField decides whether the cell is lit at all, so the
 *             continents have interiors;
 *   coast     a cell touching the sea is brighter and larger, which is what
 *             gives the continents an edge;
 *   India     distance from the subcontinent drives the only warm colour on the
 *             planet, per the brief's "a subtle warm/golden concentration of
 *             light/data points while the rest of the globe primarily uses cool
 *             blue/white illumination";
 *   size      all three above, mildly. DELIBERATELY MILDLY over India: the
 *             brief warns "do NOT make India look like a giant glowing country
 *             outline pasted onto the globe", so the subcontinent is picked out
 *             by COLOUR and by the network above it, not by fat dots.
 */
function buildLandField() {
  const pos: number[] = [];
  const col: number[] = [];
  const size: number[] = [];
  const golden = Math.PI * (3 - Math.sqrt(5));

  for (let i = 0; i < LAND_CANDIDATES; i++) {
    const y = 1 - (i / (LAND_CANDIDATES - 1)) * 2;
    const radius = Math.sqrt(Math.max(0, 1 - y * y));
    const theta = golden * i;
    const x = Math.cos(theta) * radius;
    const z = Math.sin(theta) * radius;

    // Inverse of latLonToVec3 for a unit vector, so the mask is asked about the
    // same coordinate the point will be drawn at.
    const lat = (Math.asin(Math.max(-1, Math.min(1, y))) * 180) / Math.PI;
    const lon = wrapLon(((Math.atan2(z, -x) * 180) / Math.PI) - 180);
    if (!isLand(lat, lon)) continue;

    const field = surfaceField(x, y, z);
    const coast = isCoastal(lat, lon);
    // The cull. A coastline is always kept — it is the one structure the eye
    // uses to recognise a continent, and thinning it is what turns Italy into
    // three dots.
    if (!coast && hash01(i) > 0.26 + 0.74 * field) continue;

    // JITTERED OFF THE LATTICE, AND IT IS NOT A DETAIL. A Fibonacci sphere is
    // a spiral, and at this density the spiral is VISIBLE: the northern half of
    // the planet showed fine diagonal pinstripes running across Europe and
    // Russia, which is the one thing that says "generated" about an otherwise
    // photographic field.
    //
    // HALF A SPACING, NOT A WHOLE ONE. The lattice spacing at 200,000 points is
    // sqrt(4*pi/200000) = 0.0085 radians, and a jitter of that size does kill
    // the pattern — along with the coastlines, which went from an edge to a
    // haze because a point can cross a whole mask cell. At 0.0024 per axis the
    // displacement is under half a spacing, the streaks are gone and Africa
    // still has a shape.
    //
    // It is applied AFTER the mask test on purpose, so the decision about
    // whether a cell is land is still made at the lattice point; the jitter only
    // moves where the light is DRAWN, and a light a fraction of a degree
    // offshore is what a coastline looks like anyway.
    const jx = x + (hash01(i * 7 + 5) - 0.5) * 0.0048;
    const jy = y + (hash01(i * 7 + 29) - 0.5) * 0.0048;
    const jz = z + (hash01(i * 7 + 71) - 0.5) * 0.0048;
    const jn = (R * 1.003) / Math.sqrt(jx * jx + jy * jy + jz * jz);
    pos.push(jx * jn, jy * jn, jz * jn);

    const d = angularDistanceDeg(lat, lon, INDIA_CENTRE.lat, INDIA_CENTRE.lon);
    const home = Math.max(0, 1 - d / 19); // the subcontinent itself
    // AND ITS NEIGHBOURHOOD, TIGHTLY. At 55 degrees with a 0.34 weight the gold
    // reached from Arabia to the Pacific — most of Asia warm, which is not "a
    // subtle warm concentration around India" but a differently coloured
    // hemisphere. 38 degrees puts the transition inside the subcontinent's own
    // neighbours.
    const region = Math.max(0, 1 - d / 38);
    const warm = Math.min(1, home * 0.86 + region * 0.26);

    // The inland base is DIMMER and the coastline brighter than an even split
    // would make them. A continent is recognised by its edge, and a uniform
    // fill at the same value as its outline is a grey blob with a shape.
    const edge = coast ? 1 : 0;
    let r = 0.28 + field * 0.30 + edge * 0.30;
    let g = 0.43 + field * 0.32 + edge * 0.32;
    let b = 0.71 + field * 0.26 + edge * 0.24;

    // Toward gold as India is approached. The green target is pulled less than
    // the red and blue so the hottest cells land on a rich amber rather than on
    // a neutral white — the previous revision lifted blue instead and turned
    // the subcontinent white against an amber world, which is the picture
    // inverted.
    r += (1.0 - r) * warm;
    g += (0.74 - g) * warm * 0.92;
    b += (0.34 - b) * warm;

    // THE ICE CAPS ARE DIMMED, and it is a composition fix as much as a
    // realism one. Antarctica is coastal almost everywhere, so the coastline
    // bump lit the entire southern limb into a bright dotted band — the
    // brightest thing at the bottom of the frame, on a continent with
    // essentially no lights on it. Greenland, northern Canada and Siberia
    // dim with it, which is also how a night composite looks.
    const polar = Math.max(0.28, 1 - Math.max(0, (Math.abs(lat) - 56) / 30));

    const lift = (1 + home * 0.22) * polar;
    col.push(Math.min(1, r * lift), Math.min(1, g * lift), Math.min(1, b * lift));
    size.push(
      LAND_DOT_WORLD *
        (0.80 + field * 0.34 + edge * 0.40 * polar + home * 0.35 + region * 0.10)
    );
  }

  return {
    position: new Float32Array(pos),
    color: new Float32Array(col),
    size: new Float32Array(size),
    count: size.length,
  };
}

/**
 * The network laid over the whole planet: nodes on land, linked to their
 * nearest neighbours by fine great-circle lines.
 *
 * WHY IT EXISTS. The brief asks the Earth's surface to contain "connected
 * network nodes" and "fine lines across the surface", and — more importantly —
 * that India "should naturally emerge from the Earth's network/light structure"
 * rather than be pasted onto it. It cannot emerge from a structure that only
 * exists over India, which is all the previous scene had: twenty Indian cities
 * and twelve arcs between them, on an otherwise plain globe. So the structure
 * is global and cool, and India's own arcs sit on top of it brighter and
 * warmer. The difference is then a matter of degree, which is what "emerges"
 * means.
 *
 * Nodes are accepted greedily off a Fibonacci walk with a minimum separation,
 * which spreads them without needing a relaxation pass. The ice caps are
 * excluded: a link across the pole is a long line over an empty white cap and
 * it reads as an error.
 */
const NETWORK_CANDIDATES = 3200;
const NETWORK_MIN_SEPARATION_DEG = 7.5;
const NETWORK_LINK_MAX_DEG = 33;
const NETWORK_LINKS_PER_NODE = 2;

function buildSurfaceNetwork() {
  const nodes: { lat: number; lon: number; v: [number, number, number] }[] = [];
  const golden = Math.PI * (3 - Math.sqrt(5));

  for (let i = 0; i < NETWORK_CANDIDATES; i++) {
    const y = 1 - (i / (NETWORK_CANDIDATES - 1)) * 2;
    const radius = Math.sqrt(Math.max(0, 1 - y * y));
    const theta = golden * i;
    const x = Math.cos(theta) * radius;
    const z = Math.sin(theta) * radius;
    const lat = (Math.asin(Math.max(-1, Math.min(1, y))) * 180) / Math.PI;
    if (Math.abs(lat) > 66) continue;
    const lon = wrapLon(((Math.atan2(z, -x) * 180) / Math.PI) - 180);
    if (!isLand(lat, lon)) continue;

    let clear = true;
    for (const n of nodes) {
      if (angularDistanceDeg(lat, lon, n.lat, n.lon) < NETWORK_MIN_SEPARATION_DEG) {
        clear = false;
        break;
      }
    }
    if (!clear) continue;
    nodes.push({ lat, lon, v: [x, y, z] });
  }

  const seen = new Set<string>();
  const pos: number[] = [];
  const col: number[] = [];

  nodes.forEach((n, i) => {
    const near = nodes
      .map((m, j) => ({ j, d: j === i ? Infinity : angularDistanceDeg(n.lat, n.lon, m.lat, m.lon) }))
      .filter((c) => c.d <= NETWORK_LINK_MAX_DEG)
      .sort((p, q) => p.d - q.d)
      .slice(0, NETWORK_LINKS_PER_NODE);

    for (const c of near) {
      const key = i < c.j ? `${i}:${c.j}` : `${c.j}:${i}`;
      if (seen.has(key)) continue;
      seen.add(key);

      const m = nodes[c.j];
      // The link's colour comes from its MIDPOINT's distance to India, so a
      // link is one colour end to end. Per-vertex would give a gradient nobody
      // asked for and would make the mesh read as a heat map.
      const midLat = (n.lat + m.lat) / 2;
      const midLon = (n.lon + m.lon) / 2;
      const dIndia = angularDistanceDeg(midLat, midLon, INDIA_CENTRE.lat, INDIA_CENTRE.lon);
      const warm = Math.max(0, 1 - dIndia / 42);
      const r = 0.26 + warm * 0.58;
      const g = 0.42 + warm * 0.30;
      const b = 0.76 - warm * 0.34;

      // Just above the land dots (1.003) so the mesh sits over the lights
      // rather than fighting them for the same depth.
      const path = arcPoints(n.v, m.v, 9, 0.004).map(([x, y, z]) => [
        x * R * 1.0055,
        y * R * 1.0055,
        z * R * 1.0055,
      ]);
      for (let s = 0; s < path.length - 1; s++) {
        pos.push(...path[s], ...path[s + 1]);
        col.push(r, g, b, r, g, b);
      }
    }
  });

  return {
    nodes,
    position: new Float32Array(pos),
    color: new Float32Array(col),
  };
}

/** A point on an orbit, at parameter t in 0..1. Written out rather than left to
 *  a matrix so the node placement and the tube walk cannot disagree. */
function orbitPointAt(def: OrbitDef, t: number): [number, number, number] {
  const a = t * Math.PI * 2;
  const px = Math.cos(a) * def.a;
  const py = Math.sin(a) * def.b;

  // Euler XYZ, by hand: three rotations of a vector in the orbit's own plane.
  const cx = Math.cos(def.rx), sx = Math.sin(def.rx);
  const cy = Math.cos(def.ry), sy = Math.sin(def.ry);
  const cz = Math.cos(def.rz), sz = Math.sin(def.rz);

  let x = px, y = py, z = 0;
  // Z
  let nx = x * cz - y * sz;
  let ny = x * sz + y * cz;
  x = nx; y = ny;
  // Y
  nx = x * cy + z * sy;
  const nz = -x * sy + z * cy;
  x = nx; z = nz;
  // X
  ny = y * cx - z * sx;
  const nz2 = y * sx + z * cx;
  y = ny; z = nz2;

  return [x + def.ox, y + def.oy, z + def.oz];
}

/** A soft radial sprite, drawn once into a canvas. */
function radialTexture(THREE: any, stops: Array<[number, string]>, px = 128) {
  const c = document.createElement("canvas");
  c.width = c.height = px;
  const ctx = c.getContext("2d");
  if (ctx) {
    const half = px / 2;
    const grad = ctx.createRadialGradient(half, half, 0, half, half, half);
    for (const [at, colour] of stops) grad.addColorStop(at, colour);
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, px, px);
  }
  return new THREE.CanvasTexture(c);
}

export function HeroGlobe({ className = "" }: { className?: string }) {
  const stageRef = useRef<HTMLDivElement | null>(null);
  const fadeRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [live, setLive] = useState(false);

  // The scroll-driven dissolve. Runs in BOTH modes — the static SVG has to fade
  // out over the section boundary just as the canvas does, or the fallback
  // visitor gets a globe sitting on top of the next section. It is plain CSS
  // opacity on a wrapper, so it costs the compositor a layer and costs the
  // WebGL scene nothing at all: the canvas is never redrawn for it.
  useEffect(() => {
    const stage = stageRef.current;
    const fade = fadeRef.current;
    if (!stage || !fade) return;
    let raf = 0;
    const apply = () => {
      raf = 0;
      const rect = stage.getBoundingClientRect();
      if (!rect.height) return;
      const p = Math.min(1, Math.max(0, -rect.top / (rect.height * 0.9)));
      fade.style.opacity = (1 - Math.max(0, (p - 0.55) / 0.45)).toFixed(2);
    };
    const onScroll = () => {
      if (!raf) raf = requestAnimationFrame(apply);
    };
    apply();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
      cancelAnimationFrame(raf);
    };
  }, []);

  useEffect(() => {
    if (!canRunGlobe()) return;

    let disposed = false;
    let resizeRaf = 0;
    let renderer: any = null;
    const disposables: any[] = [];
    let cleanupListeners: (() => void) | null = null;

    loadThree()
      .then((THREE) => {
        const canvas = canvasRef.current;
        const stage = stageRef.current;
        if (disposed || !canvas || !stage) return;

        let w = stage.clientWidth || 640;
        let h = stage.clientHeight || 640;

        /**
         * THE RENDER RESOLUTION GOES UP, not down, and it is the single biggest
         * quality change here.
         *
         * The previous scene capped the device pixel ratio at 1.25 because it
         * was redrawing thirty times a second on integrated GPUs and fill rate
         * was the budget. Nothing about that reasoning survives a scene that
         * draws ONCE — so the cap is 2, and the one-pixel city lights stop
         * being resampled into a smear.
         *
         * The pixel BUDGET is still real, because a buffer has to be allocated
         * whatever it costs to fill: above about four million device pixels the
         * ratio comes back down rather than risking the allocation on a weak
         * GPU. At the hero's own size that clamp does not bind.
         */
        let RENDER_DPR = Math.min(window.devicePixelRatio || 1, 2);
        const PIXEL_BUDGET = 4_000_000;
        if (w * h * RENDER_DPR * RENDER_DPR > PIXEL_BUDGET) {
          RENDER_DPR = Math.max(1, Math.sqrt(PIXEL_BUDGET / (w * h)));
        }

        renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
        renderer.setPixelRatio(RENDER_DPR);
        renderer.setSize(w, h, false);

        const scene = new THREE.Scene();
        const camera = new THREE.PerspectiveCamera(FOV, w / h, 0.1, 100);
        camera.position.set(0, 0, CAMERA_Z);
        camera.lookAt(0, 0, 0);

        const sun = new THREE.Vector3(...SUN_DIR).normalize();

        /**
         * World size to pixels, for a perspective camera.
         *
         * A sphere of diameter s at view depth d spans a fraction
         * s / (2 d tan(fov/2)) of the viewport's HEIGHT, so in device pixels it
         * is s * H / (2 tan(fov/2)) / d. Everything but d is constant per
         * frame, which is this number; the shaders divide by -mv.z.
         *
         * Recomputed on resize, so a dot is the same physical size whatever the
         * hero's height — and it is derived rather than tuned, because a
         * hand-picked constant is what drew the planet as a white disc the
         * first time.
         */
        const projScale = () =>
          (h * RENDER_DPR) / (2 * Math.tan(((FOV / 2) * Math.PI) / 180));

        /** Materials whose point size is in world units and needs projScale. */
        const scaleMats: any[] = [];
        /** Orbit materials, which need the canvas resolution for their edge fade. */
        const orbitMats: any[] = [];

        /**
         * THREE DEPTH LAYERS, as the brief asks for them by name.
         *
         *   bg   deep space: the star field and a very soft nebula wash. Added
         *        to the scene root, so nothing about the planet's pose moves it.
         *   mid  the orbital paths, their nodes and the drifting motes. Its own
         *        group rather than a child of the planet's, so each orbit's
         *        inclination is exactly the one written in ORBITS instead of
         *        that plus INDIA_TILT_X.
         *   fg   the Earth and its atmosphere. `tilt` then `spin`, two nested
         *        groups so the India-facing rotation (Y) is applied before the
         *        viewing tilt (X) — a single Euler would compose them in
         *        whichever order the rotation order happens to be, which is
         *        exactly the kind of thing that silently puts the Pacific in
         *        the middle.
         *
         * renderOrder is set explicitly on every transparent object below.
         * Three sorts transparents back-to-front by their object centres, and
         * the planet, the orbits and the sprites all share one centre — so
         * without it the sort is arbitrary and the atmosphere can be drawn
         * under the star field. Depth TESTING still does the real work: the
         * core is opaque and depth-writing, so anything genuinely behind the
         * planet is hidden whatever order it is drawn in.
         */
        const bg = new THREE.Group();
        const mid = new THREE.Group();
        const tilt = new THREE.Group();
        tilt.rotation.x = INDIA_TILT_X;
        const spin = new THREE.Group();
        spin.rotation.y = rotationFacing(INDIA_CENTRE.lon);
        tilt.add(spin);
        scene.add(bg, mid, tilt);

        // ── BACKGROUND: the nebula wash ───────────────────────────────────
        // A very faint, very large cool wash well behind everything. The hero
        // section is already navy, so this is not a backdrop — it is the
        // difference between "space" and "a flat panel", and at 6% peak alpha
        // it is felt rather than seen.
        const nebulaTex = radialTexture(THREE, [
          [0, "rgba(70,120,215,0.30)"],
          [0.45, "rgba(52,84,180,0.12)"],
          [1, "rgba(30,50,130,0)"],
        ]);
        const nebulaMat = new THREE.SpriteMaterial({
          map: nebulaTex,
          transparent: true,
          opacity: 0.55,
          blending: THREE.AdditiveBlending,
          depthWrite: false,
        });
        const nebula = new THREE.Sprite(nebulaMat);
        nebula.scale.set(12, 12, 1);
        nebula.position.set(0.6, 0.35, -7);
        nebula.renderOrder = -30;
        bg.add(nebula);
        disposables.push(nebulaTex, nebulaMat);

        // ── BACKGROUND: the star field ────────────────────────────────────
        // Deliberately in a SLAB behind the planet rather than on a shell
        // around it: a shell puts points between the camera and the globe,
        // where a point a fraction of a unit from the lens is drawn enormous.
        // Depth comes from the z spread, which is what makes the smallest ones
        // read as far away.
        const starPos = new Float32Array(STAR_COUNT * 3);
        const starSize = new Float32Array(STAR_COUNT);
        const starGlow = new Float32Array(STAR_COUNT);
        const starCol = new Float32Array(STAR_COUNT * 3);
        for (let i = 0; i < STAR_COUNT; i++) {
          const rx = hash01(i * 3 + 11);
          const ry = hash01(i * 3 + 47);
          const rz = hash01(i * 3 + 83);
          const rs = hash01(i * 3 + 157);
          starPos[i * 3] = (rx - 0.5) * 14;
          starPos[i * 3 + 1] = (ry - 0.5) * 11;
          starPos[i * 3 + 2] = -1.6 - rz * 8.5;
          starSize[i] = 0.010 + rs * 0.022;
          starGlow[i] = 0.10 + rs * 0.42;
          // A cool field with a handful of warmer grains, so it is not one
          // flat colour of dust.
          const warmStar = rs > 0.93 ? 1 : 0;
          starCol[i * 3] = 0.62 + warmStar * 0.32;
          starCol[i * 3 + 1] = 0.74 + warmStar * 0.14;
          starCol[i * 3 + 2] = 1.0 - warmStar * 0.30;
        }
        const starGeo = new THREE.BufferGeometry();
        starGeo.setAttribute("position", new THREE.BufferAttribute(starPos, 3));
        starGeo.setAttribute("aSize", new THREE.BufferAttribute(starSize, 1));
        starGeo.setAttribute("aGlow", new THREE.BufferAttribute(starGlow, 1));
        starGeo.setAttribute("aColor", new THREE.BufferAttribute(starCol, 3));
        const starMat = new THREE.ShaderMaterial({
          vertexShader: SPRITE_POINT_VERTEX,
          fragmentShader: STAR_FRAGMENT,
          uniforms: { uScale: { value: projScale() } },
          transparent: true,
          depthWrite: false,
          blending: THREE.AdditiveBlending,
        });
        const stars = new THREE.Points(starGeo, starMat);
        stars.renderOrder = -20;
        bg.add(stars);
        scaleMats.push(starMat);
        disposables.push(starGeo, starMat);

        // ── FOREGROUND: the planet's body ─────────────────────────────────
        const coreGeo = new THREE.SphereGeometry(R * 0.994, 72, 54);
        const coreMat = new THREE.ShaderMaterial({
          vertexShader: CORE_VERTEX,
          fragmentShader: CORE_FRAGMENT,
          uniforms: {
            // NEAR-BLACK, not navy. Contrast is what makes a lit coastline
            // read, and it is made at both ends: the dots lift toward white and
            // the ocean drops away under them.
            uCentre: { value: new THREE.Color(0x061021) },
            uLimb: { value: new THREE.Color(0x01040b) },
            uSun: { value: sun },
            uShadow: { value: NIGHT_SHADOW },
          },
        });
        spin.add(new THREE.Mesh(coreGeo, coreMat));
        disposables.push(coreGeo, coreMat);

        // ── FOREGROUND: the continents ────────────────────────────────────
        const field = buildLandField();
        const landGeo = new THREE.BufferGeometry();
        landGeo.setAttribute("position", new THREE.BufferAttribute(field.position, 3));
        landGeo.setAttribute("aColor", new THREE.BufferAttribute(field.color, 3));
        landGeo.setAttribute("aSize", new THREE.BufferAttribute(field.size, 1));
        const landMat = new THREE.ShaderMaterial({
          vertexShader: LAND_VERTEX,
          fragmentShader: LAND_FRAGMENT,
          uniforms: {
            uScale: { value: projScale() },
            uSun: { value: sun },
            uShadow: { value: NIGHT_SHADOW },
            uOpacity: { value: 1 },
            // Equal bounds disable the depth fade, which is what the globe
            // passes. It is kept because it is what a mirrored copy would need
            // and it costs one comparison.
            uFadeFrom: { value: 0 },
            uFadeTo: { value: 0 },
          },
          transparent: true,
          depthWrite: false,
          // NOT additive. The land field is the planet's lit SURFACE, and the
          // dots overlap where the projection foreshortens them — summing them
          // saturates the continents to white before the atmosphere is even
          // drawn. The network, hubs and arcs above the surface are additive,
          // because those genuinely are light sources.
        });
        const landPoints = new THREE.Points(landGeo, landMat);
        landPoints.renderOrder = 0;
        spin.add(landPoints);
        scaleMats.push(landMat);
        disposables.push(landGeo, landMat);

        // ── FOREGROUND: the surface network ───────────────────────────────
        const net = buildSurfaceNetwork();
        const netGeo = new THREE.BufferGeometry();
        netGeo.setAttribute("position", new THREE.BufferAttribute(net.position, 3));
        netGeo.setAttribute("aColor", new THREE.BufferAttribute(net.color, 3));
        const netMat = new THREE.ShaderMaterial({
          vertexShader: NETWORK_VERTEX,
          fragmentShader: NETWORK_FRAGMENT,
          uniforms: {
            uSun: { value: sun },
            uShadow: { value: NIGHT_SHADOW },
            // FAINT. This layer is texture, not subject: it has to be legible
            // when looked for and invisible when not, or it competes with the
            // city lights it is drawn over.
            uOpacity: { value: 0.42 },
          },
          transparent: true,
          depthWrite: false,
          blending: THREE.AdditiveBlending,
        });
        const netLines = new THREE.LineSegments(netGeo, netMat);
        netLines.renderOrder = 1;
        spin.add(netLines);
        disposables.push(netGeo, netMat);

        // The network's own nodes — a dim dot at each junction, so the mesh
        // has vertices rather than being a tangle of crossing lines.
        const netNodeGeo = new THREE.BufferGeometry();
        const nnPos = new Float32Array(net.nodes.length * 3);
        const nnSize = new Float32Array(net.nodes.length);
        const nnGlow = new Float32Array(net.nodes.length);
        const nnCol = new Float32Array(net.nodes.length * 3);
        net.nodes.forEach((n, i) => {
          nnPos[i * 3] = n.v[0] * R * 1.0055;
          nnPos[i * 3 + 1] = n.v[1] * R * 1.0055;
          nnPos[i * 3 + 2] = n.v[2] * R * 1.0055;
          const dIndia = angularDistanceDeg(n.lat, n.lon, INDIA_CENTRE.lat, INDIA_CENTRE.lon);
          const warm = Math.max(0, 1 - dIndia / 42);
          nnSize[i] = 0.011 + warm * 0.009;
          nnGlow[i] = 0.30 + warm * 0.45;
          nnCol[i * 3] = 0.52 + warm * 0.44;
          nnCol[i * 3 + 1] = 0.68 + warm * 0.16;
          nnCol[i * 3 + 2] = 0.96 - warm * 0.44;
        });
        netNodeGeo.setAttribute("position", new THREE.BufferAttribute(nnPos, 3));
        netNodeGeo.setAttribute("aSize", new THREE.BufferAttribute(nnSize, 1));
        netNodeGeo.setAttribute("aGlow", new THREE.BufferAttribute(nnGlow, 1));
        netNodeGeo.setAttribute("aColor", new THREE.BufferAttribute(nnCol, 3));
        const netNodeMat = new THREE.ShaderMaterial({
          vertexShader: SPRITE_POINT_VERTEX,
          fragmentShader: NODE_FRAGMENT,
          uniforms: { uScale: { value: projScale() } },
          transparent: true,
          depthWrite: false,
          blending: THREE.AdditiveBlending,
        });
        const netNodes = new THREE.Points(netNodeGeo, netNodeMat);
        netNodes.renderOrder = 2;
        spin.add(netNodes);
        scaleMats.push(netNodeMat);
        disposables.push(netNodeGeo, netNodeMat);

        // ── FOREGROUND: the Indian city hubs ──────────────────────────────
        const hubVecs = CITIES.map((c) => latLonToVec3(c.lat, c.lon, R * 1.014));
        const hubPos = new Float32Array(CITIES.length * 3);
        const hubSize = new Float32Array(CITIES.length);
        const hubPhase = new Float32Array(CITIES.length);
        CITIES.forEach((c, i) => {
          hubPos[i * 3] = hubVecs[i][0];
          hubPos[i * 3 + 1] = hubVecs[i][1];
          hubPos[i * 3 + 2] = hubVecs[i][2];
          hubSize[i] = c.major ? HUB_DOT_WORLD.major : HUB_DOT_WORLD.minor;
          // Deterministic, not Math.random(): the hero is the first thing on the
          // page and a scene that differs between two loads is a scene nobody
          // can compare a screenshot of. At uTime 0 this is also what gives the
          // twenty hubs twenty different brightnesses on a still frame.
          hubPhase[i] = (i * 0.37) % 1;
        });
        const hubGeo = new THREE.BufferGeometry();
        hubGeo.setAttribute("position", new THREE.BufferAttribute(hubPos, 3));
        hubGeo.setAttribute("aSize", new THREE.BufferAttribute(hubSize, 1));
        hubGeo.setAttribute("aPhase", new THREE.BufferAttribute(hubPhase, 1));
        const hubMat = new THREE.ShaderMaterial({
          vertexShader: HUB_VERTEX,
          fragmentShader: HUB_FRAGMENT,
          uniforms: {
            uScale: { value: projScale() },
            uTime: { value: 0 },
            uCore: { value: new THREE.Color(0xfff4e2) },
            uHalo: { value: new THREE.Color(0xffc98a) },
          },
          transparent: true,
          depthWrite: false,
          blending: THREE.AdditiveBlending,
        });
        const hubs = new THREE.Points(hubGeo, hubMat);
        hubs.renderOrder = 3;
        spin.add(hubs);
        scaleMats.push(hubMat);
        disposables.push(hubGeo, hubMat);

        // ── FOREGROUND: India's own network arcs ──────────────────────────
        // A tube rather than a line: these sweeps have width and a gradient,
        // and a LineBasicMaterial has neither. 48 segments along and 5 around
        // is the coarsest that still reads as round at this scale.
        //
        // THIN, AND THEY HUG THE SURFACE. Every city in geography.ts is in
        // India, so twelve arcs between them all bunch into the same few
        // degrees of the globe — thick ones are a bright tangle sitting on the
        // one part of the picture that has to stay legible. The travelling
        // head stays bright, so the structure is not lost with the bulk.
        const arcMats: any[] = [];
        ARCS.forEach(([ai, bi], i) => {
          const pts = arcPoints(hubVecs[ai], hubVecs[bi], 48, 0.1).map(
            ([x, y, z]) => new THREE.Vector3(x, y, z)
          );
          const curve = new THREE.CatmullRomCurve3(pts);
          const g = new THREE.TubeGeometry(curve, 64, 0.0030, 5, false);
          const m = new THREE.ShaderMaterial({
            vertexShader: ARC_VERTEX,
            fragmentShader: ARC_FRAGMENT,
            uniforms: {
              uColor: { value: new THREE.Color(0xffc98a) },
              uSpark: { value: new THREE.Color(0xfff6e6) },
              uTime: { value: 0 },
              // At uTime 0 this parks each arc's bright head somewhere
              // different along its own path — the static frame's answer to
              // "positioned as if they are travelling".
              uPhase: { value: (i * 0.41) % 1 },
              uSpeed: { value: 0.16 },
              uBase: { value: 0.26 },
            },
            transparent: true,
            depthWrite: false,
            blending: THREE.AdditiveBlending,
          });
          const mesh = new THREE.Mesh(g, m);
          mesh.renderOrder = 3;
          spin.add(mesh);
          arcMats.push(m);
          disposables.push(g, m);
        });

        // ── FOREGROUND: the warm bloom over India ─────────────────────────
        // Anchored to the subcontinent's own coordinates inside the spinning
        // group, so it is a property of the PLACE rather than of the screen.
        // This is the brief's "subtle warm/gold around India" as light in the
        // air above it, which no amount of dot colour can produce: the dots
        // are the source, this is the glow.
        const indiaTex = radialTexture(THREE, [
          [0, "rgba(255,196,118,0.27)"],
          [0.4, "rgba(255,168,88,0.10)"],
          [1, "rgba(255,150,70,0)"],
        ]);
        const indiaMat = new THREE.SpriteMaterial({
          map: indiaTex,
          transparent: true,
          blending: THREE.AdditiveBlending,
          depthWrite: false,
        });
        const indiaGlow = new THREE.Sprite(indiaMat);
        const [ix, iy, iz] = latLonToVec3(INDIA_CENTRE.lat, INDIA_CENTRE.lon, R * 1.02);
        indiaGlow.position.set(ix, iy, iz);
        indiaGlow.scale.set(0.60, 0.60, 1);
        indiaGlow.renderOrder = 4;
        spin.add(indiaGlow);
        disposables.push(indiaTex, indiaMat);

        // ── FOREGROUND: the atmosphere ────────────────────────────────────
        const atmGeo = new THREE.SphereGeometry(R * 1.062, 64, 48);
        const atmMat = new THREE.ShaderMaterial({
          vertexShader: ATMOSPHERE_VERTEX,
          fragmentShader: ATMOSPHERE_FRAGMENT,
          uniforms: {
            uColor: { value: new THREE.Color(0x4f8fe6) },
            uHot: { value: new THREE.Color(0xdcebff) },
            uWarm: { value: new THREE.Color(WARM) },
            uSun: { value: sun },
            // A WHISPER. The brief puts all the warmth around India, so the
            // limb runs blue into cool white and the gold is a sliver at the
            // very brightest part of it. The previous revision ran this at 1.0
            // and the result was an amber hoop bolted to the planet.
            uWarmGain: { value: 0.34 },
            // A HIGH power is what keeps this a rim. The fresnel term falls off
            // as pow(1 - facing, uPower), so a low exponent spreads it inward
            // across the whole disc.
            uPower: { value: 3.6 },
            uIntensity: { value: 0.70 },
          },
          side: THREE.BackSide,
          transparent: true,
          depthWrite: false,
          blending: THREE.AdditiveBlending,
        });
        const atmosphere = new THREE.Mesh(atmGeo, atmMat);
        atmosphere.renderOrder = 5;
        tilt.add(atmosphere);
        disposables.push(atmGeo, atmMat);

        // A soft halo behind the whole thing, which the fresnel shell cannot
        // give on its own — the shell stops at its own radius, and the glow
        // this composition wants reaches well past the silhouette. The centre
        // stop is nearly clear because it sits BEHIND the planet and is meant
        // to escape past the edge, not wash over the face.
        const haloTex = radialTexture(THREE, [
          [0, "rgba(96,150,240,0.15)"],
          [0.5, "rgba(84,126,224,0.055)"],
          [1, "rgba(76,112,216,0)"],
        ]);
        const haloMat = new THREE.SpriteMaterial({
          map: haloTex,
          transparent: true,
          blending: THREE.AdditiveBlending,
          depthWrite: false,
        });
        const halo = new THREE.Sprite(haloMat);
        halo.scale.set(3.6, 3.6, 1);
        halo.position.z = -1.5;
        halo.renderOrder = -10;
        tilt.add(halo);
        disposables.push(haloTex, haloMat);

        // ── MIDDLE: the orbital paths ─────────────────────────────────────
        const orbitNodePos: number[] = [];
        const orbitNodeSize: number[] = [];
        const orbitNodeGlow: number[] = [];
        const orbitNodeCol: number[] = [];

        ORBITS.forEach((def, i) => {
          const pts: any[] = [];
          for (let s = 0; s < 220; s++) {
            const [x, y, z] = orbitPointAt(def, s / 220);
            pts.push(new THREE.Vector3(x, y, z));
          }
          const curve = new THREE.CatmullRomCurve3(pts, true);
          const g = new THREE.TubeGeometry(curve, 240, def.tube, 6, true);
          const m = new THREE.ShaderMaterial({
            vertexShader: ORBIT_VERTEX,
            fragmentShader: ORBIT_FRAGMENT,
            uniforms: {
              uColor: { value: new THREE.Color(0x7fb2f2) },
              uHot: { value: new THREE.Color(0xe4f0ff) },
              uOpacity: { value: def.opacity },
              // The globe's centre is at the origin and the camera looks
              // straight at it, so its view-space depth IS the camera distance.
              uCentreDepth: { value: CAMERA_Z },
              uPhase: { value: def.phase },
              uSweep: { value: def.sweep },
              uResolution: { value: new THREE.Vector2(w * RENDER_DPR, h * RENDER_DPR) },
              uEdge: { value: 0.11 },
            },
            transparent: true,
            depthWrite: false,
            blending: THREE.AdditiveBlending,
          });
          const mesh = new THREE.Mesh(g, m);
          mesh.renderOrder = 6;
          mid.add(mesh);
          orbitMats.push(m);
          disposables.push(g, m);

          for (const t of def.nodes) {
            const [x, y, z] = orbitPointAt(def, t);
            orbitNodePos.push(x, y, z);
            // The inner orbits carry the larger, brighter nodes: they are
            // nearer the subject and a uniform node size flattens the set.
            const near = Math.max(0, 1 - i / ORBITS.length);
            orbitNodeSize.push(0.018 + near * 0.020);
            orbitNodeGlow.push(0.45 + near * 0.50);
            orbitNodeCol.push(0.70 + near * 0.22, 0.83 + near * 0.12, 1.0);
          }
        });

        const onGeo = new THREE.BufferGeometry();
        onGeo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(orbitNodePos), 3));
        onGeo.setAttribute("aSize", new THREE.BufferAttribute(new Float32Array(orbitNodeSize), 1));
        onGeo.setAttribute("aGlow", new THREE.BufferAttribute(new Float32Array(orbitNodeGlow), 1));
        onGeo.setAttribute("aColor", new THREE.BufferAttribute(new Float32Array(orbitNodeCol), 3));
        const onMat = new THREE.ShaderMaterial({
          vertexShader: SPRITE_POINT_VERTEX,
          fragmentShader: NODE_FRAGMENT,
          uniforms: { uScale: { value: projScale() } },
          transparent: true,
          depthWrite: false,
          blending: THREE.AdditiveBlending,
        });
        const orbitNodes = new THREE.Points(onGeo, onMat);
        orbitNodes.renderOrder = 7;
        mid.add(orbitNodes);
        scaleMats.push(onMat);
        disposables.push(onGeo, onMat);

        // ── MIDDLE: the drifting motes ────────────────────────────────────
        // Fine points scattered through the orbital shell, so the space
        // between the planet and the paths is not empty. Positions are
        // deterministic; nothing moves them.
        const motePos = new Float32Array(MOTE_COUNT * 3);
        const moteSize = new Float32Array(MOTE_COUNT);
        const moteGlow = new Float32Array(MOTE_COUNT);
        const moteCol = new Float32Array(MOTE_COUNT * 3);
        for (let i = 0; i < MOTE_COUNT; i++) {
          const rr = 1.22 + hash01(i * 5 + 3) * 1.45;
          const th = hash01(i * 5 + 19) * Math.PI * 2;
          const ph = Math.acos(hash01(i * 5 + 61) * 2 - 1);
          motePos[i * 3] = rr * Math.sin(ph) * Math.cos(th);
          motePos[i * 3 + 1] = rr * Math.sin(ph) * Math.sin(th) * 0.8;
          motePos[i * 3 + 2] = rr * Math.cos(ph);
          const s = hash01(i * 5 + 101);
          moteSize[i] = 0.011 + s * 0.016;
          moteGlow[i] = 0.24 + s * 0.46;
          moteCol[i * 3] = 0.60;
          moteCol[i * 3 + 1] = 0.77;
          moteCol[i * 3 + 2] = 0.99;
        }
        const moteGeo = new THREE.BufferGeometry();
        moteGeo.setAttribute("position", new THREE.BufferAttribute(motePos, 3));
        moteGeo.setAttribute("aSize", new THREE.BufferAttribute(moteSize, 1));
        moteGeo.setAttribute("aGlow", new THREE.BufferAttribute(moteGlow, 1));
        moteGeo.setAttribute("aColor", new THREE.BufferAttribute(moteCol, 3));
        const moteMat = new THREE.ShaderMaterial({
          vertexShader: SPRITE_POINT_VERTEX,
          fragmentShader: STAR_FRAGMENT,
          uniforms: { uScale: { value: projScale() } },
          transparent: true,
          depthWrite: false,
          blending: THREE.AdditiveBlending,
        });
        const motes = new THREE.Points(moteGeo, moteMat);
        motes.renderOrder = 7;
        mid.add(motes);
        scaleMats.push(moteMat);
        disposables.push(moteGeo, moteMat);

        // ── THE DRAW ──────────────────────────────────────────────────────
        /**
         * ONE FRAME. There is no loop, and the absence is the design.
         *
         * WHERE THE ANIMATION GOES, when it is asked for: a requestAnimationFrame
         * that advances a clock, writes it into `hubMat.uniforms.uTime`, each of
         * `arcMats`, and (for travelling orbital nodes) recomputes their
         * positions from `orbitPointAt(def, t + speed * time)` — then calls this
         * same function. Rotating the planet is `spin.rotation.y += …`; parallax
         * is moving the camera. Nothing about the look below has to change for
         * any of it, which is the point.
         */
        const draw = () => {
          const cw = stage.clientWidth;
          const ch = stage.clientHeight;
          if (cw && ch && (cw !== w || ch !== h)) {
            w = cw;
            h = ch;
            camera.aspect = w / h;
            camera.updateProjectionMatrix();
            renderer.setSize(w, h, false);
            const s = projScale();
            for (const m of scaleMats) m.uniforms.uScale.value = s;
            for (const m of orbitMats) {
              m.uniforms.uResolution.value.set(w * RENDER_DPR, h * RENDER_DPR);
            }
          }
          renderer.render(scene, camera);
        };

        draw();
        setLive(true);

        // Redraw on resize only. Coalesced through one rAF so a drag across the
        // window edge is a handful of frames rather than hundreds.
        //
        // A ResizeObserver ON THE STAGE, not just a window resize listener.
        // Without a render loop this is the ONLY thing that will ever draw a
        // second frame, so it has to see every way the box can change — and the
        // stage is a grid cell whose width moves when a late font metric
        // reflows the copy column beside it, which fires no window event at
        // all. The window listener stays because a viewport change that leaves
        // the element the same size still changes the star field's framing.
        const onResize = () => {
          if (resizeRaf) return;
          resizeRaf = requestAnimationFrame(() => {
            resizeRaf = 0;
            if (!disposed) {
              try {
                draw();
              } catch {
                /* a lost context must not take the page down with it */
              }
            }
          });
        };
        window.addEventListener("resize", onResize);
        const observer =
          typeof ResizeObserver === "function" ? new ResizeObserver(onResize) : null;
        observer?.observe(stage);

        // WITHOUT A LOOP, A LOST CONTEXT IS PERMANENT. An animated scene
        // repaints over the damage on the next frame; this one would leave a
        // blank rectangle where the hero visual is, for ever. The buffers are
        // gone with the context so there is nothing to redraw — the honest
        // answer is to uncover the SVG globe again, which has been sitting
        // underneath all along.
        const onLost = (e: Event) => {
          e.preventDefault();
          setLive(false);
        };
        canvas.addEventListener("webglcontextlost", onLost);

        cleanupListeners = () => {
          window.removeEventListener("resize", onResize);
          observer?.disconnect();
          canvas.removeEventListener("webglcontextlost", onLost);
        };
      })
      .catch(() => {
        /* the static globe is already on screen; nothing to do */
      });

    return () => {
      disposed = true;
      cancelAnimationFrame(resizeRaf);
      cleanupListeners?.();
      if (renderer) {
        try {
          disposables.forEach((d) => d?.dispose?.());
          renderer.dispose();
        } catch {
          /* disposal is best-effort */
        }
      }
    };
  }, []);

  return (
    <div ref={stageRef} className={`relative ${className}`} aria-hidden="true">
      <div ref={fadeRef} className="absolute inset-0">
        <StaticGlobe
          className="absolute inset-0 h-full w-full transition-opacity duration-700"
          style={{ opacity: live ? 0 : 1 }}
        />
        <canvas
          ref={canvasRef}
          className="absolute inset-0 h-full w-full transition-opacity duration-700"
          style={{ opacity: live ? 1 : 0 }}
        />
      </div>
    </div>
  );
}

/**
 * The globe as a static SVG.
 *
 * NOT A PLACEHOLDER. For a visitor on reduced motion, on a phone, on a
 * low-memory machine or in a browser with no WebGL, this IS the hero visual —
 * and canRunGlobe() says no to every phone, so on mobile it is what EVERYONE
 * sees. It is also what reserves the hero's box while three.min.js downloads,
 * which keeps the headline from jumping.
 *
 * SO IT GETS EVERY PALETTE DECISION THE SCENE GOT. Cool blue continents, a
 * brighter coastline, a warm band over India, and orbits at five different
 * inclinations rather than three concentric ellipses. A fallback that still
 * looked like the old globe would mean the majority of visitors never saw the
 * thing the brief asked for.
 *
 * Sampled at a 1.7-degree step because this is inline markup in the HTML
 * payload rather than a buffer — a few thousand visible dots, which gzips to
 * almost nothing.
 */
function StaticGlobe({ className = "", style }: { className?: string; style?: React.CSSProperties }) {
  const a = rotationFacing(INDIA_CENTRE.lon);
  const cosA = Math.cos(a);
  const sinA = Math.sin(a);
  const cosT = Math.cos(INDIA_TILT_X);
  const sinT = Math.sin(INDIA_TILT_X);

  /** Rotate into the scene's pose and project orthographically onto the face. */
  const project = (lat: number, lon: number) => {
    const [x, y, z] = latLonToVec3(lat, lon, 1);
    const rx = x * cosA + z * sinA;
    const rz = -x * sinA + z * cosA;
    const ty = y * cosT - rz * sinT;
    const tz = y * sinT + rz * cosT;
    return { x: 100 + rx * 80, y: 100 - ty * 80, front: tz > 0, facing: tz };
  };

  // Three depth BANDS times two palettes rather than a per-dot radius, opacity
  // and colour. Each dot is then two attributes instead of five, and this
  // markup is inlined in the page's own HTML — at a couple of thousand dots
  // that difference is tens of kilobytes of the document, for a gradient no eye
  // can resolve at three steps or at thirty.
  //
  // A COASTAL dot is promoted one band, which is how the SVG gets the same
  // brighter-and-larger coastline the shader gets without a fourth attribute.
  const BANDS = [
    { min: 0.06, max: 0.33, r: 0.4, opacity: 0.34 },
    { min: 0.33, max: 0.66, r: 0.52, opacity: 0.62 },
    { min: 0.66, max: 1.01, r: 0.64, opacity: 0.94 },
  ];
  const cool: { x: string; y: string }[][] = BANDS.map(() => []);
  const warm: { x: string; y: string }[][] = BANDS.map(() => []);

  for (let lat = -78; lat <= 78; lat += 1.7) {
    // Constant spacing ON THE GROUND rather than in degrees: a fixed longitude
    // step piles points up at the poles, which on this projection is a bright
    // smear at the top and bottom of the disc.
    const step = 1.7 / Math.max(0.16, Math.cos((lat * Math.PI) / 180));
    for (let lon = -180; lon < 180; lon += step) {
      if (!isLand(lat, lon)) continue;
      const p = project(lat, lon);
      if (!p.front || p.facing < BANDS[0].min) continue;
      let band = BANDS.findIndex((b) => p.facing >= b.min && p.facing < b.max);
      if (band < 0) continue;
      // The ice caps drop a band and the coastline promotion does not reach
      // them — the same fix the shader's `polar` term makes, by the only means
      // three fixed bands have. Antarctica is coastal along its whole length,
      // so without this it lit the entire southern limb into the brightest
      // object at the bottom of the disc, on a continent with no lights on it.
      const polar = Math.abs(lat) > 56;
      if (polar) band = Math.max(0, band - 1);
      else if (isCoastal(lat, lon)) band = Math.min(BANDS.length - 1, band + 1);
      const d = angularDistanceDeg(lat, lon, INDIA_CENTRE.lat, INDIA_CENTRE.lon);
      (d < 20 ? warm : cool)[band].push({ x: p.x.toFixed(1), y: p.y.toFixed(1) });
    }
  }

  const hubs = CITIES.map((c) => ({ ...project(c.lat, c.lon), major: c.major })).filter(
    (d) => d.front
  );

  return (
    <svg viewBox="0 0 200 200" className={className} style={style} aria-hidden="true">
      <defs>
        <radialGradient id="ps-globe-atm" cx="50%" cy="50%" r="50%">
          <stop offset="52%" stopColor="#6aa6f2" stopOpacity="0" />
          <stop offset="79%" stopColor="#6aa6f2" stopOpacity="0.34" />
          <stop offset="100%" stopColor="#6aa6f2" stopOpacity="0" />
        </radialGradient>
        <radialGradient id="ps-globe-face" cx="42%" cy="36%" r="76%">
          <stop offset="0%" stopColor="#081426" />
          <stop offset="100%" stopColor="#01040b" />
        </radialGradient>
        {/* The cool city lights. A linear ramp across the disc rather than a
            real terminator — the SVG has no normals to light — but at this size
            it reads as the same picture. */}
        <linearGradient id="ps-globe-lights" x1="0" y1="1" x2="1" y2="0">
          <stop offset="0%" stopColor="#5a80c8" />
          <stop offset="55%" stopColor="#9dc2f3" />
          <stop offset="100%" stopColor="#e8f2ff" />
        </linearGradient>
        {/* India and its neighbourhood, the one warm thing on the planet. */}
        <linearGradient id="ps-globe-warm" x1="0" y1="1" x2="1" y2="0">
          <stop offset="0%" stopColor="#d99a4c" />
          <stop offset="60%" stopColor="#ffc27a" />
          <stop offset="100%" stopColor="#ffe3b4" />
        </linearGradient>
        {/* The lit limb: electric blue into cool white, with the gold kept to a
            sliver at the brightest part of it. */}
        <linearGradient id="ps-globe-rim" x1="0" y1="1" x2="1" y2="0">
          <stop offset="48%" stopColor="#5f9ae8" stopOpacity="0" />
          <stop offset="86%" stopColor="#bcd8ff" stopOpacity="0.72" />
          <stop offset="100%" stopColor="#ffd6a2" stopOpacity="0.8" />
        </linearGradient>
        <radialGradient id="ps-globe-india" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#ffc27a" stopOpacity="0.4" />
          <stop offset="55%" stopColor="#ffab55" stopOpacity="0.12" />
          <stop offset="100%" stopColor="#ff9c46" stopOpacity="0" />
        </radialGradient>
      </defs>

      <circle cx="100" cy="100" r="99" fill="url(#ps-globe-atm)" />
      <circle cx="100" cy="100" r="80" fill="url(#ps-globe-face)" />

      {BANDS.map((b, bi) => (
        <g key={`c${bi}`} fill="url(#ps-globe-lights)" opacity={b.opacity}>
          {cool[bi].map((d, i) => (
            <circle key={i} cx={d.x} cy={d.y} r={b.r} />
          ))}
        </g>
      ))}
      {BANDS.map((b, bi) => (
        <g key={`w${bi}`} fill="url(#ps-globe-warm)" opacity={Math.min(1, b.opacity + 0.06)}>
          {warm[bi].map((d, i) => (
            <circle key={i} cx={d.x} cy={d.y} r={b.r + 0.08} />
          ))}
        </g>
      ))}

      {/* The warm bloom over the subcontinent — the SVG's answer to the
          scene's India sprite. Placed at India's own projected position rather
          than at the middle of the disc. */}
      {(() => {
        const p = project(INDIA_CENTRE.lat, INDIA_CENTRE.lon);
        return <circle cx={p.x.toFixed(1)} cy={p.y.toFixed(1)} r="30" fill="url(#ps-globe-india)" />;
      })()}

      <g>
        {hubs.map((d, i) => (
          <circle
            key={i}
            cx={d.x.toFixed(1)}
            cy={d.y.toFixed(1)}
            r={d.major ? 1.6 : 1.0}
            fill="#ffe6c2"
            opacity={(0.4 + d.facing * 0.5).toFixed(2)}
          />
        ))}
      </g>

      <circle cx="100" cy="100" r="80" fill="none" stroke="#8fbdf6" strokeOpacity="0.34" strokeWidth="0.6" />
      {/* The lit limb. */}
      <circle cx="100" cy="100" r="80.5" fill="none" stroke="url(#ps-globe-rim)" strokeWidth="2.4" />

      {/* FIVE orbital paths at five different inclinations, sizes and
          eccentricities — the brief's "they should NOT be identical circles",
          in the only terms an inline SVG has. Drawn last so they pass in FRONT
          of the planet, which is half of what makes the set read as orbits
          rather than as a frame around the disc. */}
      <g stroke="#8dc0f8" fill="none" strokeWidth="0.45">
        <ellipse cx="100" cy="100" rx="93" ry="27" strokeOpacity="0.6" transform="rotate(-14 100 100)" />
        <ellipse cx="102" cy="99" rx="88" ry="52" strokeOpacity="0.4" transform="rotate(29 100 100)" />
        <ellipse cx="99" cy="101" rx="82" ry="70" strokeOpacity="0.26" transform="rotate(-56 100 100)" />
        <ellipse cx="100" cy="100" rx="97" ry="40" strokeOpacity="0.2" transform="rotate(68 100 100)" />
        <ellipse cx="101" cy="100" rx="84" ry="16" strokeOpacity="0.34" transform="rotate(8 100 100)" />
      </g>
    </svg>
  );
}
