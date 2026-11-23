-- ─────────────────────────────────────────────────────────────
-- CHECK-iO Lead Finder — radar per province e memoria storica
--
--  • Zone di due tipi: «cerchio» (comune + raggio, come prima) e «provincia».
--  • province: le 110 province ISTAT con le celle del radar (riempita da
--    20261124090100_province.sql, generata da scripts/build_geo.py).
--  • search_cells: memoria delle ricerche, cella per cella e ricerca per ricerca
--    (quando, quanti risultati, quante strutture nuove, eventuale riposo).
--  • property_fingerprints: impronte cifrate (SHA-256) di ogni struttura trovata
--    (scheda Google, CIN, telefono, email, nome+indirizzo). Una struttura già
--    trovata non torna mai come nuova, anche dopo che i suoi dati sono stati
--    cancellati per il periodo di conservazione: resta solo l'impronta.
--  • Consultazioni: chi ha guardato una struttura e quando.
-- ─────────────────────────────────────────────────────────────

-- ── Province e celle del radar ───────────────────────────────
create table public.province (
  codice         text primary key check (codice ~ '^[0-9]{3}$'),
  sigla          text not null,
  nome           text not null,
  regione_codice text not null check (regione_codice ~ '^[0-9]{2}$'),
  regione        text not null,
  lat            double precision not null,
  lng            double precision not null,
  celle          text[] not null default '{}'
);
create index province_regione_idx on public.province (regione_codice);
alter table public.province enable row level security;
grant select on public.province to authenticated;
create policy "province: lettura team" on public.province for select to authenticated
  using ((select private.is_member()));

