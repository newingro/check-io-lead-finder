export const DAYS = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"] as const;
export type Day = (typeof DAYS)[number];
export type Shifts = Partial<Record<Day, [string, string][]>>;

export function formatShifts(shifts: Shifts | null | undefined): string {
  if (!shifts || Object.keys(shifts).length === 0) return "nessun turno impostato";
  const parts: string[] = [];
  let i = 0;
  while (i < DAYS.length) {
    const slots = shifts[DAYS[i]];
    if (!slots || slots.length === 0) {
      i++;
      continue;
    }
    let end = i;
    while (end + 1 < DAYS.length && JSON.stringify(shifts[DAYS[end + 1]]) === JSON.stringify(slots)) end++;
    const label = end === i ? DAYS[i] : `${DAYS[i]}–${DAYS[end]}`;
    parts.push(`${label} ${slots.map(([a, b]) => `${a}–${b}`).join(", ")}`);
    i = end + 1;
  }
  return parts.join("; ");
}

export function buildShifts(days: string[], start: string, end: string): Shifts {
  const shifts: Shifts = {};
  for (const day of DAYS) if (days.includes(day)) shifts[day] = [[start, end]];
  return shifts;
}

export function defaultShifts(): Shifts {
  return buildShifts(["lun", "mar", "mer", "gio", "ven"], "09:00", "17:00");
}
