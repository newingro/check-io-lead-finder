"use client";

import { useMemo, useState, useTransition } from "react";
import { Map as MapIcon, MapPin } from "lucide-react";
import { saveZones } from "@/app/(app)/actions";
import { Button, cn, Notice } from "@/components/ui";
import type { CellaEsplorata, CoperturaProvincia, ProvinciaInfo } from "@/lib/italia";
import { isCircleZone, isProvinceZone, zonesProblem, type CircleZone, type Zone } from "@/lib/zones";
import { CircleZones } from "./CircleZones";
import { ItalyRadar, type ProvinceChoice } from "./ItalyRadar";

type Tab = "italia" | "cerchi";

interface ZonesEditorProps {
  initialZones: Zone[];
  canEdit: boolean;
  province: ProvinciaInfo[];
  coverage: CoperturaProvincia[];
  previewCells?: Record<string, CellaEsplorata[]>;
}

export function ZonesEditor({ initialZones, canEdit, province, coverage, previewCells }: ZonesEditorProps) {
  const [zones, setZones] = useState<Zone[]>(initialZones);
  const [saved, setSaved] = useState(() => JSON.stringify(initialZones));
  const [tab, setTab] = useState<Tab>("italia");
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const [pending, startTransition] = useTransition();

  const dirty = JSON.stringify(zones) !== saved;
  const provinceZones = zones.filter(isProvinceZone);
  const circles = zones.filter(isCircleZone);
  const activeCodes = useMemo(() => new Set(zones.filter(isProvinceZone).filter((z) => z.attiva).map((z) => z.codice)), [zones]);
  const coverageByCode = useMemo(() => Object.fromEntries(coverage.map((c) => [c.codice, c])), [coverage]);

  function toggleProvinces(items: ProvinceChoice[], active: boolean) {
    setMessage(null);
    setZones((prev) => {
      const codes = new Set(items.map((i) => i.codice));
      const rest = prev.filter((z) => !(isProvinceZone(z) && codes.has(z.codice)));
      if (!active) return rest;
      const added: Zone[] = items.map((i) => ({ tipo: "provincia", codice: i.codice, nome: i.nome, attiva: true }));
      return [...rest.filter(isProvinceZone), ...added, ...rest.filter(isCircleZone)];
    });
  }

  function changeCircles(next: CircleZone[]) {
    setMessage(null);
    setZones((prev) => [...prev.filter(isProvinceZone), ...next]);
  }

  function save() {
    if (circles.some((z) => !z.nome.trim())) {
      setMessage({ tone: "error", text: "Ogni comune con raggio deve avere un nome." });
      return;
    }
    const clean = zones.map((z) => ({ ...z, nome: z.nome.trim() }));
    const problem = zonesProblem(clean);
    if (problem) {
      setMessage({ tone: "error", text: problem });
      return;
    }
    startTransition(async () => {
      const result = await saveZones(clean);
      if (result.ok) {
        setSaved(JSON.stringify(zones));
        setMessage({ tone: "ok", text: "Zone salvate. Il bot le userà dal prossimo giro e lo comunicherà su Telegram." });
      } else {
        setMessage({ tone: "error", text: result.error });
      }
    });
  }

  const tabs: { id: Tab; label: string; short: string; icon: typeof MapIcon; count: number }[] = [
    { id: "italia", label: "Regioni e province", short: "Province", icon: MapIcon, count: provinceZones.length },
    { id: "cerchi", label: "Comune e raggio", short: "Comuni", icon: MapPin, count: circles.length },
  ];

  return (
    <div className="space-y-6">
      <div role="tablist" aria-label="Tipo di zona" className="grid w-full grid-cols-2 gap-1 rounded-lg border border-line bg-white p-1 sm:inline-grid sm:w-auto">
        {tabs.map(({ id, label, short, icon: Icon, count }) => (
          <button
            key={id}
            type="button"
            role="tab"
            id={`tab-${id}`}
            aria-selected={tab === id}
            aria-controls={`panel-${id}`}
            aria-label={`${label} (${count})`}
            onClick={() => setTab(id)}
            className={cn(
              "inline-flex min-h-10 items-center justify-center gap-2 rounded-md px-3 text-sm font-semibold transition-colors",
              tab === id ? "bg-navy-900 text-white" : "text-navy-900 hover:bg-mist",
            )}
          >
            <Icon aria-hidden="true" className="size-4 shrink-0" />
            <span className="sm:hidden">{short}</span>
            <span className="hidden sm:inline">{label}</span>
            <span className={cn("rounded-full px-1.5 text-xs tabular-nums", tab === id ? "bg-white/15" : "bg-mist")}>{count}</span>
          </button>
        ))}
      </div>

      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === "italia" ? (
          <ItalyRadar
            province={province}
            coverage={coverageByCode}
            activeCodes={activeCodes}
            circles={circles}
            canEdit={canEdit}
            onToggle={toggleProvinces}
            previewCells={previewCells}
          />
        ) : (
          <CircleZones zones={circles} onChange={changeCircles} canEdit={canEdit} />
        )}
      </div>

      <div className="sticky bottom-0 z-[1100] -mx-4 border-t border-line bg-paper/95 px-4 py-2.5 backdrop-blur sm:mx-0 sm:rounded-lg sm:border sm:py-3">
        {canEdit ? (
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between sm:gap-3">
            <div className="min-w-0 text-sm">
              {message ? (
                <Notice tone={message.tone}>{message.text}</Notice>
              ) : (
                <p className="hidden text-slate sm:block">
                  {provinceZones.length} {provinceZones.length === 1 ? "provincia" : "province"} e {circles.length}{" "}
                  {circles.length === 1 ? "comune con raggio" : "comuni con raggio"}
                  {dirty ? " · modifiche da salvare" : ""}
                </p>
              )}
            </div>
            <Button type="button" onClick={save} disabled={!dirty || pending} className="shrink-0">
              {pending ? "Salvataggio…" : dirty ? "Salva le zone" : "Nessuna modifica"}
            </Button>
          </div>
        ) : (
          <Notice tone="info">Le zone le imposta il titolare. Tu puoi consultarle.</Notice>
        )}
      </div>
    </div>
  );
}
