"""Testi del bot, in italiano semplice."""

NOT_MEMBER = (
    "Ciao! Questo bot è riservato al team CHECK-iO.\n\n"
    "Se fai parte del team, chiedi al titolare un codice e scrivi qui:\n"
    "/collega CODICE"
)
OWNER_ONLY = "Questo comando è riservato al titolare."
UNKNOWN_COMMAND = "Comando non riconosciuto. Scrivi /aiuto per l'elenco dei comandi."
ONLY_COMMANDS = "Rispondo ai comandi e ai pulsanti delle schede. Scrivi /aiuto per l'elenco."
GENERIC_ERROR = "Si è verificato un errore. Riprova tra poco: se continua, avvisa il titolare."
SUSPENDED = "Il tuo accesso è sospeso. Per informazioni contatta il titolare."

HELP_MEMBER = (
    "Comandi disponibili:\n"
    "/io — chi sei, ruolo e turni\n"
    "/stato — giri attivi o in pausa e modalità\n"
    "/analizza link + testo — analizza un annuncio che hai trovato (incolla il testo: il bot non apre i portali)\n"
    "/annulla — annulla una modifica in corso\n"
    "/aiuto — questo elenco\n\n"
    "Le schede delle strutture arrivano qui quando sei di turno: approva, modifica o scarta, "
    "poi invia tu il messaggio e premi «Inviato»."
)
HELP_OWNER = (
    "\n\nComandi del titolare:\n"
    "/codice Nome — crea il codice per collegare una persona\n"
    "/codice Nome titolare — come sopra, ma con ruolo di titolare\n"
    "/team — le persone del team\n"
    "/pausa · /riprendi — ferma o riavvia i giri\n"
    "/modalita telefonate | messaggi | misto — cambia la modalità\n"
    "/impostazioni — le impostazioni attuali\n"
    "/cerca — fai partire un giro adesso (ricerca, analisi, schede)\n"
    "/verifica — controlla le chiavi di Google e Anthropic, senza spendere"
)

COLLEGA_USAGE = "Scrivi il codice che hai ricevuto, per esempio:\n/collega ABCD-EFGH"
CODICE_USAGE = "Scrivi il nome della persona, per esempio:\n/codice Matteo\n/codice Matteo titolare"
MODALITA_USAGE = "Scegli una modalità:\n/modalita telefonate\n/modalita messaggi\n/modalita misto"

LINK_MESSAGES = {
    "non_valido": "Codice non valido. Controlla di averlo scritto bene, oppure chiedine uno nuovo al titolare.",
    "scaduto": "Il codice è scaduto. Chiedine uno nuovo al titolare.",
    "gia_usato": "Questo codice è già stato usato. Chiedine uno nuovo al titolare.",
    "altro_account": "Questo account Telegram è già collegato a un'altra persona del team.",
    "troppi_tentativi": "Troppi tentativi sbagliati. Riprova tra un'ora.",
}
