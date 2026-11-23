-- ─────────────────────────────────────────────────────────────
-- CHECK-iO Lead Finder — schema di partenza (fase 1)
--
-- Tutte le tabelle hanno la sicurezza per righe (RLS) attiva e
-- nessuna regola di accesso pubblico: le chiavi pubbliche di Supabase
-- non leggono né scrivono nulla. Il bot si collega dal server con la
-- connessione riservata al database. Le regole per il gestionale
-- (utenti autenticati con ruoli) verranno aggiunte nella sua fase.
-- ─────────────────────────────────────────────────────────────

-- Aggiorna updated_at a ogni modifica.
create or replace function set_updated_at() returns trigger
language plpgsql set search_path = '' as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

-- Incrementa la versione delle righe di configurazione, così il bot
-- capisce quando sono state cambiate (anche dal gestionale).
create or replace function bump_version() returns trigger
language plpgsql set search_path = '' as $$
begin
  if row(new.*) is distinct from row(old.*) then
    new.version := old.version + 1;
    new.updated_at := now();
  end if;
  return new;
end;
$$;

-- ── Persone del team ─────────────────────────────────────────
create table lead_finders (
  id                     uuid primary key default gen_random_uuid(),
  name                   text not null check (length(trim(name)) between 1 and 80),
  role                   text not null check (role in ('titolare', 'commerciale')),
  telegram_user_id       bigint unique,
  telegram_chat_id       bigint,
  telegram_username      text,
  -- Turni: {"lun": [["09:00","17:00"]], "mar": [...], ...}
  shifts                 jsonb not null default '{}'::jsonb,
  receives_cards         boolean not null default true,
  receives_daily_summary boolean not null default false,
  is_active              boolean not null default true,
  linked_at              timestamptz,
  created_at             timestamptz not null default now(),
  updated_at             timestamptz not null default now()
);
create trigger lead_finders_updated_at before update on lead_finders
  for each row execute function set_updated_at();

-- Codici temporanei per collegare Telegram (salvati solo come impronta).
create table link_codes (
  id             uuid primary key default gen_random_uuid(),
  code_hash      text not null unique,
  lead_finder_id uuid not null references lead_finders(id) on delete cascade,
  created_by     uuid references lead_finders(id) on delete set null,
  expires_at     timestamptz not null,
  used_at        timestamptz,
  created_at     timestamptz not null default now()
);
create index link_codes_lead_finder_idx on link_codes (lead_finder_id);

-- ── Impostazioni (una sola riga) ─────────────────────────────
create table finder_settings (
  id                        smallint primary key default 1 check (id = 1),
  -- Zone: [{"nome": "Abetone", "lat": 44.14, "lng": 10.66, "raggio_km": 15, "attiva": true}]
  zones                     jsonb not null default '[]'::jsonb,
  property_types            text[] not null default array[
                              'appartamento', 'stanza', 'b&b', 'casa vacanze', 'affittacamere', 'guest house'],
  search_queries            text[] not null default array[
                              'casa vacanze', 'appartamenti vacanze', 'B&B', 'affittacamere', 'guest house'],
  min_score                 smallint not null default 60 check (min_score between 0 and 100),
  cards_per_run             smallint not null default 5 check (cards_per_run between 1 and 50),
  run_times                 text[] not null default array['10:00', '12:30', '15:00'],
  run_days                  text[] not null default array['lun', 'mar', 'mer', 'gio', 'ven'],
  followup_days             smallint not null default 5 check (followup_days between 1 and 60),
  max_followups             smallint not null default 2 check (max_followups between 0 and 5),
  archive_after_days        smallint not null default 30 check (archive_after_days between 1 and 365),
  max_call_attempts         smallint not null default 3 check (max_call_attempts between 1 and 10),
  call_retry_minutes        smallint not null default 120 check (call_retry_minutes between 30 and 1440),
  monthly_ai_budget_eur     numeric(8, 2) not null default 30 check (monthly_ai_budget_eur >= 0),
  monthly_search_budget_eur numeric(8, 2) not null default 30 check (monthly_search_budget_eur >= 0),
  data_retention_months     smallint not null default 12 check (data_retention_months between 1 and 60),
  version                   integer not null default 1,
  updated_by                text,
  updated_at                timestamptz not null default now()
);
create trigger finder_settings_version before update on finder_settings
  for each row execute function bump_version();
insert into finder_settings (id) values (1);

-- ── Stato: pausa e modalità (una sola riga) ──────────────────
create table finder_state (
  id         smallint primary key default 1 check (id = 1),
  paused     boolean not null default true,
  mode       text not null default 'misto' check (mode in ('telefonate', 'messaggi', 'misto')),
  version    integer not null default 1,
  updated_by text,
  updated_at timestamptz not null default now()
);
create trigger finder_state_version before update on finder_state
  for each row execute function bump_version();
-- Si parte in pausa: i giri si attivano solo quando tutto è pronto.
insert into finder_state (id) values (1);

-- ── Fasce orarie per le telefonate ───────────────────────────
create table call_windows (
  id         serial primary key,
  owner_type text not null default 'tutti' check (owner_type in ('privato', 'professionale', 'tutti')),
  weekday    smallint not null check (weekday between 1 and 7), -- 1 = lunedì
  start_time time not null,
  end_time   time not null,
  check (start_time < end_time)
);
insert into call_windows (owner_type, weekday, start_time, end_time)
select 'tutti', d, time '09:00', time '17:00' from generate_series(1, 5) as d;

