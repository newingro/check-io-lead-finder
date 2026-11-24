import { test } from "node:test";
import assert from "node:assert/strict";
import { generateCode, generateTemporaryPassword, hashCode, normalizeCode } from "../src/lib/codes.ts";
import { distanceKm, parseZones, zoneBounds, zonesSchema } from "../src/lib/zones.ts";
import { buildShifts, formatShifts } from "../src/lib/shifts.ts";
import { settingsSchema } from "../src/lib/settings.ts";

test("codici Telegram: stessa impronta del bot Python", () => {
  // Valore calcolato con app/domain/codes.py: hash_code("ABCD-EFGH")
  assert.equal(hashCode("ABCD-EFGH"), "9ac2197d9258257b1ae8463e4214e4cd0a578bc1517f2415928b91be4283fc48");
  assert.equal(hashCode("abcd efgh"), hashCode("ABCD-EFGH"));
  assert.equal(normalizeCode(" ab-cd "), "ABCD");
  assert.match(generateCode(), /^[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}$/);
  assert.match(generateTemporaryPassword(), /^([A-HJ-NP-Z2-9]{4}-){3}[A-HJ-NP-Z2-9]{4}$/);
});

test("zone: validazione e riquadro del radar", () => {
  const zones = [{ nome: "Abetone", lat: 44.1425, lng: 10.6633, raggio_km: 15, attiva: true }];
  assert.deepEqual(parseZones(zones), zones);
  assert.equal(zonesSchema.safeParse([{ ...zones[0], raggio_km: 500 }]).success, false);
  assert.equal(zonesSchema.safeParse([{ ...zones[0], nome: "" }]).success, false);
  assert.deepEqual(parseZones("nonsense"), []);
  const [[s, w], [n, e]] = zoneBounds(zones[0]);
  assert.ok(Math.abs(distanceKm({ lat: s, lng: zones[0].lng }, { lat: n, lng: zones[0].lng }) - 30) < 0.5);
  assert.ok(Math.abs(distanceKm({ lat: zones[0].lat, lng: w }, { lat: zones[0].lat, lng: e }) - 30) < 0.5);
});

test("turni: testo leggibile", () => {
  assert.equal(formatShifts(buildShifts(["lun", "mar", "mer", "gio", "ven"], "09:00", "17:00")), "lun–ven 09:00–17:00");
  assert.equal(formatShifts({}), "nessun turno impostato");
});

test("impostazioni: limiti e formati", () => {
  const ok = {
    property_types: ["appartamento"],
    search_queries: ["casa vacanze"],
    min_score: 60,
    cards_per_run: 5,
    searches_per_run: 4,
    run_days: ["lun"],
    run_times: ["10:00", "15:30"],
    followup_days: 5,
    max_followups: 2,
    archive_after_days: 30,
    max_call_attempts: 3,
    call_retry_minutes: 120,
    monthly_ai_budget_eur: 30,
    monthly_search_budget_eur: 30,
    google_monthly_requests: 0,
    data_retention_months: 12,
  };
  assert.equal(settingsSchema.safeParse(ok).success, true);
  assert.equal(settingsSchema.safeParse({ ...ok, run_times: ["25:00"] }).success, false);
  assert.equal(settingsSchema.safeParse({ ...ok, min_score: 140 }).success, false);
  assert.equal(settingsSchema.safeParse({ ...ok, run_days: [] }).success, false);
  assert.equal(settingsSchema.safeParse({ ...ok, searches_per_run: 0 }).success, true);
  assert.equal(settingsSchema.safeParse({ ...ok, searches_per_run: 51 }).success, false);
  assert.equal(settingsSchema.safeParse({ ...ok, google_monthly_requests: -1 }).success, false);
});
