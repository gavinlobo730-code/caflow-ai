/**
 * Where the world's lights are.
 *
 * WHY THIS FILE EXISTS. The globe this replaced drew the continents as a field
 * of evenly-scattered identical dots, and the owner's verdict was exact: "a
 * flat dotted world map wrapped onto a sphere". The reason it read that way is
 * that a uniform scatter carries no INFORMATION — the real night Earth is not
 * evenly lit, it is a few dozen blazing deltas and estuaries with enormous
 * darkness between them, and that contrast is the whole of what makes a night
 * Earth recognisable. Sahara dark, Nile a bright thread. Siberia dark, the
 * Trans-Siberian a line of beads. Australia dark but for its rim.
 *
 * So the lights are placed from population centres and the DARKNESS is
 * everything those centres do not reach. `landmask.ts` says where land is;
 * this says where the land is lit.
 *
 * ⚠️ PROVENANCE, AND IT IS DIFFERENT FROM THE COASTLINE'S. `landmask.ts` is
 * MEASURED — generated offline from Natural Earth's shoreline and pinned by
 * eleven coordinate checks in the backend suite. This table is written from
 * knowledge: direct egress is refused at this environment's proxy, so no
 * gazetteer could be fetched. City coordinates are stable public geography and
 * these are good to roughly a tenth of a degree, but they are not measured and
 * the difference is recorded rather than glossed.
 *
 * That is acceptable HERE and would not be in `apps/api`, because the error
 * budget is different in kind: a city half a degree out moves a decorative
 * glow by 50km on a 640px sphere — under one pixel — and lands on the same
 * coastline either way. Nothing is computed from these numbers. Contrast
 * `domain/tds/section_rates.py`, where a figure written from memory is money
 * somebody pays over, and the codebase refuses rather than guesses.
 *
 * WEIGHT is a rendering weight, not a population. It sets the radius and
 * brightness of the glow and is graded by eye against how a metropolitan area
 * reads from orbit — so Delhi's conurbation outranks a denser but smaller
 * municipality. It is not a demographic claim and nothing reads it as one.
 */

export type Light = { lat: number; lon: number; w: number };

/**
 * India, at the density the focal point deserves.
 *
 * The globe is rotated to face this subcontinent and §6 of the brief asks for
 * India "slightly brighter than the surrounding region" from lighting that
 * "appears to originate naturally from the network of Indian cities" — which
 * is only possible if there are enough Indian cities for a network to emerge
 * from. Forty-odd entries is what turns a glow into a constellation.
 */
