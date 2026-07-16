"use client";

import { useEffect, useRef } from "react";
import * as THREE from "three";
import { usePrefersReducedMotion } from "./motion";

function resetParticle(arr: Float32Array, i: number) {
  const r = 2.1 + Math.random() * 2.3;
  const theta = Math.random() * Math.PI * 2;
  const phi = Math.acos(Math.random() * 2 - 1);
  arr[i * 3] = r * Math.sin(phi) * Math.cos(theta);
  arr[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
  arr[i * 3 + 2] = r * Math.cos(phi);
}

const RING_DEFS = [
  { r: 1.7, tube: 0.008, rx: 0.35, ry: 0, rz: 0.1, opacity: 0.5, speed: 0.0022 },
  { r: 2.15, tube: 0.006, rx: 1.2, ry: 0.5, rz: 0, opacity: 0.4, speed: -0.0016 },
  { r: 2.55, tube: 0.005, rx: -0.4, ry: 0.2, rz: 0.9, opacity: 0.3, speed: 0.0012 },
];

/**
 * 3D hero centerpiece: an icosahedron core + wireframe shell, an
 * additively-blended glow sprite (a runtime-generated radial-gradient
 * canvas texture — fakes bloom cheaply, no post-processing pipeline), 3
 * orbiting torus rings, and a ~240-point particle cloud drifting inward and
 * recycling on reaching the center. Camera dollies in and the canvas fades
 * as the hero scrolls out of view, tracked via the hero container's own
 * `getBoundingClientRect()` every frame — correct under ScrollJack's
 * transform for the same reason every other reveal effect in this rebuild
 * is (see ScrollJack.tsx's doc comment).
 *
 * Gated off under prefers-reduced-motion and off desktop/fine-pointer, same
 * convention as the rest of this app — real-time 3D is exactly the kind of
 * motion reduced-motion visitors are opting out of, and it's meaningfully
 * heavier on mobile GPUs. Fails silently if WebGL is unavailable or setup
 * throws for any other reason: the page still works, just without the 3D
 * piece.
 */
export function ThreeScene({ className = "" }: { className?: string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const reduced = usePrefersReducedMotion();
  const mouseRef = useRef({ x: 0, y: 0 });

  useEffect(() => {
    const widthMq = window.matchMedia("(min-width: 1024px)");
    const pointerMq = window.matchMedia("(pointer: fine)");
    const motionMq = window.matchMedia("(prefers-reduced-motion: reduce)");
    // `reduced` (from usePrefersReducedMotion) corrects from its default
    // `false` via its own effect + setState, one render behind this one —
    // so on first mount this closure can still see a stale `false` before
    // that correction lands. Checking matchMedia directly too closes that
    // race instead of briefly spinning up a whole WebGL context/render loop
    // for a reduced-motion visitor before getting cleaned up again.
    if (reduced || motionMq.matches || !widthMq.matches || !pointerMq.matches) return;

    const canvas = canvasRef.current;
    const parent = canvas?.parentElement;
    if (!canvas || !parent) return;

    // Probe on a throwaway canvas, not the real one: THREE.WebGLRenderer's
    // own constructor logs via console.error (not just throws) when it can't
    // get a context, so catching around `new THREE.WebGLRenderer(...)` below
    // isn't enough to keep the console clean — this check lets us skip ever
    // calling it. A probe on the real canvas would work too, but calling
    // getContext() on it first would pin its context type/attributes ahead
    // of WebGLRenderer's own (differently-configured) call, which returns
    // the already-established context instead of a fresh one.
    const probe = document.createElement("canvas");
    const hasWebGL = !!(probe.getContext("webgl2") || probe.getContext("webgl"));
    if (!hasWebGL) return;

    let unmounted = false;
    let raf = 0;

    const onMouseMove = (e: MouseEvent) => {
      mouseRef.current.x = e.clientX;
      mouseRef.current.y = e.clientY;
    };

    try {
      const w = parent.clientWidth || 600;
      const h = parent.clientHeight || 600;

      const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      renderer.setSize(w, h);

      const scene = new THREE.Scene();
      const camera = new THREE.PerspectiveCamera(45, w / h, 0.1, 100);
      camera.position.set(0, 0, 7);

      const group = new THREE.Group();

      const coreGeo = new THREE.IcosahedronGeometry(0.55, 2);
      const coreMat = new THREE.MeshBasicMaterial({ color: 0x587ad9 });
      group.add(new THREE.Mesh(coreGeo, coreMat));

      const shellGeo = new THREE.IcosahedronGeometry(0.64, 1);
      const shellMat = new THREE.LineBasicMaterial({ color: 0xc7d2f0, transparent: true, opacity: 0.55 });
      group.add(new THREE.LineSegments(new THREE.WireframeGeometry(shellGeo), shellMat));

      const glowCanvas = document.createElement("canvas");
      glowCanvas.width = glowCanvas.height = 128;
      const gctx = glowCanvas.getContext("2d");
      if (gctx) {
        const grad = gctx.createRadialGradient(64, 64, 0, 64, 64, 64);
        grad.addColorStop(0, "rgba(88,122,217,0.85)");
        grad.addColorStop(0.4, "rgba(88,122,217,0.3)");
        grad.addColorStop(1, "rgba(88,122,217,0)");
        gctx.fillStyle = grad;
        gctx.fillRect(0, 0, 128, 128);
      }
      const glowTex = new THREE.CanvasTexture(glowCanvas);
      const glowSprite = new THREE.Sprite(
        new THREE.SpriteMaterial({ map: glowTex, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false })
      );
      glowSprite.scale.set(4.6, 4.6, 1);
      group.add(glowSprite);

      const rings = RING_DEFS.map((def) => {
        const ring = new THREE.Mesh(
          new THREE.TorusGeometry(def.r, def.tube, 8, 128),
          new THREE.MeshBasicMaterial({ color: 0x587ad9, transparent: true, opacity: def.opacity })
        );
        ring.rotation.set(def.rx, def.ry, def.rz);
        group.add(ring);
        return { ring, speed: def.speed };
      });

      const particleCount = 240;
      const positions = new Float32Array(particleCount * 3);
      for (let i = 0; i < particleCount; i++) resetParticle(positions, i);
      const pGeo = new THREE.BufferGeometry();
      pGeo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
      const pMat = new THREE.PointsMaterial({
        color: 0x587ad9,
        size: 0.045,
        transparent: true,
        opacity: 0.7,
        sizeAttenuation: true,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      });
      const particles = new THREE.Points(pGeo, pMat);
      group.add(particles);

      scene.add(group);

      const render = () => {
        if (unmounted) return;
        const pw = parent.clientWidth;
        const ph = parent.clientHeight;
        const dpr = Math.min(window.devicePixelRatio || 1, 2);
        if (pw && ph && (canvas.width !== Math.round(pw * dpr) || canvas.height !== Math.round(ph * dpr))) {
          camera.aspect = pw / ph;
          camera.updateProjectionMatrix();
          renderer.setSize(pw, ph);
        }

        group.rotation.y += 0.0016;
        group.rotation.x += 0.0006;

        const nx = (mouseRef.current.x / window.innerWidth - 0.5) * 2;
        const ny = (mouseRef.current.y / window.innerHeight - 0.5) * 2;
        group.rotation.x += (-ny * 0.25 - group.rotation.x) * 0.02;
        group.rotation.y += (nx * 0.35 - group.rotation.y) * 0.02;

        rings.forEach(({ ring, speed }) => {
          ring.rotation.z += speed;
        });

        const posAttr = particles.geometry.attributes.position;
        const arr = posAttr.array as Float32Array;
        for (let i = 0; i < particleCount; i++) {
          const ix = i * 3, iy = i * 3 + 1, iz = i * 3 + 2;
          let x = arr[ix], y = arr[iy], z = arr[iz];
          const len = Math.sqrt(x * x + y * y + z * z) || 1;
          const speed = 0.008;
          x -= (x / len) * speed;
          y -= (y / len) * speed;
          z -= (z / len) * speed;
          if (len < 0.45) {
            resetParticle(arr, i);
          } else {
            arr[ix] = x;
            arr[iy] = y;
            arr[iz] = z;
          }
        }
        posAttr.needsUpdate = true;

        const heroRect = parent.getBoundingClientRect();
        const p = Math.min(1, Math.max(0, -heroRect.top / (heroRect.height * 0.9)));
        camera.position.z = 7 - p * 2.6;
        canvas.style.opacity = (1 - Math.max(0, (p - 0.55) / 0.45)).toFixed(2);

        camera.lookAt(0, 0, 0);
        renderer.render(scene, camera);
        raf = requestAnimationFrame(render);
      };

      window.addEventListener("mousemove", onMouseMove);
      raf = requestAnimationFrame(render);

      return () => {
        unmounted = true;
        window.removeEventListener("mousemove", onMouseMove);
        if (raf) cancelAnimationFrame(raf);
        pGeo.dispose();
        pMat.dispose();
        coreGeo.dispose();
        coreMat.dispose();
        shellGeo.dispose();
        shellMat.dispose();
        glowTex.dispose();
        rings.forEach(({ ring }) => {
          ring.geometry.dispose();
          (ring.material as THREE.Material).dispose();
        });
        renderer.dispose();
      };
    } catch {
      return;
    }
  }, [reduced]);

  return <canvas ref={canvasRef} className={className} aria-hidden="true" />;
}
