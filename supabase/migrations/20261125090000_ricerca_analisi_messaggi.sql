-- ─────────────────────────────────────────────────────────────
-- CHECK-iO Lead Finder — fasi 2, 3 e 4
--   2. ricerca su Google Maps nelle celle del radar, con costo di ogni ricerca;
--   3. analisi AI di ogni struttura, con punteggio e motivi;
--   4. messaggi A/B e schede Telegram.
-- ─────────────────────────────────────────────────────────────

-- Quante ricerche Google fa ogni giro (si cambia dal gestionale).
alter table public.finder_settings
  add column searches_per_run smallint not null default 4 check (searches_per_run between 0 and 50);

-- Ricerche: cella, provincia, pagine pagate e quante strutture erano già note o escluse.
alter table public.search_runs
  add column cell           text,
  add column provincia      text,
  add column pages          smallint not null default 0,
  add column known_count    integer not null default 0,
  add column excluded_count integer not null default 0;
create index search_runs_started_idx on public.search_runs (started_at desc);

-- Strutture: controllo del sito, date di analisi e proposta, scheda Telegram, motivo dello scarto.
alter table public.properties
  add column website_check       jsonb,
  add column analyzed_at         timestamptz,
  add column proposed_at         timestamptz,
  add column discard_reason      text,
  add column telegram_chat_id    bigint,
  add column telegram_message_id bigint,
  add column message_edited      boolean not null default false;

-- Nuova impronta: il link di un annuncio incollato a mano (/analizza).
alter table public.property_fingerprints drop constraint property_fingerprints_kind_check;
alter table public.property_fingerprints add constraint property_fingerprints_kind_check
  check (kind in ('google', 'cin', 'telefono', 'email', 'nome_indirizzo', 'annuncio'));

-- Consumi AI: identificativo della richiesta (per i controlli) e indice per il conto del mese.
alter table public.ai_usage add column request_id text;
create index ai_usage_created_idx on public.ai_usage (created_at);
