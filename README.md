# CHECK-iO Lead Finder

Bot Telegram che trova strutture in affitto breve, le analizza e prepara per il team di CHECK-iO
messaggi personalizzati da approvare e inviare a mano.

Il progetto procede per fasi. Fatte: fase 1 (fondamenta), radar e memoria, fase 2 (ricerca), fase 3 (analisi), fase 4 (messaggi e
schede). Prossima: fase 5 (telefonate, esiti, richiami, follow-up, riepilogo serale).

## Comandi del bot

| Comando | Chi | Cosa fa |
|---|---|---|
| `/start`, `/aiuto` | tutti | benvenuto ed elenco dei comandi |
| `/collega CODICE` | chiunque abbia ricevuto un codice | collega il proprio Telegram |
| `/io` | team | nome, ruolo e turni |
| `/stato` | team | giri attivi o in pausa, modalità, zone |
| `/codice Nome` | titolare | crea il codice per collegare un commerciale (valido 15 minuti, una volta sola) |
| `/codice Nome titolare` | titolare | come sopra, con ruolo di titolare |
| `/team` | titolare | le persone del team e il loro stato |
| `/pausa`, `/riprendi` | titolare | ferma o riavvia i giri |
| `/modalita telefonate` · `messaggi` · `misto` | titolare | cambia la modalità |
| `/impostazioni` | titolare | le impostazioni attuali |
| `/cerca` | titolare | fa partire subito un giro (ricerca, analisi, schede) |
| `/analizza link + testo` | team | analizza un annuncio trovato a mano (incolla il testo: il bot non apre i portali) |
| `/annulla` | team | annulla una modifica in corso |
| `/verifica` | titolare | controlla le chiavi di Google e Anthropic, senza spendere |

Chi non fa parte del team riceve solo un messaggio di cortesia. Il bot parte **in pausa**.
Le schede delle strutture arrivano con i pulsanti (vedi «Ricerca, analisi e schede»).

## Come funziona il primo collegamento

1. Sul server si imposta la variabile `OWNER_SETUP_CODE`: un codice segreto inventato da te (almeno 12 caratteri).
2. Apri il bot su Telegram e scrivi `/collega` seguito da quel codice: diventi **titolare**.
   Funziona una sola volta; dopo, quel codice non serve più.
3. Per collegare un commerciale scrivi `/codice Matteo`: il bot ti dà un codice da inoltrargli.
   Matteo apre il bot e scrive `/collega CODICE`.

I codici sono validi 15 minuti, si usano una sola volta e nel database resta solo la loro impronta
(nessuno può leggerli). Dopo 5 tentativi sbagliati in un'ora il collegamento si blocca.

## Impostazioni

Stanno nella tabella `finder_settings` (zone, tipi di struttura, ricerche, punteggio minimo,
schede per giro, orari, follow-up, tetti di spesa…) e `finder_state` (pausa e modalità).
Si cambiano dal gestionale (quando sarà pronto) o dall'editor tabelle di Supabase: il bot le
rilegge ogni 5 minuti e avvisa su Telegram cosa è cambiato. Non serve ripubblicare il bot.

## Messa online

### 1. Database (Supabase)

1. Crea il progetto Supabase (regione Europa).
2. Apri **SQL Editor**, incolla il contenuto di `supabase/migrations/20261123090000_fondamenta.sql` ed esegui.
3. **Project Settings → Database → Connection string**: copia la stringa in modalità
   **Session pooler** e sostituisci `[YOUR-PASSWORD]` con la password del database.
   Questo valore va in `DATABASE_URL` su Railway (mai in chat).

Tutte le tabelle hanno la sicurezza per righe attiva: le chiavi pubbliche di Supabase non vedono nulla.

### 2. Server (Railway)

1. Su railway.app: **New Project → Deploy from GitHub repo** e scegli questo repository.
2. Nel servizio, scheda **Variables**, aggiungi:
   - `TELEGRAM_BOT_TOKEN`: il token di @BotFather
   - `DATABASE_URL`: la stringa del punto 1
   - `OWNER_SETUP_CODE`: il tuo codice segreto di primo avvio
3. Railway installa e avvia il bot da solo (`python -m app.main`) e lo riavvia se si ferma.
   Deve esserci **una sola copia** del bot in esecuzione.

Variabili facoltative: `TIMEZONE` (predefinito `Europe/Rome`), `SETTINGS_POLL_SECONDS` (300),
`LINK_CODE_TTL_MINUTES` (15), `LOG_LEVEL` (INFO).

## Prove

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

Le prove usano dati finti e nessuna rete. Le prove sul database vero si attivano impostando
`TEST_DATABASE_ADMIN_URL` (un Postgres locale: il database di prova viene creato e cancellato da solo).

## Radar e memoria storica

