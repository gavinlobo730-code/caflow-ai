"use client";

import { useEffect, useRef } from "react";
import { loadThree, canRunGlobe } from "../three-loader";
import { createEarthSurface } from "./EarthSurface";
import { createAtmosphere, createOuterGlow } from "./Atmosphere";
import { createNetwork } from "./NetworkNodes";
import { createOrbitalPaths } from "./OrbitalPaths";
import { createSpaceBackground } from "./SpaceBackground";
import { INDIA_CENTRE } from "./cities";
import { sphereHeightFraction } from "./math";

/**
 * The hero scene.
 *
 * IT RENDERS ONCE. There is no requestAnimationFrame loop: draw() puts up a
 * frame and runs again only when the canvas resizes. §21 asks for a static
 * composition, but the reason this is worth stating is what it BUYS — with no
 * per-frame budget the scene can afford device-pixel-ratio 2, a 128x96 sphere,
 * a 2048x1024 generated texture, seven ribbon orbits, three network layers and
 * twenty-odd lit bodies, and still cost less over the page's whole life than a
 * modest animated scene costs in a second. The quality in this frame is paid
 * for by not drawing the next one.
 *
 * MAKING IT MOVE LATER IS NOT A REWRITE. Every value the animation will touch
 * is already a uniform rather than a constant in GLSL, and the two groups that
 * will spin are already separate objects. Stage 2 is: start a loop, advance
 * `spin.rotation.y` and the sweep uniforms, call draw(). Nothing here has to
 * be taken apart to get there.
 *
 * WHY NOT REACT THREE FIBER. §22 names it as preferred "if compatible with the
 * existing project" and allows another appropriate approach. This project
 * vendors three.min.js and loads it from the component's own effect, so a
 * visitor who will never see the globe — reduced motion, a phone, no WebGL —
 * downloads none of it. R3F and drei are npm dependencies bundled into the
 * static export, so they are paid for by everyone on first load. For a scene
 * that renders a single frame and has no component tree to reconcile, that is
 * a real cost for no gain. The modules here are split along exactly the
 * boundaries §22 asks for; only the reconciler is absent.
 */

/**
 * Camera distance, and the globe's size is derived from it rather than chosen.
 *
 * sphereHeightFraction(1, 5.0, 40) = 0.561, so the planet is 56% of the
 * canvas height. The canvas is 138% of a 720px stage at a 1440x900 desktop, so
 * that is a 557px sphere — 38% of the viewport width, which is what the
 * reference image measures (its globe spans 640 of 1672 pixels).
 *
 * The two neighbouring values are both wrong and were both shipped: 4.3 gave
 * 643px and the owner's verdict was "oversized and visually heavy"; 5.3 gave
 * 517px, which cleared that complaint and left §4's "large and visually
 * dominant" unmet. Changing this ONE number moves the globe; nothing else in
 * the file needs to know.
 */
const CAMERA_Z = 5.0;
const FOV = 40;

/**
 * The composition sits left of the stage's own centre.
 *
 * The right-hand grid cell centres at 73% of a 1440px viewport; the reference
 * puts the planet's centre at 66%. Shifting the SCENE rather than the camera
 * keeps the camera on-axis, which is what lets sphereHeightFraction above
 * remain exact instead of becoming an approximation with an off-axis frustum.
 */
const SCENE_X = -0.35;

/**
 * Where the light comes from, in VIEW space.
 *
 * View space, not world space, so the lighting is a property of the
 * COMPOSITION rather than of the globe's rotation — when stage 2 spins the
 * planet, the terminator stays where it was framed instead of sweeping round
 * with it. Upper right, matching the reference, and every lit thing in the
 * scene is handed this same vector: the planet, the atmosphere, both moons,
 * the near horizon, every piece of debris and the flare's own position.
 */
const SUN: [number, number, number] = [0.66, 0.54, 0.52];

const DPR_CAP = 2;

