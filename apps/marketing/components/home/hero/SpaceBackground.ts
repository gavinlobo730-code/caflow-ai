/**
 * Everything that is not the planet: stars, haze, distant bodies, debris, and
 * the sun.
 *
 * THE BACKGROUND'S JOB IS DEPTH, AND ITS DISCIPLINE IS RESTRAINT. §11 asks for
 * a sense of the universe and then spends most of its words limiting it; §12
 * forbids the purple galaxy of the earlier concept outright; §19 puts the
 * background last in the lighting hierarchy and says nothing may compete with
 * the Earth. So the palette here is navy, black and white with one cool blue
 * wash, and the brightest thing in the file is still dimmer than the planet's
 * rim.
 *
 * §14 IS ENFORCED IN CODE, NOT BY EYE. The left of the frame belongs to the
 * headline, and "do not put bright stars, cards or planets directly behind the
 * main typography" is a constraint a scatter will violate on its own the first
 * time it is reseeded. `leftFade` dims every scattered element by its
 * screen-side, so the copy column stays clean whatever the seed does.
 */

import { hash01, hashRange } from "./math";
import {
  POINT_VERTEX,
  STAR_FRAGMENT,
  SPRITE_VERTEX,
  FLARE_FRAGMENT,
  HAZE_FRAGMENT,
  BODY_VERTEX,
  BODY_FRAGMENT,
} from "./shaders";

type Vec3 = [number, number, number];

/**
 * How much of an element survives, by how far left it sits.
 *
 * World x is negative to screen-left. Full strength from the centre rightward,
 * fading to a quarter by the far left where the headline sits. Not zero:
 * §14 allows "very subtle stars" there, and a hard cut would draw a visible
 * vertical edge through the starfield.
 */
function leftFade(x: number, span: number): number {
  const t = (x + span) / (span * 1.15);
  return 0.25 + 0.75 * Math.min(1, Math.max(0, t));
}

/** The starfield. One Points, a few hundred stars, most of them faint. */
function createStars(THREE: any, count: number, radius: number) {
  const pos = new Float32Array(count * 3);
  const col = new Float32Array(count * 3);
  const size = new Float32Array(count);
  const glow = new Float32Array(count);

  for (let i = 0; i < count; i++) {
    // Uniform on the sphere, then pushed to the far half only: a star drawn in
    // front of the planet is not a star, it is a dust speck on the lens.
    const u = hash01(i * 3 + 1);
    const v = hash01(i * 3 + 2);
    const th = u * Math.PI * 2;
    const ph = Math.acos(2 * v - 1);
    const r = radius * (0.75 + hash01(i * 3 + 5) * 0.25);
    const x = r * Math.sin(ph) * Math.cos(th);
    const y = r * Math.sin(ph) * Math.sin(th);
    const z = -Math.abs(r * Math.cos(ph));

    pos[i * 3] = x;
    pos[i * 3 + 1] = y;
    pos[i * 3 + 2] = z;

    // A few warm and a few faintly blue, the rest white. Real starfields are
    // not monochrome and an all-white one reads as a texture.
    const tint = hash01(i * 7 + 11);
    let c: Vec3 = [1, 1, 1];
    if (tint > 0.93) c = [1.0, 0.86, 0.72];
    else if (tint > 0.82) c = [0.78, 0.87, 1.0];
    col[i * 3] = c[0];
    col[i * 3 + 1] = c[1];
    col[i * 3 + 2] = c[2];

    const bright = Math.pow(hash01(i * 11 + 13), 2.6);
    size[i] = radius * (0.0016 + bright * 0.004);
    glow[i] = (0.14 + bright * 0.86) * leftFade(x, radius);
  }

  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  g.setAttribute("aColor", new THREE.BufferAttribute(col, 3));
  g.setAttribute("aSize", new THREE.BufferAttribute(size, 1));
  g.setAttribute("aGlow", new THREE.BufferAttribute(glow, 1));

  const uniforms = { uScale: { value: 600 }, uOpacity: { value: 0.9 } };
  const mesh = new THREE.Points(
    g,
    new THREE.ShaderMaterial({
      uniforms,
      vertexShader: POINT_VERTEX,
      fragmentShader: STAR_FRAGMENT,
      transparent: true,
      depthWrite: false,
      depthTest: false,
      blending: THREE.AdditiveBlending,
    })
  );
  mesh.renderOrder = 0;
  return { mesh, scale: uniforms.uScale };
}