export const INDIA_LIGHTS: Light[] = [
  { lat: 28.61, lon: 77.21, w: 3.0 }, // Delhi
  { lat: 19.08, lon: 72.88, w: 3.0 }, // Mumbai
  { lat: 22.57, lon: 88.36, w: 2.8 }, // Kolkata
  { lat: 13.08, lon: 80.27, w: 2.6 }, // Chennai
  { lat: 12.97, lon: 77.59, w: 2.6 }, // Bengaluru
  { lat: 17.39, lon: 78.49, w: 2.5 }, // Hyderabad
  { lat: 23.02, lon: 72.57, w: 2.3 }, // Ahmedabad
  { lat: 18.52, lon: 73.86, w: 2.3 }, // Pune
  { lat: 21.17, lon: 72.83, w: 2.0 }, // Surat
  { lat: 26.91, lon: 75.79, w: 2.0 }, // Jaipur
  { lat: 26.85, lon: 80.95, w: 2.0 }, // Lucknow
  { lat: 26.45, lon: 80.33, w: 1.8 }, // Kanpur
  { lat: 21.15, lon: 79.09, w: 1.8 }, // Nagpur
  { lat: 22.72, lon: 75.86, w: 1.8 }, // Indore
  { lat: 23.26, lon: 77.41, w: 1.7 }, // Bhopal
  { lat: 25.59, lon: 85.14, w: 1.8 }, // Patna
  { lat: 22.31, lon: 73.18, w: 1.6 }, // Vadodara
  { lat: 30.9, lon: 75.86, w: 1.6 }, // Ludhiana
  { lat: 27.18, lon: 78.01, w: 1.6 }, // Agra
  { lat: 19.99, lon: 73.79, w: 1.6 }, // Nashik
  { lat: 11.02, lon: 76.96, w: 1.7 }, // Coimbatore
  { lat: 9.93, lon: 76.27, w: 1.7 }, // Kochi
  { lat: 17.69, lon: 83.22, w: 1.7 }, // Visakhapatnam
  { lat: 25.32, lon: 82.97, w: 1.5 }, // Varanasi
  { lat: 31.63, lon: 74.87, w: 1.6 }, // Amritsar
  { lat: 30.73, lon: 76.78, w: 1.6 }, // Chandigarh
  { lat: 20.3, lon: 85.82, w: 1.5 }, // Bhubaneswar
  { lat: 26.14, lon: 91.74, w: 1.5 }, // Guwahati
  { lat: 8.52, lon: 76.94, w: 1.5 }, // Thiruvananthapuram
  { lat: 15.36, lon: 75.12, w: 1.3 }, // Hubli
  { lat: 16.51, lon: 80.65, w: 1.4 }, // Vijayawada
  { lat: 9.92, lon: 78.12, w: 1.4 }, // Madurai
  { lat: 12.29, lon: 76.64, w: 1.3 }, // Mysuru
  { lat: 22.3, lon: 70.8, w: 1.4 }, // Rajkot
  { lat: 24.58, lon: 73.71, w: 1.2 }, // Udaipur
  { lat: 26.22, lon: 78.18, w: 1.3 }, // Gwalior
  { lat: 23.36, lon: 85.33, w: 1.4 }, // Ranchi
  { lat: 21.25, lon: 81.63, w: 1.3 }, // Raipur
  { lat: 34.08, lon: 74.8, w: 1.2 }, // Srinagar
  { lat: 15.3, lon: 74.08, w: 1.1 }, // Goa
  { lat: 11.94, lon: 79.83, w: 1.1 }, // Puducherry
  { lat: 27.72, lon: 85.32, w: 1.3 }, // Kathmandu
  { lat: 23.81, lon: 90.41, w: 2.4 }, // Dhaka
  { lat: 22.36, lon: 91.78, w: 1.7 }, // Chattogram
  { lat: 6.93, lon: 79.86, w: 1.6 }, // Colombo
  { lat: 24.86, lon: 67.0, w: 2.5 }, // Karachi
  { lat: 31.55, lon: 74.34, w: 2.3 }, // Lahore
  { lat: 33.69, lon: 73.06, w: 1.7 }, // Islamabad
];

/**
 * The rest of the world.
 *
 * Coverage is deliberately uneven and that is the point — §5 asks for "dark
 * areas as well as illuminated areas" and calls the contrast "essential". The
 * Sahara, the Arabian interior, the Tibetan plateau, Siberia, the Amazon, the
 * Australian interior and the Canadian north carry nothing here because they
 * carry nothing from orbit either.
 *
 * Only the half of the planet the camera can see is doing real work — the
 * globe faces India — but the far side is populated anyway, because the limb
 * catches Europe and the western Pacific, and because an empty back face
 * would show the moment anyone changes the rotation.
 */
