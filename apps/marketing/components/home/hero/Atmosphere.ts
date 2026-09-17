/**
 * The blue shell around the planet.
 *
 * A second sphere, 4.5% larger, drawn BACK SIDE with additive blending and no
 * depth write. Back side is the whole trick: the front faces are culled, so
 * the only fragments that survive are the ones on the far wall of the shell,
 * and the ones the planet does not cover are exactly the ring outside its
 * silhouette. Nothing has to be masked and there is no seam.
 *
 * depthWrite false, depthTest true: it must not punch a hole in the depth
 * buffer that the orbits behind it would then fail against, but it must still
 * be occluded by the planet itself.
 *
 * 4.5% IS SMALL ON PURPOSE. A thicker shell is easy to reach for and reads as
 * a halo drawn around a ball rather than as air on a planet — §7 asks for a
 * rim, and warns off "an exaggerated neon outline".
 */

import { ATMOSPHERE_VERTEX, ATMOSPHERE_FRAGMENT } from "./shaders";

export function createAtmosphere(
  THREE: any,
  opts: { radius: number; sun: [number, number, number]; tint?: number; intensity?: number }
) {
  const uniforms = {
    uTint: { value: new THREE.Color(opts.tint ?? 0x4d93ff) },
    uSun: { value: new THREE.Vector3(...opts.sun).normalize() },
    uIntensity: { value: opts.intensity ?? 0.62 },
  };

  const mesh = new THREE.Mesh(
    new THREE.SphereGeometry(opts.radius * 1.045, 96, 64),
    new THREE.ShaderMaterial({
      uniforms,
      vertexShader: ATMOSPHERE_VERTEX,
      fragmentShader: ATMOSPHERE_FRAGMENT,
      side: THREE.BackSide,
      blending: THREE.AdditiveBlending,
      transparent: true,
      depthWrite: false,
    })
  );
  mesh.renderOrder = 3;
  return { mesh, uniforms };
}

/**
 * A wider, fainter second shell.
 *
 * The single shell above gives a crisp edge; real limb light also scatters
 * much further out at very low intensity, and without it the planet's glow
 * stops dead and the background starts. This is that falloff. Separate mesh
 * rather than a fatter gradient in one shader because the two want different
 * geometry radii, and a shader doing both would need the shell thickness as a
 * uniform for no gain.
 */
export function createOuterGlow(
  THREE: any,
  opts: { radius: number; sun: [number, number, number] }
) {
  const uniforms = {
    uTint: { value: new THREE.Color(0x2f6ad0) },
    uSun: { value: new THREE.Vector3(...opts.sun).normalize() },
    uIntensity: { value: 0.11 },
  };

  const mesh = new THREE.Mesh(
    new THREE.SphereGeometry(opts.radius * 1.3, 64, 48),
    new THREE.ShaderMaterial({
      uniforms,
      vertexShader: ATMOSPHERE_VERTEX,
      fragmentShader: ATMOSPHERE_FRAGMENT,
      side: THREE.BackSide,
      blending: THREE.AdditiveBlending,
      transparent: true,
      depthWrite: false,
      depthTest: false,
    })
  );
  mesh.renderOrder = 1;
  return { mesh, uniforms };
}