/** A flat additive billboard. Used for the haze and the flare. */
function billboard(
  THREE: any,
  fragment: string,
  color: number,
  intensity: number,
  size: [number, number],
  at: Vec3,
  renderOrder: number
) {
  const mesh = new THREE.Mesh(
    new THREE.PlaneGeometry(size[0], size[1]),
    new THREE.ShaderMaterial({
      uniforms: {
        uColor: { value: new THREE.Color(color) },
        uIntensity: { value: intensity },
      },
      vertexShader: SPRITE_VERTEX,
      fragmentShader: fragment,
      transparent: true,
      depthWrite: false,
      depthTest: false,
      blending: THREE.AdditiveBlending,
    })
  );
  mesh.position.set(at[0], at[1], at[2]);
  mesh.renderOrder = renderOrder;
  return mesh;
}

/**
 * A moon or a distant planet.
 *
 * Low segment counts on purpose: at the size these occupy on screen a 32x24
 * sphere is already smooth, and §13 wants them subtle enough that detail would
 * be wasted anyway.
 */
function body(
  THREE: any,
  opts: {
    radius: number;
    at: Vec3;
    color: number;
    sun: Vec3;
    ambient?: number;
    rimGain?: number;
    segments?: number;
    renderOrder?: number;
  }
) {
  const s = opts.segments ?? 32;
  const mesh = new THREE.Mesh(
    new THREE.SphereGeometry(opts.radius, s, Math.round(s * 0.75)),
    new THREE.ShaderMaterial({
      uniforms: {
        uColor: { value: new THREE.Color(opts.color) },
        uSun: { value: new THREE.Vector3(...opts.sun).normalize() },
        uAmbient: { value: opts.ambient ?? 0.08 },
        uRimGain: { value: opts.rimGain ?? 0.5 },
      },
      vertexShader: BODY_VERTEX,
      fragmentShader: BODY_FRAGMENT,
    })
  );
  mesh.position.set(opts.at[0], opts.at[1], opts.at[2]);
  mesh.renderOrder = opts.renderOrder ?? 0;
  return mesh;
}

/**
 * Debris.
 *
 * Icosahedra with their vertices pushed about, which is the cheapest thing
 * that reads as rock rather than as a ball. They sit LOW and toward the
 * camera: §13 allows them "near the lower portion of the composition", and in
 * front is where they do their job, because something crossing in front of the
 * planet is the clearest depth cue in the scene.
 */
function createDebris(THREE: any, count: number, sun: Vec3, span: number) {
  const meshes: any[] = [];
  for (let i = 0; i < count; i++) {
    const r = hashRange(i * 5 + 1, 0.022, 0.085);
    const geo = new THREE.IcosahedronGeometry(r, 0);
    const p = geo.attributes.position;
    for (let v = 0; v < p.count; v++) {
      const k = 0.62 + hash01(i * 97 + v * 7) * 0.76;
      p.setXYZ(v, p.getX(v) * k, p.getY(v) * k, p.getZ(v) * k);
    }
    geo.computeVertexNormals();

    // Lower half, spread wide, in front of the planet.
    const x = hashRange(i * 5 + 2, -span * 0.95, span * 0.8);
    const y = hashRange(i * 5 + 3, -span * 0.78, -span * 0.12);
    const z = hashRange(i * 5 + 4, 0.6, 2.4);

    const mesh = new THREE.Mesh(
      geo,
      new THREE.ShaderMaterial({
        uniforms: {
          uColor: { value: new THREE.Color(0x1a2130) },
          uSun: { value: new THREE.Vector3(...sun).normalize() },
          uAmbient: { value: 0.16 },
          uRimGain: { value: 0.85 * leftFade(x, span) },
        },
        vertexShader: BODY_VERTEX,
        fragmentShader: BODY_FRAGMENT,
      })
    );
    mesh.position.set(x, y, z);
    mesh.rotation.set(
      hashRange(i * 5 + 6, 0, Math.PI),
      hashRange(i * 5 + 7, 0, Math.PI),
      hashRange(i * 5 + 8, 0, Math.PI)
    );
    mesh.renderOrder = 7;
    meshes.push(mesh);
  }
  return meshes;
}

export type SpaceOptions = {
  sun: Vec3;
  /** Planet radius, so everything can be expressed relative to it. */
  radius: number;
  cameraZ: number;
};

