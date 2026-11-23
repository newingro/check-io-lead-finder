import { z } from "zod";

export const zoneSchema = z.object({
  nome: z.string().trim().min(1, "Dai un nome alla zona.").max(80, "Massimo 80 caratteri."),
  lat: z.number().min(-90).max(90),
  lng: z.number().min(-180).max(180),
  raggio_km: z.number().min(1, "Il raggio minimo è 1 km.").max(100, "Il raggio massimo è 100 km."),
  attiva: z.boolean().default(true),
});

export const zonesSchema = z.array(zoneSchema).max(50, "Massimo 50 zone.");

export type Zone = z.output<typeof zoneSchema>;

export function parseZones(value: unknown): Zone[] {
  const result = zonesSchema.safeParse(value);
  return result.success ? result.data : [];
}

const KM_PER_DEGREE_LAT = 110.574;

/** Riquadro che contiene il cerchio della zona (per disegnare il radar sulla mappa). */
export function zoneBounds(zone: Pick<Zone, "lat" | "lng" | "raggio_km">): [[number, number], [number, number]] {
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
