"use client";


import { useEffect, useRef, useState } from "react";
import { loadThree, canRunGlobe } from "./three-loader";
import { CITIES, ARCS, INDIA_CENTRE } from "./geography";

/**
 * The hero globe.
 *
 * This is the React port of the WebGL scene that used to live inline in
 * public/practicesync-homepage.html, EVOLVED rather than replaced, which is
 * what the redesign brief asks for (§2: "The existing globe concept is good and
 * should be evolved, not discarded"). What changed:
 *
 *   - the abstract icosahedron became an actual globe with India facing the
 *     camera, built from the real city coordinates in ./geography.ts;
 *   - the point cloud is brighter over India, so the subcontinent reads without
 *     a coastline texture nobody here could verify;
 *   - great-circle arcs run between the cities with a pulse travelling along
 *     them — the "fine network points, orbital trails" of the brief's §2;
 *   - the three orbital rings and the inward-drifting particles are kept
 *     unchanged, because they are what made the original feel alive.
 *
 * EVERY PERFORMANCE GUARD FROM THE ORIGINAL IS KEPT, and they are not optional.
 * Measured on the page this replaces: with the globe running the hero held
 * 11–14fps and blocking three.min.js restored it to 60, exactly matching the
 * React pages. The brief then asks for orbits, floating cards and parallax ON
 * TOP of that. So:
 *
 *   - the scene is capped to ~30fps (GLOBE_FRAME_MS). It is a slow continuous
 *     drift; 30 and 60 are indistinguishable and it halves the GPU cost.
 *   - it goes quiet for SCROLL_QUIET_MS after every scroll event, because the
 *     hero is the first screenful and therefore exactly where scrolling starts,
 *     and those are the frames the scroll itself needs.
 *   - it stops entirely once the hero leaves the viewport, or the tab is
 *     hidden.
 *   - the render resolution is capped well below native device pixels: this is
 *     a soft glowy object, so a lower internal resolution is visually
 *     near-identical and dramatically cheaper on the fill-rate-bound
 *     integrated GPUs in ordinary laptops.
 *   - the scroll fade is plain CSS opacity and is applied BEFORE the skip
 *     guards, so the globe still dissolves smoothly during the very scroll in
 *     which its WebGL work is being skipped.
 *
 * `canRunGlobe()` decides whether any of this happens. When it says no —
 * reduced motion, a phone, ≤4 GB of memory, no WebGL context — three.min.js is
 * never even downloaded and the static SVG below is the hero visual. It is
 * rendered either way and simply never covered, which is also what keeps the
 * hero from shifting while the scene loads.
 */

const GLOBE_FRAME_MS = 33;
const SCROLL_QUIET_MS = 150;
const PARTICLE_COUNT = 150;
const SURFACE_POINTS = 1400;
const R = 1;

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
 * With the mapping above, a point at longitude L sits at (180 − (L + 180))
 * degrees measured from +X toward +Z, i.e. at −L. Rotating the group by `a`
 * about +Y moves a point at angle φ to φ − a, and the camera looks down −Z at
 * the +Z face (φ = 90°). So −L − a = 90, hence a = −(L + 90).
 */
function rotationFacing(lon: number): number {
  return (-(lon + 90) * Math.PI) / 180;
}

/** Angular distance in degrees between two lat/lon points. */
function angularDistanceDeg(
  aLat: number,
  aLon: number,
  bLat: number,
  bLon: number
): number {
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
): Float32Array {
  const dot = Math.max(-1, Math.min(1, a[0] * b[0] + a[1] * b[1] + a[2] * b[2]));
  const omega = Math.acos(dot);
  const sinO = Math.sin(omega);
  const out = new Float32Array((segments + 1) * 3);
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
    out[i * 3] = x * lift;
    out[i * 3 + 1] = y * lift;
    out[i * 3 + 2] = z * lift;
  }
  return out;
}

