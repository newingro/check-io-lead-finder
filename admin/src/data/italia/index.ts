// File generato da scripts/build_geo.py: non modificarlo a mano.
import type { RegioneMappa } from "@/lib/italia";

export const caricaRegione: Record<string, () => Promise<RegioneMappa>> = {
  "01": () => import("./regioni/01.json").then((m) => m.default as unknown as RegioneMappa),
  "02": () => import("./regioni/02.json").then((m) => m.default as unknown as RegioneMappa),
  "03": () => import("./regioni/03.json").then((m) => m.default as unknown as RegioneMappa),
  "04": () => import("./regioni/04.json").then((m) => m.default as unknown as RegioneMappa),
  "05": () => import("./regioni/05.json").then((m) => m.default as unknown as RegioneMappa),
  "06": () => import("./regioni/06.json").then((m) => m.default as unknown as RegioneMappa),
  "07": () => import("./regioni/07.json").then((m) => m.default as unknown as RegioneMappa),
  "08": () => import("./regioni/08.json").then((m) => m.default as unknown as RegioneMappa),
  "09": () => import("./regioni/09.json").then((m) => m.default as unknown as RegioneMappa),
  "10": () => import("./regioni/10.json").then((m) => m.default as unknown as RegioneMappa),
  "11": () => import("./regioni/11.json").then((m) => m.default as unknown as RegioneMappa),
  "12": () => import("./regioni/12.json").then((m) => m.default as unknown as RegioneMappa),
  "13": () => import("./regioni/13.json").then((m) => m.default as unknown as RegioneMappa),
  "14": () => import("./regioni/14.json").then((m) => m.default as unknown as RegioneMappa),
  "15": () => import("./regioni/15.json").then((m) => m.default as unknown as RegioneMappa),
  "16": () => import("./regioni/16.json").then((m) => m.default as unknown as RegioneMappa),
  "17": () => import("./regioni/17.json").then((m) => m.default as unknown as RegioneMappa),
  "18": () => import("./regioni/18.json").then((m) => m.default as unknown as RegioneMappa),
  "19": () => import("./regioni/19.json").then((m) => m.default as unknown as RegioneMappa),
  "20": () => import("./regioni/20.json").then((m) => m.default as unknown as RegioneMappa),
};
