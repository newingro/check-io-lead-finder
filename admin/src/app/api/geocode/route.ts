import { NextResponse, type NextRequest } from "next/server";
import { createClient } from "@/lib/supabase/server";

const cache = new Map<string, { at: number; results: unknown }>();
let lastRequest = 0;

/** Ricerca di comuni e luoghi in Italia (OpenStreetMap Nominatim), solo per utenti collegati. */
export async function GET(request: NextRequest) {
  const supabase = await createClient();
  const { data } = await supabase.auth.getClaims();
  if (!data?.claims || data.claims.aal !== "aal2") {
    return NextResponse.json({ error: "Accesso richiesto." }, { status: 401 });
  }
  const q = (request.nextUrl.searchParams.get("q") ?? "").trim().slice(0, 100);
  if (q.length < 2) return NextResponse.json({ results: [] });

  const key = q.toLowerCase();
  const hit = cache.get(key);
  if (hit && Date.now() - hit.at < 24 * 60 * 60 * 1000) return NextResponse.json({ results: hit.results });

  // Nominatim chiede al massimo una richiesta al secondo.
  const wait = 1100 - (Date.now() - lastRequest);
  if (wait > 0) await new Promise((resolve) => setTimeout(resolve, wait));
  lastRequest = Date.now();

  const url = new URL("https://nominatim.openstreetmap.org/search");
  url.search = new URLSearchParams({ q, format: "jsonv2", limit: "5", countrycodes: "it", "accept-language": "it" }).toString();
  try {
    const response = await fetch(url, {
      headers: { "User-Agent": "CHECK-iO-Gestionale/1.0 (https://admin.check-io.it)" },
      signal: AbortSignal.timeout(8000),
    });
    if (!response.ok) throw new Error(String(response.status));
    const raw = (await response.json()) as Array<{ name?: string; display_name: string; lat: string; lon: string }>;
    const results = raw.map((item) => ({
      nome: item.name || item.display_name.split(",")[0],
      descrizione: item.display_name,
      lat: Number(Number(item.lat).toFixed(5)),
      lng: Number(Number(item.lon).toFixed(5)),
    }));
    cache.set(key, { at: Date.now(), results });
    return NextResponse.json({ results });
  } catch {
    return NextResponse.json({ error: "Ricerca non disponibile al momento. Puoi cliccare direttamente sulla mappa." }, { status: 502 });
  }
}
