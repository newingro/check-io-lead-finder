"use client";

import "leaflet/dist/leaflet.css";
import { useEffect, useMemo } from "react";
import { Circle, CircleMarker, MapContainer, SVGOverlay, TileLayer, Tooltip, useMap, useMapEvents } from "react-leaflet";
import type { LatLngBoundsExpression } from "leaflet";
import { zoneBounds, type CircleZone as Zone } from "@/lib/zones";

const DEFAULT_CENTER: [number, number] = [44.1425, 10.6633]; // Abetone

interface RadarMapProps {
  zones: Zone[];
  selected: number | null;
  onSelect: (index: number) => void;
  onPick?: (lat: number, lng: number) => void;
}

function FitToSelection({ zone }: { zone: Zone | null }) {
  const map = useMap();
  useEffect(() => {
    if (zone) map.flyToBounds(zoneBounds(zone) as LatLngBoundsExpression, { padding: [24, 24], duration: 0.6 });
  }, [map, zone?.lat, zone?.lng, zone?.raggio_km]); // eslint-disable-line react-hooks/exhaustive-deps
  return null;
}

function ClickToPick({ onPick }: { onPick?: (lat: number, lng: number) => void }) {
  useMapEvents({
    click(event) {
      onPick?.(Number(event.latlng.lat.toFixed(5)), Number(event.latlng.lng.toFixed(5)));
    },
  });
  return null;
}

/** Radar: anelli concentrici e fascio che ruota dentro il cerchio della zona selezionata. */
function RadarOverlay({ zone }: { zone: Zone }) {
  const bounds = useMemo(() => zoneBounds(zone) as LatLngBoundsExpression, [zone]);
  return (
    <SVGOverlay bounds={bounds} attributes={{ viewBox: "0 0 200 200", "aria-hidden": "true" }} interactive={false}>
      <defs>
        <linearGradient id="sweep" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="#08b7a9" stopOpacity="0" />
          <stop offset="100%" stopColor="#08b7a9" stopOpacity="0.45" />
        </linearGradient>
      </defs>
      <g fill="none" stroke="#03968b" strokeOpacity="0.55" vectorEffect="non-scaling-stroke">
        <circle cx="100" cy="100" r="33" strokeDasharray="3 4" />
        <circle cx="100" cy="100" r="66" strokeDasharray="3 4" />
        <line x1="100" y1="0" x2="100" y2="200" strokeOpacity="0.25" />
        <line x1="0" y1="100" x2="200" y2="100" strokeOpacity="0.25" />
      </g>
      <g className="radar-sweep">
        <path d="M100 100 L200 100 A100 100 0 0 0 170.7 29.3 Z" fill="url(#sweep)" />
        <line x1="100" y1="100" x2="200" y2="100" stroke="#35cdbd" strokeWidth="1.2" />
        <animateTransform attributeName="transform" type="rotate" from="0 100 100" to="360 100 100" dur="4s" repeatCount="indefinite" />
      </g>
    </SVGOverlay>
  );
}

export default function RadarMap({ zones, selected, onSelect, onPick }: RadarMapProps) {
  const selectedZone = selected !== null ? zones[selected] ?? null : null;
  const center = selectedZone ? ([selectedZone.lat, selectedZone.lng] as [number, number]) : zones[0] ? ([zones[0].lat, zones[0].lng] as [number, number]) : DEFAULT_CENTER;

  return (
    <MapContainer center={center} zoom={10} scrollWheelZoom className="h-[420px] w-full rounded-lg sm:h-[520px]">
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        maxZoom={18}
      />
      <ClickToPick onPick={onPick} />
      <FitToSelection zone={selectedZone} />
      {zones.map((zone, index) => (
        <Circle
          key={`${zone.nome}-${index}`}
          center={[zone.lat, zone.lng]}
          radius={zone.raggio_km * 1000}
          eventHandlers={{ click: () => onSelect(index) }}
          pathOptions={{
            color: zone.attiva ? "#03968b" : "#5b6b77",
            weight: index === selected ? 2.5 : 1.5,
            dashArray: zone.attiva ? undefined : "6 6",
            fillColor: zone.attiva ? "#08b7a9" : "#5b6b77",
            fillOpacity: index === selected ? 0.12 : 0.06,
          }}
        >
          <Tooltip direction="top">
            {zone.nome} · {zone.raggio_km} km{zone.attiva ? "" : " (disattivata)"}
          </Tooltip>
        </Circle>
      ))}
      {selectedZone ? <RadarOverlay zone={selectedZone} /> : null}
      {zones.map((zone, index) => (
        <CircleMarker
          key={`c-${zone.nome}-${index}`}
          center={[zone.lat, zone.lng]}
          radius={5}
          pathOptions={{ color: "#fff", weight: 2, fillColor: "#0b1a2a", fillOpacity: 1 }}
          eventHandlers={{ click: () => onSelect(index) }}
        />
      ))}
    </MapContainer>
  );
}