Le zone possono essere **intere province** (scelte sulla mappa dell'Italia nel gestionale) oppure
**un comune con il suo raggio**. Il radar divide ogni zona in celle di circa 5 km × 5 km e cerca
una cella alla volta (`app/domain/radar.py`):

- prima le celle mai cercate, poi quelle cercate da più tempo, alternando le zone;
- una cella che per 2 ricerche di fila non dà strutture nuove riposa 30 giorni (poi 90);
- ogni ricerca resta in `search_cells` (quando, quanti risultati, quante nuove).

**Una struttura già trovata non torna mai come nuova** (`app/domain/dedupe.py`): di ogni struttura
si salvano le impronte cifrate (SHA-256) di scheda Google, CIN, telefono, email e nome+indirizzo;
basta un'impronta in comune per riconoscerla, anche se arriva da un altro annuncio. Le impronte
restano anche quando i dati vengono cancellati per il periodo di conservazione
(`pulisci_memoria()`, i clienti non si cancellano). Chi ha chiesto di non essere contattato non
viene mai salvato né rimesso in ricerca. Solo il titolare può rimettere a mano una struttura
nella ricerca (pagina *Memoria* del gestionale), e ogni consultazione resta nello storico.

La ricerca su Google Places arriva nella fase 2 e userà `RadarService` (`app/services/radar.py`).

Confini di regioni e province: ISTAT 2026, pubblicati da openpolis/geojson-italy (CC BY 4.0).
Per aggiornarli: scarica `limits_IT_regions.geojson` e `limits_IT_provinces.geojson` in una
cartella e lancia `python -I scripts/build_geo.py CARTELLA` (rigenera mappa, celle e migrazione).

## Ricerca, analisi e schede (fasi 2-4)

A ogni giro (orari e giorni dalle impostazioni, solo se i giri non sono in pausa) il bot:

1. **Cerca** su Google Maps (Places API) nelle celle scelte dal radar, con le parole delle impostazioni.
   Ogni ricerca è una sola richiesta a Google (fino a 20 strutture per cella): richieste e risultati finiscono in `search_runs`.
   Hotel, ostelli, campeggi e strutture chiuse vengono esclusi (si ricorda solo l'impronta).
2. **Legge il sito proprio** della struttura (mai Booking, Airbnb o Trivago): email pubblica, CIN, portali.
3. **Analizza** con Claude (JSON strutturato): profilo, recensioni (al massimo 5, quelle che dà Google, senza
   i nomi degli autori), segnali di opportunità, esclusioni e punteggio 0-100 con i motivi. Le strutture senza
   telefono né email pubblici si scartano senza spendere. Le recensioni non si salvano.
4. **Prepara le schede**: per le migliori (punteggio ≥ minimo, fino a «schede per giro») scrive i messaggi
   WhatsApp, email e la scheda telefonata in versione A (analisi gratuita) o B (chiacchierata di 10 minuti),
   li controlla in automatico (niente numeri inventati, percentuali, frasi vietate; chi siamo, come l'abbiamo
   trovato, come dire no) e manda la scheda a chi è di turno, con il carico distribuito.
5. **Riepilogo al titolare** con la spesa del giro e del mese.

Pulsanti della scheda: Approva · Modifica · Scarta · Email · Telefonata · Già gestita da altri · Non contattare;
dopo l'approvazione: Apri WhatsApp (messaggio già scritto) · Inviato · Testo email · Inviata. L'invio resta
sempre manuale. Ogni passaggio finisce nello storico della struttura.

Comandi: `/cerca` (titolare, un giro subito), `/analizza link + testo incollato` (tutti: analizza un annuncio
trovato a mano; il bot non apre i portali), `/annulla`.

**Google gratis**: nel gestionale (Impostazioni) «Massimo richieste Google al mese» = le richieste gratuite di Google.
Il bot conta ogni richiesta (anche quelle fallite) e si ferma da solo raggiunto il numero; così la ricerca funziona
anche senza `GOOGLE_TEXT_SEARCH_USD_PER_1000`. Con 0 e senza prezzo la ricerca Google resta spenta.

**Tetti di spesa**: prima di ogni ricerca e di ogni chiamata AI si controlla la spesa del mese contro i tetti
del gestionale. Consiglio: imposta anche un limite di richieste al giorno nella console di Google Cloud.

**Variabili su Railway** (mai in chat): `GOOGLE_MAPS_API_KEY`, `GOOGLE_TEXT_SEARCH_USD_PER_1000` (prezzo dello SKU
«Text Search Enterprise + Atmosphere» dalla pagina prezzi di Google), `ANTHROPIC_API_KEY`; facoltative
`CLAUDE_MODEL` (predefinito `claude-opus-5-5`), `CLAUDE_EFFORT` (predefinito `medium`), `EUR_PER_USD`
(predefinito 1: un dollaro contato come un euro).

**Da verificare con il consulente prima della partenza**: testo del primo contatto, base giuridica per WhatsApp
ed email, e i termini di Google Maps Platform sulla conservazione dei dati delle schede.

## Gestionale web

La cartella `admin/` contiene il gestionale (Next.js) pubblicato su **admin.check-io.it**:
zone con mappa e raggio, impostazioni, pausa e modalità, team e account. Istruzioni in `admin/README.md`.

## Struttura

```
app/
  main.py          avvio del bot
  config.py        variabili del server
  bot/             comandi Telegram e testi
  db/              database: Postgres (Supabase) e versione in memoria per le prove
  domain/          codici, turni, impostazioni in italiano
  services/        collegamento, pausa e modalità, controllo delle impostazioni
admin/               gestionale web (admin.check-io.it)
scripts/build_geo.py   confini e celle del radar (si lancia a mano)
supabase/migrations/   tabelle e sicurezza
supabase/tests/        prove delle regole di accesso
tests/                 prove automatiche
```

## Sicurezza

- Token e connessioni solo nelle variabili del server, mai nel codice o in chat.
- I log non contengono il token del bot né dati personali.
- Comandi del titolare protetti; il collegamento si fa solo in chat privata.
