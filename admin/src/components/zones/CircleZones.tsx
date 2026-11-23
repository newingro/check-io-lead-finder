"use client";

import dynamic from "next/dynamic";
import { useState } from "react";
import { MapPin, Plus, Search, Trash2 } from "lucide-react";
import { Badge, Button, cn, Notice } from "@/components/ui";
import type { CircleZone as Zone } from "@/lib/zones";

const RadarMap = dynamic(() => import("./RadarMap"), {
  ssr: false,
  loading: () => <div className="flex h-[420px] items-center justify-center rounded-lg bg-mist text-sm text-slate sm:h-[520px]">Caricamento mappa…</div>,
});

interface Place {
  nome: string;
  descrizione: string;
  lat: number;
  lng: number;
}

/** Zone «comune e raggio» sulla mappa OpenStreetMap. Il salvataggio lo fa ZonesEditor. */
export function CircleZones({ zones, onChange, canEdit }: { zones: Zone[]; onChange: (zones: Zone[]) => void; canEdit: boolean }) {
  const [selected, setSelected] = useState<number | null>(zones.length ? 0 : null);
  const [query, setQuery] = useState("");
  const [places, setPlaces] = useState<Place[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const current = selected !== null ? zones[selected] : null;

  function update(index: number, patch: Partial<Zone>) {
    onChange(zones.map((zone, i) => (i === index ? { ...zone, ...patch } : zone)));
    setMessage(null);
  }

  function addZone(place?: Place) {
    const base = place ?? (current ? { nome: "", lat: current.lat, lng: current.lng } : { nome: "", lat: 44.1425, lng: 10.6633 });
    const zone: Zone = { tipo: "cerchio", nome: place?.nome ?? "", lat: base.lat, lng: base.lng, raggio_km: 10, attiva: true };
    onChange([...zones, zone]);
    setSelected(zones.length);
    setPlaces(null);
    setQuery("");
    setMessage(null);
  }

  function removeZone(index: number) {
    onChange(zones.filter((_, i) => i !== index));
    setSelected(zones.length > 1 ? 0 : null);
    setMessage(null);
  }

  async function search(event: React.FormEvent) {
    event.preventDefault();
    if (query.trim().length < 2) return;
    setSearching(true);
    setPlaces(null);
    try {
      const response = await fetch(`/api/geocode?q=${encodeURIComponent(query.trim())}`);
      const body = (await response.json()) as { results?: Place[]; error?: string };
      if (!response.ok) throw new Error(body.error ?? "Ricerca non riuscita.");
      setPlaces(body.results ?? []);
    } catch (error) {
      setMessage({ tone: "error", text: error instanceof Error ? error.message : "Ricerca non riuscita." });
    } finally {
      setSearching(false);
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_22rem]">
      <div className="card overflow-hidden p-2">
        <RadarMap
          zones={zones}
          selected={selected}
          onSelect={setSelected}
          onPick={canEdit && selected !== null ? (lat, lng) => update(selected, { lat, lng }) : undefined}
        />
        {canEdit ? (
          <p className="hint px-2 py-2">
            {selected !== null
              ? "Clicca sulla mappa per spostare il centro della zona selezionata."
              : "Cerca un comune o aggiungi una zona per iniziare."}
          </p>
        ) : null}
      </div>

      <div className="space-y-5">
        {canEdit ? (
          <form onSubmit={search} className="card space-y-3 p-4" role="search">
            <label className="label" htmlFor="place">
              Cerca un comune o un luogo
            </label>
            <div className="flex gap-2">
              <input id="place" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Es. Abetone" className="input" />
              <Button type="submit" variant="secondary" disabled={searching} aria-label="Cerca">
                <Search aria-hidden="true" className="size-4" />
              </Button>
            </div>
            {searching ? <p className="hint">Ricerca in corso…</p> : null}
            {places && places.length === 0 ? <p className="hint">Nessun risultato in Italia.</p> : null}
            {places && places.length > 0 ? (
              <ul className="divide-y divide-line rounded-md border border-line">
                {places.map((place) => (
                  <li key={`${place.lat},${place.lng}`}>
                    <button type="button" onClick={() => addZone(place)} className="flex w-full items-start gap-2 px-3 py-2 text-left text-sm hover:bg-paper">
                      <MapPin aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-turq-700" />
                      <span>
                        <span className="font-medium text-navy-900">{place.nome}</span>
                        <span className="block text-xs text-slate">{place.descrizione}</span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
          </form>
        ) : null}

        <div className="card p-4">
          <div className="flex items-center justify-between gap-2">
            <h2 className="font-semibold text-navy-900">Comuni e raggi ({zones.length})</h2>
            {canEdit ? (
              <Button type="button" variant="ghost" onClick={() => addZone()} className="min-h-9 px-2">
                <Plus aria-hidden="true" className="size-4" /> Nuova
              </Button>
            ) : null}
          </div>
          {zones.length === 0 ? <p className="mt-3 text-sm text-slate">Nessun comune con raggio. Puoi usare solo le province, oppure aggiungere qui un luogo preciso (es. Abetone, 15 km).</p> : null}
          <ul className="mt-3 space-y-1.5">
            {zones.map((zone, index) => (
              <li key={index}>
                <button
                  type="button"
                  onClick={() => setSelected(index)}
                  aria-current={index === selected}
                  className={cn(
                    "flex w-full items-center justify-between gap-2 rounded-md border px-3 py-2 text-left text-sm",
                    index === selected ? "border-turq-600 bg-turq-500/10" : "border-line bg-white hover:border-navy-900/30",
                  )}
                >
                  <span className="font-medium text-navy-900">{zone.nome || "Zona senza nome"}</span>
                  <Badge tone={zone.attiva ? "ok" : "off"}>{zone.raggio_km} km</Badge>
                </button>
              </li>
            ))}
          </ul>
        </div>

        {current && selected !== null ? (
          <div className="card space-y-4 p-4">
            <h2 className="font-semibold text-navy-900">Zona selezionata</h2>
            <div>
              <label className="label" htmlFor="zone-name">
                Nome
              </label>
              <input
                id="zone-name"
                value={current.nome}
                maxLength={80}
                disabled={!canEdit}
                onChange={(e) => update(selected, { nome: e.target.value })}
                className="input"
              />
            </div>
            <div>
              <label className="label" htmlFor="zone-radius">
                Raggio: <span className="tabular-nums">{current.raggio_km} km</span>
              </label>
              <input
                id="zone-radius"
                type="range"
                min={1}
                max={100}
                step={1}
                value={current.raggio_km}
                disabled={!canEdit}
                onChange={(e) => update(selected, { raggio_km: Number(e.target.value) })}
                className="w-full accent-turq-600"
              />
              <div className="flex justify-between text-xs text-slate">
                <span>1 km</span>
                <span>100 km</span>
              </div>
            </div>
            <p className="text-xs text-slate tabular-nums">
              Centro: {current.lat.toFixed(4)}, {current.lng.toFixed(4)}
            </p>
            <label className="flex items-center gap-2 text-sm text-navy-900">
              <input
                type="checkbox"
                checked={current.attiva}
                disabled={!canEdit}
                onChange={(e) => update(selected, { attiva: e.target.checked })}
                className="size-4 accent-turq-600"
              />
              Zona attiva (il bot la usa nelle ricerche)
            </label>
            {canEdit ? (
              <Button type="button" variant="danger" onClick={() => removeZone(selected)} className="w-full">
                <Trash2 aria-hidden="true" className="size-4" /> Elimina zona
              </Button>
            ) : null}
          </div>
        ) : null}

        {message ? <Notice tone={message.tone}>{message.text}</Notice> : null}
      </div>
    </div>
  );
}