-- ── Ricerche effettuate ──────────────────────────────────────
create table search_runs (
  id            uuid primary key default gen_random_uuid(),
  started_at    timestamptz not null default now(),
  finished_at   timestamptz,
  zone          text,
  query         text,
  results_count integer not null default 0,
  new_count     integer not null default 0,
  cost_eur      numeric(10, 4) not null default 0,
  status        text not null default 'in_corso' check (status in ('in_corso', 'completata', 'errore')),
  error         text
);

-- ── Strutture ────────────────────────────────────────────────
create table properties (
  id               uuid primary key default gen_random_uuid(),
  name             text not null,
  property_type    text,
  address          text,
  zone             text,
  latitude         double precision,
  longitude        double precision,
  cin              text,
  google_place_id  text,
  listing_urls     jsonb not null default '{}'::jsonb, -- {"booking": "...", "airbnb": "..."}
  website          text,
  phone            text,
  phone_normalized text,
  email            text,
  email_normalized text,
  ratings          jsonb not null default '{}'::jsonb, -- {"google": {"voto": 4.5, "recensioni": 120}}
  owner_type       text check (owner_type in ('privato', 'professionale')),
  analysis         jsonb,
  score            smallint check (score between 0 and 100),
  score_reasons    text[] not null default '{}',
  status           text not null default 'nuovo' check (status in (
                     'nuovo', 'analizzato', 'proposto', 'approvato', 'scartato', 'contattato', 'followup',
                     'richiamare', 'risposto', 'trattativa', 'cliente', 'perso', 'errore')),
  assigned_to      uuid references lead_finders(id) on delete set null,
  message_variant  text check (message_variant in ('A', 'B')),
  messages         jsonb not null default '{}'::jsonb,
  channel          text check (channel in ('whatsapp', 'email', 'telefono', 'visita')),
  contacted_at     timestamptz,
  next_followup_at timestamptz,
  callback_at      timestamptz,
  callback_exact   boolean not null default false,
  appointment_at   timestamptz,
  followup_count   smallint not null default 0,
  call_attempts    smallint not null default 0,
  notes            text,
  source           text not null default 'google_places' check (source in ('google_places', 'manuale', 'link_incollato')),
  search_run_id    uuid references search_runs(id) on delete set null,
  archived_at      timestamptz,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);
create trigger properties_updated_at before update on properties
  for each row execute function set_updated_at();
create unique index properties_google_place_id_key on properties (google_place_id) where google_place_id is not null;
create unique index properties_cin_key on properties (upper(cin)) where cin is not null;
create index properties_status_idx on properties (status) where archived_at is null;
create index properties_assigned_idx on properties (assigned_to) where archived_at is null;
create index properties_phone_idx on properties (phone_normalized) where phone_normalized is not null;
create index properties_email_idx on properties (email_normalized) where email_normalized is not null;

-- Storico di ogni struttura: chi, cosa, quando, da dove.
create table property_events (
  id          bigserial primary key,
  property_id uuid not null references properties(id) on delete cascade,
  actor_id    uuid references lead_finders(id) on delete set null,
  actor_label text not null,
  source      text not null check (source in ('telegram', 'gestionale', 'bot')),
  event_type  text not null,
  from_status text,
  to_status   text,
  details     jsonb not null default '{}'::jsonb,
  created_at  timestamptz not null default now()
);
create index property_events_property_idx on property_events (property_id, created_at desc);

-- Registro delle azioni di sistema (collegamenti, pausa, modalità, impostazioni).
create table audit_log (
  id          bigserial primary key,
  actor_id    uuid references lead_finders(id) on delete set null,
  actor_label text not null,
  source      text not null check (source in ('telegram', 'gestionale', 'bot')),
  action      text not null,
  details     jsonb not null default '{}'::jsonb,
  created_at  timestamptz not null default now()
);

-- Consumi dell'AI, per il tetto di spesa mensile.
create table ai_usage (
  id            bigserial primary key,
  created_at    timestamptz not null default now(),
  purpose       text not null,
  model         text not null,
  input_tokens  integer not null default 0,
  output_tokens integer not null default 0,
  cost_eur      numeric(10, 5) not null default 0,
  property_id   uuid references properties(id) on delete set null
);

-- Chi ha chiesto di non essere più contattato: non verrà mai riproposto.
create table opt_out (
  id               bigserial primary key,
  phone_normalized text,
  email_normalized text,
  reason           text,
  created_by       uuid references lead_finders(id) on delete set null,
  created_at       timestamptz not null default now(),
  check (phone_normalized is not null or email_normalized is not null)
);
create unique index opt_out_phone_key on opt_out (phone_normalized) where phone_normalized is not null;
create unique index opt_out_email_key on opt_out (email_normalized) where email_normalized is not null;

-- ── Sicurezza per righe su tutte le tabelle ──────────────────
alter table lead_finders    enable row level security;
alter table link_codes      enable row level security;
alter table finder_settings enable row level security;
alter table finder_state    enable row level security;
alter table call_windows    enable row level security;
alter table search_runs     enable row level security;
alter table properties      enable row level security;
alter table property_events enable row level security;
alter table audit_log       enable row level security;
alter table ai_usage        enable row level security;
alter table opt_out         enable row level security;