export const WORLD_LIGHTS: Light[] = [
  // ── East and South-East Asia ────────────────────────────────────────────
  { lat: 39.9, lon: 116.4, w: 3.0 }, // Beijing
  { lat: 31.23, lon: 121.47, w: 3.0 }, // Shanghai
  { lat: 23.13, lon: 113.26, w: 2.8 }, // Guangzhou
  { lat: 22.54, lon: 114.06, w: 2.7 }, // Shenzhen
  { lat: 22.32, lon: 114.17, w: 2.5 }, // Hong Kong
  { lat: 30.59, lon: 114.3, w: 2.3 }, // Wuhan
  { lat: 29.56, lon: 106.55, w: 2.3 }, // Chongqing
  { lat: 30.67, lon: 104.06, w: 2.2 }, // Chengdu
  { lat: 34.34, lon: 108.94, w: 2.0 }, // Xi'an
  { lat: 39.13, lon: 117.2, w: 2.0 }, // Tianjin
  { lat: 36.07, lon: 120.38, w: 1.8 }, // Qingdao
  { lat: 45.8, lon: 126.53, w: 1.7 }, // Harbin
  { lat: 41.8, lon: 123.43, w: 1.8 }, // Shenyang
  { lat: 25.04, lon: 121.56, w: 2.2 }, // Taipei
  { lat: 35.68, lon: 139.69, w: 3.0 }, // Tokyo
  { lat: 34.69, lon: 135.5, w: 2.5 }, // Osaka
  { lat: 35.18, lon: 136.91, w: 2.0 }, // Nagoya
  { lat: 43.06, lon: 141.35, w: 1.6 }, // Sapporo
  { lat: 33.59, lon: 130.4, w: 1.6 }, // Fukuoka
  { lat: 37.57, lon: 126.98, w: 2.8 }, // Seoul
  { lat: 35.18, lon: 129.08, w: 1.9 }, // Busan
  { lat: 39.03, lon: 125.75, w: 1.2 }, // Pyongyang
  { lat: 13.76, lon: 100.5, w: 2.5 }, // Bangkok
  { lat: 21.03, lon: 105.85, w: 2.1 }, // Hanoi
  { lat: 10.82, lon: 106.63, w: 2.3 }, // Ho Chi Minh City
  { lat: 11.56, lon: 104.92, w: 1.5 }, // Phnom Penh
  { lat: 16.87, lon: 96.2, w: 1.7 }, // Yangon
  { lat: 3.14, lon: 101.69, w: 2.1 }, // Kuala Lumpur
  { lat: 1.35, lon: 103.82, w: 2.3 }, // Singapore
  { lat: -6.21, lon: 106.85, w: 2.8 }, // Jakarta
  { lat: -7.25, lon: 112.75, w: 2.0 }, // Surabaya
  { lat: 3.6, lon: 98.67, w: 1.6 }, // Medan
  { lat: 14.6, lon: 120.98, w: 2.7 }, // Manila
  { lat: 10.32, lon: 123.89, w: 1.6 }, // Cebu
  { lat: 47.92, lon: 106.92, w: 1.2 }, // Ulaanbaatar

  // ── Middle East and Central Asia ────────────────────────────────────────
  { lat: 25.2, lon: 55.27, w: 2.4 }, // Dubai
  { lat: 24.45, lon: 54.38, w: 1.8 }, // Abu Dhabi
  { lat: 24.71, lon: 46.68, w: 2.2 }, // Riyadh
  { lat: 21.49, lon: 39.19, w: 1.9 }, // Jeddah
  { lat: 29.37, lon: 47.98, w: 1.7 }, // Kuwait City
  { lat: 25.29, lon: 51.53, w: 1.6 }, // Doha
  { lat: 26.23, lon: 50.59, w: 1.4 }, // Manama
  { lat: 33.32, lon: 44.36, w: 2.2 }, // Baghdad
  { lat: 35.7, lon: 51.42, w: 2.5 }, // Tehran
  { lat: 36.3, lon: 59.6, w: 1.7 }, // Mashhad
  { lat: 32.65, lon: 51.67, w: 1.5 }, // Isfahan
  { lat: 41.01, lon: 28.98, w: 2.7 }, // Istanbul
  { lat: 39.93, lon: 32.86, w: 1.9 }, // Ankara
  { lat: 38.42, lon: 27.14, w: 1.6 }, // Izmir
  { lat: 32.09, lon: 34.78, w: 1.9 }, // Tel Aviv
  { lat: 31.95, lon: 35.93, w: 1.6 }, // Amman
  { lat: 33.51, lon: 36.29, w: 1.6 }, // Damascus
  { lat: 33.89, lon: 35.5, w: 1.5 }, // Beirut
  { lat: 34.53, lon: 69.17, w: 1.5 }, // Kabul
  { lat: 41.3, lon: 69.24, w: 1.7 }, // Tashkent
  { lat: 43.24, lon: 76.89, w: 1.5 }, // Almaty
  { lat: 40.18, lon: 44.51, w: 1.3 }, // Yerevan
  { lat: 40.41, lon: 49.87, w: 1.5 }, // Baku

  // ── Europe ──────────────────────────────────────────────────────────────
  { lat: 51.51, lon: -0.13, w: 2.9 }, // London
  { lat: 48.86, lon: 2.35, w: 2.8 }, // Paris
  { lat: 52.52, lon: 13.41, w: 2.4 }, // Berlin
  { lat: 50.11, lon: 8.68, w: 2.0 }, // Frankfurt
  { lat: 48.14, lon: 11.58, w: 2.0 }, // Munich
  { lat: 51.23, lon: 6.78, w: 2.2 }, // Rhine-Ruhr
  { lat: 53.55, lon: 9.99, w: 1.9 }, // Hamburg
  { lat: 52.37, lon: 4.9, w: 2.1 }, // Amsterdam
  { lat: 50.85, lon: 4.35, w: 1.9 }, // Brussels
  { lat: 45.46, lon: 9.19, w: 2.2 }, // Milan
  { lat: 41.9, lon: 12.5, w: 2.2 }, // Rome
  { lat: 40.85, lon: 14.27, w: 1.8 }, // Naples
  { lat: 40.42, lon: -3.7, w: 2.3 }, // Madrid
  { lat: 41.39, lon: 2.17, w: 2.1 }, // Barcelona
  { lat: 38.72, lon: -9.14, w: 1.8 }, // Lisbon
  { lat: 47.5, lon: 19.04, w: 1.8 }, // Budapest
  { lat: 48.21, lon: 16.37, w: 1.9 }, // Vienna
  { lat: 50.08, lon: 14.44, w: 1.8 }, // Prague
  { lat: 52.23, lon: 21.01, w: 1.9 }, // Warsaw
  { lat: 37.98, lon: 23.73, w: 1.9 }, // Athens
  { lat: 55.68, lon: 12.57, w: 1.7 }, // Copenhagen
  { lat: 59.33, lon: 18.07, w: 1.7 }, // Stockholm
  { lat: 59.91, lon: 10.75, w: 1.5 }, // Oslo
  { lat: 60.17, lon: 24.94, w: 1.5 }, // Helsinki
  { lat: 53.35, lon: -6.26, w: 1.6 }, // Dublin
  { lat: 53.48, lon: -2.24, w: 1.7 }, // Manchester
  { lat: 55.86, lon: -4.25, w: 1.5 }, // Glasgow
  { lat: 47.37, lon: 8.54, w: 1.6 }, // Zurich
  { lat: 55.75, lon: 37.62, w: 2.7 }, // Moscow
  { lat: 59.93, lon: 30.34, w: 2.1 }, // St Petersburg
  { lat: 50.45, lon: 30.52, w: 2.0 }, // Kyiv
  { lat: 44.43, lon: 26.11, w: 1.7 }, // Bucharest
  { lat: 44.82, lon: 20.46, w: 1.6 }, // Belgrade
  { lat: 56.95, lon: 24.11, w: 1.2 }, // Riga
  { lat: 56.84, lon: 60.61, w: 1.4 }, // Yekaterinburg
  { lat: 55.03, lon: 82.92, w: 1.4 }, // Novosibirsk
  { lat: 43.12, lon: 131.89, w: 1.2 }, // Vladivostok

  // ── Africa ──────────────────────────────────────────────────────────────
  { lat: 30.04, lon: 31.24, w: 2.7 }, // Cairo
  { lat: 31.2, lon: 29.92, w: 2.0 }, // Alexandria
  { lat: 6.52, lon: 3.38, w: 2.6 }, // Lagos
  { lat: 9.06, lon: 7.49, w: 1.7 }, // Abuja
  { lat: 12.0, lon: 8.52, w: 1.7 }, // Kano
  { lat: 5.6, lon: -0.19, w: 1.8 }, // Accra
  { lat: 14.72, lon: -17.47, w: 1.6 }, // Dakar
  { lat: 33.57, lon: -7.59, w: 1.9 }, // Casablanca
  { lat: 34.02, lon: -6.83, w: 1.4 }, // Rabat
  { lat: 36.75, lon: 3.06, w: 1.8 }, // Algiers
  { lat: 36.8, lon: 10.18, w: 1.6 }, // Tunis
  { lat: 32.89, lon: 13.19, w: 1.4 }, // Tripoli
  { lat: 15.5, lon: 32.56, w: 1.7 }, // Khartoum
  { lat: 9.03, lon: 38.74, w: 1.9 }, // Addis Ababa
  { lat: -1.29, lon: 36.82, w: 1.9 }, // Nairobi
  { lat: -6.79, lon: 39.21, w: 1.7 }, // Dar es Salaam
  { lat: 0.35, lon: 32.58, w: 1.6 }, // Kampala
  { lat: -4.32, lon: 15.31, w: 2.0 }, // Kinshasa
  { lat: -8.84, lon: 13.23, w: 1.7 }, // Luanda
  { lat: -26.2, lon: 28.05, w: 2.2 }, // Johannesburg
  { lat: -33.92, lon: 18.42, w: 1.8 }, // Cape Town
  { lat: -29.86, lon: 31.02, w: 1.6 }, // Durban
  { lat: -17.83, lon: 31.05, w: 1.4 }, // Harare
  { lat: -18.88, lon: 47.51, w: 1.4 }, // Antananarivo
  { lat: 4.05, lon: 9.77, w: 1.3 }, // Douala
  { lat: 5.32, lon: -4.03, w: 1.6 }, // Abidjan

  // ── The Americas ────────────────────────────────────────────────────────
  { lat: 40.71, lon: -74.01, w: 3.0 }, // New York
  { lat: 34.05, lon: -118.24, w: 2.8 }, // Los Angeles
  { lat: 41.88, lon: -87.63, w: 2.4 }, // Chicago
  { lat: 29.76, lon: -95.37, w: 2.2 }, // Houston
  { lat: 32.78, lon: -96.8, w: 2.2 }, // Dallas
  { lat: 33.45, lon: -112.07, w: 2.0 }, // Phoenix
  { lat: 25.76, lon: -80.19, w: 2.1 }, // Miami
  { lat: 33.75, lon: -84.39, w: 2.0 }, // Atlanta
  { lat: 42.36, lon: -71.06, w: 2.0 }, // Boston
  { lat: 39.95, lon: -75.17, w: 2.0 }, // Philadelphia
  { lat: 38.91, lon: -77.04, w: 2.0 }, // Washington
  { lat: 37.77, lon: -122.42, w: 2.1 }, // San Francisco
  { lat: 47.61, lon: -122.33, w: 1.9 }, // Seattle
  { lat: 39.74, lon: -104.99, w: 1.7 }, // Denver
  { lat: 44.98, lon: -93.27, w: 1.7 }, // Minneapolis
  { lat: 42.33, lon: -83.05, w: 1.7 }, // Detroit
  { lat: 36.17, lon: -115.14, w: 1.6 }, // Las Vegas
  { lat: 43.65, lon: -79.38, w: 2.1 }, // Toronto
  { lat: 45.5, lon: -73.57, w: 1.8 }, // Montreal
  { lat: 49.28, lon: -123.12, w: 1.7 }, // Vancouver
  { lat: 19.43, lon: -99.13, w: 2.8 }, // Mexico City
  { lat: 20.66, lon: -103.35, w: 1.9 }, // Guadalajara
  { lat: 25.69, lon: -100.32, w: 1.9 }, // Monterrey
  { lat: 23.13, lon: -82.38, w: 1.5 }, // Havana
  { lat: 14.63, lon: -90.51, w: 1.5 }, // Guatemala City
  { lat: 8.98, lon: -79.52, w: 1.5 }, // Panama City
  { lat: 4.71, lon: -74.07, w: 2.3 }, // Bogota
  { lat: 6.24, lon: -75.58, w: 1.7 }, // Medellin
  { lat: 10.49, lon: -66.88, w: 1.9 }, // Caracas
  { lat: -12.05, lon: -77.04, w: 2.3 }, // Lima
  { lat: -0.18, lon: -78.47, w: 1.5 }, // Quito
  { lat: -2.19, lon: -79.89, w: 1.5 }, // Guayaquil
  { lat: -23.55, lon: -46.63, w: 2.9 }, // Sao Paulo
  { lat: -22.91, lon: -43.17, w: 2.5 }, // Rio de Janeiro
  { lat: -15.79, lon: -47.88, w: 1.8 }, // Brasilia
  { lat: -12.97, lon: -38.5, w: 1.7 }, // Salvador
  { lat: -8.05, lon: -34.88, w: 1.7 }, // Recife
  { lat: -3.12, lon: -60.02, w: 1.4 }, // Manaus
  { lat: -25.43, lon: -49.27, w: 1.6 }, // Curitiba
  { lat: -30.03, lon: -51.23, w: 1.6 }, // Porto Alegre
  { lat: -34.6, lon: -58.38, w: 2.5 }, // Buenos Aires
  { lat: -31.42, lon: -64.18, w: 1.5 }, // Cordoba
  { lat: -33.45, lon: -70.67, w: 2.1 }, // Santiago
  { lat: -34.9, lon: -56.16, w: 1.4 }, // Montevideo
  { lat: -25.28, lon: -57.63, w: 1.4 }, // Asuncion
  { lat: -16.5, lon: -68.15, w: 1.4 }, // La Paz

  // ── Oceania ─────────────────────────────────────────────────────────────
  { lat: -33.87, lon: 151.21, w: 2.2 }, // Sydney
  { lat: -37.81, lon: 144.96, w: 2.1 }, // Melbourne
  { lat: -27.47, lon: 153.03, w: 1.8 }, // Brisbane
  { lat: -31.95, lon: 115.86, w: 1.6 }, // Perth
  { lat: -34.93, lon: 138.6, w: 1.4 }, // Adelaide
  { lat: -36.85, lon: 174.76, w: 1.6 }, // Auckland
  { lat: -41.29, lon: 174.78, w: 1.2 }, // Wellington
  { lat: -17.71, lon: 168.32, w: 0.9 }, // Port Vila
  { lat: -9.44, lon: 147.18, w: 1.1 }, // Port Moresby
];

/** Every light on the planet, India first so its glow composites last. */
export const ALL_LIGHTS: Light[] = [...WORLD_LIGHTS, ...INDIA_LIGHTS];

/**
 * The bounding box India's warm accent is confined to.
 *
 * §6 is emphatic that the champagne must not spread: "the rest of Asia should
 * primarily remain blue/white". The accent is applied by testing a light
 * against this box rather than by re-listing the Indian cities with a colour,
 * so the two can never disagree about which lights are the warm ones. Wide
 * enough to hold the subcontinent and its immediate neighbours, whose lights
 * are part of the same visual mass from orbit.
 */
export const SUBCONTINENT = { latMin: 5, latMax: 36, lonMin: 66, lonMax: 93 };

export function isSubcontinental(l: Light): boolean {
  return (
    l.lat >= SUBCONTINENT.latMin &&
    l.lat <= SUBCONTINENT.latMax &&
    l.lon >= SUBCONTINENT.lonMin &&
    l.lon <= SUBCONTINENT.lonMax
  );
}

/** Approximate geographic centre of India — what the globe is rotated to face. */
export const INDIA_CENTRE = { lat: 22.0, lon: 79.0 };
