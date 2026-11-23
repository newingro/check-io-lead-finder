import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { cellaId, proietta, rettangoloCella } from "../src/lib/italia.ts";
import { isProvinceZone, parseZones, zoneDetail, zonesProblem, zonesSchema } from "../src/lib/zones.ts";

test("griglia del radar: stesse celle del bot Python", () => {
  // Valori calcolati con app/domain/radar.py: cell_id(lat, lng)
  assert.equal(cellaId(44.1425, 10.6633), "980_170"); // Abetone
  assert.equal(cellaId(43.7696, 11.2558), "972_180"); // Firenze
  assert.equal(cellaId(37.5, 15.09), "833_241"); // Catania
  assert.equal(cellaId(46.5, 11.35), "1033_181"); // Bolzano
});

test("la cella dell'Abetone è nella provincia di Pistoia e sta dentro la mappa", () => {
  const toscana = JSON.parse(readFileSync(new URL("../src/data/italia/regioni/09.json", import.meta.url), "utf8"));
  const pistoia = toscana.province.find((p: { codice: string }) => p.codice === "047");
  assert.ok(pistoia.celle.includes("980_170"));
  const r = rettangoloCella(toscana, "980_170");
  const abetone = proietta(toscana, 44.1425, 10.6633);
  assert.ok(abetone.x >= r.x && abetone.x <= r.x + r.w && abetone.y >= r.y && abetone.y <= r.y + r.h);
  assert.ok(r.x > 0 && r.y > 0 && r.x < toscana.larghezza && r.y < toscana.altezza);
});

test("zone: province e cerchi insieme, controlli sui doppioni", () => {
  const zones = [
    { tipo: "provincia", codice: "047", nome: "Pistoia", attiva: true },
    { nome: "Abetone", lat: 44.1425, lng: 10.6633, raggio_km: 15, attiva: true },
  ];
  const parsed = parseZones(zones);
  assert.equal(parsed.length, 2);
  assert.ok(isProvinceZone(parsed[0]) && !isProvinceZone(parsed[1]));
  assert.equal(zoneDetail(parsed[0]), "provincia");
  assert.equal(zoneDetail(parsed[1]), "raggio 15 km");
  assert.equal(zonesProblem(parsed), null);
  assert.equal(zonesProblem([...parsed, parsed[0]]), "Una provincia è presente due volte.");
  assert.equal(zonesSchema.safeParse([{ tipo: "provincia", codice: "47", nome: "X" }]).success, false);
  assert.equal(zonesSchema.safeParse([{ nome: "Senza centro", raggio_km: 10 }]).success, false);
  // Una zona rovinata non fa perdere le altre
  assert.equal(parseZones([zones[0], { nome: "rotta" }, zones[1]]).length, 2);
});