-- ── Zone: cerchi e province ──────────────────────────────────
create or replace function private.json_num_between(v jsonb, lo numeric, hi numeric) returns boolean
language sql immutable set search_path = '' as $$
  select case when jsonb_typeof(v) = 'number' then (v #>> '{}')::numeric between lo and hi else false end
$$;

create or replace function private.valid_zones(zones jsonb) returns boolean
language sql immutable set search_path = '' as $$
  select jsonb_typeof(zones) = 'array'
    and jsonb_array_length(zones) <= 150
    and not exists (
      select 1 from jsonb_array_elements(zones) as z
      where jsonb_typeof(z) <> 'object'
         or coalesce(length(trim(z ->> 'nome')), 0) not between 1 and 80
         or (z ? 'attiva' and jsonb_typeof(z -> 'attiva') <> 'boolean')
         or coalesce(z ->> 'tipo', 'cerchio') not in ('cerchio', 'provincia')
         or (coalesce(z ->> 'tipo', 'cerchio') = 'cerchio' and not (
                  private.json_num_between(z -> 'lat', -90, 90)
              and private.json_num_between(z -> 'lng', -180, 180)
              and private.json_num_between(z -> 'raggio_km', 1, 100)))
         or (z ->> 'tipo' = 'provincia' and coalesce(z ->> 'codice', '') !~ '^[0-9]{3}$')
    )
$$;

-- ── Memoria delle ricerche (cella x ricerca) ─────────────────
create table public.search_cells (
  cell              text not null check (cell ~ '^-?[0-9]+_-?[0-9]+$'),
  query             text not null check (length(query) between 1 and 120),
  searches          integer not null default 0,
  results_total     integer not null default 0,
  new_total         integer not null default 0,
  last_results      integer not null default 0,
  last_new          integer not null default 0,
  empty_streak      smallint not null default 0,
  first_searched_at timestamptz not null default now(),
  last_searched_at  timestamptz not null default now(),
  rest_until        timestamptz,
  primary key (cell, query)
);
alter table public.search_cells enable row level security;
-- Lette dal gestionale solo tramite le funzioni del radar qui sotto.

-- ── Memoria delle strutture: impronte ────────────────────────
create table public.property_fingerprints (
  kind          text not null check (kind in ('google', 'cin', 'telefono', 'email', 'nome_indirizzo')),
  hash          text not null check (hash ~ '^[0-9a-f]{64}$'),
  property_id   uuid references public.properties(id) on delete set null,
  first_seen_at timestamptz not null default now(),
  last_seen_at  timestamptz not null default now(),
  times_seen    integer not null default 1,
  primary key (kind, hash)
);
create index property_fingerprints_property_idx on public.property_fingerprints (property_id);
alter table public.property_fingerprints enable row level security;
-- Nessun accesso dal web: le usa solo il bot dal server.

-- ── Strutture: dove sono state trovate e chi le ha consultate ─
alter table public.properties
  add column cell           text,
  add column provincia      text,
  add column search_query   text,
  add column times_seen     integer not null default 1,
  add column last_seen_at   timestamptz not null default now(),
  add column view_count     integer not null default 0,
  add column last_viewed_at timestamptz,
  add column last_viewed_by uuid references public.lead_finders(id) on delete set null;
create index properties_provincia_idx on public.properties (provincia);

-- ── Funzioni per il gestionale ───────────────────────────────

-- Segna una struttura come consultata (un evento all'ora per persona e struttura).
create or replace function public.segna_consultata(p_property uuid) returns void
language plpgsql security definer set search_path = '' as $$
declare
  me uuid := private.current_member_id();
  me_name text;
begin
  if not private.is_member() then
    raise exception 'Non autorizzato' using errcode = '42501';
  end if;
  if not exists (
    select 1 from public.properties p
    where p.id = p_property and (private.is_owner() or p.assigned_to = me)
  ) then
    raise exception 'Struttura non trovata' using errcode = 'P0002';
  end if;
  select name into me_name from public.lead_finders where id = me;
  update public.properties
     set last_viewed_at = now(), last_viewed_by = me, view_count = view_count + 1
   where id = p_property;
  if not exists (
    select 1 from public.property_events e
    where e.property_id = p_property and e.actor_id = me and e.event_type = 'consultata'
      and e.created_at > now() - interval '1 hour'
  ) then
    insert into public.property_events (property_id, actor_id, actor_label, source, event_type)
    values (p_property, me, me_name, 'gestionale', 'consultata');
  end if;
end;
$$;

-- Il titolare rimette una struttura nella ricerca: tornerà a essere proposta come nuova.
-- Mai per chi ha chiesto di non essere contattato.
create or replace function public.rimetti_in_ricerca(p_property uuid, p_motivo text default null) returns void
language plpgsql security definer set search_path = '' as $$
declare
  me uuid := private.current_member_id();
  me_name text;
  prop record;
begin
  if not private.is_owner() then
    raise exception 'Solo il titolare può rimettere una struttura nella ricerca' using errcode = '42501';
  end if;
  select id, status, phone_normalized, email_normalized into prop from public.properties where id = p_property;
  if prop.id is null then
    raise exception 'Struttura non trovata' using errcode = 'P0002';
  end if;
  if exists (
    select 1 from public.opt_out o
    where (prop.phone_normalized is not null and o.phone_normalized = prop.phone_normalized)
       or (prop.email_normalized is not null and o.email_normalized = prop.email_normalized)
  ) then
    raise exception 'Questa struttura ha chiesto di non essere contattata' using errcode = '23514';
  end if;
  select name into me_name from public.lead_finders where id = me;
  update public.properties
     set status = 'nuovo', archived_at = null, assigned_to = null, next_followup_at = null,
         callback_at = null, appointment_at = null, followup_count = 0, call_attempts = 0
   where id = p_property;
  insert into public.property_events (property_id, actor_id, actor_label, source, event_type, from_status, to_status, details)
  values (p_property, me, me_name, 'gestionale', 'rimessa_in_ricerca', prop.status, 'nuovo',
          jsonb_build_object('motivo', left(coalesce(p_motivo, ''), 300)));
end;
$$;

-- Copertura del radar per provincia (numeri, nessun dato personale).
create or replace function public.radar_province()
returns table (
  codice text, celle_totali integer, celle_esplorate integer, ricerche integer,
  ultima_ricerca timestamptz, strutture integer, nuove_30_giorni integer
)
language sql stable security definer set search_path = '' as $$
  with pc as (
    select p.codice, unnest(p.celle) as cell from public.province p
  ), celle as (
    select pc.codice,
           count(distinct sc.cell)::integer as esplorate,
           coalesce(sum(sc.searches), 0)::integer as ricerche,
           max(sc.last_searched_at) as ultima
    from pc join public.search_cells sc on sc.cell = pc.cell
    group by pc.codice
  ), strutture as (
    select provincia as codice, count(*)::integer as totale,
           (count(*) filter (where created_at > now() - interval '30 days'))::integer as nuove
    from public.properties where provincia is not null group by provincia
  )
  select p.codice, cardinality(p.celle), coalesce(c.esplorate, 0), coalesce(c.ricerche, 0), c.ultima,
         coalesce(s.totale, 0), coalesce(s.nuove, 0)
  from public.province p
  left join celle c on c.codice = p.codice
  left join strutture s on s.codice = p.codice
  where private.is_member()
$$;

-- Celle già esplorate in una regione (per colorarle sulla mappa).
create or replace function public.radar_celle(p_regione text)
returns table (cell text, ultima_ricerca timestamptz, ricerche integer, nuove integer, a_riposo boolean)
language sql stable security definer set search_path = '' as $$
  select sc.cell, max(sc.last_searched_at), sum(sc.searches)::integer, sum(sc.new_total)::integer,
         bool_and(sc.rest_until is not null and sc.rest_until > now())
  from public.search_cells sc
  where private.is_member()
    and sc.cell in (select unnest(p.celle) from public.province p where p.regione_codice = p_regione)
  group by sc.cell
$$;

-- Riepilogo della memoria.
create or replace function public.memoria_riepilogo()
returns table (strutture integer, impronte integer, consultate integer, celle_esplorate integer, ricerche integer, ultima_ricerca timestamptz)
language sql stable security definer set search_path = '' as $$
  select (select count(*) from public.properties)::integer,
         (select count(*) from public.property_fingerprints)::integer,
         (select count(*) from public.properties where view_count > 0)::integer,
         (select count(distinct cell) from public.search_cells)::integer,
         (select coalesce(sum(searches), 0) from public.search_cells)::integer,
         (select max(last_searched_at) from public.search_cells)
  where private.is_member()
$$;

-- Conservazione dei dati: cancella le strutture ferme da più mesi di quelli impostati
-- (tranne i clienti). Le impronte restano, così la struttura non viene riproposta.
-- La chiama il bot dal server una volta al giorno.
create or replace function public.pulisci_memoria() returns integer
language plpgsql security definer set search_path = '' as $$
declare
  months integer;
  removed integer;
begin
  select data_retention_months into months from public.finder_settings where id = 1;
  delete from public.properties
   where status <> 'cliente'
     and greatest(updated_at, coalesce(last_viewed_at, updated_at), last_seen_at) < now() - make_interval(months => months);
  get diagnostics removed = row_count;
  if removed > 0 then
    insert into public.audit_log (actor_label, source, action, details)
    values ('bot', 'bot', 'pulizia_memoria', jsonb_build_object('strutture_cancellate', removed, 'mesi', months));
  end if;
  return removed;
end;
$$;

revoke all on function public.segna_consultata(uuid), public.rimetti_in_ricerca(uuid, text),
  public.radar_province(), public.radar_celle(text), public.memoria_riepilogo(), public.pulisci_memoria()
  from public, anon;
grant execute on function public.segna_consultata(uuid), public.rimetti_in_ricerca(uuid, text),
  public.radar_province(), public.radar_celle(text), public.memoria_riepilogo()
  to authenticated;
revoke all on function public.pulisci_memoria() from authenticated;
-- json_num_between e valid_zones restano eseguibili: servono al controllo delle zone
-- quando il titolare salva dal gestionale.
