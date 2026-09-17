/**
 * The planet: two generated textures and the sphere that samples them.
 *
 * THE WHOLE ARGUMENT OF THIS FILE IS THAT THE LIGHTS MUST CARRY THE PICTURE.
 * The globe this replaced put the continents on the surface as a field of
 * evenly-spaced dots and read, correctly, as "a flat dotted world map wrapped
 * onto a sphere". Two things were wrong with it and only one was density.
 *
 *   1. A uniform scatter has no contrast, and contrast is what a night Earth
 *      IS — see cities.ts. Fixed by generating the lights from population
 *      centres, so the Sahara and Siberia come out dark because nothing put
 *      lights there, not because anything masked them off.
 *
 *   2. Points cannot hold a coastline at any density. Africa's outline has to
 *      come from a FILL, so the surface samples a land texture underneath and
 *      the lights sit on top of it.
 *
 * Both textures are built once, on the client, into an offscreen canvas. No
 * image is fetched: direct egress is refused at this environment's proxy, so
 * NASA's Black Marble was never available, and a committed 8MB PNG would cost
 * every visitor more than the whole rest of the page. Generating from the
 * committed coastline mask plus a city table is a few milliseconds and about
 * 50KB of source.
 *
 * UV CONVENTION, AND IT IS FREE. Three's SphereGeometry lays out u as
 * (lon+180)/360 and pushes 1-v, so the image's top row is the north pole —
 * which is exactly how landmask.ts is packed (row 0 at +90, column 0 at -180).
 * The canvases are drawn in that same layout, so nothing anywhere remaps.
 */

import { isLand, MASK_W, MASK_H } from "../landmask";
import { ALL_LIGHTS, isSubcontinental, type Light } from "./cities";
import { hash01 } from "./math";
import { EARTH_VERTEX, EARTH_FRAGMENT } from "./shaders";

/**
 * Texture size.
 *
 * 2048x1024 is 8MB on the GPU and about 0.18 degrees a pixel, roughly 19km at
 * the equator — finer than any glow drawn into it. 4096 would be 32MB for
 * detail nothing here carries, and §26 asks for no unnecessarily huge
 * textures. The land mask is coarser again and is upscaled, which is fine
 * because a coastline wants to be slightly soft at this scale anyway.
 */
const TEX_W = 2048;
const TEX_H = 1024;

/** Palette. Everything is dark; §18 asks for 70-80% near-black and navy. */
export const PALETTE = {
  ocean: 0x02060f,
  land: 0x121d33,
  rim: 0x3d86ff,
  /** The world's cities: amber, the colour of sodium light from orbit. */
  warmWorld: [255, 158, 72] as [number, number, number],
  /**
   * India's: champagne. Paler than the world's amber so it reads as brighter
   * without being a different colour story.
   *
   * ⚠️ IT WAS [255, 206, 150] AND THAT DESATURATED TO WHITE. The lights are
   * composited additively — halo, then halo again, then grain — so a channel
   * that reaches 255 stops accumulating while the others keep climbing. Start
   * near-white and every overlap converges on pure white, which is precisely
   * what §6 means by India looking "pasted onto the globe": champagne is a
   * HUE, and the subcontinent had lost it while still being the brightest
   * region. Pulled back toward amber, with the peaks below so the sum has
   * somewhere to go before it clips.
   */
  warmIndia: [255, 198, 132] as [number, number, number],
};

function lonLatToPixel(lat: number, lon: number): [number, number] {
  return [((lon + 180) / 360) * TEX_W, ((90 - lat) / 180) * TEX_H];
}

function makeCanvas(w: number, h: number): HTMLCanvasElement {
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  return c;
}

/**
 * The land/ocean fill.
 *
 * Drawn at the mask's own 720x360 and scaled up with a slight blur, because a
 * nearest-neighbour coastline at 0.5 degrees shows its staircase on a sphere
 * this large. The blur is under two pixels at the upscaled size — enough to
 * kill the stair, not enough to eat a peninsula.
 */