export function HeroGlobe({ className = "" }: { className?: string }) {
  const holder = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!canRunGlobe()) return;
    const host = holder.current;
    if (!host) return;

    let disposed = false;
    let cleanup: (() => void) | null = null;

    loadThree()
      .then((THREE: any) => {
        if (disposed || !holder.current) return;

        const renderer = new THREE.WebGLRenderer({
          antialias: true,
          alpha: true,
          powerPreference: "high-performance",
        });
        renderer.setClearColor(0x000000, 0);
        host.appendChild(renderer.domElement);
        renderer.domElement.style.width = "100%";
        renderer.domElement.style.height = "100%";
        renderer.domElement.style.display = "block";

        const scene = new THREE.Scene();
        const camera = new THREE.PerspectiveCamera(FOV, 1, 0.1, 100);
        camera.position.set(0, 0, CAMERA_Z);

        // Three groups, and the split is what stage 2 will animate against.
        //   root  everything, shifted off-centre
        //   fixed things that must NOT turn with the planet (space, orbits)
        //   spin  the planet and its network, which will rotate
        const root = new THREE.Group();
        root.position.x = SCENE_X;
        scene.add(root);

        const fixed = new THREE.Group();
        const tilt = new THREE.Group();
        const spin = new THREE.Group();
        root.add(fixed);
        root.add(tilt);
        tilt.add(spin);

        /*
          Turn India to face the camera.

          ⚠️ THIS IS NOT -lon, AND THE OBVIOUS FORM IS WRONG BY 90 DEGREES.
          Three's SphereGeometry puts longitude L at angle (L+180) degrees
          around Y, so at rotation.y = 0 it is lon -90 that faces the camera,
          not lon 0. Facing L therefore needs

              a = pi/2 - (L + 180) * pi/180   ==   -pi/2 - L * pi/180

          The first build wrote the intuitive `-(lon * PI) / 180`, which for
          India's 79E evaluates to -1.379 rad and puts the subcontinent at
          z = 0.000 — EXACTLY on the limb, edge-on, where a hemisphere's worth
          of foreshortening squeezes it into nothing. Every warm light was
          still being drawn; none of it was anywhere the viewer could see it,
          and the globe simply looked like it had no focal point. A screenshot
          shows this as "India is not very visible", which reads like a
          brightness problem and is a rotation problem.

          The tilt is small and deliberate. rotation.x stays near zero because
          the point facing the camera is then the EQUATOR, which already puts
          India's 22N above the disc's centre — where the reference has it —
          without any help. rotation.z leans the axis the way the reference
          does.
        */
        spin.rotation.y = -Math.PI / 2 - (INDIA_CENTRE.lon * Math.PI) / 180;
        tilt.rotation.x = -0.04;
        tilt.rotation.z = 0.20;

        const RADIUS = 1;
        const scales: Array<{ value: number }> = [];
        // Every material that draws a CONTINUOUS line and therefore has to
        // fade before the canvas boundary — see EDGE_FADE in shaders.ts.
        const edges: Array<{ value: any }> = [];

        const earth = createEarthSurface(THREE, { sun: SUN, radius: RADIUS });
        spin.add(earth.mesh);

        const net = createNetwork(THREE, { radius: RADIUS, cameraZ: CAMERA_Z });
        for (const m of net.meshes) spin.add(m);
        scales.push(...net.scales);
        edges.push(...net.edges);

        const atmo = createAtmosphere(THREE, { radius: RADIUS, sun: SUN });
        tilt.add(atmo.mesh);
        const glow = createOuterGlow(THREE, { radius: RADIUS, sun: SUN });
        fixed.add(glow.mesh);

        const orbits = createOrbitalPaths(THREE, { radius: RADIUS, cameraZ: CAMERA_Z });
        for (const m of orbits.meshes) fixed.add(m);
        scales.push(...orbits.scales);
        edges.push(...orbits.edges);

        const space = createSpaceBackground(THREE, {
          sun: SUN,
          radius: RADIUS,
          cameraZ: CAMERA_Z,
        });
        for (const m of space.meshes) fixed.add(m);
        scales.push(...space.scales);

        /**
         * Size, project, draw.
         *
         * uScale is the point-sprite denominator and depends on the canvas
         * height in DEVICE pixels, so it is recomputed here rather than set
         * once — without this, every node and star in the scene changes
         * apparent size when the window is resized or the page is dragged to a
         * second monitor with a different DPR.
         */
        const draw = () => {
          const w = host.clientWidth;
          const h = host.clientHeight;
          if (w < 2 || h < 2) return;

          const dpr = Math.min(DPR_CAP, window.devicePixelRatio || 1);
          renderer.setPixelRatio(dpr);
          renderer.setSize(w, h, false);
          camera.aspect = w / h;
          camera.updateProjectionMatrix();

          const s = (h * dpr) / (2 * Math.tan((FOV * Math.PI) / 360));
          for (const u of scales) u.value = s;
          // Device pixels, because edgeFade() reads gl_FragCoord.
          for (const u of edges) u.value.set(w * dpr, h * dpr);

          renderer.render(scene, camera);
        };

        draw();

        // Two observers because they answer different questions: the window
        // listener catches a DPR change on a monitor swap, which does not
        // resize the element at all; the element observer catches the stage
        // changing width under a layout that the window never reported.
        const onResize = () => draw();
        window.addEventListener("resize", onResize);
        const ro = new ResizeObserver(() => draw());
        ro.observe(host);

        cleanup = () => {
          window.removeEventListener("resize", onResize);
          ro.disconnect();
          scene.traverse((o: any) => {
            if (o.geometry) o.geometry.dispose?.();
            const m = o.material;
            if (m) {
              for (const key of Object.keys(m.uniforms ?? {})) {
                m.uniforms[key]?.value?.dispose?.();
              }
              m.dispose?.();
            }
          });
          renderer.dispose();
          renderer.domElement.remove();
        };
      })
      .catch(() => {
        // Three failed to load, or WebGL context creation threw. The SVG
        // underneath was never removed, so there is nothing to undo — the
        // visitor simply keeps the fallback.
      });

    return () => {
      disposed = true;
      cleanup?.();
    };
  }, []);

  return <div ref={holder} className={className} aria-hidden="true" />;
}

/** What the globe measures, for the record and for anyone re-deriving it. */
export const GLOBE_HEIGHT_FRACTION = sphereHeightFraction(1, CAMERA_Z, FOV);
