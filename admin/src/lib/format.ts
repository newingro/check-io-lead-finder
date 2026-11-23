const dateTime = new Intl.DateTimeFormat("it-IT", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "Europe/Rome",
});

export function formatDateTime(value: string | null | undefined) {
  return value ? dateTime.format(new Date(value)) : "—";
}

export const ACTION_LABELS: Record<string, string> = {
  impostazioni: "ha modificato le impostazioni",
  stato: "ha cambiato stato o modalità",
  team: "ha modificato il team",
  account_creato: "ha creato un account",
  password_reimpostata: "ha reimpostato una password",
  "2fa_reimpostata": "ha reimpostato una verifica in due passaggi",
  titolare_creato: "ha configurato il gestionale",
  codice_creato: "ha creato un codice Telegram",
  telegram_collegato: "ha collegato Telegram",
  titolare_collegato: "si è collegato come titolare",
  pausa: "ha messo in pausa i giri",
  ripresa: "ha riavviato i giri",
  modalita: "ha cambiato modalità",
};
