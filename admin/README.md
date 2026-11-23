# Gestionale CHECK-iO (admin.check-io.it)

Area riservata del team, collegata allo stesso database del bot Telegram.

## Cosa si fa

| Pagina | Titolare | Commerciale |
|---|---|---|
| Panoramica | stato dei giri, pausa/ripresa, modalità, attività recenti | stato e zone (sola lettura) |
| Zone | mappa con radar: cerca un comune, centro e raggio in km, attiva/disattiva | sola lettura |
| Impostazioni | punteggio, giri, follow-up, tetti di spesa, conservazione dati | sola lettura |
| Team | account, ruoli, turni, codici Telegram, password e 2FA, sospensione | il proprio profilo |
| Profilo | cambio password | cambio password |

Ogni modifica è firmata con il nome di chi la fa e registrata; il bot la legge entro 5 minuti
e la comunica su Telegram.

## Sicurezza

- Login con email e password + **verifica in due passaggi obbligatoria** (app di autenticazione).
- Le regole del database (RLS) richiedono la verifica in due passaggi per leggere qualsiasi dato:
  anche con la password rubata, senza il telefono non si vede nulla.
- I commerciali vedono solo i propri dati; solo il titolare modifica.
- La chiave segreta di Supabase resta sul server ed è usata solo per gestire gli account.
- Le pagine non sono indicizzate dai motori di ricerca.

## Variabili (Vercel → Settings → Environment Variables)

| Variabile | Valore |
|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | URL del progetto Supabase |
| `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | chiave pubblica (`sb_publishable_…`) |
| `SUPABASE_SECRET_KEY` | chiave segreta (`sb_secret_…`), **mai in chat o nel codice** |
| `ADMIN_SETUP_CODE` | codice segreto per creare il primo titolare (almeno 12 caratteri) |
| `NEXT_PUBLIC_TELEGRAM_BOT_USERNAME` | nome del bot senza @ |

## Primo accesso

1. Apri `https://admin.check-io.it/setup`, inserisci il codice segreto, nome, email e password.
   L'account viene collegato al titolare già registrato dal bot.
2. Accedi da `/login` e attiva la verifica in due passaggi inquadrando il QR con l'app sul telefono.
3. Dalla pagina **Team** crea gli account dei commerciali: il gestionale mostra una password
   temporanea da comunicare di persona; al primo accesso la persona ne sceglie una sua.

Telefono perso: il titolare usa **Team → Reimposta 2FA**. Se lo perde il titolare, si reimposta
da Supabase (Authentication → Users → utente → Remove MFA factors).

## Sviluppo e prove

```bash
npm install
npm run verify        # lint, tipi, test, build
ADMIN_PREVIEW=1 npm run dev   # anteprima con dati finti su /anteprima/zone, /anteprima/team…
```

L'anteprima funziona solo in locale con `ADMIN_PREVIEW=1` e non è mai attiva in produzione.