function buildLandTexture(THREE: any) {
  const src = makeCanvas(MASK_W, MASK_H);
  const sctx = src.getContext("2d")!;
  const img = sctx.createImageData(MASK_W, MASK_H);

  for (let y = 0; y < MASK_H; y++) {
    const lat = 90 - (y + 0.5) * (180 / MASK_H);
    for (let x = 0; x < MASK_W; x++) {
      const lon = -180 + (x + 0.5) * (360 / MASK_W);
      const v = isLand(lat, lon) ? 255 : 0;
      const i = (y * MASK_W + x) * 4;
      img.data[i] = v;
      img.data[i + 1] = v;
      img.data[i + 2] = v;
      img.data[i + 3] = 255;
    }
  }
  sctx.putImageData(img, 0, 0);

  const out = makeCanvas(MASK_W * 2, MASK_H * 2);
  const octx = out.getContext("2d")!;
  octx.imageSmoothingEnabled = true;
  octx.imageSmoothingQuality = "high";
  octx.filter = "blur(1.15px)";
  octx.drawImage(src, 0, 0, out.width, out.height);

  const tex = new THREE.CanvasTexture(out);
  tex.wrapS = THREE.RepeatWrapping;
  tex.wrapT = THREE.ClampToEdgeWrapping;
  tex.minFilter = THREE.LinearFilter;
  tex.magFilter = THREE.LinearFilter;
  tex.needsUpdate = true;
  return tex;
}

/** Additive radial splat, wrapped at the date line so no city is cut in half. */
function splat(
  ctx: CanvasRenderingContext2D,
  px: number,
  py: number,
  radius: number,
  rgb: [number, number, number],
  peak: number
) {
  for (const dx of [-TEX_W, 0, TEX_W]) {
    const x = px + dx;
    if (x + radius < 0 || x - radius > TEX_W) continue;
    const g = ctx.createRadialGradient(x, py, 0, x, py, radius);
    const [r, gg, b] = rgb;
    g.addColorStop(0, `rgba(${r},${gg},${b},${peak})`);
    g.addColorStop(0.35, `rgba(${r},${gg},${b},${peak * 0.34})`);
    g.addColorStop(1, `rgba(${r},${gg},${b},0)`);
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(x, py, radius, 0, Math.PI * 2);
    ctx.fill();
  }
}

/**
 * The night lights.
 *
 * Three passes, and each answers a different half of what a night Earth looks
 * like from orbit.
 *
 *   HALOS  one soft additive splat per population centre. This is the shape of
 *          the lit world — the deltas and the coasts — and on its own it is a
 *          smooth airbrush with no texture.
 *
 *   GRAIN  discrete single-pixel lights scattered with probability read back
 *          from the halo pass. This is what makes it read as thousands of
 *          separate places rather than a glow, and it is the pass that answers
 *          §5's "do NOT make every dot identical": each grain takes its own
 *          brightness, and the probability of there being one at all falls off
 *          with distance from a centre.
 *
 *   RURAL  a very sparse, very dim scatter over all land, so a continent with
 *          no city in the table is not a black hole. Held low enough that it
 *          never competes with a real centre.
 *
 * The grain reads its probability back out of the halo pass with one
 * getImageData rather than keeping a second density grid, so the two cannot
 * disagree about where the lit regions are. Overlapping conurbations then get
 * denser grain for free, which is the right answer and would have needed
 * special-casing with a separate field.
 */
