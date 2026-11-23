import { z } from "zod";

const nome = z.string().trim().min(1, "Dai un nome alla zona.").max(80, "Massimo 80 caratteri.");

/** Zona «cerchio»: un comune o un luogo con il raggio in km (le zone salvate prima non hanno «tipo»). */
export const circleZoneSchema = z.object({
  tipo: z.literal("cerchio").optional(),
  nome,
  lat: z.number().min(-90).max(90),
  lng: z.number().min(-180).max(180),
  raggio_km: z.number().min(1, "Il raggio minimo è 1 km.").max(100, "Il raggio massimo è 100 km."),
  attiva: z.boolean().default(true),
});

/** Zona «provincia»: tutta la provincia, con il codice ISTAT a tre cifre. */
export const provinceZoneSchema = z.object({
  tipo: z.literal("provincia"),
  codice: z.string().regex(/^\d{3}$/, "Codice di provincia non valido."),
  nome,
  attiva: z.boolean().default(true),
});

export const zoneSchema = z.union([provinceZoneSchema, circleZoneSchema]);
export const zonesSchema = z.array(zoneSchema).max(150, "Massimo 150 zone.");

export type CircleZone = z.output<typeof circleZoneSchema>;
export type ProvinceZone = z.output<typeof provinceZoneSchema>;
export type Zone = z.output<typeof zoneSchema>;

export function isProvinceZone(zone: Zone): zone is ProvinceZone {
  return zone.tipo === "provincia";
}

export function isCircleZone(zone: Zone): zone is CircleZone {
  return zone.tipo !== "provincia";
}

/** Le zone salvate; quelle illeggibili si scartano una per una, senza perdere le altre. */
export function parseZones(value: unknown): Zone[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    const result = zoneSchema.safeParse(item);
    return result.success ? [result.data] : [];
  });
}

/** «Pistoia (provincia)» oppure «raggio 15 km». */
export function zoneDetail(zone: Zone): string {
  return isProvinceZone(zone) ? "provincia" : `raggio ${zone.raggio_km} km`;
}

/** Controlli che lo schema da solo non fa: nomi e province ripetuti. */
export function zonesProblem(zones: Zone[]): string | null {
  const circles = zones.filter(isCircleZone).map((z) => z.nome.trim().toLowerCase());
  if (new Set(circles).size !== circles.length) return "Ci sono due zone con lo stesso nome.";
  const codes = zones.filter(isProvinceZone).map((z) => z.codice);
  if (new Set(codes).size !== codes.length) return "Una provincia è presente due volte.";
  return null;
}

const KM_PER_DEGREE_LAT = 110.574;

/** Riquadro che contiene il cerchio della zona (per disegnare il radar sulla mappa). */
export function zoneBounds(zone: Pick<CircleZone, "lat" | "lng" | "raggio_km">): [[number, number], [number, number]] {
  const dLat = zone.raggio_km / KM_PER_DEGREE_LAT;
  const dLng = zone.raggio_km / (111.32 * Math.cos((zone.lat * Math.PI) / 180));
  return [
    [zone.lat - dLat, zone.lng - dLng],
    [zone.lat + dLat, zone.lng + dLng],
  ];
}

/** Distanza in km tra due punti (formula dell'emisenoverso). */
export function distanceKm(a: { lat: number; lng: number }, b: { lat: number; lng: number }): number {
  const R = 6371;
  const toRad = (d: number) => (d * Math.PI) / 180;
  const dLat = toRad(b.lat - a.lat);
  const dLng = toRad(b.lng - a.lng);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}