export function HeroGlobe({ className = "" }: { className?: string }) {
  const stageRef = useRef<HTMLDivElement | null>(null);
  const fadeRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [live, setLive] = useState(false);

  // The scroll-driven dissolve. Runs in BOTH modes — the static SVG has to
  // fade out over the seam just as the canvas does, or the fallback visitor
  // gets a globe that sits on top of the next section.
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
    let raf = 0;
    let renderer: any = null;
    const disposables: any[] = [];

    loadThree()
      .then((THREE) => {
        const canvas = canvasRef.current;
        const stage = stageRef.current;
        if (disposed || !canvas || !stage) return;

        const RENDER_DPR = Math.min(window.devicePixelRatio || 1, 1.25);
        let w = stage.clientWidth || 600;
        let h = stage.clientHeight || 600;

        renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
        renderer.setPixelRatio(RENDER_DPR);
        renderer.setSize(w, h, false);

        const scene = new THREE.Scene();
        const camera = new THREE.PerspectiveCamera(40, w / h, 0.1, 100);
        camera.position.set(0, 0, 5.2);

        // Two nested groups so the India-facing spin (Y) is applied before the
        // viewing tilt (X). A single Euler would compose them in whichever
        // order the rotation order happens to be, which is exactly the kind of
        // thing that silently puts the Pacific in the middle.
        const tilt = new THREE.Group();
        tilt.rotation.x = 0.3;
        const spin = new THREE.Group();
        const baseY = rotationFacing(INDIA_CENTRE.lon);
        spin.rotation.y = baseY;
        tilt.add(spin);
        scene.add(tilt);

        // ── Surface point cloud ────────────────────────────────────────────
        // Fibonacci sphere: evenly spaced without clustering at the poles,
        // which a naive random lat/lon does. Points near India are painted
        // brighter, which is what makes the subcontinent legible with no
        // texture and no coastline anybody would have had to invent.
        const surfacePos = new Float32Array(SURFACE_POINTS * 3);
        const surfaceCol = new Float32Array(SURFACE_POINTS * 3);
        const golden = Math.PI * (3 - Math.sqrt(5));
        for (let i = 0; i < SURFACE_POINTS; i++) {
          const y = 1 - (i / (SURFACE_POINTS - 1)) * 2;
          const radius = Math.sqrt(Math.max(0, 1 - y * y));
          const theta = golden * i;
          const x = Math.cos(theta) * radius;
          const z = Math.sin(theta) * radius;
          surfacePos[i * 3] = x * R * 1.002;
          surfacePos[i * 3 + 1] = y * R * 1.002;
          surfacePos[i * 3 + 2] = z * R * 1.002;

          const lat = (Math.asin(Math.max(-1, Math.min(1, y))) * 180) / Math.PI;
          const lon = (Math.atan2(z, -x) * 180) / Math.PI - 180;
          const d = angularDistanceDeg(lat, ((lon % 360) + 540) % 360 - 180, INDIA_CENTRE.lat, INDIA_CENTRE.lon);
          const near = Math.max(0, 1 - d / 30);
          surfaceCol[i * 3] = 0.42 + near * 0.42;
          surfaceCol[i * 3 + 1] = 0.53 + near * 0.35;
          surfaceCol[i * 3 + 2] = 0.82 + near * 0.18;
        }
        const surfaceGeo = new THREE.BufferGeometry();
        surfaceGeo.setAttribute("position", new THREE.BufferAttribute(surfacePos, 3));
        surfaceGeo.setAttribute("color", new THREE.BufferAttribute(surfaceCol, 3));
        const surfaceMat = new THREE.PointsMaterial({
          size: 0.028,
          vertexColors: true,
          transparent: true,
          opacity: 0.95,
          sizeAttenuation: true,
          depthWrite: false,
        });
        spin.add(new THREE.Points(surfaceGeo, surfaceMat));
        disposables.push(surfaceGeo, surfaceMat);

        // ── Graticule ──────────────────────────────────────────────────────
        // One merged LineSegments rather than seventeen Line objects: same
        // picture, one draw call.
        const grat: number[] = [];
        const pushSeg = (
          a: [number, number, number],
          b: [number, number, number]
        ) => {
          grat.push(a[0], a[1], a[2], b[0], b[1], b[2]);
        };
        for (const lat of [-60, -30, 0, 30, 60]) {
          for (let lon = -180; lon < 180; lon += 6) {
            pushSeg(
              latLonToVec3(lat, lon, R * 1.001),
              latLonToVec3(lat, lon + 6, R * 1.001)
            );
          }
        }
        for (let lon = -180; lon < 180; lon += 30) {
          for (let lat = -84; lat < 84; lat += 6) {
            pushSeg(
              latLonToVec3(lat, lon, R * 1.001),
              latLonToVec3(lat + 6, lon, R * 1.001)
            );
          }
        }
        const gratGeo = new THREE.BufferGeometry();
        gratGeo.setAttribute(
          "position",
          new THREE.BufferAttribute(new Float32Array(grat), 3)
        );
        const gratMat = new THREE.LineBasicMaterial({
          color: 0x6f8fe0,
          transparent: true,
          opacity: 0.3,
        });
        spin.add(new THREE.LineSegments(gratGeo, gratMat));
        disposables.push(gratGeo, gratMat);

        // ── Solid core, so the far side of the globe is occluded ───────────
        const coreGeo = new THREE.IcosahedronGeometry(R * 0.985, 4);
        const coreMat = new THREE.MeshBasicMaterial({
          color: 0x121e42,
          transparent: true,
          opacity: 0.95,
        });
        spin.add(new THREE.Mesh(coreGeo, coreMat));
        disposables.push(coreGeo, coreMat);

        // ── City hubs ──────────────────────────────────────────────────────
        const hubVecs = CITIES.map((c) => latLonToVec3(c.lat, c.lon, R * 1.012));
        const hubPos = new Float32Array(CITIES.length * 3);
        const hubSize = new Float32Array(CITIES.length);
        CITIES.forEach((c, i) => {
          hubPos[i * 3] = hubVecs[i][0];
          hubPos[i * 3 + 1] = hubVecs[i][1];
          hubPos[i * 3 + 2] = hubVecs[i][2];
          hubSize[i] = c.major ? 1 : 0.6;
        });
        const hubGeo = new THREE.BufferGeometry();
        hubGeo.setAttribute("position", new THREE.BufferAttribute(hubPos, 3));
        const hubMat = new THREE.PointsMaterial({
          color: 0xcfe0ff,
          size: 0.05,
          transparent: true,
          opacity: 0.95,
          sizeAttenuation: true,
          blending: THREE.AdditiveBlending,
          depthWrite: false,
        });
        spin.add(new THREE.Points(hubGeo, hubMat));
        disposables.push(hubGeo, hubMat);

        // ── Network arcs, and a pulse travelling along each ─────────────────
        const arcSegments = 40;
        const arcCurves: Float32Array[] = [];
        ARCS.forEach(([ai, bi]) => {
          const pts = arcPoints(hubVecs[ai], hubVecs[bi], arcSegments, 0.16);
          arcCurves.push(pts);
          const g = new THREE.BufferGeometry();
          g.setAttribute("position", new THREE.BufferAttribute(pts, 3));
          const m = new THREE.LineBasicMaterial({
            color: 0x9dbaff,
            transparent: true,
            opacity: 0.7,
          });
          spin.add(new THREE.Line(g, m));
          disposables.push(g, m);
        });

        const pulsePos = new Float32Array(arcCurves.length * 3);
        const pulsePhase = arcCurves.map((_, i) => (i / arcCurves.length) * 1);
        const pulseGeo = new THREE.BufferGeometry();
        pulseGeo.setAttribute("position", new THREE.BufferAttribute(pulsePos, 3));
        const pulseMat = new THREE.PointsMaterial({
          color: 0xe8f0ff,
          size: 0.055,
          transparent: true,
          opacity: 0.9,
          sizeAttenuation: true,
          blending: THREE.AdditiveBlending,
          depthWrite: false,
        });
        spin.add(new THREE.Points(pulseGeo, pulseMat));
        disposables.push(pulseGeo, pulseMat);

        // ── Atmosphere glow ────────────────────────────────────────────────
        const glowCanvas = document.createElement("canvas");
        glowCanvas.width = glowCanvas.height = 128;
        const gctx = glowCanvas.getContext("2d");
        if (gctx) {
          const grad = gctx.createRadialGradient(64, 64, 0, 64, 64, 64);
          grad.addColorStop(0, "rgba(96,132,232,0.8)");
          grad.addColorStop(0.42, "rgba(96,132,232,0.34)");
          grad.addColorStop(1, "rgba(96,132,232,0)");
          gctx.fillStyle = grad;
          gctx.fillRect(0, 0, 128, 128);
        }
        const glowTex = new THREE.CanvasTexture(glowCanvas);
        const glowMat = new THREE.SpriteMaterial({
          map: glowTex,
          transparent: true,
          blending: THREE.AdditiveBlending,
          depthWrite: false,
        });
        const glowSprite = new THREE.Sprite(glowMat);
        glowSprite.scale.set(3.9, 3.9, 1);
        tilt.add(glowSprite);
        disposables.push(glowTex, glowMat);

        // ── Orbital trails — unchanged from the original scene ─────────────
        const rings: any[] = [];
        [
          { r: 1.32, tube: 0.006, rx: 0.35, ry: 0, rz: 0.1, opacity: 0.6, speed: 0.0022 },
          { r: 1.58, tube: 0.005, rx: 1.2, ry: 0.5, rz: 0, opacity: 0.45, speed: -0.0016 },
          { r: 1.86, tube: 0.0042, rx: -0.4, ry: 0.2, rz: 0.9, opacity: 0.34, speed: 0.0012 },
        ].forEach((def) => {
          const g = new THREE.TorusGeometry(def.r, def.tube, 8, 64);
          const m = new THREE.MeshBasicMaterial({
            color: 0x587ad9,
            transparent: true,
            opacity: def.opacity,
          });
          const ring = new THREE.Mesh(g, m);
          ring.rotation.set(def.rx, def.ry, def.rz);
          ring.userData.speed = def.speed;
          tilt.add(ring);
          rings.push(ring);
          disposables.push(g, m);
        });

        // ── Inward-drifting particles — unchanged from the original scene ──
        const resetParticle = (arr: Float32Array, i: number) => {
          const r = 1.5 + Math.random() * 1.3;
          const theta = Math.random() * Math.PI * 2;
          const phi = Math.acos(Math.random() * 2 - 1);
          arr[i * 3] = r * Math.sin(phi) * Math.cos(theta);
          arr[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
          arr[i * 3 + 2] = r * Math.cos(phi);
        };
        const partPos = new Float32Array(PARTICLE_COUNT * 3);
        for (let i = 0; i < PARTICLE_COUNT; i++) resetParticle(partPos, i);
        const partGeo = new THREE.BufferGeometry();
        partGeo.setAttribute("position", new THREE.BufferAttribute(partPos, 3));
        const partMat = new THREE.PointsMaterial({
          color: 0x587ad9,
          size: 0.036,
          transparent: true,
          opacity: 0.7,
          sizeAttenuation: true,
          blending: THREE.AdditiveBlending,
          depthWrite: false,
        });
        tilt.add(new THREE.Points(partGeo, partMat));
        disposables.push(partGeo, partMat);

        // ── Loop ───────────────────────────────────────────────────────────
        let lastDraw = 0;
        let quietUntil = 0;
        let t = 0;
        const onScroll = () => {
          quietUntil = performance.now() + SCROLL_QUIET_MS;
        };
        window.addEventListener("scroll", onScroll, { passive: true });

        const frame = (ts?: number) => {
          raf = requestAnimationFrame(frame);
          if (disposed) return;
          try {
            const rect = stage.getBoundingClientRect();
            if (document.hidden || rect.bottom <= 0) return;

            // Camera dolly tracks scroll every frame even when the draw is
            // skipped — it costs nothing and simply takes effect on the next
            // real draw.
            const p = Math.min(1, Math.max(0, -rect.top / (rect.height * 0.9)));
            camera.position.z = 5.2 - p * 1.5;

            if (quietUntil && (ts || 0) < quietUntil) return;
            if (ts && ts - lastDraw < GLOBE_FRAME_MS) return;
            lastDraw = ts || 0;

            const cw = stage.clientWidth;
            const ch = stage.clientHeight;
            if (cw && ch && (cw !== w || ch !== h)) {
              w = cw;
              h = ch;
              camera.aspect = w / h;
              camera.updateProjectionMatrix();
              renderer.setSize(w, h, false);
            }

            t += 1;

            // India stays facing the camera. The globe OSCILLATES around that
            // pose rather than spinning: a continuous spin would carry the
            // subcontinent out of view inside a minute, and "India visibly
            // central" is the brief's own requirement, not a starting pose.
            spin.rotation.y = baseY + Math.sin(t * 0.0045) * 0.26;
            tilt.rotation.x = 0.3 + Math.sin(t * 0.0031) * 0.05;

            rings.forEach((ring) => {
              ring.rotation.z += ring.userData.speed;
            });

            // Pulses run hub to hub along the arcs.
            const pAttr = pulseGeo.attributes.position;
            for (let i = 0; i < arcCurves.length; i++) {
              pulsePhase[i] = (pulsePhase[i] + 0.0055) % 1;
              const curve = arcCurves[i];
              const idx = Math.min(
                arcSegments,
                Math.floor(pulsePhase[i] * arcSegments)
              );
              pAttr.array[i * 3] = curve[idx * 3];
              pAttr.array[i * 3 + 1] = curve[idx * 3 + 1];
              pAttr.array[i * 3 + 2] = curve[idx * 3 + 2];
            }
            pAttr.needsUpdate = true;

            const posAttr = partGeo.attributes.position;
            const arr = posAttr.array as Float32Array;
            for (let i = 0; i < PARTICLE_COUNT; i++) {
              const ix = i * 3;
              let x = arr[ix];
              let y = arr[ix + 1];
              let z = arr[ix + 2];
              const len = Math.sqrt(x * x + y * y + z * z) || 1;
              const speed = 0.007;
              x -= (x / len) * speed;
              y -= (y / len) * speed;
              z -= (z / len) * speed;
              if (len < 1.15) resetParticle(arr, i);
              else {
                arr[ix] = x;
                arr[ix + 1] = y;
                arr[ix + 2] = z;
              }
            }
            posAttr.needsUpdate = true;

            camera.lookAt(0, 0, 0);
            renderer.render(scene, camera);
          } catch {
            /* a lost context must not take the page down with it */
          }
        };

        setLive(true);
        raf = requestAnimationFrame(frame);

        // Captured for the cleanup closure below.
        (renderer as any).__psCleanup = () => {
          window.removeEventListener("scroll", onScroll);
        };
      })
      .catch(() => {
        /* the static globe is already on screen; nothing to do */
      });

    return () => {
      disposed = true;
      cancelAnimationFrame(raf);
      if (renderer) {
        try {
          (renderer as any).__psCleanup?.();
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
 * Not a placeholder: for a visitor on reduced motion, on a phone, on a
 * low-memory machine or in a browser with no WebGL, this IS the hero visual,
 * and it has to be worth looking at on its own. It is also what reserves the
 * hero's box while three.min.js downloads, which is what keeps the headline
 * from jumping (brief §15: "ensure the hero has a stable reserved area while
 * assets load").
 *
 * The meridians are ellipses whose horizontal radius narrows toward the limb,
 * which is what a sphere's longitude lines actually project to; the city dots
 * are the same coordinates the WebGL scene uses, flattened orthographically.
 */
function StaticGlobe({
  className = "",
  style,
}: {
  className?: string;
  style?: React.CSSProperties;
}) {
  // Orthographic projection of the same India-facing pose the 3D scene uses.
  const dots = CITIES.map((c) => {
    const [x, y, z] = latLonToVec3(c.lat, c.lon, 1);
    const a = rotationFacing(INDIA_CENTRE.lon);
    // Rotate about Y, then tilt about X, matching the scene's group order.
    const rx = x * Math.cos(a) + z * Math.sin(a);
    const rz = -x * Math.sin(a) + z * Math.cos(a);
    const tiltA = 0.3;
    const ty = y * Math.cos(tiltA) - rz * Math.sin(tiltA);
    const tz = y * Math.sin(tiltA) + rz * Math.cos(tiltA);
    return { cx: 100 + rx * 78, cy: 100 - ty * 78, front: tz > 0, major: c.major };
  }).filter((d) => d.front);

  return (
    <svg viewBox="0 0 200 200" className={className} style={style} aria-hidden="true">
      <defs>
        <radialGradient id="ps-globe-atm" cx="50%" cy="50%" r="50%">
          <stop offset="55%" stopColor="#587ad9" stopOpacity="0" />
          <stop offset="82%" stopColor="#587ad9" stopOpacity="0.28" />
          <stop offset="100%" stopColor="#587ad9" stopOpacity="0" />
        </radialGradient>
        <radialGradient id="ps-globe-face" cx="38%" cy="32%" r="78%">
          <stop offset="0%" stopColor="#1b2a58" />
          <stop offset="100%" stopColor="#080f26" />
        </radialGradient>
      </defs>
      <circle cx="100" cy="100" r="96" fill="url(#ps-globe-atm)" />
      <circle cx="100" cy="100" r="78" fill="url(#ps-globe-face)" />
      <g stroke="#5f7fd4" strokeOpacity="0.22" fill="none" strokeWidth="0.6">
        {[16, 38, 58, 72].map((ry) => (
          <ellipse key={`p-${ry}`} cx="100" cy="100" rx="78" ry={ry} />
        ))}
        <line x1="22" y1="100" x2="178" y2="100" />
        {[20, 42, 62, 74].map((rx) => (
          <ellipse key={`m-${rx}`} cx="100" cy="100" rx={rx} ry="78" />
        ))}
        <line x1="100" y1="22" x2="100" y2="178" />
      </g>
      <g fill="#cfe0ff">
        {dots.map((d, i) => (
          <circle key={i} cx={d.cx} cy={d.cy} r={d.major ? 1.9 : 1.2} opacity={d.major ? 0.95 : 0.7} />
        ))}
      </g>
      <g stroke="#587ad9" fill="none" strokeWidth="0.5">
        <ellipse cx="100" cy="100" rx="94" ry="34" strokeOpacity="0.4" transform="rotate(-18 100 100)" />
        <ellipse cx="100" cy="100" rx="88" ry="52" strokeOpacity="0.26" transform="rotate(24 100 100)" />
      </g>
      <circle cx="100" cy="100" r="78" fill="none" stroke="#7fa0ec" strokeOpacity="0.35" strokeWidth="0.7" />
    </svg>
  );
}