function buildLightsTexture(THREE: any) {
  const c = makeCanvas(TEX_W, TEX_H);
  const ctx = c.getContext("2d", { willReadFrequently: true })!;
  ctx.fillStyle = "#000000";
  ctx.fillRect(0, 0, TEX_W, TEX_H);
  ctx.globalCompositeOperation = "lighter";

  // ── Pass 1: halos ────────────────────────────────────────────────────────
  const halo = (l: Light) => {
    const [px, py] = lonLatToPixel(l.lat, l.lon);
    const india = isSubcontinental(l);
    const rgb = india ? PALETTE.warmIndia : PALETTE.warmWorld;
    // §6: India is "slightly brighter", an accent and not a mass. 1.25x, and
    // the radius is NOT scaled with it — a wider halo is what would turn the
    // subcontinent into the solid gold shape the brief rules out.
    //
    // The caps leave headroom. At 0.85 the inner splat of a w=3 city was
    // already three-quarters of the way to saturation before the grain pass
    // added anything, so every dense conurbation clipped to white regardless
    // of the colour it was given.
    const gain = india ? 1.18 : 1.0;
    splat(ctx, px, py, 4.5 + l.w * 9.5, rgb, Math.min(0.45, 0.09 * l.w * gain));
    splat(ctx, px, py, 1.6 + l.w * 2.6, rgb, Math.min(0.6, 0.16 * l.w * gain));
  };
  for (const l of ALL_LIGHTS) halo(l);

  // ── Pass 2: grain ────────────────────────────────────────────────────────
  const buf = ctx.getImageData(0, 0, TEX_W, TEX_H);
  const d = buf.data;

  const GRAIN_CANDIDATES = 150000;
  for (let i = 0; i < GRAIN_CANDIDATES; i++) {
    const u = hash01(i * 3 + 1);
    // Cosine-distributed latitude: an equirectangular map stretches the poles,
    // so a uniform y would crowd grain into Greenland and Antarctica.
    const v = Math.acos(1 - 2 * hash01(i * 3 + 2)) / Math.PI;
    const px = Math.floor(u * TEX_W);
    const py = Math.floor(v * TEX_H);
    if (py < 0 || py >= TEX_H) continue;

    const lat = 90 - (py / TEX_H) * 180;
    const lon = -180 + (px / TEX_W) * 360;
    if (!isLand(lat, lon)) continue;

    const idx = (py * TEX_W + px) * 4;
    // Density from the halo pass, 0..1 off the red channel.
    const density = d[idx] / 255;
    if (density < 0.02) continue;
    // Squared, so grain concentrates hard into the cores and thins out fast.
    if (hash01(i * 3 + 7) > density * density * 1.9) continue;

    const india = lat > 5 && lat < 36 && lon > 66 && lon < 93;
    const rgb = india ? PALETTE.warmIndia : PALETTE.warmWorld;
    const b = 0.45 + hash01(i * 5 + 11) * 0.55;
    for (let k = 0; k < 3; k++) {
      d[idx + k] = Math.min(255, d[idx + k] + rgb[k] * b);
    }
  }

  // ── Pass 3: rural ────────────────────────────────────────────────────────
  const RURAL_CANDIDATES = 60000;
  for (let i = 0; i < RURAL_CANDIDATES; i++) {
    const u = hash01(i * 7 + 101);
    const v = Math.acos(1 - 2 * hash01(i * 7 + 103)) / Math.PI;
    const px = Math.floor(u * TEX_W);
    const py = Math.floor(v * TEX_H);
    if (py < 0 || py >= TEX_H) continue;

    const lat = 90 - (py / TEX_H) * 180;
    const lon = -180 + (px / TEX_W) * 360;
    if (!isLand(lat, lon)) continue;
    // The genuinely empty latitudes stay empty. Without this the polar
    // stretch alone puts a believable-looking scatter across Antarctica.
    if (Math.abs(lat) > 66) continue;
    if (hash01(i * 7 + 107) > 0.42) continue;

    const idx = (py * TEX_W + px) * 4;
    const b = 0.1 + hash01(i * 7 + 109) * 0.16;
    for (let k = 0; k < 3; k++) {
      d[idx + k] = Math.min(255, d[idx + k] + PALETTE.warmWorld[k] * b);
    }
  }

  ctx.globalCompositeOperation = "source-over";
  ctx.putImageData(buf, 0, 0);

  const tex = new THREE.CanvasTexture(c);
  tex.wrapS = THREE.RepeatWrapping;
  tex.wrapT = THREE.ClampToEdgeWrapping;
  tex.minFilter = THREE.LinearFilter;
  tex.magFilter = THREE.LinearFilter;
  tex.needsUpdate = true;
  return tex;
}

export type EarthOptions = {
  /** View-space direction the light comes from. */
  sun: [number, number, number];
  radius: number;
};

/**
 * Build the planet.
 *
 * Returns the mesh plus the uniforms, because the scene owns the animation
 * loop that does not exist yet — every uniform here is already a uniform
 * rather than a constant baked into the GLSL, so making this move later is
 * assigning to `.value` rather than editing a shader.
 */
export function createEarthSurface(THREE: any, opts: EarthOptions) {
  const geo = new THREE.SphereGeometry(opts.radius, 128, 96);

  const uniforms = {
    uLand: { value: buildLandTexture(THREE) },
    uLights: { value: buildLightsTexture(THREE) },
    uOcean: { value: new THREE.Color(PALETTE.ocean) },
    uLandCol: { value: new THREE.Color(PALETTE.land) },
    uRim: { value: new THREE.Color(PALETTE.rim) },
    uSun: { value: new THREE.Vector3(...opts.sun).normalize() },
    uShadow: { value: 0.44 },
    uLightGain: { value: 1.9 },
    uNightFloor: { value: 0.5 },
  };

  const mat = new THREE.ShaderMaterial({
    uniforms,
    vertexShader: EARTH_VERTEX,
    fragmentShader: EARTH_FRAGMENT,
  });

  const mesh = new THREE.Mesh(geo, mat);
  mesh.renderOrder = 2;
  return { mesh, uniforms };
}