export function createSpaceBackground(THREE: any, opts: SpaceOptions) {
  const meshes: any[] = [];
  const scales: Array<{ value: number }> = [];
  const span = opts.radius * 2.6;

  // ── Haze ─────────────────────────────────────────────────────────────────
  // One cool wash behind the planet so the frame is not flat black at its
  // edge. §12's whole point: a wash, not a galaxy.
  //
  // ⚠️ IT MUST DIE OUT WELL INSIDE THE CANVAS, AND THAT IS NOT A TASTE
  // JUDGEMENT. The canvas is hung 134% x 138% of its grid cell and is still
  // narrower than the viewport, so it has visible EDGES — at 1440x900 its left
  // edge lands at x=552, right through the middle of the hero. A wash sized to
  // fill the frame therefore ends in a hard vertical line down the page, which
  // is exactly what the first build of this did: a plane 6.2 units tall at
  // z=-3.2 covers a 5.97-unit frustum, so its gradient was still at half
  // strength where the canvas stopped.
  //
  // Sized to the PLANET instead — a glow around the globe rather than a
  // background for the frame — so it is near zero long before any edge. Half
  // the intensity too: §19 puts the background last, and the first version
  // lifted the whole scene into mid-navy when §18 asks for 70-80% near-black.
  meshes.push(
    billboard(
      THREE, HAZE_FRAGMENT, 0x14305f, 0.30,
      [opts.radius * 4.4, opts.radius * 4.0], [0.05, -0.05, -2.6], 0
    )
  );

  // ── Stars ────────────────────────────────────────────────────────────────
  const stars = createStars(THREE, 680, opts.radius * 9);
  meshes.push(stars.mesh);
  scales.push(stars.scale);

  // ── The sun, at the limb ─────────────────────────────────────────────────
  // Placed to agree with the view-space sun direction the planet and every
  // body are lit by, so the flare is where the light is actually coming from.
  // A flare that disagrees with its own shading is the tell that a scene was
  // assembled rather than lit.
  const [sx, sy] = opts.sun;
  const sl = Math.hypot(sx, sy) || 1;
  meshes.push(
    billboard(
      THREE, FLARE_FRAGMENT, 0xffd9a8, 0.85,
      [opts.radius * 3.4, opts.radius * 1.5],
      [(sx / sl) * opts.radius * 1.02, (sy / sl) * opts.radius * 1.02, 0.35],
      8
    )
  );

  // ── Distant bodies ───────────────────────────────────────────────────────
  // A moon, upper right, matching the reference. Small and well clear of the
  // headline; §13 forbids a large planet behind the typography.
  meshes.push(
    body(THREE, {
      radius: opts.radius * 0.115,
      at: [opts.radius * 1.92, opts.radius * 1.12, -1.9],
      color: 0x8e9099,
      sun: opts.sun,
      ambient: 0.1,
      rimGain: 0.25,
      renderOrder: 0,
    })
  );
  // A far, cold one, low right, barely there.
  meshes.push(
    body(THREE, {
      radius: opts.radius * 0.055,
      at: [opts.radius * 1.55, -opts.radius * 1.34, -3.4],
      color: 0x33507e,
      sun: opts.sun,
      ambient: 0.14,
      rimGain: 0.35,
      segments: 24,
      renderOrder: 0,
    })
  );

  // ── The near horizon ─────────────────────────────────────────────────────
  // A body so large and so close that only its lit upper limb is in frame.
  // This is the strongest depth cue available: it establishes that the camera
  // is somewhere, in a place with something else in it.
  //
  // ⚠️ TWO THINGS ABOUT IT ARE CORRECTIONS, AND BOTH WERE VISIBLE FAILURES.
  //
  // It is BOTTOM RIGHT, though the reference puts it bottom left. The canvas
  // does not cover the viewport — it starts at x=552 on a 1440px screen — so
  // "bottom left of the canvas" is underneath the stats row, not out at the
  // page margin. The first build put it there and a pale blue wedge sat across
  // "11+ Modules" and "4 Separate tools". §14 reserves the left for the copy,
  // and the canvas's own geometry means honouring that requires the mirror of
  // the reference rather than a copy of it.
  //
  // The rim was 1.5 and is 0.34. At 1.5 this was the BRIGHTEST object in the
  // scene, which inverts §19's hierarchy outright — it is a foreground
  // silhouette, and a silhouette is defined by being dark.
  meshes.push(
    body(THREE, {
      radius: opts.radius * 3.0,
      at: [opts.radius * 2.1, -opts.radius * 3.95, 1.4],
      color: 0x060b16,
      sun: opts.sun,
      ambient: 0.1,
      rimGain: 0.34,
      segments: 64,
      renderOrder: 7,
    })
  );

  // ── Debris ───────────────────────────────────────────────────────────────
  for (const m of createDebris(THREE, 16, opts.sun, span)) meshes.push(m);

  return { meshes, scales };
}
