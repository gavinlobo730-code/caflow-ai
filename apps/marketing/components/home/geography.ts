/**
 * The geography the hero globe is built from.
 *
 * The redesign brief asks for "a luminous digital globe/core with India visibly
 * central, fine network points, orbital trails". The globe this replaced was an
 * abstract icosahedron — a sphere with no place in it — so "India central"
 * needed a source of truth, and there were two ways to get one.
 *
 * The cities below are where Indian practices actually are, to two decimal
 * places, and the network arcs run between them. That makes "India central" a
 * fact about the data rather than an illustration, and it is on-message — the
 * product is sold in one country, and the globe says so.
 *
 * ⚠️ THIS FILE USED TO CARRY A REJECTION OF THE COASTLINE, AND IT IS WITHDRAWN.
 * It said a land mask "would have to be written from memory here … and a world
 * map with the wrong coastline on the homepage of a product sold to Indian
 * professionals is a worse error than no map at all." The conclusion followed
 * from its premise and the premise was false: Natural Earth's shoreline
 * installs from npm, so the mask is a MEASURED coastline rather than a
 * recollection of one. See scripts/build-landmask.mjs and ./landmask.ts, which
 * is generated from a vendored copy of it and pinned by eleven coordinate
 * checks in the backend suite.
 *
 * The cities did not become redundant when the coastline arrived. The mask says
 * where land is; these say where the PRACTICES are, which is what the arcs and
 * the bright hubs are drawn between.
 *
 * Latitudes are north-positive and longitudes east-positive, the ordinary
 * convention; `latLonToVec3` in HeroGlobe.tsx is the only place that converts.
 */

export type City = { name: string; lat: number; lon: number; major?: boolean };

/** Approximate geographic centre of India — what the globe is rotated to face. */
export const INDIA_CENTRE = { lat: 22.0, lon: 79.0 };

export const CITIES: City[] = [
  { name: "New Delhi", lat: 28.61, lon: 77.21, major: true },
  { name: "Mumbai", lat: 19.08, lon: 72.88, major: true },
  { name: "Kolkata", lat: 22.57, lon: 88.36, major: true },
  { name: "Chennai", lat: 13.08, lon: 80.27, major: true },
  { name: "Bengaluru", lat: 12.97, lon: 77.59, major: true },
  { name: "Hyderabad", lat: 17.39, lon: 78.49, major: true },
  { name: "Ahmedabad", lat: 23.02, lon: 72.57 },
  { name: "Pune", lat: 18.52, lon: 73.86 },
  { name: "Jaipur", lat: 26.91, lon: 75.79 },
  { name: "Kochi", lat: 9.93, lon: 76.27 },
  { name: "Lucknow", lat: 26.85, lon: 80.95 },
  { name: "Surat", lat: 21.17, lon: 72.83 },
  { name: "Guwahati", lat: 26.14, lon: 91.74 },
  { name: "Chandigarh", lat: 30.73, lon: 76.78 },
  { name: "Nagpur", lat: 21.15, lon: 79.09 },
  { name: "Indore", lat: 22.72, lon: 75.86 },
  { name: "Bhubaneswar", lat: 20.3, lon: 85.82 },
  { name: "Coimbatore", lat: 11.02, lon: 76.96 },
  { name: "Visakhapatnam", lat: 17.69, lon: 83.22 },
  { name: "Patna", lat: 25.59, lon: 85.14 },
];

/** Index pairs into CITIES — the arcs drawn between them. */
export const ARCS: Array<[number, number]> = [
  [0, 1], // Delhi – Mumbai
  [1, 4], // Mumbai – Bengaluru
  [4, 3], // Bengaluru – Chennai
  [3, 2], // Chennai – Kolkata
  [2, 0], // Kolkata – Delhi
  [0, 6], // Delhi – Ahmedabad
  [5, 7], // Hyderabad – Pune
  [1, 9], // Mumbai – Kochi
  [12, 2], // Guwahati – Kolkata
  [0, 10], // Delhi – Lucknow
  [5, 3], // Hyderabad – Chennai
  [14, 16], // Nagpur – Bhubaneswar
];
