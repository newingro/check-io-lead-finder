/**
 * Codici temporanei per collegare Telegram: stesso formato e stessa impronta
 * del bot (app/domain/codes.py), così il bot li riconosce con /collega.
 */
import { createHash, randomInt } from "node:crypto";

export const ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789";

export function generateCode(): string {
  let raw = "";
  for (let i = 0; i < 8; i++) raw += ALPHABET[randomInt(ALPHABET.length)];
  return `${raw.slice(0, 4)}-${raw.slice(4)}`;
}

export function normalizeCode(value: string): string {
  return [...value.toUpperCase()].filter((ch) => /[\p{L}\p{N}]/u.test(ch)).join("");
}

export function hashCode(value: string): string {
  return createHash("sha256").update(normalizeCode(value)).digest("hex");
}

/** Password temporanea leggibile, da comunicare di persona. */
export function generateTemporaryPassword(): string {
  const groups: string[] = [];
  for (let g = 0; g < 4; g++) {
    let part = "";
    for (let i = 0; i < 4; i++) part += ALPHABET[randomInt(ALPHABET.length)];
    groups.push(part);
  }
  return groups.join("-");
}
