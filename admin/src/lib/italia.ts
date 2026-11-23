// Mappa dell'Italia per il radar: regioni e province già proiettate (scripts/build_geo.py).
// Confini ISTAT pubblicati da openpolis/geojson-italy, licenza CC BY 4.0. Nessuna mappa esterna.

export interface Proiezione {
  larghezza: number;
  altezza: number;
  lon0: number;
  lat1: number;
  k: number;
  cos: number;
}

export interface AreaRegione {
  codice: string;
  nome: string;
  d: string;
  centro: { x: number; y: number };
}

export interface ItaliaMappa extends Proiezione {
  fonte: string;
  aree: AreaRegione[];
}

export interface AreaProvincia {
  codice: string;
  sigla: string;
  nome: string;
  tipo: string;
  d: string;
  centro: { x: number; y: number; lat: number; lng: number };
  celle: string[];
}

export interface RegioneMappa extends Proiezione {
  codice: string;
  nome: string;
  province: AreaProvincia[];
}

// Griglia del radar: identica a app/domain/radar.py e scripts/build_geo.py.
export const STEP_LAT = 0.045;
export const STEP_LNG = 0.0625;

/** Coordinate geografiche → punto della mappa. */
export function proietta(m: Proiezione, lat: number, lng: number): { x: number; y: number } {
  return { x: (lng - m.lon0) * m.cos * m.k, y: (m.lat1 - lat) * m.k };
}

export function cellaId(lat: number, lng: number): string {
  return `${Math.floor(lat / STEP_LAT)}_${Math.floor(lng / STEP_LNG)}`;
}

/** Il quadrato di una cella sulla mappa. */
export function rettangoloCella(m: Proiezione, cella: string): { x: number; y: number; w: number; h: number } {
  const [i, j] = cella.split("_").map(Number);
  const nordOvest = proietta(m, (i + 1) * STEP_LAT, j * STEP_LNG);
  const sudEst = proietta(m, i * STEP_LAT, (j + 1) * STEP_LNG);
  return { x: nordOvest.x, y: nordOvest.y, w: sudEst.x - nordOvest.x, h: sudEst.y - nordOvest.y };
}

/** Dati di copertura del radar per provincia (funzione radar_province del database). */
export interface CoperturaProvincia {
  codice: string;
  celle_totali: number;
  celle_esplorate: number;
  ricerche: number;
  ultima_ricerca: string | null;
  strutture: number;
  nuove_30_giorni: number;
}

/** Elenco delle province (tabella province del database). */
export interface ProvinciaInfo {
  codice: string;
  sigla: string;
  nome: string;
  regione_codice: string;
  regione: string;
  lat: number;
  lng: number;
}

export interface CellaEsplorata {
  cell: string;
  ultima_ricerca: string;
  ricerche: number;
  nuove: number;
  a_riposo: boolean;
}
